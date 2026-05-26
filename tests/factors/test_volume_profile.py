"""Volume Profile 因子单元测试（R1 阶段一）"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.factors.volume.volume_profile_factor import (
    calc_volume_profile,
    calc_lvn,
)


@pytest.fixture
def normal_df():
    """120 行标准量价数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=120, freq="D")
    base_price = 100.0
    daily_ret = np.random.randn(120) * 0.015
    prices = base_price * np.exp(np.cumsum(daily_ret))
    return pd.DataFrame(
        {
            "high": prices * (1 + np.random.rand(120) * 0.012),
            "low": prices * (1 - np.random.rand(120) * 0.012),
            "close": prices,
            "volume": np.random.randint(1_000_000, 10_000_000, 120),
        },
        index=dates,
    )


@pytest.fixture
def flat_df():
    """价格波动极窄的数据（验证边界处理）。"""
    dates = pd.date_range("2025-01-01", periods=30, freq="D")
    return pd.DataFrame(
        {
            "high": [100.01] * 30,
            "low": [100.0] * 30,
            "close": [100.005] * 30,
            "volume": [1_000_000] * 30,
        },
        index=dates,
    )


@pytest.fixture
def short_df():
    """极短数据（1 行）。"""
    dates = pd.date_range("2025-01-01", periods=1, freq="D")
    return pd.DataFrame(
        {"high": [105], "low": [101], "close": [103], "volume": [2_000_000]},
        index=dates,
    )


class TestCalcVolumeProfile:
    """calc_volume_profile 测试。"""

    def test_normal(self, normal_df):
        vp = calc_volume_profile(normal_df)
        assert vp["poc"] > 0
        assert vp["vah"] >= vp["val"]  # 高值区 >= 低值区
        assert 0 < vp["value_area_pct"] <= 100

    def test_flat_prices(self, flat_df):
        vp = calc_volume_profile(flat_df)
        # 极窄波动不应报错
        assert isinstance(vp["poc"], float)

    def test_short_data(self, short_df):
        """单行数据应能正常处理。"""
        vp = calc_volume_profile(short_df)
        # 单行数据不影响正确输出
        assert isinstance(vp["poc"], float)


class TestCalcLVN:
    """calc_lvn 测试。"""

    def test_normal(self, normal_df):
        lvns = calc_lvn(normal_df)
        assert isinstance(lvns, list)
        # LVN 存在或为空都不应报错
        if lvns:
            lo, hi = lvns[0]
            assert lo < hi

    def test_flat_prices(self, flat_df):
        lvns = calc_lvn(flat_df)
        assert isinstance(lvns, list)

    def test_short_data(self, short_df):
        lvns = calc_lvn(short_df)
        assert isinstance(lvns, list)
        assert len(lvns) == 0
