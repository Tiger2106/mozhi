"""
GKV — 门控核验模块 (Gate-Keeping Verification)

综合 RSM 状态 + DSV 一致性 + 流动性评分，执行三闸门核验，
决定是否放行交易信号。

核心规则（三闸门逻辑，全部通过才放行）：
  1. RSM 状态 >= WARN    — 共振至少达到预警级别
  2. DSV 一致性 > 0.7    — 双源校验强一致
  3. 流动性评分 > LIQUIDITY_MIN_THRESHOLD — 流动性充足

任何一闸未通过 → gate_open=False, gated=True → SG 不应生成交易信号。

Usage:
    >>> from src.resonance.gkv import compute, compute_gate
    >>> from src.resonance.models import RSMState, ModuleStatus, LQMResult, GKVResult
    >>> from src.resonance.dsv import DSVResult
    >>>
    >>> # 从 DSV 获取一致性评分（假设 dsv_result 已通过 DSV compute 获得）
    >>> dsv_score = 0.85
    >>> lqm = LQMResult(amplitude=1.5, volume_ratio=1.2, turnover_rate=0.8,
    ...                 liquidity_score=0.72, status=ModuleStatus.PASS)
    >>>
    >>> result = compute(
    ...     ticker="601857.SH",
    ...     rsm_state=RSMState.ACTIVE,
    ...     dsv_score=dsv_score,
    ...     lqm_result=lqm,
    ...     signal_strength=0.75,
    ... )
    >>> result.gate_open
    True
    >>> result.passed
    True
    >>> result.reason
    '三闸门全开: RSM=ACTIVE DSV=0.85 Liq=0.72'

依赖:
    - src.resonance.constants: LIQUIDITY_MIN_THRESHOLD, RESONANCE_MIN_STRENGTH
    - src.resonance.models: RSMState, ModuleStatus, LQMResult, GKVResult
    - src.resonance.dsv: DSVResult

Author: moheng
Created: 2026-05-29T11:09:00+08:00
"""

from __future__ import annotations

import logging
from typing import Optional

from src.resonance.constants import (
    LIQUIDITY_MIN_THRESHOLD,
)
from src.resonance.models import (
    GKVResult,
    LQMResult,
    ModuleStatus,
    RSMState,
)

logger = logging.getLogger("resonance.gkv")

# ══════════════════════════════════════════════════════════
# 门控核验参数
# ══════════════════════════════════════════════════════════

_DSV_CONSISTENCY_THRESHOLD: float = 0.7
"""DSV 一致性评分通过阈值。DSV 综合评分 > 0.7 表示双源信号方向强一致。

与 SG 模块共享此阈值判断。"""

_RSM_STATE_ORDER: dict = {
    RSMState.NONE: 0,
    RSMState.WARN: 1,
    RSMState.ACTIVE: 2,
    RSMState.DECAY: 3,
}
"""RSM 状态数值映射表，用于 >= WARN 比较。
数值越大表示共振越明确（或越持久）。
  NONE=0 < WARN=1 < ACTIVE=2 < DECAY=3
"""


# ══════════════════════════════════════════════════════════
# RSM 状态比较辅助
# ══════════════════════════════════════════════════════════


def _state_ge_warn(state: RSMState) -> bool:
    """检查 RSM 状态是否 >= WARN。

    边界判定：
      - RSMState.WARN    → True
      - RSMState.ACTIVE  → True
      - RSMState.DECAY   → True
      - RSMState.NONE    → False
      - 未知状态         → False（安全回归）

    Args:
        state: RSM 共振状态枚举值。

    Returns:
        bool: True 表示状态 >= WARN 级别。
    """
    level = _RSM_STATE_ORDER.get(state, -1)
    result = level >= 1  # WARN = 1
    if not result and state is not None:
        logger.debug("GKV: RSM 状态 %s 不满足 >= WARN", state)
    return result


# ══════════════════════════════════════════════════════════
# 输入前置校验
# ══════════════════════════════════════════════════════════


