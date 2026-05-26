"""
test_method_meta_all.py — 全部 Method 的 METHOD_META 校验 (C19, C20, C21)

覆盖：
1. C19: 每个 Method 携带 METHOD_META + 必填字段
2. C20: 每个 Method 实现 setup() + generate_signal()
3. C21: GridMethod.requires_state == True，其他方法为 False
"""

import sys, os, unittest
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.methods.manifest import validate_manifest

# 导入所有 Method
from backtest.methods.trend.ma_cross_method import MaCrossMethod, METHOD_META as META_MACROSS
from backtest.methods.trend.macd_method import MACDMethod, METHOD_META as META_MACD
from backtest.methods.trend.bollinger_method import BollingerMethod, METHOD_META as META_BOLLINGER
from backtest.methods.trend.volume_profile_method import VolumeProfileMethod, METHOD_META as META_VP
from backtest.methods.trend.wyckoff_method import WyckoffMethod, METHOD_META as META_WYCKOFF
from backtest.methods.momentum.rsi_method import RSIMethod, METHOD_META as META_RSI
from backtest.methods.momentum.kdj_method import KDJMethod, METHOD_META as META_KDJ
from backtest.methods.momentum.bias_method import BiasMethod, METHOD_META as META_BIAS
from backtest.methods.grid.grid_method import GridMethod, METHOD_META as META_GRID
from backtest.methods.reversal.reversal_method import ReversalMethod, METHOD_META as META_REVERSAL


# ─── 所有 Method 及其 META ────────────────────────────────

ALL_METHODS = [
    (MaCrossMethod, META_MACROSS, "ma_cross"),
    (MACDMethod, META_MACD, "macd"),
    (BollingerMethod, META_BOLLINGER, "bollinger"),
    (VolumeProfileMethod, META_VP, "volume_profile"),
    (WyckoffMethod, META_WYCKOFF, "wyckoff"),
    (RSIMethod, META_RSI, "rsi"),
    (KDJMethod, META_KDJ, "kdj"),
    (BiasMethod, META_BIAS, "bias"),
    (GridMethod, META_GRID, "grid"),
    (ReversalMethod, META_REVERSAL, "reversal"),
]

# 预期 requires_state 值
EXPECTED_REQUIRES_STATE = {
    "ma_cross": False,
    "macd": False,
    "bollinger": False,
    "volume_profile": False,
    "wyckoff": False,
    "rsi": False,
    "kdj": False,
    "bias": False,
    "grid": True,
    "reversal": False,
}


class TestAllMethods_METAC19(unittest.TestCase):
    """C19: 每个 Method 携带 METHOD_META + 必填字段"""

    def test_all_have_meta(self):
        """所有 Method 类有 METHOD_META"""
        for cls, meta, name in ALL_METHODS:
            self.assertTrue(hasattr(cls, "METHOD_META"),
                            f"{name} 缺少 METHOD_META")

    def test_all_meta_valid(self):
        """所有 METHOD_META 通过 validate_manifest 校验"""
        for cls, meta, name in ALL_METHODS:
            errors = validate_manifest(meta)
            self.assertEqual(errors, [],
                             f"{name} METHOD_META 校验错误: {errors}")

    def test_meta_name_matches(self):
        """meta.name 与方法名对应"""
        for cls, meta, name in ALL_METHODS:
            self.assertEqual(meta["name"], name,
                             f"{name} meta.name 应为 '{name}'")

    def test_meta_has_version(self):
        """所有 meta 有 version"""
        for cls, meta, name in ALL_METHODS:
            self.assertIn("version", meta,
                          f"{name} 缺少 version")

    def test_meta_has_default_params(self):
        """所有 meta 有 default_params"""
        for cls, meta, name in ALL_METHODS:
            self.assertIn("default_params", meta,
                          f"{name} 缺少 default_params")
            self.assertIsInstance(meta["default_params"], dict)

    def test_meta_has_capabilities(self):
        """所有 meta 有 capabilities"""
        for cls, meta, name in ALL_METHODS:
            self.assertIn("capabilities", meta,
                          f"{name} 缺少 capabilities")

    def test_capabilities_has_long_only(self):
        for cls, meta, name in ALL_METHODS:
            self.assertIn("long_only", meta["capabilities"],
                          f"{name} capabilities 缺少 long_only")

    def test_capabilities_has_intraday_support(self):
        for cls, meta, name in ALL_METHODS:
            self.assertIn("intraday_support", meta["capabilities"],
                          f"{name} capabilities 缺少 intraday_support")

    def test_capabilities_has_requires_state(self):
        for cls, meta, name in ALL_METHODS:
            self.assertIn("requires_state", meta["capabilities"],
                          f"{name} capabilities 缺少 requires_state")


