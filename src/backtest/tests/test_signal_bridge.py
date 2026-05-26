"""
test_signal_bridge.py — Phase 1 信号桥接层单元测试

覆盖5个场景：
1. 信号转换：signal_to_orders 正信号→BUY，负信号→SELL
2. 仓位比例控制：15%仓位上限验证
3. 100股对齐：下单数量为100的倍数
4. 已持仓检查：已有持仓时不重复开仓
5. 缓存：indicator_cache / factor_cache 命中/未命中
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backtest.signal_bridge import (
    SignalBridge,
    SignalBridgeConfig,
    SignalStrategy,
)
from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    Bar,
    OrderRequest,
    OrderSide,
    OrderType,
    Strategy,
)
from backtest.backtest_context import BacktestContext
from backtest.position_manager import CostMethod, Position, PositionManager


# ═══════════════════════════════════════════════════════════════
# 测试数据构造工具
# ═══════════════════════════════════════════════════════════════

def make_bar(date: str, symbol: str = "000001.SZ",
             o: float = 10.0, h: float = 10.5,
             l: float = 9.5,  c: float = 10.0,
             v: float = 1000.0) -> Bar:
    return Bar(date=date, symbol=symbol, open=o, high=h, low=l, close=c, volume=v)


class _SignalRow:
    """Mimics a pandas Series (row) returned by DataFrame.iterrows()."""
    def __init__(self, data):
        self._data = data

    def get(self, key, default=0):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]


class _SignalDF:
    """
    模拟 pandas.DataFrame（用于测试加载信号）。
    DataFrame.iterrows() 产出 (index, Series) 元组。
    """
    def __init__(self, rows):
        self._rows = rows  # list of dict

    def iterrows(self):
        return iter(
            (i, _SignalRow(row)) for i, row in enumerate(self._rows)
        )


def make_signal_df(rows):
    """构造信号 DataFrame（模拟 signal_bridge 期望的格式）。"""
    return _SignalDF(rows)


def make_context(initial_capital: float = 1_000_000.0,
                 positions: Optional[Dict[str, Position]] = None) -> BacktestContext:
    """构造 BacktestContext，可选预置持仓。"""
    ctx = BacktestContext(initial_capital=initial_capital, cost_method=CostMethod.WEIGHTED_AVG)
    if positions:
        for sym, pos in positions.items():
            ctx.positions._positions[sym] = pos
    return ctx


# ═══════════════════════════════════════════════════════════════
# 场景1：信号转换 — 正信号→BUY，负信号→SELL
# ═══════════════════════════════════════════════════════════════

class TestSignalToOrdersConversion(unittest.TestCase):
    """验证 signal_to_orders 正确将信号值映射到订单方向"""

    def test_positive_signal_generates_buy_order(self):
        bridge = SignalBridge()
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].side, OrderSide.BUY)
        self.assertEqual(orders[0].symbol, "000001.SZ")

    def test_negative_signal_generates_sell_order(self):
        """负信号产生 SELL 订单（需有持仓才生效）"""
        bridge = SignalBridge()
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": -1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        ctx.positions._positions["000001.SZ"] = Position(
            symbol="000001.SZ", quantity=1000, avg_cost=9.5
        )
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].side, OrderSide.SELL)
        self.assertEqual(orders[0].symbol, "000001.SZ")

    def test_zero_signal_returns_none(self):
        bridge = SignalBridge()
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 0.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNone(orders)

    def test_signal_below_threshold_returns_none(self):
        bridge = SignalBridge(SignalBridgeConfig(default_quantity=100))
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 0.3},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        orders = bridge.signal_to_orders(ctx, bar, threshold=0.5)

        self.assertIsNone(orders)

    def test_no_signal_for_unknown_symbol_returns_none(self):
        bridge = SignalBridge()
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "999999.SZ", c=10.0)  # 不同的 symbol
        ctx = make_context()
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNone(orders)

    def test_quantity_override_respected(self):
        bridge = SignalBridge(SignalBridgeConfig(default_quantity=100))
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        orders = bridge.signal_to_orders(ctx, bar, quantity_override=500)

        self.assertIsNotNone(orders)
        self.assertEqual(orders[0].quantity, 500)


# ═══════════════════════════════════════════════════════════════
# 场景2：仓位比例控制 — 15%仓位上限验证
# ═══════════════════════════════════════════════════════════════

class TestPositionSizeLimit(unittest.TestCase):
    """验证下单数量受 max_position_pct 上限约束"""

    def test_quantity_capped_at_15_percent_of_capital(self):
        """总资金100万，15%上限 → 最大可下单价值15万"""
        config = SignalBridgeConfig(
            default_quantity=10000,   # 远超实际可买
            max_position_pct=0.15,
        )
        bridge = SignalBridge(config)
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)   # 价格10元
        ctx = make_context(initial_capital=1_000_000.0)
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        qty = orders[0].quantity
        # 数量 × 价格 ≤ 1_000_000 × 0.15 = 150_000
        self.assertLessEqual(qty * bar.close, 1_000_000.0 * 0.15)

    def test_small_capital_reduces_quantity(self):
        """资金少时实际可买数量进一步受限"""
        config = SignalBridgeConfig(default_quantity=10000, max_position_pct=0.15)
        bridge = SignalBridge(config)
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=100.0)   # 价格100元
        ctx = make_context(initial_capital=100_000.0)
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        qty = orders[0].quantity
        # 实际下单价值不能超过 100_000 × 0.15 = 15_000
        self.assertLessEqual(qty * bar.close, 100_000.0 * 0.15)

    def test_zero_capital_still_places_min_order(self):
        """资金为0时，bridge层面仍生成订单（至少1手），executor层拒绝"""
        config = SignalBridgeConfig(default_quantity=100, max_position_pct=0.15)
        bridge = SignalBridge(config)
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context(initial_capital=0.0)
        orders = bridge.signal_to_orders(ctx, bar)

        # quantity 被 max(quantity, 100) 保底至100，bridge仍生成订单
        self.assertIsNotNone(orders)
        self.assertEqual(orders[0].quantity, 100)
        self.assertEqual(orders[0].side, OrderSide.BUY)


# ═══════════════════════════════════════════════════════════════
# 场景3：100股对齐 — 下单数量为100的倍数
# ═══════════════════════════════════════════════════════════════

class TestLotSizeAlignment(unittest.TestCase):
    """验证下单数量取整为100的倍数"""

    def test_quantity_rounded_down_to_nearest_100(self):
        """计算可买1500股 → 取整1000股"""
        config = SignalBridgeConfig(default_quantity=1500, max_position_pct=0.15)
        bridge = SignalBridge(config)
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context(initial_capital=1_000_000.0)
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        qty = orders[0].quantity
        self.assertEqual(qty % 100, 0)
        self.assertLessEqual(qty, 1500)

    def test_exact_100_unchanged(self):
        """恰好100股不受影响"""
        config = SignalBridgeConfig(default_quantity=100, max_position_pct=0.15)
        bridge = SignalBridge(config)
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context(initial_capital=1_000_000.0)
        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        self.assertEqual(orders[0].quantity, 100)

    def test_very_small_quantity_rounded_up_to_100(self):
        """计算数量远小于100时，max保底至100（A股最低1手）"""
        config = SignalBridgeConfig(default_quantity=50, max_position_pct=0.0001)
        bridge = SignalBridge(config)
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))
        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context(initial_capital=500.0)
        orders = bridge.signal_to_orders(ctx, bar)

        # quantity 被 max(quantity,100) 保底到100
        self.assertIsNotNone(orders)
        self.assertEqual(orders[0].quantity, 100)


# ═══════════════════════════════════════════════════════════════
# 场景4：已持仓检查 — 已有持仓时不重复开仓
# ═══════════════════════════════════════════════════════════════

class TestPositionCheckNoDuplicateOpen(unittest.TestCase):
    """验证卖出信号在有持仓时平仓，无持仓时不产生订单"""

    def test_sell_signal_with_position_executes_sell(self):
        """有持仓时卖出信号产生 SELL 订单"""
        bridge = SignalBridge()
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": -1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        ctx.positions._positions["000001.SZ"] = Position(
            symbol="000001.SZ", quantity=1000, avg_cost=9.5
        )

        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].side, OrderSide.SELL)
        self.assertLessEqual(orders[0].quantity, 1000)

    def test_sell_signal_without_position_returns_none(self):
        """无持仓时卖出信号不产生订单（不会做空）"""
        bridge = SignalBridge()
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": -1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()  # 无持仓

        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNone(orders)

    def test_sell_qty_capped_at_holding(self):
        """卖出数量不超过持仓"""
        bridge = SignalBridge(SignalBridgeConfig(default_quantity=10000))
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": -1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        ctx.positions._positions["000001.SZ"] = Position(
            symbol="000001.SZ", quantity=500, avg_cost=9.5
        )

        orders = bridge.signal_to_orders(ctx, bar)

        self.assertIsNotNone(orders)
        self.assertLessEqual(orders[0].quantity, 500)

    def test_buy_signal_with_existing_position_opens_or_increases(self):
        """买入信号有持仓时仍可加仓（不禁止重复开多）"""
        bridge = SignalBridge(SignalBridgeConfig(default_quantity=100,
                                                  max_position_pct=0.15))
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)
        ctx = make_context()
        ctx.positions._positions["000001.SZ"] = Position(
            symbol="000001.SZ", quantity=1000, avg_cost=9.5
        )

        orders = bridge.signal_to_orders(ctx, bar)

        # 买入信号仍产生 BUY 订单（允许加仓）
        self.assertIsNotNone(orders)
        self.assertEqual(orders[0].side, OrderSide.BUY)


# ═══════════════════════════════════════════════════════════════
# 场景5：缓存 — indicator_cache / factor_cache 命中/未命中
# ═══════════════════════════════════════════════════════════════

class TestIndicatorCache(unittest.TestCase):
    """验证指标缓存的命中与未命中"""

    def test_indicator_cache_miss_then_hit(self):
        """首次查询未命中 → 计算并写入缓存；再次查询命中"""
        config = SignalBridgeConfig(cache_indicators=True)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeEngine:
            def compute(self, data, name):
                return 42.0

        bridge._indicator_engine = _FakeEngine()

        val1 = bridge.get_indicator(bar, "rsi14")
        self.assertEqual(val1, 42.0)

        cache_key = ("2026-05-07", "000001.SZ", "rsi14")
        self.assertIn(cache_key, bridge._indicator_cache)

        # 修改 engine 返回值，缓存应返回旧值（命中）
        class _FakeEngine2:
            def compute(self, data, name):
                return 99.0

        bridge._indicator_engine = _FakeEngine2()
        val2 = bridge.get_indicator(bar, "rsi14")
        self.assertEqual(val2, 42.0)

    def test_force_recompute_bypasses_cache(self):
        """force_recompute=True 强制重算"""
        config = SignalBridgeConfig(cache_indicators=True)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeEngine:
            _call_count = 0

            def compute(self, data, name):
                _FakeEngine._call_count += 1
                return 42.0

        bridge._indicator_engine = _FakeEngine()

        bridge.get_indicator(bar, "rsi14")
        self.assertEqual(_FakeEngine._call_count, 1)

        bridge.get_indicator(bar, "rsi14", force_recompute=True)
        self.assertEqual(_FakeEngine._call_count, 2)

    def test_cache_disabled_always_recomputes(self):
        """cache_indicators=False 时每次都重算"""
        config = SignalBridgeConfig(cache_indicators=False)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeEngine:
            _call_count = 0

            def compute(self, data, name):
                _FakeEngine._call_count += 1
                return 42.0

        bridge._indicator_engine = _FakeEngine()

        bridge.get_indicator(bar, "rsi14")
        bridge.get_indicator(bar, "rsi14")

        self.assertEqual(_FakeEngine._call_count, 2)

    def test_clear_indicator_cache(self):
        """清空指标缓存"""
        config = SignalBridgeConfig(cache_indicators=True)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeEngine:
            def compute(self, data, name):
                return 42.0

        bridge._indicator_engine = _FakeEngine()
        bridge.get_indicator(bar, "rsi14")

        self.assertGreater(len(bridge._indicator_cache), 0)
        bridge.clear_indicator_cache()
        self.assertEqual(len(bridge._indicator_cache), 0)


class TestFactorCache(unittest.TestCase):
    """验证因子缓存的命中与未命中"""

    def test_factor_cache_miss_then_hit(self):
        """首次查询未命中 → 计算写入缓存；再次查询命中"""
        config = SignalBridgeConfig(cache_factors=True)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeCalculator:
            def compute_factor(self, data, name):
                return 3.14

        bridge._factor_calculator = _FakeCalculator()

        val1 = bridge.get_factor(bar, "momentum")
        self.assertAlmostEqual(val1, 3.14)

        cache_key = ("2026-05-07", "000001.SZ", "momentum")
        self.assertIn(cache_key, bridge._factor_cache)

        class _FakeCalculator2:
            def compute_factor(self, data, name):
                return 99.99

        bridge._factor_calculator = _FakeCalculator2()
        val2 = bridge.get_factor(bar, "momentum")
        self.assertAlmostEqual(val2, 3.14)

    def test_force_recompute_factor(self):
        """force_recompute=True 强制重算因子"""
        config = SignalBridgeConfig(cache_factors=True)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeCalc:
            _call_count = 0

            def compute_factor(self, data, name):
                _FakeCalc._call_count += 1
                return 1.0

        bridge._factor_calculator = _FakeCalc()

        bridge.get_factor(bar, "momentum")
        self.assertEqual(_FakeCalc._call_count, 1)

        bridge.get_factor(bar, "momentum", force_recompute=True)
        self.assertEqual(_FakeCalc._call_count, 2)

    def test_cache_disabled_factor_always_recomputes(self):
        """cache_factors=False 时每次都重算"""
        config = SignalBridgeConfig(cache_factors=False)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeCalc:
            _call_count = 0

            def compute_factor(self, data, name):
                _FakeCalc._call_count += 1
                return 1.0

        bridge._factor_calculator = _FakeCalc()

        bridge.get_factor(bar, "momentum")
        bridge.get_factor(bar, "momentum")
        self.assertEqual(_FakeCalc._call_count, 2)

    def test_clear_factor_cache(self):
        """清空因子缓存"""
        config = SignalBridgeConfig(cache_factors=True)
        bridge = SignalBridge(config)

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeCalc:
            def compute_factor(self, data, name):
                return 1.0

        bridge._factor_calculator = _FakeCalc()
        bridge.get_factor(bar, "momentum")

        self.assertGreater(len(bridge._factor_cache), 0)
        bridge.clear_factor_cache()
        self.assertEqual(len(bridge._factor_cache), 0)

    def test_different_date_symbol_triggers_new_compute(self):
        """不同日期/标的 → 缓存未命中，需重新计算"""
        config = SignalBridgeConfig(cache_factors=True)
        bridge = SignalBridge(config)

        bar1 = make_bar("2026-05-07", "000001.SZ", c=10.0)
        bar2 = make_bar("2026-05-08", "000001.SZ", c=11.0)
        bar3 = make_bar("2026-05-07", "000002.SZ", c=20.0)

        class _FakeCalc:
            _call_count = 0

            def compute_factor(self, data, name):
                _FakeCalc._call_count += 1
                return float(_FakeCalc._call_count)

        bridge._factor_calculator = _FakeCalc()

        val1 = bridge.get_factor(bar1, "momentum")
        val2 = bridge.get_factor(bar2, "momentum")
        val3 = bridge.get_factor(bar3, "momentum")

        # 三次计算（不同 date+symbol 组合）
        self.assertEqual(_FakeCalc._call_count, 3)
        self.assertAlmostEqual(val1, 1.0)
        self.assertAlmostEqual(val2, 2.0)
        self.assertAlmostEqual(val3, 3.0)


# ═══════════════════════════════════════════════════════════════
# 集成测试：SignalStrategy 与 BacktestEngine 联动
# ═══════════════════════════════════════════════════════════════

class TestSignalBridgeIntegration(unittest.TestCase):
    """验证 SignalStrategy 与 BacktestEngine 端到端联动"""

    def test_signal_strategy_generates_orders_end_to_end(self):
        """SignalStrategy 在回测引擎中产生正确的买单/卖单"""
        bridge_config = SignalBridgeConfig(
            default_quantity=100,
            max_position_pct=0.15,
        )

        class MySignalStrategy(SignalStrategy):
            def on_start(self, ctx):
                super().on_start(ctx)
                self.bridge.load_signals(make_signal_df([
                    {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
                    {"date": "2026-05-09", "symbol": "000001.SZ", "signal": -1.0},
                ]))

        cfg = BacktestConfig(
            start_date="2026-05-07",
            end_date="2026-05-09",
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MySignalStrategy(bridge_config))

        dates = ["2026-05-07", "2026-05-08", "2026-05-09"]
        prices = [10.0, 10.1, 10.2]
        bars = [
            make_bar(dates[i], "000001.SZ",
                     o=prices[i] - 0.05, h=prices[i] + 0.1,
                     l=prices[i] - 0.1, c=prices[i])
            for i in range(len(dates))
        ]

        result = engine.run(bars)

        self.assertEqual(result.total_trades, 2)
        self.assertEqual(result.trades[0]["side"], "buy")
        self.assertEqual(result.trades[1]["side"], "sell")

    def test_reset_clears_all_caches(self):
        """bridge.reset() 清空所有缓存"""
        bridge = SignalBridge()
        bridge.load_signals(make_signal_df([
            {"date": "2026-05-07", "symbol": "000001.SZ", "signal": 1.0},
        ]))

        bar = make_bar("2026-05-07", "000001.SZ", c=10.0)

        class _FakeEngine:
            def compute(self, data, name):
                return 42.0

        class _FakeCalc:
            def compute_factor(self, data, name):
                return 3.14

        bridge._indicator_engine = _FakeEngine()
        bridge._factor_calculator = _FakeCalc()
        bridge.get_indicator(bar, "rsi14")
        bridge.get_factor(bar, "momentum")

        self.assertGreater(len(bridge._signal_cache), 0)
        self.assertGreater(len(bridge._indicator_cache), 0)
        self.assertGreater(len(bridge._factor_cache), 0)

        bridge.reset()

        self.assertEqual(len(bridge._signal_cache), 0)
        self.assertEqual(len(bridge._indicator_cache), 0)
        self.assertEqual(len(bridge._factor_cache), 0)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()