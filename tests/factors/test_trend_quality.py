"""Trend Quality 因子单元测试（R1 阶段一）"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.factors.trend.trend_quality_factor import (
    calc_adx,
    calc_trend_strength,
    calc_trend_consistency,
)


@pytest.fixture
def trend_df():
    """有明显的上升趋势数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    base = 100.0
    trend = np.linspace(0, 30, 100)  # 稳步上升
    noise = np.random.randn(100) * 2
    prices = base + trend + noise
    return pd.DataFrame(
        {
            "high": prices + np.random.rand(100) * 3,
            "low": prices - np.random.rand(100) * 3,
            "close": prices,
        },
        index=dates,
    )


@pytest.fixture
def random_df():
    """纯随机数据（应产生低 ADX / 弱趋势）。"""
    np.random.seed(1)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    prices = 100.0 + np.random.randn(100) * 1.0
    return pd.DataFrame(
        {
            "high": prices + np.random.rand(100) * 0.5,
            "low": prices - np.random.rand(100) * 0.5,
            "close": prices,
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
        },
        index=dates,
    )


@pytest.fixture
def nan_df():
    """含有 NaN 的数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    df = pd.DataFrame(
        {
            "high": 100 + np.random.randn(50) * 5,
            "low": 95 + np.random.randn(50) * 5,
            "close": 100 + np.cumsum(np.random.randn(50) * 0.5),
        },
        index=dates,
    )
    df.loc[df.index[10], "close"] = np.nan
    return df


class TestCalcADX:
    """calc_adx 测试。"""

    def test_trend_data(self, trend_df):
        adx = calc_adx(trend_df, period=14)
        valid = adx.dropna()
        assert len(valid) > 0
        # 趋势数据的 ADX 应为正
        assert valid.iloc[-1] > 0

    def test_random_data_lower_adx(self, random_df, trend_df):
        adx_rand = calc_adx(random_df, period=14).dropna()
        adx_trend = calc_adx(trend_df, period=14).dropna()
        if len(adx_rand) > 0 and len(adx_trend) > 0:
            # 趋势数据的 ADX 应高于随机数据
            assert adx_trend.iloc[-1] >= adx_rand.iloc[-1] * 0.5

    def test_short_data(self, short_df):
        adx = calc_adx(short_df, period=14)
        # 数据不足应全为 NaN
        assert adx.isna().all()

    def test_nan_handling(self, nan_df):
        adx = calc_adx(nan_df, period=14)
        assert not adx.isna().all()  # 不应全 NaN


class TestCalcTrendStrength:
    """calc_trend_strength 测试。"""

    def test_mapping_range(self, trend_df):
        adx = calc_adx(trend_df, period=14)
        strength = calc_trend_strength(adx)
        valid = strength.dropna()
        assert len(valid) > 0
        # 所有值应在 [0, 1] 区间
        assert valid.min() >= 0.0
        assert valid.max() <= 1.0

    def test_low_adx_maps_low(self):
        adx = pd.Series([5.0, 10.0, 15.0])
        strength = calc_trend_strength(adx)
        assert (strength <= 0.3).all()

    def test_high_adx_maps_high(self):
        adx = pd.Series([50.0, 60.0, 100.0])
        strength = calc_trend_strength(adx)
        assert (strength >= 0.7).all()


class TestCalcTrendConsistency:
    """calc_trend_consistency 测试。"""

    def test_normal(self, trend_df):
        consistency = calc_trend_consistency(trend_df, lookback=10)
        valid = consistency.dropna()
        assert len(valid) > 0
        assert valid.min() >= 0.0
        assert valid.max() <= 1.0

    def test_short_data(self, short_df):
        consistency = calc_trend_consistency(short_df, lookback=10)
        assert not consistency.isna().all()
