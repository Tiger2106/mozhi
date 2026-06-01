"""
DSV — 双源校验模块 (Dual-Source Verification)

接收 ZNM（z-score 归一化）输出的波动率 z-score 序列和 LQM（流动性评价）
输出的流动性数据，对两个数据源做信号方向一致性校验，为 GKV（门控验证）
和 CPE（条件放行）提供双源校验依据。

核心逻辑：
  1. 波动率维度一致性：ZNM vol_zscore 方向 vs 流动性信号方向（Spearman ρ）
  2. 流动性维度一致性：LQM volume_ratio/turnover_rate 内部方向一致性
  3. 综合判定：双维评分加权 → 双源校验 pass / partial / fail

校验规则：
  - 双源可用（vol_zscore 和 liquidity 均有有效数据）        → dual 模式
  - 仅一源可用                                             → single_degraded 模式
  - 均不可用                                               → SKIPPED
  - 有效数据点 < MIN_HISTORY_LENGTH                       → FAILED

Usage:
    >>> import numpy as np
    >>> from src.resonance.dsv import compute
    >>> from src.resonance.models import ModuleStatus, LQMResult
    >>> vol_zscore = np.array([0.5, 0.8, 1.2, 0.9, 0.6], dtype=np.float64)
    >>> lqm = LQMResult(amplitude=1.5, volume_ratio=1.2, turnover_rate=0.8,
    ...                 liquidity_score=0.72, status=ModuleStatus.PASS)
    >>> result = compute("601857.SH", vol_zscore, lqm)
    >>> result.status
    <ModuleStatus.PASS: 'PASS'>
    >>> isinstance(result.passed, bool)
    True
    >>> 0.0 <= result.score <= 1.0
    True

依赖:
    - src.resonance.constants: LOOKBACK_WINDOW, MIN_HISTORY_LENGTH
    - src.resonance.models: LQMResult, ModuleStatus

Author: moheng
Created: 2026-05-29T11:00:00+08:00
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
from numpy.typing import NDArray

from src.resonance.constants import (
    LOOKBACK_WINDOW,
    MIN_HISTORY_LENGTH,
)
from src.resonance.models import LQMResult, ModuleStatus

logger = logging.getLogger("resonance.dsv")

# ══════════════════════════════════════════════════════════
# 双源校验参数
# ══════════════════════════════════════════════════════════

_EPSILON: float = 1e-12
"""数值稳定性常数（避免除零）。"""

_SIGNAL_CORRELATION_THRESHOLD: float = 0.7
"""Spearman 相关系数的双源一致性阈值。
ρ > 0.7 表示两源信号方向高度一致。"""

_LIQUIDITY_SCORE_THRESHOLD: float = 0.3
"""LQM 流动性评分阈值（综合评分 < 此值表示流动性不足）。
用于 single_degraded 模式的降级评分计算。"""

_DEGRADED_BASE_SCORE: float = 0.5
"""单源降级模式的基础一致性评分。
当仅有一源可用时，以此值为基线叠加方向置信度。"""

_DEGRADED_SCORE_CAP: float = 0.7
"""单源降级模式的评分上限。
单源模式下最多获得 0.7 分（即使源数据表现很强）。"""

_MIN_DATA_POINTS: int = 3
"""Spearman 相关系数计算所需的最小数据点数。
少于 3 个点无法计算相关（n=2 时 Spearman ρ 恒为 ±1.0，有误导性）。"""


# ══════════════════════════════════════════════════════════
# DSVResult — 双源校验输出
# ══════════════════════════════════════════════════════════


@dataclass
class DSVResult:
    """双源校验模块输出。

    DSV 对波动率 z-score（来自 ZNM）和流动性数据（来自 LQM）
    做信号方向一致性校验，输出校验结论。

    Fields:
      passed                : 双源校验是否通过（score > 阈值且有效的双源/降级校验）。
      partial               : 是否处于单源降级模式（仅一源可用）。
      score                 : 综合一致性评分 [0, 1]。
                              双源模式：vol_consistency 和 liquidity_consistency 加权。
                              单源模式：降级评分 capped 至 0.7。
      vol_consistency      : 波动率维度一致性 [-1, 1]。
                              Spearman 相关系数。
      liquidity_consistency: 流动性维度一致性 [-0.5, 1.0]。
                              流动性内部指标（volume_ratio vs turnover_rate）的相关性。
      method               : 校验方法：'dual' | 'single_degraded'。
      status               : 模块执行状态：PASS | FAILED | SKIPPED。
      reason               : 校验结论的理由描述（50 字以内）。
    """

    passed: bool = False
    """双源校验是否通过。"""

    partial: bool = False
    """是否处于单源降级模式。"""

    score: float = 0.0
    """综合一致性评分 [0, 1]。"""

    vol_consistency: float = 0.0
    """波动率维度一致性 [-1, 1]。"""

    liquidity_consistency: float = 0.0
    """流动性维度一致性 [-0.5, 1.0]。"""

    method: str = "single_degraded"
    """校验方法：'dual' | 'single_degraded' | ''（SKIPPED 时置空）。"""

    status: ModuleStatus = ModuleStatus.SKIPPED
    """模块执行状态。"""

    reason: str = ""
    """校验结论理由。"""


# ══════════════════════════════════════════════════════════
# Spearman 秩相关系数（轻量实现）
# ══════════════════════════════════════════════════════════


def _spearman_rankcorr(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    """计算两个数组的 Spearman 秩相关系数（轻量实现，无外部依赖）。

    剔除 NaN 后对有效值分别求秩，然后计算 Pearson 相关系数。
    当数据点不足 3 个或一方标准差为零时返回 0.0。

    Args:
        a: 数组 A（浮点数）。
        b: 数组 B（浮点数），长度须与 a 相同。

    Returns:
        float: Spearman ρ ∈ [-1, 1]。
                - 有效点 < 3 时返回 0.0
                - 任一数组标准差为零时返回 0.0
                - 全部为 NaN 时返回 0.0
    """
    if a.size != b.size or a.size == 0:
        return 0.0

    # 剔除任一为 NaN 的位置
    mask = np.isfinite(a) & np.isfinite(b)
    valid_a = a[mask]
    valid_b = b[mask]

    n = valid_a.size
    if n < _MIN_DATA_POINTS:
        return 0.0

    # 检查标准差
    if np.std(valid_a) < _EPSILON or np.std(valid_b) < _EPSILON:
        return 0.0

    # 秩排序
    rank_a = _rank_data(valid_a)
    rank_b = _rank_data(valid_b)

    # Pearson 相关系数
    diff_a = rank_a - np.mean(rank_a)
    diff_b = rank_b - np.mean(rank_b)

    numerator = np.sum(diff_a * diff_b)
    denom = np.sqrt(np.sum(diff_a ** 2) * np.sum(diff_b ** 2))

    if denom < _EPSILON:
        return 0.0

    return float(numerator / denom)


def _rank_data(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """计算数组中各元素的平均秩（处理并列值）。

    Args:
        values: 一维浮点数数组。

    Returns:
        NDArray[np.float64]: 每个元素的平均秩。
    """
    n = len(values)
    # 排序索引
    sorter = np.argsort(values)
    # 为排序后每个位置分配秩（1-based）
    ranks = np.empty(n, dtype=np.float64)
    ranks[sorter] = np.arange(1, n + 1, dtype=np.float64)

    # 处理并列值：相同值的秩取平均值
    sorted_vals = values[sorter]
    i = 0
    while i < n:
        j = i
        while j < n and abs(sorted_vals[j] - sorted_vals[i]) < _EPSILON:
            j += 1
        if j - i > 1:  # 有并列
            avg_rank = np.mean(ranks[sorter[i:j]])
            ranks[sorter[i:j]] = avg_rank
        i = j

    return ranks


# ══════════════════════════════════════════════════════════
# convergence_check — 双源方向一致性校验
# ══════════════════════════════════════════════════════════


def convergence_check(
    vol_zscore_series: NDArray[np.float64],
    liquidity_scores: NDArray[np.float64],
    *,
    window: int = LOOKBACK_WINDOW,
    threshold: float = _SIGNAL_CORRELATION_THRESHOLD,
) -> Dict[str, Any]:
    """计算两个数据源的方向一致性校验结果。

    对 vol_zscore_series 和 liquidity_scores 做 Spearman 秩相关分析，
    判断两个数据源在滚动窗口内的信号方向是否一致。

    Args:
        vol_zscore_series: ZNM 输出的波动率 z-score 序列。
            按时间升序排列，最新值在后。
        liquidity_scores: LQM 的流动性评分序列（或截面数据对标）。
            按时间升序排列，最新值在后。
        window:  滚动窗口大小，默认 ``LOOKBACK_WINDOW``（20）。
        threshold: Spearman ρ 的通过阈值，默认 0.7。

    Returns:
        Dict[str, Any]:
            consistency: 双源方向一致性评分 [0, 1]。
                         = (ρ + 1) / 2 将 [-1, 1] 映射到 [0, 1]。
            correlation: Spearman ρ 原始值 [-1, 1]。
            p_value:     p 值的简化代理（非严格统计），
                         基于有效数据点数估算：min(1.0, 1.0 / sqrt(n))。
            n_valid:     参与计算的有效数据点数。
            threshold:   使用的阈值。
            passed:      correlation > threshold 且 n_valid >= MIN_DATA_POINTS。
    """
    # ── 数据剪裁到窗口大小 ──────────
    effective_vol = vol_zscore_series[-window:] if vol_zscore_series.size > window else vol_zscore_series
    effective_liq = liquidity_scores[-window:] if liquidity_scores.size > window else liquidity_scores

    # ── 对齐长度 ──
    n_min = min(effective_vol.size, effective_liq.size)
    if n_min == 0:
        return {
            "consistency": 0.0,
            "correlation": 0.0,
            "p_value": 1.0,
            "n_valid": 0,
            "threshold": threshold,
            "passed": False,
        }

    vol_slice = effective_vol[-n_min:]
    liq_slice = effective_liq[-n_min:]

    # ── Spearman 相关系数 ────────────
    rho = _spearman_rankcorr(vol_slice, liq_slice)

    # ── 有效数据点数（剔除 NaN 后） ──
    mask = np.isfinite(vol_slice) & np.isfinite(liq_slice)
    n_valid = int(np.sum(mask))

    # ── 一致性评分 [0, 1] ──────────
    # ρ ∈ [-1, 1] → consistency ∈ [0, 1]
    consistency = (rho + 1.0) / 2.0

    # ── p 值代理估算 ─────────────────
    p_value = min(1.0, 1.0 / (n_valid ** 0.5)) if n_valid >= _MIN_DATA_POINTS else 1.0

    # ── 通过判定 ────────────────────
    passed = bool(rho > threshold) and n_valid >= _MIN_DATA_POINTS

    logger.debug(
        "DSV convergence: ρ=%.4f, consistency=%.4f, n_valid=%d, passed=%s",
        rho, consistency, n_valid, passed,
    )

    return {
        "consistency": round(consistency, 4),
        "correlation": round(rho, 4),
        "p_value": round(p_value, 4),
        "n_valid": n_valid,
        "threshold": threshold,
        "passed": passed,
    }


# ══════════════════════════════════════════════════════════
# 流动性方向一致性
# ══════════════════════════════════════════════════════════


def _liquidity_consistency(lqm_result: LQMResult) -> float:
    """评估 LQM 流动性内部指标的方向一致性。

    检查 volume_ratio 和 liquidity_score 的方向一致性。
    - volume_ratio > 1.0 且 liquidity_score > 0.5 → 方向一致（积极）
    - volume_ratio < 1.0 且 liquidity_score < 0.5 → 方向一致（消极）
    - 其他 → 方向不一致

    返回 [-0.5, 1.0] 范围的方向一致性评分。

    Args:
        lqm_result: LQMResult 实例。

    Returns:
        float: 流动性方向一致性 [-0.5, 1.0]。
            若 volume_ratio 或 liquidity_score 非有限数值，返回 0.0。
            volume_ratio 和 liquidity_score 高置信度同向 → +1.0
            两者均低（一致消极）→ +0.5
            方向矛盾 → -0.5 或 0.0（视偏离程度）
            无法评估 → 0.0（status 不为 PASS）。
    """
    if lqm_result.status != ModuleStatus.PASS:
        return 0.0

    # 数据完整性保护（_MIN_DATA_POINTS 最小数据量原则）
    if not np.isfinite(lqm_result.volume_ratio) or not np.isfinite(lqm_result.liquidity_score):
        logger.warning("DSV [liquidity_consistency]: volume_ratio 或 liquidity_score 为非有限值")
        return 0.0

    vol_high = lqm_result.volume_ratio > 1.0
    liq_high = lqm_result.liquidity_score > 0.5

    if vol_high and liq_high:
        # 高成交量 + 高评分 → 一致积极
        vol_magnitude = min(1.0, (lqm_result.volume_ratio - 1.0) / 2.0)
        liq_magnitude = lqm_result.liquidity_score
        return (vol_magnitude + liq_magnitude) / 2.0

    if not vol_high and not liq_high:
        # 低成交量 + 低评分 → 一致消极（但仍为方向一致）
        return 0.5

    # 方向矛盾
    return -0.5


# ══════════════════════════════════════════════════════════
# 主入口：compute
# ══════════════════════════════════════════════════════════


def compute(
    ticker: str,
    vol_zscore_series: NDArray[np.float64],
    lqm_result: Optional[LQMResult],
    *,
    window: int = LOOKBACK_WINDOW,
    threshold: float = _SIGNAL_CORRELATION_THRESHOLD,
) -> DSVResult:
    """执行双源校验（DSV 模块主入口）。

    处理流程：
      1. 校验输入数据完整性
      2. 提取波动率 z-score 序列和流动性数据
      3. 调用 ``convergence_check()`` 计算双源方向一致性
      4. 评估流动性内部方向一致性
      5. 综合评分 → 输出 DSVResult

    Args:
        ticker:            标的代码（如 ``'601857.SH'``），用于日志追踪。
        vol_zscore_series: ZNM 输出的波动率 z-score 序列。
                           按时间升序排列，最新值在后。
                           可传入 ZNMResult.normalized_values。
        lqm_result:        LQMResult 实例（可 None，此时使用 single_degraded 模式）。
        window:            滚动窗口大小（默认 ``LOOKBACK_WINDOW=20``）。
        threshold:         Spearman ρ 通过阈值（默认 0.7）。

    Returns:
        DSVResult:
          - passed:               校验是否通过
          - partial:              是否单源降级
          - score:                综合一致性评分 [0, 1]
          - vol_consistency:      波动率维度一致性 [-1, 1]
          - liquidity_consistency:流动性维度一致性 [-0.5, 1.0]
          - method:               'dual' | 'single_degraded' | ''
          - status:               PASS / FAILED / SKIPPED
          - reason:               判定理由

    状态判定逻辑：
      - vol_zscore_series 为空或全 NaN，且无 LQM → SKIPPED（双源均不可用）
      - vol_zscore_series 有效点 < MIN_HISTORY_LENGTH，且无 LQM → FAILED
      - 仅 vol_zscore_series 可用 → single_degraded 模式
      - 仅 LQM 可用 → single_degraded 模式
      - 双源均可用 → dual 模式（convergence_check + liquidity_consistency 联合）
    """
    # ── 前置校验 ──────────────────
    vol_available = _check_vol_availability(vol_zscore_series, window)
    liq_available = (lqm_result is not None and lqm_result.status == ModuleStatus.PASS)

    # ── 双源均不可用 → SKIPPED ────
    if not vol_available and not liq_available:
        logger.warning("DSV [%s]: 波动率和流动性数据均不可用，返回 SKIPPED", ticker)
        return DSVResult(
            passed=False,
            partial=False,
            score=0.0,
            vol_consistency=0.0,
            liquidity_consistency=0.0,
            method="",
            status=ModuleStatus.SKIPPED,
            reason="波动率和流动性数据均不可用",
        )

    # ── 单源降级模式 ──────────────
    if not vol_available or not liq_available:
        return _compute_single_degraded(ticker, vol_zscore_series, lqm_result, window, threshold)

    # ── 双源模式 ──────────────────
    return _compute_dual(ticker, vol_zscore_series, lqm_result, window, threshold)


# ══════════════════════════════════════════════════════════
# 内部函数
# ══════════════════════════════════════════════════════════


def _check_vol_availability(
    vol_zscore_series: NDArray[np.float64],
    min_effective: int,
) -> bool:
    """检查波动率 z-score 序列是否可用。

    可用条件：
      - 不为空
      - 不全为 NaN
      - 有效值 >= MIN_HISTORY_LENGTH

    Args:
        vol_zscore_series: ZNM 输出的波动率 z-score 序列。
        min_effective:     参与计算的最小有效数据点数。

    Returns:
        bool: True 表示可用。
    """
    if vol_zscore_series is None or vol_zscore_series.size == 0:
        return False
    if np.all(np.isnan(vol_zscore_series)):
        return False
    valid_count = int(np.sum(np.isfinite(vol_zscore_series)))
    return valid_count >= MIN_HISTORY_LENGTH


def _compute_single_degraded(
    ticker: str,
    vol_zscore_series: NDArray[np.float64],
    lqm_result: Optional[LQMResult],
    window: int,
    threshold: float,
) -> DSVResult:
    """单源降级双源校验。

    当仅有一源可用时：
      - 波动率单源：以 z-score 绝对值方向置信度计算评分
      - 流动性单源：以 LQM 流动性评分和 volume_ratio 计算评分
      - 评分封顶 0.7，基础分 0.5

    Args:
        ticker:            标的代码。
        vol_zscore_series: 波动率 z-score 序列（可能不可用）。
        lqm_result:        LQM 结果（可能为 None）。
        window:            滚动窗口大小。
        threshold:         通过阈值。

    Returns:
        DSVResult: 单源降级模式的校验结果。
    """
    if vol_zscore_series is not None and vol_zscore_series.size > 0:
        # 波动率单源
        valid_zscores = vol_zscore_series[np.isfinite(vol_zscore_series)]
        if valid_zscores.size >= MIN_HISTORY_LENGTH:
            latest_z = valid_zscores[-1]
            # 方向置信度：abs(z-score) 越大，> threshold 的概率越高
            # z > 0.5 表示正向信号置信，z < -0.5 表示负向信号置信
            direction_confidence = min(1.0, abs(latest_z) / 1.5)
            score = min(_DEGRADED_SCORE_CAP, _DEGRADED_BASE_SCORE + direction_confidence * 0.2)
            passed = score > 0.5

            vol_consistency = float(latest_z)
            liq_consistency = 0.0

            result = DSVResult(
                passed=passed,
                partial=True,
                score=round(score, 4),
                vol_consistency=round(vol_consistency, 4),
                liquidity_consistency=liq_consistency,
                method="single_degraded",
                status=ModuleStatus.PASS,
                reason=f"波动率单源降级: z={latest_z:.2f}, 评分={score:.2f}",
            )
            logger.info(
                "DSV [%s]: 单源降级(vol) z=%.4f score=%.4f passed=%s",
                ticker, latest_z, score, passed,
            )
            return result

    if lqm_result is not None and lqm_result.status == ModuleStatus.PASS:
        # 流动性单源
        liq_conf = _liquidity_consistency(lqm_result)
        score = min(_DEGRADED_SCORE_CAP, _DEGRADED_BASE_SCORE + abs(liq_conf) * 0.2)
        passed = score > 0.5

        result = DSVResult(
            passed=passed,
            partial=True,
            score=round(score, 4),
            vol_consistency=0.0,
            liquidity_consistency=round(liq_conf, 4),
            method="single_degraded",
            status=ModuleStatus.PASS,
            reason=f"流动性单源降级: 评分={score:.2f}",
        )
        logger.info(
            "DSV [%s]: 单源降级(liq) score=%.4f passed=%s",
            ticker, score, passed,
        )
        return result

    # 不应到达此处（前置已检查），但为了类型安全：
    logger.error("DSV [%s]: 单源降级逻辑异常——双源均不可用", ticker)
    return DSVResult(
        passed=False,
        partial=False,
        score=0.0,
        method="single_degraded",
        status=ModuleStatus.FAILED,
        reason="单源降级逻辑异常",
    )


def _compute_dual(
    ticker: str,
    vol_zscore_series: NDArray[np.float64],
    lqm_result: LQMResult,
    window: int,
    threshold: float,
) -> DSVResult:
    """双源双维双源校验。

    双维校验：
      1. 波动率维度：vol_zscore 序列 vs LQM volume_ratio 序列趋势一致性
      2. 流动性维度：LQM 内部（volume_ratio vs liquidity_score）方向一致性
      3. 综合评分 = 0.7 × vol_consistency + 0.3 × liquidity_consistency_mapped

    Args:
        ticker:            标的代码。
        vol_zscore_series: 波动率 z-score 序列。
        lqm_result:        LQMResult 实例（status == PASS）。
        window:            滚动窗口大小。
        threshold:         Spearman 通过阈值。

    Returns:
        DSVResult: 双源模式的校验结果。
    """
    # ── 检查 vol_zscore 有效数据量 ────
    valid_vol = vol_zscore_series[np.isfinite(vol_zscore_series)]
    if valid_vol.size < MIN_HISTORY_LENGTH:
        logger.error(
            "DSV [%s]: 波动率有效数据不足（有效 %d < 要求 %d），返回 FAILED",
            ticker, valid_vol.size, MIN_HISTORY_LENGTH,
        )
        return DSVResult(
            passed=False,
            partial=False,
            score=0.0,
            vol_consistency=0.0,
            liquidity_consistency=0.0,
            method="dual",
            status=ModuleStatus.FAILED,
            reason=f"波动率数据不足（有效 {valid_vol.size} < {MIN_HISTORY_LENGTH}）",
        )

    # ── 构建流动性评分序列 ─────────
    # 使用 LQM volume_ratio 作为流动性方向序列（与 vol_zscore 对比）
    # 与 vol_zscore_series 对齐长度
    liq_scores_array = _build_liquidity_series(lqm_result, window)

    # ── 波动率维度一致性（convergence_check） ──
    conv_result = convergence_check(
        vol_zscore_series, liq_scores_array,
        window=window, threshold=threshold,
    )
    vol_consistency_raw = conv_result["correlation"]  # [-1, 1]
    vol_consistency_mapped = conv_result["consistency"]  # [0, 1]

    # ── 流动性维度一致性 ────────────
    liq_consistency_raw = _liquidity_consistency(lqm_result)  # [-1, 1]
    liq_consistency_mapped = (liq_consistency_raw + 1.0) / 2.0  # [0, 1]

    # ── 综合评分 ───────────────────
    # 权重：波动率 0.7 (主维度) + 流动性 0.3 (辅维度)
    # 若无有效的 vol 一致性（n_valid < MIN_DATA_POINTS），则降级为单源
    if conv_result["n_valid"] < _MIN_DATA_POINTS:
        # 退化为以流动性为主
        score = liq_consistency_mapped
        logger.info(
            "DSV [%s]: 波动率一致性数据不足(n_valid=%d)，以流动性为主，score=%.4f",
            ticker, conv_result["n_valid"], score,
        )
    else:
        score = 0.7 * vol_consistency_mapped + 0.3 * liq_consistency_mapped

    # ── 阈值判定 ───────────────────
    passed = score > threshold
    partial = False  # 双源模式不设 partial

    result = DSVResult(
        passed=passed,
        partial=partial,
        score=round(score, 4),
        vol_consistency=round(vol_consistency_raw, 4),
        liquidity_consistency=round(liq_consistency_raw, 4),
        method="dual",
        status=ModuleStatus.PASS,
        reason=(
            f"双源校验: vol_corr={vol_consistency_raw:.2f}, "
            f"liq_consistency={liq_consistency_raw:.2f}, "
            f"score={score:.2f}"
        ),
    )

    logger.info(
        "DSV [%s]: 双源校验 ρ=%.4f liq=%.4f score=%.4f passed=%s",
        ticker, vol_consistency_raw, liq_consistency_raw, score, passed,
    )
    return result


def _build_liquidity_series(
    lqm_result: LQMResult,
    max_length: int,
) -> NDArray[np.float64]:
    """从 LQMResult 构建流动性评分序列。

    当前 Phase 0 单日 LQM 输出为截面数据（单点值）。
    为匹配 vol_zscore_series 的长度，以 volume_ratio 为基准
    构建等长序列（若 LQM 仅有单日值，则用当前值填充短序列）。

    后续 Phase 1+ 将支持历史流动性序列。

    Args:
        lqm_result: LQMResult 实例。
        max_length: 目标序列最大长度（匹配 vol_zscore 窗口）。

    Returns:
        NDArray[np.float64]: 流动性评分序列。
    """
    # 使用 LQM volume_ratio 作为单一流动性指标
    vol_ratio = lqm_result.volume_ratio if np.isfinite(lqm_result.volume_ratio) else 1.0
    # 构建等长系列（当前只有单点值，但为收敛计算做等长填充）
    series = np.full(max_length, vol_ratio, dtype=np.float64)
    return series
