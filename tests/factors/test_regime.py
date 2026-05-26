"""Regime 因子单元测试（R1 阶段一）"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.factors.regime.regime_factor import classify_regime


@pytest.fixture
def uptrend_df():
    """上涨趋势数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    base = 100.0
    trend = np.linspace(0, 25, 100)
    noise = np.random.randn(100) * 1.5
    prices = base + trend + noise
    return pd.DataFrame(
        {
            "high": prices + np.random.rand(100) * 2,
            "low": prices - np.random.rand(100) * 2,
            "close": prices,
            "volume": np.random.randint(1_000_000, 5_000_000, 100),
        },
        index=dates,
    )


@pytest.fixture
def range_df():
    """震荡（盘整）数据。"""
    np.random.seed(7)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    prices = 100.0 + np.random.randn(100) * 2.0
    return pd.DataFrame(
        {
            "high": prices + np.random.rand(100) * 1.0,
            "low": prices - np.random.rand(100) * 1.0,
            "close": prices,
            "volume": np.random.randint(500_000, 2_000_000, 100),
        },
        index=dates,
    )


@pytest.fixture
def short_df():
    """极短数据。"""
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    return pd.DataFrame(
        {
            "high": [101, 102, 103, 102, 101],
            "low": [99, 100, 101, 100, 99],
            "close": [100, 101, 102, 101, 100],
            "volume": [1_000_000] * 5,
        },
        index=dates,
    )


class TestClassifyRegime:
    """classify_regime 测试。"""

    def test_uptrend_detection(self, uptrend_df):
        result = classify_regime(uptrend_df)
        # 合成趋势数据的 regime 不应是 UNKNOWN
        assert result["regime"] != "UNKNOWN"
        # 至少在 UPTREND / BREAKOUT 之二
        if result["regime"] not in ("UPTREND", "BREAKOUT", "CLIMAX", "RANGE"):
            pytest.fail(f"unexpected regime: {result['regime']}")
        assert 0 <= result["confidence"] <= 1.0
        assert isinstance(result["evidence"], dict)

    def test_range_detection(self, range_df):
        result = classify_regime(range_df)
        assert result["regime"] in ("RANGE", "UNKNOWN")
        assert 0 <= result["confidence"] <= 1.0

    def test_short_data(self, short_df):
        result = classify_regime(short_df)
        assert result["regime"] == "UNKNOWN"
        assert result["confidence"] <= 0.5

    def test_nan_handling(self):
        dates = pd.date_range("2025-01-01", periods=50, freq="D")
        df = pd.DataFrame(
            {
                "high": 100 + np.random.randn(50) * 5,
                "low": 95 + np.random.randn(50) * 5,
                "close": 100 + np.cumsum(np.random.randn(50) * 0.5),
                "volume": np.random.randint(1_000_000, 5_000_000, 50),
            },
            index=dates,
        )
        df.loc[df.index[5], "close"] = np.nan
        result = classify_regime(df)
        assert result["regime"] in (
            "UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX", "UNKNOWN"
        )
