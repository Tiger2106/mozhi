"""VWAP 因子单元测试（R1 阶段一）"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.factors.volume.vwap_factor import (
    calc_vwap,
    calc_vwap_deviation,
    calc_multi_vwap,
    calc_vwap_band,
)


@pytest.fixture
def normal_df():
    """10 行标准量价数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
    return pd.DataFrame(
        {
            "high": np.random.uniform(102, 108, 10),
            "low": np.random.uniform(98, 102, 10),
            "close": np.random.uniform(100, 106, 10),
            "volume": np.random.randint(1_000_000, 5_000_000, 10),
        },
        index=dates,
    )


@pytest.fixture
def nan_df():
    """包含 NaN 的数据。"""
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {
            "high": np.random.uniform(102, 108, 10),
            "low": np.random.uniform(98, 102, 10),
            "close": np.random.uniform(100, 106, 10),
            "volume": np.random.randint(1_000_000, 5_000_000, 10),
        },
        index=dates,
    )
    df.loc[df.index[3], "volume"] = np.nan
    return df


@pytest.fixture
def short_df():
    """极短数据（3 行）。"""
    dates = pd.date_range("2025-01-04", periods=3, freq="D")
    return pd.DataFrame(
        {
            "high": [105, 106, 107],
            "low": [101, 102, 103],
            "close": [103, 104, 105],
            "volume": [2_000_000, 3_000_000, 4_000_000],
        },
        index=dates,
    )


class TestCalcVWAP:
    """calc_vwap 测试。"""

    def test_normal(self, normal_df):
        vwap = calc_vwap(normal_df)
        assert len(vwap) == 10
        assert vwap.isna().sum() == 0  # 所有值非空（cumsum）
        assert vwap.iloc[-1] > 0  # 最终值 > 0

    def test_nan_handling(self, nan_df):
        vwap = calc_vwap(nan_df)
        assert not vwap.isna().all()  # 不应全为 NaN

    def test_short_data(self, short_df):
        vwap = calc_vwap(short_df)
        assert len(vwap) == 3
        assert vwap.isna().sum() == 0


class TestCalcVWAPDeviation:
    """calc_vwap_deviation 测试。"""

    def test_normal(self, normal_df):
        dev = calc_vwap_deviation(normal_df)
        assert len(dev) == 10
        # 偏离度应为合理的百分比值
        assert all(abs(v) < 10 for v in dev.dropna())

    def test_precomputed_vwap(self, normal_df):
        vwap = calc_vwap(normal_df)
        df = normal_df.copy()
        df["my_vwap"] = vwap
        dev = calc_vwap_deviation(df, vwap_column="my_vwap")
        assert len(dev) == 10

    def test_short_data(self, short_df):
        dev = calc_vwap_deviation(short_df)
        assert len(dev) == 3


class TestCalcMultiVWAP:
    """calc_multi_vwap 测试。"""

    def test_default_windows(self, normal_df):
        result = calc_multi_vwap(normal_df)
        assert "vwap_5" in result
        assert "vwap_10" in result
        assert "vwap_20" in result

    def test_custom_windows(self, normal_df):
        result = calc_multi_vwap(normal_df, windows=[3])
        assert "vwap_3" in result
        assert len(result["vwap_3"]) == 10


class TestCalcVWAPBand:
    """calc_vwap_band 测试。"""

    def test_default_deviations(self, normal_df):
        result = calc_vwap_band(normal_df)
        assert "vwap" in result
        assert "vwap_upper_1" in result
        assert "vwap_lower_1" in result
        assert "vwap_upper_2" in result

    def test_order_consistency(self, normal_df):
        result = calc_vwap_band(normal_df)
        # upper ≥ vwap ≥ lower
        assert (result["vwap_upper_1"] >= result["vwap"]).all()
        assert (result["vwap_lower_1"] <= result["vwap"]).all()
