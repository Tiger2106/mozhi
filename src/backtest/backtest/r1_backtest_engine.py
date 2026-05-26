"""
墨枢 - R1BacktestEngine（R1 阶段二：任务8）

R1 研究方法回测引擎。

功能：
  - 运行任意 method 配置的回测
  - 输出净值曲线、交易记录、胜率、盈亏比等绩效指标

依赖:
  - src.backtest.models.signal_types — R1Signal
  - src.backtest.methods.breakout_retest  — run_breakout_retest (et al.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.models.signal_types import R1Signal
from src.backtest.methods.breakout_retest import run_breakout_retest
from src.backtest.methods.continuation import run_continuation
from src.backtest.methods.volume_price_expansion import run_vpe


# ─── 方法注册 ────────────────────────────────────────────────

METHOD_MAP: Dict[str, Callable] = {
    "breakout_retest": run_breakout_retest,
    "continuation": run_continuation,
    "volume_price_expansion": run_vpe,
}


# ─── Trade Record ────────────────────────────────────────────

@dataclass
class TradeRecord:
    """单笔交易记录"""
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    direction: int           # 1=long, -1=short
    quantity: float          # 标准化仓位
    pnl: float               # 盈亏金额
    pnl_pct: float           # 盈亏百分比
    hold_bars: int           # 持仓K线数
    exit_reason: str = "signal"   # 平仓原因

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "direction": self.direction,
            "quantity": round(self.quantity, 2),
            "pnl": round(self.pnl, 4),
            "pnl_pct": round(self.pnl_pct, 4),
            "hold_bars": self.hold_bars,
            "exit_reason": self.exit_reason,
        }


# ─── 回测结果 ────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """回测执行结果"""
    symbol: str
    method: str
    start: str
    end: str
    total_bars: int
    trades: List[TradeRecord]
    equity_curve: List[Dict[str, float]]
    metrics: Dict[str, float]
    execution_time_ms: float = 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return round(wins / len(self.trades), 4)

    @property
    def avg_pnl_pct(self) -> float:
        if not self.trades:
            return 0.0
        return round(float(np.mean([t.pnl_pct for t in self.trades])), 4)

    @property
    def profit_factor(self) -> float:
        if not self.trades:
            return 0.0
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        if gross_loss == 0:
            return 999.0
        return round(gross_profit / gross_loss, 4)

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        navs = [e.get("nav", 1.0) for e in self.equity_curve]
        peak = navs[0]
        max_dd = 0.0
        for n in navs:
            if n > peak:
                peak = n
            dd = (peak - n) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "method": self.method,
            "start": self.start,
            "end": self.end,
            "total_bars": self.total_bars,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "avg_pnl_pct": self.avg_pnl_pct,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "metrics": self.metrics,
            "trades": [t.to_dict() for t in self.trades],
            "equity_curve": self.equity_curve,
        }


# ─── R1BacktestEngine ────────────────────────────────────────

class R1BacktestEngine:
    """R1 研究方法回测引擎。

    支持运行任意已注册的 method，并计算完整回测绩效。
    """

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.initial_capital = initial_capital

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        method: str,
        start: str = "",
        end: str = "",
        method_kwargs: Optional[Dict[str, Any]] = None,
        exit_after_bars: int = 10,
        stop_loss_pct: float = 0.05,
    ) -> BacktestResult:
        """执行回测。

        Args:
            df: OHLCV DataFrame，需含 'close', 'high', 'low', 'volume' 列
            symbol: 标的代码
            method: 方法名（'breakout_retest', 'continuation', 'volume_price_expansion'）
            start: 回测开始日期（YYYY-MM-DD，默认从数据起始）
            end: 回测结束日期（YYYY-MM-DD，默认到数据结束）
            method_kwargs: 传递给 method 的额外参数
            exit_after_bars: 持仓最大K线数
            stop_loss_pct: 止损百分比

        Returns:
            BacktestResult
        """
        import time
        t0 = time.time()

        if method not in METHOD_MAP:
            raise ValueError(f"未知方法: {method}，可用: {list(METHOD_MAP.keys())}")

        # ── 日期过滤 ────────────────────────────────────
        df_filtered = df.copy()
        if isinstance(df_filtered.index, pd.DatetimeIndex):
            if start:
                df_filtered = df_filtered[df_filtered.index >= start]
            if end:
                df_filtered = df_filtered[df_filtered.index <= end]
        else:
            # 按行过滤
            if start:
                df_filtered = df_filtered.iloc[int(start):] if start.isdigit() else df_filtered
            if end:
                df_filtered = df_filtered.iloc[:int(end)] if end.isdigit() else df_filtered

        if df_filtered.empty:
            raise ValueError("过滤后无数据")

        # ── 生成信号 ────────────────────────────────────
        kwargs = method_kwargs or {}
        fn = METHOD_MAP[method]
        signals = fn(df_filtered, **kwargs)

        # ── 交易模拟 ────────────────────────────────────
        trades: List[TradeRecord] = []
        equity_curve: List[Dict[str, float]] = []
        position = 0.0  # 持仓方向：1=多, -1=空, 0=空仓
        entry_price = 0.0
        entry_bar = 0
        entry_time = ""
        quantity = 1.0  # 标准化仓位

        # 建立信号索引
        signal_bars: Dict[int, R1Signal] = {}
        for sig in signals:
            # 通过时间戳查找 df 索引
            if isinstance(df_filtered.index, pd.DatetimeIndex) and isinstance(sig.timestamp, datetime):
                matches = np.where(df_filtered.index == sig.timestamp)[0]
                if len(matches) > 0:
                    signal_bars[int(matches[0])] = sig
            elif hasattr(sig.timestamp, 'strftime'):
                ts_str = sig.timestamp.strftime('%Y-%m-%d')
                matches = np.where(df_filtered.index.astype(str).str.startswith(ts_str))[0]
                if len(matches) > 0:
                    signal_bars[int(matches[0])] = sig

        # ── Bar 循环 ────────────────────────────────────
        for i in range(len(df_filtered)):
            row = df_filtered.iloc[i]
            close = float(row['close'])
            timestamp = str(df_filtered.index[i]) if isinstance(df_filtered.index, pd.DatetimeIndex) else str(i)

            # 更新净值
            nav = 1.0 + (close - entry_price) / entry_price * position if entry_price > 0 and position != 0 else 1.0
            # 实际净值以初始资金 + 已实现盈亏 + 未实现盈亏计算
            realized_pnl = sum(t.pnl for t in trades)
            unrealized = (close - entry_price) * position * quantity if position != 0 else 0.0
            equity = (self.initial_capital + realized_pnl + unrealized) / self.initial_capital

            equity_curve.append({"date": timestamp, "nav": round(equity, 6)})

            # ── 持仓管理 ────────────────────────────────
            if position != 0:
                # 止盈/止损检查
                pnl_pct = (close - entry_price) / entry_price if entry_price > 0 else 0.0
                if position < 0:
                    pnl_pct = -pnl_pct
                if abs(pnl_pct) >= stop_loss_pct:
                    trades.append(TradeRecord(
                        entry_time=entry_time,
                        exit_time=timestamp,
                        entry_price=entry_price,
                        exit_price=close,
                        direction=position,
                        quantity=quantity,
                        pnl=(close - entry_price) * position,
                        pnl_pct=pnl_pct,
                        hold_bars=i - entry_bar,
                        exit_reason="stop_loss",
                    ))
                    position = 0.0
                    continue

                # 最大持仓K线数退出
                if i - entry_bar >= exit_after_bars:
                    trades.append(TradeRecord(
                        entry_time=entry_time,
                        exit_time=timestamp,
                        entry_price=entry_price,
                        exit_price=close,
                        direction=position,
                        quantity=quantity,
                        pnl=(close - entry_price) * position,
                        pnl_pct=pnl_pct,
                        hold_bars=i - entry_bar,
                        exit_reason="max_hold",
                    ))
                    position = 0.0
                    continue

            # ── 开仓检查 ────────────────────────────────
            if position == 0 and i in signal_bars:
                sig = signal_bars[i]
                if sig.direction != 0:
                    position = float(sig.direction)
                    entry_price = close
                    entry_bar = i
                    entry_time = timestamp

        # ── 收盘平仓 ────────────────────────────────────
        if position != 0 and len(equity_curve) > 0:
            last_close = float(df_filtered['close'].iloc[-1])
            pnl_pct = (last_close - entry_price) / entry_price if entry_price > 0 else 0.0
            if position < 0:
                pnl_pct = -pnl_pct
            trades.append(TradeRecord(
                entry_time=entry_time,
                exit_time=str(df_filtered.index[-1]) if isinstance(df_filtered.index, pd.DatetimeIndex) else str(len(df_filtered)),
                entry_price=entry_price,
                exit_price=last_close,
                direction=position,
                quantity=quantity,
                pnl=(last_close - entry_price) * position,
                pnl_pct=pnl_pct,
                hold_bars=len(df_filtered) - entry_bar,
                exit_reason="end_of_data",
            ))

        # ── 绩效计算 ────────────────────────────────────
        metrics = self._calc_metrics(trades, equity_curve)

        elapsed = (time.time() - t0) * 1000

        return BacktestResult(
            symbol=symbol,
            method=method,
            start=str(df_filtered.index[0]) if isinstance(df_filtered.index, pd.DatetimeIndex) else "0",
            end=str(df_filtered.index[-1]) if isinstance(df_filtered.index, pd.DatetimeIndex) else str(len(df_filtered)),
            total_bars=len(df_filtered),
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
            execution_time_ms=elapsed,
        )

    # ─── 绩效指标 ────────────────────────────────────────

    @staticmethod
    def _calc_metrics(
        trades: List[TradeRecord],
        equity_curve: List[Dict[str, float]],
    ) -> Dict[str, float]:
        """计算绩效指标"""
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_pnl_pct": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "total_return_pct": 0.0,
                "sharpe_approx": 0.0,
            }

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        avg_pnl_pct = float(np.mean([t.pnl_pct for t in trades]))
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        # 最大回撤
        max_dd = 0.0
        if equity_curve:
            navs = [e.get("nav", 1.0) for e in equity_curve]
            peak = navs[0]
            for n in navs:
                if n > peak:
                    peak = n
                dd = (peak - n) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)

        total_return = (navs[-1] - 1.0) * 100 if equity_curve else 0.0

        # 近似夏普比
        daily_returns = []
        if equity_curve:
            navs = [e.get("nav", 1.0) for e in equity_curve]
            for i in range(1, len(navs)):
                daily_returns.append(navs[i] / navs[i - 1] - 1.0)
        sharpe = 0.0
        if daily_returns and len(daily_returns) > 1:
            avg_ret = float(np.mean(daily_returns))
            std_ret = float(np.std(daily_returns))
            if std_ret > 0:
                sharpe = avg_ret / std_ret * np.sqrt(252)  # 年化

        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 4),
            "avg_pnl_pct": round(avg_pnl_pct, 4),
            "profit_factor": round(profit_factor, 4),
            "max_drawdown": round(max_dd, 4),
            "total_return_pct": round(total_return, 4),
            "sharpe_approx": round(float(sharpe), 4),
        }
