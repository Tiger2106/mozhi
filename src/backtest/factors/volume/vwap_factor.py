"""
墨枢 - VWAP 因子扩展（R1 阶段一）

提供多时间尺度的 VWAP 计算与偏离度分析。
VWAP = cumulative_amount / cumulative_volume (从 stock_daily 表的 amount/volume 字段计算)
回退：Sum(TypicalPrice * Volume) / Sum(Volume)（兼容没有 amount 列的场景）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def calc_vwap(df: pd.DataFrame) -> pd.Series:
    """
    VWAP（成交量加权平均价）。

    使用 stock_daily 表的实际成交额和成交量计算：VWAP = amount / volume。

    Parameters
    ----------
    df : pd.DataFrame
        如果存在 'amount' 列，使用 amount.cumsum() / volume.cumsum()；
        否则回退至 typical_price 累积版本（兼容旧数据）。
        至少需包含 'volume' 列。

    Returns
    -------
    pd.Series
        与 df 等长的 VWAP 列。
    """
    if "amount" in df.columns:
        cumulative_amount = df["amount"].cumsum()
        cumulative_vol = df["volume"].cumsum()
    else:
        # 回退：typical_price 累积版本（兼容旧数据流）
        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        cumulative_amount = (typical_price * df["volume"]).cumsum()
        cumulative_vol = df["volume"].cumsum()
    # 避免除以 0
    mask = cumulative_vol > 0
    result = pd.Series(np.nan, index=df.index)
    result[mask] = cumulative_amount[mask] / cumulative_vol[mask]
    return result


def calc_vwap_deviation(
    df: pd.DataFrame, vwap_column: Optional[str] = None
) -> pd.Series:
    """
    VWAP 偏离度 = (close - VWAP) / VWAP * 100。

    正值表示价格在 VWAP 上方（多头优势），负值表示在 VWAP 下方（空头优势）。

    Parameters
    ----------
    df : pd.DataFrame
        包含 'close' 列，以及 vwap_column 指定的 VWAP 列。
    vwap_column : str, optional
        VWAP 列名。若未指定则自动计算。
    """
    if vwap_column is None:
        vwap = calc_vwap(df)
    else:
        vwap = df[vwap_column]
    mask = vwap > 0
    result = pd.Series(np.nan, index=df.index)
    result[mask] = (df.loc[mask, "close"] - vwap[mask]) / vwap[mask] * 100.0
    return result


def calc_multi_vwap(
    df: pd.DataFrame,
    windows: Optional[List[int]] = None,
) -> Dict[str, pd.Series]:
    """
    多周期 VWAP（滚动窗口）。

    Parameters
    ----------
    df : pd.DataFrame
        如果存在 'amount' 列，使用 amount.rolling / volume.rolling；
        否则回退至 typical_price 累积版本。
    windows : List[int], optional
        滚动窗口列表。默认 [5, 10, 20]。

    Returns
    -------
    Dict[str, pd.Series]
        {"vwap_5": ..., "vwap_10": ..., "vwap_20": ...}
    """
    if windows is None:
        windows = [5, 10, 20]

    if "amount" in df.columns:
        base_amount = df["amount"]
    else:
        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        base_amount = typical_price * df["volume"]

    result: Dict[str, pd.Series] = {}
    for w in windows:
        cum_amount = base_amount.rolling(window=w, min_periods=1).sum()
        cum_vol = df["volume"].rolling(window=w, min_periods=1).sum()
        vwap_series = pd.Series(np.nan, index=df.index)
        mask = cum_vol > 0
        vwap_series[mask] = cum_amount[mask] / cum_vol[mask]
        result[f"vwap_{w}"] = vwap_series

    return result


# ──────────────────────────────────────────────────────────────────────
# VwapFactor（类封装，适配 FactorCache / MissingAsset.cache_strategy 调用）
# ──────────────────────────────────────────────────────────────────────


class VwapFactor:
    """VWAP 因子（类接口封装）。

    包装 ``calc_vwap()`` 为类方法形式，使 MissingAsset 和 FactorCache
    可以通过 ``VwapFactor.compute(df)`` 样式的 .compute() 调用，
    无需使用函数式接口。

    FACTOR_META 记录在模块级，与 BaseFactor 子类兼容。

    Examples:
        >>> result = VwapFactor.compute(df)  # pd.DataFrame with 'vwap' column
    """

    FACTOR_META = {
        "name": "vwap",
        "version": "1.0.0",
        "author": "墨衡",
        "description": "成交量加权平均价（类封装，包装 calc_vwap）",
        "category": "volume",
        "default_params": {},
        "tags": ["volume", "vwap"],
    }

    @classmethod
    def compute(cls, df: pd.DataFrame) -> pd.DataFrame:
        """计算 VWAP 值。

        Args:
            df: 必须包含 ``high``、``low``、``close``、``volume`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含 ``vwap`` 列的 DataFrame，索引与 ``df`` 对齐。
        """
        vwap_series = calc_vwap(df)
        return pd.DataFrame({"vwap": vwap_series}, index=df.index)


def calc_vwap_band(
    df: pd.DataFrame,
    deviations: Optional[List[float]] = None,
) -> Dict[str, pd.Series]:
    """
    VWAP 通道带（±n% 带宽）。

    Parameters
    ----------
    df : pd.DataFrame
        包含 'high', 'low', 'close', 'volume' 列。
    deviations : List[float], optional
        带宽百分比列表。默认 [1.0, 2.0, 3.0]。

    Returns
    -------
    Dict[str, pd.Series]
        {"vwap_upper_1": ..., "vwap_lower_1": ..., ...}
    """
    if deviations is None:
        deviations = [1.0, 2.0, 3.0]

    vwap = calc_vwap(df)
    result: Dict[str, pd.Series] = {}
    for dev in deviations:
        key = str(dev).rstrip("0.") or str(int(dev))
        result[f"vwap_upper_{key}"] = vwap * (1.0 + dev / 100.0)
        result[f"vwap_lower_{key}"] = vwap * (1.0 - dev / 100.0)
    result["vwap"] = vwap
    return result
