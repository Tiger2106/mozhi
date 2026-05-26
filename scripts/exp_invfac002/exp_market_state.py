"""
EXP-2026-INVFAC-002: 滚动波动率分位数状态分类
==================================================
author: 墨衡 (moheng)
created: 2026-05-25T17:10+08:00

实现实验设计 §3.2 的市场状态分类函数。

函数清单:
  - classify_market_state(close, percentile_high, percentile_low, window, warmup_vol)
    → 滚动波动率分位数状态分类

状态定义:
  - state=2: 高波动 (panic) — top 20%
  - state=1: 中波动 (consolidation) — 30%~80%
  - state=0: 低波动 (trend) — bottom 30%

依赖: numpy
"""

from __future__ import annotations

import numpy as np


def classify_market_state(
    close: np.ndarray,
    percentile_high: float = 0.80,
    percentile_low: float = 0.30,
    window: int = 20,
    warmup_vol: np.ndarray | None = None,
) -> tuple[np.ndarray, float, float]:
    """
    滚动波动率分位数状态分类 (§3.2.1)。

    基于每日收益率计算年化滚动波动率，再根据分位数阈值划分市场状态。

    Parameters
    ----------
    close : 收盘价序列
    percentile_high : 高波动分位数阈值（默认 0.80 = top 20%）
    percentile_low : 低波动分位数阈值（默认 0.30 = bottom 30%）
    window : 滚动窗口（默认 20 交易日）
    warmup_vol : 暖机期波动率序列。若提供，阈值仅基于暖机期计算（锁前视偏差）

    Returns
    -------
    tuple:
      - state (np.ndarray): 状态序列（2=高，1=中，0=低）
      - high_threshold (float): 高波动分位数值
      - low_threshold (float): 低波动分位数值
    """
    close = np.asarray(close, dtype=float)
    n = len(close)

    # 每日收益率
    returns = np.diff(close) / close[:-1]
    returns = np.concatenate([[0.0], returns])

    # 滚动年化波动率
    rolling_vol = np.full(n, np.nan)
    for i in range(window, n):
        rolling_vol[i] = np.std(returns[i - window + 1:i + 1]) * np.sqrt(252)

    state = np.zeros(n, dtype=np.int8)

    # 阈值计算
    vol_series = rolling_vol[~np.isnan(rolling_vol)]
    if len(vol_series) == 0:
        return state, 0.0, 0.0

    if warmup_vol is not None:
        warmup_clean = warmup_vol[~np.isnan(warmup_vol)]
        if len(warmup_clean) > 0:
            high_threshold = np.percentile(warmup_clean, percentile_high * 100)
            low_threshold = np.percentile(warmup_clean, percentile_low * 100)
        else:
            high_threshold = np.percentile(vol_series, percentile_high * 100)
            low_threshold = np.percentile(vol_series, percentile_low * 100)
    else:
        high_threshold = np.percentile(vol_series, percentile_high * 100)
        low_threshold = np.percentile(vol_series, percentile_low * 100)

    # 状态分配
    for i in range(n):
        if np.isnan(rolling_vol[i]):
            state[i] = 1  # NaN 时默认为中波动
        elif rolling_vol[i] >= high_threshold:
            state[i] = 2  # 高波动
        elif rolling_vol[i] < low_threshold:
            state[i] = 0  # 低波动
        else:
            state[i] = 1  # 中波动

    return state, high_threshold, low_threshold
