"""
mozhi_platform.src.backtest.factors.momentum.rsi_factor — RsiFactor

RSI（Relative Strength Index）因子。
包装 RSIMethod 的 RSI 计算核心，返回纯 RSI 指标列。

旧系统源：rsi_method.py — RSIMethod._compute_rsi()
迁移日期：2026-05-18
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from backtest.factors.base import BaseFactor
from backtest.methods.momentum.rsi_method import RSIMethod

# ──────────────────────────────────────────────────────────────────────
# FACTOR_META 协议常量
# ──────────────────────────────────────────────────────────────────────

FACTOR_META = {
    "name": "rsi",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "RSI 指标：基于收盘价变化的相对强弱指数",
    "category": "momentum",
    "default_params": {
        "period": 14,
    },
    "tags": ["momentum", "rsi", "overbought_oversold"],
}


# ──────────────────────────────────────────────────────────────────────
# RsiFactor
# ──────────────────────────────────────────────────────────────────────


class RsiFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """RSI 指标因子。

    **计算逻辑**：
    1. 计算 RSI(period)：基于收盘价变化的 Wilder 平滑法
    2. 输出纯 RSI 数值列

    内部委托给 ``RSIMethod._compute_rsi()``，确保与信号层计算结果一致。

    ``compute()`` 返回一个包含 ``rsi`` 列的 DataFrame。

    Examples:
        >>> factor = RsiFactor(params={"period": 14})
        >>> result = factor.compute(df)  # pd.DataFrame with 'rsi' column
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.period = ctx.get_config("period", 14)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 RSI 指标。

        Args:
            df: 必须包含 ``close`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含 ``rsi`` 列的 DataFrame，索引与 ``df`` 对齐。

        Raises:
            ValueError: 如果必要列缺失。
        """
        if "close" not in df.columns:
            raise ValueError("输入 DataFrame 必须包含 'close' 列")

        period = self.params.get("period", 14)
        rsi = RSIMethod._compute_rsi(df["close"], period)

        return pd.DataFrame({"rsi": rsi}, index=df.index)
