"""
test_context.py — StrategyContext / RuntimeState 单元测试

覆盖场景：
1. frozen不可修改
2. get_config双层查找（先config后global_config）
3. get_logger懒加载
4. RuntimeState属性读写
5. initial_cash默认值
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.context import StrategyContext, RuntimeState


class TestStrategyContext_Frozen(unittest.TestCase):
    """场景1: frozen不可修改"""

    def test_cannot_set_attribute(self):
        """尝试修改frozen实例的字段应抛FrozenInstanceError/DataclassFrozenError"""
        ctx = StrategyContext(symbol="000001.SH", method_name="test")
        with self.assertRaises(Exception):
            ctx.symbol = "000002.SH"

    def test_can_read_attribute(self):
        """读取字段正常"""
        ctx = StrategyContext(symbol="601857.SH")
        self.assertEqual(ctx.symbol, "601857.SH")

    def test_default_values(self):
        """默认值验证"""
        ctx = StrategyContext()
        self.assertEqual(ctx.symbol, "")
        self.assertEqual(ctx.tick_size, 0.01)
        self.assertEqual(ctx.lot_size, 100)
        self.assertEqual(ctx.initial_cash, 1_000_000.0)
        self.assertEqual(ctx.benchmark, "000300.SH")
        self.assertEqual(ctx.data_frequency, "daily")
        self.assertIsNone(ctx.date_range)
        self.assertFalse(ctx.verbose)
        self.assertFalse(ctx.debug_mode)
        self.assertEqual(ctx.config, {})
        self.assertEqual(ctx.global_config, {})

    def test_cannot_append_to_config(self):
        """不能直接替换frozen字段"""
        ctx = StrategyContext()
        with self.assertRaises(Exception):
            ctx.config = {"key": "val"}


class TestStrategyContext_GetConfig(unittest.TestCase):
    """场景2: get_config双层查找"""

    def test_config_first(self):
        """config中的值优先返回"""
        ctx = StrategyContext(
            config={"fast": 12, "slow": 26},
            global_config={"fast": 999, "slow": 999, "extra": 1},
        )
        self.assertEqual(ctx.get_config("fast"), 12)
        self.assertEqual(ctx.get_config("slow"), 26)

    def test_global_config_fallback(self):
        """global_config作为后备"""
        ctx = StrategyContext(
            config={"fast": 12},
            global_config={"slow": 26, "extra": 1},
        )
        self.assertEqual(ctx.get_config("slow"), 26)

    def test_config_empty_global_present(self):
        """config为空字典时使用global_config"""
        ctx = StrategyContext(
            config={},
            global_config={"fast": 12},
        )
        self.assertEqual(ctx.get_config("fast"), 12)

    def test_default_returned(self):
        """都找不到时返回default"""
        ctx = StrategyContext()
        self.assertIsNone(ctx.get_config("nonexistent"))
        self.assertEqual(ctx.get_config("nonexistent", 42), 42)

    def test_config_nonexistent_key(self):
        """config中有但global_config中没有"""
        ctx = StrategyContext(
            config={"local_only": "val"},
            global_config={"shared": "val"},
        )
        self.assertEqual(ctx.get_config("local_only"), "val")
        self.assertEqual(ctx.get_config("shared"), "val")
        self.assertIsNone(ctx.get_config("missing"))


class TestStrategyContext_GetLogger(unittest.TestCase):
    """场景3: get_logger懒加载"""

    def test_get_logger_returns_logger(self):
        """首次调用返回logger实例"""
        import logging
        ctx = StrategyContext(method_name="test_method")
        logger = ctx.get_logger()
        self.assertIsInstance(logger, logging.Logger)
        self.assertIn("test_method", logger.name)

    def test_logger_cached(self):
        """多次调用返回同一实例"""
        ctx = StrategyContext(method_name="cache_test")
        logger1 = ctx.get_logger()
        logger2 = ctx.get_logger()
        self.assertIs(logger1, logger2)

    def test_logger_unknown_method(self):
        """method_name为空时仍能获取logger"""
        import logging
        ctx = StrategyContext()
        logger = ctx.get_logger()
        self.assertIsInstance(logger, logging.Logger)
        self.assertIn("unknown", logger.name)


class TestRuntimeState(unittest.TestCase):
    """场景4: RuntimeState属性读写"""

    def test_mutable_cash(self):
        """current_cash可修改"""
        state = RuntimeState()
        state.current_cash = 500_000.0
        self.assertEqual(state.current_cash, 500_000.0)

    def test_mutable_positions(self):
        """positions可修改"""
        state = RuntimeState()
        state.positions = {"601857.SH": 1000}
        self.assertEqual(state.positions, {"601857.SH": 1000})

    def test_mutable_logger(self):
        """logger可修改"""
        import logging
        state = RuntimeState()
        logger = logging.getLogger("test")
        state.logger = logger
        self.assertIs(state.logger, logger)

    def test_default_all_none(self):
        """所有字段默认None"""
        state = RuntimeState()
        self.assertIsNone(state.current_cash)
        self.assertIsNone(state.positions)
        self.assertIsNone(state.logger)

    def test_independent_instances(self):
        """不同实例互不影响"""
        s1 = RuntimeState()
        s2 = RuntimeState()
        s1.current_cash = 100.0
        self.assertIsNone(s2.current_cash)


class TestInitialCashDefault(unittest.TestCase):
    """场景5: initial_cash默认值"""

    def test_default_cash(self):
        """默认initial_cash为1000000"""
        ctx = StrategyContext()
        self.assertEqual(ctx.initial_cash, 1_000_000.0)

    def test_custom_cash(self):
        """可自定义initial_cash"""
        ctx = StrategyContext(initial_cash=50000.0)
        self.assertEqual(ctx.initial_cash, 50000.0)

    def test_cash_type_float(self):
        """initial_cash应为float类型"""
        ctx = StrategyContext(initial_cash=100_000)
        self.assertIsInstance(ctx.initial_cash, (int, float))


if __name__ == "__main__":
    unittest.main()
