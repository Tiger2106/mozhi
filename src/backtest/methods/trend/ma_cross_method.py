"""
mozhi_platform.src.backtest.methods.trend.ma_cross_method — MaCrossMethod

双均线交叉策略（金叉/死叉）。
配置快慢均线周期后，generate_signal() 检测 MA_fast 与 MA_slow 的交叉生成信号。

旧系统源：trend_strategy.py — generate_ma_cross_signals()
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
    "name": "ma_cross",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "双均线交叉：MA_fast 上穿/下穿 MA_slow 生成 BUY/SELL 信号",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "ma_fast": 5,
        "ma_slow": 20,
    },
    "dependencies": ["ma"],
    "tags": ["trend", "ma_cross", "crossover"],
}


# ──────────────────────────────────────────────────────────────────────
# MaCrossMethod
# ──────────────────────────────────────────────────────────────────────


class MaCrossMethod(BaseMethod):
    METHOD_META = METHOD_META
    """双均线交叉信号方法。

    **信号逻辑**（与旧系统 ``trend_strategy.generate_ma_cross_signals`` 一致）：

    - MA_fast 上穿 MA_slow（金叉） → signal = 1（BUY）
    - MA_fast 下穿 MA_slow（死叉） → signal = -1（SELL）
    - 其他情况 → signal = 0（无操作）

    **默认参数**：
        - ``ma_fast``：快线周期（默认 5）
        - ``ma_slow``：慢线周期（默认 20）

    Examples:
        >>> method = MaCrossMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]  # {-1, 0, 1}
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.ma_fast: int = ctx.get_config("ma_fast", 5)
        self.ma_slow: int = ctx.get_config("ma_slow", 20)

        if self.ma_fast >= self.ma_slow:
            raise ValueError(
                f"ma_fast ({self.ma_fast}) 必须小于 ma_slow ({self.ma_slow})"
            )

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成 MA 金叉/死叉信号。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame，索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}，-1=死叉做空, 0=无操作, 1=金叉做多
                - ``ma_fast_val``: 快线值
                - ``ma_slow_val``: 慢线值

        Raises:
            ValueError: 如果必要列缺失或 ``ma_fast >= ma_slow``。
        """
        if "close" not in df.columns:
            raise ValueError("输入 DataFrame 必须包含 'close' 列")

        n = len(df)
        close = df["close"]

        # ── 1. 计算快慢 SMA ──────────────────────────────────────
        fast_ma = close.rolling(window=self.ma_fast).mean()
        slow_ma = close.rolling(window=self.ma_slow).mean()

        # ── 2. 检测交叉 ───────────────────────────────────────────
        first_valid = max(self.ma_fast, self.ma_slow) - 1

        signal: pd.Series = pd.Series(np.zeros(n, dtype=int), index=df.index)

        if first_valid >= n:
            result = pd.DataFrame(
                {"signal": signal, "ma_fast_val": fast_ma, "ma_slow_val": slow_ma},
                index=df.index,
            )
            return result

        # 初始状态
        prev_fast = fast_ma.iloc[first_valid]
        prev_slow = slow_ma.iloc[first_valid]
        if pd.notna(prev_fast) and pd.notna(prev_slow):
            prev_state = 1 if prev_fast > prev_slow else (-1 if prev_fast < prev_slow else 0)
        else:
            prev_state = 0

        for i in range(first_valid, n):
            cur_fast = fast_ma.iloc[i]
            cur_slow = slow_ma.iloc[i]

            if pd.isna(cur_fast) or pd.isna(cur_slow):
                continue

            cur_state = 1 if cur_fast > cur_slow else (-1 if cur_fast < cur_slow else 0)

            if cur_state == 1 and prev_state == -1:
                signal.iloc[i] = 1   # 金叉 → BUY
            elif cur_state == -1 and prev_state == 1:
                signal.iloc[i] = -1  # 死叉 → SELL

            prev_state = cur_state

        result = pd.DataFrame(
            {
                "signal": signal,
                "ma_fast_val": fast_ma,
                "ma_slow_val": slow_ma,
            },
            index=df.index,
        )
        return result
