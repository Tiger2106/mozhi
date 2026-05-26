"""
反转信号模块
提供 RSI / KDJ / 布林带反转 / 乖离率 / 多规则投票 / 冷却期 6种信号及工具
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class Signal:
    action: Literal["BUY", "SELL", "HOLD"]
    strength: float  # 0.0~1.0


# ─────────────────────────────────────────────
# 内部工具函数
# ─────────────────────────────────────────────
def _ema(prices: np.ndarray, window: int) -> np.ndarray:
    if len(prices) < window:
        return np.array([])
    alpha = 2.0 / (window + 1)
    ema = np.zeros(len(prices))
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i - 1]
    return ema


def _rsi(prices: np.ndarray, window: int = 14) -> np.ndarray:
    """返回与 prices 等长的 RSI 数组（window 之前的元素为 nan）"""
    if len(prices) < window + 1:
        return np.array([])
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.zeros(len(prices))
    avg_loss = np.zeros(len(prices))
    avg_gain[window] = gains[:window].mean()
    avg_loss[window] = losses[:window].mean()

    for i in range(window + 1, len(prices)):
        avg_gain[i] = (avg_gain[i - 1] * (window - 1) + gains[i - 1]) / window
        avg_loss[i] = (avg_loss[i - 1] * (window - 1) + losses[i - 1]) / window

    rsi_vals = np.full(len(prices), np.nan)
    for i in range(window, len(prices)):
        if avg_loss[i] == 0:
            rsi_vals[i] = 100.0 if avg_gain[i] > 0 else 50.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi_vals[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi_vals


def _kdj(prices: np.ndarray,
         high: Optional[np.ndarray] = None,
         low: Optional[np.ndarray] = None,
         n: int = 9,
         m1: int = 3,
         m2: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 (K, D, J) 数组，与 prices 等长，n 之前的元素为 nan"""
    if len(prices) < n:
        return np.array([]), np.array([]), np.array([])
    if high is None:
        high = prices.copy()
    if low is None:
        low = prices.copy()

    RSV = np.full(len(prices), np.nan)
    for i in range(n - 1, len(prices)):
        win_high = high[i - n + 1:i + 1].max()
        win_low = low[i - n + 1:i + 1].min()
        if win_high == win_low:
            RSV[i] = 50.0
        else:
            RSV[i] = 100.0 * (prices[i] - win_low) / (win_high - win_low)

    K = np.full(len(prices), np.nan)
    D = np.full(len(prices), np.nan)
    K[n - 1] = 50.0
    D[n - 1] = 50.0
    for i in range(n, len(prices)):
        K[i] = (m1 - 1) / m1 * K[i - 1] + RSV[i] / m1
        D[i] = (m2 - 1) / m2 * D[i - 1] + K[i] / m2
    J = 3 * K - 2 * D
    return K, D, J


# ─────────────────────────────────────────────
# 1. RSI 信号
# ─────────────────────────────────────────────
def rsi_signal(prices: np.ndarray,
               window: int = 14,
               buy_thr: float = 30.0,
               sell_thr: float = 70.0) -> Signal:
    """
    RSI < buy_thr  → BUY  (超卖)
    RSI > sell_thr → SELL (超买)
    30~70          → HOLD
    """
    if len(prices) < window + 1:
        return Signal("HOLD", 0.0)
    rsi_vals = _rsi(prices, window)
    # 找到最后一个有效（非 nan）RSI
    valid_mask = ~np.isnan(rsi_vals)
    if not np.any(valid_mask):
        return Signal("HOLD", 0.0)
    curr_rsi = rsi_vals[valid_mask][-1]
    if curr_rsi < buy_thr:
        strength = (buy_thr - curr_rsi) / buy_thr
        return Signal("BUY", min(max(strength, 0.0), 1.0))
    if curr_rsi > sell_thr:
        strength = (curr_rsi - sell_thr) / (100.0 - sell_thr)
        return Signal("SELL", min(max(strength, 0.0), 1.0))
    return Signal("HOLD", 0.0)


