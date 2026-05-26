"""
mozhi_platform.src.backtest.methods.trend.macd_method — MACDMethod

MACD 策略（DIF-DEA 穿越信号）。
配置 MACD 参数后，generate_signal() 检测 DIF 与 DEA 的穿越生成信号。

旧系统源：trend_strategy.py — generate_macd_signals()
迁移日期：2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import numpy as np
from typing import List, Optional

from backtest.methods.base import BaseMethod
from backtest.methods.manifest import METHOD_META as _BASE_METHOD_META

# ──────────────────────────────────────────────────────────────────────
# METHOD_META 协议常量
# ──────────────────────────────────────────────────────────────────────

METHOD_META = {
    "name": "macd",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "MACD 策略：DIF 上穿/下穿 DEA 生成 BUY/SELL 信号（含零轴穿越）",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
    },
    "dependencies": ["macd"],
    "tags": ["trend", "macd", "momentum"],
}


# ──────────────────────────────────────────────────────────────────────
# MACDMethod
# ──────────────────────────────────────────────────────────────────────


class MACDMethod(BaseMethod):
    METHOD_META = METHOD_META
    """MACD 信号方法。

    **信号逻辑**（与旧系统 ``trend_strategy.generate_macd_signals`` 一致）：

    1. 计算 DIF = EMA(close, fast) - EMA(close, slow)
    2. 计算 DEA = EMA(DIF, signal)
    3. DIF 上穿 DEA → signal = 1（BUY）
    4. DIF 下穿 DEA → signal = -1（SELL）
    5. 其余 → signal = 0

    **默认参数**：
        - ``fast_period``：MACD 快线周期（默认 12）
        - ``slow_period``：MACD 慢线周期（默认 26）
        - ``signal_period``：DEA 信号线周期（默认 9）

    Examples:
        >>> method = MACDMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]
    """

    @staticmethod
    def _ema_compat(values: pd.Series, period: int) -> pd.Series:
        """兼容旧系统的 EMA 计算（用 SMA(period) 作种子值）。

        旧系统 ``_ema()`` 在 ``period - 1`` 位置初始化 SMA，
        而非从 ``values[0]`` 开始递归。此方法匹配旧系统行为。
        """
        n = len(values)
        result = np.full(n, np.nan)
        alpha = 2.0 / (period + 1)

        if n < period:
            return pd.Series(result, index=values.index)

        # SMA 种子
        ema = float(values.iloc[:period].mean())
        result[period - 1] = ema

        for i in range(period, n):
            ema = alpha * float(values.iloc[i]) + (1 - alpha) * ema
            result[i] = ema

        return pd.Series(result, index=values.index)

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.fast_period: int = ctx.get_config("fast_period", 12)
        self.slow_period: int = ctx.get_config("slow_period", 26)
        self.signal_period: int = ctx.get_config("signal_period", 9)

    def _ema_fast(self, close: pd.Series) -> pd.Series:
        return self._ema_compat(close, self.fast_period)

    def _ema_slow(self, close: pd.Series) -> pd.Series:
        return self._ema_compat(close, self.slow_period)

    def _ema_dea(self, dif: pd.Series) -> pd.Series:
        return self._ema_compat(dif, self.signal_period)

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成 MACD DIF-DEA 穿越信号。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame，索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}
                - ``dif``: DIF 快线值
                - ``dea``: DEA 信号线值
                - ``macd_hist``: MACD 柱状图（(DIF - DEA) * 2）

        Raises:
            ValueError: 如果必要列缺失。
        """
        if "close" not in df.columns:
            raise ValueError("输入 DataFrame 必须包含 'close' 列")

        close = df["close"]
        n = len(df)

        # ── 1. 计算两条 EMA（兼容旧系统 SMA 种子）──────────────
        ema_fast = self._ema_fast(close)
        ema_slow = self._ema_slow(close)

        # ── 2. DIF = EMA_fast - EMA_slow ─────────────────────────
        dif = ema_fast - ema_slow

        # ── 3. DEA = EMA(valid DIF, signal_period)，映射回索引 ──
        # 旧系统逻辑：仅对有效 DIF 值序列计算 DEA，再映射回原索引
        valid_mask = dif.notna()
        valid_dif = dif[valid_mask]
        dea = pd.Series(np.nan, index=dif.index)
        if len(valid_dif) > 0:
            dea_raw = self._ema_dea(valid_dif)
            dea.loc[valid_mask] = dea_raw.values

        # ── 4. MACD 柱 = (DIF - DEA) * 2 ─────────────────────────
        macd_hist = (dif - dea) * 2

        # ── 5. 检测 DIF 穿越 DEA ─────────────────────────────────
        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)

        first_valid = max(self.fast_period, self.slow_period) - 1

        if first_valid < n:
            prev_dif = dif.iloc[first_valid]
            prev_dea = dea.iloc[first_valid]
            if pd.notna(prev_dif) and pd.notna(prev_dea):
                prev_state = 1 if prev_dif > prev_dea else (-1 if prev_dif < prev_dea else 0)
            else:
                prev_state = 0

            for i in range(first_valid, n):
                cur_dif = dif.iloc[i]
                cur_dea = dea.iloc[i]

                if pd.isna(cur_dif) or pd.isna(cur_dea):
                    continue

                cur_state = 1 if cur_dif > cur_dea else (-1 if cur_dif < cur_dea else 0)

                if cur_state == 1 and prev_state == -1:
                    signal.iloc[i] = 1   # DIF 上穿 DEA → BUY
                elif cur_state == -1 and prev_state == 1:
                    signal.iloc[i] = -1  # DIF 下穿 DEA → SELL

                prev_state = cur_state

        result = pd.DataFrame(
            {
                "signal": signal,
                "dif": dif,
                "dea": dea,
                "macd_hist": macd_hist,
            },
            index=df.index,
        )
        return result
