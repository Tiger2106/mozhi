"""
mozhi_platform.src.backtest.methods.trend.volume_profile_method — VolumeProfileMethod

成交量分布分析方法。
基于成交量在价格区间上的累积分布生成信号（高点量 vs 低点量对比）。

旧系统源：无（全新实现）
创建日期：2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd
import numpy as np

from backtest.methods.base import BaseMethod
from backtest.methods.manifest import METHOD_META as _BASE_METHOD_META

# ──────────────────────────────────────────────────────────────────────
# METHOD_META 协议常量
# ──────────────────────────────────────────────────────────────────────

METHOD_META = {
    "name": "volume_profile",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "成交量分布分析：比较高价区与低价区成交量累积，识别支撑/阻力区域",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "lookback": 20,
        "n_zones": 5,
        "volume_ratio_threshold": 1.5,
    },
    "dependencies": [],
    "tags": ["trend", "volume", "support_resistance"],
}


# ──────────────────────────────────────────────────────────────────────
# VolumeProfileMethod
# ──────────────────────────────────────────────────────────────────────


class VolumeProfileMethod(BaseMethod):
    METHOD_META = METHOD_META
    """成交量分布分析信号方法（全新实现）。

    **核心逻辑**：

    1. 在每个分析窗口内（lookback 根 Bar），将价格区间等分成 ``n_zones`` 个区域。
    2. 分别累积高价格区（上半区）和低价格区（下半区）的成交量。
    3. 计算高低区成交量比值。
    4. 信号规则：
        - 低区累积量 / 高区累积量 > ``volume_ratio_threshold`` → signal = 1（BUY，支撑强）
        - 高区累积量 / 低区累积量 > ``volume_ratio_threshold`` → signal = -1（SELL，阻力强）
        - 其他 → signal = 0

    **默认参数**：
        - ``lookback``：分析窗口（默认 20）
        - ``n_zones``：价格分区数（默认 5）
        - ``volume_ratio_threshold``：成交量比值阈值（默认 1.5）

    Examples:
        >>> method = VolumeProfileMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.lookback: int = ctx.get_config("lookback", 20)
        self.n_zones: int = ctx.get_config("n_zones", 5)
        self.volume_ratio_threshold: float = ctx.get_config("volume_ratio_threshold", 1.5)

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成成交量分布信号。

        Args:
            df: 必须包含 ``close``、``high``、``low``、``volume`` 列的 OHLCV DataFrame，
                索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}
                - ``volume_ratio``: 低区成交量 / 高区成交量比值
                - ``high_zone_vol``: 高价区累积成交量
                - ``low_zone_vol``: 低价区累积成交量
                - ``vp_support``: 支撑位价格（低区均价）
                - ``vp_resistance``: 阻力位价格（高区均价）

        Raises:
            ValueError: 如果必要列缺失。
        """
        required = {"close", "high", "low", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"输入 DataFrame 缺少列: {missing}")

        n = len(df)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        volume_ratio = pd.Series(np.nan, index=df.index)
        high_zone_vol = pd.Series(np.nan, index=df.index)
        low_zone_vol = pd.Series(np.nan, index=df.index)
        vp_support = pd.Series(np.nan, index=df.index)
        vp_resistance = pd.Series(np.nan, index=df.index)

        for i in range(self.lookback - 1, n):
            window_high = high.iloc[i - self.lookback + 1:i + 1]
            window_low = low.iloc[i - self.lookback + 1:i + 1]
            window_close = close.iloc[i - self.lookback + 1:i + 1]
            window_volume = volume.iloc[i - self.lookback + 1:i + 1]

            price_min = window_low.min()
            price_max = window_high.max()

            if price_max <= price_min:
                continue

            zone_size = (price_max - price_min) / self.n_zones

            # 将窗口价格-成交量分配到各区域
            zone_volumes = np.zeros(self.n_zones)
            zone_prices = np.zeros(self.n_zones)

            for j in range(len(window_close)):
                p = window_close.iloc[j]
                v = window_volume.iloc[j]
                zone_idx = min(int((p - price_min) / zone_size), self.n_zones - 1)
                zone_volumes[zone_idx] += v
                zone_prices[zone_idx] += p * v  # 加权和

            # 上半区（高价格） vs 下半区（低价格）
            mid_zone = self.n_zones // 2
            high_vol = zone_volumes[mid_zone:].sum()
            low_vol = zone_volumes[:mid_zone].sum()

            # 均价
            total_vol_high = zone_volumes[mid_zone:].sum()
            total_vol_low = zone_volumes[:mid_zone].sum()

            high_price_avg = (
                zone_prices[mid_zone:].sum() / total_vol_high
                if total_vol_high > 0 else np.nan
            )
            low_price_avg = (
                zone_prices[:mid_zone].sum() / total_vol_low
                if total_vol_low > 0 else np.nan
            )

            high_zone_vol.iloc[i] = high_vol
            low_zone_vol.iloc[i] = low_vol

            # 比值（低/高）
            if high_vol > 0:
                ratio = low_vol / high_vol
                volume_ratio.iloc[i] = ratio
            else:
                volume_ratio.iloc[i] = np.inf if low_vol > 0 else 1.0

            # 信号判定
            if low_vol > high_vol * self.volume_ratio_threshold:
                signal.iloc[i] = 1  # 低区量大 → 支撑强 → BUY
            elif high_vol > low_vol * self.volume_ratio_threshold:
                signal.iloc[i] = -1  # 高区量大 → 阻力强 → SELL

            if not np.isnan(low_price_avg):
                vp_support.iloc[i] = low_price_avg
            if not np.isnan(high_price_avg):
                vp_resistance.iloc[i] = high_price_avg

        result = pd.DataFrame(
            {
                "signal": signal,
                "volume_ratio": volume_ratio,
                "high_zone_vol": high_zone_vol,
                "low_zone_vol": low_zone_vol,
                "vp_support": vp_support,
                "vp_resistance": vp_resistance,
            },
            index=df.index,
        )
        return result