# ─────────────────────────────────────────────
# 2. KDJ 信号
# ─────────────────────────────────────────────
def kdj_signal(prices: np.ndarray,
               n: int = 9,
               m1: int = 3,
               m2: int = 3,
               buy_thr: float = 20.0,
               sell_thr: float = 80.0) -> Signal:
    """
    K < buy_thr  → BUY  (超卖)
    K > sell_thr → SELL (超买)
    """
    if len(prices) < n:
        return Signal("HOLD", 0.0)
    K, D, J = _kdj(prices, n=n, m1=m1, m2=m2)
    valid_mask = ~np.isnan(K)
    if not np.any(valid_mask):
        return Signal("HOLD", 0.0)
    curr_K = K[valid_mask][-1]
    if curr_K < buy_thr:
        strength = (buy_thr - curr_K) / buy_thr
        return Signal("BUY", min(max(strength, 0.0), 1.0))
    if curr_K > sell_thr:
        strength = (curr_K - sell_thr) / (100.0 - sell_thr)
        return Signal("SELL", min(max(strength, 0.0), 1.0))
    return Signal("HOLD", 0.0)


# ─────────────────────────────────────────────
# 3. 布林带反转信号
# ─────────────────────────────────────────────
def bollinger_reversal_signal(prices: np.ndarray,
                              window: int = 20,
                              num_std: float = 2.0) -> Signal:
    """
    价格跌破下轨 → BUY  (均值回归)
    价格突破上轨 → SELL (均值回归)
    """
    if len(prices) < window:
        return Signal("HOLD", 0.0)
    ma = np.convolve(prices, np.ones(window) / window, mode="valid")
    std_arr = np.array([prices[i:i + window].std() for i in range(len(ma))])
    upper = ma + num_std * std_arr
    lower = ma - num_std * std_arr

    if len(ma) < 2:
        return Signal("HOLD", 0.0)
    # prices[-2] 对应 ma[-2]，prices[-1] 对应 ma[-1]
    prev_p, curr_p = prices[-2], prices[-1]
    prev_u, curr_u = upper[-2], upper[-1]
    prev_l, curr_l = lower[-2], lower[-1]

    # 跌破下轨 → BUY
    if prev_p >= prev_l and curr_p < curr_l:
        return Signal("BUY", 1.0)
    # 突破上轨 → SELL
    if prev_p <= prev_u and curr_p > curr_u:
        return Signal("SELL", 1.0)
    return Signal("HOLD", 0.0)


# ─────────────────────────────────────────────
# 4. 乖离率信号
# ─────────────────────────────────────────────
def bias_signal(prices: np.ndarray,
                window: int = 20,
                buy_thr: float = -5.0,
                sell_thr: float = 5.0) -> Signal:
    """
    bias < buy_thr  (负乖离大) → BUY
    bias > sell_thr (正乖离大) → SELL
    """
    if len(prices) < window:
        return Signal("HOLD", 0.0)
    ma = np.convolve(prices, np.ones(window) / window, mode="valid")
    if len(ma) == 0:
        return Signal("HOLD", 0.0)
    curr_ma = ma[-1]
    if curr_ma == 0:
        return Signal("HOLD", 0.0)
    bias = (prices[-1] - curr_ma) / curr_ma * 100.0

    if bias < buy_thr:
        strength = (buy_thr - bias) / abs(buy_thr)
        return Signal("BUY", min(max(strength, 0.0), 1.0))
    if bias > sell_thr:
        strength = (bias - sell_thr) / sell_thr
        return Signal("SELL", min(max(strength, 0.0), 1.0))
    return Signal("HOLD", 0.0)


# ─────────────────────────────────────────────
# 5. 多规则投票
# ─────────────────────────────────────────────
def multi_vote(signals: list[Signal],
               threshold: int = 2,
               weights: Optional[list[float]] = None) -> Signal:
    """
    K 个规则一致才执行（默认 threshold=2，即至少2个 BUY 才发 BUY）
    weights 可选，按顺序对信号加权。
    """
    if not signals:
        return Signal("HOLD", 0.0)
    n = len(signals)
    if weights is None:
        weights = [1.0] * n
    if len(weights) != n:
        raise ValueError("signals 与 weights 长度必须一致")

    buy_score = sum(s.strength * w for s, w in zip(signals, weights) if s.action == "BUY")
    sell_score = sum(s.strength * w for s, w in zip(signals, weights) if s.action == "SELL")

    buy_count = sum(1 for s in signals if s.action == "BUY")
    sell_count = sum(1 for s in signals if s.action == "SELL")

    # 至少 threshold 个 BUY 且 BUY score 占优才发 BUY
    if buy_count >= threshold and buy_score > sell_score:
        return Signal("BUY", buy_score / (buy_score + sell_score + 1e-10))
    # 至少 threshold 个 SELL 且 SELL score 占优才发 SELL
    if sell_count >= threshold and sell_score > buy_score:
        return Signal("SELL", sell_score / (buy_score + sell_score + 1e-10))
    return Signal("HOLD", 0.0)


