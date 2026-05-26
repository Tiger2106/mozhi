"""
测试：SignalConsumer — Signal → OrderRequest 映射

覆盖场景：
  1. consume() 基础路径：BUY → OrderSide.BUY, SELL → OrderSide.SELL
  2. HOLD 方向返回 None
  3. quantity 优先级：extras["quantity"] > config.default_quantity
  4. 缺省 quantity 使用 config.default_quantity
  5. 只读观察者模式标记
  6. consume_batch() 批量转换（HOLD 自动过滤）
  7. 异常路径：无效 direction
  8. 浮点 quantity 自动向下取整

author: 墨衡
created_time: 2026-05-20
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pytest

from src.backtest.order_executor import OrderSide, OrderType
from src.backtest.backtest_engine import OrderRequest
from src.signals.signal_protocol_v1 import (
    Signal,
    CURRENT_PROTOCOL_VERSION,
    generate_signal_id,
)
from src.signals.consumer import SignalConsumer, ConsumerConfig


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


_TZ_EAST8 = timezone(timedelta(hours=8))


def _make_signal(
    direction: str = "BUY",
    symbol: str = "601857",
    confidence: float = 0.85,
    extras: Optional[Dict[str, Any]] = None,
) -> Signal:
    """创建一个标准的测试 Signal 对象。"""
    return Signal(
        signal_id=generate_signal_id(),
        symbol=symbol,
        direction=direction,        # type: ignore[arg-type]
        confidence=confidence,
        horizon="short",
        signal_type="trend",
        timestamp=datetime.now(_TZ_EAST8),
        protocol_version=CURRENT_PROTOCOL_VERSION,
        extras=extras or {},
    )


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def consumer() -> SignalConsumer:
    return SignalConsumer()


@pytest.fixture
def read_only_consumer() -> SignalConsumer:
    return SignalConsumer(ConsumerConfig(read_only=True))


# ═══════════════════════════════════════════════════════════════
# 单信号映射：基础路径
# ═══════════════════════════════════════════════════════════════


class TestConsumeBasic:
    """consume() 基本映射路径。"""

    def test_buy_direction(self, consumer: SignalConsumer):
        """BUY 方向 → OrderSide.BUY + OrderType.MARKET"""
        signal = _make_signal(direction="BUY")
        order = consumer.consume(signal)

        assert order is not None
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.symbol == "601857"
        assert order.quantity > 0

    def test_sell_direction(self, consumer: SignalConsumer):
        """SELL 方向 → OrderSide.SELL + OrderType.MARKET"""
        signal = _make_signal(direction="SELL")
        order = consumer.consume(signal)

        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.order_type == OrderType.MARKET
        assert order.symbol == "601857"

    def test_hold_returns_none(self, consumer: SignalConsumer):
        """HOLD 方向 → None（不下单）"""
        signal = _make_signal(direction="HOLD")
        order = consumer.consume(signal)

        assert order is None

    def test_symbol_preserved(self, consumer: SignalConsumer):
        """symbol 字段完整保留"""
        signal = _make_signal(symbol="600036")
        order = consumer.consume(signal)

        assert order is not None
        assert order.symbol == "600036"


# ═══════════════════════════════════════════════════════════════
# 数量解析
# ═══════════════════════════════════════════════════════════════


class TestQuantityResolution:
    """quantity 解析优先级。"""

    def test_quantity_from_extras(self, consumer: SignalConsumer):
        """extras["quantity"] 生效"""
        signal = _make_signal(extras={"quantity": 500})
        order = consumer.consume(signal)

        assert order is not None
        assert order.quantity == 500

    def test_quantity_default(self, consumer: SignalConsumer):
        """无 extras.quantity → 使用 config.default_quantity"""
        # ConsumerConfig 默认 default_quantity=100
        signal = _make_signal(extras={})
        order = consumer.consume(signal)

        assert order is not None
        assert order.quantity == 100

    def test_quantity_custom_default(self):
        """自定义 default_quantity"""
        consumer = SignalConsumer(ConsumerConfig(default_quantity=300))
        signal = _make_signal(extras={"price": 10.5})  # 无 quantity
        order = consumer.consume(signal)

        assert order is not None
        assert order.quantity == 300

    def test_quantity_float_floor(self, consumer: SignalConsumer):
        """浮点 quantity 被向下取整"""
        signal = _make_signal(extras={"quantity": 150.7})
        order = consumer.consume(signal)

        assert order is not None
        assert order.quantity == 150  # int(150.7) = 150

    def test_quantity_string_number(self, consumer: SignalConsumer):
        """字符串数字 quantity 被正确转换"""
        signal = _make_signal(extras={"quantity": "200"})
        order = consumer.consume(signal)

        assert order is not None
        assert order.quantity == 200

    def test_quantity_invalid_uses_default(self, consumer: SignalConsumer):
        """无效的 quantity → 兜底到 default"""
        signal = _make_signal(extras={"quantity": "abc"})
        order = consumer.consume(signal)

        assert order is not None
        assert order.quantity == 100  # default


# ═══════════════════════════════════════════════════════════════
# 只读观察者模式
# ═══════════════════════════════════════════════════════════════


class TestReadOnlyMode:
    """read_only 标记不影响返回值，但调用方应识别。"""

    def test_read_only_still_returns_order(self, read_only_consumer: SignalConsumer):
        """read_only=True 时仍返回 OrderRequest"""
        signal = _make_signal()
        order = read_only_consumer.consume(signal)

        assert order is not None
        assert isinstance(order, OrderRequest)

    def test_read_only_config_accessible(self, read_only_consumer: SignalConsumer):
        """read_only 标记可通过 config 访问"""
        assert read_only_consumer.config.read_only is True


# ═══════════════════════════════════════════════════════════════
# 批量映射
# ═══════════════════════════════════════════════════════════════


class TestConsumeBatch:
    """consume_batch() 批量转换。"""

    def test_batch_all_directions(self, consumer: SignalConsumer):
        """混合方向：HOLD 被过滤"""
        signals = [
            _make_signal(direction="BUY"),
            _make_signal(direction="HOLD"),
            _make_signal(direction="SELL"),
            _make_signal(direction="HOLD"),
        ]
        orders = consumer.consume_batch(signals)

        assert len(orders) == 2
        assert all(isinstance(o, OrderRequest) for o in orders)
        assert orders[0].side == OrderSide.BUY
        assert orders[1].side == OrderSide.SELL

    def test_batch_empty_list(self, consumer: SignalConsumer):
        """空列表 → 空列表"""
        orders = consumer.consume_batch([])
        assert orders == []

    def test_batch_all_hold(self, consumer: SignalConsumer):
        """全是 HOLD → 空列表"""
        signals = [
            _make_signal(direction="HOLD"),
            _make_signal(direction="HOLD"),
        ]
        orders = consumer.consume_batch(signals)
        assert orders == []

    def test_batch_preserves_order(self, consumer: SignalConsumer):
        """非 HOLD 信号保持原始顺序"""
        signals = [
            _make_signal(direction="BUY", symbol="A"),
            _make_signal(direction="HOLD", symbol="B"),
            _make_signal(direction="SELL", symbol="C"),
        ]
        orders = consumer.consume_batch(signals)

        assert len(orders) == 2
        assert orders[0].symbol == "A"
        assert orders[0].side == OrderSide.BUY
        assert orders[1].symbol == "C"
        assert orders[1].side == OrderSide.SELL


# ═══════════════════════════════════════════════════════════════
# 异常路径
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界与异常。"""

    def test_invalid_direction_raises(self, consumer: SignalConsumer):
        """无效 direction → ValueError"""
        signal = _make_signal(direction="BUY")
        # 覆写 direction 为非法值（绕过 Signal 验证）
        object.__setattr__(signal, "direction", "INVALID")

        with pytest.raises(ValueError, match="无法映射"):
            consumer.consume(signal)

    def test_zero_quantity_default(self):
        """extras.quantity=0 → 至少返回 1（max(qty, 1)）"""
        consumer = SignalConsumer(ConsumerConfig(default_quantity=0))
        signal = _make_signal(extras={"quantity": 0})
        order = consumer.consume(signal)

        assert order is not None
        assert order.quantity >= 1
