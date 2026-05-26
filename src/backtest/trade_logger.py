"""
墨枢 - TradeLogger
持仓记录器：每笔交易流水 + 每日持仓快照。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 数据容器
# ═══════════════════════════════════════════════════════════════


@dataclass
class TradeRecord:
    """单笔交易流水记录"""

    trade_id: str                       # 交易流水号
    symbol: str                         # 标的代码
    direction: str                      # "buy" | "sell" | "short"
    quantity: int                       # 成交数量
    price: float                        # 成交价格
    fee: float                          # 交易费用
    order_type: str = "market"          # 订单类型: market / limit
    slippage: float = 0.0               # 滑点金额
    realized_pnl: float = 0.0           # 已实现盈亏（平仓时）
    timestamp: str = ""                 # 成交时间 (YYYY-MM-DD HH:mm:ss)
    date: str = ""                      # 成交日期 (YYYY-MM-DD)
    note: str = ""                      # 备注

    def __post_init__(self):
        if not self.date and self.timestamp:
            self.date = self.timestamp[:10]
        if not self.timestamp and self.date:
            self.timestamp = f"{self.date} 15:00:00"

    @property
    def turnover(self) -> float:
        """成交金额 = 价格 × 数量"""
        return self.price * self.quantity

    @property
    def net_amount(self) -> float:
        """净额 = 成交金额（含手续费方向）"""
        if self.direction in ("buy",):
            return -(self.turnover + self.fee)
        else:
            return self.turnover - self.fee

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "quantity": self.quantity,
            "price": round(self.price, 4),
            "fee": round(self.fee, 2),
            "order_type": self.order_type,
            "slippage": round(self.slippage, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "timestamp": self.timestamp,
            "date": self.date,
            "turnover": round(self.turnover, 2),
            "net_amount": round(self.net_amount, 2),
            "note": self.note,
        }


@dataclass
class DailySnapshot:
    """每日持仓快照"""

    date: str                           # 日期 YYYY-MM-DD
    cash: float                         # 现金余额
    frozen: float                       # 冻结资金
    position_value: float               # 持仓市值
    total_equity: float                 # 总权益 = cash + frozen + position_value
    position_count: int = 0             # 持仓品种数
    daily_return_pct: float = 0.0       # 当日收益率 (%)
    cumulative_return_pct: float = 0.0  # 累计收益率 (%)
    positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    margin_ratio: float = 0.0           # 仓位比例 = position_value / total_equity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "cash": round(self.cash, 2),
            "frozen": round(self.frozen, 2),
            "position_value": round(self.position_value, 2),
            "total_equity": round(self.total_equity, 2),
            "position_count": self.position_count,
            "daily_return_pct": round(self.daily_return_pct, 4),
            "cumulative_return_pct": round(self.cumulative_return_pct, 4),
            "margin_ratio": round(self.margin_ratio, 4),
            "positions": self.positions,
        }


# ═══════════════════════════════════════════════════════════════
# TradeLogger
# ═══════════════════════════════════════════════════════════════


class TradeLogger:
    """
    持仓记录器。

    职责:
      1. 按时间顺序记录每笔交易流水
      2. 生成每日持仓快照（持仓市值、现金、总权益）
      3. 导出成结构化数据便于后续分析
    """

    def __init__(self, initial_capital: float = 1_000_000.0):
        self._initial_capital = initial_capital
        self._trades: List[TradeRecord] = []
        self._snapshots: List[DailySnapshot] = []
        self._trade_counter: int = 0

    # ── 属性 ────────────────────────────────────────────────

    @property
    def trades(self) -> List[TradeRecord]:
        return list(self._trades)

    @property
    def snapshots(self) -> List[DailySnapshot]:
        return list(self._snapshots)

    @property
    def initial_capital(self) -> float:
        return self._initial_capital

    @property
    def total_trades(self) -> int:
        return len(self._trades)

    def get_trade_dicts(self) -> List[Dict[str, Any]]:
        """获取交易流水的字典列表（用于序列化/导出）。"""
        return [t.to_dict() for t in self._trades]

    def get_snapshot_dicts(self) -> List[Dict[str, Any]]:
        """获取快照的字典列表。"""
        return [s.to_dict() for s in self._snapshots]

    # ── 交易记录 ────────────────────────────────────────────

    def record_trade(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        fee: float = 0.0,
        order_type: str = "market",
        slippage: float = 0.0,
        realized_pnl: float = 0.0,
        timestamp: str = "",
        date: str = "",
        note: str = "",
    ) -> TradeRecord:
        """记录一笔交易流水。"""
        self._trade_counter += 1
        trade_id = f"T{self._trade_counter:06d}"

        record = TradeRecord(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            price=price,
            fee=fee,
            order_type=order_type,
            slippage=slippage,
            realized_pnl=realized_pnl,
            timestamp=timestamp,
            date=date,
            note=note,
        )
        self._trades.append(record)
        return record

    def record_buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        fee: float = 0.0,
        timestamp: str = "",
        date: str = "",
        note: str = "",
    ) -> TradeRecord:
        """便捷方法：记录买入交易。"""
        return self.record_trade(
            symbol=symbol,
            direction="buy",
            quantity=quantity,
            price=price,
            fee=fee,
            timestamp=timestamp,
            date=date,
            note=note,
        )

    def record_sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        fee: float = 0.0,
        realized_pnl: float = 0.0,
        timestamp: str = "",
        date: str = "",
        note: str = "",
    ) -> TradeRecord:
        """便捷方法：记录卖出交易。"""
        return self.record_trade(
            symbol=symbol,
            direction="sell",
            quantity=quantity,
            price=price,
            fee=fee,
            realized_pnl=realized_pnl,
            timestamp=timestamp,
            date=date,
            note=note,
        )

    # ── 快照 ────────────────────────────────────────────────

    def record_snapshot(
        self,
        date: str,
        cash: float,
        frozen: float,
        position_value: float,
        positions: Optional[Dict[str, Dict[str, Any]]] = None,
        prev_total_equity: Optional[float] = None,
        cumulative_return_pct: Optional[float] = None,
    ) -> DailySnapshot:
        """
        记录一份每日快照。

        参数
        ----------
        date : str
            日期 YYYY-MM-DD
        cash : float
            现金余额
        frozen : float
            冻结资金
        position_value : float
            持仓市值
        positions : dict, optional
            持仓明细 {symbol: {quantity, avg_cost, market_value, ...}}
        prev_total_equity : float, optional
            上一日总权益（用于计算日收益率），初日传 None
        cumulative_return_pct : float, optional
            累计收益率（若传 None 自动计算）
        """
        total_equity = cash + frozen + position_value

        if positions is None:
            positions = {}
            position_count = 0
        else:
            position_count = len(positions)

        daily_return_pct = 0.0
        if prev_total_equity is not None and prev_total_equity > 0:
            daily_return_pct = (
                (total_equity - prev_total_equity) / prev_total_equity * 100.0
            )

        if cumulative_return_pct is None:
            cumulative_return_pct = (
                (total_equity - self._initial_capital) / self._initial_capital * 100.0
            )

        margin_ratio = 0.0
        if total_equity > 0:
            margin_ratio = position_value / total_equity

        snapshot = DailySnapshot(
            date=date,
            cash=cash,
            frozen=frozen,
            position_value=position_value,
            total_equity=total_equity,
            position_count=position_count,
            daily_return_pct=daily_return_pct,
            cumulative_return_pct=cumulative_return_pct,
            positions={
                sym: {k: round(v, 4) if isinstance(v, float) else v for k, v in info.items()}
                for sym, info in positions.items()
            }
            if positions
            else {},
            margin_ratio=margin_ratio,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def build_from_equity_curve(
        self,
        equity_curve: List[Dict[str, float]],
        cash_series: Optional[List[float]] = None,
        position_value_series: Optional[List[float]] = None,
    ) -> List[DailySnapshot]:
        """
        从已有的 equity_curve 重建快照序列。

        适用于回测引擎已有 equity_curve 但缺少完整快照的场景。

        参数
        ----------
        equity_curve : List[Dict[str, float]]
            净值曲线 [{date, total_equity}, ...]
        cash_series : List[float], optional
            现金序列（长度需匹配），若不传则记为 0
        position_value_series : List[float], optional
            持仓市值序列，若不传则用 total_equity 倒推

        返回
        -------
        List[DailySnapshot]
        """
        self._snapshots.clear()

        for i, pt in enumerate(equity_curve):
            date = pt["date"]
            total = pt["total_equity"]
            cash = cash_series[i] if cash_series and i < len(cash_series) else 0.0
            frozen = 0.0
            pv = (
                position_value_series[i]
                if position_value_series and i < len(position_value_series)
                else total - cash - frozen
            )

            prev = equity_curve[i - 1]["total_equity"] if i > 0 else None
            cum_ret = (
                (total - self._initial_capital) / self._initial_capital * 100.0
            )

            self.record_snapshot(
                date=date,
                cash=cash,
                frozen=frozen,
                position_value=pv,
                prev_total_equity=prev,
                cumulative_return_pct=cum_ret,
            )

        return self._snapshots

    # ── 汇总 ────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """
        生成交易统计摘要。

        返回
        -------
        dict: {total_trades, total_buy, total_sell, total_fees,
               gross_pnl, net_pnl, trade_dates}
        """
        total_buy = sum(
            t.turnover for t in self._trades if t.direction == "buy"
        )
        total_sell = sum(
            t.turnover for t in self._trades if t.direction == "sell"
        )
        total_fees = sum(t.fee for t in self._trades)
        gross_pnl = sum(
            t.realized_pnl for t in self._trades
        )

        return {
            "total_trades": self.total_trades,
            "total_buy_turnover": round(total_buy, 2),
            "total_sell_turnover": round(total_sell, 2),
            "total_fees": round(total_fees, 2),
            "gross_realized_pnl": round(gross_pnl, 2),
            "initial_capital": round(self._initial_capital, 2),
            "first_trade_date": self._trades[0].date if self._trades else None,
            "last_trade_date": self._trades[-1].date if self._trades else None,
            "snapshot_count": len(self._snapshots),
        }

    def reset(self) -> None:
        """重置所有记录。"""
        self._trades.clear()
        self._snapshots.clear()
        self._trade_counter = 0
