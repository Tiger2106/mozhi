"""
mozhi_platform.src.backtest.methods.trend.bollinger_method — BollingerMethod

布林带策略（突破/回归信号）。
配置布林参数后，generate_signal() 检测价格与上轨/下轨/中轨的关系生成信号。

旧系统源：trend_strategy.py — generate_bollinger_signals()
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
    "name": "bollinger",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "布林带策略：价格突破上轨/下轨或回归中轨生成 BUY/SELL 信号",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "period": 20,
        "std_dev": 2.0,
    },
    "dependencies": ["bollinger"],
    "tags": ["trend", "bollinger", "volatility"],
}


# ──────────────────────────────────────────────────────────────────────
# BollingerMethod
# ──────────────────────────────────────────────────────────────────────


class BollingerMethod(BaseMethod):
    METHOD_META = METHOD_META
    """布林带信号方法。

    **信号逻辑**（与旧系统 ``trend_strategy.generate_bollinger_signals`` 一致）：

    布林带计算：
        - MIDDLE = SMA(close, period)
        - STD = 滚动标准差(close, period, ddof=0)
        - UPPER = MIDDLE + std_dev * STD
        - LOWER = MIDDLE - std_dev * STD

    信号规则（Breakout 策略）：
        - 价格从带内上穿上轨 → signal = 1（BUY，向上突破追涨）
        - 价格从带内下穿下轨 → signal = -1（SELL，向下突破追跌）
        - 价格从上轨回归中轨 → signal = -1（平多）
        - 价格从下轨回归中轨 → signal = 1（平空）

    **默认参数**：
        - ``period``：布林带周期（默认 20）
        - ``std_dev``：标准差倍数（默认 2.0）

    Examples:
        >>> method = BollingerMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.period: int = ctx.get_config("period", 20)
        self.std_dev: float = ctx.get_config("std_dev", 2.0)

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成布林带突破/回归信号。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame，索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}
                - ``upper``: 上轨值
                - ``middle``: 中轨值
                - ``lower``: 下轨值
                - ``bandwidth``: 相对带宽（(UPPER - LOWER) / MIDDLE）

        Raises:
            ValueError: 如果必要列缺失。
        """
        if "close" not in df.columns:
            raise ValueError("输入 DataFrame 必须包含 'close' 列")

        close = df["close"]
        n = len(df)

        # ── 1. 计算布林带 ─────────────────────────────────────────
        middle = close.rolling(window=self.period).mean()
        std = close.rolling(window=self.period).std(ddof=0)
        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std

        # ── 2. 带宽 ───────────────────────────────────────────────
        bandwidth = pd.Series(
            np.where(middle.notna() & (middle != 0),
                     (upper - lower) / middle, np.nan),
            index=df.index,
        )

        # ── 3. 检测突破 / 回归 ────────────────────────────────────
        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        first_valid = self.period - 1

        if first_valid < n:
            # 初始区域判定
            prev_close = close.iloc[first_valid]
            prev_upper = upper.iloc[first_valid]
            prev_lower = lower.iloc[first_valid]

            if pd.notna(prev_upper) and prev_close > prev_upper:
                prev_zone = 1
            elif pd.notna(prev_lower) and prev_close < prev_lower:
                prev_zone = -1
            else:
                prev_zone = 0

            for i in range(1, n):
                cur_close = close.iloc[i]
                cur_upper = upper.iloc[i]
                cur_lower = lower.iloc[i]

                if pd.isna(cur_upper) or pd.isna(cur_lower):
                    continue

                # 当前区域
                if cur_close > cur_upper:
                    cur_zone = 1
                elif cur_close < cur_lower:
                    cur_zone = -1
                else:
                    cur_zone = 0

                # 检测转换事件
                if prev_zone == 0 and cur_zone == 1:
                    signal.iloc[i] = 1   # 上穿上轨 → BUY
                elif prev_zone == 0 and cur_zone == -1:
                    signal.iloc[i] = -1  # 下穿下轨 → SELL
                elif prev_zone == 1 and cur_zone == 0:
                    signal.iloc[i] = -1  # 回归中轨 → 平多（SELL）
                elif prev_zone == -1 and cur_zone == 0:
                    signal.iloc[i] = 1   # 回归中轨 → 平空（BUY）

                prev_zone = cur_zone

        result = pd.DataFrame(
            {
                "signal": signal,
                "upper": upper,
                "middle": middle,
                "lower": lower,
                "bandwidth": bandwidth,
            },
            index=df.index,
        )
        return result
