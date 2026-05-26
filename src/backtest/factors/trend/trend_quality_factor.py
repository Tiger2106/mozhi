"""
墨枢 - Trend Quality 因子（R1 阶段一：第1组-3）

量化趋势质量的因子族：
  - calc_adx：ADX（平均趋向指数）衡量趋势强度
  - calc_trend_strength：将 ADX 归一化到 [0, 1]
  - calc_trend_consistency：方向一致性（连续同向 K 线占比）

注意：本模块与 backtest_engine/strategies/factor_calculator.py 互补。
前者用于回测引擎内部，本模块为 R1 因子工程独立版本（使用 DataFrame）。
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd


def calc_adx(
    df: pd.DataFrame,
    period: int = 14,
) -> pd.Series:
    """
    ADX（Average Directional Index, 平均趋向指数）。

    衡量趋势强度（不区分方向）：
      - ADX < 20  → 弱趋势 / 盘整
      - 20 ≤ ADX < 40 → 中等趋势
      - ADX ≥ 40 → 强趋势

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'high', 'low', 'close' 列。
    period : int
        周期（默认 14）。

    Returns
    -------
    pd.Series
        与 df 等长的 ADX 系列，前 (period + 1) 个为 NaN。
    """
    df = df.copy()
    n = len(df)
    if n < period + 1:
        return pd.Series(np.nan, index=df.index)

    # TR（True Range）
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # +DM / -DM
    up_move = df["high"].diff()
    down_move = -(df["low"].diff())
    pos_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move
    neg_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move

    # Wilder 平滑（修正 EMA）
    def wilder_smooth(series: pd.Series, p: int) -> pd.Series:
        alpha = 1.0 / p
        return series.ewm(alpha=alpha, adjust=False).mean()

    tr_s = wilder_smooth(tr, period)
    pdi_s = wilder_smooth(pos_dm.clip(lower=0), period)
    ndi_s = wilder_smooth(neg_dm.clip(lower=0), period)

    # +DI / -DI
    tr_s = tr_s.replace(0, np.nan)  # 避免除以 0
    pdi = 100.0 * pdi_s / tr_s
    ndi = 100.0 * ndi_s / tr_s

    # DX
    di_sum = pdi + ndi
    dx = 100.0 * (pdi - ndi).abs() / di_sum.replace(0, np.nan)

    # ADX
    adx = wilder_smooth(dx, period)

    return adx


def calc_trend_strength(adx_series: pd.Series) -> pd.Series:
    """
    将 ADX 值归一化到 [0, 1]。

    映射规则：
      - ADX < 20  → 0.0 ~ 0.3
      - 20 ≤ ADX < 40 → 0.3 ~ 0.7
      - ADX ≥ 40 → 0.7 ~ 1.0

    使用线性分段映射。
    """
    result = adx_series.copy()
    # 分段线性映射
    result[adx_series < 20] = adx_series[adx_series < 20] / 20.0 * 0.3
    mask_mid = (adx_series >= 20) & (adx_series < 40)
    result[mask_mid] = 0.3 + (adx_series[mask_mid] - 20) / 20.0 * 0.4
    mask_strong = adx_series >= 40
    result[mask_strong] = 0.7 + (adx_series[mask_strong] - 40) / 60.0 * 0.3
    return result.clip(0.0, 1.0)


def calc_trend_consistency(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """
    趋势方向一致性。

    统计连续同向 K 线（连续上涨或连续下跌）占 lookback 窗口的比例。
    核心逻辑：连续同向收盘越多，趋势越一致。

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'close' 列。
    lookback : int
        回溯窗口（默认 10 根 K 线）。

    Returns
    -------
    pd.Series
        [0, 1] 之间的置信度值。1.0 = 全部同向。
    """
    direction = df["close"].diff().fillna(0)
    direction = direction.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    consistency = direction.rolling(window=lookback, min_periods=1).apply(
        _calc_window_consistency, raw=True
    )
    return consistency


def _calc_window_consistency(arr: np.ndarray) -> float:
    """辅助：计算窗口内方向一致性得分。"""
    if len(arr) < 2:
        return 0.0
    non_zero = arr[arr != 0]
    if len(non_zero) == 0:
        return 0.0
    positive_ratio = (non_zero > 0).sum() / len(non_zero)
    # 越接近 0 或 1 一致性越高
    return 2.0 * abs(positive_ratio - 0.5)
