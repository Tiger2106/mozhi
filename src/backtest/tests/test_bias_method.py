"""
test_bias_method.py — BiasMethod 单元测试 (C16)
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.momentum.bias_method import BiasMethod, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.methods.base import BaseMethod


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)


class TestBiasMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "bias")

    def test_requires_state_false(self):
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])


class TestBiasMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = BiasMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.ma_period, 20)
        self.assertEqual(m.bias_buy, -0.05)
        self.assertEqual(m.bias_sell, 0.05)

    def test_custom(self):
        m = BiasMethod()
        m.setup(MockContext({"ma_period": 10, "bias_buy": -0.03, "bias_sell": 0.03}))
        self.assertEqual(m.ma_period, 10)
        self.assertEqual(m.bias_buy, -0.03)
        self.assertEqual(m.bias_sell, 0.03)


class TestBiasMethod_GenerateSignal(unittest.TestCase):
    def setUp(self):
        self.method = BiasMethod()
        self.method.setup(MockContext({}))

    def test_signal_domain(self):
        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_columns(self):
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame({"close": np.ones(50)*100}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        for col in ["signal", "bias", "ma", "strength"]:
            self.assertIn(col, result.columns)

    def test_missing_close(self):
        with self.assertRaises(ValueError):
            self.method.generate_signal(pd.DataFrame({}))

    def test_index_preserved(self):
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame({"close": np.ones(50)*100}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        pd.testing.assert_index_equal(result.index, df.index)


class TestBiasMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = BiasMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_cleanup(self):
        m = BiasMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")

    def test_sell_signal_on_high_bias(self):
        """正乖离大产生SELL信号"""
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        close = np.concatenate([np.ones(20)*100, 100 + np.arange(10)*5])  # 后10日暴涨
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        m = BiasMethod()
        m.setup(MockContext({"ma_period": 20, "bias_buy": -0.05, "bias_sell": 0.03}))
        result = m.generate_signal(df)
        self.assertIn(-1, result["signal"].values)

    def test_buy_signal_on_low_bias(self):
        """负乖离大产生BUY信号"""
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        close = np.concatenate([np.ones(20)*100, 100 - np.arange(10)*5])  # 后10日暴跌
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        m = BiasMethod()
        m.setup(MockContext({"ma_period": 20, "bias_buy": -0.03, "bias_sell": 0.05}))
        result = m.generate_signal(df)
        self.assertIn(1, result["signal"].values)


class TestBiasMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(BiasMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
