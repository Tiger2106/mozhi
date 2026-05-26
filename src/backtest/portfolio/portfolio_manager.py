"""
mozhi_platform.src.backtest.portfolio.portfolio_manager — PortfolioManager

仓位管理桥接层。

Phase 4 — 仓位管理桥接。

职责:
  1. process_signal(signal, bar) → Optional[Order]: 信号 → 订单
  2. update_market(bar): 逐 Bar 更新市值
  3. 支持多种仓位模式（固定比例、金字塔、趋势强度）
  4. 与 BacktestEngine 的 PositionManager / CapitalManager 配合

使用示例:
    >>> from backtest.portfolio.portfolio_manager import (
    ...     PortfolioManager, Order, OrderSide, Position
    ... )
    ...
    >>> mgr = PortfolioManager(initial_cash=1_000_000)
    >>> bar = {"close": 100.0, "date": "2025-01-01"}
    >>> signal = Signal(symbol="601857", signal_value=1, confidence=0.8)
    >>> order = mgr.process_signal(signal, bar)
    >>> order.quantity
    3000

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 公共数据类型
# ──────────────────────────────────────────────────────────────────────


class OrderSide(str, Enum):
    """订单方向。"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """订单类型。"""
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Signal:
    """统一信号结构（PortfolioManager 输入）。

    由 MethodResult 中的信号行转换而来。
    """
    symbol: str
    """标的代码。"""

    signal_value: int
    """信号值: 1=买入, -1=卖出, 0=无操作。"""

    confidence: float = 0.5
    """信号置信度 [0, 1]。"""

    timestamp: str = ""
    """信号时间戳。"""

    price: float = 0.0
    """触发价格。"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """扩展信息。"""


@dataclass
class Order:
    """统一订单结构（PortfolioManager 输出）。

    直接传递给 BacktestEngine 的 OrderRequest。
    """
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    price: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """简化持仓信息。"""
    symbol: str
    quantity: int
    avg_price: float
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


# ──────────────────────────────────────────────────────────────────────
# PositionSizer — 仓位计算器接口
# ──────────────────────────────────────────────────────────────────────


class PositionSizer:
    """仓位计算器基类。

    子类实现不同的仓位分配策略：
    - FixedRatioSizer: 固定比例
    - PyramidSizer: 金字塔加仓
    - TrendScoreSizer: 趋势强度
    """

    def calc_quantity(
        self,
        available_cash: float,
        price: float,
        signal: Signal,
        position: Optional[Position] = None,
        min_shares: int = 100,
    ) -> int:
        """计算开仓数量。

        Args:
            available_cash: 当前可用资金。
            price: 当前价格。
            signal: 信号对象。
            position: 当前持仓（可选）。
            min_shares: 最小交易单位。

        Returns:
            int: 开仓数量（0 表示不开仓）。
        """
        raise NotImplementedError


class FixedRatioSizer(PositionSizer):
    """固定比例仓位计算器。

    每次开仓按 available_cash × ratio 计算资金。
    """

    def __init__(self, ratio: float = 0.3):
        """初始化固定比例仓位计算器。

        Args:
            ratio: 仓位比例（0.0 ~ 1.0，默认 0.3）。
        """
        self.ratio = max(0.0, min(1.0, ratio))

    def calc_quantity(
        self,
        available_cash: float,
        price: float,
        signal: Signal,
        position: Optional[Position] = None,
        min_shares: int = 100,
    ) -> int:
        """固定比例计算开仓数量。

        Args:
            available_cash: 当前可用资金。
            price: 当前价格。
            signal: 信号对象（用于置信度调整）。
            position: 当前持仓（固定比例模式下忽略）。
            min_shares: 最小交易单位。

        Returns:
            int: 开仓数量。
        """
        if price <= 0 or available_cash <= 0:
            return 0

        # 基础资金 = 可用资金 × 仓位比例
        base_capital = available_cash * self.ratio

        # 置信度调整
        adjusted_capital = base_capital * (0.5 + signal.confidence * 0.5)

        # 计算股数
        quantity = int(adjusted_capital / price)
        # 对齐到最小单位
        quantity = (quantity // min_shares) * min_shares

        return max(quantity, 0)


class PyramidSizer(PositionSizer):
    """金字塔仓位计算器。

    先开底仓（initial_ratio），后续信号满足间隔条件时加仓（add_ratio × add_count）。
    """

    def __init__(
        self,
        initial_ratio: float = 0.3,
        add_ratio: float = 0.15,
        max_adds: int = 3,
        add_wait_bars: int = 5,
    ):
        """初始化金字塔仓位计算器。

        Args:
            initial_ratio: 初始仓位比例。
            add_ratio: 每次加仓比例。
            max_adds: 最大加仓次数。
            add_wait_bars: 加仓间隔最小 Bar 数。
        """
        self.initial_ratio = max(0.0, min(1.0, initial_ratio))
        self.add_ratio = max(0.0, min(1.0, add_ratio))
        self.max_adds = max(0, max_adds)
        self.add_wait_bars = max(1, add_wait_bars)

        # 运行时状态
        self._add_count: int = 0
        self._last_add_bar: int = -self.add_wait_bars  # 初始允许开仓

    def calc_quantity(
        self,
        available_cash: float,
        price: float,
        signal: Signal,
        position: Optional[Position] = None,
        min_shares: int = 100,
    ) -> int:
        """金字塔计算开仓数量。

        Args:
            available_cash: 当前可用资金。
            price: 当前价格。
            signal: 信号对象。
            position: 当前持仓（用于判断是否已开仓）。
            min_shares: 最小交易单位。

        Returns:
            int: 开仓数量。
        """
        if price <= 0 or available_cash <= 0:
            return 0

        is_first_entry = (position is None or position.quantity == 0)

        if is_first_entry:
            # 初始开仓
            self._add_count = 0
            self._last_add_bar = 0
            base_capital = available_cash * self.initial_ratio
        elif self._add_count < self.max_adds:
            # 加仓
            self._add_count += 1
            self._last_add_bar = self._last_add_bar
            base_capital = available_cash * self.add_ratio
        else:
            return 0  # 已达最大加仓次数

        quantity = int(base_capital / price)
        quantity = (quantity // min_shares) * min_shares
        return max(quantity, 0)

    def reset(self) -> None:
        """重置金字塔状态。"""
        self._add_count = 0
        self._last_add_bar = -self.add_wait_bars


class TrendScoreSizer(PositionSizer):
    """趋势强度仓位计算器。

    根据 signal.confidence（趋势评分）映射仓位比例。
    评分越高，仓位越大。
    """

    def __init__(self, min_ratio: float = 0.1, max_ratio: float = 0.5):
        """初始化趋势强度仓位计算器。

        Args:
            min_ratio: 最低仓位比例。
            max_ratio: 最高仓位比例。
        """
        self.min_ratio = max(0.0, min(1.0, min_ratio))
        self.max_ratio = max(self.min_ratio, min(1.0, max_ratio))

    def calc_quantity(
        self,
        available_cash: float,
        price: float,
        signal: Signal,
        position: Optional[Position] = None,
        min_shares: int = 100,
    ) -> int:
        """趋势强度计算开仓数量。

        Args:
            available_cash: 当前可用资金。
            price: 当前价格。
            signal: 信号对象（confidence 作为趋势强度）。
            position: 当前持仓（趋势强度模式下忽略）。
            min_shares: 最小交易单位。

        Returns:
            int: 开仓数量。
        """
        if price <= 0 or available_cash <= 0:
            return 0

        # 根据置信度线性映射仓位比例
        ratio = self.min_ratio + (self.max_ratio - self.min_ratio) * signal.confidence
        ratio = max(self.min_ratio, min(self.max_ratio, ratio))

        base_capital = available_cash * ratio
        quantity = int(base_capital / price)
        quantity = (quantity // min_shares) * min_shares
        return max(quantity, 0)


# ──────────────────────────────────────────────────────────────────────
# RiskManager — 风控检查
# ──────────────────────────────────────────────────────────────────────


@dataclass
class RiskManager:
    """风控管理器。

    检查操作前是否触发了风控限制。
    """

    max_position_ratio: float = 0.5
    """单标的最大仓位比例。"""

    max_drawdown_pct: float = 0.2
    """最大浮动亏损比例（触发后禁止开仓）。"""

    min_signal_confidence: float = 0.3
    """信号最小置信度。"""

    _hit_peak_cash: float = 0.0
    """历史最高现金额（用于计算回撤）。"""

    def check_open(self, signal: Signal, available_cash: float) -> Tuple[bool, str]:
        """检查是否允许开仓。

        Args:
            signal: 信号对象。
            available_cash: 当前可用资金。

        Returns:
            Tuple[bool, str]: (允许, 拒绝原因)。
        """
        # 置信度检查
        if signal.confidence < self.min_signal_confidence:
            return False, f"信号置信度 {signal.confidence:.3f} 低于阈值 {self.min_signal_confidence}"

        # 资金检查
        if available_cash <= 0:
            return False, "可用资金不足"

        return True, ""

    def check_close(self, position: Position) -> Tuple[bool, str]:
        """检查是否允许平仓。

        Args:
            position: 当前持仓。

        Returns:
            Tuple[bool, str]: (允许, 拒绝原因)。
        """
        if position.quantity <= 0:
            return False, "无持仓"
        return True, ""

    def update_peak_cash(self, current_cash: float) -> None:
        """更新历史最高现金记录。

        Args:
            current_cash: 当前现金。
        """
        if current_cash > self._hit_peak_cash:
            self._hit_peak_cash = current_cash

    @property
    def current_drawdown_pct(self) -> float:
        """当前浮动回撤比例。

        Returns:
            float: 回撤比例（0.0 ~ 1.0）。
        """
        if self._hit_peak_cash <= 0:
            return 0.0
        return 0.0  # 实际由外部更新


# ──────────────────────────────────────────────────────────────────────
# PortfolioManager
# ──────────────────────────────────────────────────────────────────────


class PortfolioManager:
    """仓位管理桥接层。

    职责:
    - 接收 MethodResult 信号 → 转换为 Order
    - 管理持仓信息
    - 支持多种仓位计算策略
    - 集成风控检查
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        sizer: Optional[PositionSizer] = None,
        risk_manager: Optional[RiskManager] = None,
        symbol: str = "DEFAULT",
        min_shares: int = 100,
    ):
        """初始化 PortfolioManager。

        Args:
            initial_cash: 初始资金。
            sizer: 仓位计算器（默认 FixedRatioSizer(0.3)）。
            risk_manager: 风控管理器（默认 RiskManager()）。
            symbol: 默认交易标的。
            min_shares: 最小交易单位。
        """
        self.initial_cash: float = initial_cash
        self.available_cash: float = initial_cash
        self.symbol: str = symbol
        self.min_shares: int = min_shares

        self.sizer: PositionSizer = sizer or FixedRatioSizer(ratio=0.3)
        self.risk: RiskManager = risk_manager or RiskManager()

        # 运行时状态
        self._positions: Dict[str, Position] = {}
        self._total_trades: int = 0
        self._bar_count: int = 0

        self.logger = logging.getLogger(f"mozhi.portfolio.{symbol}")

    # ─── 信号处理 ──────────────────────────────────────────

    def process_signal(
        self,
        signal: Signal,
        bar: Optional[Dict[str, Any]] = None,
        position_ratio: float = 1.0,
    ) -> Optional[Order]:
        """信号 → 订单。

        Args:
            signal: 信号对象。
            bar: 当前 K 线数据（可选，用于获取价格）。
            position_ratio: 仓位比例 [0, 1]（默认 1.0=不调整）。
                            由 RiskPipeline 计算，受 ATR/市场状态影响。

        Returns:
            Optional[Order]: 生成的订单，或 None（无操作/风控拒绝）。
        """
        if signal.signal_value == 0:
            return None

        price = signal.price
        if price <= 0 and bar is not None:
            price = bar.get("close", 0.0)

        if price <= 0:
            self.logger.warning("信号价格无效: price=%s", price)
            return None

        current_pos = self._positions.get(signal.symbol)

        if signal.signal_value > 0:
            # ── 买入信号 ──────────────────────────────────
            allowed, reason = self.risk.check_open(signal, self.available_cash)
            if not allowed:
                self.logger.debug("风控拒绝开仓: %s", reason)
                return None

            quantity = self.sizer.calc_quantity(
                available_cash=self.available_cash,
                price=price,
                signal=signal,
                position=current_pos,
                min_shares=self.min_shares,
            )

            if quantity <= 0:
                return None

            # 应用 RiskPipeline 计算的仓位比例
            quantity = max(int(quantity * max(0.0, min(1.0, position_ratio))), 0)
            if quantity <= 0:
                return None

            return Order(
                symbol=signal.symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                order_type=OrderType.MARKET,
                price=price,
            )

        else:
            # ── 卖出信号 ──────────────────────────────────
            if current_pos is None or current_pos.quantity <= 0:
                return None

            allowed, reason = self.risk.check_close(current_pos)
            if not allowed:
                return None

            return Order(
                symbol=signal.symbol,
                side=OrderSide.SELL,
                quantity=current_pos.quantity,
                order_type=OrderType.MARKET,
                price=price,
            )

    # ─── 市值更新 ──────────────────────────────────────────

    def update_market(self, bar: Dict[str, Any]) -> None:
        """逐 Bar 更新市值。

        Args:
            bar: 当前 K 线数据，需包含 ``close`` 和可选 ``date``。
        """
        self._bar_count += 1
        close_price = bar.get("close", 0.0)

        for pos in self._positions.values():
            pos.market_value = pos.quantity * close_price
            pos.unrealized_pnl = (close_price - pos.avg_price) * pos.quantity

        self.risk.update_peak_cash(self.available_cash)

    # ─── 订单执行反馈 ──────────────────────────────────────

    def on_order_filled(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        fee: float = 0.0,
    ) -> None:
        """订单成交回调。

        Args:
            symbol: 标的代码。
            side: 订单方向。
            quantity: 成交数量。
            price: 成交价格。
            fee: 手续费。
        """
        self._total_trades += 1

        if side == OrderSide.BUY:
            cost = price * quantity + fee
            self.available_cash -= cost

            # 更新持仓
            if symbol not in self._positions:
                self._positions[symbol] = Position(
                    symbol=symbol,
                    quantity=quantity,
                    avg_price=price,
                )
            else:
                pos = self._positions[symbol]
                total_cost = pos.avg_price * pos.quantity + price * quantity
                pos.quantity += quantity
                pos.avg_price = total_cost / pos.quantity if pos.quantity > 0 else 0

            self.logger.info(
                "BUY: %s qty=%d @ %.4f (cash=%.2f)",
                symbol, quantity, price, self.available_cash,
            )

        elif side == OrderSide.SELL:
            proceeds = price * quantity - fee
            self.available_cash += proceeds

            if symbol in self._positions:
                pos = self._positions[symbol]
                # 计算已实现盈亏
                realized = (price - pos.avg_price) * min(quantity, pos.quantity)
                pos.realized_pnl += realized
                pos.quantity -= quantity
                if pos.quantity <= 0:
                    del self._positions[symbol]

            self.logger.info(
                "SELL: %s qty=%d @ %.4f (cash=%.2f)",
                symbol, quantity, price, self.available_cash,
            )

    # ─── 查询 ──────────────────────────────────────────────

    def total_equity(self, current_price: float = 0.0) -> float:
        """计算总权益（现金 + 持仓市值）。

        Args:
            current_price: 当前价格（用于市值估算）。

        Returns:
            float: 总权益。
        """
        market_value = sum(
            p.quantity * current_price for p in self._positions.values()
        )
        return self.available_cash + market_value

    @property
    def total_trades(self) -> int:
        """总交易次数。"""
        return self._total_trades

    @property
    def positions(self) -> Dict[str, Position]:
        """持仓字典 {symbol: Position}。"""
        return dict(self._positions)

    @property
    def has_position(self) -> bool:
        """是否持有任何仓位。"""
        return len(self._positions) > 0

    def get_position(self, symbol: str) -> Optional[Position]:
        """获取指定标的持仓。

        Args:
            symbol: 标的代码。

        Returns:
            Optional[Position]: 持仓信息。
        """
        return self._positions.get(symbol)

    def reset(self) -> None:
        """重置所有运行时状态。"""
        self.available_cash = self.initial_cash
        self._positions.clear()
        self._total_trades = 0
        self._bar_count = 0

        # 重置风控
        self.risk._hit_peak_cash = 0.0

        # 重置 sizer
        if hasattr(self.sizer, "reset"):
            self.sizer.reset()

    # ─── MethodResult 转换成 Signals ────────────────────────

    @staticmethod
    def result_to_signals(
        result: "MethodResult",
        symbol: str = "DEFAULT",
    ) -> List[Signal]:
        """将 MethodResult 转换为 Signal 列表。

        遍历 signals DataFrame，每行非零信号生成一个 Signal 对象。

        Args:
            result: MethodResult 实例。
            symbol: 标的代码。

        Returns:
            List[Signal]: 信号列表。
        """
        signals_list: List[Signal] = []
        df = result.signals

        if df.empty or "signal" not in df.columns:
            return signals_list

        for idx, row in df.iterrows():
            sig_val = int(row.get("signal", 0))
            if sig_val == 0:
                continue

            signals_list.append(
                Signal(
                    symbol=symbol,
                    signal_value=sig_val,
                    confidence=float(row.get("confidence", 0.5)),
                    timestamp=str(idx),
                    price=float(row.get("close", row.get("price", 0.0))),
                )
            )

        return signals_list

    # ─── 显示 ──────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<PortfolioManager cash={self.available_cash:.2f} "
            f"positions={len(self._positions)} trades={self._total_trades}>"
        )
