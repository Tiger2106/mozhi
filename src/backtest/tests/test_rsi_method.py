"""
test_rsi_method.py — RSIMethod 单元测试 (C14)
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.momentum.rsi_method import RSIMethod, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.methods.base import BaseMethod


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)


class TestRSIMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "rsi")

    def test_requires_state_false(self):
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])

    def test_default_params(self):
        self.assertEqual(METHOD_META["default_params"]["period"], 14)
        self.assertEqual(METHOD_META["default_params"]["oversold"], 30.0)
        self.assertEqual(METHOD_META["default_params"]["overbought"], 70.0)


class TestRSIMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = RSIMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.period, 14)
        self.assertEqual(m.oversold, 30.0)
        self.assertEqual(m.overbought, 70.0)

    def test_custom(self):
        m = RSIMethod()
        m.setup(MockContext({"period": 7, "oversold": 25.0, "overbought": 75.0}))
        self.assertEqual(m.period, 7)
        self.assertEqual(m.oversold, 25.0)
        self.assertEqual(m.overbought, 75.0)


class TestRSIMethod_GenerateSignal(unittest.TestCase):
    def setUp(self):
        self.method = RSIMethod()
        self.method.setup(MockContext({}))

    def test_signal_domain(self):
        dates = pd.date_range("2025-01-01", periods=100, freq="D")
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_columns(self):
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame({"close": np.ones(50) * 100}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        for col in ["signal", "rsi", "strength"]:
            self.assertIn(col, result.columns)

    def test_missing_close(self):
        with self.assertRaises(ValueError):
            self.method.generate_signal(pd.DataFrame({}))

    def test_oversold_signal(self):
        """连续下跌产生超卖信号"""
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        close = 100 - np.arange(50) * 2.0  # 持续下跌
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertIn(1, result["signal"].values)  # 应有BUY

    def test_overbought_signal(self):
        """连续上涨产生超买信号"""
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        close = 100 + np.arange(50) * 2.0  # 持续上涨
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertIn(-1, result["signal"].values)  # 应有SELL


class TestRSIMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = RSIMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_small_data(self):
        m = RSIMethod()
        m.setup(MockContext({"period": 14}))
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = pd.DataFrame({"close": [100]*5}, index=pd.DatetimeIndex(dates))
        result = m.generate_signal(df)
        self.assertEqual(len(result), 5)

    def test_cleanup(self):
        m = RSIMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestRSIMethod_ComputeRSI(unittest.TestCase):
    def test_rsi_compute(self):
        """RSI 静态方法计算正确"""
        close = pd.Series([100.0, 101.0, 102.0, 101.5, 100.5, 99.0, 100.0])
        rsi = RSIMethod._compute_rsi(close, 5)
        self.assertIsNotNone(rsi)
        # RSI 值应在 0-100 之间
        valid = rsi.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 100).all())


class TestRSIMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(RSIMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
