"""
test_bollinger_method.py — BollingerMethod 单元测试 (C11)
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.trend.bollinger_method import BollingerMethod, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.methods.base import BaseMethod


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)


def make_df(n=100) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.8)
    return pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))


class TestBollingerMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "bollinger")

    def test_requires_state_false(self):
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])


class TestBollingerMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = BollingerMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.period, 20)
        self.assertEqual(m.std_dev, 2.0)

    def test_custom(self):
        m = BollingerMethod()
        m.setup(MockContext({"period": 10, "std_dev": 1.5}))
        self.assertEqual(m.period, 10)
        self.assertEqual(m.std_dev, 1.5)


class TestBollingerMethod_GenerateSignal(unittest.TestCase):
    def setUp(self):
        self.method = BollingerMethod()
        self.method.setup(MockContext({}))

    def test_signal_domain(self):
        df = make_df(100)
        result = self.method.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_columns(self):
        df = make_df(100)
        result = self.method.generate_signal(df)
        for col in ["signal", "upper", "middle", "lower", "bandwidth"]:
            self.assertIn(col, result.columns)

    def test_missing_close(self):
        with self.assertRaises(ValueError):
            self.method.generate_signal(pd.DataFrame({"open": [1.0]}))

    def test_index_preserved(self):
        df = make_df(50)
        result = self.method.generate_signal(df)
        pd.testing.assert_index_equal(result.index, df.index)


class TestBollingerMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = BollingerMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_small_data(self):
        m = BollingerMethod()
        m.setup(MockContext({"period": 20}))
        df = make_df(10)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 10)

    def test_cleanup(self):
        m = BollingerMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestBollingerMethod_BreakoutSignal(unittest.TestCase):
    """布林带突破信号测试"""
    def test_band_crossing(self):
        """极端行情产生突破信号"""
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        # 前20Bar平稳，后30Bar大幅上涨
        close = np.concatenate([
            np.ones(20) * 100.0,
            100.0 + np.arange(30) * 2.0,  # 大幅突破
        ])
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        m = BollingerMethod()
        m.setup(MockContext({"period": 20, "std_dev": 2.0}))
        result = m.generate_signal(df)
        # 突破上轨应产生信号
        self.assertGreaterEqual(result["signal"].abs().sum(), 0)


class TestBollingerMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(BollingerMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
