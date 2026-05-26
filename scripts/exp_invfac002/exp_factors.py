"""
EXP-2026-INVFAC-002: 三因子计算函数
============================================
author: 墨衡 (moheng)
created: 2026-05-25T17:10+08:00

实现实验设计 §3.1 的三个因子计算函数。

函数清单:
  - calc_trend_quality(high, low, close, period=20)  → §3.1.1
  - calc_vol_rsi_std(volume, rsi_period=14, std_period=20) → §3.1.2
  - calc_kdj_k(high, low, close, period=9, k_smooth=3) → §3.1.3
  - reverse_factor(factor_series) → 符号反转 §3.1.4

依赖: numpy, pandas
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calc_trend_quality(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 20,
) -> np.ndarray:
    """
    趋势质量因子 — 价格位置偏移与 ATR 的比值。

    逻辑 (§3.1.1):
      1. 计算 AR(平均真实波幅)作为归一化基础
      2. 价格位置偏移 = (close - rolling_min(low)) / (rolling_max(high) - rolling_min(low))
      3. 趋势质量 = (price_pos - 0.5) / (ATR / close)

    Parameters
    ----------
    high : 最高价序列
    low : 最低价序列
    close : 收盘价序列
    period : 滚动窗口（默认 20）

    Returns
    -------
    np.ndarray : 趋势质量值序列，前 period-1 个为 NaN
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    result = np.full(n, np.nan)

    if n < period + 1:
        return result

    # 1. 计算 ATR（滚动窗口内的平均 TR）
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]

    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - prev_close),
            np.abs(low - prev_close),
        ),
    )

    # 滚动均值（第一行 ATR）
    atr = np.full(n, np.nan)
    for i in range(period - 1, n):
        atr[i] = np.mean(tr[i - period + 1:i + 1])

    # 2. 价格位置偏移 (rolling min/max)
    for i in range(period - 1, n):
        low_min = np.min(low[i - period + 1:i + 1])
        high_max = np.max(high[i - period + 1:i + 1])
        denom = high_max - low_min
        if denom < 1e-10:
            price_pos = 0.5
        else:
            price_pos = (close[i] - low_min) / denom

        # 3. 趋势质量
        atr_i = atr[i]
        if atr_i is not None and not np.isnan(atr_i) and atr_i > 1e-10:
            result[i] = (price_pos - 0.5) / (atr_i / close[i] + 1e-10)
        else:
            result[i] = 0.0

    return result


def calc_vol_rsi_std(
    volume: np.ndarray | pd.Series,
    rsi_period: int = 14,
    std_period: int = 20,
) -> np.ndarray:
    """
    成交量 RSI 的滚动标准差 — 量能发散/收敛状态。

    逻辑 (§3.1.2):
      1. 成交量变化率: vol_change = volume.diff()
      2. 计算成交量 RSI 序列
      3. 对 vol_rsi 计算滚动标准差

    Parameters
    ----------
    volume : 成交量序列
    rsi_period : RSI 周期（默认 14）
    std_period : 滚动标准差窗口（默认 20）

    Returns
    -------
    np.ndarray : vol_rsi_std 值序列
    """
    volume = np.asarray(volume, dtype=float)
    n = len(volume)
    result = np.full(n, np.nan)

    if n < rsi_period + std_period:
        return result

    # 1. 成交量变化率
    vol_change = np.diff(volume)
    vol_change = np.concatenate([[0.0], vol_change])  # 第一列为 0

    # 2. 成交量 RSI
    gain = np.clip(vol_change, 0, None)
    loss = np.clip(-vol_change, 0, None)

    # SMA of gains/losses
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)

    # 初始化第一组 SMA
    avg_gain[rsi_period] = np.mean(gain[1:rsi_period + 1])
    avg_loss[rsi_period] = np.mean(loss[1:rsi_period + 1])

    # Wilder 平滑
    for i in range(rsi_period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (rsi_period - 1) + gain[i]) / rsi_period
        avg_loss[i] = (avg_loss[i - 1] * (rsi_period - 1) + loss[i]) / rsi_period

    rs = avg_gain / (avg_loss + 1e-10)
    vol_rsi = 100.0 - (100.0 / (1.0 + rs))

    # 3. 滚动标准差
    for i in range(rsi_period + std_period - 1, n):
        result[i] = np.std(vol_rsi[i - std_period + 1:i + 1])

    return result


def calc_kdj_k(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 9,
    k_smooth: int = 3,
) -> np.ndarray:
    """
    KDJ 指标的 K 值 — 经典超买超卖指标。

    逻辑 (§3.1.3):
      1. RSV = (close - min(low, period)) / (max(high, period) - min(low, period)) * 100
      2. K = EMA(RSV, k_smooth)

    与 phase1_factor_backfill._calc_kdj 返回的 K/D/J 中的 K 值一致。

    Parameters
    ----------
    high : 最高价序列
    low : 最低价序列
    close : 收盘价序列
    period : KDJ 周期（默认 9）
    k_smooth : K 平滑系数（默认 3）

    Returns
    -------
    np.ndarray : K 值序列 [0, 100]
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    k = np.full(n, np.nan)

    if n < period:
        return k

    for i in range(period - 1, n):
        low_min = np.min(low[i - period + 1:i + 1])
        high_max = np.max(high[i - period + 1:i + 1])
        denom = high_max - low_min
        if denom > 1e-10:
            rsv = (close[i] - low_min) / denom * 100.0
        else:
            rsv = 50.0

        if np.isnan(k[i - 1]):
            k[i] = rsv
        else:
            k[i] = (k_smooth - 1.0) / k_smooth * k[i - 1] + 1.0 / k_smooth * rsv

    return k


def reverse_factor(factor_series: np.ndarray) -> np.ndarray:
    """
    因子符号反转 (§3.1.4)。

    对原始负 IC 因子值做符号取反处理。

    Parameters
    ----------
    factor_series : 原始因子值序列

    Returns
    -------
    np.ndarray : 反转后的因子值（已取负）
    """
    return -1.0 * np.asarray(factor_series, dtype=float)
