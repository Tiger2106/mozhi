"""
mozhi_platform.src.backtest.methods.reversal.reversal_method — ReversalMethod

反转策略（带 CooldownTracker 冷却器）。
组合 RSI/KDJ/BIAS 多信号投票，入场后 N 根 Bar 内不反向开仓。

旧系统源：reversal_strategy.py — CooldownTracker / voted_reversal_signal
迁移日期：2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from backtest.methods.base import BaseMethod
from backtest.methods.manifest import METHOD_META as _BASE_METHOD_META

# ──────────────────────────────────────────────────────────────────────
# METHOD_META 协议常量
# ──────────────────────────────────────────────────────────────────────

METHOD_META = {
    "name": "reversal",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "反转策略：RSI/KDJ/BIAS 多信号投票融合 + CooldownTracker 冷却保护",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "rsi_period": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "kdj_n": 9,
        "kdj_oversold": 20.0,
        "kdj_overbought": 80.0,
        "bias_period": 20,
        "bias_buy": -0.05,
        "bias_sell": 0.05,
        "cooldown_bars": 5,
        "min_votes": 2,
    },
    "dependencies": [],
    "tags": ["reversal", "voting", "cooldown"],
}


# ──────────────────────────────────────────────────────────────────────
# CooldownTracker — 冷却期管理器
# ──────────────────────────────────────────────────────────────────────


class CooldownTracker:
    """追踪冷却期，入场后 N 根 Bar 内不允许同方向反向开仓。

    与旧系统 ``reversal_strategy.CooldownTracker`` 逻辑一致。
    """

    def __init__(self, cooldown_bars: int = 5):
        """初始化冷却期管理器。

        Args:
            cooldown_bars: 冷却期长度（以 Bar 为单位）。
        """
        self.cooldown_bars: int = cooldown_bars
        self._last_buy_bar: Dict[str, int] = {}
        self._last_sell_bar: Dict[str, int] = {}

    def can_buy(self, symbol: str, current_bar: int) -> bool:
        """检查是否允许买入。

        Args:
            symbol: 标的代码。
            current_bar: 当前 Bar 索引。

        Returns:
            bool: 允许买入返回 True。
        """
        last = self._last_buy_bar.get(symbol, -self.cooldown_bars)
        return (current_bar - last) >= self.cooldown_bars

    def can_sell(self, symbol: str, current_bar: int) -> bool:
        """检查是否允许卖出。

        Args:
            symbol: 标的代码。
            current_bar: 当前 Bar 索引。

        Returns:
            bool: 允许卖出返回 True。
        """
        last = self._last_sell_bar.get(symbol, -self.cooldown_bars)
        return (current_bar - last) >= self.cooldown_bars

    def record_buy(self, symbol: str, current_bar: int) -> None:
        """记录买入操作。

        Args:
            symbol: 标的代码。
            current_bar: 当前 Bar 索引。
        """
        self._last_buy_bar[symbol] = current_bar

    def record_sell(self, symbol: str, current_bar: int) -> None:
        """记录卖出操作。

        Args:
            symbol: 标的代码。
            current_bar: 当前 Bar 索引。
        """
        self._last_sell_bar[symbol] = current_bar

    def reset(self, symbol: str) -> None:
        """重置指定标的的冷却记录。

        Args:
            symbol: 标的代码。
        """
        self._last_buy_bar.pop(symbol, None)
        self._last_sell_bar.pop(symbol, None)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "cooldown_bars": self.cooldown_bars,
            "last_buy_bar": dict(self._last_buy_bar),
            "last_sell_bar": dict(self._last_sell_bar),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CooldownTracker":
        """从字典反序列化。"""
        tracker = cls(cooldown_bars=data.get("cooldown_bars", 5))
        tracker._last_buy_bar = dict(data.get("last_buy_bar", {}))
        tracker._last_sell_bar = dict(data.get("last_sell_bar", {}))
        return tracker


# ──────────────────────────────────────────────────────────────────────
# 内部信号生成函数（与 reversal_strategy 逻辑一致）
# ──────────────────────────────────────────────────────────────────────


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    """计算 RSI 值（与旧系统 ``_rsi()`` 一致）。"""
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)

    avg_gain = gains.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def _compute_kdj(
    close: pd.Series, high: pd.Series, low: pd.Series,
    n: int, m1: int, m2: int,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """计算 K/D/J 值（与旧系统 ``_kdj()`` 一致）。"""
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

    k = rsv.ewm(alpha=1.0 / m1, adjust=False).mean()
    d = k.ewm(alpha=1.0 / m2, adjust=False).mean()
    j = 3.0 * k - 2.0 * d
    return k, d, j


def _compute_bias(close: pd.Series, period: int) -> pd.Series:
    """计算乖离率（与旧系统 ``bias_signal()`` 一致）。"""
    ma = close.rolling(window=period).mean()
    return (close - ma) / ma.replace(0, np.nan)


# ──────────────────────────────────────────────────────────────────────
# ReversalMethod
# ──────────────────────────────────────────────────────────────────────


class ReversalMethod(BaseMethod):
    METHOD_META = METHOD_META
    """反转策略信号方法（带 CooldownTracker 冷却器）。

    **核心逻辑**（与旧系统 ``reversal_strategy.voted_reversal_signal`` 一致）：

    1. 分别计算 RSI / KDJ / BIAS 三个子信号：
        - RSI 信号：RSI < oversold → BUY，RSI > overbought → SELL
        - KDJ 信号：K < oversold → BUY，K > overbought → SELL
        - BIAS 信号：bias < buy_thr → BUY，bias > sell_thr → SELL

    2. **投票融合**：
        - BUY 票数 >= ``min_votes`` 且 > SELL 票数 → signal = 1
        - SELL 票数 >= ``min_votes`` 且 > BUY 票数 → signal = -1
        - 其他 → signal = 0

    3. **冷却保护**（CooldownTracker）：
        - BUY 后 cooldown_bars 根 Bar 内不再产生 BUY 信号
        - SELL 后 cooldown_bars 根 Bar 内不再产生 SELL 信号
        - ``setup()`` 调用时传入 ``symbol`` 用于冷却判定

    **默认参数**：
        - RSI：period=14, oversold=30, overbought=70
        - KDJ：n=9, oversold=20, overbought=80
        - BIAS：period=20, buy=-5%, sell=+5%
        - cooldown_bars=5, min_votes=2

    Examples:
        >>> method = ReversalMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result[["signal", "rsi_signal", "kdj_signal", "bias_signal", "votes"]]
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
                  需包含 ``symbol`` 字段用于冷却器判定。
        """
        # ── RSI 参数 ──────────────────────────────────────────
        self.rsi_period: int = ctx.get_config("rsi_period", 14)
        self.rsi_oversold: float = ctx.get_config("rsi_oversold", 30.0)
        self.rsi_overbought: float = ctx.get_config("rsi_overbought", 70.0)

        # ── KDJ 参数 ──────────────────────────────────────────
        self.kdj_n: int = ctx.get_config("kdj_n", 9)
        self.kdj_oversold: float = ctx.get_config("kdj_oversold", 20.0)
        self.kdj_overbought: float = ctx.get_config("kdj_overbought", 80.0)

        # ── BIAS 参数 ─────────────────────────────────────────
        self.bias_period: int = ctx.get_config("bias_period", 20)
        self.bias_buy: float = ctx.get_config("bias_buy", -0.05)
        self.bias_sell: float = ctx.get_config("bias_sell", 0.05)

        # ── 投票 & 冷却参数 ──────────────────────────────────
        self.cooldown_bars: int = ctx.get_config("cooldown_bars", 5)
        self.min_votes: int = ctx.get_config("min_votes", 2)

        # ── 冷却器 & 标的 ─────────────────────────────────────
        self._cooldown_tracker = CooldownTracker(cooldown_bars=self.cooldown_bars)
        self._symbol: str = getattr(ctx, "symbol", "DEFAULT")

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成反转多信号投票结果。

        Args:
            df: 必须包含 ``close``、``high``、``low`` 列的 OHLCV DataFrame，
                索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1} — 多信号投票融合结果（经冷却器过滤）
                - ``rsi_signal``: {-1, 0, 1} — RSI 子信号
                - ``kdj_signal``: {-1, 0, 1} — KDJ 子信号
                - ``bias_signal``: {-1, 0, 1} — BIAS 子信号
                - ``votes``: 投票数（正=BUY票, 负=SELL票）
                - ``strength``: 平均信号强度 [0, 1]

        Raises:
            ValueError: 如果必要列缺失。
        """
        required = {"close", "high", "low"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"输入 DataFrame 缺少列: {missing}")

        close = df["close"]
        high = df["high"]
        low = df["low"]
        n = len(df)

        # ── 1. 计算子信号 ──────────────────────────────────────
        rsi_vals = _compute_rsi(close, self.rsi_period)
        k, d, j = _compute_kdj(close, high, low, self.kdj_n, 3, 3)
        bias_vals = _compute_bias(close, self.bias_period)

        rsi_signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        kdj_signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        bias_signal = pd.Series(np.zeros(n, dtype=int), index=df.index)

        rsi_strength = pd.Series(np.zeros(n, dtype=float), index=df.index)
        kdj_strength = pd.Series(np.zeros(n, dtype=float), index=df.index)
        bias_strength = pd.Series(np.zeros(n, dtype=float), index=df.index)

        for i in range(n):
            # RSI
            r = rsi_vals.iloc[i]
            if not pd.isna(r):
                if r < self.rsi_oversold:
                    rsi_signal.iloc[i] = 1
                    rsi_strength.iloc[i] = min(1.0, (self.rsi_oversold - r) / self.rsi_oversold)
                elif r > self.rsi_overbought:
                    rsi_signal.iloc[i] = -1
                    rsi_strength.iloc[i] = min(1.0, (r - self.rsi_overbought) / (100.0 - self.rsi_overbought))

            # KDJ (使用 K 值)
            k_val = k.iloc[i]
            if not pd.isna(k_val):
                if k_val < self.kdj_oversold:
                    kdj_signal.iloc[i] = 1
                    kdj_strength.iloc[i] = min(1.0, (self.kdj_oversold - k_val) / self.kdj_oversold)
                elif k_val > self.kdj_overbought:
                    kdj_signal.iloc[i] = -1
                    kdj_strength.iloc[i] = min(1.0, (k_val - self.kdj_overbought) / (100.0 - self.kdj_overbought))

            # BIAS
            b = bias_vals.iloc[i]
            if not pd.isna(b):
                if b < self.bias_buy:
                    bias_signal.iloc[i] = 1
                    bias_strength.iloc[i] = min(1.0, (self.bias_buy - b) / max(abs(self.bias_buy), 0.001))
                elif b > self.bias_sell:
                    bias_signal.iloc[i] = -1
                    bias_strength.iloc[i] = min(1.0, (b - self.bias_sell) / max(self.bias_sell, 0.001))

        # ── 2. 投票融合 + 冷却器过滤 ──────────────────────────
        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        votes = pd.Series(np.zeros(n, dtype=int), index=df.index)
        strength = pd.Series(np.zeros(n, dtype=float), index=df.index)

        for i in range(n):
            buy_votes = 0
            sell_votes = 0
            total_strength = 0.0

            for sub_sig, sub_str in [
                (rsi_signal.iloc[i], rsi_strength.iloc[i]),
                (kdj_signal.iloc[i], kdj_strength.iloc[i]),
                (bias_signal.iloc[i], bias_strength.iloc[i]),
            ]:
                if sub_sig > 0:
                    buy_votes += 1
                    total_strength += sub_str
                elif sub_sig < 0:
                    sell_votes += 1
                    total_strength += sub_str

            # 原始投票
            raw_signal = 0
            if buy_votes >= self.min_votes and buy_votes > sell_votes:
                raw_signal = 1
            elif sell_votes >= self.min_votes and sell_votes > buy_votes:
                raw_signal = -1

            # 冷却器过滤
            if raw_signal == 1 and self._cooldown_tracker.can_buy(self._symbol, i):
                signal.iloc[i] = 1
                self._cooldown_tracker.record_buy(self._symbol, i)
            elif raw_signal == -1 and self._cooldown_tracker.can_sell(self._symbol, i):
                signal.iloc[i] = -1
                self._cooldown_tracker.record_sell(self._symbol, i)

            votes.iloc[i] = buy_votes - sell_votes
            strength.iloc[i] = total_strength / 3.0

        result = pd.DataFrame(
            {
                "signal": signal,
                "rsi_signal": rsi_signal,
                "kdj_signal": kdj_signal,
                "bias_signal": bias_signal,
                "votes": votes,
                "strength": strength,
            },
            index=df.index,
        )
        return result
