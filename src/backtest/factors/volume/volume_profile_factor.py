"""
墨枢 - Volume Profile 因子（R1 阶段一：第1组-2）

基于成交量分布的价量分析：
  - calc_volume_profile：按价格区间划分成交量，识别 POC / VAH / VAL
  - calc_lvn：Low Volume Node — 成交量异常低的价区（潜在断裂缺口）

参考：Market Profile / Volume Profile 方法论。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def calc_volume_profile(
    df: pd.DataFrame,
    n_bins: int = 24,
) -> Dict[str, float]:
    """
    计算当日 Volume Profile。

    将价格区间等分为 n_bins 个桶，统计每个桶的成交量，
    找出 POC（Point of Control，最大成交量价格区）、
    VAH（Value Area High）、VAL（Value Area Low）。

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'high', 'low', 'close', 'volume' 列。
        仅使用最后一行作为当日数据。
    n_bins : int
        价格区间分桶数（默认 24，对应 1h 级别的日内分桶）。

    Returns
    -------
    Dict[str, float]
        {
            "poc": float,        # Point of Control（最大成交量价区中值）
            "vah": float,        # Value Area High（70% 成交量上界）
            "val": float,        # Value Area Low（70% 成交量下界）
            "range_high": float, # 当日最高价
            "range_low": float,  # 当日最低价
            "value_area_pct": float  # 价值区成交量占比
        }
    """
    if df.empty or len(df) < 1:
        return _empty_vp()

    high = df["high"].max()
    low = df["low"].min()
    if high <= low:
        return _empty_vp()

    bin_width = (high - low) / n_bins
    if bin_width == 0:
        return _empty_vp()

    # 对每一行分配价格桶（假设 day 内的每笔交易）
    bin_volumes = np.zeros(n_bins, dtype=np.float64)

    for _, row in df.iterrows():
        row_high = row["high"]
        row_low = row["low"]
        row_vol = row["volume"] if pd.notna(row["volume"]) else 0.0
        if row_vol <= 0:
            continue

        # 将成交量均匀分配到该 bar 覆盖的桶
        start_bin = int((row_low - low) / bin_width)
        end_bin = int((row_high - low) / bin_width)
        start_bin = max(0, min(start_bin, n_bins - 1))
        end_bin = max(0, min(end_bin, n_bins - 1))

        if end_bin >= start_bin:
            n_covered = end_bin - start_bin + 1
            vol_per_bin = row_vol / n_covered
            for b in range(start_bin, end_bin + 1):
                bin_volumes[b] += vol_per_bin

    total_vol = bin_volumes.sum()
    if total_vol <= 0:
        return _empty_vp()

    # POC: 最大成交量桶的中值价格
    poc_bin = int(np.argmax(bin_volumes))
    poc_price = low + (poc_bin + 0.5) * bin_width

    # Value Area: 从 POC 向两侧扩展至覆盖 70% 成交量
    target_vol = total_vol * 0.70
    sorted_bins = sorted(
        range(n_bins), key=lambda i: bin_volumes[i], reverse=True
    )

    cum_vol = 0.0
    included_bins: List[int] = []
    for b in sorted_bins:
        if cum_vol >= target_vol:
            break
        cum_vol += bin_volumes[b]
        included_bins.append(b)

    if included_bins:
        vah_price = low + (max(included_bins) + 1) * bin_width
        val_price = low + min(included_bins) * bin_width
    else:
        vah_price = high
        val_price = low

    return {
        "poc": round(poc_price, 4),
        "vah": round(vah_price, 4),
        "val": round(val_price, 4),
        "range_high": round(high, 4),
        "range_low": round(low, 4),
        "value_area_pct": round(cum_vol / total_vol * 100, 2),
    }


def calc_lvn(
    df: pd.DataFrame,
    threshold: float = 0.3,
    n_bins: int = 24,
) -> List[Tuple[float, float]]:
    """
    Low Volume Node 检测。

    成交量 ≤ 均值 × threshold 的价格区间，通常对应市场流动性缺口。

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'high', 'low', 'volume' 列。
    threshold : float
        阈值倍数。成交量≤均值×threshold 的桶视为 LVN。
    n_bins : int
        分桶数。

    Returns
    -------
    List[Tuple[float, float]]
        (价区下限, 价区上限) 列表。
    """
    if df.empty or len(df) < 1:
        return []

    high = df["high"].max()
    low = df["low"].min()
    if high <= low:
        return []

    bin_width = (high - low) / n_bins
    if bin_width == 0:
        return []

    bin_volumes = np.zeros(n_bins, dtype=np.float64)
    for _, row in df.iterrows():
        row_high = row["high"]
        row_low = row["low"]
        row_vol = row["volume"] if pd.notna(row["volume"]) else 0.0
        if row_vol <= 0:
            continue
        start_bin = max(0, min(int((row_low - low) / bin_width), n_bins - 1))
        end_bin = max(0, min(int((row_high - low) / bin_width), n_bins - 1))
        if end_bin >= start_bin:
            n_covered = end_bin - start_bin + 1
            vol_per_bin = row_vol / n_covered
            for b in range(start_bin, end_bin + 1):
                bin_volumes[b] += vol_per_bin

    mean_vol = bin_volumes.mean()
    lvn_threshold = mean_vol * threshold

    # 连续低量桶合并
    lvn_regions: List[Tuple[float, float]] = []
    in_lvn = False
    lvn_start = -1

    for b in range(n_bins):
        if bin_volumes[b] <= lvn_threshold:
            if not in_lvn:
                lvn_start = b
                in_lvn = True
        else:
            if in_lvn:
                lvn_regions.append(
                    (low + lvn_start * bin_width, low + b * bin_width)
                )
                in_lvn = False

    if in_lvn:
        lvn_regions.append(
            (low + lvn_start * bin_width, low + n_bins * bin_width)
        )

    return [(round(lo, 4), round(hi, 4)) for lo, hi in lvn_regions]


def _empty_vp() -> Dict[str, float]:
    return {
        "poc": 0.0,
        "vah": 0.0,
        "val": 0.0,
        "range_high": 0.0,
        "range_low": 0.0,
        "value_area_pct": 0.0,
    }