def _validate_inputs(
    ticker: str,
    rsm_state: Optional[RSMState],
    dsv_score: Optional[float],
    lqm_result: Optional[LQMResult],
    signal_strength: Optional[float],
) -> Optional[GKVResult]:
    """校验 GKV 输入参数完整性。

    当关键输入为空或不可用时返回 SKIPPED/FAILED 结果。
    校验逻辑：
      - rsm_state 为 None → SKIPPED（无共振状态，无法核验）
      - dsv_score 为 None → SKIPPED（无双源校验，保守封锁）
      - lqm_result 为 None 或非 PASS → 流动性降级模式
      - 其他异常 → FAILED

    Args:
        ticker:           标的代码（用于日志）。
        rsm_state:        当前 RSM 状态（可为 None）。
        dsv_score:        DSV 一致性评分（可为 None）。
        lqm_result:       LQM 结果（可为 None）。
        signal_strength:  信号强度（可为 None）。

    Returns:
        Optional[GKVResult]: 若输入不完整则返回 SKIPPED/FAILED 的
            快速结果；否则返回 None 表示可以继续执行核验。
    """
    if rsm_state is None:
        logger.warning("GKV [%s]: RSM 状态为 None，跳过门控核验", ticker)
        return GKVResult(
            gated=True,
            passed=False,
            reason="RSM 状态不可用，无法核验",
            status=ModuleStatus.SKIPPED,
            gate_open=False,
            rsm_state_ok=False,
            dsv_consistency_ok=False,
            liquidity_ok=False,
            rsm_state_value="NONE",
            dsv_score=0.0,
            liquidity_score=0.0,
            signal_strength=0.0,
        )

    if dsv_score is None:
        logger.warning("GKV [%s]: DSV 评分为 None，保守封锁信号", ticker)
        return GKVResult(
            gated=True,
            passed=False,
            reason="DSV 评分不可用，保守封锁",
            status=ModuleStatus.SKIPPED,
            gate_open=False,
            rsm_state_ok=_state_ge_warn(rsm_state),
            dsv_consistency_ok=False,
            liquidity_ok=False,
            rsm_state_value=rsm_state.value,
            dsv_score=0.0,
            liquidity_score=0.0,
            signal_strength=signal_strength or 0.0,
        )

    if signal_strength is None:
        logger.warning("GKV [%s]: signal_strength 为 None，默认为 0.0", ticker)
        signal_strength = 0.0

    return None  # 输入完整，可以继续


# ══════════════════════════════════════════════════════════
# 核心核验：compute_gate
# ══════════════════════════════════════════════════════════


def compute_gate(
    rsm_state: RSMState,
    dsv_score: float,
    liquidity_score: float,
    signal_strength: float,
    *,
    dsv_threshold: float = _DSV_CONSISTENCY_THRESHOLD,
    liquidity_threshold: float = LIQUIDITY_MIN_THRESHOLD,
) -> GKVResult:
    """执行三闸门核验，返回门控决策结果。

    三闸门判定逻辑：
      ┌────────────┬──────────────────────────────┬───────────────┐
      │ 闸门        │ 通过条件                      │ 不通过后果    │
      ├────────────┼──────────────────────────────┼───────────────┤
      │ 闸门1 (RSM) │ state >= WARN               │ 信号封锁       │
      │ 闸门2 (DSV) │ dsv_score > 0.7             │ 信号封锁       │
      │ 闸门3 (Liq) │ liquidity_score > 0.5       │ 信号封锁       │
      └────────────┴──────────────────────────────┴───────────────┘

    Args:
        rsm_state:         当前 RSM 共振状态。
        dsv_score:         DSV 双源校验一致性评分 [0, 1]。
        liquidity_score:   LQM 流动性评分 [0, 1]。
        signal_strength:   信号共振强度 [0, 1]（透传自 RSM）。
        dsv_threshold:     DSV 一致性通过阈值（默认 0.7）。
        liquidity_threshold: 流动性评分通过阈值（默认 LIQUIDITY_MIN_THRESHOLD）。

    Returns:
        GKVResult: 门控决策结果。
          - gate_open / passed:         全部通过=True
          - gated:                      任一未通过=True
          - rsm_state_ok:               闸门1 结果
          - dsv_consistency_ok:         闸门2 结果
          - liquidity_ok:               闸门3 结果
          - reason:                     简洁理由
          - status:                     PASS（核验完成）
    """
    # ── 闸门1: RSM 状态 >= WARN ──────────
    rsm_state_ok = _state_ge_warn(rsm_state)

    # ── 闸门2: DSV 一致性 > 阈值 ─────────
    dsv_consistency_ok = dsv_score > dsv_threshold

    # ── 闸门3: 流动性评分 > 阈值 ──────────
    liquidity_ok = liquidity_score > liquidity_threshold

    # ── 综合判定 ────────────────────────
    all_pass = rsm_state_ok and dsv_consistency_ok and liquidity_ok

    # ── 理由生成 ────────────────────────
    if all_pass:
        reason = (
            f"三闸门全开: RSM={rsm_state.value} "
            f"DSV={dsv_score:.2f} Liq={liquidity_score:.2f}"
        )
    else:
        # 按优先级报告未通过的原因
        failed_checks = []
        if not rsm_state_ok:
            failed_checks.append(f"RSM={rsm_state.value}")
        if not dsv_consistency_ok:
            failed_checks.append(f"DSV={dsv_score:.2f}")
        if not liquidity_ok:
            failed_checks.append(f"Liq={liquidity_score:.2f}")
        reason = f"闸门封锁: {'; '.join(failed_checks)}"

    logger.info(
        "GKV: %s (RSM=%s DSV=%.4f Liq=%.4f Str=%.4f)",
        "放行" if all_pass else "封锁",
        rsm_state.value,
        dsv_score,
        liquidity_score,
        signal_strength,
    )

    return GKVResult(
        gated=not all_pass,
        passed=all_pass,
        reason=reason,
        status=ModuleStatus.PASS,
        gate_open=all_pass,
        rsm_state_ok=rsm_state_ok,
        dsv_consistency_ok=dsv_consistency_ok,
        liquidity_ok=liquidity_ok,
        rsm_state_value=rsm_state.value,
        dsv_score=round(dsv_score, 4),
        liquidity_score=round(liquidity_score, 4),
        signal_strength=round(signal_strength, 4),
    )


