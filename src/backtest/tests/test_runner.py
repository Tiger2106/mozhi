"""
test_runner.py — MethodBacktestRunner 单元测试

覆盖场景:
1. test_mode_a_method: 模式A（无状态方法，如 MACD）标准流程
2. test_mode_b_method: 模式B（有状态方法，如 Grid）事件驱动流程
3. test_unknown_method: 未知方法抛 ValueError
4. test_run_batch: 批量运行（多时间框架）

作者: 墨衡
创建时间: 2026-05-17
"""

import sys
import os
import unittest

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.context import StrategyContext
from backtest.methods.base import MethodResult
from backtest.runners.method_backtest_runner import MethodBacktestRunner


# ──────────────────────────────────────────────────────────────────────
# 测试数据生成
# ──────────────────────────────────────────────────────────────────────


def _make_price_df(
    n: int = 100,
    seed: int = 42,
) -> pd.DataFrame:
    """生成合成 OHLCV 测试数据。

    Args:
        n: 数据行数。
        seed: 随机种子。

    Returns:
        pd.DataFrame: 包含 open/high/low/close/volume 列的 DataFrame，
                      索引为 DatetimeIndex。
    """
    rng = np.random.default_rng(seed)
    # 生成趋势 + 噪声的收盘价
    base = 100.0
    trend = np.linspace(0, 5, n)
    noise = rng.normal(0, 1.5, n)
    closes = base + trend + np.cumsum(noise) * 0.3

    opens = closes + rng.normal(0, 0.5, n)
    highs = np.maximum(
        np.maximum(opens, closes),
        np.maximum(opens, closes) + np.abs(rng.normal(0, 0.8, n)),
    )
    lows = np.minimum(
        np.minimum(opens, closes),
        np.minimum(opens, closes) - np.abs(rng.normal(0, 0.8, n)),
    )
    volumes = rng.integers(10000, 100000, n)

    dates = pd.date_range("2025-01-01", periods=n, freq="D")

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=pd.DatetimeIndex(dates, name="date"),
    )


# ──────────────────────────────────────────────────────────────────────
# 测试类
# ──────────────────────────────────────────────────────────────────────


class TestRunnerModeA(unittest.TestCase):
    """场景1: 模式A — 无状态方法（MACD）标准流程"""

    def setUp(self):
        self.df = _make_price_df(n=100)
        self.ctx = StrategyContext(
            symbol="601857.SH",
            method_name="macd",
            config={
                "fast_period": 12,
                "slow_period": 26,
                "signal_period": 9,
            },
        )

    def test_mode_a_macd_returns_methodresult(self):
        """MACD 运行应返回 MethodResult 实例"""
        runner = MethodBacktestRunner("macd", self.ctx)
        result = runner.run(self.df)
        self.assertIsInstance(result, MethodResult)
        self.assertEqual(result.method_name, "macd")

    def test_mode_a_macd_signal_column_valid(self):
        """MACD 信号列值域应在 {-1, 0, 1} 内"""
        runner = MethodBacktestRunner("macd", self.ctx)
        result = runner.run(self.df)
        self.assertIn("signal", result.signals.columns)
        valid_values = result.signals["signal"].dropna().unique()
        for v in valid_values:
            self.assertIn(v, {-1, 0, 1})

    def test_mode_a_macd_indicators(self):
        """MACD 应生成指标列（dif/dea/macd_hist）"""
        runner = MethodBacktestRunner("macd", self.ctx)
        result = runner.run(self.df)
        self.assertIsNotNone(result.indicators)
        for col in ["dif", "dea", "macd_hist"]:
            self.assertIn(col, result.indicators.columns)

    def test_mode_a_metrics_filled(self):
        """运行时应填充 duration_ms 和 completed_time"""
        runner = MethodBacktestRunner("macd", self.ctx)
        result = runner.run(self.df)
        self.assertIsNotNone(result.duration_ms)
        self.assertGreater(result.duration_ms, 0)
        self.assertIsNotNone(result.completed_time)
        self.assertIn("+08:00", result.completed_time)

    def test_mode_a_n_bars_correct(self):
        """n_bars 应与输入数据一致"""
        runner = MethodBacktestRunner("macd", self.ctx)
        result = runner.run(self.df)
        self.assertEqual(result.n_bars, len(self.df))

    def test_mode_a_ma_cross_also_works(self):
        """模式A 下 ma_cross 方法也能正常运行"""
        ctx = StrategyContext(
            symbol="601857.SH",
            method_name="ma_cross",
            config={"fast_period": 5, "slow_period": 20},
        )
        runner = MethodBacktestRunner("ma_cross", ctx)
        result = runner.run(self.df)
        self.assertIsInstance(result, MethodResult)
        self.assertEqual(result.method_name, "ma_cross")
        self.assertGreater(result.n_bars, 0)


