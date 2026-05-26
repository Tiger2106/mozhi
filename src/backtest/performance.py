"""
墨枢 - Performance
绩效指标计算：收益率、风险指标、交易统计。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# PerformanceCalculator
# ═══════════════════════════════════════════════════════════════


class PerformanceCalculator:
    """
    回测绩效指标计算器。

    用法::

        calcer = PerformanceCalculator()
        metrics = calcer.compute(equity_curve, initial_capital, trades)
    """

    # 年化因子（假设250个交易日/年）
    TRADING_DAYS: int = 250
    # VaR 置信水平
    VAR_CONFIDENCE: float = 0.95

    def compute(
        self,
        equity_curve: List[Dict[str, float]],
        initial_capital: float,
        trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """计算完整绩效指标。"""
        if not equity_curve:
            return self._empty_result(initial_capital)

        metrics = {}

        # ── 收益率指标 ──────────────────────────────────────
        metrics.update(self._calc_return_metrics(equity_curve, initial_capital))

        # ── 风险指标 ────────────────────────────────────────
        metrics.update(self._calc_risk_metrics(equity_curve))

        # ── 交易统计 ────────────────────────────────────────
        # BUGFIX: 2026-05-16: 将原始订单配对为 round-trip 后再计算盈亏因子
        #         原始 fill-level trades 不含 realized_pnl，直接计算恒为 0
        from .analytics.trade_pairing import pair_trades_to_roundtrips
        paired = pair_trades_to_roundtrips(trades)
        metrics.update(self._calc_trade_stats(paired))

        # ── 基础信息 ────────────────────────────────────────
        metrics["total_trades"] = len(trades)
        metrics["final_equity"] = round(equity_curve[-1]["total_equity"], 2)

        return metrics

    # ── 收益率指标 ─────────────────────────────────────────

    def calc_total_return_pct(
        self, equity_curve: List[Dict[str, float]], initial_capital: float
    ) -> float:
        """总收益率（百分比）。"""
        if not equity_curve:
            return 0.0
        first = equity_curve[0]["total_equity"]
        last = equity_curve[-1]["total_equity"]
        if first == 0:
            return 0.0
        return (last - first) / first * 100.0

    def calc_annual_return_pct(
        self, equity_curve: List[Dict[str, float]], total_return_pct: float
    ) -> float:
        """
        年化收益率（百分比）。

        使用复利公式将总收益率折算到年化。
        """
        n = len(equity_curve)
        if n <= 1:
            return 0.0
        return ((1.0 + total_return_pct / 100.0) ** (self.TRADING_DAYS / n) - 1.0) * 100.0

    def calc_daily_returns(
        self, equity_curve: List[Dict[str, float]]
    ) -> List[float]:
        """日收益率序列。"""
        if len(equity_curve) < 2:
            return []
        daily = []
        prev = equity_curve[0]["total_equity"]
        for pt in equity_curve[1:]:
            eq = pt["total_equity"]
            r = (eq - prev) / prev if prev != 0 else 0.0
            daily.append(r)
            prev = eq
        return daily

    def calc_max_drawdown_pct(
        self, equity_curve: List[Dict[str, float]]
    ) -> float:
        """最大回撤（百分比）。"""
        if not equity_curve:
            return 0.0
        peak = equity_curve[0]["total_equity"]
        max_dd_pct = 0.0
        for pt in equity_curve:
            eq = pt["total_equity"]
            if eq > peak:
                peak = eq
            dd_pct = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
        return max_dd_pct

    def calc_max_drawdown(
        self, equity_curve: List[Dict[str, float]]
    ) -> float:
        """最大回撤（金额）。"""
        if not equity_curve:
            return 0.0
        peak = equity_curve[0]["total_equity"]
        max_dd = 0.0
        for pt in equity_curve:
            eq = pt["total_equity"]
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def calc_calmar_ratio(
        self, annual_return_pct: float, max_drawdown_pct: float
    ) -> float:
        """Calmar比率 = 年化收益率 / 最大回撤百分比。"""
        if max_drawdown_pct == 0:
            return 0.0
        return annual_return_pct / max_drawdown_pct

    def generate_equity_curve(
        self, equity_curve: List[Dict[str, float]]
    ) -> List[Dict[str, float]]:
        """
        收益曲线生成（在原净值曲线上补充累计收益率字段）。
        """
        if not equity_curve:
            return []
        first = equity_curve[0]["total_equity"]
        result = []
        for pt in equity_curve:
            cumulative = (
                (pt["total_equity"] - first) / first * 100.0
                if first != 0
                else 0.0
            )
            result.append(
                {
                    "date": pt["date"],
                    "total_equity": pt["total_equity"],
                    "cumulative_return_pct": round(cumulative, 4),
                }
            )
        return result

    # ── 风险指标 ───────────────────────────────────────────

    def calc_volatility(self, daily_returns: List[float]) -> float:
        """日收益率波动率（标准差）。"""
        if len(daily_returns) < 2:
            return 0.0
        mean = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean) ** 2 for r in daily_returns) / len(daily_returns)
        return math.sqrt(variance)

    def calc_annual_volatility(self, daily_returns: List[float]) -> float:
        """年化波动率。"""
        vol = self.calc_volatility(daily_returns)
        return vol * math.sqrt(self.TRADING_DAYS)

    def calc_downside_volatility(
        self, daily_returns: List[float], target_return: float = 0.0
    ) -> float:
        """
        下行波动率：仅考虑低于目标收益率的负收益样本。
        """
        downside = [r for r in daily_returns if r < target_return]
        if len(downside) < 2:
            return 0.0
        mean = sum(downside) / len(downside)
        variance = sum((r - mean) ** 2 for r in downside) / len(downside)
        return math.sqrt(variance)

    def calc_annual_downside_volatility(
        self, daily_returns: List[float], target_return: float = 0.0
    ) -> float:
        """年化下行波动率。"""
        dv = self.calc_downside_volatility(daily_returns, target_return)
        return dv * math.sqrt(self.TRADING_DAYS)

    def calc_sharpe_ratio(
        self,
        daily_returns: List[float],
        risk_free_rate: float = 0.0,
    ) -> float:
        """
        夏普比率（年化）。

        Sharpe = mean(daily_return - rf) / std(daily_return) * sqrt(250)
        """
        if len(daily_returns) < 2:
            return 0.0
        mean = sum(daily_returns) / len(daily_returns)
        std = self.calc_volatility(daily_returns)
        if std < 1e-12:
            return 0.0
        excess_mean = mean - risk_free_rate / self.TRADING_DAYS
        return (excess_mean / std) * math.sqrt(self.TRADING_DAYS)

    def calc_sortino_ratio(
        self,
        daily_returns: List[float],
        risk_free_rate: float = 0.0,
        target_return: float = 0.0,
    ) -> float:
        """
        索提诺比率（年化）。

        Sortino = mean(daily_return - rf) / downside_std * sqrt(250)
        """
        if len(daily_returns) < 2:
            return 0.0
        mean = sum(daily_returns) / len(daily_returns)
        downs = self.calc_downside_volatility(daily_returns, target_return)
        if downs < 1e-12:
            return 0.0
        excess_mean = mean - risk_free_rate / self.TRADING_DAYS
        return (excess_mean / downs) * math.sqrt(self.TRADING_DAYS)

    def calc_var(self, daily_returns: List[float], confidence: float = 0.95) -> float:
        """
        VaR（Value at Risk）——给定置信水平下的最大预期亏损。

        使用百分位法计算。
        """
        if not daily_returns:
            return 0.0
        sorted_ret = sorted(daily_returns)
        idx = int((1.0 - confidence) * len(sorted_ret))
        idx = max(0, min(idx, len(sorted_ret) - 1))
        return sorted_ret[idx] * 100.0  # 转换为百分比

    # ── 交易统计 ───────────────────────────────────────────

    def calc_win_rate(self, trades: List[Dict[str, Any]]) -> float:
        """
        胜率（%）。

        依据 realized_pnl > 0 判断盈利交易。
        若无法获取 realized_pnl，则按卖出价 > 买入均价粗略判断。
        """
        if not trades:
            return 0.0

        wins = 0
        for t in trades:
            pnl = t.get("realized_pnl")
            if pnl is not None:
                if pnl > 0:
                    wins += 1
            else:
                # 降级判断：卖出交易且价格 > 0 视为盈利
                if t.get("side") in ("sell", "short") and t.get("price", 0) > t.get("avg_buy_price", 0):
                    wins += 1
        return wins / len(trades) * 100.0

    def calc_profit_loss_ratio(self, trades: List[Dict[str, Any]]) -> float:
        """
        盈亏比（平均盈利 / 平均亏损绝对值）。
        """
        profits = []
        losses = []
        for t in trades:
            pnl = t.get("realized_pnl")
            if pnl is not None:
                if pnl > 0:
                    profits.append(pnl)
                elif pnl < 0:
                    losses.append(abs(pnl))

        avg_profit = sum(profits) / len(profits) if profits else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        if avg_loss == 0:
            return 0.0
        return avg_profit / avg_loss

    def calc_profit_factor(self, trades: List[Dict[str, Any]]) -> float:
        """
        盈亏因子（总盈利 / 总亏损绝对值）。
        若总亏损为 0 且总盈利 > 0，返回 999.99 表示极大值；
        若两者均为 0，返回 0.0。
        """
        total_profit = 0.0
        total_loss = 0.0
        for t in trades:
            pnl = t.get("realized_pnl")
            if pnl is not None:
                if pnl > 0:
                    total_profit += pnl
                elif pnl < 0:
                    total_loss += abs(pnl)

        if total_loss == 0:
            return 999.99 if total_profit > 0 else 0.0
        return round(total_profit / total_loss, 4)

    def calc_max_consecutive_wins(self, trades: List[Dict[str, Any]]) -> int:
        """最大连续盈利次数。"""
        max_win = cur_win = 0
        for t in trades:
            pnl = t.get("realized_pnl")
            if pnl is not None and pnl > 0:
                cur_win += 1
                if cur_win > max_win:
                    max_win = cur_win
            else:
                cur_win = 0
        return max_win

    def calc_max_consecutive_losses(self, trades: List[Dict[str, Any]]) -> int:
        """最大连续亏损次数。"""
        max_loss = cur_loss = 0
        for t in trades:
            pnl = t.get("realized_pnl")
            if pnl is not None and pnl < 0:
                cur_loss += 1
                if cur_loss > max_loss:
                    max_loss = cur_loss
            else:
                cur_loss = 0
        return max_loss

    # ── 内部组合方法 ───────────────────────────────────────

    def _calc_return_metrics(
        self,
        equity_curve: List[Dict[str, float]],
        initial_capital: float,
    ) -> Dict[str, Any]:
        total_return = self.calc_total_return_pct(equity_curve, initial_capital)
        annual_return = self.calc_annual_return_pct(equity_curve, total_return)
        max_dd = self.calc_max_drawdown(equity_curve)
        max_dd_pct = self.calc_max_drawdown_pct(equity_curve)
        calmar = self.calc_calmar_ratio(annual_return, max_dd_pct)
        daily_returns = self.calc_daily_returns(equity_curve)
        equity_enhanced = self.generate_equity_curve(equity_curve)

        return {
            "total_return_pct": round(total_return, 4),
            "annual_return_pct": round(annual_return, 4),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 4),
            "calmar_ratio": round(calmar, 4),
            "daily_returns": [round(r, 8) for r in daily_returns],
            "equity_curve": equity_enhanced,
        }

    def _calc_risk_metrics(
        self, equity_curve: List[Dict[str, float]]
    ) -> Dict[str, Any]:
        daily_returns = self.calc_daily_returns(equity_curve)
        sharpe = self.calc_sharpe_ratio(daily_returns)
        vol = self.calc_annual_volatility(daily_returns)
        down_vol = self.calc_annual_downside_volatility(daily_returns)
        sortino = self.calc_sortino_ratio(daily_returns)
        var_95 = self.calc_var(daily_returns, self.VAR_CONFIDENCE)

        return {
            "sharpe_ratio": round(sharpe, 4),
            "volatility": round(vol, 6),
            "downside_volatility": round(down_vol, 6),
            "sortino_ratio": round(sortino, 4),
            "var_95_pct": round(var_95, 4),
        }

    def _calc_trade_stats(
        self, trades: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        win_rate = self.calc_win_rate(trades)
        pl_ratio = self.calc_profit_loss_ratio(trades)
        pf = self.calc_profit_factor(trades)
        max_win = self.calc_max_consecutive_wins(trades)
        max_loss = self.calc_max_consecutive_losses(trades)

        return {
            "win_rate_pct": round(win_rate, 4),
            "profit_loss_ratio": round(pl_ratio, 4),
            "profit_factor": pf,
            "max_consecutive_wins": max_win,
            "max_consecutive_losses": max_loss,
        }

    def _empty_result(self, initial_capital: float) -> Dict[str, Any]:
        return {
            "total_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar_ratio": 0.0,
            "daily_returns": [],
            "equity_curve": [],
            "sharpe_ratio": 0.0,
            "volatility": 0.0,
            "downside_volatility": 0.0,
            "sortino_ratio": 0.0,
            "var_95_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_loss_ratio": 0.0,
            "profit_factor": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "total_trades": 0,
            "final_equity": round(initial_capital, 2),
        }


# ═══════════════════════════════════════════════════════════════
# 交易配对 & 盈亏分布
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# 交易配对 — 从 .analytics.trade_pairing 导入（保持向后兼容）
# ═══════════════════════════════════════════════════════════════
from .analytics.trade_pairing import (  # noqa: F401
    pair_trades_to_roundtrips,
    compute_trade_distribution,
)

# ═══════════════════════════════════════════════════════════════
# Performance  — 旧版兼容别名
# ═══════════════════════════════════════════════════════════════


class Performance(PerformanceCalculator):
    """
    旧版 Performance 兼容类。

    保留静态 compute 方法，以便从 ``backtest_engine.Performance.compute()``
    平滑过渡到 ``PerformanceCalculator().compute()``。
    """

    @staticmethod
    def compute(
        equity_curve: List[Dict[str, float]],
        initial_capital: float,
        trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return PerformanceCalculator().compute(
            equity_curve, initial_capital, trades
        )
