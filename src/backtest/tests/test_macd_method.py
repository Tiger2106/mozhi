"""
test_macd_method.py — MACDMethod 单元测试 (C10)
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.trend.macd_method import MACDMethod, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.methods.base import BaseMethod


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)


def make_df(n=100) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))


class TestMACDMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "macd")

    def test_requires_state_false(self):
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])


class TestMACDMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = MACDMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.fast_period, 12)
        self.assertEqual(m.slow_period, 26)
        self.assertEqual(m.signal_period, 9)

    def test_custom(self):
        m = MACDMethod()
        m.setup(MockContext({"fast_period": 8, "slow_period": 20, "signal_period": 5}))
        self.assertEqual(m.fast_period, 8)
        self.assertEqual(m.slow_period, 20)
        self.assertEqual(m.signal_period, 5)


class TestMACDMethod_GenerateSignal(unittest.TestCase):
    def setUp(self):
        self.method = MACDMethod()
        self.method.setup(MockContext({}))

    def test_signal_domain(self):
        df = make_df(100)
        result = self.method.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_columns(self):
        df = make_df(100)
        result = self.method.generate_signal(df)
        for col in ["signal", "dif", "dea", "macd_hist"]:
            self.assertIn(col, result.columns)

    def test_missing_close(self):
        with self.assertRaises(ValueError):
            self.method.generate_signal(pd.DataFrame({"open": [1.0]}))

    def test_minimal_data(self):
        df = make_df(5)  # 小于 slow_period(26)
        result = self.method.generate_signal(df)
        self.assertEqual(len(result), 5)

    def test_index_preserved(self):
        df = make_df(60)
        result = self.method.generate_signal(df)
        pd.testing.assert_index_equal(result.index, df.index)


class TestMACDMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = MACDMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_cleanup(self):
        m = MACDMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestMACDMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(MACDMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
