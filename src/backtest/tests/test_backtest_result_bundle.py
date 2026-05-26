"""
mozhi_platform 测试 — BacktestResultBundle + bundle_from_runner + compute_data_quality

作者: 墨衡
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from backtest.methods.base import MethodResult
from backtest.engine.backtest_result_bundle import (
    BacktestResultBundle,
    compute_data_quality,
    bundle_from_runner,
    _build_benchmark_curve,
)


def _make_signals_df() -> pd.DataFrame:
    """生成模拟信号 DataFrame。"""
    dates = pd.date_range("2025-06-01", periods=10, freq="D")
    return pd.DataFrame({
        "close": [10.0 + i for i in range(10)],
        "signal": [0, 1, 0, -1, 0, 1, 0, -1, 0, 0],
        "position": [0, 1, 1, 0, 0, 1, 1, 0, 0, 0],
    }, index=dates)


def _make_ohlcv() -> pd.DataFrame:
    """生成模拟 OHLCV 数据。"""
    dates = pd.date_range("2025-06-01", periods=10, freq="D")
    return pd.DataFrame({
        "open": [10.0 + i for i in range(10)],
        "high": [10.5 + i for i in range(10)],
        "low": [9.8 + i for i in range(10)],
        "close": [10.0 + i * 1.02 for i in range(10)],
        "volume": [100_000 + i * 1000 for i in range(10)],
    }, index=dates)


def _make_method_result() -> MethodResult:
    """生成模拟 MethodResult。"""
    signals = _make_signals_df()
    return MethodResult(
        method_name="ma_cross",
        params={"ma_short": 5, "ma_long": 20},
        signals=signals,
        indicators=pd.DataFrame(),
        statistics={
            "n_bars": 100,
            "n_signals": 8,
            "n_buy": 4,
            "n_sell": 4,
            "signal_ratio": 0.08,
        },
# summary removed — not a MethodResult parameter

    )


# ─── BacktestResultBundle ────────────────────────────────────────────


class TestBacktestResultBundle:
    def test_creation_defaults(self):
        bundle = BacktestResultBundle()
        assert bundle.run_id == ""
        assert bundle.method_name == ""
        assert isinstance(bundle.equity_curve, pd.DataFrame)
        assert isinstance(bundle.trades, list)
        assert isinstance(bundle.insights, list)
        assert isinstance(bundle.summary_metrics, dict)
        assert isinstance(bundle.data_quality, dict)

    def test_creation_with_values(self):
        bundle = BacktestResultBundle(
            run_id="test_001",
            method_name="ma_cross",
            symbol="601857.SH",
            start_date="2025-06-01",
            end_date="2025-12-31",
            params={"ma_short": 5},
            summary_metrics={"n_trades": 10},
            data_quality={"completeness": 99.2, "rating": "A"},
        )
        assert bundle.run_id == "test_001"
        assert bundle.method_name == "ma_cross"
        assert bundle.symbol == "601857.SH"
        assert bundle.summary_metrics["n_trades"] == 10

    def test_repr(self):
        bundle = BacktestResultBundle(
            run_id="r1", method_name="macd", symbol="601857.SH"
        )
        r = repr(bundle)
        assert "r1" in r
        assert "macd" in r
        assert "601857" in r


# ─── compute_data_quality ────────────────────────────────────────────


class TestComputeDataQuality:
    def test_perfect_data(self):
        df = _make_ohlcv()
        result = compute_data_quality(df)
        assert result["completeness"] == 100.0
        assert result["rating"] == "A"
        assert result["engine_version"] == "v3.0"
        assert result["real_trade"] is False

    def test_partial_data(self):
        df = _make_ohlcv()
        expected = pd.date_range("2025-06-01", periods=12, freq="D")
        df_expected = pd.DataFrame(index=expected)
        result = compute_data_quality(df, df_expected=df_expected)
        # 10 actual / 12 expected = 83.3%
        assert result["total_days"] == 12
        assert result["actual_days"] == 10
        assert result["missing_days"] == 2
        assert result["rating"] == "C"

    def test_nan_stats(self):
        df = _make_ohlcv()
        df.loc[df.index[0], "close"] = np.nan
        result = compute_data_quality(df)
        assert result["nan_stats"]["close"] > 0

    def test_with_config(self):
        df = _make_ohlcv()
        config = {"data_source": "local", "engine_version": "v3.2"}
        result = compute_data_quality(df, config=config)
        assert result["source"] == "local"
        assert result["engine_version"] == "v3.2"

    def test_slippage_placeholder(self):
        df = _make_ohlcv()
        result = compute_data_quality(df)
        assert result["slippage_validated"] is False
        assert "Phase 3" in result["slippage_note"]

    def test_empty_df(self):
        df = pd.DataFrame()
        result = compute_data_quality(df)
        # 空 DataFrame 且无 expected 时，默认 completeness=100%
        assert result["completeness"] == 100.0
        assert result["rating"] == "D"  # 无数据时评级 D


# ─── _build_benchmark_curve ──────────────────────────────────────────


class TestBuildBenchmarkCurve:
    def test_basic(self):
        df = _make_ohlcv()
        result = _build_benchmark_curve(df)
        assert isinstance(result, pd.DataFrame)
        if not result.empty:
            assert "equity" in result.columns
            assert "return" in result.columns

    def test_empty_if_no_close(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = _build_benchmark_curve(df)
        assert result.empty


# ─── bundle_from_runner ──────────────────────────────────────────────


class TestBundleFromRunner:
    def test_basic_mapping(self):
        mr = _make_method_result()
        df = _make_ohlcv()
        bundle = bundle_from_runner(mr, df)
        assert isinstance(bundle, BacktestResultBundle)
        assert bundle.method_name == "ma_cross"
        assert bundle.symbol == ""
        assert bundle.params["ma_short"] == 5
        # 检查 summary_metrics 中映射了 statistics
        assert bundle.summary_metrics.get("n_bars") == 100
        assert bundle.summary_metrics.get("n_signals") == 8
        assert bundle.summary_metrics.get("signal_ratio") == 0.08

    def test_data_quality_in_bundle(self):
        mr = _make_method_result()
        df = _make_ohlcv()
        bundle = bundle_from_runner(mr, df)
        assert isinstance(bundle.data_quality, dict)
        assert "completeness" in bundle.data_quality
        assert "rating" in bundle.data_quality

    def test_empty_signals(self):
        """处理空 signals 不应崩溃。"""
        mr = MethodResult(
            method_name="empty",
            params={},
            signals=pd.DataFrame(),
            indicators=pd.DataFrame(),
            statistics={},
        )
        df = pd.DataFrame()
        # 空数据场景：至少不应抛出异常
        bundle = bundle_from_runner(mr, df)
        assert isinstance(bundle, BacktestResultBundle)
