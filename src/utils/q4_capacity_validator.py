# -*- coding: utf-8 -*-
"""
q4_capacity_validator.py — Q4 Capacity Validator 资金容量验证器

检测策略在**多资金规模级**下的边际收益衰减情况，评估可容纳的资金上限。

定位：
  Layer Q — Transverse Governance Layer（横向治理层）
  Q4 Capacity — 资金容量维度质量审计（Phase 2 补缺）

设计说明：
  - 当前无实盘资金流数据，使用**模拟方法**评估容量上限
  - 接口兼容 `existence_validator.py` 的 TradeRecord 数据结构
  - 模拟方法：基于 TradeRecord 的 pnl_pct 分布，假设容量增大导致收益衰减，
    在 1x / 2x / 5x / 10x 四个规模级别下评估边际收益变化
  - 衰减模型：假设每增加单位资金量，交易拥挤成本线性上升，
    pnl_pct 按衰减因子 scale_penalty = 1 - (scale_level - 1) * decay_per_step
  - decay_per_step 默认 0.05 表示每扩大 1x 资金，平均收益衰减 5%
  - 实际部署时建议替换为回测引擎的逐笔滑点模拟数据

输入：
  复用 existence_validator.py 的 TradeRecord（date, pnl_pct, regime）

输出：
  CapacityResult 包含通过/不通过、置信度、最大容量级别、失败原因

作者：墨衡 (moheng)
创建时间：2026-05-19 16:37 GMT+8
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.utils.existence_validator import TradeRecord


# ============================================================
# 常量
# ============================================================

_TZ_CST = timezone(timedelta(hours=8), "CST")

# 默认资金规模测试级别（相对基准资金量）
_DEFAULT_SCALE_LEVELS: list[float] = [1.0, 2.0, 5.0, 10.0]

# 每个规模级别的收益衰减因子（每扩大 1x 资金，收益衰减比例）
_DEFAULT_DECAY_PER_STEP: float = 0.05

# Sharpe 比率最低可接受阈值（夏普 < 此值视为容量超出）
_DEFAULT_MIN_SHARPE: float = 0.5

# 边际收益递减比例阈值（某级别相比 1x 基准收益下降超过此比例 → 容量超出）
_DEFAULT_MARGINAL_DECLINE_THRESHOLD: float = 0.30

# 置信度计算权重
_CONFIDENCE_SHARPE_WEIGHT: float = 0.40
_CONFIDENCE_MARGINAL_WEIGHT: float = 0.40
_CONFIDENCE_COVERAGE_WEIGHT: float = 0.20

# 年化因子（按 252 交易日）
_ANNUALIZATION_FACTOR: float = 252.0


# ============================================================
# 数据类型
# ============================================================

@dataclass
class CapacityLevelStats:
    """单个资金规模级别的容量统计"""
    scale: float                          # 资金倍数（如 1.0, 2.0, 5.0, 10.0）
    n_trades: int                         # 有效交易数
    mean_pnl: float                       # 调整后平均 pnl_pct
    sharpe: float                         # 年化夏普比率（基于 pnl_pct）
    total_pnl: float                      # 合计收益
    positive_ratio: float                 # 正向收益占比
    marginal_decay: float                 # 相比 1x 的边际收益衰减比例
    is_sustainable: bool                  # 该级别是否可持续

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "n_trades": self.n_trades,
            "mean_pnl": round(self.mean_pnl, 6),
            "sharpe": round(self.sharpe, 4),
            "total_pnl": round(self.total_pnl, 6),
            "positive_ratio": round(self.positive_ratio, 4),
            "marginal_decay": round(self.marginal_decay, 4),
            "is_sustainable": self.is_sustainable,
        }


@dataclass
class CapacityResult:
    """资金容量验证结果

    Attributes
    ----------
    is_capacity_ok : bool
        是否通过容量检查（至少 2x 级别可持续即为 OK）
    confidence : float
        置信度 (0.0 ~ 1.0)
    max_capacity_level : float
        推算的最大安全资金倍数（如 2.0、5.0、10.0）
    level_stats : list[CapacityLevelStats]
        各资金级别的详细统计
    fail_reason : str | None
        不通过时的原因说明
    details : dict
        详细辅助信息
    simulation_params : dict
        模拟参数说明
    """
    is_capacity_ok: bool
    confidence: float
    max_capacity_level: float
    level_stats: list[CapacityLevelStats]
    fail_reason: Optional[str]
    details: dict[str, Any]
    simulation_params: dict[str, Any]


# ============================================================
# 核心验证函数
# ============================================================

def _simulate_scale_pnl(
    trades: list[TradeRecord],
    scale: float,
    decay_per_step: float = _DEFAULT_DECAY_PER_STEP,
) -> list[float]:
    """模拟某一资金规模级别下调整后的 pnl_pct 序列

    模拟逻辑（无实盘资金流时的替代方案）：
      随着资金量增大，交易拥挤成本导致收益衰减。
      scale_penalty = 1 - (scale - 1) * decay_per_step
      调整后 pnl = 原始 pnl * max(scale_penalty, 0)

    Parameters
    ----------
    trades : list[TradeRecord]
        原始交易记录
    scale : float
        资金倍数（如 2.0 表示 2 倍基准资金）
    decay_per_step : float
        每扩大 1x 资金的收益衰减比例

    Returns
    -------
    list[float]
        调整后的 pnl_pct 序列
    """
    scale_penalty = max(1.0 - (scale - 1.0) * decay_per_step, 0.0)
    return [t.pnl_pct * scale_penalty for t in trades]


def _compute_sharpe(pnls: list[float]) -> float:
    """从 pnl_pct 序列计算年化夏普比率

    假设 pnl_pct 为单笔收益，年化 = mean/std * sqrt(252)
    """
    if len(pnls) < 2:
        return 0.0
    mean_pnl = statistics.mean(pnls)
    if len(pnls) < 2:
        return 0.0
    try:
        std_pnl = statistics.stdev(pnls)
    except statistics.StatisticsError:
        return 0.0
    if std_pnl == 0.0:
        # 全相同收益：若均为正 NaN → 极端情况返回高夏普；均为负返回低夏普
        return 2.0 if mean_pnl > 0 else -2.0
    daily_sharpe = mean_pnl / std_pnl
    return daily_sharpe * math.sqrt(_ANNUALIZATION_FACTOR)


def _estimate_max_capacity(
    level_stats: list[CapacityLevelStats],
    min_sharpe: float = _DEFAULT_MIN_SHARPE,
) -> tuple[float, str | None]:
    """从各级别统计推断最大安全资金倍数

    规则：
      1. 从低到高遍历
      2. 第一个 sharpe < min_sharpe 的上一级别为最大容量（若第一级就低于，返回 0）
      3. 全部通过则返回最大测试级别 + 警告标注

    Returns
    -------
    tuple[float, str | None]
        (max_capacity_level, fail_reason_or_None)
    """
    fail_reason: Optional[str] = None

    # 首先至少 1x 级别必须通过
    if not level_stats:
        return 0.0, "无资金级别统计数据"

    first = level_stats[0]
    if not first.is_sustainable:
        return 0.0, (
            f"基准资金级 (1x) 已不可持续：Sharpe {first.sharpe:.2f}"
            f" < 阈值 {min_sharpe}"
        )

    for i, stat in enumerate(level_stats):
        if not stat.is_sustainable:
            if i >= 1:
                max_level = level_stats[i - 1].scale
            else:
                max_level = 0.0
            fail_reason = (
                f"资金级 {stat.scale}x 不可持续：Sharpe {stat.sharpe:.2f}"
                f" < {min_sharpe}，边际衰减 {stat.marginal_decay:.1%}"
            )
            return max_level, fail_reason

    # 所有级别都通过
    max_level = level_stats[-1].scale
    fail_reason = None  # 正常通过
    return max_level, fail_reason


def validate_capacity(
    trades: list[TradeRecord],
    *,
    scale_levels: Optional[list[float]] = None,
    decay_per_step: float = _DEFAULT_DECAY_PER_STEP,
    min_sharpe: float = _DEFAULT_MIN_SHARPE,
    marginal_decline_threshold: float = _DEFAULT_MARGINAL_DECLINE_THRESHOLD,
) -> CapacityResult:
    """对交易/观测记录执行资金容量验证

    Parameters
    ----------
    trades : list[TradeRecord]
        交易记录列表
    scale_levels : list[float] | None
        资金规模测试级别。默认 [1.0, 2.0, 5.0, 10.0]
    decay_per_step : float
        每扩 1x 资金的收益衰减比例。默认 0.05（5%）
    min_sharpe : float
        夏普比率最低阈值。默认 0.5
    marginal_decline_threshold : float
        边际收益下降比例阈值（相比 1x）。默认 0.30（30%）

    Returns
    -------
    CapacityResult
    """
    if scale_levels is None:
        scale_levels = _DEFAULT_SCALE_LEVELS

    # 基准级别统计
    if not trades:
        return CapacityResult(
            is_capacity_ok=False,
            confidence=0.0,
            max_capacity_level=0.0,
            level_stats=[],
            fail_reason="无交易记录",
            details={},
            simulation_params={
                "decay_per_step": decay_per_step,
                "min_sharpe": min_sharpe,
                "scale_levels": scale_levels,
            },
        )

    baseline_pnls = _simulate_scale_pnl(trades, 1.0, decay_per_step)
    baseline_mean = statistics.mean(baseline_pnls)

    level_stats: list[CapacityLevelStats] = []

    for scale in scale_levels:
        scaled_pnls = _simulate_scale_pnl(trades, scale, decay_per_step)
        n = len(scaled_pnls)
        mean_pnl = statistics.mean(scaled_pnls)
        sharpe = _compute_sharpe(scaled_pnls)
        total_pnl = sum(scaled_pnls)
        pos_ratio = sum(1 for p in scaled_pnls if p > 0) / n

        # 边际收益衰减
        if abs(baseline_mean) > 1e-10:
            marginal_decay = (baseline_mean - mean_pnl) / abs(baseline_mean)
        else:
            marginal_decay = 0.0

        # 可持续判定：Sharpe 达标 + 边际衰减未超限
        is_sustainable = (
            sharpe >= min_sharpe
            and marginal_decay <= marginal_decline_threshold
        )

        level_stats.append(CapacityLevelStats(
            scale=scale,
            n_trades=n,
            mean_pnl=mean_pnl,
            sharpe=sharpe,
            total_pnl=total_pnl,
            positive_ratio=pos_ratio,
            marginal_decay=marginal_decay,
            is_sustainable=is_sustainable,
        ))

    # 计算最大安全容量
    max_capacity_level, fail_reason = _estimate_max_capacity(
        level_stats, min_sharpe
    )

    # 置信度计算
    n_sustainable = sum(1 for s in level_stats if s.is_sustainable)
    sharpe_score = min(level_stats[0].sharpe / max(min_sharpe, 1.0), 1.0) if level_stats else 0.0
    sharpe_score = max(min(sharpe_score, 1.0), 0.0)

    marginal_score = 1.0 - min(
        level_stats[-1].marginal_decay if level_stats else 1.0,
        1.0,
    )
    marginal_score = max(marginal_score, 0.0)

    coverage_score = n_sustainable / len(level_stats) if level_stats else 0.0

    confidence = (
        _CONFIDENCE_SHARPE_WEIGHT * sharpe_score
        + _CONFIDENCE_MARGINAL_WEIGHT * marginal_score
        + _CONFIDENCE_COVERAGE_WEIGHT * coverage_score
    )
    confidence = round(min(max(confidence, 0.0), 1.0), 4)

    # 通过判定：至少 2x 级别可持续
    is_capacity_ok = max_capacity_level >= 2.0

    details = {
        "n_trades": len(trades),
        "n_sustainable_levels": n_sustainable,
        "total_scale_levels": len(scale_levels),
        "baseline_mean_pnl": round(baseline_mean, 6),
        "min_sharpe_threshold": min_sharpe,
        "marginal_threshold": marginal_decline_threshold,
    }

    return CapacityResult(
        is_capacity_ok=is_capacity_ok,
        confidence=confidence,
        max_capacity_level=max_capacity_level,
        level_stats=level_stats,
        fail_reason=fail_reason,
        details=details,
        simulation_params={
            "decay_per_step": decay_per_step,
            "min_sharpe": min_sharpe,
            "marginal_decline_threshold": marginal_decline_threshold,
            "scale_levels": scale_levels,
            "note": (
                "当前使用模拟方法评估容量上限（无实盘资金流数据）。"
                "实际部署时建议替换为回测引擎的逐笔滑点模拟。"
            ),
        },
    )


# ============================================================
# 便捷统计导出
# ============================================================

def format_capacity_summary(result: CapacityResult) -> str:
    """格式化容量验证结果为可读字符串"""
    lines: list[str] = [
        "=" * 56,
        "  资金容量验证报告 (Q4 Capacity Validator)",
        "=" * 56,
        f"  容量检查:      {'✓ 通过' if result.is_capacity_ok else '✗ 不通过'}",
        f"  置信度:        {result.confidence:.1%}",
        f"  最大安全容量:  {result.max_capacity_level:.1f}x",
        f"  失败原因:      {result.fail_reason or '无'}",
        "=" * 56,
        "  各资金级别统计:",
        f"  {'级别':>6} | {'Sharpe':>8} | {'收益均值':>8} | {'衰减比例':>8} | {'可持续':>6}",
        "  " + "-" * 44,
    ]
    for s in result.level_stats:
        lines.append(
            f"  {s.scale:>4.0f}x | {s.sharpe:>8.2f} | {s.mean_pnl:>8.2f} | "
            f"{s.marginal_decay:>7.1%} | {'✓' if s.is_sustainable else '✗':>6}"
        )
    lines.extend([
        "=" * 56,
        "  模拟参数:",
        f"    衰减因子:   {result.simulation_params['decay_per_step']:.0%}/步",
        f"    夏普阈值:   {result.simulation_params['min_sharpe']}",
        f"    测试级别:   {result.simulation_params['scale_levels']}",
        f"    说明:       {result.simulation_params['note']}",
        "=" * 56,
    ])
    return "\n".join(lines)
