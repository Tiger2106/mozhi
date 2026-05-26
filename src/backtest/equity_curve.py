"""
墨枢 - EquityCurve
净值曲线生成器：从交易流水重建日净值，叠加基准对比与超额收益。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EquityPoint:
    """单日净值点"""

    date: str
    nav: float                     # 单位净值（初始 = 1.0）
    total_equity: float            # 总权益（金额）
    daily_return_pct: float        # 日收益率 (%)
    cumulative_return_pct: float   # 累计收益率 (%)
    benchmark_nav: Optional[float] = None      # 基准净值
    benchmark_return_pct: Optional[float] = None    # 基准日收益率
    benchmark_cumulative_pct: Optional[float] = None  # 基准累计收益率
    excess_return_pct: Optional[float] = None   # 超额日收益率
    excess_cumulative_pct: Optional[float] = None    # 超额累计收益率

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "nav": round(self.nav, 6),
            "total_equity": round(self.total_equity, 2),
            "daily_return_pct": round(self.daily_return_pct, 4),
            "cumulative_return_pct": round(self.cumulative_return_pct, 4),
            "benchmark_nav": round(self.benchmark_nav, 6) if self.benchmark_nav is not None else None,
            "benchmark_return_pct": round(self.benchmark_return_pct, 4) if self.benchmark_return_pct is not None else None,
            "benchmark_cumulative_pct": round(self.benchmark_cumulative_pct, 4) if self.benchmark_cumulative_pct is not None else None,
            "excess_return_pct": round(self.excess_return_pct, 4) if self.excess_return_pct is not None else None,
            "excess_cumulative_pct": round(self.excess_cumulative_pct, 4) if self.excess_cumulative_pct is not None else None,
        }


@dataclass
class EquityCurveResult:
    """净值曲线生成结果"""

    points: List[EquityPoint]
    initial_capital: float
    final_nav: float
    total_return_pct: float
    benchmark_total_return_pct: Optional[float] = None
    excess_total_return_pct: Optional[float] = None
    annual_return_pct: float = 0.0
    annual_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "points": [p.to_dict() for p in self.points],
            "initial_capital": round(self.initial_capital, 2),
            "final_nav": round(self.final_nav, 6),
            "total_return_pct": round(self.total_return_pct, 4),
            "benchmark_total_return_pct": round(self.benchmark_total_return_pct, 4)
            if self.benchmark_total_return_pct is not None
            else None,
            "excess_total_return_pct": round(self.excess_total_return_pct, 4)
            if self.excess_total_return_pct is not None
            else None,
            "annual_return_pct": round(self.annual_return_pct, 4),
            "annual_volatility": round(self.annual_volatility, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
        }


# ═══════════════════════════════════════════════════════════════
# EquityCurveGenerator
# ═══════════════════════════════════════════════════════════════


class EquityCurveGenerator:
    """
    净值曲线生成器。

    从 equity_curve（回测引擎输出的日净值序列）或从 TradeLogger 快照
    生成标准化的净值曲线，支持基准对比和超额收益计算。
    """

    TRADING_DAYS: int = 250  # 年化因子

    def __init__(self, initial_capital: float = 1_000_000.0):
        self._initial_capital = initial_capital

    # ── 主入口 ──────────────────────────────────────────────

    def build(
        self,
        equity_curve: List[Dict[str, float]],
        benchmark_curve: Optional[List[Dict[str, float]]] = None,
    ) -> EquityCurveResult:
        """
        从回测引擎输出的 equity_curve 构建净值曲线。

        参数
        ----------
        equity_curve : List[Dict[str, float]]
            日净值序列 [{"date": str, "total_equity": float}, ...]
            （必须按日期升序排列）
        benchmark_curve : List[Dict[str, float]], optional
            基准净值序列 [{"date": str, "nav": float}, ...]
            日期必须是 equity_curve 的子集或超集

        返回
        -------
        EquityCurveResult
        """
        if not equity_curve:
            return self._empty_result()

        points = []
        benchmark_index: Dict[str, float] = {}
        if benchmark_curve:
            benchmark_index = {b["date"]: b["nav"] for b in benchmark_curve}

        first_equity = equity_curve[0]["total_equity"]
        prev_equity = first_equity
        benchmark_start_nav = None

        for i, pt in enumerate(equity_curve):
            date = pt["date"]
            equity = pt["total_equity"]

            # NAV
            nav = equity / self._initial_capital

            # 日收益率
            if i == 0:
                daily_ret = 0.0
            else:
                daily_ret = (equity - prev_equity) / prev_equity * 100.0

            # 累计收益率
            cum_ret = (equity - self._initial_capital) / self._initial_capital * 100.0

            # 基准
            bench_nav = benchmark_index.get(date)
            bench_daily_ret = None
            bench_cum_ret = None
            excess_daily = None
            excess_cum = None

            if bench_nav is not None:
                if benchmark_start_nav is None:
                    benchmark_start_nav = bench_nav

                # 基准日收益率（用前一日基准净值计算）
                if i > 0 and benchmark_start_nav is not None:
                    prev_date = equity_curve[i - 1]["date"]
                    prev_bench = benchmark_index.get(prev_date)
                    if prev_bench is not None and prev_bench > 0:
                        bench_daily_ret = (bench_nav - prev_bench) / prev_bench * 100.0

                bench_cum_ret = (
                    (bench_nav - benchmark_start_nav) / benchmark_start_nav * 100.0
                )

                # 超额
                if bench_daily_ret is not None:
                    excess_daily = daily_ret - bench_daily_ret
                if bench_cum_ret is not None:
                    excess_cum = cum_ret - bench_cum_ret

            point = EquityPoint(
                date=date,
                nav=nav,
                total_equity=equity,
                daily_return_pct=daily_ret,
                cumulative_return_pct=cum_ret,
                benchmark_nav=bench_nav,
                benchmark_return_pct=bench_daily_ret,
                benchmark_cumulative_pct=bench_cum_ret,
                excess_return_pct=excess_daily,
                excess_cumulative_pct=excess_cum,
            )
            points.append(point)
            prev_equity = equity

        # ── 汇总指标 ──────────────────────────────────────────
        result = self._compute_summary(points, benchmark_start_nav)
        return result

    def build_from_snapshots(
        self,
        snapshots: List[Any],
        benchmark_curve: Optional[List[Dict[str, float]]] = None,
    ) -> EquityCurveResult:
        """
        从 TradeLogger / DailySnapshot 列表构建净值曲线。

        参数
        ----------
        snapshots : List[DailySnapshot] | List[dict]
            快照列表（需有 date / total_equity 或 to_dict()）
        benchmark_curve : List[Dict[str, float]], optional
            基准净值序列

        返回
        -------
        EquityCurveResult
        """
        equity_curve: List[Dict[str, float]] = []
        for snap in snapshots:
            if hasattr(snap, "total_equity"):
                equity_curve.append(
                    {"date": snap.date, "total_equity": snap.total_equity}
                )
            elif isinstance(snap, dict):
                equity_curve.append(
                    {"date": snap["date"], "total_equity": snap["total_equity"]}
                )
        return self.build(equity_curve, benchmark_curve)

    # ── 内部计算 ────────────────────────────────────────────

    def _compute_summary(
        self,
        points: List[EquityPoint],
        benchmark_start_nav: Optional[float],
    ) -> EquityCurveResult:
        """从 EquityPoints 列表计算汇总指标。"""
        if not points:
            return self._empty_result()

        # 基本指标
        final_nav = points[-1].nav
        total_return = points[-1].cumulative_return_pct

        # 年化收益率
        n = len(points)
        annual_return = (
            (1.0 + total_return / 100.0) ** (self.TRADING_DAYS / n) - 1.0
        ) * 100.0 if n > 1 else 0.0

        # 年化波动率
        daily_returns = [p.daily_return_pct / 100.0 for p in points[1:]]
        vol = 0.0
        sharpe = 0.0
        if len(daily_returns) >= 2:
            mean_ret = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
            vol = math.sqrt(variance) * math.sqrt(self.TRADING_DAYS)

            # 夏普（假设无风险利率 0）
            if vol > 1e-12:
                sharpe = (mean_ret / (vol / math.sqrt(self.TRADING_DAYS))) * math.sqrt(self.TRADING_DAYS)

        # 最大回撤
        max_dd_pct = 0.0
        peak = points[0].nav
        for p in points:
            if p.nav > peak:
                peak = p.nav
            dd = (peak - p.nav) / peak * 100.0
            if dd > max_dd_pct:
                max_dd_pct = dd

        # 基准总收益
        bench_total_ret = None
        if benchmark_start_nav is not None:
            # 找最后一个有基准净值的点
            last_bench = None
            for p in reversed(points):
                if p.benchmark_nav is not None:
                    last_bench = p.benchmark_nav
                    break
            if last_bench is not None:
                bench_total_ret = (last_bench - benchmark_start_nav) / benchmark_start_nav * 100.0

        # 超额总收益
        excess_total = None
        if total_return is not None and bench_total_ret is not None:
            excess_total = total_return - bench_total_ret

        return EquityCurveResult(
            points=points,
            initial_capital=self._initial_capital,
            final_nav=final_nav,
            total_return_pct=total_return,
            benchmark_total_return_pct=bench_total_ret,
            excess_total_return_pct=excess_total,
            annual_return_pct=annual_return,
            annual_volatility=vol,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd_pct,
        )

    def _empty_result(self) -> EquityCurveResult:
        return EquityCurveResult(
            points=[],
            initial_capital=self._initial_capital,
            final_nav=1.0,
            total_return_pct=0.0,
        )


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def build_equity_curve(
    equity_curve: List[Dict[str, float]],
    initial_capital: float = 1_000_000.0,
    benchmark_curve: Optional[List[Dict[str, float]]] = None,
) -> EquityCurveResult:
    """便捷函数：一行调用生成净值曲线。"""
    gen = EquityCurveGenerator(initial_capital)
    return gen.build(equity_curve, benchmark_curve)
