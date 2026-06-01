"""
墨枢 - p0_fixes.opening_execution
OpeningPriceExecutor — 开盘价执行器 (P1_004b)

在集合竞价阶段使用 auction_engine 确定开盘价，并以开盘价为基准执行订单。

集成：
  - auction_engine: 集合竞价撮合（P1_004a）
  - DynamicSlippage: 动态滑点（P1_002b，可选）
  - 开盘价边界检查（涨跌停 ±10%/±20%）
  - 竞价阶段判定

开盘价执行流程：
  1. 接收委托簿（买单/卖单集合）
  2. auction_engine.match_auction_price() → 既定开盘价
  3. 检查开盘价是否在涨跌停范围内
  4. 按开盘价（+滑点）执行订单
  5. 记录成交

author: moheng
created_time: 2026-05-28T13:16+08:00
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..order_executor import (
    FillReport,
    OrderExecutor,
    OrderSide,
    OrderType,
    TradeRecord,
)

from .auction_engine import (
    AuctionPhase,
    get_auction_phase,
    match_auction_price,
)


# ═══════════════════════════════════════════════════════════════
# DynamicSlippage 导入（可选依赖）
# ═══════════════════════════════════════════════════════════════

try:
    from .dynamic_slippage import DynamicSlippage

    _HAS_SLIPPAGE = True
except ImportError:
    DynamicSlippage = None  # type: ignore[assignment,misc]
    _HAS_SLIPPAGE = False


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

# A股涨跌停限制
LIMIT_UP_PCT = 0.10     # 主板 ±10%
LIMIT_DOWN_PCT = 0.10
ST_LIMIT_UP_PCT = 0.05  # ST ±5%
ST_LIMIT_DOWN_PCT = 0.05
KCB_LIMIT_UP_PCT = 0.20  # 科创板/创业板 ±20%
KCB_LIMIT_DOWN_PCT = 0.20

# 默认开盘滑点率（‰）
DEFAULT_OPEN_SLIPPAGE = 0.0008  # 0.08%

# 竞价阶段到 9:30 的缓冲秒数
OPENING_EXECUTION_DELAY_SEC = 0.0

# 最小成交量阈值（防止僵尸成交）
MIN_MATCHED_VOLUME = 1


# ═══════════════════════════════════════════════════════════════
# 内联辅助函数
# ═══════════════════════════════════════════════════════════════


def is_st_stock(board_code: Optional[str] = None, symbol: Optional[str] = None) -> bool:
    """判断是否为 ST / *ST 股票。"""
    code = (board_code or symbol or "").upper()
    return "ST" in code


def get_price_limits(
    prev_close: float,
    is_st: bool = False,
    is_kcb: bool = False,
) -> Tuple[float, float]:
    """计算涨跌停价格边界。

    Args:
        prev_close: 前收盘价
        is_st: 是否为 ST 股票
        is_kcb: 是否为科创板/创业板股票（ST 优先判定）

    Returns:
        (lower_limit, upper_limit) 价格边界
    """
    if is_st:
        up = prev_close * (1.0 + ST_LIMIT_UP_PCT)
        down = prev_close * (1.0 - ST_LIMIT_DOWN_PCT)
    elif is_kcb:
        up = prev_close * (1.0 + KCB_LIMIT_UP_PCT)
        down = prev_close * (1.0 - KCB_LIMIT_DOWN_PCT)
    else:
        up = prev_close * (1.0 + LIMIT_UP_PCT)
        down = prev_close * (1.0 - LIMIT_DOWN_PCT)
    return (round(down, 2), round(up, 2))


def clamp_to_price_limits(price: float, lower: float, upper: float) -> float:
    """将价格限制在指定边界范围内。"""
    return max(lower, min(upper, price))


# ═══════════════════════════════════════════════════════════════
# OpeningPriceExecutor
# ═══════════════════════════════════════════════════════════════

class OpeningPriceExecutor:
    """
    开盘价执行器 — 在集合竞价阶段确定开盘价并执行订单。

    参数
    ----------
    executor : OrderExecutor
        底层的 OrderExecutor 实例，用于最终执行成交。
    slippage_model : DynamicSlippage, optional
        动态滑点模型。None 时使用固定默认滑点率。
    prev_close : float, optional
        前收盘价。用于涨跌停边界检查。
    board_code : str, optional
        板块代码（如 '600000', '300750', '688xxx'），用于涨跌停边界判断。
    """

    def __init__(
        self,
        executor: OrderExecutor,
        slippage_model: Optional["DynamicSlippage"] = None,
        prev_close: Optional[float] = None,
        board_code: Optional[str] = None,
    ):
        if not isinstance(executor, OrderExecutor):
            raise TypeError("executor 必须是 OrderExecutor 实例")
        self.executor = executor
        self.slippage_model = slippage_model
        self.prev_close = prev_close
        self.board_code = board_code

        # ── 内部状态 ──
        self._buy_orders: List[Dict[str, Any]] = []
        self._sell_orders: List[Dict[str, Any]] = []
        self._opening_price: Optional[float] = None
        self._matched_volume: int = 0

        # ── 统计 ──
        self.stats: Dict[str, int] = {
            "total_open_orders": 0,
            "total_open_filled": 0,
            "total_open_rejected": 0,
            "auction_run_count": 0,
            "executions_delegated": 0,
        }

    # ──────────────── 委托簿管理 ────────────────

    def set_auction_orders(
        self,
        buy_orders: List[Dict[str, Any]],
        sell_orders: List[Dict[str, Any]],
    ) -> dict:
        """设置集合竞价委托簿。

        Args:
            buy_orders: 买单列表，每个元素含 {"price": float, "volume": int}
            sell_orders: 卖单列表，每个元素含 {"price": float, "volume": int}

        Returns:
            {"status": "OK", "buy_count": int, "sell_count": int}
        """
        self._buy_orders = list(buy_orders)
        self._sell_orders = list(sell_orders)

        # 重置开盘价缓存
        self._opening_price = None
        self._matched_volume = 0

        return {
            "status": "OK",
            "buy_count": len(self._buy_orders),
            "sell_count": len(self._sell_orders),
        }

    def get_order_book_size(self) -> Dict[str, int]:
        """返回当前委托簿的大小。"""
        return {
            "buy": len(self._buy_orders),
            "sell": len(self._sell_orders),
        }

    def clear_auction_orders(self) -> None:
        """清空委托簿。"""
        self._buy_orders = []
        self._sell_orders = []
        self._opening_price = None
        self._matched_volume = 0

    # ──────────────── 开盘价确定 ────────────────

    def get_opening_price(self) -> Optional[float]:
        """执行集合竞价撮合，返回开盘价。

        通过 auction_engine.match_auction_price() 完成撮合，
        同时检查价格是否在涨跌停范围内。

        Returns:
            开盘价（float）或 None（无法形成有效开盘价）
        """
        price, volume = match_auction_price(
            self._buy_orders,
            self._sell_orders,
            prev_close=self.prev_close,
        )

        if price is None:
            self._opening_price = None
            self._matched_volume = 0
            return None

        # 开盘价边界检查（有 prev_close 时）
        if self.prev_close is not None:
            lower, upper = get_price_limits(
                self.prev_close,
                is_st=is_st_stock(self.board_code),
                is_kcb=self._is_kcb(),
            )
            price = clamp_to_price_limits(price, lower, upper)

        self._opening_price = round(price, 2)
        self._matched_volume = volume
        self.stats["auction_run_count"] += 1

        return self._opening_price

    def get_matched_volume(self) -> int:
        """返回最近一次撮合的匹配成交量。"""
        return self._matched_volume

    def has_valid_opening_price(self) -> bool:
        """检查是否已形成有效的开盘价。"""
        return self._opening_price is not None and self._matched_volume > 0

    # ──────────────── 竞价阶段判定 ────────────────

    def get_auction_phase(self, timestamp: datetime.datetime) -> AuctionPhase:
        """委托给 auction_engine 判定当前竞价阶段。

        Args:
            timestamp: 待判定时间戳

        Returns:
            AuctionPhase 枚举值

        Raises:
            ValueError: 时间戳不在 A 股交易时段内
        """
        return get_auction_phase(timestamp)

    def is_in_auction_window(self, timestamp: datetime.datetime) -> bool:
        """检查是否在集合竞价窗口（9:15-9:25）。

        Returns:
            True 如果在集合竞价时段内
        """
        try:
            phase = self.get_auction_phase(timestamp)
            return phase in (AuctionPhase.PRE_OPEN, AuctionPhase.PRE_OPEN_CHECK)
        except (ValueError, TypeError):
            return False

    def is_after_opening(self, timestamp: datetime.datetime) -> bool:
        """检查是否在开盘后（9:25 之后）。

        Returns:
            True 如果在开盘价已出之后
        """
        try:
            return self.get_auction_phase(timestamp) == AuctionPhase.CONTINUOUS
        except (ValueError, TypeError):
            return False

    # ──────────────── 开盘价执行 ────────────────

    def execute_open_market(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        fee_rate: Optional[float] = None,
        market_cap: Optional[float] = None,
        daily_volume_value: Optional[float] = None,
        volatility: Optional[float] = None,
        force_open: bool = False,
    ) -> FillReport:
        """
        以开盘价执行市价单。

        执行流程：
          1. 确认有效开盘价（若无，尝试撮合）
          2. 计算开盘滑点
          3. 计算有效执行价 = 开盘价 * (1 ± 滑点率)
          4. 委托给内部 executor 执行
          5. 记录成交

        Args:
            symbol: 标的代码
            side: 买卖方向
            quantity: 委托数量（正数买入，负数卖出）
            fee_rate: 可选手续费率覆盖
            market_cap: 市值（亿），用于动态滑点
            daily_volume_value: 日均成交额（元），用于动态滑点
            volatility: 波动率，用于动态滑点
            force_open: 若 True，即使委托簿为空也尝试使用 prev_close 执行

        Returns:
            FillReport
        """
        self.stats["total_open_orders"] += 1

        # ── Step 1: 确认开盘价 ──
        opening_price = self._opening_price
        if opening_price is None:
            opening_price = self.get_opening_price()

        if opening_price is None:
            if force_open and self.prev_close is not None:
                opening_price = self.prev_close
            else:
                self.stats["total_open_rejected"] += 1
                return FillReport(
                    filled=False,
                    fill_price=0.0,
                    fill_quantity=0,
                    fill_fee=0.0,
                    message="无法确定开盘价",
                )

        # ── Step 2: 计算滑点 ──
        slippage_rate = self._compute_open_slippage(
            opening_price, quantity, market_cap, daily_volume_value, volatility,
        )

        # ── Step 3: 计算有效执行价 ──
        # 将滑点率写入 executor，由底层 OrderExecutor 在成交时统一应用
        # （避免在 OpeningPriceExecutor 中预调价后再被 executor 二次滑点）
        effective_price = opening_price
        if self.prev_close is not None:
            lower, upper = get_price_limits(
                self.prev_close,
                is_st=is_st_stock(self.board_code),
                is_kcb=self._is_kcb(),
            )
            effective_price = clamp_to_price_limits(effective_price, lower, upper)

        # ── Step 4: 委托执行（设置 executor.slippage_rate 使底层应用滑点）──
        original_rate = self.executor.slippage_rate
        self.executor.slippage_rate = slippage_rate
        try:
            result = self.executor.execute_market(
                symbol, side, abs(quantity), effective_price, fee_rate,
            )
            self._annotate_open_trade(result, opening_price, slippage_rate)
            if result.filled:
                self.stats["total_open_filled"] += 1
            self.stats["executions_delegated"] += 1
            return result
        finally:
            self.executor.slippage_rate = original_rate

    def execute_open_limit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        limit_price: float,
        fee_rate: Optional[float] = None,
    ) -> FillReport:
        """
        以开盘价执行限价单。

        限价单触发条件：
          - 买单：limit_price >= opening_price（能以不高于限价的价格买入）
          - 卖单：limit_price <= opening_price（能以不低于限价的价格卖出）

        Args:
            symbol: 标的代码
            side: 买卖方向
            quantity: 委托数量
            limit_price: 限价
            fee_rate: 可选手续费率覆盖

        Returns:
            FillReport
        """
        self.stats["total_open_orders"] += 1

        # ── Step 1: 确认开盘价 ──
        opening_price = self._opening_price
        if opening_price is None:
            opening_price = self.get_opening_price()

        if opening_price is None:
            self.stats["total_open_rejected"] += 1
            return FillReport(
                filled=False,
                fill_price=0.0,
                fill_quantity=0,
                fill_fee=0.0,
                message="无法确定开盘价，限价单未触发",
            )

        # ── Step 2: 判断是否触发 ──
        triggered = False
        if side == OrderSide.BUY and limit_price >= opening_price:
            triggered = True
        elif side == OrderSide.SELL and limit_price <= opening_price:
            triggered = True

        if not triggered:
            self.stats["total_open_rejected"] += 1
            return FillReport(
                filled=False,
                fill_price=0.0,
                fill_quantity=0,
                fill_fee=0.0,
                message=f"限价单未触发: limit={limit_price}, open={opening_price}",
            )

        # ── Step 3: 以开盘价成交（限价单无额外滑点加成）──
        result = self.executor.execute_market(
            symbol, side, abs(quantity), opening_price, fee_rate,
        )
        self._annotate_open_trade(result, opening_price, 0.0)
        if result.filled:
            self.stats["total_open_filled"] += 1
        self.stats["executions_delegated"] += 1
        return result

    # ──────────────── 滑点计算 ────────────────

    def _compute_open_slippage(
        self,
        price: float,
        quantity: int,
        market_cap: Optional[float] = None,
        daily_volume_value: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> float:
        """计算开盘滑点率。

        优先使用 DynamicSlippage（若已注入），否则使用固定默认值。

        开盘滑点特征（相对盘中）：
          - 开盘流动性通常较好 → 对 MEGA/LARGE 更友好
          - 但偶尔有跳空 → 对小盘股增加保护
        """
        if self.slippage_model is not None:
            order_value = abs(price * abs(quantity))
            return self.slippage_model.get_slippage_rate(
                market_cap=market_cap,
                board_code=self.board_code,
                order_value=order_value,
                daily_volume_value=daily_volume_value,
                volatility=volatility,
            )
        return DEFAULT_OPEN_SLIPPAGE

    # ──────────────── 辅助方法 ────────────────

    def _is_kcb(self) -> bool:
        """判断是否为科创板/创业板。"""
        code = (self.board_code or "").strip()
        return code.startswith("688") or code.startswith("300")

    def _annotate_open_trade(
        self,
        result: FillReport,
        opening_price: float,
        slippage_rate: float,
    ) -> None:
        """为成交记录注入开盘价和滑点信息。"""
        if result.trade is not None:
            result.trade.slippage = slippage_rate

    # ──────────────── 内部 executor 委托 ────────────────

    def execute_market(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        fee_rate: Optional[float] = None,
    ) -> FillReport:
        """直接委托给内部 executor 执行市价单（无开盘价处理）。"""
        return self.executor.execute_market(symbol, side, quantity, price, fee_rate)

    def execute_limit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        limit_price: float,
        current_price: float,
        fee_rate: Optional[float] = None,
    ) -> FillReport:
        """直接委托给内部 executor 执行限价单。"""
        return self.executor.execute_limit(
            symbol, side, quantity, limit_price, current_price, fee_rate,
        )

    # ──────────────── 查询 / 重置 ────────────────

    def get_stats(self) -> Dict[str, int]:
        """返回当前统计快照。"""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """重置所有统计。"""
        self.stats = {
            "total_open_orders": 0,
            "total_open_filled": 0,
            "total_open_rejected": 0,
            "auction_run_count": 0,
            "executions_delegated": 0,
        }
        self.clear_auction_orders()

    # ──────────────── 属性 ────────────────

    @property
    def opening_price(self) -> Optional[float]:
        """当前开盘价（若已撮合）。"""
        return self._opening_price

    @property
    def context(self):
        """委托到内部 executor 的回测上下文。"""
        return self.executor.context

    @property
    def trade_history(self) -> list:
        """委托到内部 executor 的成交记录列表。"""
        return self.executor.trade_history

    @property
    def slippage_rate(self) -> float:
        """外部可见的滑点率（从内部 executor 读取）。"""
        return self.executor.slippage_rate

    @slippage_rate.setter
    def slippage_rate(self, value: float) -> None:
        """设置内部 executor 的滑点率。"""
        self.executor.slippage_rate = value

    def __repr__(self) -> str:
        op = f"open={self._opening_price}" if self._opening_price else "open=?"
        vol = f"vol={self._matched_volume}"
        model = "Dynamic" if self.slippage_model else "Fixed"
        return (
            f"<OpeningPriceExecutor {op} {vol} "
            f"slippage={model} "
            f"orders={self.stats['total_open_orders']}>"
        )
