"""
墨枢 — SignalBacktestAdapter
旧回测引擎的 Signal 适配器。

让 BacktestEngine 能消费策略输出的 Signal 对象，自动通过 SignalConsumer
转换为 OrderRequest，而不修改回测引擎本身。

设计原理：
  - 使用装饰器模式包装 Strategy 或 BacktestEngine
  - 对引擎和策略代码零侵入（不修改现有文件）
  - 与 DualValidator 配合使用，实现新旧路径并行验证

用法::

    from src.signals.signal_backtest_adapter import SignalBacktestAdapter
    from src.signals.consumer import SignalConsumer, ConsumerConfig

    # 包装策略
    consumer = SignalConsumer(ConsumerConfig(read_only=False))
    adapter = SignalBacktestAdapter(consumer=consumer)
    wrapped_strategy = adapter.wrap_strategy(inner_strategy)

    # 创建引擎时传入包装后的策略
    engine = BacktestEngine(config=config, strategy=wrapped_strategy)
    result = engine.run(bars)

    # 若需双路径并行验证：
    from tests.validation.dual_validator import DualValidator
    old_engine = BacktestEngine(config=config, strategy=inner_strategy)
    new_engine = BacktestEngine(config=config, strategy=wrapped_strategy)
    # ... 分别运行后比较

author: 墨衡
created_time: 2026-05-20
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from src.backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Bar,
    OrderRequest,
    Strategy,
)
from src.signals.consumer import SignalConsumer, ConsumerConfig
from src.signals.signal_protocol_v1 import Signal

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# SignalToOrderStrategy — 包装策略
# ═══════════════════════════════════════════════════════════════


class SignalToOrderStrategy(Strategy):
    """将输出 Signal 的策略包装为输出 OrderRequest 的策略。

    内部策略（inner_strategy）的 on_bar 应返回 Optional[List[Signal]]，
    此包装器通过 SignalConsumer 将其转换为 OrderRequest 列表，
    供 BacktestEngine 消费。

    不修改内部策略的 on_start / on_end 行为。
    """

    def __init__(
        self,
        inner_strategy: Strategy,
        consumer: Optional[SignalConsumer] = None,
    ):
        """初始化包装策略。

        Args:
            inner_strategy: 输出 Signal 的内部策略实例。
            consumer: SignalConsumer 实例。默认为 read_only=False 的 Consumer。
        """
        super().__init__()
        self._inner = inner_strategy
        self._consumer = consumer or SignalConsumer(
            ConsumerConfig(read_only=False)
        )

    def on_start(self, context: Any) -> None:
        """转发给内部策略。"""
        self._inner.on_start(context)

    def on_bar(
        self, context: Any, bar: Bar
    ) -> Optional[List[OrderRequest]]:
        """调用内部策略获取 signals，通过 Consumer 转为 OrderRequest。

        步骤:
          1. 调用 inner_strategy.on_bar() → Optional[List[Signal]]
          2. 若返回 None，直接返回 None（无操作）
          3. 通过 consumer.consume_batch() 批量转换
          4. 返回转换后的 OrderRequest 列表

        Args:
            context: BacktestContext
            bar: 当前 K 线

        Returns:
            Optional[List[OrderRequest]]: 转换后的下单请求，或无操作时 None
        """
        signals = self._inner.on_bar(context, bar)

        if signals is None:
            return None

        # 确保是 Signal 列表
        if not isinstance(signals, list):
            logger.warning(
                "SignalToOrderStrategy: inner_strategy.on_bar 返回非列表类型 %s",
                type(signals).__name__,
            )
            return None

        # 过滤转换为 OrderRequest
        orders = self._consumer.consume_batch(signals, context)

        if not orders:
            return None

        logger.debug(
            "SignalToOrderStrategy: %d signals → %d orders [bar.date=%s, symbol=%s]",
            len(signals),
            len(orders),
            bar.date,
            bar.symbol,
        )

        return orders

    def on_end(self, context: Any) -> None:
        """转发给内部策略。"""
        self._inner.on_end(context)


# ═══════════════════════════════════════════════════════════════
# SignalBacktestAdapter
# ═══════════════════════════════════════════════════════════════


class SignalBacktestAdapter:
    """旧回测引擎的 Signal 适配器。

    提供以下适配方式：

    1. wrap_strategy(strategy) → SignalToOrderStrategy
       装饰策略模式：将输出 Signal 的策略包装为输出 OrderRequest 的策略

    2. run_with_signal(engine, strategy, bars) → BacktestResult
       一次运行模式：直接在现有引擎上跑带 Signal 的策略

    3. wrap_engine(engine, strategy) → object
       引擎包装模式（预留）：返回包装后的引擎（自动适配 signal→order）
    """

    def __init__(self, consumer: Optional[SignalConsumer] = None):
        """初始化适配器。

        Args:
            consumer: SignalConsumer 实例。默认为默认配置的 Consumer。
        """
        self.consumer = consumer or SignalConsumer()

    # ── 策略包装 ─────────────────────────────────────────────

    def wrap_strategy(self, inner_strategy: Strategy) -> SignalToOrderStrategy:
        """将输出 Signal 的策略包装为输出 OrderRequest 的策略。

        Args:
            inner_strategy: 输出 Signal 的内部策略实例。

        Returns:
            SignalToOrderStrategy: 包装后的策略，可用于 BacktestEngine。
        """
        return SignalToOrderStrategy(
            inner_strategy=inner_strategy,
            consumer=self.consumer,
        )

    # ── 一次运行模式 ─────────────────────────────────────────

    def run_with_signal(
        self,
        engine: BacktestEngine,
        strategy: Strategy,
        bars: List[Bar],
        config: Optional[BacktestConfig] = None,
    ) -> BacktestResult:
        """在现有 BacktestEngine 上运行带 Signal 的策略。

        创建一个新引擎（为避免修改传入引擎）并使用包装后的策略。

        Args:
            engine: 模板引擎（用于复制配置）
            strategy: 输出 Signal 的策略
            bars: K 线数据
            config: 可选的新配置（覆盖 engine.config）

        Returns:
            BacktestResult: 回测结果
        """
        cfg = config or engine.config
        wrapped = self.wrap_strategy(strategy)

        new_engine = BacktestEngine(config=cfg, strategy=wrapped)
        return new_engine.run(bars)

    # ── 引擎包装（预留） ─────────────────────────────────────

    def wrap_engine(
        self,
        engine: BacktestEngine,
        strategy: Strategy,
    ) -> BacktestEngine:
        """返回包装后的引擎。

        注意：包装后的引擎与原引擎共享 context，不适合并发运行。
        推荐使用 wrap_strategy + 独立 Engine 的方式。

        Args:
            engine: 需要适配的 BacktestEngine 实例。
            strategy: 输出 Signal 的策略。

        Returns:
            BacktestEngine: 新的引擎实例，已挂载包装策略。
        """
        wrapped = self.wrap_strategy(strategy)
        new_engine = BacktestEngine(config=engine.config, strategy=wrapped)
        return new_engine


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def create_dual_engines(
    config: BacktestConfig,
    inner_strategy: Strategy,
    consumer: Optional[SignalConsumer] = None,
) -> tuple:
    """创建一对引擎：旧路径引擎 + 新路径引擎。

    用于 DualValidator 的双路径并行验证。

    Args:
        config: 回测配置
        inner_strategy: 输出 Signal 的策略
        consumer: 可选的 SignalConsumer

    Returns:
        tuple: (old_engine, new_engine)
          - old_engine: 直接使用 inner_strategy（期望返回 OrderRequest）
          - new_engine: 通过 SignalBacktestAdapter 包装

    注意：如果 inner_strategy 返回 Signal 而非 OrderRequest，
    old_engine 的 run() 会失败。此时应使用旧的 SignalBridge-based strategy
    作为 old_engine 的策略。
    """
    adapter = SignalBacktestAdapter(consumer=consumer)
    wrapped_strategy = adapter.wrap_strategy(inner_strategy)

    old_engine = BacktestEngine(config=config, strategy=inner_strategy)
    new_engine = BacktestEngine(config=config, strategy=wrapped_strategy)

    return old_engine, new_engine
