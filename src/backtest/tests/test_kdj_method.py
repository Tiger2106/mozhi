"""
test_kdj_method.py — KDJMethod 单元测试 (C15)
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.momentum.kdj_method import KDJMethod, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.methods.base import BaseMethod


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)


class TestKDJMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "kdj")

    def test_requires_state_false(self):
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])


class TestKDJMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = KDJMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.n, 9)
        self.assertEqual(m.m1, 3)
        self.assertEqual(m.m2, 3)
        self.assertEqual(m.oversold, 20.0)
        self.assertEqual(m.overbought, 80.0)

    def test_custom(self):
        m = KDJMethod()
        m.setup(MockContext({"n": 14, "m1": 5, "m2": 5, "oversold": 15.0, "overbought": 85.0}))
        self.assertEqual(m.n, 14)
        self.assertEqual(m.m1, 5)
        self.assertEqual(m.m2, 5)
        self.assertEqual(m.oversold, 15.0)
        self.assertEqual(m.overbought, 85.0)


class TestKDJMethod_GenerateSignal(unittest.TestCase):
    def setUp(self):
        self.method = KDJMethod()
        self.method.setup(MockContext({}))

    def test_signal_domain(self):
        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        high = close + 2
        low = close - 2
        df = pd.DataFrame({"close": close, "high": high, "low": low}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_columns(self):
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame({
            "close": np.ones(50)*100, "high": np.ones(50)*102, "low": np.ones(50)*98,
        }, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        for col in ["signal", "K", "D", "J", "strength"]:
            self.assertIn(col, result.columns)

    def test_missing_columns(self):
        with self.assertRaises(ValueError):
            self.method.generate_signal(pd.DataFrame({"close": [1.0]}))

    def test_oversold_signal(self):
        """持续下跌产生超卖信号"""
        dates = pd.date_range("2025-01-01", periods=60, freq="D")
        close = 100 - np.arange(60) * 1.5
        high = close + 1
        low = close - 1
        df = pd.DataFrame({"close": close, "high": high, "low": low}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertIn(1, result["signal"].values)

    def test_overbought_signal(self):
        """持续上涨产生超买信号"""
        dates = pd.date_range("2025-01-01", periods=60, freq="D")
        close = 100 + np.arange(60) * 1.5
        high = close + 1
        low = close - 1
        df = pd.DataFrame({"close": close, "high": high, "low": low}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertIn(-1, result["signal"].values)


class TestKDJMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = KDJMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": [], "high": [], "low": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_cleanup(self):
        m = KDJMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestKDJMethod_ComputeKDJ(unittest.TestCase):
    def test_kdj_values(self):
        close = pd.Series([100.0, 101.0, 102.0, 101.5, 100.5, 99.0, 100.0, 101.0, 102.0])
        high = pd.Series([101.0, 102.0, 103.0, 102.5, 101.5, 100.0, 101.0, 102.0, 103.0])
        low = pd.Series([99.0, 100.0, 101.0, 100.5, 99.5, 98.0, 99.0, 100.0, 101.0])
        K, D, J = KDJMethod._compute_kdj(close, high, low, 9, 3, 3)
        valid = K.dropna()
        self.assertGreater(len(valid), 0)
        # K/D/J 应在合理范围内
        self.assertTrue((K.dropna() >= 0).all())
        self.assertTrue((K.dropna() <= 100).all())


class TestKDJMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(KDJMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
