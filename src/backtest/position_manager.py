"""
墨枢 - PositionManager
持仓管理：开仓/加仓/减仓/平仓，支持 FIFO 及加权平均成本计算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class CostMethod(str, Enum):
    """持仓成本计算方法"""
    FIFO = "fifo"           # 先进先出
    WEIGHTED_AVG = "wavg"   # 加权平均


@dataclass
class Position:
    """单个标的的持仓信息"""
    symbol: str
    quantity: int = 0                 # 持仓数量（正数 = 多头）
    avg_cost: float = 0.0            # 持仓均价（加权平均模式下）
    cost_basis: float = 0.0          # 总成本（用于计算盈亏）
    market_value: float = 0.0        # 当前市值（由外部更新）

    # ── FIFO 批次 ───────────────────────────────────────────
    # 每笔买入记录 (quantity, cost_per_share)
    lots: List[Tuple[int, float]] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.lots, tuple):
            self.lots = list(self.lots)

    @property
    def size(self) -> int:
        return self.quantity

    @property
    def is_empty(self) -> bool:
        return self.quantity == 0

    def snapshot(self) -> dict:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": round(self.avg_cost, 4),
            "cost_basis": round(self.cost_basis, 2),
            "market_value": round(self.market_value, 2),
            "unrealized_pnl": round(self.market_value - self.cost_basis, 2),
            "lots": [(q, round(c, 4)) for q, c in self.lots],
        }


@dataclass
class PositionManager:
    """持仓管理器，管理多标的多头持仓。"""

    cost_method: CostMethod = CostMethod.WEIGHTED_AVG
    _positions: Dict[str, Position] = field(default_factory=dict)

    # ── 持仓访问 ────────────────────────────────────────────

    def get(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def get_or_create(self, symbol: str) -> Position:
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)
        return self._positions[symbol]

    @property
    def positions(self) -> Dict[str, Position]:
        return dict(self._positions)

    @property
    def all_symbols(self) -> List[str]:
        return list(self._positions.keys())

    def has_position(self, symbol: str) -> bool:
        pos = self._positions.get(symbol)
        return pos is not None and pos.quantity > 0

    # ── 开仓 / 加仓 ────────────────────────────────────────

    def open_position(
        self, symbol: str, quantity: int, price: float, fee: float = 0.0
    ) -> Position:
        """开新仓位或加仓，返回更新后的持仓对象。"""
        if quantity <= 0:
            raise ValueError(f"开仓数量必须为正: {quantity}")

        pos = self.get_or_create(symbol)
        total_cost = quantity * price + fee

        if self.cost_method == CostMethod.FIFO:
            # FIFO：追加买入批次
            pos.lots.append((quantity, price))
            pos.quantity += quantity
            pos.cost_basis += total_cost
        else:
            # 加权平均
            old_qty = pos.quantity
            old_cost = pos.cost_basis
            new_qty = old_qty + quantity
            new_cost = old_cost + total_cost
            pos.avg_cost = new_cost / new_qty if new_qty > 0 else 0.0
            pos.quantity = new_qty
            pos.cost_basis = new_cost

        return pos

    def close_position(
        self, symbol: str, quantity: int, price: float, fee: float = 0.0
    ) -> Tuple[float, float]:
        """
        减仓或平仓。
        返回 (realized_pnl, released_capital)。
        realized_pnl  = 卖出收入 - 卖出成本（基于持仓成本计算方法）
        released_capital = 卖出收入 - 手续费（这部分资金将归还资金账户）
        """
        if quantity <= 0:
            raise ValueError(f"平仓数量必须为正: {quantity}")

        pos = self.get(symbol)
        if pos is None or pos.quantity < quantity:
            raise ValueError(
                f"持仓不足: 需平 {quantity}, 持有 {pos.quantity if pos else 0}"
            )

        revenue = quantity * price - fee

        if self.cost_method == CostMethod.FIFO:
            realized_pnl = self._close_fifo(pos, quantity, price, fee)
        else:
            realized_pnl = self._close_wavg(pos, quantity, price, fee)

        # 清理空仓位
        if pos.quantity == 0:
            pos.avg_cost = 0.0
            pos.cost_basis = 0.0
            pos.lots.clear()
            del self._positions[symbol]

        return realized_pnl, revenue

    def _close_fifo(
        self, pos: Position, quantity: int, price: float, fee: float
    ) -> float:
        """FIFO 方式计算已实现盈亏。"""
        remaining = quantity
        total_cost = 0.0
        new_lots: List[Tuple[int, float]] = []

        for lot_qty, lot_cost in pos.lots:
            if remaining <= 0:
                new_lots.append((lot_qty, lot_cost))
                continue
            used = min(lot_qty, remaining)
            total_cost += used * lot_cost
            remaining -= used
            if lot_qty > used:
                new_lots.append((lot_qty - used, lot_cost))

        pos.lots = new_lots
        pos.quantity -= quantity
        revenue = quantity * price - fee
        realized_pnl = revenue - total_cost

        if pos.quantity > 0:
            # 更新剩余成本基础
            pos.cost_basis = sum(q * c for q, c in pos.lots)
            pos.avg_cost = pos.cost_basis / pos.quantity if pos.quantity > 0 else 0.0

        return realized_pnl

    def _close_wavg(
        self, pos: Position, quantity: int, price: float, fee: float
    ) -> float:
        """加权平均方式计算已实现盈亏。"""
        total_cost = quantity * pos.avg_cost
        pos.quantity -= quantity
        pos.cost_basis -= total_cost
        revenue = quantity * price - fee
        realized_pnl = revenue - total_cost

        if pos.quantity == 0:
            pos.avg_cost = 0.0
        return realized_pnl

    # ── 快照 ────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, dict]:
        return {sym: pos.snapshot() for sym, pos in self._positions.items()}

    def total_market_value(self, price_map: Dict[str, float]) -> float:
        """根据当前价格计算所有持仓市值"""
        total = 0.0
        for sym, pos in self._positions.items():
            px = price_map.get(sym, pos.avg_cost)
            pos.market_value = pos.quantity * px
            total += pos.market_value
        return total
