"""
墨枢 - TradeAttribution 交易归因分析（R1 阶段三：任务2）

功能：
  - 将每笔交易归因到具体因子
  - 计算各因子贡献度、胜率、盈亏比、累计收益贡献
  - 生成因子间相关性热图数据

依赖:
  - src.backtest.models.signal_types — FactorSignal
  - src.backtest.backtest.r1_backtest_engine — TradeRecord
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.backtest.models.signal_types import FactorSignal
from src.backtest.backtest.r1_backtest_engine import TradeRecord


# ─── 归因结果类型 ──────────────────────────────────────────────


@dataclass
class TradeAttribution:
    """单笔交易的因子归因"""
    trade_index: int
    entry_time: str
    exit_time: str
    direction: int
    pnl: float
    pnl_pct: float
    active_factors: Dict[str, float]      # {factor_name: score}
    factor_contributions: Dict[str, float] # {factor_name: contribution_pct (0~1, 归一化)}
    factor_consistency: float              # 同方向因子占比 [0, 1]
    primary_factor: str                    # 贡献最大的因子
    primary_contribution: float            # 最大因子贡献度


@dataclass
class FactorCumulativeStats:
    """因子累计统计"""
    factor_name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    avg_contribution: float = 0.0  # 归因平均贡献度


@dataclass
class FactorCorrelation:
    """因子间相关性数据"""
    factor_pairs: List[Tuple[str, str, float]]  # [(factor_a, factor_b, correlation)]
    matrix_values: List[List[float]]              # 相关系数矩阵
    labels: List[str]                             # 因子标签


@dataclass
class AttributionReport:
    """完整归因分析报告"""
    total_trades: int = 0
    total_pnl: float = 0.0
    trade_attributions: List[TradeAttribution] = field(default_factory=list)
    factor_stats: Dict[str, FactorCumulativeStats] = field(default_factory=dict)
    correlation: Optional[FactorCorrelation] = None
    top_factor_by_win_rate: str = ""
    top_factor_by_pnl: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 4),
            "top_factor_by_win_rate": self.top_factor_by_win_rate,
            "top_factor_by_pnl": self.top_factor_by_pnl,
            "factor_stats": {
                name: {
                    "total_trades": s.total_trades,
                    "win_rate": round(s.win_rate, 4),
                    "total_pnl": round(s.total_pnl, 4),
                    "profit_factor": round(s.profit_factor, 4),
                    "avg_contribution": round(s.avg_contribution, 4),
                }
                for name, s in self.factor_stats.items()
            },
            "correlation": {
                "labels": self.correlation.labels if self.correlation else [],
                "matrix_values": self.correlation.matrix_values if self.correlation else [],
                "factor_pairs": [
                    {"a": a, "b": b, "r": round(r, 4)}
                    for a, b, r in (self.correlation.factor_pairs if self.correlation else [])
                ],
            } if self.correlation else None,
            "trade_count_by_factor": {
                name: s.total_trades for name, s in self.factor_stats.items()
            },
        }


# ─── 主归因函数 ────────────────────────────────────────────────


def attribute_trades(
    trades: List[TradeRecord],
    factor_signals: Dict[str, List[FactorSignal]],
) -> AttributionReport:
    """归因分析：将每笔交易映射到对应因子的贡献。

    Args:
        trades: 交易记录列表（TradeRecord）
        factor_signals: {factor_name: [FactorSignal, ...]} 字典，
                        每个因子在时间轴上的信号序列

    Returns:
        AttributionReport: 归因分析报告
    """
    if not trades:
        return AttributionReport()

    # ── 构建因子信号时间索引 ──────────────────────────────
    # {factor_name: {timestamp_str: factor_signal}}
    factor_index: Dict[str, Dict[str, FactorSignal]] = {}
    for factor_name, signals in factor_signals.items():
        index: Dict[str, FactorSignal] = {}
        for s in signals:
            index[s.timestamp] = s
        factor_index[factor_name] = index

    all_factor_names = list(factor_signals.keys())

    # ── 逐笔归因 ──────────────────────────────────────────
    trade_attributions: List[TradeAttribution] = []
    # 用于计算相关性的矩阵
    factor_score_matrix: Dict[str, List[float]] = {
        name: [] for name in all_factor_names
    }

    for i, trade in enumerate(trades):
        entry_ts = trade.entry_time
        exit_ts = trade.exit_time
        trade_dir = trade.direction

        # 收集进入时各因子信号
        active_factors: Dict[str, float] = {}
        for fname in all_factor_names:
            idx = factor_index.get(fname, {})
            # 找出最近的信号（entry 前或 entry 时）
            matched_score = _find_nearest_signal(idx, entry_ts)
            if matched_score is not None:
                active_factors[fname] = matched_score

        if not active_factors:
            # 无有效因子信号，跳过归因
            continue

        # ── 因子贡献度计算 ────────────────────────────────
        # 按 score 绝对值归一化作为贡献度
        abs_scores = {k: abs(v) for k, v in active_factors.items()}
        total_abs = sum(abs_scores.values())
        if total_abs > 0:
            factor_contributions = {
                k: v / total_abs for k, v in abs_scores.items()
            }
        else:
            factor_contributions = {k: 0.0 for k in active_factors}

        # ── 因子一致性 ────────────────────────────────────
        # 同方向因子占比（与交易方向一致）
        same_dir_count = sum(
            1 for v in active_factors.values()
            if (v > 0 and trade_dir > 0) or (v < 0 and trade_dir < 0)
        )
        total_active = len(active_factors)
        consistency = same_dir_count / total_active if total_active > 0 else 0.0

        # ── 主要因子 ──────────────────────────────────────
        primary_factor = max(factor_contributions, key=factor_contributions.get)  # type: ignore[arg-type]
        primary_contrib = factor_contributions[primary_factor]

        # 填充相关性矩阵
        for fname in all_factor_names:
            val = active_factors.get(fname, 0.0)
            factor_score_matrix[fname].append(val)

        attribution = TradeAttribution(
            trade_index=i,
            entry_time=entry_ts,
            exit_time=exit_ts,
            direction=trade_dir,
            pnl=trade.pnl,
            pnl_pct=trade.pnl_pct,
            active_factors=active_factors,
            factor_contributions=factor_contributions,
            factor_consistency=round(consistency, 4),
            primary_factor=primary_factor,
            primary_contribution=round(primary_contrib, 4),
        )
        trade_attributions.append(attribution)

    # ── 因子累计统计 ──────────────────────────────────────
    factor_stats = _calc_factor_stats(trade_attributions, all_factor_names)

    # ── 相关性计算 ──────────────────────────────────────────
    correlation = _calc_correlation(factor_score_matrix, all_factor_names)

    # ── Top 因子 ──────────────────────────────────────────
    top_win_rate = ""
    top_win_val = 0.0
    top_pnl = ""
    top_pnl_val = float("-inf")

    for name, stats in factor_stats.items():
        if stats.total_trades >= 2 and stats.win_rate > top_win_val:
            top_win_rate = name
            top_win_val = stats.win_rate
        if stats.total_pnl > top_pnl_val:
            top_pnl = name
            top_pnl_val = stats.total_pnl

    total_pnl = sum(t.pnl for t in trades)

    return AttributionReport(
        total_trades=len(trades),
        total_pnl=total_pnl,
        trade_attributions=trade_attributions,
        factor_stats=factor_stats,
        correlation=correlation,
        top_factor_by_win_rate=top_win_rate,
        top_factor_by_pnl=top_pnl,
    )


# ─── 辅助函数 ──────────────────────────────────────────────────


def _find_nearest_signal(
    index: Dict[str, FactorSignal],
    entry_ts: str,
) -> Optional[float]:
    """在因子信号索引中找到最接近 entry_ts 的信号 score。

    优先精确匹配，次选最近的前向匹配。
    """
    if not index:
        return None

    # 精确匹配
    if entry_ts in index:
        return index[entry_ts].score

    # 模糊匹配：找最接近的（时间差最小）
    matched_score = None
    matched_diff = float("inf")

    for ts, sig in index.items():
        try:
            diff = abs(
                datetime.fromisoformat(entry_ts).timestamp()
                - datetime.fromisoformat(ts).timestamp()
            )
            if diff < matched_diff:
                matched_diff = diff
                matched_score = sig.score
        except (ValueError, TypeError):
            # 字符串无法解析时，跳过
            continue

    return matched_score


def _calc_factor_stats(
    attributions: List[TradeAttribution],
    all_factor_names: List[str],
) -> Dict[str, FactorCumulativeStats]:
    """计算各因子的累计统计指标。"""
    # 初始化
    stats_map: Dict[str, FactorCumulativeStats] = {}
    for fname in all_factor_names:
        stats_map[fname] = FactorCumulativeStats(factor_name=fname)

    for attr in attributions:
        for fname, contrib in attr.factor_contributions.items():
            if fname not in stats_map:
                stats_map[fname] = FactorCumulativeStats(factor_name=fname)
            stats = stats_map[fname]
            stats.total_trades += 1
            stats.total_pnl += attr.pnl
            stats.avg_contribution += contrib

            if attr.pnl > 0:
                stats.wins += 1
                stats.gross_profit += attr.pnl
            elif attr.pnl < 0:
                stats.losses += 1
                stats.gross_loss += abs(attr.pnl)

    # 计算衍生指标
    for stats in stats_map.values():
        if stats.total_trades > 0:
            stats.win_rate = stats.wins / stats.total_trades
            stats.avg_pnl = stats.total_pnl / stats.total_trades
            stats.avg_contribution = stats.avg_contribution / stats.total_trades
        if stats.gross_loss > 0:
            stats.profit_factor = stats.gross_profit / stats.gross_loss
        elif stats.gross_profit > 0:
            stats.profit_factor = 999.0

    return stats_map


def _calc_correlation(
    score_matrix: Dict[str, List[float]],
    factor_names: List[str],
) -> Optional[FactorCorrelation]:
    """计算因子信号间的成对相关性。"""
    active_names = [n for n in factor_names if len(score_matrix.get(n, [])) > 1]
    if len(active_names) < 2:
        return None

    n = len(active_names)
    matrix_values = [[0.0] * n for _ in range(n)]
    factor_pairs: List[Tuple[str, str, float]] = []

    for i in range(n):
        matrix_values[i][i] = 1.0  # 对角线为 1
        for j in range(i + 1, n):
            a = np.array(score_matrix[active_names[i]])
            b = np.array(score_matrix[active_names[j]])

            # 确保长度一致，补齐至较短的
            min_len = min(len(a), len(b))
            if min_len < 2:
                corr = 0.0
            else:
                corr = float(np.corrcoef(a[:min_len], b[:min_len])[0, 1])
                if np.isnan(corr):
                    corr = 0.0

            matrix_values[i][j] = round(corr, 4)
            matrix_values[j][i] = round(corr, 4)
            factor_pairs.append((active_names[i], active_names[j], round(corr, 4)))

    return FactorCorrelation(
        factor_pairs=factor_pairs,
        matrix_values=matrix_values,
        labels=active_names,
    )
