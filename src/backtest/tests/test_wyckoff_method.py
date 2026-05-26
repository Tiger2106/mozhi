"""
test_wyckoff_method.py — WyckoffMethod 单元测试 (C13)
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.trend.wyckoff_method import WyckoffMethod, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.methods.base import BaseMethod


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)


def make_df(n=60) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.rand(n) * 2
    low = close - np.random.rand(n) * 2
    volume = np.random.randint(1000, 10000, n)
    return pd.DataFrame({
        "close": close, "high": high, "low": low, "volume": volume,
    }, index=pd.DatetimeIndex(dates))


class TestWyckoffMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "wyckoff")

    def test_requires_state_false(self):
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])


class TestWyckoffMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = WyckoffMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.lookback, 20)
        self.assertEqual(m.volume_surge_ratio, 1.5)
        self.assertEqual(m.price_change_threshold, 0.02)

    def test_custom(self):
        m = WyckoffMethod()
        m.setup(MockContext({"lookback": 15, "volume_surge_ratio": 2.0, "price_change_threshold": 0.03}))
        self.assertEqual(m.lookback, 15)
        self.assertEqual(m.volume_surge_ratio, 2.0)
        self.assertEqual(m.price_change_threshold, 0.03)


class TestWyckoffMethod_GenerateSignal(unittest.TestCase):
    def setUp(self):
        self.method = WyckoffMethod()
        self.method.setup(MockContext({}))

    def test_signal_domain(self):
        df = make_df(60)
        result = self.method.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_columns(self):
        df = make_df(60)
        result = self.method.generate_signal(df)
        for col in ["signal", "accumulation_score", "distribution_score", "volume_ma_ratio", "wyckoff_phase"]:
            self.assertIn(col, result.columns)

    def test_missing_columns(self):
        with self.assertRaises(ValueError):
            self.method.generate_signal(pd.DataFrame({"close": [1.0]}))

    def test_index_preserved(self):
        df = make_df(50)
        result = self.method.generate_signal(df)
        pd.testing.assert_index_equal(result.index, df.index)


class TestWyckoffMethod_Accumulation(unittest.TestCase):
    """吸筹场景测试"""
    def test_accumulation_phase(self):
        """下跌缩量+上涨放量应产生吸筹信号"""
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        # 盘整后上涨：下跌时缩量，上涨时放量
        close = np.array([100, 99, 98, 99, 100, 101, 102, 103, 102, 101,
                          100, 99, 100, 101, 102, 103, 104, 105, 106, 107,
                          108, 109, 108, 107, 108, 109, 110, 111, 112, 113])
        high = close + 2
        low = close - 2
        # 模式：下跌缩量(小vol)，上涨放量(大vol)
        volume = np.array([5000, 2000, 2000, 5000, 8000, 8000, 8000, 8000, 3000, 3000,
                           3000, 2000, 5000, 8000, 8000, 8000, 8000, 8000, 8000, 8000,
                           8000, 8000, 3000, 3000, 5000, 8000, 8000, 8000, 8000, 8000])
        df = pd.DataFrame({
            "close": close, "high": high, "low": low, "volume": volume,
        }, index=pd.DatetimeIndex(dates))
        m = WyckoffMethod()
        m.setup(MockContext({"lookback": 20, "volume_surge_ratio": 1.5, "price_change_threshold": 0.005}))
        result = m.generate_signal(df)
        # 应出现吸筹信号
        self.assertIn("accumulation", result["wyckoff_phase"].values)


class TestWyckoffMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = WyckoffMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": [], "high": [], "low": [], "volume": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_cleanup(self):
        m = WyckoffMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestWyckoffMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(WyckoffMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
