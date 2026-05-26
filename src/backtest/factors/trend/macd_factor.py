"""
mozhi_platform.src.backtest.factors.trend.macd_factor — MACDFactor

MACD（Moving Average Convergence Divergence）因子。
计算 DIF / DEA / MACD 柱三条线。

旧系统源：trend_strategy.py — _ema() / generate_macd_signals()
迁移日期：2026-05-17
"""

from __future__ import annotations

import pandas as pd

from backtest.factors.base import BaseFactor

# ──────────────────────────────────────────────────────────────────────
# FACTOR_META 协议常量
# ──────────────────────────────────────────────────────────────────────

FACTOR_META = {
    "name": "macd",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "MACD 指标：计算 DIF、DEA、MACD 柱三条线",
    "category": "trend",
    "default_params": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
    },
    "tags": ["trend", "macd", "momentum"],
}


# ──────────────────────────────────────────────────────────────────────
# MACDFactor
# ──────────────────────────────────────────────────────────────────────


class MACDFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """MACD 指标因子。

    计算逻辑（与旧系统 ``trend_strategy.generate_macd_signals`` 一致）：
    1. DIF = EMA(close, fast_period) - EMA(close, slow_period)
    2. DEA = EMA(DIF, signal_period)
    3. MACD 柱 = (DIF - DEA) * 2

    ``compute()`` 返回以 ``dif`` / ``dea`` / ``macd_hist`` 三列为列的 DataFrame，
    便于下游 method 直接引用。

    Examples:
        >>> factor = MACDFactor(params={"fast_period": 12, "slow_period": 26})
        >>> result = factor.compute(df)  # pd.DataFrame with dif/dea/macd_hist
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.fast_period = ctx.get_config("fast_period", 12)
        self.slow_period = ctx.get_config("slow_period", 26)
        self.signal_period = ctx.get_config("signal_period", 9)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 MACD 指标。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含三列的 DataFrame，索引与 ``df`` 对齐：
                - ``dif``: DIF 快线（EMA_fast - EMA_slow）
                - ``dea``: DEA 信号线（EMA of DIF）
                - ``macd_hist``: MACD 柱状图（(DIF - DEA) * 2）
        """
        close = df["close"]
        fast = self.params.get("fast_period", 12)
        slow = self.params.get("slow_period", 26)
        signal = self.params.get("signal_period", 9)

        # ── 1. 计算两条 EMA ──────────────────────────────────────
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()

        # ── 2. DIF = EMA_fast - EMA_slow ─────────────────────────
        dif = ema_fast - ema_slow

        # ── 3. DEA = EMA(DIF, signal_period) ─────────────────────
        dea = dif.ewm(span=signal, adjust=False).mean()

        # ── 4. MACD 柱 = (DIF - DEA) * 2 ─────────────────────────
        macd_hist = (dif - dea) * 2

        return pd.DataFrame(
            {"dif": dif, "dea": dea, "macd_hist": macd_hist},
            index=df.index,
        )
