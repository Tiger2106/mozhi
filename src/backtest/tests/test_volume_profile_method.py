"""
test_volume_profile_method.py — VolumeProfileMethod 单元测试 (C12)
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backtest.methods.trend.volume_profile_method import VolumeProfileMethod, METHOD_META
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


class TestVolumeProfileMethod_META(unittest.TestCase):
    def test_meta_exists(self):
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [])

    def test_meta_name(self):
        self.assertEqual(METHOD_META["name"], "volume_profile")

    def test_requires_state_false(self):
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])


class TestVolumeProfileMethod_Setup(unittest.TestCase):
    def test_defaults(self):
        m = VolumeProfileMethod()
        m.setup(MockContext({}))
        self.assertEqual(m.lookback, 20)
        self.assertEqual(m.n_zones, 5)
        self.assertEqual(m.volume_ratio_threshold, 1.5)

    def test_custom(self):
        m = VolumeProfileMethod()
        m.setup(MockContext({"lookback": 10, "n_zones": 3, "volume_ratio_threshold": 2.0}))
        self.assertEqual(m.lookback, 10)
        self.assertEqual(m.n_zones, 3)
        self.assertEqual(m.volume_ratio_threshold, 2.0)


class TestVolumeProfileMethod_GenerateSignal(unittest.TestCase):
    def setUp(self):
        self.method = VolumeProfileMethod()
        self.method.setup(MockContext({}))

    def test_signal_domain(self):
        df = make_df(60)
        result = self.method.generate_signal(df)
        self.assertTrue(result["signal"].isin({-1, 0, 1}).all())

    def test_has_columns(self):
        df = make_df(60)
        result = self.method.generate_signal(df)
        for col in ["signal", "volume_ratio", "high_zone_vol", "low_zone_vol", "vp_support", "vp_resistance"]:
            self.assertIn(col, result.columns)

    def test_missing_columns(self):
        with self.assertRaises(ValueError):
            self.method.generate_signal(pd.DataFrame({"close": [1.0]}))

    def test_index_preserved(self):
        df = make_df(50)
        result = self.method.generate_signal(df)
        pd.testing.assert_index_equal(result.index, df.index)


class TestVolumeProfileMethod_Boundary(unittest.TestCase):
    def test_empty_df(self):
        m = VolumeProfileMethod()
        m.setup(MockContext({}))
        df = pd.DataFrame({"close": [], "high": [], "low": [], "volume": []}, dtype=float)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_small_data(self):
        m = VolumeProfileMethod()
        m.setup(MockContext({"lookback": 20}))
        df = make_df(5)
        result = m.generate_signal(df)
        self.assertEqual(len(result), 5)

    def test_cleanup(self):
        m = VolumeProfileMethod()
        try:
            m.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestVolumeProfileMethod_Logic(unittest.TestCase):
    """成交量分布逻辑测试"""
    def test_low_zone_heavy(self):
        """低价区量大应产生BUY信号"""
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        close = np.concatenate([np.ones(15)*90, np.ones(15)*110])
        high = close + 10
        low = np.concatenate([np.ones(15)*80, np.ones(15)*100])
        # 低价区量远大于高价区
        volume = np.concatenate([np.ones(15)*10000, np.ones(15)*1000])
        df = pd.DataFrame({
            "close": close, "high": high, "low": low, "volume": volume,
        }, index=pd.DatetimeIndex(dates))
        m = VolumeProfileMethod()
        m.setup(MockContext({"lookback": 30, "volume_ratio_threshold": 1.5}))
        result = m.generate_signal(df)
        # 在低价区成交量大的情况下应有BUY信号
        has_buy = (result["signal"] == 1).any()
        self.assertTrue(has_buy, "低价区量大应产生BUY信号")


class TestVolumeProfileMethod_Inheritance(unittest.TestCase):
    def test_is_base_method(self):
        self.assertTrue(issubclass(VolumeProfileMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
