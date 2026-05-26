"""
SignalConsumer — 将 Signal 对象映射为 OrderRequest 对象。

Phase 2 桥接器：策略输出 Signal → 回测引擎输入 OrderRequest。

映射规则：
  - signal.direction == "BUY"  → OrderSide.BUY
  - signal.direction == "SELL" → OrderSide.SELL
  - signal.direction == "HOLD" → None（不下单）
  - order_type 统一为 OrderType.MARKET
  - quantity 优先取自 extras["quantity"]，否则使用 config.default_quantity
  - 支持"只读观察者"模式（config.read_only 控制日志模式）

引用说明：
  - OrderSide, OrderType → backtest.order_executor（复用的枚举类型）
  - OrderRequest         → backtest.backtest_engine（策略 → 引擎的下单请求）
  - Signal               → signals.signal_protocol_v1（信号协议核心类）

author: 墨衡
created_time: 2026-05-20
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional

from ..backtest.order_executor import OrderSide, OrderType
from ..backtest.backtest_engine import OrderRequest
from .signal_protocol_v1 import Signal

# ── 日志 ──────────────────────────────────────────────────

import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# ConsumerConfig
# ═══════════════════════════════════════════════════════════


@dataclass
class ConsumerConfig:
    """Consumer 运行时配置。

    Attributes:
        read_only: 只读观察者模式。True 时 consume() 仍返回 OrderRequest，
                   但调用者应依此 flag 不实际发单（仅记录/分析）。
        default_quantity: signal.extras 中未提供 quantity 时的缺省值。
        fallback_price: 当 quantity 需要从价格推算但价格不可用时使用的兜底值。
    """

    read_only: bool = False
    default_quantity: int = 100
    fallback_price: float = 0.0


# ═══════════════════════════════════════════════════════════
# SignalConsumer
# ═══════════════════════════════════════════════════════════


class SignalConsumer:
    """将 Signal 对象映射为 OrderRequest 对象。

    核心功能：
      1. consume()  — 单信号 → OrderRequest（HOLD 方向返回 None）
      2. consume_batch() — 批量转换，返回非 None 的 OrderRequest 列表

    使用示例：
      consumer = SignalConsumer(ConsumerConfig(read_only=True))
      order = consumer.consume(signal)
      if order:
          logger.info("信号 %s 映射为订单: %s %s x%d",
                       signal.signal_id, order.side, order.symbol, order.quantity)
    """

    def __init__(self, config: Optional[ConsumerConfig] = None):
        """初始化 Consumer。

        Args:
            config: Consumer 运行时配置。缺省使用 ConsumerConfig()。
        """
        self.config = config or ConsumerConfig()

    # ── 公共方法 ─────────────────────────────────────────

    def consume(self, signal: Signal, context: Any = None) -> Optional[OrderRequest]:
        """将单个 Signal 映射为 OrderRequest。

        映射规则：
          1. direction == "HOLD" → 返回 None（不下单）
          2. direction == "BUY"  → OrderSide.BUY
          3. direction == "SELL" → OrderSide.SELL
          4. quantity 优先级：extras["quantity"] > config.default_quantity
          5. order_type 统一为 OrderType.MARKET

        Args:
            signal: Signal 协议 v1 信号对象。
            context: 可选的上下文信息（当前未使用，为扩展保留）。

        Returns:
            Optional[OrderRequest]: HOLD 方向返回 None，否则返回 OrderRequest 对象。

        Raises:
            ValueError: direction 值异常（BUY/SELL 之外的不可映射值）。
        """
        # ── HOLD 直接跳过 ──
        if signal.direction == "HOLD":
            logger.debug(
                "consume: signal=%s direction=HOLD → skip",
                signal.signal_id,
            )
            return None

        # ── Direction → OrderSide ──
        try:
            side = OrderSide[signal.direction]
        except KeyError:
            raise ValueError(
                f"无法映射 signal.direction='{signal.direction}' "
                f"到 OrderSide（期望 BUY / SELL / HOLD）"
            )

        # ── Quantity ──
        quantity = self._resolve_quantity(signal, context)

        # ── 构造 OrderRequest ──
        order = OrderRequest(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )

        # ── 只读模式日志 ──
        if self.config.read_only:
            logger.info(
                "[READ_ONLY] 信号 %s → 订单: %s %s x%d （仅观察，未发单）",
                signal.signal_id, side.value, signal.symbol, quantity,
            )

        return order

    def consume_batch(
        self, signals: List[Signal], context: Any = None
    ) -> List[OrderRequest]:
        """批量将 Signal 列表映射为 OrderRequest 列表。

        HOLD 方向的信号被过滤（不返回 None 占位）。

        Args:
            signals: Signal 对象列表。
            context: 可选的上下文信息（为扩展保留）。

        Returns:
            List[OrderRequest]: 可执行的下单请求列表，不含 None。
        """
        orders: List[OrderRequest] = []
        skipped = 0

        for signal in signals:
            order = self.consume(signal, context)
            if order is not None:
                orders.append(order)
            else:
                skipped += 1

        if skipped:
            logger.debug(
                "consume_batch: %d / %d 信号因 HOLD 跳过",
                skipped, len(signals),
            )

        return orders

    # ── 内部方法 ─────────────────────────────────────────

    def _resolve_quantity(
        self, signal: Signal, context: Any = None
    ) -> int:
        """解析下单数量。

        优先级：
          1. signal.extras.get("quantity") — 策略级指定
          2. config.default_quantity       — 全局缺省

        如果 extras.quantity 为 float，自动向下取整。

        Args:
            signal: Signal 对象。
            context: 上下文（预留，当前未使用）。

        Returns:
            int: 解析后的下单数量（保证 ≥ 1）。
        """
        # 策略指定
        qty = signal.extras.get("quantity")
        if qty is not None:
            try:
                qty_int = int(float(qty))
            except (ValueError, TypeError):
                qty_int = self.config.default_quantity
            return max(qty_int, 1)

        # 全局缺省
        return max(self.config.default_quantity, 1)
