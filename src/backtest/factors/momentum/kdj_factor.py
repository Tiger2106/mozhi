"""
mozhi_platform.src.backtest.factors.momentum.kdj_factor — KdjFactor

KDJ 随机指标因子。
包装 KDJMethod 的 K/D/J 计算核心，返回纯 K/D/J 指标列。

旧系统源：kdj_method.py — KDJMethod._compute_kdj()
迁移日期：2026-05-18
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from backtest.factors.base import BaseFactor
from backtest.methods.momentum.kdj_method import KDJMethod

# ──────────────────────────────────────────────────────────────────────
# FACTOR_META 协议常量
# ──────────────────────────────────────────────────────────────────────

FACTOR_META = {
    "name": "kdj",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "KDJ 随机指标：K 值、D 值、J 值三线",
    "category": "momentum",
    "default_params": {
        "n": 9,
        "m1": 3,
        "m2": 3,
    },
    "tags": ["momentum", "kdj", "stochastic"],
}


# ──────────────────────────────────────────────────────────────────────
# KdjFactor
# ──────────────────────────────────────────────────────────────────────


class KdjFactor(BaseFactor):
    FACTOR_META = FACTOR_META
    """KDJ 随机指标因子。

    **计算逻辑**：
    1. RSV = (close - min(L, n)) / (max(H, n) - min(L, n)) * 100
    2. K = SMA(RSV, m1)
    3. D = SMA(K, m2)
    4. J = 3K - 2D

    内部委托给 ``KDJMethod._compute_kdj()``，确保与信号层计算结果一致。

    ``compute()`` 返回一个包含 ``K``、``D``、``J`` 三列的 DataFrame。

    Examples:
        >>> factor = KdjFactor(params={"n": 9, "m1": 3, "m2": 3})
        >>> result = factor.compute(df)  # pd.DataFrame with K/D/J columns
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: 配置上下文，需提供 ``get_config(key, default)`` 方法。
        """
        self.n = ctx.get_config("n", 9)
        self.m1 = ctx.get_config("m1", 3)
        self.m2 = ctx.get_config("m2", 3)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 KDJ 指标。

        Args:
            df: 必须包含 ``close``、``high``、``low`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含 ``K``、``D``、``J`` 三列的 DataFrame，索引与 ``df`` 对齐。

        Raises:
            ValueError: 如果必要列缺失。
        """
        required = {"close", "high", "low"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"输入 DataFrame 缺少列: {missing}")

        n = self.params.get("n", 9)
        m1 = self.params.get("m1", 3)
        m2 = self.params.get("m2", 3)

        K, D, J = KDJMethod._compute_kdj(
            df["close"], df["high"], df["low"],
            n, m1, m2,
        )

        return pd.DataFrame(
            {"K": K, "D": D, "J": J},
            index=df.index,
        )