# ─────────────────────────────────────────────
# 6. 冷却期追踪器
# ─────────────────────────────────────────────
class CooldownTracker:
    """追踪每个品种的冷却期，触发后 N 日内不重复开仓"""

    def __init__(self, cooldown_bars: int = 5):
        self.cooldown_bars = cooldown_bars
        self._last_buy_bar: dict[str, int] = {}
        self._last_sell_bar: dict[str, int] = {}

    def can_buy(self, symbol: str, current_bar: int) -> bool:
        last = self._last_buy_bar.get(symbol, -self.cooldown_bars)
        return (current_bar - last) >= self.cooldown_bars

    def can_sell(self, symbol: str, current_bar: int) -> bool:
        last = self._last_sell_bar.get(symbol, -self.cooldown_bars)
        return (current_bar - last) >= self.cooldown_bars

    def record_buy(self, symbol: str, current_bar: int) -> None:
        self._last_buy_bar[symbol] = current_bar

    def record_sell(self, symbol: str, current_bar: int) -> None:
        self._last_sell_bar[symbol] = current_bar

    def reset(self, symbol: str) -> None:
        self._last_buy_bar.pop(symbol, None)
        self._last_sell_bar.pop(symbol, None)

    def remaining_cooldown_buy(self, symbol: str, current_bar: int) -> int:
        last = self._last_buy_bar.get(symbol, -1)
        remaining = self.cooldown_bars - (current_bar - last)
        return max(0, remaining)

    def remaining_cooldown_sell(self, symbol: str, current_bar: int) -> int:
        last = self._last_sell_bar.get(symbol, -1)
        remaining = self.cooldown_bars - (current_bar - last)
        return max(0, remaining)


# ═════════════════════════════════════════════════════════
# 以下为 run_reversal.py 所需的批量信号生成 + ReversalCooler
# ═════════════════════════════════════════════════════════


def generate_rsi_signals(
    bars: list, period: int = 14, oversold: float = 30.0, overbought: float = 70.0
) -> list[dict]:
    """
    批量生成 RSI 反转信号。

    bars 为 Bar 列表（有 .date / .close 属性）。
    返回 [{"date": ..., "symbol": ..., "signal": 1/0/-1, "strength": float}, ...]
    """
    # Deal with both Bar objects and dict-like objects
    closes = np.array([float(b.close) for b in bars])
    rsi_vals = _rsi(closes, period)
    signals: list[dict] = []
    for i, bar in enumerate(bars):
        sig_val = 0
        strength = 0.0
        if not np.isnan(rsi_vals[i]):
            if rsi_vals[i] < oversold:
                sig_val = 1
                strength = min(1.0, (oversold - rsi_vals[i]) / oversold)
            elif rsi_vals[i] > overbought:
                sig_val = -1
                strength = min(1.0, (rsi_vals[i] - overbought) / (100.0 - overbought))
        signals.append({
            "date": str(bar.date),
            "symbol": str(bar.symbol) if hasattr(bar, 'symbol') else "601857",
            "signal": sig_val,
            "strength": round(strength, 4),
        })
    return signals


def generate_kdj_signals(
    bars: list, period: int = 9, k_buy: float = 20.0, k_sell: float = 80.0
) -> list[dict]:
    """批量生成 KDJ 反转信号。"""
    closes = np.array([float(b.close) for b in bars])
    highs = np.array([float(b.high) for b in bars])
    lows = np.array([float(b.low) for b in bars])
    K, D, J = _kdj(closes, high=highs, low=lows, n=period)
    signals: list[dict] = []
    for i, bar in enumerate(bars):
        sig_val = 0
        strength = 0.0
        if not np.isnan(K[i]):
            if K[i] < k_buy:
                sig_val = 1
                strength = min(1.0, (k_buy - K[i]) / k_buy)
            elif K[i] > k_sell:
                sig_val = -1
                strength = min(1.0, (K[i] - k_sell) / (100.0 - k_sell))
        signals.append({
            "date": str(bar.date),
            "symbol": str(bar.symbol) if hasattr(bar, 'symbol') else "601857",
            "signal": sig_val,
            "strength": round(strength, 4),
        })
    return signals


