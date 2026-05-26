"""
mozhi_platform.src.backtest.factors.volume.obv_factor — OBVFactor

OBV（On-Balance Volume，能量潮）因子。
OBV 通过成交量累积反映资金流向，是量价先行指标。

全新实现：旧系统无 OBV 计算。
创建日期：2026-05-17
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from backtest.factors.base import BaseFactor

# ──────────────────────────────────────────────────────────────────────
# FACTOR_META 协议常量
# ──────────────────────────────────────────────────────────────────────

FACTOR_META = {
    "name": "obv",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "能量潮（On-Balance Volume）：通过成交量累积反映资金流向",
    "category": "volume",
    "default_params": {
        "signal_period": 20,
        "ma_type": "sma",
    },
    "tags": ["volume", "leading_indicator"],
}


# ──────────────────────────────────────────────────────────────────────
# OBVFactor
# ──────────────────────────────────────────────────────────────────────


class OBVFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """能量潮（OBV）因子。

    OBV 计算公式：
    1. 如果 ``close[t] > close[t-1]``：OBV[t] = OBV[t-1] + volume[t]
    2. 如果 ``close[t] < close[t-1]``：OBV[t] = OBV[t-1] - volume[t]
    3. 如果 ``close[t] == close[t-1]``：OBV[t] = OBV[t-1]

    ``compute()`` 返回以 ``obv`` / ``obv_signal`` 两列为列的 DataFrame：
    - ``obv``: OBV 累积值序列
    - ``obv_signal``: OBV 的移动平均信号线（用于判断趋势方向）

    Examples:
        >>> factor = OBVFactor(params={"signal_period": 14, "ma_type": "ema"})
        >>> result = factor.compute(df)  # pd.DataFrame with obv/obv_signal
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.signal_period = ctx.get_config("signal_period", 20)
        self.ma_type = ctx.get_config("ma_type", "sma")

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 OBV 及信号线。

        Args:
            df: 必须包含 ``close`` 和 ``volume`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含两列的 DataFrame，索引与 ``df`` 对齐：
                - ``obv``: OBV 累积值
                - ``obv_signal``: OBV 的移动平均信号线

        Raises:
            ValueError: OHLCV 数据不足（至少需要 2 根 K 线）。
        """
        close = df["close"].values
        volume = df["volume"].values
        n = len(df)

        if n < 2:
            raise ValueError(f"OBV 需要至少 2 根 K 线，当前 {n} 根")

        # ── 逐元素计算 OBV ─────────────────────────────────────────
        obv_arr = np.zeros(n, dtype=np.float64)
        for i in range(1, n):
            if close[i] > close[i - 1]:
                obv_arr[i] = obv_arr[i - 1] + volume[i]
            elif close[i] < close[i - 1]:
                obv_arr[i] = obv_arr[i - 1] - volume[i]
            else:
                obv_arr[i] = obv_arr[i - 1]

        obv_series = pd.Series(obv_arr, index=df.index, name="obv")

        # ── 信号线（移动平均） ─────────────────────────────────────
        signal_period = self.params.get("signal_period", 20)
        ma_type = self.params.get("ma_type", "sma").lower()

        if ma_type == "sma":
            obv_signal = obv_series.rolling(window=signal_period).mean()
        elif ma_type == "ema":
            obv_signal = obv_series.ewm(span=signal_period, adjust=False).mean()
        else:
            raise ValueError(f"不支持的 ma_type: '{ma_type}'，仅支持 sma/ema")

        return pd.DataFrame(
            {"obv": obv_series, "obv_signal": obv_signal},
            index=df.index,
        )
