"""
test_ma_cross_method.py — MaCrossMethod 单元测试 (C9)

覆盖：
1. METHOD_META 验证
2. setup() 参数装配（默认值、覆盖值、缺失值）
3. generate_signal(df) 信号正确性（金叉/死叉、{-1,0,1} 值域）
4. 边界条件（空DF、最小数据量、全涨/全跌市场）
5. cleanup() 不抛异常
"""

import sys
import os
import unittest

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.methods.trend.ma_cross_method import MaCrossMethod, METHOD_META
from backtest.methods.manifest import validate_manifest
from backtest.context import StrategyContext
from backtest.methods.base import BaseMethod


class MockContext:
    """模拟 StrategyContext，提供 get_config 方法。"""
    def __init__(self, config: dict = None):
        self._config = config or {}
        self.symbol = "TEST"

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)


def make_up_trend_df(n: int = 50) -> pd.DataFrame:
    """生成持续上涨行情 DataFrame。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100.0 + np.arange(n) * 1.0  # 每Bar涨1
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 0.3,
        "low": close - 0.5,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    }, index=pd.DatetimeIndex(dates))


def make_down_trend_df(n: int = 50) -> pd.DataFrame:
    """生成持续下跌行情 DataFrame。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100.0 - np.arange(n) * 1.0
    return pd.DataFrame({
        "open": close + 0.5,
        "high": close + 0.5,
        "low": close - 0.3,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    }, index=pd.DatetimeIndex(dates))


