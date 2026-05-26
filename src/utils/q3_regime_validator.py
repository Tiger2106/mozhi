# -*- coding: utf-8 -*-
"""
q3_regime_validator.py — Q3 Regime Validator 市场状态适配验证器

验证策略/因子的表现是否集中在单一市场状态，或能否在 ≥2 种市场状态下
获得正收益。

Regime 标准命名（与 backtest_system_reform_20260519.md §1.4 协议对齐）：
  TREND_UP     — 上涨趋势（UPTREND / bullish）
  TREND_DOWN   — 下跌趋势（DOWNTREND / bearish）
  SIDEWAYS     — 横盘震荡（RANGE / oscillation）
  HIGH_VOL     — 高波动（BREAKOUT / CLIMAX / high volatility periods）
  LOW_VOL      — 低波动（low volatility oscillation）

数据输入方式：
  ① TradeRecord + regime 标签的直接列表（回测结果解析后的逐笔交易）
  ② 按 regime 聚合的分层绩效指标（regime → Sharpe / WinRate / Return）

设计说明：
  - 兼容 existing regime_analyzer 的 5 状态输出：UPTREND/DOWNTREND/RANGE/BREAKOUT/CLIMAX
  - 提供标准命名映射函数 map_regime_name()
  - ≥2 regime 正收益 = 最低通过标准
  - 支持逐笔交易分析和按 Regime 聚合分析两种模式

作者：墨衡 (moheng)
创建时间：2026-05-19 16:20 GMT+8
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")


# ============================================================
# Regime 标准命名
# ============================================================

class RegimeName(str, enum.Enum):
    """标准 Regime 命名（5 状态对齐协议）"""
    TREND_UP   = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    SIDEWAYS   = "SIDEWAYS"
    HIGH_VOL   = "HIGH_VOL"
    LOW_VOL    = "LOW_VOL"
    UNKNOWN    = "UNKNOWN"

    @classmethod
    def _missing_(cls, value: object) -> "RegimeName":
        """处理未知值：UNKNOWN 兜底"""
        return cls.UNKNOWN


# ============================================================
# Regime 名称映射
# ============================================================

# 已知来源系统 → 标准命名映射表
_REGIME_MAP: dict[str, str] = {
    # regime_factor.py (UPTREND/DOWNTREND/RANGE/BREAKOUT/CLIMAX)
    "UPTREND":    "TREND_UP",
    "DOWNTREND":  "TREND_DOWN",
    "RANGE":      "SIDEWAYS",
    "BREAKOUT":   "HIGH_VOL",
    "CLIMAX":     "HIGH_VOL",
    # 其他可能的输入
    "TREND_UP":                "TREND_UP",
    "TREND_DOWN":              "TREND_DOWN",
    "SIDEWAYS":                "SIDEWAYS",
    "HIGH_VOL":                "HIGH_VOL",
    "LOW_VOL":                 "LOW_VOL",
    "OSCILLATION_LOWVOL":      "LOW_VOL",
    "OSCILLATION_HIGHVOL":     "HIGH_VOL",
    "OSCILLATION":             "LOW_VOL",
    "BULLISH":                 "TREND_UP",
    "BEARISH":                 "TREND_DOWN",
    "SIDEWAY":                 "SIDEWAYS",
    "RANGING":                 "SIDEWAYS",
    "HIGH_VOLATILITY":         "HIGH_VOL",
    "LOW_VOLATILITY":          "LOW_VOL",
    "BREAKING_OUT":            "HIGH_VOL",
}


def map_regime_name(name: str) -> str:
    """将任意来源的 regime 名称映射为标准 5 状态命名

    Parameters
    ----------
    name : str
        输入的 regime 名称（大小写敏感）

    Returns
    -------
    str
        标准命名，映射失败返回 "UNKNOWN"
    """
    return _REGIME_MAP.get(name, "UNKNOWN")


def standardize_regime_set(regimes: list[str]) -> list[str]:
    """将一组 regime 名称全部标准化

    Parameters
    ----------
    regimes : list[str]
        输入的 regime 名称列表

    Returns
    -------
    list[str]
        标准化后的列表
    """
    return [map_regime_name(r) for r in regimes]


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RegimeTradeRecord:
    """带市场状态标签的单笔交易记录（Q3 输入格式）"""
    date: Union[datetime, str]       # 交易日期
    pnl_pct: float                   # 收益率（%）
    regime: str                      # 市场状态标签（原始命名，自动标准化）
    weight: float = 1.0              # 权重（可选，默认等权）


@dataclass
class RegimePerfSnapshot:
    """单市场状态的绩效切片"""
    regime: str                      # 标准命名
    n_trades: int                    # 该状态下的交易笔数
    total_return: float              # 总收益率
    avg_return: float                # 平均单笔收益率
    sharpe: Optional[float]          # 夏普比率（≥2笔时计算）
    win_rate: float                  # 胜率
    profit_factor: Optional[float]   # 盈亏比
    contribution_pct: float          # 占总收益的比例


@dataclass
class RegimePerfAggregation:
    """按市场状态聚合的绩效全景"""
    snapshots: list[RegimePerfSnapshot]
    positive_regime_count: int       # 正收益状态数
    dominant_regime: Optional[str]   # 贡献最大的状态
    dominant_share_pct: float        # 最大贡献占比
    regime_diversity: float          # 状态多样性 [0,1]


@dataclass
class RegimeValidationResult:
    """Regime 验证结果

    Attributes
    ----------
    passed : bool
        True = 在 ≥2 个 regime 下有正收益
    positive_regime_count : int
        正收益状态个数
    total_regimes_observed : int
        观察到的总状态数
    dominant_regime : str | None
        收益贡献最大的状态
    dominant_share_pct : float
        最大贡献状态的收益占比
    regime_aggregation : RegimePerfAggregation
        详细聚合数据
    fail_reason : str
        未通过的原因（通过时为空字符串）
    details : dict
        附加详细信息
    """
    passed: bool
    positive_regime_count: int
    total_regimes_observed: int
    dominant_regime: Optional[str]
    dominant_share_pct: float
    regime_aggregation: RegimePerfAggregation
    fail_reason: str = ""
    details: dict = field(default_factory=dict)


# ============================================================
# 核心验证逻辑
# ============================================================

def _to_dt(val: Union[datetime, str]) -> datetime:
    """统一转换为 datetime"""
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        return datetime.fromisoformat(val)
    raise TypeError(f"不支持的日期类型: {type(val)}")


def _calc_sharpe(returns: list[float]) -> Optional[float]:
    """计算夏普比率

    假设无风险利率为 0，使用样本标准差。

    Parameters
    ----------
    returns : list[float]
        收益率列表

    Returns
    -------
    float | None
        夏普比率，样本数 < 2 时返回 None
    """
    if len(returns) < 2:
        return None
    mean_r = sum(returns) / len(returns)
    if len(returns) < 2:
        return None
    variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return mean_r / std


def _calc_win_rate(returns: list[float]) -> float:
    """计算胜率"""
    if not returns:
        return 0.0
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns)


def _calc_profit_factor(returns: list[float]) -> Optional[float]:
    """计算盈亏比"""
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    if gross_loss == 0:
        return None  # 没有亏损
    return gross_profit / gross_loss if gross_loss > 0 else None


# ============================================================
# 聚合分析
# ============================================================

def aggregate_by_regime(records: list[RegimeTradeRecord]) -> RegimePerfAggregation:
    """按标准 regime 名称聚合交易记录

    Parameters
    ----------
    records : list[RegimeTradeRecord]
        带 regime 标签的交易记录列表

    Returns
    -------
    RegimePerfAggregation
        按状态聚合后的绩效全景
    """
    # 标准化 regime 名称
    grouped: dict[str, list[RegimeTradeRecord]] = {}
    for rec in records:
        std_regime = map_regime_name(rec.regime)
        grouped.setdefault(std_regime, []).append(rec)

    snapshots: list[RegimePerfSnapshot] = []
    total_return_all = sum(
        rec.pnl_pct * rec.weight
        for rec in records
    )
    total_return_abs = sum(
        abs(rec.pnl_pct * rec.weight)
        for rec in records
    )

    for regime, recs in sorted(grouped.items()):
        weighted_returns = [r.pnl_pct * r.weight for r in recs]
        n_trades = len(recs)
        total_return = sum(weighted_returns)

        # 贡献占比（绝对值）
        regime_total_abs = sum(abs(wr) for wr in weighted_returns)
        contribution_pct = (regime_total_abs / total_return_abs * 100) if total_return_abs > 0 else 0.0

        snapshot = RegimePerfSnapshot(
            regime=regime,
            n_trades=n_trades,
            total_return=round(total_return, 4),
            avg_return=round(total_return / n_trades, 4) if n_trades > 0 else 0.0,
            sharpe=_calc_sharpe(weighted_returns),
            win_rate=round(_calc_win_rate(weighted_returns), 4),
            profit_factor=_calc_profit_factor(weighted_returns),
            contribution_pct=round(contribution_pct, 2),
        )
        snapshots.append(snapshot)

    # 正收益状态数
    positive_count = sum(1 for s in snapshots if s.total_return > 0)
    total_regimes = len(snapshots)

    # 主导状态
    dominant_snapshot = max(snapshots, key=lambda s: abs(s.total_return)) if snapshots else None
    dominant_regime = dominant_snapshot.regime if dominant_snapshot else None
    dominant_share = dominant_snapshot.contribution_pct if dominant_snapshot else 0.0

    # 多样性指标：覆盖了几个标准状态（分母 5 对应 TREND_UP/DOWN/SIDEWAYS/HIGH_VOL/LOW_VOL）
    # 排除 UNKNOWN
    known_regimes = [s for s in snapshots if s.regime != "UNKNOWN"]
    diversity = len(known_regimes) / 5.0

    return RegimePerfAggregation(
        snapshots=snapshots,
        positive_regime_count=positive_count,
        dominant_regime=dominant_regime,
        dominant_share_pct=round(dominant_share, 2),
        regime_diversity=round(diversity, 4),
    )


# ============================================================
# 主验证函数
# ============================================================

def validate_regime_consistency(
    records: list[RegimeTradeRecord],
    min_positive_regimes: int = 2,
    max_dominant_share: float = 80.0,
) -> RegimeValidationResult:
    """验证策略在不同市场状态下的表现一致性

    核心逻辑：
      1. 将逐笔交易按标准 Regime 聚合
      2. 统计正收益的 Regime 个数
      3. 检查是否达到 ≥2 个 Regime 正收益的通过条件
      4. 检视收益集中度（单一状态贡献是否过高）

    Parameters
    ----------
    records : list[RegimeTradeRecord]
        带市场状态标签的交易记录
    min_positive_regimes : int
        最少正收益状态数（默认 2）
    max_dominant_share : float
        最大单一状态贡献占比（默认 80%），
        超过此值即使通过也可能标记为"过度集中"

    Returns
    -------
    RegimeValidationResult
    """
    if not records:
        return RegimeValidationResult(
            passed=False,
            positive_regime_count=0,
            total_regimes_observed=0,
            dominant_regime=None,
            dominant_share_pct=0.0,
            regime_aggregation=RegimePerfAggregation(
                snapshots=[], positive_regime_count=0,
                dominant_regime=None, dominant_share_pct=0.0,
                regime_diversity=0.0,
            ),
            fail_reason="无交易记录可分析",
        )

    aggregation = aggregate_by_regime(records)
    positive_count = aggregation.positive_regime_count
    total_regimes = len(aggregation.snapshots)
    dominant = aggregation.dominant_regime
    dominant_share = aggregation.dominant_share_pct

    # 通过条件
    pass_basic = positive_count >= min_positive_regimes

    fail_reason_parts: list[str] = []
    if not pass_basic:
        fail_reason_parts.append(
            f"正收益状态数 {positive_count} < 阈值 {min_positive_regimes}"
        )

    if dominant_share > max_dominant_share and positive_count > 0:
        fail_reason_parts.append(
            f"收益过度集中于 {dominant} ({dominant_share:.1f}% > {max_dominant_share:.0f}%)"
        )

    passed = pass_basic and dominant_share <= 90.0  # 90% 为绝对边界

    return RegimeValidationResult(
        passed=passed,
        positive_regime_count=positive_count,
        total_regimes_observed=total_regimes,
        dominant_regime=dominant,
        dominant_share_pct=dominant_share,
        regime_aggregation=aggregation,
        fail_reason="; ".join(fail_reason_parts),
        details={
            "standard_regimes": sorted(set(
                map_regime_name(r.regime) for r in records
            )),
            "records_analyzed": len(records),
            "threshold_min_positive": min_positive_regimes,
            "threshold_max_dominant_share": max_dominant_share,
        },
    )


def validate_from_perf_slices(
    perf_by_regime: dict[str, float],
    min_positive_regimes: int = 2,
) -> RegimeValidationResult:
    """从预聚合的逐状态收益数据验证 Regime 一致性

    适用于已有按 Regime 聚合的绩效数据，无需逐笔交易明细的场景。

    Parameters
    ----------
    perf_by_regime : dict[str, float]
        按原始 regime 名称聚合的总收益，如
        {"UPTREND": 5.2, "DOWNTREND": -1.3, "RANGE": 3.8}
    min_positive_regimes : int
        最少正收益状态数（默认 2）

    Returns
    -------
    RegimeValidationResult
    """
    return validate_regime_consistency(
        records=[
            RegimeTradeRecord(
                date=datetime.now(_TZ_CST),
                pnl_pct=pnl,
                regime=regime,
                weight=1.0,
            )
            # 每个状态模拟为一条记录（总收益作为单笔收益）
            for regime, pnl in perf_by_regime.items()
        ],
        min_positive_regimes=min_positive_regimes,
    )


def validate_regime_trades_only(
    trades_with_regime: list[dict],
    min_positive_regimes: int = 2,
    date_key: str = "date",
    pnl_key: str = "pnl_pct",
    regime_key: str = "regime",
) -> RegimeValidationResult:
    """从 dict 格式的交易列表验证 Regime 一致性

    Parameters
    ----------
    trades_with_regime : list[dict]
        每条记录包含日期、收益率、Regime 标签
    min_positive_regimes : int
        最少正收益状态数
    date_key : str
        日期字段名
    pnl_key : str
        收益率字段名
    regime_key : str
        Regime 字段名

    Returns
    -------
    RegimeValidationResult
    """
    records = [
        RegimeTradeRecord(
            date=t[date_key],
            pnl_pct=t[pnl_key],
            regime=t[regime_key],
        )
        for t in trades_with_regime
    ]
    return validate_regime_consistency(records, min_positive_regimes)


def format_validation_summary(result: RegimeValidationResult) -> str:
    """将验证结果格式化为可读摘要

    Parameters
    ----------
    result : RegimeValidationResult

    Returns
    -------
    str
    """
    lines = [
        f"Regime 一致性验证: {'✅ 通过' if result.passed else '🔴 未通过'}",
        f"正收益状态数: {result.positive_regime_count}/{result.total_regimes_observed}",
        f"主导状态: {result.dominant_regime or 'N/A'} (贡献 {result.dominant_share_pct:.1f}%)",
    ]
    if result.fail_reason:
        lines.append(f"原因: {result.fail_reason}")
    lines.append("")
    lines.append("各状态绩效:")
    for snap in result.regime_aggregation.snapshots:
        sharpe_str = f"{snap.sharpe:.3f}" if snap.sharpe is not None else "N/A"
        pf_str = f"{snap.profit_factor:.3f}" if snap.profit_factor is not None else "N/A"
        lines.append(
            f"  {snap.regime:15s} | n={snap.n_trades:3d} | "
            f"收益={snap.total_return:+.2%} | "
            f"胜率={snap.win_rate:.1%} | "
            f"夏普={sharpe_str} | 盈亏比={pf_str}"
        )
    return "\n".join(lines)


# ============================================================
# 快速 PASS/FAIL 判定（供 Gate 集成）
# ============================================================

def regime_check_passes(
    records: list[RegimeTradeRecord],
    min_positive_regimes: int = 2,
) -> bool:
    """快速判定 Regime 验证是否通过

    Parameters
    ----------
    records : list[RegimeTradeRecord]
        交易记录
    min_positive_regimes : int
        最小正收益状态数

    Returns
    -------
    bool
    """
    return validate_regime_consistency(records, min_positive_regimes).passed
