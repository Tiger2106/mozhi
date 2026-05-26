"""
墨枢 - Structure 因子（R1 阶段一：第2组-6）

价格结构分析：
  - calc_support_resistance：自动识别关键支撑 / 阻力位
  - calc_structure_quality：价格形态完整度评分
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


def calc_support_resistance(
    df: pd.DataFrame,
    lookback: int = 60,
    min_touch: int = 2,
    cluster_distance: float = 0.005,
) -> Dict[str, List[float]]:
    """
    自动识别关键支撑 / 阻力位。

    使用极值点聚类法：
      1. 在 lookback 窗口中查找局部极值（波峰 / 波谷）
      2. 将相近的价格点聚类
      3. 每个类的价格中值作为关键位

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'high', 'low' 列。
    lookback : int
        回溯窗口（默认 60 根 K 线）。
    min_touch : int
        最少触碰次数（默认 2），少于该值的聚类不视为有效关键位。
    cluster_distance : float
        聚类距离（价格比例），默认 0.5%（千分之五）。

    Returns
    -------
    Dict[str, List[float]]
        {
            "support": [price1, price2, ...],  # 支撑位（价值区）
            "resistance": [price1, price2, ...],  # 阻力位（高价区）
            "all_levels": [price1, price2, ...]  # 全量级别
        }
    """
    df = df.iloc[-lookback:].copy()
    n = len(df)
    if n < 20:
        return {"support": [], "resistance": [], "all_levels": []}

    # ── 1. 局部极值检测 ───────────────────────────
    high = df["high"].values
    low = df["low"].values
    local_max_idx: List[int] = []
    local_min_idx: List[int] = []

    for i in range(2, n - 2):
        # 波峰：比左右各 2 个都高
        if all(high[i] >= high[i + j] for j in (-2, -1, 1, 2)):
            local_max_idx.append(i)
        # 波谷：比左右各 2 个都低
        if all(low[i] <= low[i + j] for j in (-2, -1, 1, 2)):
            local_min_idx.append(i)

    # ── 2. 聚类 ─────────────────────────────────
    def _cluster(prices: List[float], min_dist_ratio: float) -> List[float]:
        if not prices:
            return []
        prices_sorted = sorted(prices)
        clusters: List[List[float]] = []
        current = [prices_sorted[0]]

        for p in prices_sorted[1:]:
            mean_p = sum(current) / len(current)
            if abs(p - mean_p) / (mean_p + 1e-10) <= min_dist_ratio:
                current.append(p)
            else:
                clusters.append(current)
                current = [p]
        clusters.append(current)

        # 只保留触及次数 ≥ min_touch 的聚类
        return [round(sum(c) / len(c), 4) for c in clusters if len(c) >= min_touch]

    resistance_prices = [high[i] for i in local_max_idx]
    support_prices = [low[i] for i in local_min_idx]

    resistance = _cluster(resistance_prices, cluster_distance)
    support = _cluster(support_prices, cluster_distance)

    return {
        "support": sorted(set(support)) if support else [],
        "resistance": sorted(set(resistance)) if resistance else [],
        "all_levels": sorted(set(support + resistance)),
    }


def calc_structure_quality(df: pd.DataFrame, lookback: int = 30) -> float:
    """
    价格形态完整度评分。

    基于以下维度综合评分 (0~1)：
      1. 波动率稳定性（高稳定 → 高分）
      2. 峰谷识别度（清晰峰谷 → 高分）
      3. 趋势片段长度（长片段 → 高分）

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'high', 'low', 'close' 列。
    lookback : int
        回溯窗口。

    Returns
    -------
    float
        [0, 1] 结构完整度得分。
    """
    df = df.iloc[-lookback:].copy()
    n = len(df)
    if n < 20:
        return 0.0

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    # ── 1. 波动率稳定性 ───────────────────────────
    true_ranges = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - np.roll(close, 1)),
            np.abs(low - np.roll(close, 1)),
        ),
    )[1:]  # 移除第一个 NaN
    if len(true_ranges) < 2:
        return 0.0
    vol_cv = true_ranges.std() / (true_ranges.mean() + 1e-10)
    vol_stability = 1.0 / (1.0 + vol_cv)  # CV 越小越稳定

    # ── 2. 峰谷识别度 ─────────────────────────────
    peak_count = 0
    for i in range(2, n - 2):
        if all(high[i] >= high[i + j] for j in (-2, -1, 1, 2)):
            peak_count += 1
        if all(low[i] <= low[i + j] for j in (-2, -1, 1, 2)):
            peak_count += 1
    peak_clarity = min(peak_count / (n * 0.2), 1.0)

    # ── 3. 趋势片段长度 ─────────────────────────
    direction = np.sign(np.diff(close))
    # 连续同向长度
    runs: List[int] = []
    current_run = 1
    for i in range(1, len(direction)):
        if direction[i] == direction[i - 1] and direction[i] != 0:
            current_run += 1
        else:
            if current_run >= 3:
                runs.append(current_run)
            current_run = 1
    if current_run >= 3:
        runs.append(current_run)

    avg_run_len = np.mean(runs) if runs else 1.0
    run_score = min(avg_run_len / 10.0, 1.0)

    # ── 合成 ────────────────────────────────────
    quality = 0.4 * vol_stability + 0.35 * peak_clarity + 0.25 * run_score
    return round(float(np.clip(quality, 0.0, 1.0)), 4)
