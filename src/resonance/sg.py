"""
SG — 信号生成模块 (Signal Generator)

依据 CPE 综合评分 + GKV 门控状态 → 生成交易信号。

核心逻辑:
  1. GKV 闸门封锁 → HOLD (NONE)
  2. GKV 闸门开放 → 按 CPE 评分映射信号类型和强度
  3. 评分阈值: STRONG > 0.8, MEDIUM > 0.6, WEAK > 0.4

信号映射表:
  ┌─────────────────┬────────────────┬──────────────────┐
  │ 条件              │ signal_type    │ signal_strength  │
  ├─────────────────┼────────────────┼──────────────────┤
  │ GKV 闸门封锁      │ HOLD           │ NONE             │
  │ CPE 评分 > 0.8   │ BUY            │ STRONG           │
  │ CPE 评分 > 0.6   │ BUY            │ MEDIUM           │
  │ CPE 评分 > 0.4   │ BUY            │ WEAK             │
  │ CPE 评分 ≤ 0.4   │ HOLD           │ NONE             │
  └─────────────────┴────────────────┴──────────────────┘

状态传播:
  - CPE 状态 = FAILED         → SG FAILED（无法评估）
  - CPE 状态 = SKIPPED        → SG SKIPPED（前置条件不足）
  - GKV 状态 = FAILED         → SG FAILED（门控异常）
  - CPE PASS + GKV PASS       → SG PASS（正常生成信号）

Usage:
    >>> from src.resonance.sg import generate
    >>> from src.resonance.models import CPEResult, GKVResult, ModuleStatus
    >>>
    >>> cpe = CPEResult(score=0.75, status=ModuleStatus.PASS,
    ...                 position_cap=1.0, reason="")
    >>> gkv = GKVResult(gated=False, passed=True, status=ModuleStatus.PASS,
    ...                 gate_open=True, rsm_state_ok=True, dsv_consistency_ok=True,
    ...                 liquidity_ok=True, rsm_state_value="ACTIVE",
    ...                 dsv_score=0.85, liquidity_score=0.72, signal_strength=0.75,
    ...                 reason="三闸门全开")
    >>>
    >>> result = generate("601857.SH", cpe, gkv)
    >>> result.signal_type
    'BUY'
    >>> result.signal_strength
    'MEDIUM'
    >>> result.status
    <ModuleStatus.PASS: 'PASS'>

依赖:
    - src.resonance.models: SGResult, CPEResult, GKVResult, ModuleStatus

Author: moheng
Created: 2026-05-29T12:21:00+08:00
"""

from __future__ import annotations

import logging

from src.resonance.models import (
    CPEResult,
    GKVResult,
    ModuleStatus,
    SGResult,
)

logger = logging.getLogger("resonance.sg")

# ══════════════════════════════════════════════════════════
# 评分阈值常量
# ══════════════════════════════════════════════════════════

_STRONG_THRESHOLD: float = 0.8
"""STRONG 信号评分下限。CPE 评分 > 0.8 → STRONG。"""

_MEDIUM_THRESHOLD: float = 0.6
"""MEDIUM 信号评分下限。CPE 评分 > 0.6 → MEDIUM。"""

_WEAK_THRESHOLD: float = 0.4
"""WEAK 信号评分下限。CPE 评分 > 0.4 → WEAK。"""


# ══════════════════════════════════════════════════════════
# 强度/类型映射函数
# ══════════════════════════════════════════════════════════


def _map_strength(score: float) -> str:
    """将 CPE 评分映射为信号强度级别。

    Args:
        score: CPE 综合评分 [0, 1]。

    Returns:
        str: 信号强度枚举值 'STRONG' | 'MEDIUM' | 'WEAK' | 'NONE'。

    映射规则:
      > 0.8 → STRONG
      > 0.6 → MEDIUM
      > 0.4 → WEAK
      ≤ 0.4 → NONE
    """
    if score > _STRONG_THRESHOLD:
        return "STRONG"
    if score > _MEDIUM_THRESHOLD:
        return "MEDIUM"
    if score > _WEAK_THRESHOLD:
        return "WEAK"
    return "NONE"


