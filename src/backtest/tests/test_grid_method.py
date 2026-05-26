"""
test_grid_method.py — GridMethod 单元测试 (C17)

覆盖：
1. METHOD_META 验证
2. setup() 参数装配
3. generate_signal(df) 批量模式信号 {-1,0,1}
4. on_bar() 事件驱动模式正确性
5. on_state_save / on_state_restore 序列化一致性
6. 边界条件
7. cleanup() 不抛异常
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.grid.grid_method import GridMethod, GridLevel, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.methods.base import BaseMethod


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
        self.symbol = "TEST"
    def get_config(self, key, default=None):
        return self._config.get(key, default)


def make_df(n=60) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.rand(n) * 1.5
    low = close - np.random.rand(n) * 1.5
    volume = np.random.randint(1000, 10000, n)
    return pd.DataFrame({
        "close": close, "high": high, "low": low, "volume": volume,
    }, index=pd.DatetimeIndex(dates))


class TestGridMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "grid")

    def test_requires_state_true(self):
        """GridMethod requires_state=True"""
        self.assertTrue(METHOD_META["capabilities"]["requires_state"])

    def test_intraday_support_true(self):
        self.assertTrue(METHOD_META["capabilities"]["intraday_support"])


class TestGridMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = GridMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.n_levels, 10)
        self.assertEqual(m.grid_type, "arithmetic")
        self.assertEqual(m.lookback, 20)
        self.assertEqual(m.width_multiplier, 2.0)
        self.assertEqual(m._grid_levels, [])
        self.assertIsNone(m._prev_close)

    def test_custom(self):
        m = GridMethod()
        m.setup(MockContext({
            "n_levels": 8, "grid_type": "geometric",
            "lookback": 15, "width_multiplier": 3.0,
        }))
        self.assertEqual(m.n_levels, 8)
        self.assertEqual(m.grid_type, "geometric")
        self.assertEqual(m.lookback, 15)
        self.assertEqual(m.width_multiplier, 3.0)


class TestGridMethod_GridLevel(unittest.TestCase):
    def test_gridlevel_init(self):
        gl = GridLevel(price=100.0, is_buy=True)
        self.assertEqual(gl.price, 100.0)
        self.assertTrue(gl.is_buy)
        self.assertFalse(gl.triggered)

    def test_gridlevel_to_dict(self):
        gl = GridLevel(price=101.5, is_buy=False)
        gl.triggered = True
        d = gl.to_dict()
        self.assertEqual(d["price"], 101.5)
        self.assertFalse(d["is_buy"])
        self.assertTrue(d["triggered"])

    def test_gridlevel_from_dict(self):
        gl = GridLevel.from_dict({"price": 99.0, "is_buy": True, "triggered": True})
        self.assertEqual(gl.price, 99.0)
        self.assertTrue(gl.is_buy)
        self.assertTrue(gl.triggered)

    def test_reset_trigger(self):
        gl = GridLevel(price=100.0, is_buy=True)
        gl.triggered = True
        gl.reset_trigger()
        self.assertFalse(gl.triggered)


class TestGridMethod_OnBar(unittest.TestCase):
    def setUp(self):
        self.method = GridMethod()
        self.method.setup(MockContext({"n_levels": 6, "lookback": 20}))

    def test_on_bar_sequential(self):
        """逐Bar调用on_bar产生信号"""
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        close = 100 + np.cumsum(np.random.randn(30) * 0.5)
        for i in range(len(dates)):
            row = pd.Series({
                "close": close[i],
                "high": close[i] + 0.5,
                "low": close[i] - 0.5,
                "volume": 5000,
            }, name=dates[i])
            result = self.method.on_bar(row)
            # 不应抛异常
            self.assertIn(type(result), [type(None), dict], f"on_bar 返回类型错误: {type(result)}")

    def test_on_bar_return_type(self):
        """on_bar 返回 None 或 dict"""
        row = pd.Series({"close": 100.0, "high": 101.0, "low": 99.0, "volume": 5000})
        result = self.method.on_bar(row)
        self.assertIn(type(result), [type(None), dict])

    def test_on_bar_missing_close(self):
        """缺少close列返回None"""
        row = pd.Series({"high": 101.0, "low": 99.0})
        result = self.method.on_bar(row)
        self.assertIsNone(result)

    def test_on_bar_cross_detected(self):
        """价格穿越网格线产生信号"""
        m = GridMethod()
        m.setup(MockContext({"n_levels": 4, "lookback": 20}))
        # 前20Bar提供足够的波动以构建网格
        for i in range(20):
            close_val = 100.0 + np.random.randn() * 1.5
            row = pd.Series({
                "close": close_val,
                "high": close_val + np.random.rand() * 2,
                "low": close_val - np.random.rand() * 2,
                "volume": 5000,
            })
            m.on_bar(row)

        # 当prev_close不等于最后一次close时才有机会穿越
        # 显式触发网格重建后，大幅跳升穿越网格
        m._rebuild_grid()
        m._prev_close = 100.0
        row = pd.Series({"close": 110.0, "high": 112.0, "low": 100.0, "volume": 5000})
        result = m.on_bar(row)
        self.assertIsNotNone(result, "价格穿越网格应产生信号")
        if result is not None:
            self.assertIn("action", result)
            self.assertIn("price", result)


class TestGridMethod_GenerateSignal(unittest.TestCase):
    def test_signal_domain(self):
        """批量模式信号值域正确"""
        m = GridMethod()
        m.setup(MockContext({"n_levels": 6, "lookback": 10}))
        df = make_df(30)
        result = m.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_signal_column(self):
        m = GridMethod()
        m.setup(MockContext({}))
        df = make_df(30)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_missing_columns(self):
        m = GridMethod()
        m.setup(MockContext({}))
        with self.assertRaises(ValueError):
            m.generate_signal(pd.DataFrame({"close": [1.0]}))


class TestGridMethod_StateSerialization(unittest.TestCase):
    """on_state_save / on_state_restore"""

    def test_state_save_restore_roundtrip(self):
        m = GridMethod()
        m.setup(MockContext({"n_levels": 6, "lookback": 20}))
        # 运行一些Bar
        for i in range(25):
            row = pd.Series({"close": 100.0 + i * 0.1, "high": 101.0 + i * 0.1,
                            "low": 99.0 + i * 0.1, "volume": 5000})
            m.on_bar(row)

        state = m.on_state_save()
        self.assertIsInstance(state, dict)
        self.assertIn("grid_levels", state)
        self.assertIn("prev_close", state)
        self.assertIn("bar_count", state)
        self.assertIn("method_params", state)

        # 从状态恢复
        m2 = GridMethod()
        m2.on_state_restore(state)
        self.assertEqual(m2.n_levels, m.n_levels)
        self.assertEqual(m2.grid_type, m.grid_type)
        self.assertEqual(m2._bar_count, m._bar_count)
        self.assertEqual(len(m2._grid_levels), len(m._grid_levels))

    def test_state_save_roundtrip_via_dict(self):
        """序列化后重新构造"""
        m = GridMethod()
        m.setup(MockContext({"n_levels": 6, "lookback": 20}))
        row = pd.Series({"close": 100.0, "high": 101.0, "low": 99.0, "volume": 5000})
        m.on_bar(row)

        state = m.on_state_save()
        # 反序列化
        m2 = GridMethod()
        m2.on_state_restore(state)
        self.assertEqual(m2._bar_count, 1)

    def test_empty_state_restore(self):
        """空状态恢复不抛异常"""
        m = GridMethod()
        m.on_state_restore({})
        self.assertIsNone(m._prev_close)


class TestGridMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = GridMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": [], "high": [], "low": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_small_data(self):
        m = GridMethod()
        m.setup(MockContext({"lookback": 20}))
        df = make_df(5)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 5)

    def test_cleanup(self):
        m = GridMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestGridMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(GridMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
