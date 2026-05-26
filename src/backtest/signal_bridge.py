"""
墨枢 - SignalBridge
信号桥接层：将已有组件（tech_signal_generator / indicator_engine / factor_calculator）
的输出转换为回测引擎可消费的 OrderRequest。同时提供逐Bar计算、缓存等基础设施。

依赖的已有组件路径（在 import 时读取）：
  - automation_v2/paper_trade/tech_signal_generator.py
  - automation_v2/phase1_core/indicator_engine.py
  - automation_v2/phase1_core/factor_calculator.py

用法::

    from .signal_bridge import SignalBridge, SignalStrategy

    class MyStrategy(SignalStrategy):
        def on_bar(self, ctx, bar):
            # 通过桥接器获取信号
            orders = self.bridge.signal_to_orders(ctx, bar, threshold=0.5)
            # 读取指标
            rsi = self.bridge.get_indicator(bar, "rsi14")
            # 读取因子
            f = self.bridge.get_factor(bar, "momentum")
            return orders
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

# ── 尝试导入已有组件 ─────────────────────────────────────
# 采用惰性/防御式导入，允许 SignalBridge 在组件未就绪时以降级模式运行

_TSG_AVAILABLE = False
_IE_AVAILABLE = False
_FC_AVAILABLE = False

# 加入自动化模块路径
_AUTO_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "automation_v2")
)
if _AUTO_DIR not in sys.path:
    sys.path.insert(0, _AUTO_DIR)

try:
    from paper_trade.tech_signal_generator import (
        generate_backtest_signals,
        TechnicalSignalGenerator,
    )

    _TSG_AVAILABLE = True
except ImportError:
    TechnicalSignalGenerator = None  # type:ignore
    generate_backtest_signals = None  # type:ignore


try:
    from phase1_core.indicator_engine import IndicatorEngine

    _IE_AVAILABLE = True
except ImportError:
    IndicatorEngine = None  # type:ignore


try:
    from phase1_core.factor_calculator import FactorCalculator

    _FC_AVAILABLE = True
except ImportError:
    FactorCalculator = None  # type:ignore

# ── 回测引擎类型 ─────────────────────────────────────────
from .backtest_engine import Bar, OrderRequest, OrderSide, OrderType, Strategy


# ============================================================
# P1-32: SignalBridge 核心 — 信号 → OrderRequest
# ============================================================


@dataclass
class SignalBridgeConfig:
    """SignalBridge 配置"""

    # 信号列名映射（tech_signal_generator 输出的 DataFrame）
    signal_col: str = "signal"  # 预期值: 1 (买入), -1 (卖出), 0 (无操作)
    strength_col: str = "strength"  # 信号强度（可选，用于仓位缩放）

    # 下单参数
    default_quantity: int = 100
    order_type: OrderType = OrderType.MARKET
    max_position_pct: float = 0.15  # 单标的占总资金比例上限

    # 缓存开关
    cache_indicators: bool = True
    cache_factors: bool = True


class SignalBridge:
    """
    P1-32 + P1-33 + P1-34 信号桥接器。

    职责：
      1. 将 tech_signal_generator 的回测信号 → OrderRequest（P1-32）
      2. 逐Bar回调 IndicatorEngine.compute()，带缓存（P1-33）
      3. 逐Bar计算因子值，按交易日缓存（P1-34）

    每个回测 session 应创建一个 SignalBridge 实例，在 on_start 中初始化。
    """

    def __init__(self, config: Optional[SignalBridgeConfig] = None):
        self.config = config or SignalBridgeConfig()

        # ── 信号缓存 ──────────────────────────────────────
        # 格式: {(date, symbol): signal_value}
        self._signal_cache: Dict[Tuple[str, str], float] = {}

        # ── P1-33: 指标缓存 ────────────────────────────────
        # 格式: {(date, symbol, indicator_name): value}
        self._indicator_cache: Dict[Tuple[str, str, str], Any] = {}

        # ── P1-34: 因子缓存（按交易日 + symbol 分组） ────
        # 格式: {(date, symbol, factor_name): value}
        self._factor_cache: Dict[Tuple[str, str, str], Any] = {}

        # ── 跟踪已计算的日期（避免重复计算整日因子） ────
        self._factor_dates_done: set = set()

        # ── 组件实例（惰性创建） ──────────────────────────
        self._indicator_engine: Any = None
        self._factor_calculator: Any = None

        # ── 信号发生器 ─────────────────────────────────────
        self._signal_df: Any = None  # 预生成的回测信号 DataFrame

    # ═══════════════════════════════════════════════════════════
    # P1-32: 信号 → OrderRequest
    # ═══════════════════════════════════════════════════════════

    def load_signals(self, signal_df: Any) -> None:
        """
        加载 tech_signal_generator 生成的信号 DataFrame。

        要求 signal_df 至少包含列: ['date', 'symbol', 'signal']
        signal 列取值: 1 (买入), -1 (卖出), 0 (无操作)

        也接受由 generate_backtest_signals() 直接输出的 DataFrame。
        """
        self._signal_df = signal_df
        self._build_signal_cache()

    def _build_signal_cache(self) -> None:
        """将 DataFrame 信号预加载到字典缓存，实现 O(1) 查找。"""
        if self._signal_df is None:
            return
        df = self._signal_df
        col = self.config.signal_col

        for _, row in df.iterrows():
            key = (row["date"], row["symbol"])
            self._signal_cache[key] = row.get(col, 0)

    def get_signal(self, bar: Bar) -> float:
        """
        获取某 Bar 对应的信号值。

        返回:
            - 1.0  → 买入信号
            - -1.0 → 卖出信号
            - 0.0  → 无操作
        """
        key = (bar.date, bar.symbol)
        return self._signal_cache.get(key, 0.0)

    def signal_to_orders(
        self,
        context: Any,
        bar: Bar,
        threshold: float = 0.0,
        quantity_override: Optional[int] = None,
    ) -> Optional[List[OrderRequest]]:
        """
        核心方法：将信号转换为 OrderRequest 列表。

        参数
        ----------
        context : BacktestContext
            回测上下文，用于获取当前持仓/资金信息。
        bar : Bar
            当前 K 线。
        threshold : float
            信号绝对值阈值，信号强度 > threshold 时才下单。
        quantity_override : int, optional
            强制指定下单数量（如 None 则按 default_quantity 计算）。

        返回
        -------
        Optional[List[OrderRequest]]
            下单请求列表，无信号时返回 None。
        """
        signal = self.get_signal(bar)
        if abs(signal) <= threshold:
            return None

        quantity = quantity_override or self.config.default_quantity

        # 按资金比例限制下单数量
        if context and context.available_capital > 0:
            max_cost = context.available_capital * self.config.max_position_pct
            max_qty = int(max_cost / (bar.close * 1.001))  # 预留滑点/手续费
            quantity = min(quantity, max_qty)
            quantity = max(quantity, 100)  # 至少一手（A股）

        # 取 100 的倍数
        quantity = (quantity // 100) * 100
        if quantity <= 0:
            return None

        orders: List[OrderRequest] = []
        if signal > 0:
            orders.append(
                OrderRequest(
                    symbol=bar.symbol,
                    side=OrderSide.BUY,
                    quantity=quantity,
                    order_type=self.config.order_type,
                )
            )
        elif signal < 0:
            # 卖出信号：检查是否有持仓
            if context and context.positions.has_position(bar.symbol):
                pos = context.positions.get(bar.symbol)
                sell_qty = min(quantity, pos.quantity)
                if sell_qty > 0:
                    orders.append(
                        OrderRequest(
                            symbol=bar.symbol,
                            side=OrderSide.SELL,
                            quantity=sell_qty,
                            order_type=self.config.order_type,
                        )
                    )

        return orders if orders else None

    # ═══════════════════════════════════════════════════════════
    # P1-33: IndicatorEngine 逐Bar计算集成
    # ═══════════════════════════════════════════════════════════

    def _lazy_indicator_engine(self) -> Any:
        """惰性初始化 IndicatorEngine 实例。"""
        if self._indicator_engine is None and IndicatorEngine is not None:
            self._indicator_engine = IndicatorEngine()
        return self._indicator_engine

    def get_indicator(
        self,
        bar: Bar,
        indicator_name: str,
        include_bar_data: Optional[Dict[str, Any]] = None,
        force_recompute: bool = False,
    ) -> Any:
        """
        获取指定指标值（P1-33）。

        先查缓存（当 cache_indicators=True 时），未命中则回调
        IndicatorEngine.compute() 实时计算。

        参数
        ----------
        bar : Bar
            当前 K 线。
        indicator_name : str
            指标名，如 "rsi14", "ma5", "macd", "boll_upper"。
        include_bar_data : dict, optional
            额外 Bar 上下文数据（如历史 K 线列表）。
        force_recompute : bool
            是否强制重算（忽略缓存）。

        返回
        -------
        Any
            指标计算值。
        """
        cache_key = (bar.date, bar.symbol, indicator_name)

        # ── 缓存命中 ──────────────────────────────────────
        if (
            self.config.cache_indicators
            and not force_recompute
            and cache_key in self._indicator_cache
        ):
            return self._indicator_cache[cache_key]

        # ── 回调 IndicatorEngine.compute() ────────────────
        engine = self._lazy_indicator_engine()
        value: Any = None

        if engine is not None:
            # IndicatorEngine 预期的入参模式（根据实际接口调整）：
            #   1) compute(bar_data, indicator_name) → value
            #   2) compute(df_or_list, indicator_name) → Series
            bar_data = include_bar_data or self._bar_to_dict(bar)
            try:
                value = engine.compute(bar_data, indicator_name)
            except Exception:
                # 容错：尝试备用接口
                try:
                    value = engine.compute(
                        {"open": bar.open, "high": bar.high, "low": bar.low,
                         "close": bar.close, "volume": bar.volume},
                        indicator_name,
                    )
                except Exception:
                    value = None

        # ── 写入缓存 ──────────────────────────────────────
        if self.config.cache_indicators:
            self._indicator_cache[cache_key] = value

        return value

    def get_indicators(
        self,
        bar: Bar,
        indicator_names: List[str],
        include_bar_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        批量获取多个指标（逐次走缓存，避免重复计算）。

        返回 {indicator_name: value} 字典。
        """
        result: Dict[str, Any] = {}
        for name in indicator_names:
            result[name] = self.get_indicator(bar, name, include_bar_data)
        return result

    def clear_indicator_cache(self) -> None:
        """清空指标缓存（典型用途：切换交易日时）。"""
        self._indicator_cache.clear()

    # ═══════════════════════════════════════════════════════════
    # P1-34: FactorCalculator 接入
    # ═══════════════════════════════════════════════════════════

    def _lazy_factor_calculator(self) -> Any:
        """惰性初始化 FactorCalculator 实例。"""
        if self._factor_calculator is None and FactorCalculator is not None:
            self._factor_calculator = FactorCalculator()
        return self._factor_calculator

    def get_factor(
        self,
        bar: Bar,
        factor_name: str,
        all_bars: Optional[List[Bar]] = None,
        force_recompute: bool = False,
    ) -> Any:
        """
        获取指定因子值（P1-34）。

        缓存机制：一个交易日内针对某 symbol + factor 只计算一次，
        后续同日期内读取命中缓存，不重复计算。

        参数
        ----------
        bar : Bar
            当前 K 线。
        factor_name : str
            因子名，如 "momentum", "volatility", "reversal"。
        all_bars : List[Bar], optional
            全部或历史 K 线数据（FactorCalculator 可能需要）。
        force_recompute : bool
            是否强制重算。

        返回
        -------
        Any
            因子计算值（通常为 float）。
        """
        cache_key = (bar.date, bar.symbol, factor_name)

        # ── 缓存命中 ──────────────────────────────────────
        if (
            self.config.cache_factors
            and not force_recompute
            and cache_key in self._factor_cache
        ):
            return self._factor_cache[cache_key]

        # ── 回调 FactorCalculator ──────────────────────────
        calculator = self._lazy_factor_calculator()
        value: Any = None

        if calculator is not None:
            # FactorCalculator 预期的入参模式（根据实际接口调整）：
            #   compute_factor(bar_data_or_df, factor_name) → value
            bar_data = self._bar_to_dict(bar)
            try:
                value = calculator.compute_factor(bar_data, factor_name)
            except Exception:
                try:
                    value = calculator.compute(bar_data, factor_name)
                except Exception:
                    value = None

        # ── 写入缓存 ──────────────────────────────────────
        if self.config.cache_factors:
            self._factor_cache[cache_key] = value

        return value

    def get_factors(
        self,
        bar: Bar,
        factor_names: List[str],
        all_bars: Optional[List[Bar]] = None,
    ) -> Dict[str, Any]:
        """
        批量获取多个因子值。
        """
        result: Dict[str, Any] = {}
        for name in factor_names:
            result[name] = self.get_factor(bar, name, all_bars)
        return result

    def warm_factor_cache(
        self, date: str, symbol: str, factor_names: List[str]
    ) -> None:
        """
        预计算某日期 + 标的的因子值，写入缓存。
        典型用途：在遍历某交易日第一条 Bar 时预计算完整日因子。
        """
        # 构建一个模拟 bar 用于触发计算（仅用于触发缓存填充）
        dummy_bar = Bar(
            date=date,
            symbol=symbol,
            open=0.0,
            high=0.0,
            low=0.0,
            close=0.0,
            volume=0,
        )
        for name in factor_names:
            self.get_factor(dummy_bar, name)

    def clear_factor_cache(self) -> None:
        """清空因子缓存。"""
        self._factor_cache.clear()
        self._factor_dates_done.clear()

    def on_new_trading_day(self, date: str) -> None:
        """
        通知桥接器进入新的交易日。
        按需清空指标/因子缓存（日级粒度）。
        """
        # 因子：一个交易日只计算一次某因子 — 我们保留缓存只增不减
        # 仅在需要时由策略显式清空
        pass

    # ═══════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _bar_to_dict(bar: Bar) -> Dict[str, Any]:
        """将 Bar 转换为字典（便于传入已有组件）。"""
        return {
            "date": bar.date,
            "symbol": bar.symbol,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "vwap": bar.vwap,
        }

    def reset(self) -> None:
        """重置所有缓存和状态（每次回测运行前调用）。"""
        self._signal_cache.clear()
        self._indicator_cache.clear()
        self._factor_cache.clear()
        self._factor_dates_done.clear()
        self._signal_df = None