def _map_signal_type(gate_open: bool, score: float) -> str:
    """根据 GKV 门控状态和 CPE 评分确定信号类型。

    决策逻辑:
      - 闸门封锁 (gate_open=False) → HOLD
      - 闸门开放 + 评分 > 0.4     → BUY
      - 闸门开放 + 评分 ≤ 0.4     → HOLD（评分不足，不执行）

    Args:
        gate_open: GKV 门控是否开放（True=可放行）。
        score:     CPE 综合评分 [0, 1]。

    Returns:
        str: 信号类型 'BUY' | 'SELL' | 'HOLD'。
    """
    if not gate_open:
        return "HOLD"
    if score > _WEAK_THRESHOLD:
        return "BUY"
    return "HOLD"


# ══════════════════════════════════════════════════════════
# 主入口：generate
# ══════════════════════════════════════════════════════════


def generate(
    ticker: str,
    cpe_result: CPEResult,
    gkv_result: GKVResult,
) -> SGResult:
    """SG 信号生成主入口。

    依据 CPE 综合评分 + GKV 门控状态 → 生成交易信号。

    处理流程:
      1. 状态传播检查（CPE/GKV 的 FAILED/SKIPPED 状态处理）
      2. 获取 GKV 门控状态（gate_open）
      3. 映射信号类型和强度（_map_signal_type + _map_strength）
      4. 生成决策理由
      5. 构建并返回 SGResult

    Args:
        ticker:     标的代码，如 '601857.SH'。
                    仅用于日志追踪和结果标识。
        cpe_result: CPE 组合评估模块输出。
                    必须包含 score、status 等字段。
        gkv_result: GKV 门控核验模块输出。
                    必须包含 gated、passed、status 等字段。

    Returns:
        SGResult: 信号生成结果。
          - signal_type:     信号类型（BUY/SELL/HOLD）
          - signal_strength: 信号强度级别（STRONG/MEDIUM/WEAK/NONE）
          - score:           CPE 综合评分透传 [0, 1]
          - status:          模块执行状态（PASS/FAILED/SKIPPED）
          - ticker:          标的代码
          - reason:          决策理由（简洁文本）

    状态传播 —— 输入异常时的行为:
      ┌─────────────────────┬──────────┬──────────────────────────┐
      │ 输入状态             │ SG 状态  │ reason                    │
      ├─────────────────────┼──────────┼──────────────────────────┤
      │ CPE FAILED          │ FAILED   │ CPE 执行失败，无法生成信号 │
      │ GKV FAILED          │ FAILED   │ GKV 执行失败，无法生成信号 │
      │ CPE SKIPPED         │ SKIPPED  │ CPE 跳过执行，无法生成信号 │
      │ CPE PASS + GKV PASS │ PASS     │ 信号映射理由              │
      └─────────────────────┴──────────┴──────────────────────────┘

    Example:
        >>> from src.resonance.models import CPEResult, GKVResult, ModuleStatus
        >>>
        >>> cpe = CPEResult(score=0.75, status=ModuleStatus.PASS,
        ...                 position_cap=1.0, reason="RSM=0.75, DSV=0.85, Liq=0.72")
        >>> gkv = GKVResult(gated=False, passed=True, status=ModuleStatus.PASS,
        ...                 gate_open=True, rsm_state_ok=True, dsv_consistency_ok=True,
        ...                 liquidity_ok=True, rsm_state_value="ACTIVE",
        ...                 dsv_score=0.85, liquidity_score=0.72, signal_strength=0.75,
        ...                 reason="三闸门全开")
        >>>
        >>> result = generate("601857.SH", cpe, gkv)
        >>> result.signal_type
        'BUY'
        >>> result.signal_strength
        'MEDIUM'
        >>> result.score
        0.75
    """
    # ── Step 1: 状态传播检查 ──────────
    if cpe_result.status == ModuleStatus.FAILED:
        logger.error("SG [%s]: CPE 状态为 FAILED，信号生成失败", ticker)
        return SGResult(
            signal_type="HOLD",
            signal_strength="NONE",
            score=0.0,
            status=ModuleStatus.FAILED,
            ticker=ticker,
            reason="CPE 执行失败，无法生成信号",
        )

    if gkv_result.status == ModuleStatus.FAILED:
        logger.error("SG [%s]: GKV 状态为 FAILED，信号生成失败", ticker)
        return SGResult(
            signal_type="HOLD",
            signal_strength="NONE",
            score=0.0,
            status=ModuleStatus.FAILED,
            ticker=ticker,
            reason="GKV 执行失败，无法生成信号",
        )

    if cpe_result.status == ModuleStatus.SKIPPED:
        logger.warning("SG [%s]: CPE 状态为 SKIPPED，跳过信号生成", ticker)
        return SGResult(
            signal_type="HOLD",
            signal_strength="NONE",
            score=0.0,
            status=ModuleStatus.SKIPPED,
            ticker=ticker,
            reason="CPE 跳过执行，无法生成信号",
        )

    # ── Step 2: 获取 GKV 门控状态 ──────
    gate_open = (
        gkv_result.status == ModuleStatus.PASS
        and not gkv_result.gated
        and gkv_result.passed
    )

    # ── Step 3: 映射信号类型和强度 ─────
    score = cpe_result.score
    signal_type = _map_signal_type(gate_open, score)
    signal_strength = _map_strength(score) if gate_open else "NONE"

    # ── Step 4: 生成决策理由 ──────────
    if not gate_open:
        reason = (
            f"闸门封锁: RSM={gkv_result.rsm_state_value} "
            f"DSV={gkv_result.dsv_score:.2f} Liq={gkv_result.liquidity_score:.2f}"
        )
    else:
        strength_label = signal_strength
        cap_pct = cpe_result.position_cap * 100
        reason = (
            f"CPE评分={score:.4f} → {signal_type}/{strength_label} "
            f"(门控通过, 仓位上限={cap_pct:.0f}%)"
        )

    logger.info(
        "SG [%s]: signal=%s/%s score=%.4f gate_open=%s",
        ticker,
        signal_type,
        signal_strength,
        score,
        gate_open,
    )

    # ── Step 5: 构建结果 ──────────────
    return SGResult(
        signal_type=signal_type,
        signal_strength=signal_strength,
        score=round(score, 4),
        status=ModuleStatus.PASS,
        ticker=ticker,
        reason=reason,
    )


