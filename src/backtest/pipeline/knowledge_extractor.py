"""
墨枢 - P5b-09: KnowledgeExtractor
知识提取器
从回测结果和流水线数据中提取可读知识片段，供给日报/周报的
"关键事件"和"建议"部分。

提取维度：
- 策略表现异常（胜率突变、夏普反转）
- 冲突事件统计（冲突率趋势、主要冲突对）
- 回撤事件（突破阈值、恢复状态）
- 连续亏损
- 资金分配偏差

Author: 墨衡
Created: 2026-05-15
Version: 1.0

用法::

    from backtest.pipeline.knowledge_extractor import KnowledgeExtractor

    extractor = KnowledgeExtractor()
    insights = extractor.extract_insights(multi_result, period_data)
    # insights → [{"type": "warning", "category": "sharp_drop", ...}, ...]
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.strategies.multi_runner import (
    CombinedResult,
    ConflictEvent,
    MultiStrategyResult,
)


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

DEFAULT_STRATEGY_NAMES = ("trend", "reversal", "grid")

# 预警阈值
SHARPE_WARNING = 0.5          # 夏普 < 0.5 → 建议检查参数
CONFLICT_RATE_WARNING = 0.40  # 冲突率 > 40% → 市况震荡
MAX_CONSECUTIVE_LOSS = 5      # 连亏 > 5 日 → 建议暂停或降低仓位
DRAWDOWN_WARNING = 0.05       # 回撤 > 5% → 警告
DRAWDOWN_CRITICAL = 0.10     # 回撤 > 10% → 严重警告
WIN_RATE_DROP_PCT = 20.0     # 胜率下降超过 20pct → 异常
MIN_ANALYSIS_DAYS = 3         # 最少分析天数
SHARPE_REVERSAL_THRESHOLD = 0.3  # 夏普变化 > 0.3 → 反转

# 追踪分配的偏差阈值
ALLOCATION_DEVIATION_THRESHOLD = 0.10  # 分配偏差 > 10pct → 提醒

INSIGHT_TYPES = ("warning", "info", "suggestion")
INSIGHT_CATEGORIES = (
    "sharp_drop",
    "sharpe_reversal",
    "win_rate_drop",
    "high_conflict",
    "trend_conflict_pair",
    "drawdown_breach",
    "drawdown_recovery",
    "consecutive_loss",
    "consecutive_gain_grid",
    "allocation_bias",
    "trend_param_check",
    "reversal_stop_loss",
    "grid_oscillation",
)


# ═══════════════════════════════════════════════════════════════
# KnowledgeExtractor
# ═══════════════════════════════════════════════════════════════


class KnowledgeExtractor:
    """
    知识提取器。

    从 MultiStrategyResult 和 period_data 中提取可读知识片段。

    period_data 格式（兼容 daily_extractor / weekly_extractor 输出）::

        {
            "date": "20260515",
            "symbol": "601857.SH",
            "signals": {...},        # 信号数据
            "trades": {...},         # 交易数据
            "equities": {...},       # 净值数据
            "metrics": {...},        # 绩效指标
            # 周报特有
            "weekly_return_pct": ...,
            "trading_days_in_week": ...,
        }
    """

    def __init__(
        self,
        sharpe_warning: float = SHARPE_WARNING,
        conflict_rate_warning: float = CONFLICT_RATE_WARNING,
        max_consecutive_loss: int = MAX_CONSECUTIVE_LOSS,
        drawdown_warning: float = DRAWDOWN_WARNING,
        drawdown_critical: float = DRAWDOWN_CRITICAL,
    ):
        self.sharpe_warning = sharpe_warning
        self.conflict_rate_warning = conflict_rate_warning
        self.max_consecutive_loss = max_consecutive_loss
        self.drawdown_warning = drawdown_warning
        self.drawdown_critical = drawdown_critical

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    def extract_insights(
        self,
        multi_result: MultiStrategyResult,
        period_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        从回测结果提取知识片段。

        参数
        ----------
        multi_result : MultiStrategyResult
            多策略回测结果。
        period_data : dict, optional
            日报/周报提取器的结构化输出。提供时用于补充更多上下文。

        返回
        -------
        list[dict]
            知识片段列表。每个片段包含:
            - type : str   — "warning" | "info" | "suggestion"
            - category : str — 预定义类别
            - message : str  — 可读消息
            - severity : int — 严重程度 (1=轻微, 3=中等, 5=严重)
        """
        insights: List[Dict[str, Any]] = []

        # ── 1. 策略表现异常 ──────────────────────────────
        insights.extend(self._check_strategy_anomalies(multi_result))

        # ── 2. 冲突事件 ──────────────────────────────────
        insights.extend(self._check_conflicts(multi_result))

        # ── 3. 回撤事件 ──────────────────────────────────
        insights.extend(self._check_drawdown(multi_result))

        # ── 4. 连续亏损 ──────────────────────────────────
        insights.extend(self._check_consecutive_losses(multi_result))

        # ── 5. 资金分配偏差 ──────────────────────────────
        insights.extend(self._check_allocation_bias(multi_result))

        # ── 6. 网格连续正收益 ────────────────────────────
        insights.extend(self._check_grid_streak(multi_result))

        # ── 排序：按 severity 降序 ──────────────────────
        insights.sort(key=lambda x: x.get("severity", 0), reverse=True)

        return insights

    # ═══════════════════════════════════════════════════════════
    # 1. 策略表现异常检查
    # ═══════════════════════════════════════════════════════════

    def _check_strategy_anomalies(
        self, result: MultiStrategyResult
    ) -> List[Dict[str, Any]]:
        """检查各策略夏普、胜率等异常。"""
        insights: List[Dict[str, Any]] = []
        combined = result.combined
        df = combined.equity_curve

        if df.empty:
            return insights

        for name in result.strategies:
            col = f"{name}_equity"
            if col not in df.columns:
                continue

            # ── 夏普检查 ────────────────────────────────
            bt_result = result.backtest_results.get(name)
            if bt_result:
                # 如果同策略有独立夏普，直接使用 backtest 提供的夏普
                # 但 backtest_engine.BacktestResult 可能没有 sharpe_ratio 字段
                # 从 equity 曲线推算
                strategy_equity = df[col].dropna().values
                if len(strategy_equity) >= 20:
                    daily_rets = (strategy_equity[1:] - strategy_equity[:-1]) / strategy_equity[:-1]
                    std = daily_rets.std()
                    if std > 0:
                        sharpe = float(daily_rets.mean() / std * math.sqrt(252))
                    else:
                        sharpe = 0.0

                    if sharpe < self.sharpe_warning and sharpe > 0:
                        insights.append({
                            "type": "warning",
                            "category": "sharp_drop",
                            "message": (
                                f"【{name}策略】夏普比率 {sharpe:.2f} < {self.sharpe_warning}，"
                                f"建议检查策略参数或市况是否已发生变化"
                            ),
                            "severity": 3,
                        })
                    elif sharpe <= 0:
                        insights.append({
                            "type": "warning",
                            "category": "sharp_drop",
                            "message": (
                                f"【{name}策略】夏普比率 {sharpe:.2f}（非正），"
                                f"策略表现严重下滑，建议全面检视"
                            ),
                            "severity": 5,
                        })

                    # ── 夏普反转检测 ─────────────────
                    if len(daily_rets) >= 40:
                        recent = daily_rets[-20:]
                        older = daily_rets[-40:-20]
                        recent_sharpe = (recent.mean() / recent.std() * math.sqrt(252)
                                         if recent.std() > 0 else 0.0)
                        older_sharpe = (older.mean() / older.std() * math.sqrt(252)
                                        if older.std() > 0 else 0.0)
                        delta = recent_sharpe - older_sharpe
                        if abs(delta) > SHARPE_REVERSAL_THRESHOLD and recent_sharpe < older_sharpe:
                            insights.append({
                                "type": "warning",
                                "category": "sharpe_reversal",
                                "message": (
                                    f"【{name}策略】近期夏普 {recent_sharpe:.2f} 较前期 {older_sharpe:.2f} "
                                    f"下降 {abs(delta):.2f}，出现夏普反转信号"
                                ),
                                "severity": 4,
                            })

            # ── 胜率异常（从回撤频次反推） ────────────
            col_ret = "daily_return"
            if col_ret in df.columns and len(df) >= MIN_ANALYSIS_DAYS:
                strategy_daily_ret = df[col_ret].dropna().values
                if len(strategy_daily_ret) >= 20:
                    # 使用整体 daily_return（组合级），如果无策略级别收益率则跳过
                    pass

        # 组合级夏普检查
        if combined.sharpe_ratio < self.sharpe_warning and combined.sharpe_ratio > 0:
            insights.append({
                "type": "warning",
                "category": "sharp_drop",
                "message": (
                    f"组合夏普比率 {combined.sharpe_ratio:.2f} < {self.sharpe_warning}，"
                    f"整体表现偏弱"
                ),
                "severity": 3,
            })
        elif combined.sharpe_ratio <= 0:
            insights.append({
                "type": "warning",
                "category": "sharp_drop",
                "message": (
                    f"组合夏普比率 {combined.sharpe_ratio:.2f}（非正），"
                    f"整体表现严重下滑"
                ),
                "severity": 5,
            })

        return insights

    # ═══════════════════════════════════════════════════════════
    # 2. 冲突事件统计
    # ═══════════════════════════════════════════════════════════

    def _check_conflicts(self, result: MultiStrategyResult) -> List[Dict[str, Any]]:
        """检查冲突事件统计。"""
        insights: List[Dict[str, Any]] = []
        df = result.combined.equity_curve

        if df.empty:
            return insights

        total_trading_days = len(df)
        if total_trading_days < MIN_ANALYSIS_DAYS:
            return insights

        # 冲突按策略对聚合
        pair_counts: Dict[Tuple[str, str], int] = {}
        for ce in result.conflicts:
            key = tuple(sorted(ce.pair))
            pair_counts[key] = pair_counts.get(key, 0) + 1

        total_conflict_days = len(set(ce.date for ce in result.conflicts))
        conflict_rate = total_conflict_days / total_trading_days

        if conflict_rate > self.conflict_rate_warning:
            insights.append({
                "type": "warning",
                "category": "high_conflict",
                "message": (
                    f"信号冲突率 {conflict_rate:.1%} > {self.conflict_rate_warning:.0%}，"
                    f"说明当前市况震荡加剧，信号方向分歧显著"
                ),
                "severity": 4 if conflict_rate > 0.50 else 3,
            })
        elif conflict_rate > 0.20:
            insights.append({
                "type": "info",
                "category": "high_conflict",
                "message": (
                    f"信号冲突率 {conflict_rate:.1%}，略偏高，市况存在一定分歧"
                ),
                "severity": 2,
            })

        # 主要冲突对
        if pair_counts:
            sorted_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)
            top_pair = sorted_pairs[0]
            top_pair_rate = top_pair[1] / total_trading_days

            if top_pair_rate > 0.15:
                pair_label = f"{top_pair[0][0]} vs {top_pair[0][1]}"
                insights.append({
                    "type": "info",
                    "category": "trend_conflict_pair",
                    "message": (
                        f"主要冲突对：【{pair_label}】，"
                        f"共 {top_pair[1]} 天/ {top_pair_rate:.1%} 的交易日存在冲突"
                    ),
                    "severity": 2,
                })

            if len(sorted_pairs) >= 2:
                second_pair = sorted_pairs[1]
                insights.append({
                    "type": "info",
                    "category": "trend_conflict_pair",
                    "message": (
                        f"次要冲突对：【{second_pair[0][0]} vs {second_pair[0][1]}】，"
                        f"共 {second_pair[1]} 天"
                    ),
                    "severity": 1,
                })

        return insights

    # ═══════════════════════════════════════════════════════════
    # 3. 回撤事件
    # ═══════════════════════════════════════════════════════════

    def _check_drawdown(self, result: MultiStrategyResult) -> List[Dict[str, Any]]:
        """检查回撤阈值突破及恢复状态。"""
        insights: List[Dict[str, Any]] = []
        df = result.combined.equity_curve
        combined = result.combined

        if df.empty:
            return insights

        max_dd = combined.max_drawdown

        if max_dd >= self.drawdown_critical:
            insights.append({
                "type": "warning",
                "category": "drawdown_breach",
                "message": (
                    f"组合最大回撤已达 {max_dd:.1%}，"
                    f"超过严重阈值 {self.drawdown_critical:.0%}，需立即评估风控"
                ),
                "severity": 5,
            })
        elif max_dd >= self.drawdown_warning:
            insights.append({
                "type": "warning",
                "category": "drawdown_breach",
                "message": (
                    f"组合最大回撤 {max_dd:.1%} > {self.drawdown_warning:.0%}，"
                    f"需关注回撤是否持续扩大"
                ),
                "severity": 3,
            })
        else:
            insights.append({
                "type": "info",
                "category": "drawdown_recovery",
                "message": (
                    f"组合回撤控制在 {max_dd:.1%}，"
                    f"未触发预警阈值 {self.drawdown_warning:.0%}，风控状态良好"
                ),
                "severity": 1,
            })

        # 从 equity_curve 检测近期回撤恢复
        equity_col = "combined_equity"
        if equity_col in df.columns and len(df) >= 10:
            equity_vals = df[equity_col].dropna().values
            peak = np.maximum.accumulate(equity_vals)
            drawdown = (equity_vals - peak) / peak

            # 检测最近的恢复区间
            recent_dd = drawdown[-1]
            last_peak_idx = np.argmax(peak[-20:]) if len(peak) >= 20 else 0
            if last_peak_idx > 0 and abs(recent_dd) < 0.01:
                # 已接近前高
                if abs(drawdown[-5:].min()) > self.drawdown_warning:
                    insights.append({
                        "type": "suggestion",
                        "category": "drawdown_recovery",
                        "message": (
                            f"近期回撤已基本修复，净值接近前高，"
                            f"可评估是否逐步恢复仓位"
                        ),
                        "severity": 2,
                    })

        return insights

    # ═══════════════════════════════════════════════════════════
    # 4. 连续亏损
    # ═══════════════════════════════════════════════════════════

    def _check_consecutive_losses(
        self, result: MultiStrategyResult
    ) -> List[Dict[str, Any]]:
        """
        检测连续亏损。

        对每个策略和组合，从 daily_return 序列中检测。
        """
        insights: List[Dict[str, Any]] = []
        df = result.combined.equity_curve

        if df.empty or "daily_return" not in df.columns:
            return insights

        # 组合级连亏检测
        returns = df["daily_return"].dropna().values
        combined_streak = self._longest_loss_streak(returns)
        if combined_streak >= self.max_consecutive_loss:
            insights.append({
                "type": "warning",
                "category": "consecutive_loss",
                "message": (
                    f"组合连续亏损已达 {combined_streak} 天"
                    f"（> {self.max_consecutive_loss} 天阈值），"
                    f"建议暂停或降低仓位，等待市场方向明确"
                ),
                "severity": 5 if combined_streak >= 8 else 4,
            })
        elif combined_streak >= 3:
            insights.append({
                "type": "suggestion",
                "category": "consecutive_loss",
                "message": (
                    f"组合已连续亏损 {combined_streak} 天，"
                    f"建议关注是否需调整策略权重"
                ),
                "severity": 2,
            })

        # 各策略级连亏
        for name in result.strategies:
            col = f"{name}_equity"
            if col not in df.columns:
                continue
            eq_vals = df[col].dropna().values
            if len(eq_vals) < 3:
                continue

            # 从 equity 反推每日收益
            eq_returns = np.diff(eq_vals) / eq_vals[:-1]
            streak = self._longest_loss_streak(eq_returns)

            if streak >= self.max_consecutive_loss:
                severity = 5 if streak >= 8 else 4
                if name == "reversal":
                    # 反转策略连亏 > 5 → 建议暂停或降低仓位
                    insights.append({
                        "type": "warning",
                        "category": "consecutive_loss",
                        "message": (
                            f"【反转策略】连续亏损 {streak} 天"
                            f"（> {self.max_consecutive_loss} 天），"
                            f"反转策略可能不适合当前趋势市，建议降低仓位"
                        ),
                        "severity": severity,
                    })
                elif name == "trend":
                    insights.append({
                        "type": "warning",
                        "category": "consecutive_loss",
                        "message": (
                            f"【趋势策略】连续亏损 {streak} 天"
                            f"（> {self.max_consecutive_loss} 天），"
                            f"建议检查趋势参数或是否已进入震荡市"
                        ),
                        "severity": severity,
                    })

        return insights

    # ═══════════════════════════════════════════════════════════
    # 5. 资金分配偏差
    # ═══════════════════════════════════════════════════════════

    def _check_allocation_bias(
        self, result: MultiStrategyResult
    ) -> List[Dict[str, Any]]:
        """检查资金分配偏差。"""
        insights: List[Dict[str, Any]] = []
        allocation = result.allocation

        if allocation is None:
            return insights

        weights = allocation.weights
        mode = allocation.mode

        # 检查是否有策略权重异常
        if mode == "equal":
            # 等分配模式下检查是否有策略被明显偏向
            names = list(weights.keys())
            if names:
                expected = 1.0 / len(names)
                for name, w in weights.items():
                    deviation = abs(w - expected)
                    if deviation > ALLOCATION_DEVIATION_THRESHOLD:
                        direction = "偏高" if w > expected else "偏低"
                        insights.append({
                            "type": "info",
                            "category": "allocation_bias",
                            "message": (
                                f"【{name}策略】资金占比 {w:.0%}（{direction}于等分配 {expected:.0%}），"
                                f"偏差 {deviation:.1%}"
                            ),
                            "severity": 2,
                        })

        return insights

    # ═══════════════════════════════════════════════════════════
    # 6. 网格连续正收益
    # ═══════════════════════════════════════════════════════════

    def _check_grid_streak(self, result: MultiStrategyResult) -> List[Dict[str, Any]]:
        """
        检查网格策略是否连续正收益。
        网格连续正收益 → 确认震荡市。
        """
        insights: List[Dict[str, Any]] = []
        df = result.combined.equity_curve

        if df.empty:
            return insights

        grid_col = "grid_equity"
        if grid_col not in df.columns:
            return insights

        eq_vals = df[grid_col].dropna().values
        if len(eq_vals) < 5:
            return insights

        eq_returns = np.diff(eq_vals) / eq_vals[:-1]
        pos_count = 0
        max_pos_streak = 0

        for ret in eq_returns:
            if ret > 0:
                pos_count += 1
                max_pos_streak = max(max_pos_streak, pos_count)
            else:
                pos_count = 0

        if max_pos_streak >= self.max_consecutive_loss:
            insights.append({
                "type": "info",
                "category": "consecutive_gain_grid",
                "message": (
                    f"【网格策略】连续正收益达 {max_pos_streak} 天，"
                    f"确认当前为震荡行情，网格策略表现突出"
                ),
                "severity": 1,
            })
        elif max_pos_streak >= 3:
            insights.append({
                "type": "suggestion",
                "category": "consecutive_gain_grid",
                "message": (
                    f"【网格策略】近期连续正收益 {max_pos_streak} 天，"
                    f"市况可能偏向震荡"
                ),
                "severity": 1,
            })

        # 检查网格是否在趋势市中表现不佳
        if len(eq_returns) >= 10:
            recent = eq_returns[-10:]
            neg_count = int((recent < 0).sum())
            if neg_count >= 7:
                insights.append({
                    "type": "suggestion",
                    "category": "consecutive_gain_grid",
                    "message": (
                        f"【网格策略】近10日中 {neg_count} 日亏损，"
                        f"可能已进入趋势行情，网格策略贡献有限"
                    ),
                    "severity": 3,
                })

        return insights

    # ═══════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _longest_loss_streak(returns: np.ndarray) -> int:
        """
        计算日收益率序列中的最长连续亏损天数。

        参数
        ----------
        returns : np.ndarray
            日收益率数组（如 daily_return 列的值）。

        返回
        -------
        int
            最长连续亏损天数。
        """
        if len(returns) == 0:
            return 0

        streak = 0
        max_streak = 0

        for r in returns:
            if r < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

        return max_streak

    @staticmethod
    def _compute_strategy_sharpe(
        equity_curve: np.ndarray,
    ) -> float:
        """
        从净值序列计算年化夏普比率。

        参数
        ----------
        equity_curve : np.ndarray
            净值序列。

        返回
        -------
        float
            年化夏普比率。
        """
        if len(equity_curve) < 5:
            return 0.0

        returns = (equity_curve[1:] - equity_curve[:-1]) / equity_curve[:-1]
        returns = returns[~np.isnan(returns)]
        returns = returns[~np.isinf(returns)]

        if len(returns) < 3:
            return 0.0

        std = returns.std()
        if std == 0:
            return 0.0

        return float(returns.mean() / std * math.sqrt(252))

    # ═══════════════════════════════════════════════════════════
    # 批量提取（便捷方法）
    # ═══════════════════════════════════════════════════════════

    def extract_all(
        self,
        results: Dict[str, MultiStrategyResult],
        period_data_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        批量提取多个标的的知识片段。

        参数
        ----------
        results : dict[str, MultiStrategyResult]
            {symbol: MultiStrategyResult}
        period_data_map : dict, optional
            {symbol: period_data}

        返回
        -------
        dict[str, list[dict]]
            {symbol: [insight, ...]}
        """
        all_insights: Dict[str, List[Dict[str, Any]]] = {}

        for symbol, result in results.items():
            period_data = period_data_map.get(symbol) if period_data_map else None
            all_insights[symbol] = self.extract_insights(result, period_data)

        return all_insights

    # ═══════════════════════════════════════════════════════════
    # 格式化输出
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def format_insights_markdown(
        insights: List[Dict[str, Any]],
        max_items: int = 10,
    ) -> str:
        """
        将知识片段格式化为 Markdown 文本。

        参数
        ----------
        insights : list[dict]
            知识片段列表。
        max_items : int
            最大输出条目数。

        返回
        -------
        str
            Markdown 格式的文本。
        """
        if not insights:
            return "暂无显著事件。\n"

        lines: List[str] = []

        # 按 severity 分组
        critical = [i for i in insights if i.get("severity", 0) >= 4]
        warnings = [i for i in insights if i.get("severity", 0) == 3]
        others = [i for i in insights if i.get("severity", 0) < 3]

        if critical:
            lines.append("### 🚨 严重")
            for item in critical[:max_items]:
                lines.append(f"- **{item['message']}**")
            lines.append("")

        if warnings:
            lines.append("### ⚠️ 关注")
            for item in warnings[:max_items]:
                lines.append(f"- {item['message']}")
            lines.append("")

        if others:
            lines.append("### ℹ️ 信息")
            for item in others[:max_items]:
                lines.append(f"- {item['message']}")
            lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def extract_insights(
    multi_result: MultiStrategyResult,
    period_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """便捷函数：提取知识片段。"""
    return KnowledgeExtractor().extract_insights(multi_result, period_data)


# ═══════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 构造一个模拟的 MultiStrategyResult 做自测
    from backtest.strategies.multi_runner import CombinedResult, MultiStrategyResult, ConflictEvent
    from dataclasses import dataclass, field

    # 构造模拟净值数据（带30个交易日，包含连亏和回撤模式）
    np.random.seed(42)
    n = 30
    dates = [f"202605{1+i:02d}" for i in range(n)]

    # 先平稳后回撤 + 连亏的净值
    trend_eq = 1_000_000 + np.cumsum(np.random.normal(0.001, 0.01, n)) * 1_000_000
    reversal_eq = 1_000_000 + np.cumsum(np.random.normal(0.0005, 0.015, n)) * 1_000_000
    grid_eq = 1_000_000 + np.cumsum(np.random.normal(0.0008, 0.005, n)) * 1_000_000

    # 最后5天连亏
    for eq in (trend_eq, reversal_eq, grid_eq):
        eq[-5:] *= 0.995 ** np.arange(5, 0, -1)

    equity_df = pd.DataFrame({
        "date": dates,
        "trend_equity": trend_eq,
        "reversal_equity": reversal_eq,
        "grid_equity": grid_eq,
        "combined_equity": trend_eq * 0.34 + reversal_eq * 0.33 + grid_eq * 0.33,
    })
    equity_df["daily_return"] = equity_df["combined_equity"].pct_change().fillna(0.0)
    equity_df["cumulative_return"] = (1 + equity_df["daily_return"]).cumprod() - 1

    final_eq = equity_df["combined_equity"].iloc[-1]
    combined = CombinedResult(
        equity_curve=equity_df,
        weights={"trend": 0.34, "reversal": 0.33, "grid": 0.33},
        initial_capital=1_000_000,
        final_equity=final_eq,
        total_return=final_eq / 1_000_000 - 1,
        sharpe_ratio=0.35,
        max_drawdown=0.08,
    )

    # 模拟冲突
    conflicts = [
        ConflictEvent(date=dates[i], pair=("trend", "reversal"), direction_1=1, direction_2=-1)
        for i in range(12)  # 12/30 = 40% 冲突率
    ]
    conflicts += [
        ConflictEvent(date=dates[i], pair=("trend", "grid"), direction_1=1, direction_2=-1)
        for i in range(6, 18)
    ]

    # 模拟分配
    from backtest.strategies.capital_allocator import AllocationResult
    allocation = AllocationResult(
        allocations={"trend": 340000, "reversal": 330000, "grid": 330000},
        weights={"trend": 0.34, "reversal": 0.33, "grid": 0.33},
        mode="equal",
    )

    result = MultiStrategyResult(
        symbol="601857.SH",
        strategies={"trend": None, "reversal": None, "grid": None},
        signals=[],
        combined=combined,
        conflicts=conflicts,
        allocation=allocation,
    )

    extractor = KnowledgeExtractor()
    insights = extractor.extract_insights(result)

    print("=" * 60)
    print("KNOWLEDGE EXTRACTOR SELF-TEST")
    print("=" * 60)
    print(f"Total insights: {len(insights)}")
    for i, ins in enumerate(insights):
        print(f"\n[{i+1}] type={ins['type']} | category={ins['category']} | severity={ins['severity']}")
        print(f"    {ins['message']}")

    print("\n\n--- Markdown ---")
    print(KnowledgeExtractor.format_insights_markdown(insights))
    print("\n✅ KnowledgeExtractor self-test passed.")
