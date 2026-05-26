"""
墨枢 - FeeModel
手续费计算模型：抽象基类 + A股标准实现。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════
# FeeModel 抽象基类
# ═══════════════════════════════════════════════════════════════


class FeeModel(ABC):
    """手续费计算模型抽象基类。"""

    @abstractmethod
    def calc_buy_fee(self, price: float, quantity: int) -> float:
        """计算买入手续费"""
        ...

    @abstractmethod
    def calc_sell_fee(self, price: float, quantity: int) -> float:
        """计算卖出手续费"""
        ...

    def calculate(self, price: float, quantity: int) -> float:
        """
        通用手续费计算（兼容旧版接口）。
        默认按卖出费用处理（最保守估计）。
        """
        return self.calc_sell_fee(price, quantity)


# ═══════════════════════════════════════════════════════════════
# SimpleFeeModel  — 简单比例（旧版兼容）
# ═══════════════════════════════════════════════════════════════


@dataclass
class SimpleFeeModel(FeeModel):
    """
    简单统一比例收费模型（旧版 FeeModel 兼容实现）。

    买入和卖出使用相同的费率与最低收费。
    """

    fee_rate: float = 0.0003
    min_fee: float = 5.0

    def calc_buy_fee(self, price: float, quantity: int) -> float:
        return max(round(price * quantity * self.fee_rate, 2), self.min_fee)

    def calc_sell_fee(self, price: float, quantity: int) -> float:
        return max(round(price * quantity * self.fee_rate, 2), self.min_fee)


# ═══════════════════════════════════════════════════════════════
# CNStockFeeModel  — A股标准收费
# ═══════════════════════════════════════════════════════════════


@dataclass
class CNStockFeeModel(FeeModel):
    """
    A股标准手续费模型。

    - 佣金：万分之2.5（最低5元）
    - 印花税：千分之1（仅卖出时收取）
    - 过户费：万分之0.2（买入和卖出均收取）
    """

    commission_rate: float = 0.00025       # 佣金万分之2.5
    min_commission: float = 5.0            # 佣金最低5元
    stamp_tax_rate: float = 0.001          # 印花税千分之1
    transfer_fee_rate: float = 0.00002     # 过户费万分之0.2

    def calc_buy_fee(self, price: float, quantity: int) -> float:
        turnover = price * quantity
        commission = max(
            round(turnover * self.commission_rate, 2), self.min_commission
        )
        transfer_fee = round(turnover * self.transfer_fee_rate, 2)
        return commission + transfer_fee

    def calc_sell_fee(self, price: float, quantity: int) -> float:
        turnover = price * quantity
        commission = max(
            round(turnover * self.commission_rate, 2), self.min_commission
        )
        stamp_tax = round(turnover * self.stamp_tax_rate, 2)
        transfer_fee = round(turnover * self.transfer_fee_rate, 2)
        return commission + stamp_tax + transfer_fee
