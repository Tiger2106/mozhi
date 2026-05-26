"""
mozhi_platform.src.backtest.methods.momentum.kdj_method — KDJMethod

KDJ 穿越策略。
配置 KDJ 参数后，generate_signal() 检测 K 值与 D 值的穿越或超买/超卖生成信号。

旧系统源：reversal_strategy.py — _kdj() / generate_kdj_signals()
迁移日期：2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pandas as pd
import numpy as np

from backtest.methods.base import BaseMethod
from backtest.methods.manifest import METHOD_META as _BASE_METHOD_META

# ──────────────────────────────────────────────────────────────────────
# METHOD_META 协议常量
# ──────────────────────────────────────────────────────────────────────

METHOD_META = {
    "name": "kdj",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "KDJ 策略：K 值低于超卖阈值 → BUY，高于超买阈值 → SELL，K/D 穿越辅助",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "n": 9,
        "m1": 3,
        "m2": 3,
        "oversold": 20.0,
        "overbought": 80.0,
    },
    "dependencies": [],
    "tags": ["momentum", "kdj", "stochastic"],
}


# ──────────────────────────────────────────────────────────────────────
# KDJMethod
# ──────────────────────────────────────────────────────────────────────


class KDJMethod(BaseMethod):
    METHOD_META = METHOD_META
    """KDJ 信号方法。

    **信号逻辑**（与旧系统 ``reversal_strategy.kdj_signal`` 一致）：

    1. 计算 K/D/J 值：
        - RSV = (close - min(L, n)) / (max(H, n) - min(L, n)) * 100
        - K = (m1-1)/m1 * prev_K + RSV/m1
        - D = (m2-1)/m2 * prev_D + K/m2
        - J = 3K - 2D

    2. K < oversold → signal = 1（BUY，超卖）
    3. K > overbought → signal = -1（SELL，超买）
    4. 其他 → signal = 0

    **默认参数**：
        - ``n``：RSV 周期（默认 9）
        - ``m1``：K 平滑周期（默认 3）
        - ``m2``：D 平滑周期（默认 3）
        - ``oversold``：超卖阈值（默认 20.0）
        - ``overbought``：超买阈值（默认 80.0）

    Examples:
        >>> method = KDJMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.n: int = ctx.get_config("n", 9)
        self.m1: int = ctx.get_config("m1", 3)
        self.m2: int = ctx.get_config("m2", 3)
        self.oversold: float = ctx.get_config("oversold", 20.0)
        self.overbought: float = ctx.get_config("overbought", 80.0)

    @staticmethod
    def _compute_kdj(
        close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        n: int,
        m1: int,
        m2: int,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算 K/D/J 值。

        公式（与旧系统 ``reversal_strategy._kdj`` 一致）：
        - RSV = (close - min(L, n)) / (max(H, n) - min(L, n)) * 100
        - K = SMA(RSV, m1)
        - D = SMA(K, m2)
        - J = 3K - 2D

        Args:
            close: 收盘价序列。
            high: 最高价序列。
            low: 最低价序列。
            n: RSV 周期。
            m1: K 平滑周期。
            m2: D 平滑周期。

        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: (K, D, J)
        """
        # RSV 计算
        rolling_high = high.rolling(window=n).max()
        rolling_low = low.rolling(window=n).min()
        denominator = rolling_high - rolling_low
        rsv = pd.Series(
            np.where(denominator != 0,
                     100.0 * (close - rolling_low) / denominator,
                     50.0),
            index=close.index,
        )
        rsv[rsv.isna()] = 50.0

        # K = SMA(RSV, m1), D = SMA(K, m2)
        # 使用 Wilder 平滑（等价于 EMA alpha=1/m）
        k = rsv.ewm(alpha=1.0 / m1, adjust=False).mean()
        d = k.ewm(alpha=1.0 / m2, adjust=False).mean()
        j = 3.0 * k - 2.0 * d

        return k, d, j

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成 KDJ 信号。

        Args:
            df: 必须包含 ``close``、``high``、``low`` 列的 OHLCV DataFrame，
                索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}
                - ``K``: K 值
                - ``D``: D 值
                - ``J``: J 值
                - ``strength``: 信号强度 [0, 1]

        Raises:
            ValueError: 如果必要列缺失。
        """
        required = {"close", "high", "low"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"输入 DataFrame 缺少列: {missing}")

        n = len(df)

        K, D, J = self._compute_kdj(
            df["close"], df["high"], df["low"],
            self.n, self.m1, self.m2,
        )

        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        strength = pd.Series(np.zeros(n, dtype=float), index=df.index)

        for i in range(n):
            val = K.iloc[i]
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
                "K": K,
                "D": D,
                "J": J,
                "strength": strength,
            },
            index=df.index,
        )
        return result
