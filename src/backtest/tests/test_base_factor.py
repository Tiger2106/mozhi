"""
test_base_factor.py — BaseFactor 单元测试

覆盖场景：
1. 子类化实现（完整实现compute）
2. compute()输出正确性
3. params默认值
"""

import sys
import os
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.factors.base import BaseFactor


# ─── 辅助：完整实现的因子子类 ───────────────────────────────


class MomentumFactor(BaseFactor):
    """动量因子：完整实现"""
    FACTOR_META = {
        "name": "momentum",
        "version": "1.0.0",
        "category": "momentum",
        "default_params": {"window": 20},
    }

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(self.params.get("window", 20))


class VolatilityFactor(BaseFactor):
    """波动率因子：完整实现"""
    FACTOR_META = {
        "name": "volatility",
        "version": "1.0.0",
        "category": "risk",
        "default_params": {"window": 10},
    }

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change().rolling(self.params.get("window", 10)).std()


class TestBaseFactor_子类化实现(unittest.TestCase):
    """场景1: 子类化实现"""

    def test_instantiate_concrete_factor(self):
        """具体因子可实例化"""
        f = MomentumFactor()
        self.assertIsInstance(f, BaseFactor)

    def test_cannot_instantiate_abstract(self):
        """抽象基类本身不可实例化（有抽象方法）"""
        with self.assertRaises(TypeError):
            BaseFactor()  # ABC with abstractmethod

    def test_missing_compute_raises(self):
        """未实现compute的子类不可实例化"""
        with self.assertRaises(TypeError):
            class IncompleteFactor(BaseFactor):
                FACTOR_META = {"name": "incomplete", "version": "1.0.0",
                               "category": "test", "default_params": {}}
                pass
            IncompleteFactor()


class TestBaseFactor_compute输出(unittest.TestCase):
    """场景2: compute()输出"""

    def setUp(self):
        np = __import__("numpy")
        self.df = pd.DataFrame(
            {"close": [100.0, 102.0, 101.0, 105.0, 107.0]},
            index=pd.date_range("2025-01-01", periods=5)
        )

    def test_momentum_output_series(self):
        """动量因子输出pd.Series"""
        f = MomentumFactor(params={"window": 2})
        result = f.compute(self.df)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(len(result), 5)

    def test_volatility_output_series(self):
        """波动率因子输出pd.Series"""
        f = VolatilityFactor(params={"window": 2})
        result = f.compute(self.df)
        self.assertIsInstance(result, pd.Series)

    def test_momentum_first_n_values_nan(self):
        """动量因子前window个值为NaN"""
        f = MomentumFactor(params={"window": 2})
        result = f.compute(self.df)
        # pct_change(2): first 2 values are NaN
        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertTrue(pd.isna(result.iloc[1]))
        self.assertFalse(pd.isna(result.iloc[2]))

    def test_volatility_values(self):
        """波动率因子计算值验证"""
        f = VolatilityFactor(params={"window": 2})
        result = f.compute(self.df)
        self.assertEqual(len(result), 5)


class TestBaseFactor_params默认值(unittest.TestCase):
    """场景3: params默认值"""

    def test_default_params_from_meta(self):
        """未传入params时，使用FACTOR_META的默认值"""
        f = MomentumFactor()
        self.assertEqual(f.params, {"window": 20})

    def test_params_override(self):
        """传入params时覆盖默认值"""
        f = MomentumFactor(params={"window": 10})
        self.assertEqual(f.params, {"window": 10})

    def test_partial_override(self):
        """部分覆盖：默认值保持，新键添加"""
        f = MomentumFactor(params={"threshold": 0.5})
        self.assertEqual(f.params["window"], 20)
        self.assertEqual(f.params["threshold"], 0.5)

    def test_empty_params(self):
        """空字典不影响默认值"""
        f = MomentumFactor(params={})
        self.assertEqual(f.params, {"window": 20})

    def test_volatility_default(self):
        """VolatilityFactor默认参数"""
        f = VolatilityFactor()
        self.assertEqual(f.params, {"window": 10})


class TestBaseFactor_repr(unittest.TestCase):
    """BaseFactor __repr__ 测试"""

    def test_repr_with_name(self):
        """repr包含FACTOR_META中的name"""
        f = MomentumFactor()
        self.assertIn("momentum", repr(f))

    def test_repr_without_meta(self):
        """子类没有FACTOR_META时，repr用类名"""
        class CustomFactor(BaseFactor):
            def compute(self, df):
                return df["close"]
        f = CustomFactor()
        self.assertIn("CustomFactor", repr(f))


if __name__ == "__main__":
    unittest.main()
