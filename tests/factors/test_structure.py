"""Structure 因子单元测试（R1 阶段一）"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.factors.structure.structure_factor import (
    calc_support_resistance,
    calc_structure_quality,
)


@pytest.fixture
def wavy_df():
    """明显波峰波谷的结构化数据。"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    t = np.linspace(0, 4 * np.pi, 100)
    wave = np.sin(t) * 10 + 100  # 4 个完整正弦波
    return pd.DataFrame(
        {
            "high": wave + np.random.rand(100) * 2 + 1,
            "low": wave - np.random.rand(100) * 2 - 1,
            "close": wave + np.random.randn(100) * 0.5,
        },
        index=dates,
    )


@pytest.fixture
def flat_df():
    """价格极平的数据（无结构）。"""
    dates = pd.date_range("2025-01-01", periods=30, freq="D")
    return pd.DataFrame(
        {
            "high": [101] * 30,
            "low": [99] * 30,
            "close": [100] * 30,
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


class TestCalcSupportResistance:
    """calc_support_resistance 测试。"""

    def test_wavy_data(self, wavy_df):
        result = calc_support_resistance(wavy_df, lookback=100)
        assert "support" in result
        assert "resistance" in result
        assert "all_levels" in result
        # 正弦波应有支撑和阻力位
        total = len(result["support"]) + len(result["resistance"])
        assert total > 0, "正弦波数据应识别出支撑/阻力位"

    def test_flat_data(self, flat_df):
        result = calc_support_resistance(flat_df, lookback=30)
        # 平坦数据至少返回空列表
        assert isinstance(result["support"], list)

    def test_short_data(self, short_df):
        result = calc_support_resistance(short_df, lookback=5)
        assert isinstance(result["support"], list)


class TestCalcStructureQuality:
    """calc_structure_quality 测试。"""

    def test_wavy_data(self, wavy_df):
        quality = calc_structure_quality(wavy_df, lookback=100)
        assert 0 <= quality <= 1.0
        # 正弦波是有结构的数据，质量应 > 0.3
        assert quality > 0.3, f"正弦波数据结构完整度应为正，实际: {quality}"

    def test_flat_data(self, flat_df):
        quality = calc_structure_quality(flat_df, lookback=30)
        assert 0 <= quality <= 1.0

    def test_short_data(self, short_df):
        quality = calc_structure_quality(short_df, lookback=5)
        assert quality == 0.0  # 数据不足
