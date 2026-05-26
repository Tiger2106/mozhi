"""
mozhi_platform.src.backtest.methods.momentum.bias_method — BiasMethod

BIAS 乖离率策略。
配置乖离率阈值后，generate_signal() 检测价格偏离均线的程度生成信号。

旧系统源：reversal_strategy.py — bias_signal() / generate_bias_signals()
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
    "name": "bias",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "BIAS 乖离率策略：价格偏离均线过大 → 超卖 BUY / 超买 SELL",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "ma_period": 20,
        "bias_buy": -0.05,
        "bias_sell": 0.05,
    },
    "dependencies": ["ma"],
    "tags": ["momentum", "bias", "deviation"],
}


# ──────────────────────────────────────────────────────────────────────
# BiasMethod
# ──────────────────────────────────────────────────────────────────────


class BiasMethod(BaseMethod):
    METHOD_META = METHOD_META
    """BIAS 乖离率信号方法。

    **信号逻辑**（与旧系统 ``reversal_strategy.bias_signal`` 一致）：

    1. 计算 MA(close, ma_period)
    2. BIAS = (close - MA) / MA
    3. BIAS < bias_buy（负乖离大，价格远低于均线） → signal = 1（BUY，超卖）
    4. BIAS > bias_sell（正乖离大，价格远高于均线） → signal = -1（SELL，超买）
    5. 其他 → signal = 0

    **默认参数**：
        - ``ma_period``：均线周期（默认 20）
        - ``bias_buy``：买入乖离阈值（默认 -0.05，即 -5%）
        - ``bias_sell``：卖出乖离阈值（默认 0.05，即 +5%）

    Examples:
        >>> method = BiasMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.ma_period: int = ctx.get_config("ma_period", 20)
        self.bias_buy: float = ctx.get_config("bias_buy", -0.05)
        self.bias_sell: float = ctx.get_config("bias_sell", 0.05)

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成 BIAS 乖离率信号。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame，索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}
                - ``bias``: 乖离率值
                - ``ma``: 均线值
                - ``strength``: 信号强度 [0, 1]

        Raises:
            ValueError: 如果必要列缺失。
        """
        if "close" not in df.columns:
            raise ValueError("输入 DataFrame 必须包含 'close' 列")

        close = df["close"]
        n = len(df)

        # ── 1. 计算 MA 和乖离率 ──────────────────────────────────
        ma = close.rolling(window=self.ma_period).mean()
        bias = (close - ma) / ma.replace(0, np.nan)

        # ── 2. 生成信号 ──────────────────────────────────────────
        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        strength = pd.Series(np.zeros(n, dtype=float), index=df.index)

        for i in range(n):
            b = bias.iloc[i]
            if pd.isna(b):
                continue

            if b < self.bias_buy:
                signal.iloc[i] = 1
                strength.iloc[i] = min(1.0, (self.bias_buy - b) / max(abs(self.bias_buy), 0.001))
            elif b > self.bias_sell:
                signal.iloc[i] = -1
                strength.iloc[i] = min(1.0, (b - self.bias_sell) / max(self.bias_sell, 0.001))

        result = pd.DataFrame(
            {
                "signal": signal,
                "bias": bias,
                "ma": ma,
                "strength": strength,
            },
            index=df.index,
        )
        return result
