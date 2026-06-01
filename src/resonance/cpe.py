"""
CPE — 组合评估模块 (Combined Performance Evaluation)

实现两个核心功能：
  1. 综合评分（CPE Core）：融合 RSM强度 + DSV一致性 + 流动性评分 → 加权总分
  2. 条件放行判断（Conditional Pass）：基于连续共振日数和 DSV 验证结果判定仓位上限

综合评分权重（默认）：
  - RSM 强度: 0.5   (共振强度是信号的核心指标)
  - DSV 一致性: 0.3 (双源验证提供额外置信度)
  - LQM 流动性: 0.2 (流动性是交易执行的必要条件)

权重可覆写：通过 weights 关键字参数传入自定义权重字典。

评分封顶 [0, 1]，低于 0 截断为 0，高于 1 截断为 1。

条件放行逻辑：
  - 连续 CPE_CONTINUOUS_DAYS (5) 日共振强度 > RESONANCE_MIN_STRENGTH (0.6)
    AND DSV 双源验证通过 (passed == True)
    → CONDITIONAL_PASS (仓位 ≤ 50%)
  - 否则 → FULL_PASS (正常仓位，受其他约束限制)
  - DSV partial=True 时自动降为 FULL_PASS

状态处理：
  - PASS:   正常完成评估
  - FAILED: 关键输入无效（空值或异常）
  - SKIPPED: 前置未满足（如数据不足跳过评估）

Usage:
    >>> from src.resonance.cpe import compute, compute_weighted_score
    >>>
    >>> # 基础综合评分
    >>> result = compute(
    ...     ticker="601857.SH",
    ...     rsm_strength=0.75,
    ...     dsv_score=0.85,
    ...     liquidity_score=0.72,
    ... )
    >>> result.score
    0.759
    >>> result.status
    <ModuleStatus.PASS: 'PASS'>

    >>> # 带条件放行判断
    >>> result = compute(
    ...     ticker="601857.SH",
    ...     rsm_strength=0.75,
    ...     dsv_score=0.85,
    ...     liquidity_score=0.72,
    ...     resonance_history=[
    ...         {"strength": 0.68, "dsv_passed": True, "date": "20260528"},
    ...         {"strength": 0.72, "dsv_passed": True, "date": "20260527"},
    ...     ],
    ... )
    >>> result.continuous_days
    3

    >>> # 覆写权重
    >>> result = compute(
    ...     ticker="601857.SH",
    ...     rsm_strength=0.75,
    ...     dsv_score=0.85,
    ...     liquidity_score=0.72,
    ...     weights={"rsm": 0.6, "dsv": 0.3, "liq": 0.1},
    ... )
    >>> result.rsm_weight == 0.6
    True

    >>> # 部分输入（降级模式）
    >>> result = compute(
    ...     ticker="601857.SH",
    ...     rsm_strength=0.75,
    ...     dsv_score=None,
    ...     liquidity_score=0.72,
    ... )
    >>> result.status
    <ModuleStatus.PASS: 'PASS'>

依赖:
    - src.resonance.constants: RESONANCE_MIN_STRENGTH, CPE_CONTINUOUS_DAYS,
      CONDITIONAL_PASS_POSITION_CAP, FULL_PASS_CAP
    - src.resonance.models: CPEResult, ModuleStatus

Author: moheng
Created: 2026-05-29T11:22:00+08:00
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from src.resonance.constants import (
    CONDITIONAL_PASS_POSITION_CAP,
    CPE_CONTINUOUS_DAYS,
    FULL_PASS_CAP,
    RESONANCE_MIN_STRENGTH,
)
from src.resonance.models import CPEResult, ModuleStatus

logger = logging.getLogger("resonance.cpe")

# ══════════════════════════════════════════════════════════
# 默认权重
# ══════════════════════════════════════════════════════════

_DEFAULT_RSM_WEIGHT: float = 0.5
"""RSM 强度默认权重。"""

_DEFAULT_DSV_WEIGHT: float = 0.3
"""DSV 一致性默认权重。"""

_DEFAULT_LIQ_WEIGHT: float = 0.2
"""流动性评分默认权重。"""

_WEIGHT_EPSILON: float = 1e-10
"""权重归一化容差。"""


# ══════════════════════════════════════════════════════════
# 综合评分函数
# ══════════════════════════════════════════════════════════


def compute_weighted_score(
    rsm_strength: Optional[float] = None,
    dsv_score: Optional[float] = None,
    liquidity_score: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """计算加权综合评分。

    融合 RSM 强度、DSV 一致性和流动性评分为单一综合分数。
    支持部分输入降级：当某维度为 None 时，其权重按比例分配到其余可用维度。
    所有维度均为 None 时返回 score=0.0，调用方需处理 SKIPPED 状态。

    Args:
        rsm_strength:   RSM 共振强度 [0, 1]，None 表示该维度不可用。
        dsv_score:      DSV 双源验证一致性得分 [0, 1]，None 表示不可用。
        liquidity_score: LQM 流动性评分 [0, 1]，None 表示不可用。
        weights:        权重覆写字典。
                        可选键: 'rsm', 'dsv', 'liq'。
                        省略的键将使用默认值。
                        例: {"rsm": 0.6, "dsv": 0.3, "liq": 0.1}

    Returns:
        包含 score, rsm_weight, dsv_weight, liq_weight 的字典。
        score 已封顶 [0, 1]。

    Raises:
        ValueError: 权重和为 0 或包含负值。
    """
    # 解析权重
    rsm_w = _DEFAULT_RSM_WEIGHT
    dsv_w = _DEFAULT_DSV_WEIGHT
    liq_w = _DEFAULT_LIQ_WEIGHT

    if weights is not None:
        rsm_w = weights.get("rsm", rsm_w)
        dsv_w = weights.get("dsv", dsv_w)
        liq_w = weights.get("liq", liq_w)

    # 权重验证
    if rsm_w < 0 or dsv_w < 0 or liq_w < 0:
        raise ValueError(
            f"权重不能为负，当前: rsm={rsm_w}, dsv={dsv_w}, liq={liq_w}"
        )

    # 检查可用维度
    rsm_avail = rsm_strength is not None
    dsv_avail = dsv_score is not None
    liq_avail = liquidity_score is not None

    if not (rsm_avail or dsv_avail or liq_avail):
        # 全部不可用，返回零分
        return {
            "score": 0.0,
            "rsm_weight": rsm_w,
            "dsv_weight": dsv_w,
            "liq_weight": liq_w,
        }

    # 重归一化：将不可用维度的权重按比例分配给可用维度
    avail_weights = []
    if rsm_avail:
        avail_weights.append(rsm_w)
    if dsv_avail:
        avail_weights.append(dsv_w)
    if liq_avail:
        avail_weights.append(liq_w)

    total_avail = sum(avail_weights)
    if total_avail <= _WEIGHT_EPSILON:
        raise ValueError("可用维度权重和必须为正数")

    scale = 1.0 / total_avail
    rsm_w_actual = rsm_w * scale if rsm_avail else 0.0
    dsv_w_actual = dsv_w * scale if dsv_avail else 0.0
    liq_w_actual = liq_w * scale if liq_avail else 0.0

    # 综合评分
    score = 0.0
    if rsm_avail:
        score += float(rsm_strength) * rsm_w_actual  # type: ignore[arg-type]
    if dsv_avail:
        score += float(dsv_score) * dsv_w_actual  # type: ignore[arg-type]
    if liq_avail:
        score += float(liquidity_score) * liq_w_actual  # type: ignore[arg-type]

    # 评分封顶 [0, 1]
    score = max(0.0, min(1.0, score))

    return {
        "score": round(score, 4),
        "rsm_weight": round(rsm_w_actual, 6),
        "dsv_weight": round(dsv_w_actual, 6),
        "liq_weight": round(liq_w_actual, 6),
    }


# ══════════════════════════════════════════════════════════
# 条件放行判断函数
# ══════════════════════════════════════════════════════════


def check_conditional_pass(
    resonance_history: List[Dict[str, Any]],
    current_strength: float,
    current_dsv_passed: bool,
    current_dsv_partial: bool,
) -> Dict[str, Any]:
    """检查是否满足 CONDITIONAL_PASS 条件。

    条件放行逻辑：
      1. 连续 CPE_CONTINUOUS_DAYS (5) 日共振强度 > RESONANCE_MIN_STRENGTH (0.6)
      2. 每日 DSV 双源验证通过 (passed == True)
      3. DSV partial=True → 自动降为 FULL_PASS，不可触发 CONDITIONAL_PASS

    Args:
        resonance_history: 历史共振记录列表，每项必须包含:
            - "strength":   float, 当日共振强度 [0, 1]
            - "dsv_passed": bool, 当日 DSV 验证是否通过
            按时间顺序，不要求严格排序（自动处理）。
        current_strength:   当日共振强度 [0, 1]。
        current_dsv_passed: 当日 DSV 验证是否通过。
        current_dsv_partial:当日 DSV 是否处于 partial 模式。

    Returns:
        包含 continuous_days, conditional_pass, days_remaining 的字典。
    """
    # DSV partial=True → 不可触发 CONDITIONAL_PASS
    if current_dsv_partial:
        return {
            "continuous_days": 0,
            "conditional_pass": False,
            "days_remaining": CPE_CONTINUOUS_DAYS,
        }

    # 统计连续达标天数（含当日）
    continuous_days = 0

    # 检查当日
    if current_strength >= RESONANCE_MIN_STRENGTH and current_dsv_passed:
        continuous_days = 1
    else:
        return {
            "continuous_days": 0,
            "conditional_pass": False,
            "days_remaining": CPE_CONTINUOUS_DAYS,
        }

    # 已经达标
    if continuous_days >= CPE_CONTINUOUS_DAYS:
        return {
            "continuous_days": continuous_days,
            "conditional_pass": True,
            "days_remaining": 0,
        }

    # 按时间从近到远遍历历史
    sorted_history = list(resonance_history)

    # 自动排序：如果有 date 字段且第一项日期旧于末项则反转
    if len(sorted_history) >= 2:
        try:
            d0 = str(sorted_history[0].get("date", ""))
            dn = str(sorted_history[-1].get("date", ""))
            if d0 and dn and d0 < dn:
                sorted_history.reverse()
        except (ValueError, TypeError):
            pass

    for entry in sorted_history:
        if continuous_days >= CPE_CONTINUOUS_DAYS:
            break

        strength = entry.get("strength", 0.0)
        dsv_passed = entry.get("dsv_passed", False)

        if not isinstance(strength, (int, float)):
            break
        if not isinstance(dsv_passed, bool):
            break

        if strength >= RESONANCE_MIN_STRENGTH and dsv_passed:
            continuous_days += 1
        else:
            break

    conditional_pass = continuous_days >= CPE_CONTINUOUS_DAYS
    days_remaining = max(0, CPE_CONTINUOUS_DAYS - continuous_days)

    return {
        "continuous_days": continuous_days,
        "conditional_pass": conditional_pass,
        "days_remaining": days_remaining,
    }


# ══════════════════════════════════════════════════════════
# 数值验证
# ══════════════════════════════════════════════════════════


def _validate_numeric(
    value: Any,
    name: str,
    ticker: str,
) -> bool:
    """验证数值是否有效（非 NaN、非 Inf）。"""
    if value is None:
        return True  # None 是合法的缺失标记，由调用方处理降级
    if not isinstance(value, (int, float)):
        logger.error("CPE [%s]: %s 类型无效: %s", ticker, name, type(value).__name__)
        return False
    if np.isnan(value) or np.isinf(value):
        logger.error("CPE [%s]: %s 为 NaN 或 Inf", ticker, name)
        return False
    return True


# ══════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════


def compute(
    ticker: str,
    rsm_strength: Optional[float] = None,
    dsv_score: Optional[float] = None,
    liquidity_score: Optional[float] = None,
    dsv_passed: bool = True,
    dsv_partial: bool = False,
    resonance_history: Optional[List[Dict[str, Any]]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> CPEResult:
    """CPE 组合评估主入口。

    执行综合评分 + 条件放行判断，返回 CPEResult。

    状态判定逻辑：
      - rsm_strength / dsv_score / liquidity_score 全部为 None → SKIPPED
      - 任一数值为 NaN/Inf/无效 → FAILED
      - 权重配置不合法（负值、和为零） → FAILED
      - 正常执行 → PASS

    Args:
        ticker:           标的代码，如 '601857.SH'。
        rsm_strength:     RSM 共振强度 [0, 1]。
                          为 None 表示该维度不可用（降级模式）。
        dsv_score:        DSV 双源验证一致性得分 [0, 1]。
                          为 None 表示该维度不可用（降级模式）。
        liquidity_score:  LQM 流动性评分 [0, 1]。
                          为 None 表示该维度不可用（降级模式）。
        dsv_passed:       DSV 验证是否通过（默认 True）。
        dsv_partial:      DSV 是否处于 single_degraded 模式（默认 False）。
        resonance_history: 历史共振记录列表。
                           每项需含 "strength" (float) 和 "dsv_passed" (bool)。
                           按时间顺序，不要求严格排序（自动处理）。
                           省略时仅计算综合评分，不进行条件放行判断。
        weights:           权重覆写字典。
                           可选键: 'rsm', 'dsv', 'liq'。
                           例: {"rsm": 0.6, "dsv": 0.3, "liq": 0.1}

    Returns:
        CPEResult 实例。

    Raises:
        无异常抛出。所有异常状态通过 CPEResult.status 和 CPEResult.reason 返回。
    """
    # ── ticker 验证 ──
    if not ticker or not isinstance(ticker, str):
        logger.error("CPE: ticker 无效: %s", ticker)
        return CPEResult(
            score=0.0,
            continuous_days=0,
            conditional_pass=False,
            days_remaining=CPE_CONTINUOUS_DAYS,
            status=ModuleStatus.FAILED,
            reason=f"ticker 无效: {ticker}",
        )

    # ── 输入可用性检查 ──
    rsm_avail = rsm_strength is not None
    dsv_avail = dsv_score is not None
    liq_avail = liquidity_score is not None

    if not (rsm_avail or dsv_avail or liq_avail):
        logger.warning("CPE [%s]: 全部输入均为 None，返回 SKIPPED", ticker)
        return CPEResult(
            score=0.0,
            continuous_days=0,
            conditional_pass=False,
            days_remaining=CPE_CONTINUOUS_DAYS,
            status=ModuleStatus.SKIPPED,
            reason="全部输入均为 None",
        )

    # ── 数值验证 ──
    valid_rsm = _validate_numeric(rsm_strength, "rsm_strength", ticker)
    valid_dsv = _validate_numeric(dsv_score, "dsv_score", ticker)
    valid_liq = _validate_numeric(liquidity_score, "liquidity_score", ticker)

    if not (valid_rsm and valid_dsv and valid_liq):
        return CPEResult(
            score=0.0,
            continuous_days=0,
            conditional_pass=False,
            days_remaining=CPE_CONTINUOUS_DAYS,
            status=ModuleStatus.FAILED,
            reason="输入数值包含 NaN 或 Inf",
        )

    # ── 综合评分 ──
    try:
        score_result = compute_weighted_score(
            rsm_strength=rsm_strength,
            dsv_score=dsv_score,
            liquidity_score=liquidity_score,
            weights=weights,
        )
    except ValueError as e:
        logger.error("CPE [%s]: 权重配置错误: %s", ticker, e)
        return CPEResult(
            score=0.0,
            continuous_days=0,
            conditional_pass=False,
            days_remaining=CPE_CONTINUOUS_DAYS,
            status=ModuleStatus.FAILED,
            reason=f"权重错误: {e}",
        )

    score = score_result["score"]
    rsm_w = score_result["rsm_weight"]
    dsv_w = score_result["dsv_weight"]
    liq_w = score_result["liq_weight"]

    # ── 条件放行判断 ──
    cond_pass_result = {
        "continuous_days": 0,
        "conditional_pass": False,
        "days_remaining": CPE_CONTINUOUS_DAYS,
    }

    if resonance_history is not None and rsm_strength is not None:
        if not isinstance(resonance_history, list):
            logger.warning(
                "CPE [%s]: resonance_history 类型无效 (%s)，跳过条件放行判断",
                ticker, type(resonance_history).__name__,
            )
        else:
            cond_pass_result = check_conditional_pass(
                resonance_history=resonance_history,
                current_strength=rsm_strength,
                current_dsv_passed=dsv_passed,
                current_dsv_partial=dsv_partial,
            )

    continuous_days = cond_pass_result["continuous_days"]
    conditional_pass = cond_pass_result["conditional_pass"]
    days_remaining = cond_pass_result["days_remaining"]

    # ── 仓位上限 ──
    if conditional_pass and not dsv_partial:
        position_cap = CONDITIONAL_PASS_POSITION_CAP
    else:
        position_cap = FULL_PASS_CAP
        if conditional_pass and dsv_partial:
            conditional_pass = False  # partial=True 覆盖为 FULL_PASS

    # ── 理由说明 ──
    if conditional_pass:
        reason = (
            f"连续{continuous_days}日共振>{RESONANCE_MIN_STRENGTH} "
            f"+ DSV通过 → CONDITIONAL_PASS (仓位≤50%)"
        )
    else:
        rsm_str = f"RSM={rsm_strength:.2f}" if rsm_avail else "RSM=N/A"
        dsv_str = f"DSV={dsv_score:.2f}" if dsv_avail else "DSV=N/A"
        liq_str = f"Liq={liquidity_score:.2f}" if liq_avail else "Liq=N/A"
        reason = f"综合评分={score:.4f} ({rsm_str}, {dsv_str}, {liq_str})"

    # ── 构建结果 ──
    return CPEResult(
        score=score,
        rsm_weight=rsm_w,
        dsv_weight=dsv_w,
        liq_weight=liq_w,
        continuous_days=continuous_days,
        conditional_pass=conditional_pass,
        days_remaining=days_remaining,
        status=ModuleStatus.PASS,
        position_cap=position_cap,
        reason=reason,
    )