def generate_bollinger_reversal_signals(
    bars: list, period: int = 20, std_dev: float = 2.0
) -> list[dict]:
    """批量生成布林带反转信号。"""
    closes = np.array([float(b.close) for b in bars])
    signals: list[dict] = []
    for i, bar in enumerate(bars):
        sig_val = 0
        strength = 0.0
        if i >= period:
            window = closes[i - period + 1:i + 1]
            ma = window.mean()
            std = window.std()
            upper = ma + std_dev * std
            lower = ma - std_dev * std
            prev_close = closes[i - 1]
            curr_close = closes[i]
            if prev_close >= lower and curr_close < lower:
                sig_val = 1
                strength = 1.0
            elif prev_close <= upper and curr_close > upper:
                sig_val = -1
                strength = 1.0
        signals.append({
            "date": str(bar.date),
            "symbol": str(bar.symbol) if hasattr(bar, 'symbol') else "601857",
            "signal": sig_val,
            "strength": round(strength, 4),
        })
    return signals


def generate_bias_signals(
    bars: list, ma_period: int = 5, bias_buy: float = -0.05, bias_sell: float = 0.05
) -> list[dict]:
    """批量生成乖离率反转信号。"""
    closes = np.array([float(b.close) for b in bars])
    signals: list[dict] = []
    for i, bar in enumerate(bars):
        sig_val = 0
        strength = 0.0
        if i >= ma_period:
            ma = closes[i - ma_period + 1:i + 1].mean()
            if ma > 0:
                bias = (closes[i] - ma) / ma
                if bias < bias_buy:
                    sig_val = 1
                    strength = min(1.0, (bias_buy - bias) / max(abs(bias_buy), 0.001))
                elif bias > bias_sell:
                    sig_val = -1
                    strength = min(1.0, (bias - bias_sell) / max(bias_sell, 0.001))
        signals.append({
            "date": str(bar.date),
            "symbol": str(bar.symbol) if hasattr(bar, 'symbol') else "601857",
            "signal": sig_val,
            "strength": round(strength, 4),
        })
    return signals


def voted_reversal_signal(
    signal_lists: list[list[dict]], min_votes: int = 2
) -> dict:
    """
    多信号投票融合。

    signal_lists 每个元素是 generate_*_signals() 的输出。
    返回 { "signal": [融合后的信号列表], "votes": ... }
    """
    if not signal_lists:
        return {"signal": [], "votes": []}
    n = len(signal_lists[0])
    merged_signals: list[dict] = []
    for i in range(n):
        buy_votes = 0
        sell_votes = 0
        total_strength = 0.0
        for sl in signal_lists:
            if i < len(sl):
                s = sl[i]["signal"]
                st = sl[i]["strength"]
                if s > 0:
                    buy_votes += 1
                    total_strength += st
                elif s < 0:
                    sell_votes += 1
                    total_strength += st
        sig_val = 0
        if buy_votes >= min_votes and buy_votes > sell_votes:
            sig_val = 1
        elif sell_votes >= min_votes and sell_votes > buy_votes:
            sig_val = -1
        merged_signals.append({
            "date": signal_lists[0][i]["date"],
            "symbol": signal_lists[0][i]["symbol"],
            "signal": sig_val,
            "strength": round(total_strength / max(len(signal_lists), 1), 4),
        })
    return {"signal": merged_signals}


class ReversalCooler:
    """反转冷却期管理器（基于日期字符串而非索引）。"""

    def __init__(self, cooler_days: int = 2):
        self.cooler_days = cooler_days
        self._records: dict[str, list[str]] = {}  # symbol -> [买入日期列表]

    def can_open(self, date: str, symbol: str, signal: int) -> bool:
        if signal <= 0 or self.cooler_days <= 0:
            return True
        dates = self._records.get(symbol, [])
        if not dates:
            return True
        last_date = dates[-1]
        # 计算日期差（简化：字符串比较 YYYYMMDD 格式）
        try:
            diff = int(date[:8]) - int(last_date[:8])
            return diff >= self.cooler_days
        except (ValueError, IndexError):
            return True

    def record(self, date: str, symbol: str, signal: int) -> None:
        if signal > 0:
            if symbol not in self._records:
                self._records[symbol] = []
            self._records[symbol].append(date[:8])

    def reset(self, symbol: str = "") -> None:
        if symbol:
            self._records.pop(symbol, None)
        else:
            self._records.clear()