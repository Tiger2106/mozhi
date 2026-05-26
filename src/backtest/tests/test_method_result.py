"""
test_method_result.py — MethodResult 单元测试

覆盖场景：
1. 正常构造（含完整字段）
2. 空DataFrame防御
3. 缺少signal列抛ValueError
4. signal值域不合法（2、-2、0.5）抛ValueError
5. 非DatetimeIndex抛ValueError（RangeIndex、MultiIndex）
6. statistics类型异常warning
7. n_bars/n_signals/signal_ratio自动计算正确性
"""

import sys
import os
import warnings
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.methods.base import MethodResult


class TestMethodResult_正常构造(unittest.TestCase):
    """场景1: 正常构造"""

    def test_minimal_fields(self):
        """最小字段构造：仅必填"""
        df = pd.DataFrame(
            {"signal": [0, 1, -1, 0]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"])
        )
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 4)
        self.assertEqual(r.n_signals, 2)
        self.assertAlmostEqual(r.signal_ratio, 0.5)
        self.assertEqual(r.method_name, "")
        self.assertEqual(r.params, {})
        self.assertEqual(r.statistics, {})
        self.assertIsNone(r.completed_time)
        self.assertIsNone(r.duration_ms)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.metadata, {})

    def test_all_fields(self):
        """完整字段构造"""
        df = pd.DataFrame(
            {"signal": [1, -1, 0]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        r = MethodResult(
            signals=df,
            indicators=pd.DataFrame({"sma": [1.0, 2.0, 3.0]}),
            method_name="test_method",
            params={"fast": 12},
            statistics={"sharpe": 1.5},
            completed_time="2025-01-03T15:00:00",
            duration_ms=10.5,
            errors=["warn: low data"],
            metadata={"source": "manual"},
        )
        self.assertEqual(r.n_bars, 3)
        self.assertEqual(r.n_signals, 2)
        self.assertAlmostEqual(r.signal_ratio, 2 / 3)
        self.assertEqual(r.method_name, "test_method")
        self.assertEqual(r.params, {"fast": 12})
        self.assertEqual(r.statistics, {"sharpe": 1.5})
        self.assertEqual(r.completed_time, "2025-01-03T15:00:00")
        self.assertEqual(r.duration_ms, 10.5)
        self.assertEqual(r.errors, ["warn: low data"])
        self.assertEqual(r.metadata, {"source": "manual"})


class TestMethodResult_空DataFrame防御(unittest.TestCase):
    """场景2: 空DataFrame防御"""

    def test_empty_df(self):
        """空DataFrame应安全处理，不抛异常"""
        df = pd.DataFrame({"signal": []}, dtype=int)
        # 空 DataFrame 即使有"signal"列也会被 empty 检测
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 0)
        self.assertEqual(r.n_signals, 0)
        self.assertEqual(r.signal_ratio, 0.0)

    def test_empty_df_no_columns(self):
        """完全空的DataFrame（无列）"""
        df = pd.DataFrame(index=pd.DatetimeIndex([]))
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 0)
        self.assertEqual(r.n_signals, 0)
        self.assertEqual(r.signal_ratio, 0.0)


