"""
comparison_test_helper.py — 新旧系统对比测试基础设施 (D1)

提供：
- df_to_bars()  : DataFrame → List[Bar] 转换
- extract_signals() : 从旧系统函数输出提取 signal 列表
- compare_deviation() : 计算新老系统 signal 偏差
"""

import sys
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.backtest_engine import Bar

from collections import namedtuple


def df_to_bars(df: pd.DataFrame) -> List[Bar]:
    """将 OHLCV DataFrame 转换为 Bar 对象列表。

    Args:
        df: 包含 open/high/low/close/volume 列的 DataFrame，索引为日期字符串。

    Returns:
        List[Bar]: 按时间升序排列的 Bar 列表。
    """
    bars: List[Bar] = []
    for idx in df.index:
        row = df.loc[idx]
        date_str = str(idx)
        if isinstance(idx, pd.Timestamp):
            date_str = idx.strftime("%Y-%m-%d")
        bars.append(
            Bar(
                date=date_str,
                symbol="TEST",
                open=float(row.get("open", row.get("close", 0))),
                high=float(row.get("high", row.get("close", 0))),
                low=float(row.get("low", row.get("close", 0))),
                close=float(row.get("close", 0)),
                volume=float(row.get("volume", 0)),
                vwap=float(row.get("vwap", 0.0)),
            )
        )
    return bars


def extract_signals(old_result: List[Dict[str, Any]]) -> List[int]:
    """从旧系统函数输出中提取 signal 列表。

    Args:
        old_result: 旧系统函数返回的 List[Dict]，每项包含 "signal" 键。

    Returns:
        List[int]: signal 值列表。
    """
    return [r["signal"] for r in old_result]


def compute_deviation(
    old_signals: List[int], new_signal_series: pd.Series
) -> Dict[str, float]:
    """计算新老系统 signal 偏差统计。

    Args:
        old_signals: 旧系统 signal 列表（长度 n）。
        new_signal_series: 新方法 signal Series（长度 n）。

    Returns:
        dict: {mean_abs_diff, max_abs_diff, mse, pass_rate}
    """
    n = min(len(old_signals), len(new_signal_series))
    old_arr = np.array(old_signals[:n], dtype=float)
    new_arr = new_signal_series.iloc[:n].values.astype(float)

    diff = np.abs(old_arr - new_arr)
    mask = ~np.isnan(diff)
    if mask.sum() == 0:
        return {"mean_abs_diff": 0.0, "max_abs_diff": 0.0, "mse": 0.0, "pass_rate": 1.0}

    diff_valid = diff[mask]
    return {
        "mean_abs_diff": float(np.mean(diff_valid)),
        "max_abs_diff": float(np.max(diff_valid)),
        "mse": float(np.mean(diff_valid ** 2)),
        "pass_rate": float(1.0 - np.mean(diff_valid > 0)),  # 完全一致率
    }


def assert_deviation_under_threshold(
    old_signals: List[int],
    new_signal_series: pd.Series,
    threshold: float = 0.005,
    method_name: str = "unknown",
) -> None:
    """断言新旧 signal 偏差小于阈值。

    辅助函数用于 D2-D13 测试。

    Args:
        old_signals: 旧系统 signal 列表。
        new_signal_series: 新方法 signal Series。
        threshold: 最大允许平均绝对偏差（默认 0.005 = 0.5%）。
        method_name: 方法名，用于错误消息。
    """
    stats = compute_deviation(old_signals, new_signal_series)
    assert stats["mean_abs_diff"] < threshold, (
        f"[{method_name}] 平均偏差 {stats['mean_abs_diff']:.6f} 超过阈值 {threshold}。"
        f" max_abs_diff={stats['max_abs_diff']:.6f}, mse={stats['mse']:.6f}"
    )
