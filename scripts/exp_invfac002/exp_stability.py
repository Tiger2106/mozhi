"""
EXP-2026-INVFAC-002: 三层稳定性检验
========================================
author: 墨衡 (moheng)
created: 2026-05-25T17:10+08:00

实现实验设计 §5.3 的三层稳定性检验函数。

函数清单:
  - check_time_slice_stability(reversed_ic, n_slices=4)
  - check_rolling_stability(reversed_ic, roll_window=126)
  - check_cross_sectional_stability(ic_by_stock, n_stocks=12, min_agree=8)

依赖: numpy
"""

from __future__ import annotations

import numpy as np


def check_time_slice_stability(
    reversed_ic: np.ndarray,
    n_slices: int = 4,
) -> tuple[bool, np.ndarray]:
    """
    时间切片稳定性检验 (§5.3.1)。

    将数据按时间分为 n_slices 等份，每份独立计算 IC 均值。
    通过条件：≥ (n_slices-1) 个切片 IC 符号一致。

    Parameters
    ----------
    reversed_ic : 反转后 IC 序列（含 NaN）
    n_slices : 切片数量（默认 4）

    Returns
    -------
    tuple:
      - passed: bool — 是否通过
      - slice_ic_means: np.ndarray — 各切片 IC 均值
    """
    ic_clean = reversed_ic[~np.isnan(reversed_ic)]
    n = len(ic_clean)

    if n < n_slices:
        return False, np.full(n_slices, np.nan)

    slice_size = n // n_slices
    slice_ic_means = np.full(n_slices, np.nan)
    for i in range(n_slices):
        start = i * slice_size
        end = start + slice_size if i < n_slices - 1 else n
        slice_ic_means[i] = np.mean(ic_clean[start:end])

    # 统计正负符号一致数
    n_positive = np.sum(slice_ic_means > 0)
    n_negative = np.sum(slice_ic_means < 0)
    max_agree = max(n_positive, n_negative)

    # 通过：≥ (n_slices-1) 的切片方向一致
    passed = max_agree >= (n_slices - 1)
    return passed, slice_ic_means


def check_rolling_stability(
    reversed_ic: np.ndarray,
    roll_window: int = 126,
    max_flip_rate: float = 0.30,
) -> tuple[bool, float]:
    """
    滚动稳定性检验 (§5.3.2)。

    使用 6 个月（约 126 交易日）滚动窗口计算反转后 IC。
    通过条件：滚动 IC 窗口正负翻转率 < max_flip_rate。
    翻转率 = 翻转次数 / (总窗口数 - 1)

    Parameters
    ----------
    reversed_ic : 反转后 IC 序列
    roll_window : 滚动窗口（默认 126 = 半年）
    max_flip_rate : 最大允许翻转率（默认 0.30 = 30%）

    Returns
    -------
    tuple:
      - passed: bool
      - flip_rate: float — 实际翻转率
    """
    n = len(reversed_ic)
    if n < roll_window + 2:
        return False, 1.0

    rolling_mean = np.full(n, np.nan)
    for i in range(roll_window, n):
        window = reversed_ic[i - roll_window:i + 1]
        rolling_mean[i] = np.nanmean(window)

    rolling_clean = rolling_mean[~np.isnan(rolling_mean)]

    if len(rolling_clean) < 2:
        return False, 1.0

    # 统计正负切换次数
    sign = np.sign(rolling_clean)
    flips = np.sum(np.abs(np.diff(sign)) > 0.5)  # sign change detection
    total_windows = len(rolling_clean) - 1

    flip_rate = flips / total_windows if total_windows > 0 else 1.0
    passed = flip_rate < max_flip_rate

    return passed, float(flip_rate)


def check_cross_sectional_stability(
    ic_by_stock: dict[str, np.ndarray],
    min_agree: int = 8,
    n_stocks: int = 12,
) -> tuple[bool, dict[str, float]]:
    """
    标的交叉稳定性检验 (§5.3.3)。

    统计各标的的反转后 IC 方向一致性。
    通过条件：≥ min_agree 个标的 IC 方向一致。

    Parameters
    ----------
    ic_by_stock : {stock_code: reversed_ic_series}
    min_agree : 最少一致标的数（默认 8）
    n_stocks : 总标数（默认 12）

    Returns
    -------
    tuple:
      - passed: bool
      - stock_ic_means: dict {code: mean_ic}
    """
    stock_ic_means: dict[str, float] = {}
    for code, ic_series in ic_by_stock.items():
        ic_clean = ic_series[~np.isnan(ic_series)]
        if len(ic_clean) > 0:
            stock_ic_means[code] = float(np.mean(ic_clean))
        else:
            stock_ic_means[code] = 0.0

    n_positive = sum(1 for v in stock_ic_means.values() if v > 0)
    n_negative = sum(1 for v in stock_ic_means.values() if v < 0)
    max_agree = max(n_positive, n_negative)

    passed = max_agree >= min_agree
    return passed, stock_ic_means


def check_oos_stability(
    is_ic_mean: float,
    oos_ic_mean: float,
) -> bool:
    """
    样本外稳定性检验 (§5.3.4)。

    通过条件：OOS 方向与 IS 一致（IC 符号一致，不要求 p 值）。

    Parameters
    ----------
    is_ic_mean : 样本内 IC 均值
    oos_ic_mean : 样本外 IC 均值

    Returns
    -------
    bool : 是否通过
    """
    return (is_ic_mean > 0 and oos_ic_mean > 0) or \
           (is_ic_mean < 0 and oos_ic_mean < 0)