class TestMethodResult_缺少signal列(unittest.TestCase):
    """场景3: 缺少signal列抛ValueError"""

    def test_missing_signal_column(self):
        """缺少signal列的DataFrame应抛ValueError"""
        df = pd.DataFrame(
            {"close": [10.0, 11.0]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02"])
        )
        with self.assertRaises(ValueError) as ctx:
            MethodResult(signals=df)
        self.assertIn("signal", str(ctx.exception).lower())


class TestMethodResult_signal值域校验(unittest.TestCase):
    """场景4: signal值域不合法抛ValueError"""

    def test_invalid_value_2(self):
        """值为2应抛ValueError"""
        df = pd.DataFrame(
            {"signal": [1, 2, 0]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        with self.assertRaises(ValueError) as ctx:
            MethodResult(signals=df)
        self.assertIn("signal", str(ctx.exception))

    def test_invalid_value_negative2(self):
        """值为-2应抛ValueError"""
        df = pd.DataFrame(
            {"signal": [-2, 0, 1]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        with self.assertRaises(ValueError):
            MethodResult(signals=df)

    def test_invalid_value_0_5(self):
        """值为0.5应抛ValueError"""
        df = pd.DataFrame(
            {"signal": [0.5, -0.5]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02"])
        )
        with self.assertRaises(ValueError):
            MethodResult(signals=df)

    def test_valid_all_zeros(self):
        """全零信号应通过"""
        df = pd.DataFrame(
            {"signal": [0, 0, 0]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        r = MethodResult(signals=df)
        self.assertEqual(r.n_signals, 0)
        self.assertEqual(r.signal_ratio, 0.0)


class TestMethodResult_索引类型校验(unittest.TestCase):
    """场景5: 非DatetimeIndex抛ValueError"""

    def test_range_index(self):
        """RangeIndex应抛ValueError"""
        df = pd.DataFrame({"signal": [1, 0, -1]})
        with self.assertRaises(ValueError) as ctx:
            MethodResult(signals=df)
        self.assertIn("DatetimeIndex", str(ctx.exception))

    def test_multi_index(self):
        """MultiIndex应抛ValueError"""
        arrays = [["a", "a", "b"], [1, 2, 1]]
        df = pd.DataFrame(
            {"signal": [1, 0, -1]},
            index=pd.MultiIndex.from_arrays(arrays, names=["level1", "level2"])
        )
        with self.assertRaises(ValueError) as ctx:
            MethodResult(signals=df)
        self.assertIn("DatetimeIndex", str(ctx.exception))


class TestMethodResult_statistics类型异常warning(unittest.TestCase):
    """场景6: statistics值类型异常应发出warning"""

    def test_string_stat_warns(self):
        """statistics中字符串值应发出UserWarning"""
        df = pd.DataFrame(
            {"signal": [1, 0, -1]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MethodResult(
                signals=df,
                statistics={"sharpe": "1.5"}  # str instead of float
            )
            self.assertEqual(len(w), 1)
            self.assertIn("statistics", str(w[0].message).lower())

    def test_list_stat_warns(self):
        """statistics中列表值应发出UserWarning"""
        df = pd.DataFrame(
            {"signal": [1, 0, -1]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MethodResult(
                signals=df,
                statistics={"sharpe": [1.5, 2.0]}
            )
            self.assertEqual(len(w), 1)
            self.assertIn("statistics", str(w[0].message).lower())

    def test_int_stat_no_warn(self):
        """statistics中int值不应warning"""
        df = pd.DataFrame(
            {"signal": [1, 0, -1]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MethodResult(
                signals=df,
                statistics={"sharpe": 1}  # int is fine
            )
            self.assertEqual(len(w), 0)

    def test_float_stat_no_warn(self):
        """statistics中float值不应warning"""
        df = pd.DataFrame(
            {"signal": [1, 0, -1]},
            index=pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MethodResult(
                signals=df,
                statistics={"sharpe": 1.5}
            )
            self.assertEqual(len(w), 0)


class TestMethodResult_自动计算正确性(unittest.TestCase):
    """场景7: n_bars/n_signals/signal_ratio自动计算正确性"""

    def test_all_positive(self):
        """全正信号"""
        df = pd.DataFrame(
            {"signal": [1, 1, 1, 1, 1]},
            index=pd.DatetimeIndex(pd.date_range("2025-01-01", periods=5))
        )
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 5)
        self.assertEqual(r.n_signals, 5)
        self.assertEqual(r.signal_ratio, 1.0)

    def test_all_negative(self):
        """全负信号"""
        df = pd.DataFrame(
            {"signal": [-1, -1, -1]},
            index=pd.DatetimeIndex(pd.date_range("2025-01-01", periods=3))
        )
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 3)
        self.assertEqual(r.n_signals, 3)
        self.assertEqual(r.signal_ratio, 1.0)

    def test_all_zeros(self):
        """全无信号"""
        df = pd.DataFrame(
            {"signal": [0, 0, 0, 0]},
            index=pd.DatetimeIndex(pd.date_range("2025-01-01", periods=4))
        )
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 4)
        self.assertEqual(r.n_signals, 0)
        self.assertEqual(r.signal_ratio, 0.0)

    def test_single_row(self):
        """单行数据"""
        df = pd.DataFrame(
            {"signal": [1]},
            index=pd.DatetimeIndex(["2025-01-01"])
        )
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 1)
        self.assertEqual(r.n_signals, 1)
        self.assertEqual(r.signal_ratio, 1.0)

    def test_mixed_signals(self):
        """混合信号"""
        df = pd.DataFrame(
            {"signal": [1, 0, -1, 0, 1, -1]},
            index=pd.DatetimeIndex(pd.date_range("2025-01-01", periods=6))
        )
        r = MethodResult(signals=df)
        self.assertEqual(r.n_bars, 6)
        self.assertEqual(r.n_signals, 4)
        self.assertAlmostEqual(r.signal_ratio, 4 / 6)


if __name__ == "__main__":
    unittest.main()
