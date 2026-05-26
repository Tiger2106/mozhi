"""
墨枢 - OrderExecutor
订单执行引擎：市价单/限价单/部分成交逻辑/成交记录。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .backtest_context import BacktestContext
from .capital_manager import CapitalManager
from .position_manager import PositionManager


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class TradeRecord:
    """单笔成交记录。"""
    date: str
    symbol: str
    side: OrderSide
    price: float
    quantity: int
    fee: float
    slippage: float = 0.0
    order_type: OrderType = OrderType.MARKET

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": round(self.price, 4),
            "quantity": self.quantity,
            "fee": round(self.fee, 2),
            "slippage": round(self.slippage, 4),
            "order_type": self.order_type.value,
        }


@dataclass
class FillReport:
    """订单执行结果报告。"""
    filled: bool
    fill_price: float
    fill_quantity: int
    fill_fee: float
    partial: bool = False                # 是否部分成交
    remaining: int = 0                   # 未成交数量
    trade: Optional[TradeRecord] = None
    message: str = ""

    @property
    def is_full_fill(self) -> bool:
        return self.filled and not self.partial

    @property
    def is_partial_fill(self) -> bool:
        return self.filled and self.partial


@dataclass
class OrderExecutor:
    """
    订单执行器，支持市价单和限价单。

    依赖 BacktestContext（包含 CapitalManager 和 PositionManager）。
    """

    context: BacktestContext
    slippage_rate: float = 0.001        # 默认 0.1% 滑点
    fee_rate: float = 0.0003            # 默认 0.03% 手续费
    min_fee: float = 5.0                # 最低手续费（元）

    # ── 成交记录 ────────────────────────────────────────────
    trade_history: List[TradeRecord] = field(default_factory=list)

    # ── 市价单执行 ──────────────────────────────────────────

    def execute_market(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        fee_rate: Optional[float] = None,
    ) -> FillReport:
        """
        执行市价单：立即按当前价格（经滑点调整）成交。

        参数
        ----------
        symbol : str
            标的代码。
        side : OrderSide
            买卖方向。
        quantity : int
            委托数量。
        price : float
            当前市场价格。
        fee_rate : float, optional
            手续费率，默认使用 self.fee_rate。

        返回
        -------
        FillReport
            成交报告。
        """
        fr = fee_rate if fee_rate is not None else self.fee_rate

        # 滑点调整价格
        if side == OrderSide.BUY:
            fill_price = price * (1 + self.slippage_rate)
        else:
            fill_price = price * (1 - self.slippage_rate)

        fill_price = round(fill_price, 4)
        fee = max(fill_price * quantity * fr, self.min_fee)
        turnover = fill_price * quantity + fee

        # 资金 / 持仓检查
        if side == OrderSide.BUY:
            return self._execute_market_buy(
                symbol, quantity, fill_price, fee, turnover, fr
            )
        else:
            return self._execute_market_sell(
                symbol, quantity, fill_price, fee, fr
            )

    def _execute_market_buy(
        self,
        symbol: str,
        quantity: int,
        fill_price: float,
        fee: float,
        turnover: float,
        fee_rate: float,
    ) -> FillReport:
        cap = self.context.capital

        if not self.context.check_sufficient_capital(turnover):
            # 计算可用资金能买多少
            max_qty = int(
                (cap.available - self.min_fee) // (fill_price * (1 + fee_rate))
            )
            if max_qty <= 0:
                return FillReport(
                    filled=False,
                    fill_price=fill_price,
                    fill_quantity=0,
                    fill_fee=0.0,
                    message="可用资金不足",
                )
            # 部分成交
            quantity = max_qty
            fee = max(fill_price * quantity * fee_rate, self.min_fee)
            turnover = fill_price * quantity + fee
            partial = True
        else:
            partial = False

        # 冻结资金 → 扣除
        try:
            cap.freeze(turnover)
            cap.deduct(turnover)
        except ValueError as e:
            return FillReport(
                filled=False,
                fill_price=fill_price,
                fill_quantity=0,
                fill_fee=0.0,
                message=str(e),
            )

        # 开仓
        self.context.positions.open_position(symbol, quantity, fill_price, fee)

        trade = TradeRecord(
            date=self.context.current_date or "",
            symbol=symbol,
            side=OrderSide.BUY,
            price=fill_price,
            quantity=quantity,
            fee=fee,
            slippage=self.slippage_rate,
            order_type=OrderType.MARKET,
        )
        self.trade_history.append(trade)

        remaining = 0
        if partial:
            # 解冻剩余未成交部分 - 由于我们已经全部冻结后扣除实际部分，
            # 无多余需解冻
            pass

        return FillReport(
            filled=True,
            fill_price=fill_price,
            fill_quantity=quantity,
            fill_fee=fee,
            partial=partial,
            remaining=remaining,
            trade=trade,
            message="市价买入成交"
            + ("（部分成交）" if partial else "（全部成交）"),
        )

    def _execute_market_sell(
        self,
        symbol: str,
        quantity: int,
        fill_price: float,
        fee: float,
        fee_rate: float,
    ) -> FillReport:
        pos_mgr = self.context.positions

        if not pos_mgr.has_position(symbol):
            return FillReport(
                filled=False,
                fill_price=fill_price,
                fill_quantity=0,
                fill_fee=0.0,
                message="无持仓，无法卖出",
            )

        pos = pos_mgr.get(symbol)
        if pos.quantity < quantity:
            # 部分成交：只能卖出持有的数量
            quantity = pos.quantity
            fee = max(fill_price * quantity * fee_rate, self.min_fee)
            partial = True
        else:
            partial = False

        realized_pnl, revenue = pos_mgr.close_position(
            symbol, quantity, fill_price, fee
        )
        self.context.capital.add(revenue)

        trade = TradeRecord(
            date=self.context.current_date or "",
            symbol=symbol,
            side=OrderSide.SELL,
            price=fill_price,
            quantity=quantity,
            fee=fee,
            slippage=self.slippage_rate,
            order_type=OrderType.MARKET,
        )
        self.trade_history.append(trade)

        return FillReport(
            filled=True,
            fill_price=fill_price,
            fill_quantity=quantity,
            fill_fee=fee,
            partial=partial,
            remaining=0,
            trade=trade,
            message="市价卖出成交"
            + ("（部分成交）" if partial else "（全部成交）"),
        )

    # ── 限价单执行 ──────────────────────────────────────────

    def execute_limit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        limit_price: float,
        current_price: float,
        fee_rate: Optional[float] = None,
    ) -> FillReport:
        """
        执行限价单：检查价格是否触发。

        买入：当前价 <= 限价时触发
        卖出：当前价 >= 限价时触发
        """
        # 检查价格条件
        triggered = False
        if side == OrderSide.BUY and current_price <= limit_price:
            triggered = True
        elif side == OrderSide.SELL and current_price >= limit_price:
            triggered = True

        if not triggered:
            return FillReport(
                filled=False,
                fill_price=0.0,
                fill_quantity=0,
                fill_fee=0.0,
                message=f"限价单未触发: limit={limit_price}, current={current_price}",
            )

        # 已触发，按限价成交（无额外滑点）
        return self._execute_at_price(
            symbol, side, quantity, limit_price, fee_rate
        )

    def _execute_at_price(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        fee_rate: Optional[float] = None,
    ) -> FillReport:
        """以指定价格执行（限价单触发后使用）。"""
        fr = fee_rate if fee_rate is not None else self.fee_rate
        fee = max(price * quantity * fr, self.min_fee)
        turnover = price * quantity + fee

        if side == OrderSide.BUY:
            return self._execute_limit_buy(symbol, quantity, price, fee, turnover, fr)
        else:
            return self._execute_limit_sell(symbol, quantity, price, fee, fr)

    def _execute_limit_buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        fee: float,
        turnover: float,
        fee_rate: float,
    ) -> FillReport:
        cap = self.context.capital

        if not self.context.check_sufficient_capital(turnover):
            max_qty = int(
                (cap.available - self.min_fee) // (price * (1 + fee_rate))
            )
            if max_qty <= 0:
                return FillReport(
                    filled=False,
                    fill_price=price,
                    fill_quantity=0,
                    fill_fee=0.0,
                    message="限价买入可用资金不足",
                )
            quantity = max_qty
            fee = max(price * quantity * fee_rate, self.min_fee)
            turnover = price * quantity + fee
            partial = True
        else:
            partial = False

        try:
            cap.freeze(turnover)
            cap.deduct(turnover)
        except ValueError as e:
            return FillReport(
                filled=False,
                fill_price=price,
                fill_quantity=0,
                fill_fee=0.0,
                message=str(e),
            )

        self.context.positions.open_position(symbol, quantity, price, fee)

        trade = TradeRecord(
            date=self.context.current_date or "",
            symbol=symbol,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            fee=fee,
            slippage=0.0,
            order_type=OrderType.LIMIT,
        )
        self.trade_history.append(trade)

        return FillReport(
            filled=True,
            fill_price=price,
            fill_quantity=quantity,
            fill_fee=fee,
            partial=partial,
            remaining=0,
            trade=trade,
            message="限价买入成交" + ("（部分成交）" if partial else ""),
        )

    def _execute_limit_sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        fee: float,
        fee_rate: float,
    ) -> FillReport:
        pos_mgr = self.context.positions

        if not pos_mgr.has_position(symbol):
            return FillReport(
                filled=False,
                fill_price=price,
                fill_quantity=0,
                fill_fee=0.0,
                message="无持仓，限价卖出失败",
            )

        pos = pos_mgr.get(symbol)
        if pos.quantity < quantity:
            quantity = pos.quantity
            fee = max(price * quantity * fee_rate, self.min_fee)
            partial = True
        else:
            partial = False

        realized_pnl, revenue = pos_mgr.close_position(
            symbol, quantity, price, fee
        )
        self.context.capital.add(revenue)

        trade = TradeRecord(
            date=self.context.current_date or "",
            symbol=symbol,
            side=OrderSide.SELL,
            price=price,
            quantity=quantity,
            fee=fee,
            slippage=0.0,
            order_type=OrderType.LIMIT,
        )
        self.trade_history.append(trade)

        return FillReport(
            filled=True,
            fill_price=price,
            fill_quantity=quantity,
            fill_fee=fee,
            partial=partial,
            remaining=0,
            trade=trade,
            message="限价卖出成交" + ("（部分成交）" if partial else ""),
        )

    # ── 工具 ────────────────────────────────────────────────

    def get_trade_history(self) -> List[Dict[str, Any]]:
        """获取成交记录列表（字典格式）。"""
        return [t.to_dict() for t in self.trade_history]

    def clear_trade_history(self) -> None:
        """清空成交记录。"""
        self.trade_history.clear()