class TestRunnerModeB(unittest.TestCase):
    """场景2: 模式B — 有状态方法（Grid）事件驱动流程"""

    def setUp(self):
        self.df = _make_price_df(n=60)  # 60 bars for grid (needs lookback=20)
        self.ctx = StrategyContext(
            symbol="601857.SH",
            method_name="grid",
            config={
                "n_levels": 10,
                "grid_type": "arithmetic",
                "lookback": 20,
                "width_multiplier": 2.0,
            },
        )

    def test_mode_b_grid_returns_methodresult(self):
        """Grid 运行应返回 MethodResult 实例"""
        runner = MethodBacktestRunner("grid", self.ctx)
        result = runner.run(self.df)
        self.assertIsInstance(result, MethodResult)
        self.assertEqual(result.method_name, "grid")

    def test_mode_b_grid_signal_column_valid(self):
        """Grid 信号列值域应在 {-1, 0, 1} 内"""
        runner = MethodBacktestRunner("grid", self.ctx)
        result = runner.run(self.df)
        self.assertIn("signal", result.signals.columns)
        valid_values = result.signals["signal"].dropna().unique()
        for v in valid_values:
            self.assertIn(v, {-1, 0, 1})

    def test_mode_b_grid_metrics_filled(self):
        """Grid 运行时应填充 duration_ms 和 completed_time"""
        runner = MethodBacktestRunner("grid", self.ctx)
        result = runner.run(self.df)
        self.assertIsNotNone(result.duration_ms)
        self.assertGreater(result.duration_ms, 0)
        self.assertIsNotNone(result.completed_time)
        self.assertIn("+08:00", result.completed_time)

    def test_mode_b_grid_n_bars_correct(self):
        """Grid n_bars 应与输入数据一致"""
        runner = MethodBacktestRunner("grid", self.ctx)
        result = runner.run(self.df)
        self.assertEqual(result.n_bars, len(self.df))

    def test_mode_b_reversal_requires_state_false(self):
        """ReversalMethod 的 requires_state=False，走模式A"""
        ctx = StrategyContext(
            symbol="601857.SH",
            method_name="reversal",
            config={
                "rsi_period": 14,
                "kdj_n": 9,
                "bias_period": 20,
                "cooldown_bars": 5,
                "min_votes": 2,
            },
        )
        runner = MethodBacktestRunner("reversal", ctx)
        result = runner.run(self.df)
        self.assertIsInstance(result, MethodResult)
        self.assertIn("signal", result.signals.columns)


class TestRunnerUnknownMethod(unittest.TestCase):
    """场景3: 未知方法抛 ValueError"""

    def test_unknown_method_raises(self):
        """未注册的方法名应抛 ValueError"""
        ctx = StrategyContext(symbol="601857.SH", method_name="dummy")
        with self.assertRaises(ValueError) as ctx_mgr:
            MethodBacktestRunner("non_existent_method_xyz", ctx)
        self.assertIn("未知方法", str(ctx_mgr.exception))

    def test_typo_method_raises(self):
        """拼写错误的方法名应抛 ValueError"""
        ctx = StrategyContext(symbol="601857.SH", method_name="mac")
        with self.assertRaises(ValueError):
            MethodBacktestRunner("mac", ctx)


