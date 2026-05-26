"""
EXP-2026-INVFAC-002: Bootstrap 置换检验 + 多持有期前向 IC
==============================================================
author: 墨衡 (moheng)
created: 2026-05-25T17:10+08:00

实现实验设计 §3.3 和 §3.4 的统计检验函数。

函数清单:
  - bootstrap_ic_test(factor_values, forward_returns, n_bootstrap, alpha)
    → Bootstrap 置换检验
  - compute_forward_ic(factor_series, forward_returns, periods)
    → 多持有期前向 IC 计算
  - spearman_correlation(x, y)
    → Spearman 秩相关系数

依赖: numpy
"""

from __future__ import annotations

import numpy as np
from typing import Dict


def spearman_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """
    计算 Spearman 秩相关系数（无 scipy 依赖）。

    Parameters
    ----------
    x, y : 等长序列

    Returns
    -------
    float : Spearman rho
    """
    n = len(x)
    if n < 3:
        return 0.0

    # 秩转换
    x_rank = np.argsort(np.argsort(x)).astype(float)
    y_rank = np.argsort(np.argsort(y)).astype(float)

    d = x_rank - y_rank
    d2 = np.sum(d ** 2)

    rho = 1.0 - (6.0 * d2) / (n * (n * n - 1.0))
    return rho


def bootstrap_ic_test(
    factor_values: np.ndarray,
    forward_returns: np.ndarray,
    n_bootstrap: int = 10000,
    alpha: float = 0.05,
    random_seed: int = 42,
) -> dict:
    """
    Bootstrap 置换检验 — 判断 IC 均值是否显著偏离 0 (§3.3)。

    零假设：IC 均值 = 0（反转信号无统计意义）。
    双尾检验。

    Parameters
    ----------
    factor_values : 因子值序列
    forward_returns : 前向收益序列（与 factor_values 等长）
    n_bootstrap : 置换次数（默认 10000）
    alpha : 显著性水平（默认 0.05）
    random_seed : 随机种子（默认 42，确保可复现）

    Returns
    -------
    dict:
      - p_value: 置换检验 p 值
      - significant: 是否显著（p < alpha）
      - ci_lower: 置信区间下限 (alpha/2)
      - ci_upper: 置信区间上限 (1 - alpha/2)
      - ic_mean: 原始 IC 均值
    """
    factor_values = np.asarray(factor_values, dtype=float)
    forward_returns = np.asarray(forward_returns, dtype=float)

    # 去除 NaN
    valid = ~(np.isnan(factor_values) | np.isnan(forward_returns))
    fv = factor_values[valid]
    fr = forward_returns[valid]
    n = len(fv)

    if n < 3:
        return {
            "p_value": 1.0,
            "significant": False,
            "ci_lower": -1.0,
            "ci_upper": 1.0,
            "ic_mean": 0.0,
        }

    # 原始 IC
    ic_mean = spearman_correlation(fv, fr)

    if n_bootstrap <= 0:
        return {
            "p_value": None,
            "significant": None,
            "ci_lower": None,
            "ci_upper": None,
            "ic_mean": ic_mean,
        }

    # 置换检验
    rng = np.random.default_rng(random_seed)
    bootstrap_means = np.zeros(n_bootstrap)

    for i in range(n_bootstrap):
        shuffled = rng.permutation(fv)
        bootstrap_means[i] = spearman_correlation(shuffled, fr)

    # 双尾 p 值
    p_value = np.mean(np.abs(bootstrap_means) >= np.abs(ic_mean))

    # 百分位置信区间
    ci_lower = np.percentile(bootstrap_means, alpha / 2 * 100)
    ci_upper = np.percentile(bootstrap_means, (1 - alpha / 2) * 100)

    return {
        "p_value": float(p_value),
        "significant": bool(p_value < alpha),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "ic_mean": float(ic_mean),
    }


def compute_forward_ic(
    factor_series: np.ndarray,
    forward_returns: np.ndarray,
    periods: list[int] = [5, 10, 20],
) -> dict[int, np.ndarray]:
    """
    计算多个持有期的前向 IC 序列 (§3.4)。

    对每个持有期，计算因子值与未来 period 日的收益之间的滚动 Spearman IC。

    Parameters
    ----------
    factor_series : 因子值序列
    forward_returns : 日收益率序列（与 factor_series 等长）
    periods : 持有期列表（默认 [5, 10, 20]）

    Returns
    -------
    dict : {period: ic_series} — 每个持有期的 IC 滚动序列
    """
    factor_series = np.asarray(factor_series, dtype=float)
    forward_returns = np.asarray(forward_returns, dtype=float)
    n = len(factor_series)

    ic_by_period: dict[int, np.ndarray] = {}

    for period in periods:
        if period >= n:
            ic_by_period[period] = np.array([])
            continue

        ic_series = np.full(n, np.nan)
        for i in range(n - period):
            fv = factor_series[:i + 1]
            # 前向 period 日收益
            fwd_ret = np.full(i + 1, np.nan)
            for j in range(i + 1):
                if j + period < n:
                    fwd_ret[j] = np.prod(1 + forward_returns[j:j + period]) - 1

            # 计算 IC
            valid = ~(np.isnan(fv) | np.isnan(fwd_ret))
            if np.sum(valid) >= 3:
                ic_series[i] = spearman_correlation(fv[valid], fwd_ret[valid])

        ic_by_period[period] = ic_series

    return ic_by_period


def compute_forward_returns(
    close: np.ndarray,
    periods: list[int] = [5, 10, 20],
) -> dict[int, np.ndarray]:
    """
    计算多持有期前向收益率。

    用于 bootstrap_ic_test 和 compute_forward_ic 的输入准备。

    Parameters
    ----------
    close : 收盘价序列
    periods : 持有期列表

    Returns
    -------
    dict: {period: fwd_ret_series}
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    result: dict[int, np.ndarray] = {}
    for period in periods:
        fwd_ret = np.full(n, np.nan)
        for i in range(n - period):
            fwd_ret[i] = close[i + period] / close[i] - 1.0
        result[period] = fwd_ret
    return result