class TestAllMethods_SetupAndSignalC20(unittest.TestCase):
    """C20: 每个 Method 正确实现 setup() + generate_signal()"""

    def test_all_implement_setup(self):
        """所有 Method 实现 setup（即不是 BaseMethod 的抽象方法）"""
        for cls, meta, name in ALL_METHODS:
            self.assertNotEqual(
                cls.setup, BaseMethod.setup,
                f"{name} 未覆盖 setup()"
            )

    def test_all_implement_generate_signal(self):
        """所有 Method 实现 generate_signal"""
        for cls, meta, name in ALL_METHODS:
            self.assertNotEqual(
                cls.generate_signal, BaseMethod.generate_signal,
                f"{name} 未覆盖 generate_signal()"
            )


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
        self.symbol = "TEST"
    def get_config(self, key, default=None):
        return self._config.get(key, default)


class TestAllMethods_RequiresStateC21(unittest.TestCase):
    """C21: GridMethod.requires_state == True，其他方法为 False"""

    def test_requires_state_correct(self):
        for cls, meta, name in ALL_METHODS:
            expected = EXPECTED_REQUIRES_STATE[name]
            actual = meta["capabilities"]["requires_state"]
            self.assertEqual(
                actual, expected,
                f"{name} requires_state 应为 {expected}，实际为 {actual}"
            )

    def test_only_grid_requires_state(self):
        """仅 GridMethod requires_state=True"""
        for cls, meta, name in ALL_METHODS:
            if name == "grid":
                self.assertTrue(meta["capabilities"]["requires_state"])
            else:
                self.assertFalse(meta["capabilities"]["requires_state"])


class MockContextFull:
    """完整的模拟上下文，用于实际调用测试"""
    def __init__(self):
        self._config = {
            # MaCross
            "ma_fast": 5, "ma_slow": 20,
            # MACD
            "fast_period": 12, "slow_period": 26, "signal_period": 9,
            # Bollinger
            "period": 20, "std_dev": 2.0,
            # VolumeProfile
            "lookback": 20, "n_zones": 5, "volume_ratio_threshold": 1.5,
            # Wyckoff
            "volume_surge_ratio": 1.5, "price_change_threshold": 0.02,
            # RSI
            "oversold": 30.0, "overbought": 70.0,
            # KDJ
            "n": 9, "m1": 3, "m2": 3,
            # Bias
            "ma_period": 20, "bias_buy": -0.05, "bias_sell": 0.05,
            # Grid
            "n_levels": 10, "grid_type": "arithmetic", "width_multiplier": 2.0,
            # Reversal
            "rsi_period": 14, "rsi_oversold": 30.0, "rsi_overbought": 70.0,
            "kdj_n": 9, "kdj_oversold": 20.0, "kdj_overbought": 80.0,
            "bias_period": 20, "bias_buy": -0.05, "bias_sell": 0.05,
            "cooldown_bars": 5, "min_votes": 2,
        }
        self.symbol = "TEST"

    def get_config(self, key, default=None):
        return self._config.get(key, default)


class TestAllMethods_IntegrationSmoke(unittest.TestCase):
    """冒烟测试：每个 Method setup + generate_signal"""

    def test_ma_cross_smoke(self):
        m = MaCrossMethod()
        m.setup(MockContextFull())
        df = make_df(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_macd_smoke(self):
        m = MACDMethod()
        m.setup(MockContextFull())
        df = make_df(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_bollinger_smoke(self):
        m = BollingerMethod()
        m.setup(MockContextFull())
        df = make_df(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_volume_profile_smoke(self):
        m = VolumeProfileMethod()
        m.setup(MockContextFull())
        df = make_df_vp(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_wyckoff_smoke(self):
        m = WyckoffMethod()
        m.setup(MockContextFull())
        df = make_df_vp(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_rsi_smoke(self):
        m = RSIMethod()
        m.setup(MockContextFull())
        df = make_df(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_kdj_smoke(self):
        m = KDJMethod()
        m.setup(MockContextFull())
        df = make_df_kdj(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_bias_smoke(self):
        m = BiasMethod()
        m.setup(MockContextFull())
        df = make_df(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_grid_smoke(self):
        m = GridMethod()
        m.setup(MockContextFull())
        df = make_df_vp(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_reversal_smoke(self):
        m = ReversalMethod()
        m.setup(MockContextFull())
        df = make_df_kdj(50)
        result = m.generate_signal(df)
        self.assertIn("signal", result.columns)

    def test_each_method_cleanup(self):
        """所有 cleanup 不抛异常"""
        for cls, meta, name in ALL_METHODS:
            m = cls()
            try:
                m.cleanup()
            except Exception as e:
                self.fail(f"{name}.cleanup() 抛异常: {e}")


# ─── 辅助函数 ────────────────────────────────────────────

def make_df(n: int) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))


def make_df_kdj(n: int) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "close": close,
        "high": close + 2,
        "low": close - 2,
    }, index=pd.DatetimeIndex(dates))


def make_df_vp(n: int) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.rand(n) * 2
    low = close - np.random.rand(n) * 2
    volume = np.random.randint(1000, 10000, n)
    return pd.DataFrame({
        "close": close, "high": high, "low": low, "volume": volume,
    }, index=pd.DatetimeIndex(dates))


from backtest.methods.base import BaseMethod


if __name__ == "__main__":
    unittest.main()
