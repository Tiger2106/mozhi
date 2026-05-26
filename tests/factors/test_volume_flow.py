"""Volume Flow 因子单元测试（R1 阶段一）"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.factors.volume.volume_flow_factor import (
    calc_smart_money_score,
    calc_volume_trend,
    calc_volume_ratio,
)


@pytest.fixture
def normal_df():
    """100 行标准量价数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    # 创建量价正相关 → 聪明钱正分
    base = 100.0
    trend = np.linspace(0, 15, 100)
    prices = base + trend + np.random.randn(100) * 1.0
    volumes = 5_000_000 + trend * 100_000 + np.random.randint(-200_000, 200_000, 100)
    return pd.DataFrame(
        {"close": prices, "volume": volumes.astype(float)},
        index=dates,
    )


@pytest.fixture
def reverse_df():
    """量价反向数据（价涨量缩 → 负分）。"""
    np.random.seed(7)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    prices = 100.0 + np.linspace(0, 10, 100)
    volumes = 5_000_000 - np.linspace(0, 2_000_000, 100)
    vol_noise = np.random.randint(-100_000, 100_000, 100)
    return pd.DataFrame(
        {"close": prices + np.random.randn(100) * 2, "volume": (volumes + vol_noise).astype(float)},
        index=dates,
    )


@pytest.fixture
def short_df():
    """极短数据（3 行）。"""
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {"close": [100, 101, 102], "volume": [1_000_000, 2_000_000, 3_000_000]},
        index=dates,
    )


class TestCalcSmartMoneyScore:
    """calc_smart_money_score 测试。"""

    def test_normal_uptrend(self, normal_df):
        score = calc_smart_money_score(normal_df, lookback=10)
        mean_score = score.iloc[-20:].mean()
        # 量价正相关的趋势数据最后一截应 > 0
        assert mean_score >= -0.1

    def test_reverse_signal(self, reverse_df):
        score = calc_smart_money_score(reverse_df, lookback=10)
        # 部分时段应为负值
        negative_count = (score < 0).sum()
        assert negative_count > 0

    def test_short_data(self, short_df):
        score = calc_smart_money_score(short_df, lookback=10)
        assert len(score) == 3
        assert not score.isna().all()

    def test_range_constraint(self, normal_df):
        score = calc_smart_money_score(normal_df)
        # 所有值应在 [-1, 1]
        assert score.min() >= -1.0
        assert score.max() <= 1.0


class TestCalcVolumeTrend:
    """calc_volume_trend 测试。"""

    def test_normal(self, normal_df):
        trend = calc_volume_trend(normal_df, period=20)
        assert len(trend) == 100
        assert trend.min() >= -1.0
        assert trend.max() <= 1.0

    def test_short_data(self, short_df):
        trend = calc_volume_trend(short_df, period=20)
        assert len(trend) == 3


class TestCalcVolumeRatio:
    """calc_volume_ratio 测试。"""

    def test_normal(self, normal_df):
        ratio = calc_volume_ratio(normal_df)
        assert len(ratio) == 100
        assert ratio.min() > 0  # 应为正数

    def test_short_data(self, short_df):
        ratio = calc_volume_ratio(short_df, short_period=2, long_period=5)
        assert len(ratio) == 3
