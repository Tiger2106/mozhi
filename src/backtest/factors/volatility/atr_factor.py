"""
mozhi_platform.src.backtest.factors.volatility.atr_factor — ATRFactor

ATR（Average True Range，平均真实波幅）因子。
衡量市场波动性，常用于止损设置和波动率过滤器。

旧系统源：grid_strategy.py — _true_range() / _atr()
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
    "name": "atr",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "平均真实波幅（Average True Range）：TR 滚动均值，波动率度量",
    "category": "volatility",
    "default_params": {
        "period": 14,
        "use_ema": True,
    },
    "tags": ["volatility", "stop_loss", "volatility_filter"],
}


# ──────────────────────────────────────────────────────────────────────
# ATRFactor
# ──────────────────────────────────────────────────────────────────────


class ATRFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """平均真实波幅（ATR）因子。

    计算逻辑（与旧系统 ``grid_strategy._true_range`` / ``_atr`` 一致）：

    **真实波幅 TR**：
    ``TR = max(high - low, |high - prev_close|, |low - prev_close|)``

    **ATR 计算**：
    - 第一个 ATR = SMA(TR, period)
    - 后续 ATR = alpha * TR[t] + (1 - alpha) * ATR[t-1]  (Wilder 平滑)
    - 其中 alpha = 1 / period（Wilder 方法）或 2 / (period + 1)（标准 EMA）

    ``use_ema=True`` 时使用标准 EMA（alpha = 2/(period+1)），
    ``use_ema=False`` 时使用 Wilder 平滑（alpha = 1/period）。

    ``compute()`` 返回以 ``tr`` 和 ``atr`` 两列为列的 DataFrame。

    Examples:
        >>> factor = ATRFactor(params={"period": 14, "use_ema": True})
        >>> result = factor.compute(df)  # pd.DataFrame with tr/atr
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.period = ctx.get_config("period", 14)
        self.use_ema = ctx.get_config("use_ema", True)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 TR 及 ATR。

        Args:
            df: 必须包含 ``high`` / ``low`` / ``close`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含两列的 DataFrame，索引与 ``df`` 对齐：
                - ``tr``: 真实波幅（True Range），第一根 K 线为 NaN
                - ``atr``: 平均真实波幅（前 period 根为 NaN）

        Raises:
            ValueError: OHLCV 数据不足（至少需要 2 根 K 线）。
        """
        high = df["high"].to_numpy(dtype=np.float64)
        low = df["low"].to_numpy(dtype=np.float64)
        close = df["close"].to_numpy(dtype=np.float64)
        n = len(df)

        if n < 2:
            raise ValueError(f"ATR 需要至少 2 根 K 线，当前 {n} 根")

        period = self.params.get("period", 14)
        use_ema = self.params.get("use_ema", True)

        # ── 1. 逐元素计算 TR（与旧系统 _true_range 一致）─────────
        tr_arr = np.full(n, np.nan, dtype=np.float64)
        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr_arr[i] = max(hl, hc, lc)

        # ── 2. 计算 ATR ───────────────────────────────────────────
        atr_arr = np.full(n, np.nan, dtype=np.float64)
        tr_valid = tr_arr[1:]  # 从索引 1 开始
        m = len(tr_valid)

        if m < period:
            return pd.DataFrame(
                {"tr": pd.Series(tr_arr, index=df.index),
                 "atr": pd.Series(atr_arr, index=df.index)},
                index=df.index,
            )

        # 初始 ATR = SMA(TR, period)
        initial_atr = float(np.mean(tr_valid[:period]))
        atr_arr[period] = initial_atr  # ATR[period] 对应 tr_arr[period]

        # 后续 ATR：平滑计算
        if use_ema:
            alpha = 2.0 / (period + 1)  # 标准 EMA
        else:
            alpha = 1.0 / period  # Wilder 平滑

        for i in range(period, m):
            atr_val = alpha * tr_valid[i] + (1.0 - alpha) * (atr_arr[i] if not np.isnan(atr_arr[i]) else initial_atr)
            atr_arr[i + 1] = atr_val

        return pd.DataFrame(
            {"tr": pd.Series(tr_arr, index=df.index),
             "atr": pd.Series(atr_arr, index=df.index)},
            index=df.index,
        )