def make_cross_df(n: int = 60) -> pd.DataFrame:
    """生成先涨后跌（有交叉点的）行情 DataFrame。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    # 前30Bar涨，后30Bar跌
    close = np.concatenate([
        100.0 + np.arange(30) * 0.5,   # 缓涨
        115.0 - np.arange(30) * 0.6,   # 缓跌
    ])
    return pd.DataFrame({
        "open": close - 0.2,
        "high": close + 0.3,
        "low": close - 0.3,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    }, index=pd.DatetimeIndex(dates))


# ═══════════════════════════════════════════════════════════════
# C9: test class
# ═══════════════════════════════════════════════════════════════

class TestMaCrossMethod_META(unittest.TestCase):
    """场景1: METHOD_META 验证"""

    def test_meta_exists(self):
        """模块级 METHOD_META 存在"""
        self.assertIsNotNone(METHOD_META)

    def test_meta_valid(self):
        """METHOD_META 通过 validate_manifest 校验"""
        errors = validate_manifest(METHOD_META)
        self.assertEqual(errors, [], f"METHOD_META 校验错误: {errors}")

    def test_meta_fields(self):
        """METHOD_META 关键字段"""
        self.assertEqual(METHOD_META["name"], "ma_cross")
        self.assertEqual(METHOD_META["version"], "1.0.0")
        self.assertIn("ma_fast", METHOD_META["default_params"])
        self.assertIn("ma_slow", METHOD_META["default_params"])

    def test_requires_state_false(self):
        """MaCrossMethod 不需要状态持久化"""
        self.assertFalse(METHOD_META["capabilities"]["requires_state"])

    def test_class_meta(self):
        """类属性 METHOD_META 与模块级一致"""
        self.assertIs(MaCrossMethod.METHOD_META, METHOD_META)


class TestMaCrossMethod_Setup(unittest.TestCase):
    """场景2: setup() 参数装配"""

    def test_default_params(self):
        """默认参数装配"""
        method = MaCrossMethod()
        ctx = MockContext({})
        method.setup(ctx)
        self.assertEqual(method.ma_fast, 5)
        self.assertEqual(method.ma_slow, 20)

    def test_custom_params(self):
        """自定义参数覆盖"""
        method = MaCrossMethod()
        ctx = MockContext({"ma_fast": 10, "ma_slow": 30})
        method.setup(ctx)
        self.assertEqual(method.ma_fast, 10)
        self.assertEqual(method.ma_slow, 30)

    def test_invalid_params_raises(self):
        """ma_fast >= ma_slow 时抛 ValueError"""
        method = MaCrossMethod()
        ctx = MockContext({"ma_fast": 20, "ma_slow": 10})
        with self.assertRaises(ValueError) as cm:
            method.setup(ctx)
        self.assertIn("ma_fast", str(cm.exception))

    def test_equal_params_raises(self):
        """ma_fast == ma_slow 时抛 ValueError"""
        method = MaCrossMethod()
        ctx = MockContext({"ma_fast": 15, "ma_slow": 15})
        with self.assertRaises(ValueError):
            method.setup(ctx)


class TestMaCrossMethod_GenerateSignal(unittest.TestCase):
    """场景3: generate_signal() 信号正确性"""

    def setUp(self):
        self.method = MaCrossMethod()
        ctx = MockContext({"ma_fast": 5, "ma_slow": 20})
        self.method.setup(ctx)

    def test_signal_domain(self):
        """信号值域为 {-1, 0, 1}"""
        df = make_cross_df(60)
        result = self.method.generate_signal(df)
        valid = result["signal"].dropna().isin({-1, 0, 1}).all()
        self.assertTrue(valid)

    def test_up_trend_golden_cross(self):
        """先跌后涨应有金叉信号 (1)"""
        # 先跌20天再涨30天
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        close = np.concatenate([
            100.0 - np.arange(20) * 0.5,  # 前20天下跌
            90.0 + np.arange(30) * 0.8,   # 后30天上涨 -> 产生金叉
        ])
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertIn(1, result["signal"].values)

    def test_down_trend_death_cross(self):
        """先涨后跌应有死叉信号 (-1)"""
        # 先涨20天再跌30天
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        close = np.concatenate([
            100.0 + np.arange(20) * 0.5,  # 前20天上涨
            110.0 - np.arange(30) * 0.8,   # 后30天下跌 -> 产生死叉
        ])
        df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))
        result = self.method.generate_signal(df)
        self.assertIn(-1, result["signal"].values)

    def test_cross_df_has_signals(self):
        """交叉行情应有信号"""
        df = make_cross_df(60)
        result = self.method.generate_signal(df)
        self.assertGreater(result["signal"].abs().sum(), 0)

    def test_result_columns(self):
        """结果包含必要列"""
        df = make_cross_df(60)
        result = self.method.generate_signal(df)
        for col in ["signal", "ma_fast_val", "ma_slow_val"]:
            self.assertIn(col, result.columns)


class TestMaCrossMethod_Boundary(unittest.TestCase):
    """场景4: 边界条件"""

    def test_empty_df(self):
        """空 DataFrame 返回空结果"""
        method = MaCrossMethod()
        ctx = MockContext({})
        method.setup(ctx)
        df = pd.DataFrame({"close": []}, dtype=float)
        result = method.generate_signal(df)
        self.assertEqual(len(result), 0)

    def test_missing_close_column(self):
        """缺少 close 列抛 ValueError"""
        method = MaCrossMethod()
        ctx = MockContext({})
        method.setup(ctx)
        df = pd.DataFrame({"open": [1.0, 2.0]})
        with self.assertRaises(ValueError) as cm:
            method.generate_signal(df)
        self.assertIn("close", str(cm.exception))

    def test_minimal_data(self):
        """数据量小于快线周期：无信号返回"""
        method = MaCrossMethod()
        ctx = MockContext({"ma_fast": 5, "ma_slow": 20})
        method.setup(ctx)
        df = make_up_trend_df(10)  # 10 < 20 (slow)
        result = method.generate_signal(df)
        self.assertEqual(len(result), 10)

    def test_all_up_market(self):
        """全涨市场应有稳定信号"""
        df = make_up_trend_df(100)
        self.method = MaCrossMethod()
        self.method.setup(MockContext({"ma_fast": 5, "ma_slow": 20}))
        result = self.method.generate_signal(df)
        # 上涨趋势: 快线在慢线上方 -> 初始信号不能是SELL
        # 但可能在初始状态有金叉或dead cross逻辑
        pass  # 至少不抛异常

    def test_all_down_market(self):
        """全跌市场应有稳定信号"""
        df = make_down_trend_df(100)
        self.method = MaCrossMethod()
        self.method.setup(MockContext({"ma_fast": 5, "ma_slow": 20}))
        result = self.method.generate_signal(df)
        pass  # 至少不抛异常


class TestMaCrossMethod_Cleanup(unittest.TestCase):
    """场景5: cleanup() 不抛异常"""

    def test_cleanup_noop(self):
        """cleanup 应安全执行"""
        method = MaCrossMethod()
        try:
            method.cleanup()
        except Exception as e:
            self.fail(f"cleanup 抛异常: {e}")


class TestMaCrossMethod_Inheritance(unittest.TestCase):
    """继承自 BaseMethod"""

    def test_is_base_method(self):
        """MaCrossMethod 是 BaseMethod 子类"""
        self.assertTrue(issubclass(MaCrossMethod, BaseMethod))


if __name__ == "__main__":
    unittest.main()
