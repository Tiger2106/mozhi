"""
mozhi_platform.src.backtest.factors.volatility.bollinger_factor — BollingerFactor

布林带（Bollinger Bands）因子。
计算上轨、中轨、下轨及带宽，用于识别超买超卖和波动率变化。

旧系统源：trend_strategy.py — _rolling_stddev() / generate_bollinger_signals()
迁移日期：2026-05-17
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from backtest.factors.base import BaseFactor

# ──────────────────────────────────────────────────────────────────────
# FACTOR_META 协议常量
# ──────────────────────────────────────────────────────────────────────

FACTOR_META = {
    "name": "bollinger",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "布林带（Bollinger Bands）：上轨/中轨/下轨/带宽，超买超卖 & 波动率指示",
    "category": "volatility",
    "default_params": {
        "period": 20,
        "std_dev": 2.0,
    },
    "tags": ["volatility", "bollinger", "overbought_oversold"],
}


# ──────────────────────────────────────────────────────────────────────
# BollingerFactor
# ──────────────────────────────────────────────────────────────────────


class BollingerFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """布林带因子。

    计算逻辑（与旧系统 ``trend_strategy.generate_bollinger_signals`` 一致）：

    **布林带计算**：
    - MIDDLE = SMA(close, period)
    - STD = 滚动标准差(close, period, ddof=0)
    - UPPER = MIDDLE + std_dev * STD
    - LOWER = MIDDLE - std_dev * STD
    - BANDWIDTH = (UPPER - LOWER) / MIDDLE（带宽相对值）

    **标准差计算**：使用总体标准差（ddof=0），与旧系统 ``_rolling_stddev`` 一致。

    ``compute()`` 返回包含 ``upper`` / ``middle`` / ``lower`` / ``bandwidth``
    四列的 DataFrame。

    Examples:
        >>> factor = BollingerFactor(params={"period": 20, "std_dev": 2.0})
        >>> result = factor.compute(df)  # pd.DataFrame with upper/middle/lower/bandwidth
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.period = ctx.get_config("period", 20)
        self.std_dev = ctx.get_config("std_dev", 2.0)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算布林带。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含四列的 DataFrame，索引与 ``df`` 对齐：
                - ``upper``: 上轨（MIDDLE + std_dev * STD）
                - ``middle``: 中轨（SMA）
                - ``lower``: 下轨（MIDDLE - std_dev * STD）
                - ``bandwidth``: 相对带宽（(UPPER - LOWER) / MIDDLE）

        Raises:
            ValueError: OHLCV 数据不足 period 根 K 线。
        """
        close = df["close"]
        period = self.params.get("period", 20)
        std_dev = self.params.get("std_dev", 2.0)

        # ── 1. 中轨（SMA）───────────与旧系统 _sma 一致 ──────────
        middle = close.rolling(window=period).mean()

        # ── 2. 滚动标准差（ddof=0 总体标准差，与旧系统一致）─────
        std = close.rolling(window=period).std(ddof=0)

        # ── 3. 上下轨 ─────────────────────────────────────────────
        upper = middle + std_dev * std
        lower = middle - std_dev * std

        # ── 4. 带宽 ───────────────────────────────────────────────
        bandwidth = pd.Series(
            np.where(middle.notna() & (middle != 0),
                     (upper - lower) / middle, np.nan),
            index=df.index,
        )

        return pd.DataFrame(
            {
                "upper": upper,
                "middle": middle,
                "lower": lower,
                "bandwidth": bandwidth,
            },
            index=df.index,
        )
