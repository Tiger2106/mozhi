"""
墨枢 - P5b-01: DailyReportExtractor
日报数据提取器
从 MultiStrategyResult 中提取每日信号/交易/净值/绩效数据。
无数据库依赖，所有数据从回测结果内存结构提取。

Author: 墨衡
Created: 2026-05-15
Version: 1.0

用法::

    from backtest.pipeline.daily_extractor import DailyReportExtractor

    extractor = DailyReportExtractor()
    report = extractor.extract_daily("20260515", multi_result)
    # report → {date, symbol, signals, trades, equities, metrics}
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.strategies.multi_runner import MultiStrategyResult


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

TRADING_DAYS_PER_YEAR = 252


class DailyReportExtractor:
    """
    日报数据提取器。

    提取每日：
    - 当日各策略信号（趋势/反转/网格）
    - 当日交易（买入/卖出/持仓）
    - 当日分策略净值、累计收益
    - 当日组合净值
    - 近5日/20日/60日夏普
    - 最大回撤

    用法::

        extractor = DailyReportExtractor()
        report = extractor.extract_daily("20260515", multi_result)
    """

    def extract_daily(self, date: str, result: MultiStrategyResult) -> Dict[str, Any]:
        """
        提取指定日期的日报数据。

        参数
        ----------
        date : str
            目标日期（YYYYMMDD）。
        result : MultiStrategyResult
            多策略回测结果。

        返回
        -------
        dict
            结构化日报数据。
        """
        self._validate_date(date)

        signals = self._extract_signals(date, result)
        trades = self._extract_trades(date, result)
        equities = self._extract_equities(date, result)
        metrics = self._extract_metrics(date, result)

        return {
            "date": date,
            "symbol": result.symbol,
            "signals": signals,
            "trades": trades,
            "equities": equities,
            "metrics": metrics,
        }

    # ── 公共辅助接口 ──────────────────────────────────────────

    def get_available_dates(self, result: MultiStrategyResult) -> List[str]:
        """返回结果中所有可用的交易日期（净值曲线日期列表）。"""
        df = result.combined.equity_curve
        if df.empty:
            return []
        return sorted(df["date"].dropna().unique().tolist())

    def get_first_date(self, result: MultiStrategyResult) -> Optional[str]:
        """返回回测起始日期。"""
        dates = self.get_available_dates(result)
        return dates[0] if dates else None

    def get_last_date(self, result: MultiStrategyResult) -> Optional[str]:
        """返回回测结束日期。"""
        dates = self.get_available_dates(result)
        return dates[-1] if dates else None

    # ── 信号提取 ─────────────────────────────────────────────

    def _extract_signals(self, date: str, result: MultiStrategyResult) -> Dict[str, Any]:
        """
        提取当日各策略信号。

        返回格式::

            {
                "strategies": {
                    "trend": {"signal": 1, "strength": 0.8, "price": 12.50, "quantity": 1000},
                    "reversal": {"signal": 0, "strength": 0.0, "price": 12.50, "quantity": 0},
                    "grid": {"signal": -1, "strength": 1.0, "price": 12.50, "quantity": 500},
                },
                "conflicts": [...],
                "total_signal_count": 3,
            }
        """
        strategy_names = list(result.strategies.keys())
        strategy_signals: Dict[str, Dict[str, Any]] = {
            name: {"signal": 0, "strength": 0.0, "price": 0.0, "quantity": 0}
            for name in strategy_names
        }

        for sig in result.signals:
            if sig.date == date:
                strategy_signals[sig.strategy_name] = {
                    "signal": sig.signal,
                    "strength": round(sig.strength, 4),
                    "price": round(sig.price, 4),
                    "quantity": sig.quantity,
                }

        # 当日冲突事件
        day_conflicts = [
            {
                "pair": list(c.pair),
                "direction_1": c.direction_1,
                "direction_2": c.direction_2,
                "price": round(c.price, 4),
                "resolved": c.resolved,
                "resolved_direction": c.resolved_direction,
            }
            for c in result.conflicts
            if c.date == date
        ]

        return {
            "strategies": strategy_signals,
            "conflicts": day_conflicts,
            "total_signal_count": len(strategy_names),
        }

    # ── 交易提取 ─────────────────────────────────────────────

    def _extract_trades(self, date: str, result: MultiStrategyResult) -> Dict[str, Any]:
        """
        提取当日各策略交易记录。

        返回格式::

            {
                "by_strategy": {
                    "trend": [{"side": "BUY", "price": 12.5, "quantity": 1000, ...}],
                    ...
                },
                "summary": {
                    "total_trades": 5,
                    "total_buy_volume": 2000,
                    "total_sell_volume": 1500,
                    "total_fee": 15.5,
                },
            }
        """
        day_trades: Dict[str, List[Dict[str, Any]]] = {}

        for name, bt_result in result.backtest_results.items():
            strategy_trades = []
            for trade in bt_result.trades:
                if trade.get("date") == date:
                    strategy_trades.append({
                        "side": trade.get("side", ""),
                        "price": round(float(trade.get("price", 0)), 4),
                        "quantity": int(trade.get("quantity", 0)),
                        "fee": round(float(trade.get("fee", 0)), 2),
                        "slippage": round(float(trade.get("slippage", 0)), 4),
                        "order_type": trade.get("order_type", ""),
                    })
            if strategy_trades:
                day_trades[name] = strategy_trades

        # 汇总
        total_trades = sum(len(v) for v in day_trades.values())
        total_buy = sum(
            t["quantity"]
            for trades in day_trades.values()
            for t in trades
            if t["side"] == "BUY"
        )
        total_sell = sum(
            t["quantity"]
            for trades in day_trades.values()
            for t in trades
            if t["side"] == "SELL"
        )
        total_fee = round(
            sum(t["fee"] for trades in day_trades.values() for t in trades),
            2,
        )

        return {
            "by_strategy": day_trades,
            "summary": {
                "total_trades": total_trades,
                "total_buy_volume": total_buy,
                "total_sell_volume": total_sell,
                "total_fee": total_fee,
            },
        }

    # ── 净值提取 ─────────────────────────────────────────────

    def _extract_equities(self, date: str, result: MultiStrategyResult) -> Dict[str, Any]:
        """
        提取当日各策略净值及组合净值。

        返回格式::

            {
                "per_strategy": {
                    "trend": 1050000.0,
                    "reversal": 1020000.0,
                    "grid": 1005000.0,
                },
                "combined": 3075000.0,
                "daily_return_pct": 0.25,
                "cumulative_return_pct": 5.35,
            }
        """
        df = result.combined.equity_curve
        if df.empty:
            return self._empty_equities(result)

        row = df[df["date"] == date]
        if row.empty:
            return self._empty_equities(result)

        row = row.iloc[0]

        per_strategy = {}
        for name in result.strategies:
            equity_col = f"{name}_equity"
            if equity_col in row.index and not pd.isna(row[equity_col]):
                per_strategy[name] = round(float(row[equity_col]), 2)

        combined_equity = (
            round(float(row["combined_equity"]), 2)
            if "combined_equity" in row.index and not pd.isna(row["combined_equity"])
            else 0.0
        )

        daily_return = (
            round(float(row["daily_return"]) * 100, 4)
            if "daily_return" in row.index and not pd.isna(row["daily_return"])
            else 0.0
        )
        cumulative_return = (
            round(float(row["cumulative_return"]) * 100, 4)
            if "cumulative_return" in row.index and not pd.isna(row["cumulative_return"])
            else 0.0
        )

        return {
            "per_strategy": per_strategy,
            "combined": combined_equity,
            "daily_return_pct": daily_return,
            "cumulative_return_pct": cumulative_return,
        }

    def _empty_equities(self, result: MultiStrategyResult) -> Dict[str, Any]:
        """返回空的净值结构。"""
        return {
            "per_strategy": {name: 0.0 for name in result.strategies},
            "combined": 0.0,
            "daily_return_pct": 0.0,
            "cumulative_return_pct": 0.0,
        }

    # ── 绩效指标提取 ─────────────────────────────────────────

    def _extract_metrics(self, date: str, result: MultiStrategyResult) -> Dict[str, Any]:
        """
        提取绩效指标：
        - 近5日/20日/60日年化夏普比率
        - 最大回撤
        - 总收益率 / 年化收益率
        - 资金分配信息

        返回格式::

            {
                "rolling_sharpe": {"5d": 1.5, "20d": 1.2, "60d": 0.9},
                "max_drawdown_pct": -8.5,
                "total_return_pct": 12.3,
                "annualized_return_pct": 8.5,
                "overall_sharpe": 1.25,
                "allocation": {"weights": {...}, "mode": "equal"},
            }
        """
        df = result.combined.equity_curve
        rolling_sharpe = self._compute_rolling_sharpe(date, df)

        max_dd = (
            round(float(result.combined.max_drawdown) * 100, 4)
            if result.combined.max_drawdown != 0.0
            else 0.0
        )

        total_ret = round(float(result.combined.total_return) * 100, 4)
        annual_ret = round(float(result.combined.annualized_return) * 100, 4)
        overall_sharpe = round(float(result.combined.sharpe_ratio), 4)

        allocation_info = (
            result.allocation.to_dict() if result.allocation else {}
        )

        return {
            "rolling_sharpe": rolling_sharpe,
            "max_drawdown_pct": -abs(max_dd),
            "total_return_pct": total_ret,
            "annualized_return_pct": annual_ret,
            "overall_sharpe": overall_sharpe,
            "allocation": allocation_info,
        }

    @staticmethod
    def _compute_rolling_sharpe(
        date: str, df: pd.DataFrame
    ) -> Dict[str, Optional[float]]:
        """
        从净值曲线 DataFrame 计算近 5/20/60 个交易日滚动年化夏普。

        算法：
        1. 定位 date 在 DataFrame 中的索引位置
        2. 向前取 n 个交易日（含当日）的 daily_return 序列
        3. 年化夏普 = mean(return) / std(return) * sqrt(252)
        4. 若数据不足或标准差为 0，返回 None
        """
        if df.empty or "daily_return" not in df.columns:
            return {"5d": None, "20d": None, "60d": None}

        # 按日期排序
        df_sorted = df.sort_values("date").reset_index(drop=True)

        # 定位 date 位置
        positions = df_sorted.index[df_sorted["date"] == date].tolist()
        if not positions:
            return {"5d": None, "20d": None, "60d": None}
        pos = positions[0]

        windows = {"5d": 5, "20d": 20, "60d": 60}
        result: Dict[str, Optional[float]] = {}

        for label, window in windows.items():
            start = max(0, pos - window + 1)
            segment = df_sorted.iloc[start : pos + 1]["daily_return"].dropna()
            segment = segment.replace([np.inf, -np.inf], np.nan).dropna()

            if len(segment) < 2:
                result[label] = None
                continue

            mean_ret = segment.mean()
            std_ret = segment.std()

            if std_ret == 0 or pd.isna(std_ret) or pd.isna(mean_ret):
                result[label] = None
                continue

            sharpe = (mean_ret / std_ret) * math.sqrt(TRADING_DAYS_PER_YEAR)
            result[label] = round(float(sharpe), 4)

        return result

    # ── 验证 ─────────────────────────────────────────────────

    @staticmethod
    def _validate_date(date: str) -> None:
        """验证日期格式 YYYYMMDD。"""
        if not date or not isinstance(date, str):
            raise ValueError(f"日期必须为非空字符串: {date!r}")
        if len(date) != 8 or not date.isdigit():
            raise ValueError(f"日期格式必须为 YYYYMMDD: {date!r}")

    def validate_report(self, report: Dict[str, Any]) -> List[str]:
        """
        验证日报结构的完整性。
        返回缺少的必填键列表（空列表 = 完整通过）。
        """
        required_top = ["date", "symbol", "signals", "trades", "equities", "metrics"]
        missing = [k for k in required_top if k not in report]

        if "signals" in report:
            if "strategies" not in report["signals"]:
                missing.append("signals.strategies")

        if "metrics" in report:
            for sub in ("rolling_sharpe", "max_drawdown_pct", "overall_sharpe"):
                if sub not in report["metrics"]:
                    missing.append(f"metrics.{sub}")

        return missing
