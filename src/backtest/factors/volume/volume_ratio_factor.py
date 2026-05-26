"""
mozhi_platform.src.backtest.factors.volume.volume_ratio_factor — VolumeRatioFactor

量比（Volume Ratio）因子。
计算当日成交量相对 N 日均量的倍数，衡量成交量相对活跃程度。

旧系统源：volume_strategy.py — volume_ratio_signal()
迁移日期：2026-05-18
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from backtest.factors.base import BaseFactor

# ──────────────────────────────────────────────────────────────────────
# FACTOR_META 协议常量
# ──────────────────────────────────────────────────────────────────────

FACTOR_META = {
    "name": "volume_ratio",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "量比：当日成交量 / N 日均量，支持 5 日、20 日两档",
    "category": "volume",
    "default_params": {
        "windows": [5, 20],
    },
    "tags": ["volume", "volume_ratio"],
}


# ──────────────────────────────────────────────────────────────────────
# VolumeRatioFactor
# ──────────────────────────────────────────────────────────────────────


class VolumeRatioFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """量比因子。

    **计算逻辑**：
    1. 计算 N 日移动平均成交量
    2. 量比 = 当日成交量 / N 日均量

    ``compute()`` 返回一个 DataFrame，包含 ``volume_ratio_5`` 和 ``volume_ratio_20`` 两列。

    旧系统兼容：
    - 5 日均量逻辑与 ``volume_strategy._avg_volume(5)`` 一致
    - 量比值 > 1 表示放量，< 1 表示缩量

    Examples:
        >>> factor = VolumeRatioFactor(params={"windows": [5, 20]})
        >>> result = factor.compute(df)  # pd.DataFrame
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.windows = ctx.get_config("windows", [5, 20])

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算量比因子。

        Args:
            df: 必须包含 ``close``、``volume`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``volume_ratio_5``: 5 日量比
                - ``volume_ratio_20``: 20 日量比

        Raises:
            ValueError: 如果必要列缺失。
        """
        required = {"close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"输入 DataFrame 缺少列: {missing}")

        volume = df["volume"]
        windows = self.params.get("windows", [5, 20])

        result = pd.DataFrame(index=df.index)
        for w in windows:
            avg_vol = volume.rolling(window=w, min_periods=1).mean()
            # 避免除以 0
            mask = avg_vol > 0
            col = pd.Series(np.nan, index=df.index)
            col[mask] = volume[mask] / avg_vol[mask]
            result[f"volume_ratio_{w}"] = col

        return result