class TestRunnerRunBatch(unittest.TestCase):
    """场景4: 批量运行（多时间框架支持）"""

    def setUp(self):
        self.df_daily = _make_price_df(n=100, seed=42)
        self.df_weekly = _make_price_df(n=20, seed=99)
        self.ctx = StrategyContext(
            symbol="601857.SH",
            method_name="macd",
            config={
                "fast_period": 12,
                "slow_period": 26,
                "signal_period": 9,
            },
        )

    def test_run_batch_two_frequencies(self):
        """批量运行应返回两个时间框架的结果"""
        runner = MethodBacktestRunner("macd", self.ctx)
        data_dict = {"daily": self.df_daily, "weekly": self.df_weekly}
        results = runner.run_batch(data_dict)
        self.assertIsInstance(results, dict)
        self.assertIn("daily", results)
        self.assertIn("weekly", results)

    def test_run_batch_all_methodresults(self):
        """批量运行的所有结果应为 MethodResult"""
        runner = MethodBacktestRunner("macd", self.ctx)
        data_dict = {"daily": self.df_daily, "weekly": self.df_weekly}
        results = runner.run_batch(data_dict)
        for freq, result in results.items():
            with self.subTest(freq=freq):
                self.assertIsInstance(result, MethodResult)

    def test_run_batch_n_bars_match(self):
        """批量运行各结果的 n_bars 应与输入对齐"""
        runner = MethodBacktestRunner("macd", self.ctx)
        data_dict = {"daily": self.df_daily, "weekly": self.df_weekly}
        results = runner.run_batch(data_dict)
        self.assertEqual(results["daily"].n_bars, len(self.df_daily))
        self.assertEqual(results["weekly"].n_bars, len(self.df_weekly))

    def test_run_batch_duration_filled(self):
        """批量运行应填充 duration_ms"""
        runner = MethodBacktestRunner("macd", self.ctx)
        data_dict = {"daily": self.df_daily, "weekly": self.df_weekly}
        results = runner.run_batch(data_dict)
        for freq, result in results.items():
            with self.subTest(freq=freq):
                self.assertIsNotNone(result.duration_ms)
                self.assertGreater(result.duration_ms, 0)

    def test_run_batch_handles_empty_dict(self):
        """空字典的批量运行应返回空 dict"""
        runner = MethodBacktestRunner("macd", self.ctx)
        results = runner.run_batch({})
        self.assertEqual(results, {})

    def test_run_batch_partial_failure(self):
        """某个时间框架失败不应影响其他结果"""
        runner = MethodBacktestRunner("macd", self.ctx)
        data_dict = {
            "daily": self.df_daily,
            "bad": pd.DataFrame({"wrong": [1, 2, 3]}),  # 缺少 close 列
        }
        results = runner.run_batch(data_dict)
        self.assertIn("daily", results)
        self.assertIn("bad", results)
        # daily 应成功
        self.assertEqual(results["daily"].n_bars, len(self.df_daily))
        # bad 应失败但返回空 result
        self.assertEqual(len(results["bad"].errors), 1)


class TestRunnerEdgeCases(unittest.TestCase):
    """边界场景"""

    def test_empty_dataframe(self):
        """空 DataFrame → ValueError（R1 数据预检）"""
        df = pd.DataFrame(
            {"close": []},
            index=pd.DatetimeIndex([]),
            dtype=float,
        )
        ctx = StrategyContext(
            symbol="601857.SH",
            method_name="macd",
            config={"fast_period": 12, "slow_period": 26, "signal_period": 9},
        )
        runner = MethodBacktestRunner("macd", ctx)
        with self.assertRaises(ValueError):
            runner.run(df)

    def test_single_row(self):
        """单行数据不足 data_min_bars -> ValueError（R1 数据预检）"""
        df = pd.DataFrame(
            {"close": [100.0]},
            index=pd.DatetimeIndex(["2025-01-01"]),
        )
        ctx = StrategyContext(
            symbol="601857.SH",
            method_name="ma_cross",
            config={"fast_period": 5, "slow_period": 20},
        )
        runner = MethodBacktestRunner("ma_cross", ctx)
        with self.assertRaises(ValueError):
            runner.run(df)

    def test_grid_with_short_data(self):
        """Grid 使用短数据（少于 lookback）应安全运行"""
        df = _make_price_df(n=10, seed=42)  # 只有 10 bar，lookback=20
        ctx = StrategyContext(
            symbol="601857.SH",
            method_name="grid",
            config={"lookback": 20},
        )
        runner = MethodBacktestRunner("grid", ctx)
        with self.assertRaises(ValueError):
            runner.run(df)


if __name__ == "__main__":
    unittest.main()
