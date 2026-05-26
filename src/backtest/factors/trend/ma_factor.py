"""
mozhi_platform.src.backtest.factors.trend.ma_factor — MaFactor

移动平均线（Moving Average）因子。
支持 SMA（简单移动平均）、EMA（指数移动平均）、WMA（加权移动平均）三种模式。

旧系统源：trend_strategy.py — _sma() / _ema() / ma_signal()
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
    "name": "ma",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "移动平均线：支持 SMA、EMA、WMA 三种模式",
    "category": "trend",
    "default_params": {
        "period": 20,
        "type": "sma",
    },
    "tags": ["trend", "moving_average"],
}


# ──────────────────────────────────────────────────────────────────────
# MaFactor
# ──────────────────────────────────────────────────────────────────────


class MaFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """移动平均线因子。

    支持三种移动平均计算模式：
    - ``sma``：简单移动平均（Simple Moving Average）
    - ``ema``：指数移动平均（Exponential Moving Average）
    - ``wma``：加权移动平均（Weighted Moving Average），权重 = 位置线性递减

    旧系统兼容：
    - SMA 计算逻辑与 ``trend_strategy._sma()`` 一致（滑动窗口和法）
    - EMA 计算逻辑与 ``trend_strategy._ema()`` 一致（alpha = 2/(period+1)）
    - WMA 为扩展实现（旧系统无 WMA，纯数学定义）

    Examples:
        >>> factor = MaFactor(params={"period": 10, "type": "sma"})
        >>> result = factor.compute(df)  # pd.Series
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.period = ctx.get_config("period", 20)
        self.ma_type = ctx.get_config("type", "sma").lower()

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """计算移动平均线。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame。

        Returns:
            pd.Series: MA 数值序列，索引与 ``df`` 对齐。
                       前 ``period-1`` 个值为 NaN（数据不足）。

        Raises:
            ValueError: ``ma_type`` 不是 ``sma`` / ``ema`` / ``wma`` 之一。
        """
        close = df["close"]
        period = self.params.get("period", 20)
        ma_type = self.params.get("type", "sma").lower()

        if ma_type == "sma":
            return close.rolling(window=period).mean()
        elif ma_type == "ema":
            # alpha = 2/(period+1)，与旧系统 trend_strategy._ema 一致
            return close.ewm(span=period, adjust=False).mean()
        elif ma_type == "wma":
            # 加权移动平均：权重线性递减，最新价格权重为 period
            def _wma(arr: np.ndarray) -> float:
                weights = np.arange(1, len(arr) + 1, dtype=float)
                return np.dot(arr, weights) / weights.sum()
            return close.rolling(window=period).apply(_wma, raw=True)
        else:
            raise ValueError(f"不支持的 MA 类型: '{ma_type}'，仅支持 sma/ema/wma")
