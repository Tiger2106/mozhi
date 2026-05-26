"""
墨枢 - Volume Flow 因子（R1 阶段一：第2组-5）

分析成交量与价格行为的配合关系：
  - calc_smart_money_score：量价匹配度评分
  - calc_volume_trend：量能趋势方向与强度
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calc_smart_money_score(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """
    量价匹配度评分（聪明钱信号）。

    核心逻辑：
      - 价涨量增 → 正分（健康上涨）
      - 价跌量增 → 负分（恐慌抛售）
      - 价涨量缩 → 弱正分（上涨动能不足）
      - 价跌量缩 → 弱负分（下跌耗尽）

    评分范围 [-1, 1]：
      > 0.3  → 健康上涨（聪明钱买入）
      < -0.3 → 恐慌抛售（聪明钱卖出）

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'close', 'volume' 列。
    lookback : int
        评分回溯窗口（默认 10）。

    Returns
    -------
    pd.Series
        [-1, 1] 量价匹配度评分。
    """
    df = df.copy()
    # 价格变化方向
    price_change = df["close"].diff()
    price_direction = price_change.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    # 成交量变化方向
    vol_change = df["volume"].diff()
    vol_direction = vol_change.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    # 量价协同：方向一致时强化，不一致时弱化
    raw_score = price_direction * vol_direction
    # 如果价格持平则为 0
    raw_score = raw_score.where(price_direction != 0, 0.0)

    # 加权平滑
    weights = np.array([0.5 + 0.5 * i / lookback for i in range(lookback)])
    weights = weights / weights.sum()

    smoothed = raw_score.rolling(window=lookback, min_periods=1).apply(
        lambda x: np.dot(np.nan_to_num(x), weights[: len(x)]), raw=True
    )

    return smoothed.clip(-1.0, 1.0)


def calc_volume_trend(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    量能趋势指标。

    使用成交量的线性回归斜率，判断量能扩大或萎缩。

    Returns
    -------
    pd.Series
        [-1, 1] 量能趋势评分：
        > 0.3  → 量能放大
        < -0.3 → 量能萎缩
        其  他 → 量能稳定
    """
    volume = df["volume"]
    n = len(volume)

    def _slope(arr: np.ndarray) -> float:
        if len(arr) < 2:
            return 0.0
        x = np.arange(len(arr))
        y = np.array(arr)
        # 标准化
        y_norm = (y - y.mean()) / (y.std() + 1e-10)
        slope = np.polyfit(x, y_norm, 1)[0]
        # 映射到 [-1, 1]
        return np.clip(slope * 2.0, -1.0, 1.0)

    trend = volume.rolling(window=period, min_periods=5).apply(
        _slope, raw=True
    )
    return trend.fillna(0.0)


def calc_volume_ratio(
    df: pd.DataFrame, short_period: int = 5, long_period: int = 20
) -> pd.Series:
    """
    量比：短期均量 / 长期均量。

    > 1.5 → 放量显著
    < 0.5 → 缩量显著
    """
    short_ma = df["volume"].rolling(short_period, min_periods=1).mean()
    long_ma = df["volume"].rolling(long_period, min_periods=1).mean()
    ratio = short_ma / long_ma.replace(0, np.nan)
    return ratio.fillna(1.0)
