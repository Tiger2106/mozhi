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

    # 置换检验 — 优化版：fr_rank 外提（避免循环内重复 argsort）
    # P2: 锁定随机种子确保可复现
    np.random.seed(random_seed)
    rng = np.random.RandomState(random_seed)
    bootstrap_means = np.zeros(n_bootstrap)

    # 预计算 fr 的秩，循环内只需计算 shuffled 的秩
    fr_rank = np.argsort(np.argsort(fr)).astype(float)

    for i in range(n_bootstrap):
        shuffled = rng.permutation(fv)
        shuffled_rank = np.argsort(np.argsort(shuffled)).astype(float)
        d2 = np.sum((shuffled_rank - fr_rank) ** 2)
        bootstrap_means[i] = 1.0 - (6.0 * d2) / (n * (n * n - 1.0))

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


def apply_verdict_degradation(
    verdict: str,
    n_samples: int,
    threshold: int = 3000,
) -> tuple[str, str]:
    """
    样本量门限自动降级规则（验证期适用）。

    当验证期的样本量 n_samples < threshold 时，统计检验力受限，
    按以下规则自动降级 verdict：
      - PASS  → WARN
      - WARN  → FAIL
      - FAIL  → FAIL（不变）

    这是引擎层面的硬逻辑，用于预防因样本量不足导致的错误结论。

    Parameters
    ----------
    verdict : 原始 verdict（PASS / WARN / FAIL）
    n_samples : 该组合的实际样本量
    threshold : 样本量门限（默认 3000）

    Returns
    -------
    tuple[str, str]:
      - degraded_verdict: 降级后的 verdict
      - note: 降级原因标注（空字符串表示无需降级）
    """
    if n_samples >= threshold:
        return verdict, ""

    # 降级映射
    degradation_map = {
        "PASS": "WARN",
        "WARN": "FAIL",
        "FAIL": "FAIL",
    }

    note = (f"检验力受限，结论置信度降低"
            f"（n_samples={n_samples}<{threshold}，"
            f"verdict从{verdict}自动降级至{degradation_map.get(verdict, verdict)}）")

    return degradation_map.get(verdict, verdict), note


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
