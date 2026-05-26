"""
墨枢 - BacktestContext
回测上下文：资金管理、持仓管理、当前Bar指针、快照记录。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .capital_manager import CapitalManager
from .position_manager import CostMethod, PositionManager


@dataclass
class BacktestContext:
    """
    回测上下文，连接资金管理、持仓管理、当前Bar指针和快照系统。

    用法::

        ctx = BacktestContext(initial_capital=1_000_000)
        ctx.on_bar("2026-01-10", "000001.SZ")
        # ... 交易逻辑 ...
        snap = ctx.take_snapshot()
    """

    # ── 资金管理 ────────────────────────────────────────────
    initial_capital: float = 1_000_000.0
    capital: CapitalManager = field(init=False)

    # ── 持仓管理 ────────────────────────────────────────────
    cost_method: CostMethod = CostMethod.WEIGHTED_AVG
    positions: PositionManager = field(init=False)

    # ── 当前Bar指针 ─────────────────────────────────────────
    current_date: Optional[str] = field(init=False, default=None)
    current_symbol: Optional[str] = field(init=False, default=None)

    # ── 快照系统 ────────────────────────────────────────────
    snapshots: List[Dict[str, Any]] = field(default_factory=list)
    _snapshot_enabled: bool = field(init=False, default=True)

    def __post_init__(self):
        self.capital = CapitalManager(initial_capital=self.initial_capital)
        self.positions = PositionManager(cost_method=self.cost_method)
        self.current_date = None
        self.current_symbol = None
        self.snapshots = []
        self._snapshot_enabled = True

    # ── Bar 指针 ────────────────────────────────────────────

    def on_bar(self, date: str, symbol: str) -> None:
        """更新到当前Bar的日期和标的。"""
        self.current_date = date
        self.current_symbol = symbol

    def reset_bar(self) -> None:
        """重置当前Bar指针。"""
        self.current_date = None
        self.current_symbol = None

    # ── 查询 ────────────────────────────────────────────────

    @property
    def available_capital(self) -> float:
        return self.capital.available

    @property
    def frozen_capital(self) -> float:
        return self.capital.frozen

    @property
    def total_capital(self) -> float:
        """现金 + 冻结"""
        return self.capital.total_assets

    @property
    def total_equity(self) -> float:
        """总权益 = 现金 + 持仓市值（基于当前持仓平均成本估算）"""
        # 若需要更精确的市场价值，调用方应使用 positions.total_market_value()
        pos_mv = sum(
            pos.quantity * pos.avg_cost
            for pos in self.positions.positions.values()
        )
        return self.capital.available + self.capital.frozen + pos_mv

    def total_equity_with_prices(self, price_map: Dict[str, float]) -> float:
        """基于传入的最新价格计算总权益。"""
        pos_mv = self.positions.total_market_value(price_map)
        return self.capital.available + self.capital.frozen + pos_mv

    def check_sufficient_capital(self, required: float) -> bool:
        """检查可用资金是否充足。"""
        return self.capital.available >= required - 1e-9

    # ── 快照 ────────────────────────────────────────────────

    def take_snapshot(
        self,
        extra: Optional[Dict[str, Any]] = None,
        price_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        记录当前状态快照，并保存到 self.snapshots。

        参数
        ----------
        extra : dict, optional
            额外字段（如当前价格、技术指标等）。
        price_map : dict, optional
            标的最新价格映射，用于计算持仓市值。

        返回
        -------
        dict
            完整快照。
        """
        if not self._snapshot_enabled:
            return {}

        # 计算持仓市值
        if price_map:
            pos_mv = self.positions.total_market_value(price_map)
        else:
            pos_mv = sum(
                pos.quantity * pos.avg_cost
                for pos in self.positions.positions.values()
            )

        snapshot = {
            "date": self.current_date,
            "symbol": self.current_symbol,
            "capital": self.capital.snapshot(),
            "positions": self.positions.snapshot(),
            "position_market_value": round(pos_mv, 2),
            "total_equity": round(
                self.capital.available + self.capital.frozen + pos_mv, 2
            ),
        }
        if extra:
            snapshot["extra"] = extra

        self.snapshots.append(snapshot)
        return snapshot

    def enable_snapshot(self, enabled: bool = True) -> None:
        """启用/禁用快照记录。"""
        self._snapshot_enabled = enabled

    def get_snapshot_history(self) -> List[Dict[str, Any]]:
        """获取所有快照记录。"""
        return list(self.snapshots)

    def clear_snapshots(self) -> None:
        """清空快照历史。"""
        self.snapshots.clear()

    # ── 完整上下文摘要 ──────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """返回当前上下文的摘要信息。"""
        return {
            "current_date": self.current_date,
            "current_symbol": self.current_symbol,
            "capital": self.capital.snapshot(),
            "positions_summary": {
                "count": len(self.positions.positions),
                "details": self.positions.snapshot(),
            },
            "total_equity": round(self.total_equity, 2),
            "snapshot_count": len(self.snapshots),
        }