# ══════════════════════════════════════════════════════════
# 便捷生成接口
# ══════════════════════════════════════════════════════════


def generate_buy(
    ticker: str,
    score: float,
    position_cap: float = 1.0,
) -> SGResult:
    """便捷接口：生成 BUY 信号（当 CPE 和 GKV 结果已确认通过时）。

    用于测试、回测、或手动覆写场景。不经过完整的 CPE/GKV 检查流程，
    直接基于给定的评分生成 BUY 信号。

    Args:
        ticker:       标的代码。
        score:        信号评分 [0, 1]。
        position_cap: 仓位上限 [0, 1]（默认 1.0）。

    Returns:
        SGResult: BUY 信号结果。

    Example:
        >>> result = generate_buy("601857.SH", 0.75)
        >>> result.signal_type
        'BUY'
        >>> result.signal_strength
        'MEDIUM'
    """
    score = max(0.0, min(1.0, float(score)))
    signal_strength = _map_strength(score)

    logger.info(
        "SG [%s]: 便捷生成 BUY signal=%s score=%.4f cap=%.1f%%",
        ticker,
        signal_strength,
        score,
        position_cap * 100,
    )

    return SGResult(
        signal_type="BUY",
        signal_strength=signal_strength,
        score=round(score, 4),
        status=ModuleStatus.PASS,
        ticker=ticker,
        reason=(
            f"便捷生成BUY评分={score:.4f} → {signal_strength} "
            f"(仓位上限={position_cap:.0%})"
        ),
    )


def generate_hold(
    ticker: str,
    reason: str = "无交易信号",
) -> SGResult:
    """便捷接口：生成 HOLD 信号（当明确不需要交易时）。

    用于 GKV 封锁、评分不足等无需交易的场景。
    支持便捷调用，无需构造完整的 CPE/GKV 结果。

    Args:
        ticker: 标的代码。
        reason: 持有理由。

    Returns:
        SGResult: HOLD 信号结果。

    Example:
        >>> result = generate_hold("601857.SH", "流动性不足")
        >>> result.signal_type
        'HOLD'
    """
    return SGResult(
        signal_type="HOLD",
        signal_strength="NONE",
        score=0.0,
        status=ModuleStatus.PASS,
        ticker=ticker,
        reason=reason,
    )
