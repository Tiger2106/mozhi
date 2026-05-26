"""
墨枢 - SlippageModel
滑点计算模型：抽象基类 + 固定/比例/零滑点实现。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════
# SlippageModel 抽象基类
# ═══════════════════════════════════════════════════════════════


class SlippageModel(ABC):
    """滑点计算模型抽象基类。"""

    @abstractmethod
    def calc_buy_price(self, price: float) -> float:
        """计算考虑滑点后的买入价格"""
        ...

    @abstractmethod
    def calc_sell_price(self, price: float) -> float:
        """计算考虑滑点后的卖出价格"""
        ...


# ═══════════════════════════════════════════════════════════════
# NoSlippage  — 零滑点
# ═══════════════════════════════════════════════════════════════


class NoSlippage(SlippageModel):
    """零滑点模式：成交价 = 市场价。"""

    def calc_buy_price(self, price: float) -> float:
        return price

    def calc_sell_price(self, price: float) -> float:
        return price


# ═══════════════════════════════════════════════════════════════
# FixedSlippage  — 固定滑点
# ═══════════════════════════════════════════════════════════════


@dataclass
class FixedSlippage(SlippageModel):
    """
    固定滑点模式。

    买入：成交价 = 市场价 + slippage
    卖出：成交价 = 市场价 - slippage
    """

    slippage: float = 0.01  # 固定滑点金额

    def calc_buy_price(self, price: float) -> float:
        return price + self.slippage

    def calc_sell_price(self, price: float) -> float:
        return price - self.slippage


# ═══════════════════════════════════════════════════════════════
# RatioSlippage  — 比例滑点
# ═══════════════════════════════════════════════════════════════


@dataclass
class RatioSlippage(SlippageModel):
    """
    比例滑点模式。

    买入：成交价 = 市场价 * (1 + slippage_rate)
    卖出：成交价 = 市场价 * (1 - slippage_rate)
    """

    slippage_rate: float = 0.001  # 千分之1

    def calc_buy_price(self, price: float) -> float:
        return price * (1.0 + self.slippage_rate)

    def calc_sell_price(self, price: float) -> float:
        return price * (1.0 - self.slippage_rate)
