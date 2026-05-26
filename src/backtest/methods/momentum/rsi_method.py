"""
mozhi_platform.src.backtest.methods.momentum.rsi_method — RSIMethod

RSI 超买/超卖策略。
配置 RSI 参数和超买/超卖阈值后，generate_signal() 检测 RSI 值生成信号。

旧系统源：reversal_strategy.py — _rsi() / generate_rsi_signals()
迁移日期：2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import numpy as np

from backtest.methods.base import BaseMethod
from backtest.methods.manifest import METHOD_META as _BASE_METHOD_META

# ──────────────────────────────────────────────────────────────────────
# METHOD_META 协议常量
# ──────────────────────────────────────────────────────────────────────

METHOD_META = {
    "name": "rsi",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "RSI 策略：RSI 低于超卖阈值 → BUY，高于超买阈值 → SELL",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "period": 14,
        "oversold": 30.0,
        "overbought": 70.0,
    },
    "dependencies": [],
    "tags": ["momentum", "rsi", "overbought_oversold"],
}


# ──────────────────────────────────────────────────────────────────────
# RSIMethod
# ──────────────────────────────────────────────────────────────────────


class RSIMethod(BaseMethod):
    METHOD_META = METHOD_META
    """RSI 超买/超卖信号方法。

    **信号逻辑**（与旧系统 ``reversal_strategy.rsi_signal`` 一致）：

    1. 计算 RSI(period)：基于收盘价变化的平均涨幅 / 平均跌幅
    2. RSI < oversold → signal = 1（BUY，超卖）
    3. RSI > overbought → signal = -1（SELL，超买）
    4. 其他 → signal = 0

    信号强度 = 偏离阈值程度（归一化到 [0, 1]），返回作为 ``strength`` 列。

    **默认参数**：
        - ``period``：RSI 周期（默认 14）
        - ``oversold``：超卖阈值（默认 30.0）
        - ``overbought``：超买阈值（默认 70.0）

    Examples:
        >>> method = RSIMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.period: int = ctx.get_config("period", 14)
        self.oversold: float = ctx.get_config("oversold", 30.0)
        self.overbought: float = ctx.get_config("overbought", 70.0)

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
        """计算 RSI 指标（完全匹配旧系统 ``reversal_strategy._rsi``）。

        使用 Wilder 平滑法（SMA 种子 + 递归平滑），
        而非 pandas EWM（种子值不同会导致持续偏差）。
        """
        n = len(close)
        if n < period + 1:
            return pd.Series(np.nan, index=close.index)

        values = close.values.astype(float)
        deltas = np.diff(values)  # len = n-1
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.zeros(n)
        avg_loss = np.zeros(n)
        avg_gain[period] = gains[:period].mean()
        avg_loss[period] = losses[:period].mean()

        for i in range(period + 1, n):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

        rsi_vals = np.full(n, np.nan)
        for i in range(period, n):
            if avg_loss[i] == 0:
                rsi_vals[i] = 100.0 if avg_gain[i] > 0 else 50.0
            else:
                rs = avg_gain[i] / avg_loss[i]
                rsi_vals[i] = 100.0 - 100.0 / (1.0 + rs)

        return pd.Series(rsi_vals, index=close.index)

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成 RSI 超买/超卖信号。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame，索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}
                - ``rsi``: RSI 值
                - ``strength``: 信号强度 [0, 1]

        Raises:
            ValueError: 如果必要列缺失。
        """
        if "close" not in df.columns:
            raise ValueError("输入 DataFrame 必须包含 'close' 列")

        close = df["close"]
        n = len(df)

        rsi = self._compute_rsi(close, self.period)
        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        strength = pd.Series(np.zeros(n, dtype=float), index=df.index)

        for i in range(n):
            val = rsi.iloc[i]
            if pd.isna(val):
                continue

            if val < self.oversold:
                signal.iloc[i] = 1
                strength.iloc[i] = min(1.0, (self.oversold - val) / self.oversold)
            elif val > self.overbought:
                signal.iloc[i] = -1
                strength.iloc[i] = min(1.0, (val - self.overbought) / (100.0 - self.overbought))

        result = pd.DataFrame(
            {
                "signal": signal,
                "rsi": rsi,
                "strength": strength,
            },
            index=df.index,
        )
        return result
