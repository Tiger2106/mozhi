"""
墨枢 - CapitalManager
资金管理：可用资金/冻结资金/总资产跟踪
"""
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class CapitalManager:
    """资金管理器：跟踪可用资金、冻结资金和总资产。"""

    initial_capital: float = 1_000_000.0
    _available: float = field(init=False, repr=True)
    _frozen: float = field(init=False, repr=True, default=0.0)

    def __post_init__(self):
        self._available = self.initial_capital
        self._frozen = 0.0

    # ── 属性 ────────────────────────────────────────────────
    @property
    def available(self) -> float:
        """可用资金"""
        return self._available

    @property
    def frozen(self) -> float:
        """冻结资金"""
        return self._frozen

    @property
    def total_assets(self) -> float:
        """总资产 = 可用 + 冻结（不含持仓市值，由外部加入）"""
        return self._available + self._frozen

    @property
    def total_with_position(self, position_market_value: float = 0.0) -> float:
        """含持仓市值的总资产"""
        return self._available + self._frozen + position_market_value

    # ── 核心操作 ─────────────────────────────────────────────

    def freeze(self, amount: float) -> None:
        """下单时冻结资金"""
        if amount <= 0:
            raise ValueError(f"冻结金额必须为正数: {amount}")
        if amount > self._available:
            raise ValueError(
                f"可用资金不足: 需要 {amount:.2f}, 可用 {self._available:.2f}"
            )
        self._available -= amount
        self._frozen += amount

    def unfreeze(self, amount: float) -> None:
        """取消订单时解冻资金"""
        if amount <= 0:
            raise ValueError(f"解冻金额必须为正数: {amount}")
        if amount > self._frozen:
            raise ValueError(
                f"冻结资金不足: 需解冻 {amount:.2f}, 已冻结 {self._frozen:.2f}"
            )
        self._frozen -= amount
        self._available += amount

    def deduct(self, amount: float) -> None:
        """成交时从冻结中扣除实际成交金额"""
        if amount <= 0:
            raise ValueError(f"扣除金额必须为正数: {amount}")
        if amount > self._frozen:
            raise ValueError(
                f"冻结资金不足以扣除: 需扣除 {amount:.2f}, 已冻结 {self._frozen:.2f}"
            )
        self._frozen -= amount
        # 多余冻结资金退回可用
        # （注意：deduct 仅扣除实际成交额；差额由 caller 解冻）

    def add(self, amount: float) -> None:
        """平仓/卖出后增加可用资金"""
        if amount < 0:
            raise ValueError(f"增加金额不能为负: {amount}")
        self._available += amount

    # ── 快照 ────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """获取资金快照"""
        return {
            "initial_capital": self.initial_capital,
            "available": round(self._available, 2),
            "frozen": round(self._frozen, 2),
            "total_assets": round(self.total_assets, 2),
        }