# ══════════════════════════════════════════════════════════
# 主入口：compute
# ══════════════════════════════════════════════════════════


def compute(
    ticker: str,
    rsm_state: Optional[RSMState],
    dsv_score: Optional[float],
    lqm_result: Optional[LQMResult],
    signal_strength: Optional[float] = None,
    *,
    dsv_threshold: float = _DSV_CONSISTENCY_THRESHOLD,
    liquidity_threshold: float = LIQUIDITY_MIN_THRESHOLD,
) -> GKVResult:
    """GKV 门控核验主入口。

    完整执行流程：
      1. 输入完整性校验（rsm_state, dsv_score 等）
      2. 提取流动性评分（LQM→liquidity_score）
      3. 三闸门核验（compute_gate）
      4. 返回带详细字段的 GKVResult

    Args:
        ticker:             标的代码（如 '601857.SH'），用于日志追踪。
        rsm_state:          当前 RSM 共振状态。来自 RSM 模块。
                            为 None 时返回 SKIPPED。
        dsv_score:          DSV 双源校验一致性评分 [0, 1]。
                            来自 DSV 模块的 result.score。
                            为 None 时返回 SKIPPED（保守封锁）。
        lqm_result:         LQMResult 实例（可为 None）。
                            为 None 时 liquidity_score 默认为 0.0。
        signal_strength:    信号共振强度 [0, 1]。
                            来自 RSM 模块的 strength 计算。
                            为 None 时默认为 0.0。
        dsv_threshold:      DSV 一致性通过阈值（默认 0.7）。
        liquidity_threshold: 流动性评分通过阈值（默认 LIQUIDITY_MIN_THRESHOLD）。

    Returns:
        GKVResult: 门控核验结果。

    状态映射：
      ┌─────────────────────────────────┬────────┬────────┬──────────┐
      │ 输入条件                          │ status │ passed │ gated    │
      ├─────────────────────────────────┼────────┼────────┼──────────┤
      │ rsm_state=None                   │ SKIP   │ False  │ True     │
      │ dsv_score=None                   │ SKIP   │ False  │ True     │
      │ lqm_result=None / lqm 非 PASS    │ PASS   │ 按闸门 │ 按闸门   │
      │ 三闸门全通过                      │ PASS   │ True   │ False   │
      │ 任一闸门未通过                    │ PASS   │ False  │ True     │
      └─────────────────────────────────┴────────┴────────┴──────────┘

    Example:
        >>> from src.resonance.models import RSMState, ModuleStatus, LQMResult
        >>>
        >>> lqm = LQMResult(amplitude=1.2, volume_ratio=0.9, turnover_rate=0.5,
        ...                 liquidity_score=0.65, status=ModuleStatus.PASS)
        >>> result = compute("601857.SH", RSMState.ACTIVE, 0.85, lqm, 0.75)
        >>> result.gate_open
        True
        >>> result.gated
        False
    """
    # ── Step 1: 输入校验 ────────────────
    early_result = _validate_inputs(
        ticker, rsm_state, dsv_score, lqm_result, signal_strength,
    )
    if early_result is not None:
        return early_result

    # ── Step 2: 提取流动性评分 ──────────
    if lqm_result is not None and lqm_result.status == ModuleStatus.PASS:
        liquidity_score = float(lqm_result.liquidity_score)
    else:
        liquidity_score = 0.0
        logger.warning(
            "GKV [%s]: LQM 不可用 (status=%s)，流动性评分为 0.0",
            ticker,
            lqm_result.status if lqm_result is not None else "None",
        )

    # ── Step 3: 执行三闸门核验 ──────────
    result = compute_gate(
        rsm_state=rsm_state,          # type: ignore[arg-type]  # 已校验非 None
        dsv_score=dsv_score,          # type: ignore[arg-type]  # 已校验非 None
        liquidity_score=liquidity_score,
        signal_strength=signal_strength or 0.0,
        dsv_threshold=dsv_threshold,
        liquidity_threshold=liquidity_threshold,
    )

    logger.info(
        "GKV [%s]: gate_open=%s gated=%s passed=%s | "
        "RSM=%s DSV=%.4f Liq=%.4f Str=%.4f | %s",
        ticker,
        result.gate_open,
        result.gated,
        result.passed,
        result.rsm_state_value,
        result.dsv_score,
        result.liquidity_score,
        result.signal_strength,
        result.reason,
    )

    return result
