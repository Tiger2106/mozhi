"""
墨枢 - P5b-02: WeeklyReportExtractor
周报数据提取器
从 MultiStrategyResult 中提取每周收益/交易/持仓/胜率/环比数据。
无数据库依赖，所有数据从回测结果内存结构提取。

Author: 墨衡
Created: 2026-05-15
Version: 1.0

用法::

    from backtest.pipeline.weekly_extractor import WeeklyReportExtractor

    extractor = WeeklyReportExtractor()
    report = extractor.extract_weekly("20260511", multi_result)
    # report → {week_start, week_end, summary, trades, deltas, monthly, ...}
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.strategies.multi_runner import MultiStrategyResult

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

TRADING_DAYS_PER_YEAR = 252
MAX_WEEK_CALENDAR_DAYS = 7
DATE_FORMAT = "%Y%m%d"


class WeeklyReportExtractor:
    """
    周报数据提取器。

    提取每周：
    - 周收益汇总（各策略/组合）
    - 周交易记录
    - 周增减（与上周对比）
    - 月累计收益
    - 周胜率
    - 持仓汇总

    用法::

        extractor = WeeklyReportExtractor()
        report = extractor.extract_weekly("20260511", multi_result)
    """

    def extract_weekly(
        self, week_start: str, result: MultiStrategyResult
    ) -> Dict[str, Any]:
        """
        提取周报数据。

        参数
        ----------
        week_start : str
            周起始日期（YYYYMMDD，周一或该周首个交易日）。
        result : MultiStrategyResult
            多策略回测结果。

        返回
        -------
        dict
            结构化周报数据。
        """
        self._validate_date(week_start)
        df = result.combined.equity_curve
        if df.empty:
            return self._empty_weekly(week_start, result)

        # 计算周范围
        week_end = self._compute_week_end(week_start)
        prev_week_start, prev_week_end = self._compute_prev_week(week_start)

        # 提取该周内的净值数据行
        week_data = self._filter_date_range(df, week_start, week_end)
        prev_week_data = self._filter_date_range(df, prev_week_start, prev_week_end)

        # 各维度提取
        summary = self._extract_weekly_summary(
            week_data, prev_week_data, week_start, week_end, result
        )
        trades = self._extract_weekly_trades(
            week_start, week_end, result
        )
        daily_details = self._extract_daily_details(
            week_data, result
        )
        win_rate = self._compute_win_rate(week_data)
        monthly = self._extract_monthly_cumulative(
            week_data, week_start, df, result
        )
        holdings = self._extract_holdings(
            week_end, result
        )
        conflicts = self._extract_weekly_conflicts(
            week_start, week_end, result
        )

        return {
            "week_start": week_start,
            "week_end": week_end,
            "symbol": result.symbol,
            "trading_days_in_week": len(week_data),
            "summary": summary,
            "trades": trades,
            "daily_details": daily_details,
            "win_rate": win_rate,
            "monthly_cumulative": monthly,
            "holdings": holdings,
            "conflicts": conflicts,
        }

    # ── 日期工具 ─────────────────────────────────────────────

    @staticmethod
    def _compute_week_end(week_start: str) -> str:
        """计算周结束日期（week_start + 6 个自然日）。"""
        dt = datetime.strptime(week_start, DATE_FORMAT)
        end_dt = dt + timedelta(days=MAX_WEEK_CALENDAR_DAYS - 1)
        return end_dt.strftime(DATE_FORMAT)

    @staticmethod
    def _compute_prev_week(week_start: str) -> Tuple[str, str]:
        """计算上周范围（week_start - 7d, week_end - 7d）。"""
        dt = datetime.strptime(week_start, DATE_FORMAT)
        prev_start = (dt - timedelta(days=MAX_WEEK_CALENDAR_DAYS)).strftime(DATE_FORMAT)
        prev_end = (dt - timedelta(days=1)).strftime(DATE_FORMAT)
        return prev_start, prev_end

    @staticmethod
    def _compute_month_start(date_str: str) -> str:
        """计算 date_str 所在月份的第一天。"""
        dt = datetime.strptime(date_str, DATE_FORMAT)
        return dt.replace(day=1).strftime(DATE_FORMAT)

    @staticmethod
    def _filter_date_range(
        df: pd.DataFrame, start: str, end: str
    ) -> pd.DataFrame:
        """
        从净值曲线 DataFrame 中截取 [start, end] 日期范围的交易日数据。
        """
        if df.empty:
            return pd.DataFrame()
        df_sorted = df.sort_values("date")
        return df_sorted[(df_sorted["date"] >= start) & (df_sorted["date"] <= end)]

    # ── 周收益汇总 ───────────────────────────────────────────

    @staticmethod
    def _extract_weekly_summary(
        week_data: pd.DataFrame,
        prev_week_data: pd.DataFrame,
        week_start: str,
        week_end: str,
        result: MultiStrategyResult,
    ) -> Dict[str, Any]:
        """
        提取周收益汇总（含环比）。

        返回::

            {
                "per_strategy": {
                    "trend": {"return_pct": 1.25, "prev_return_pct": 0.85, "change_pct": 0.40},
                    ...
                },
                "combined": {"return_pct": 1.10, "prev_return_pct": 0.90, "change_pct": 0.20},
                "weekly_return_pct": 1.10,
                "prev_weekly_return_pct": 0.90,
                "week_over_week_change": 0.20,
            }
        """
        strategies = list(result.strategies.keys())
        per_strategy = {}

        for name in strategies:
            col = f"{name}_equity"
            ret = 0.0
            prev_ret = 0.0
            change = 0.0

            if col in week_data.columns:
                week_vals = week_data[col].dropna()
                if len(week_vals) >= 1:
                    first_eq = week_vals.iloc[0]
                    last_eq = week_vals.iloc[-1]
                    if first_eq > 0:
                        ret = round((last_eq - first_eq) / first_eq * 100, 4)

            if col in prev_week_data.columns and not prev_week_data.empty:
                prev_vals = prev_week_data[col].dropna()
                if len(prev_vals) >= 1:
                    pfirst = prev_vals.iloc[0]
                    plast = prev_vals.iloc[-1]
                    if pfirst > 0:
                        prev_ret = round((plast - pfirst) / pfirst * 100, 4)

            change = round(ret - prev_ret, 4)

            per_strategy[name] = {
                "return_pct": ret,
                "prev_return_pct": prev_ret,
                "change_pct": change,
            }

        # 组合收益
        combined_col = "combined_equity"
        combined_ret = 0.0
        prev_combined_ret = 0.0

        if combined_col in week_data.columns:
            cvals = week_data[combined_col].dropna()
            if len(cvals) >= 2:
                first_c = cvals.iloc[0]
                last_c = cvals.iloc[-1]
                if first_c > 0:
                    combined_ret = round((last_c - first_c) / first_c * 100, 4)
            elif len(cvals) == 1:
                # 单日周，从 cumulative_return 反推
                pass

        if combined_col in prev_week_data.columns and not prev_week_data.empty:
            pcvals = prev_week_data[combined_col].dropna()
            if len(pcvals) >= 2:
                pfirst_c = pcvals.iloc[0]
                plast_c = pcvals.iloc[-1]
                if pfirst_c > 0:
                    prev_combined_ret = round((plast_c - pfirst_c) / pfirst_c * 100, 4)

        combined_change = round(combined_ret - prev_combined_ret, 4)

        return {
            "per_strategy": per_strategy,
            "combined": {
                "return_pct": combined_ret,
                "prev_return_pct": prev_combined_ret,
                "change_pct": combined_change,
            },
            "weekly_return_pct": combined_ret,
            "prev_weekly_return_pct": prev_combined_ret,
            "week_over_week_change": combined_change,
        }

    # ── 周交易记录 ───────────────────────────────────────────

    @staticmethod
    def _extract_weekly_trades(
        week_start: str, week_end: str, result: MultiStrategyResult
    ) -> Dict[str, Any]:
        """
        提取该周内所有交易记录。

        返回::

            {
                "by_strategy": {
                    "trend": [{"date": ..., "side": ..., ...}],
                    ...
                },
                "summary": {
                    "total_trades": 10,
                    "buy_trades": 6,
                    "sell_trades": 4,
                    "total_volume": 5000,
                    "total_fee": 25.0,
                },
            }
        """
        week_trades: Dict[str, List[Dict[str, Any]]] = {}

        for name, bt_result in result.backtest_results.items():
            strategy_trades = []
            for trade in bt_result.trades:
                tdate = trade.get("date", "")
                if week_start <= tdate <= week_end:
                    strategy_trades.append({
                        "date": tdate,
                        "side": trade.get("side", ""),
                        "price": round(float(trade.get("price", 0)), 4),
                        "quantity": int(trade.get("quantity", 0)),
                        "fee": round(float(trade.get("fee", 0)), 2),
                        "slippage": round(float(trade.get("slippage", 0)), 4),
                        "order_type": trade.get("order_type", ""),
                    })
            if strategy_trades:
                week_trades[name] = strategy_trades

        # 汇总
        all_week_trades = [t for v in week_trades.values() for t in v]
        total_trades = len(all_week_trades)
        buy_trades = sum(1 for t in all_week_trades if t["side"] == "BUY")
        sell_trades = sum(1 for t in all_week_trades if t["side"] == "SELL")
        total_volume = sum(t["quantity"] for t in all_week_trades)
        total_fee = round(sum(t["fee"] for t in all_week_trades), 2)

        return {
            "by_strategy": week_trades,
            "summary": {
                "total_trades": total_trades,
                "buy_trades": buy_trades,
                "sell_trades": sell_trades,
                "total_volume": total_volume,
                "total_fee": total_fee,
            },
        }

    # ── 逐日明细 ─────────────────────────────────────────────

    @staticmethod
    def _extract_daily_details(
        week_data: pd.DataFrame, result: MultiStrategyResult
    ) -> List[Dict[str, Any]]:
        """
        提取该周逐日净值明细。

        返回::

            [
                {
                    "date": "20260511",
                    "combined_equity": 1005000.0,
                    "daily_return_pct": 0.15,
                    "trend_equity": 505000.0,
                    "reversal_equity": 300000.0,
                    "grid_equity": 200000.0,
                },
                ...
            ]
        """
        if week_data.empty:
            return []

        details = []
        strategies = list(result.strategies.keys())

        for _, row in week_data.iterrows():
            entry: Dict[str, Any] = {
                "date": str(row.get("date", "")),
                "combined_equity": round(float(row.get("combined_equity", 0)), 2),
                "daily_return_pct": round(
                    float(row.get("daily_return", 0)) * 100, 4
                ),
            }
            for name in strategies:
                col = f"{name}_equity"
                if col in row.index and not pd.isna(row[col]):
                    entry[name] = round(float(row[col]), 2)
            details.append(entry)

        return details

    # ── 胜率 ─────────────────────────────────────────────────

    @staticmethod
    def _compute_win_rate(week_data: pd.DataFrame) -> Dict[str, Any]:
        """
        计算该周的日胜率。

        返回::

            {
                "daily_win_rate_pct": 60.0,
                "winning_days": 3,
                "losing_days": 2,
                "total_days": 5,
                "best_day_pct": 1.25,
                "worst_day_pct": -0.85,
                "avg_daily_return_pct": 0.15,
            }
        """
        if week_data.empty or "daily_return" not in week_data.columns:
            return {
                "daily_win_rate_pct": 0.0,
                "winning_days": 0,
                "losing_days": 0,
                "total_days": 0,
                "best_day_pct": 0.0,
                "worst_day_pct": 0.0,
                "avg_daily_return_pct": 0.0,
            }

        returns = week_data["daily_return"].dropna()
        returns = returns.replace([np.inf, -np.inf], np.nan).dropna()

        if len(returns) == 0:
            return {
                "daily_win_rate_pct": 0.0,
                "winning_days": 0,
                "losing_days": 0,
                "total_days": 0,
                "best_day_pct": 0.0,
                "worst_day_pct": 0.0,
                "avg_daily_return_pct": 0.0,
            }

        winning = int((returns > 0).sum())
        losing = int((returns <= 0).sum())
        total = len(returns)
        win_rate = round(winning / total * 100, 2) if total > 0 else 0.0

        returns_pct = returns * 100
        best = round(float(returns_pct.max()), 4)
        worst = round(float(returns_pct.min()), 4)
        avg = round(float(returns_pct.mean()), 4)

        return {
            "daily_win_rate_pct": win_rate,
            "winning_days": winning,
            "losing_days": losing,
            "total_days": total,
            "best_day_pct": best,
            "worst_day_pct": worst,
            "avg_daily_return_pct": avg,
        }

    # ── 月累计收益 ───────────────────────────────────────────

    @staticmethod
    def _extract_monthly_cumulative(
        week_data: pd.DataFrame,
        week_start: str,
        full_df: pd.DataFrame,
        result: MultiStrategyResult,
    ) -> Dict[str, Any]:
        """
        提取当月（从月初到本周五）的累计收益。

        返回::

            {
                "month_start": "20260501",
                "cumulative_return_pct": 2.35,
                "per_strategy": {
                    "trend": 2.80,
                    "reversal": 1.50,
                    "grid": 2.10,
                },
            }
        """
        month_start = WeeklyReportExtractor._compute_month_start(week_start)
        month_data = WeeklyReportExtractor._filter_date_range(
            full_df, month_start, week_start
        ).sort_values("date")

        if month_data.empty:
            return {
                "month_start": month_start,
                "cumulative_return_pct": 0.0,
                "per_strategy": {name: 0.0 for name in result.strategies},
            }

        # 组合累计收益
        cum_ret = 0.0
        combined_col = "combined_equity"
        if combined_col in month_data.columns:
            cvals = month_data[combined_col].dropna()
            if len(cvals) >= 1:
                first = cvals.iloc[0]
                last = cvals.iloc[-1]
                if first > 0:
                    cum_ret = round((last - first) / first * 100, 4)

        # 各策略
        per_strategy = {}
        for name in result.strategies:
            col = f"{name}_equity"
            if col in month_data.columns:
                vals = month_data[col].dropna()
                if len(vals) >= 1:
                    first_v = vals.iloc[0]
                    last_v = vals.iloc[-1]
                    if first_v > 0:
                        per_strategy[name] = round(
                            (last_v - first_v) / first_v * 100, 4
                        )
                    else:
                        per_strategy[name] = 0.0
                else:
                    per_strategy[name] = 0.0
            else:
                per_strategy[name] = 0.0

        return {
            "month_start": month_start,
            "cumulative_return_pct": cum_ret,
            "per_strategy": per_strategy,
        }

    # ── 持仓汇总 ─────────────────────────────────────────────

    @staticmethod
    def _extract_holdings(
        week_end: str, result: MultiStrategyResult
    ) -> Dict[str, Any]:
        """
        提取该周最后一个交易日的持仓汇总。

        从 snapshots 中获取期末（<= week_end 的最后一个）持仓。

        返回::

            {
                "per_strategy": {
                    "trend": {
                        "positions": {"003816.SZ": {...}},
                        "total_position_value": 500000.0,
                        "available_cash": 505000.0,
                        "total_equity": 1005000.0,
                    },
                    ...
                },
                "combined_summary": {
                    "total_position_value": 1500000.0,
                    "total_equity": 3075000.0,
                    "position_ratio_pct": 48.78,
                },
            }
        """
        per_strategy = {}

        for name, bt_result in result.backtest_results.items():
            snapshots = bt_result.snapshots
            if not snapshots:
                per_strategy[name] = {
                    "positions": {},
                    "total_position_value": 0.0,
                    "available_cash": 0.0,
                    "total_equity": 0.0,
                }
                continue

            # 找到 <= week_end 的最后一个 snapshot
            last_snapshot = None
            for s in reversed(snapshots):
                if s.get("date", "") <= week_end:
                    last_snapshot = s
                    break

            if not last_snapshot:
                per_strategy[name] = {
                    "positions": {},
                    "total_position_value": 0.0,
                    "available_cash": 0.0,
                    "total_equity": 0.0,
                }
                continue

            # 提取持仓
            positions_raw = last_snapshot.get("positions", {})
            position_value = float(last_snapshot.get("position_market_value", 0))
            total_equity = float(last_snapshot.get("total_equity", 0))

            # 获取可用资金（从 capital snapshot 中）
            capital = last_snapshot.get("capital", {})
            available_cash = float(capital.get("available", 0)) if isinstance(capital, dict) else 0.0

            # 格式化持仓
            positions = {}
            if isinstance(positions_raw, dict):
                for sym, pos_info in positions_raw.items():
                    if isinstance(pos_info, dict):
                        positions[sym] = {
                            "quantity": pos_info.get("quantity", 0),
                            "avg_cost": round(float(pos_info.get("avg_cost", 0)), 4),
                        }

            per_strategy[name] = {
                "positions": positions,
                "total_position_value": round(position_value, 2),
                "available_cash": round(available_cash, 2),
                "total_equity": round(total_equity, 2),
            }

        # 组合汇总
        total_position_value = sum(
            v["total_position_value"] for v in per_strategy.values()
        )
        total_equity = sum(v["total_equity"] for v in per_strategy.values())
        position_ratio = (
            round(total_position_value / total_equity * 100, 2)
            if total_equity > 0
            else 0.0
        )

        return {
            "per_strategy": per_strategy,
            "combined_summary": {
                "total_position_value": round(total_position_value, 2),
                "total_equity": round(total_equity, 2),
                "position_ratio_pct": position_ratio,
            },
        }

    # ── 冲突事件 ─────────────────────────────────────────────

    @staticmethod
    def _extract_weekly_conflicts(
        week_start: str, week_end: str, result: MultiStrategyResult
    ) -> List[Dict[str, Any]]:
        """提取周内信号冲突事件。"""
        return [
            {
                "date": c.date,
                "pair": list(c.pair),
                "direction_1": c.direction_1,
                "direction_2": c.direction_2,
                "price": round(c.price, 4),
                "resolved": c.resolved,
                "resolved_direction": c.resolved_direction,
            }
            for c in result.conflicts
            if week_start <= c.date <= week_end
        ]

    # ── 空结构 ───────────────────────────────────────────────

    @staticmethod
    def _empty_weekly(week_start: str, result: MultiStrategyResult) -> Dict[str, Any]:
        """返回空周报结构（无净值数据时使用）。"""
        return {
            "week_start": week_start,
            "week_end": WeeklyReportExtractor._compute_week_end(week_start),
            "symbol": result.symbol,
            "trading_days_in_week": 0,
            "summary": {
                "per_strategy": {
                    name: {"return_pct": 0.0, "prev_return_pct": 0.0, "change_pct": 0.0}
                    for name in result.strategies
                },
                "combined": {
                    "return_pct": 0.0, "prev_return_pct": 0.0, "change_pct": 0.0,
                },
                "weekly_return_pct": 0.0,
                "prev_weekly_return_pct": 0.0,
                "week_over_week_change": 0.0,
            },
            "trades": {
                "by_strategy": {},
                "summary": {
                    "total_trades": 0, "buy_trades": 0, "sell_trades": 0,
                    "total_volume": 0, "total_fee": 0.0,
                },
            },
            "daily_details": [],
            "win_rate": {
                "daily_win_rate_pct": 0.0, "winning_days": 0, "losing_days": 0,
                "total_days": 0, "best_day_pct": 0.0, "worst_day_pct": 0.0,
                "avg_daily_return_pct": 0.0,
            },
            "monthly_cumulative": {
                "month_start": "",
                "cumulative_return_pct": 0.0,
                "per_strategy": {name: 0.0 for name in result.strategies},
            },
            "holdings": {
                "per_strategy": {},
                "combined_summary": {
                    "total_position_value": 0.0, "total_equity": 0.0, "position_ratio_pct": 0.0,
                },
            },
            "conflicts": [],
        }

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
        验证周报结构的完整性。
        返回缺少的必填键列表。
        """
        required_top = [
            "week_start", "week_end", "symbol",
            "summary", "trades", "daily_details",
            "win_rate", "monthly_cumulative", "holdings",
        ]
        missing = [k for k in required_top if k not in report]

        if "summary" in report:
            for sub in ("weekly_return_pct", "week_over_week_change", "per_strategy"):
                if sub not in report["summary"]:
                    missing.append(f"summary.{sub}")

        if "win_rate" in report:
            if "daily_win_rate_pct" not in report["win_rate"]:
                missing.append("win_rate.daily_win_rate_pct")

        return missing
