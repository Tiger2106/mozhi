"""
portfolio_manager — 仓位管理桥接

author: 墨衡
version: 1.0.0

将 Method 产生的信号转换为交易订单，跟踪持仓和资金曲线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class Order:
    """交易订单"""
    action: str          # "buy" / "sell"
    symbol: str
    price: float
    shares: int
    timestamp: str = ""


@dataclass
class TradeRecord:
    """成交记录"""
    action: str
    symbol: str
    price: float
    shares: int
    cash_after: float
    position_after: int
    timestamp: str = ""


class PortfolioManager:
    """仓位管理桥接

    接收信号 → 生成订单 → 更新持仓 → 记录权益曲线。

    Args:
        initial_cash: 初始资金（默认 1,000,000）
        commission_pct: 手续费比例（默认 0.0003 = 万三）
        slippage_pct: 滑点比例（默认 0.001 = 0.1%）

    Examples:
        >>> pm = PortfolioManager(initial_cash=1000000.0)
        >>> order = pm.process_signal(1, 50.0)
        >>> order.action
        'buy'
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission_pct: float = 0.0003,
        slippage_pct: float = 0.001,
    ):
        self.initial_cash = initial_cash
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct

        self.cash: float = initial_cash
        self.positions: Dict[str, int] = {}  # {symbol: shares}
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[float] = []
        self._current_price: Optional[float] = None

    def process_signal(
        self,
        signal: int,
        price: float,
        symbol: str = "DEFAULT",
        bar_info: Any = None,
        position_ratio: float = 1.0,
    ) -> Order:
        """处理信号，生成订单

        Args:
            signal: -1=卖出, 0=持有, 1=买入
            price:  当期价格
            symbol: 标的代码
            bar_info: 可选 K 线信息
            position_ratio: 仓位比例 [0, 1]（默认 1.0=全仓）。
                            由 RiskPipeline 计算得出，受 ATR/市场状态影响。

        Returns:
            Order: 生成的订单（或持有/不可操作的订单）
        """
        self._current_price = price

        if signal == 0:
            return Order(action="hold", symbol=symbol, price=price, shares=0)

        if signal == 1:  # 买入
            pos = self.positions.get(symbol, 0)
            if pos > 0:
                return Order(action="hold", symbol=symbol, price=price, shares=0)

            # 受 position_ratio 约束的资金分配
            actual_price = price * (1 + self.slippage_pct)
            allocated_cash = self.cash * max(0.0, min(1.0, position_ratio))
            max_shares = int(allocated_cash * (1 - self.commission_pct) // actual_price)
            if max_shares <= 0:
                return Order(action="hold", symbol=symbol, price=price, shares=0)

            cost = actual_price * max_shares
            commission = cost * self.commission_pct
            self.cash -= (cost + commission)
            self.positions[symbol] = self.positions.get(symbol, 0) + max_shares

            self.trades.append(TradeRecord(
                action="buy", symbol=symbol, price=price,
                shares=max_shares, cash_after=self.cash,
                position_after=self.positions[symbol],
            ))
            return Order(action="buy", symbol=symbol, price=price, shares=max_shares)

        if signal == -1:  # 卖出
            pos = self.positions.get(symbol, 0)
            if pos <= 0:
                return Order(action="hold", symbol=symbol, price=price, shares=0)

            actual_price = price * (1 - self.slippage_pct)
            revenue = actual_price * pos
            commission = revenue * self.commission_pct
            self.cash += (revenue - commission)
            self.positions[symbol] = 0

            self.trades.append(TradeRecord(
                action="sell", symbol=symbol, price=price,
                shares=pos, cash_after=self.cash,
                position_after=0,
            ))
            return Order(action="sell", symbol=symbol, price=price, shares=pos)

        return Order(action="hold", symbol=symbol, price=price, shares=0)

    def record_equity(self, current_price: float) -> None:
        """记录当前权益"""
        total_value = self.get_portfolio_value(current_price)
        self.equity_curve.append(total_value)

    def get_portfolio_value(self, current_price: float) -> float:
        """计算组合市值: 现金 + 持仓市值"""
        position_value = sum(
            shares * current_price for shares in self.positions.values()
        )
        return self.cash + position_value

    def get_total_return(self) -> float:
        """计算总收益率"""
        if not self.equity_curve:
            return 0.0
        final = self.equity_curve[-1]
        return (final - self.initial_cash) / self.initial_cash

    def get_peak_drawdown(self) -> float:
        """计算最大回撤"""
        if len(self.equity_curve) < 2:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for v in self.equity_curve:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def reset(self) -> None:
        """重置为初始状态"""
        self.cash = self.initial_cash
        self.positions.clear()
        self.trades.clear()
        self.equity_curve.clear()
        self._current_price = None

    def summary(self) -> Dict[str, Any]:
        """汇总报告"""
        return {
            "initial_cash": self.initial_cash,
            "final_cash": self.cash,
            "positions": dict(self.positions),
            "total_trades": len(self.trades),
            "total_return": self.get_total_return(),
            "max_drawdown": self.get_peak_drawdown(),
        }