# ============================================================
# P1-32: SignalStrategy — 信号驱动策略基类
# ============================================================


class SignalStrategy(Strategy):
    """
    信号驱动策略基类，内嵌 SignalBridge。

    子类只需覆盖以下方法之一：
      - on_signal(bar, signal_value) → Optional[List[OrderRequest]]
        (默认实现调用 self.bridge.signal_to_orders)
      - on_bar(context, bar)  (完全自定义逻辑，可访问 self.bridge)

    用法::

        class MyStrategy(SignalStrategy):
            def on_start(self, ctx):
                signals = generate_backtest_signals(...)
                self.bridge.load_signals(signals)

            def on_bar(self, ctx, bar):
                # 读取指标辅助决策
                rsi = self.bridge.get_indicator(bar, "rsi14")
                if rsi and rsi < 30:
                    return self.bridge.signal_to_orders(ctx, bar)
                return None
    """

    def __init__(
        self,
        bridge_config: Optional[SignalBridgeConfig] = None,
    ):
        super().__init__()
        self.bridge = SignalBridge(config=bridge_config)

    def on_start(self, context: Any) -> None:
        """回测开始时重置桥接器状态。"""
        self.bridge.reset()
        super().on_start(context)

    def on_bar(
        self, context: Any, bar: Bar
    ) -> Optional[List[OrderRequest]]:
        """
        默认 on_bar 实现：调用 on_signal 处理信号。

        若子类直接覆盖 on_bar，需手动调用 bridge 的方法。
        """
        signal = self.bridge.get_signal(bar)
        return self.on_signal(context, bar, signal)

    def on_signal(
        self, context: Any, bar: Bar, signal_value: float
    ) -> Optional[List[OrderRequest]]:
        """
        信号回调。默认将正信号转发给 bridge.signal_to_orders。
        子类可覆写实现自定义逻辑（如结合指标过滤）。
        """
        if abs(signal_value) > 0:
            return self.bridge.signal_to_orders(context, bar)
        return None

    def on_end(self, context: Any) -> None:
        """回测结束时调用。"""
        super().on_end(context)


# ============================================================
# 模块级别安全查询
# ============================================================


def is_tech_signal_generator_available() -> bool:
    """检查 tech_signal_generator 是否可导入。"""
    return _TSG_AVAILABLE


def is_indicator_engine_available() -> bool:
    """检查 indicator_engine 是否可导入。"""
    return _IE_AVAILABLE


def is_factor_calculator_available() -> bool:
    """检查 factor_calculator 是否可导入。"""
    return _FC_AVAILABLE
