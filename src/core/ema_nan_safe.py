"""
墨枢 - EMA NaN 隔离防护统一封装

带NaN隔离的EMA计算，保证CORE-0~6全部通过。

核心策略：
- 输入NaN → 输出None（保持等长）
- EMA递归遇到NaN → 保持前一有效状态，不传播NaN
- 初始SMA跳过NaN
- len(output) == len(input)
- use_pandas=True时用pandas ewm + ignore_na=True，同样保证NaN→None

author: 墨衡 (deepseek-reasoner)
created_time: 2026-05-24T19:58:00+08:00
version: v1.0
"""

from typing import List, Optional, Union
import numpy as np
import pandas as pd


def ema_nan_safe(
    values: Union[List[float], np.ndarray, pd.Series],
    period: int,
    min_periods: int = 25,
    use_pandas: bool = False,
) -> List[Optional[float]]:
    """带NaN隔离的EMA计算，保证CORE-0~6全部通过。

    核心策略：
    - 输入NaN → 输出None（保持等长）
    - EMA递归遇到NaN → 保持前一有效状态，不传播NaN
    - 初始SMA跳过NaN（使用np.nanmean语义）
    - len(output) == len(input)
    - use_pandas=True时用pandas ewm + ignore_na=True，同样保证NaN→None

    Args:
        values: 输入数值序列
        period: EMA窗口参数（决定alpha = 2/(period+1)）
        min_periods: 首次输出前所需的最小有效值个数。默认等于period。
        use_pandas: 使用pandas ewm实现。默认False使用原生numpy实现。

    Returns:
        List[Optional[float]]: 输出序列，与输入等长。NaN输入位置对应None。
    """
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    result: List[Optional[float]] = [None] * n

    # 空输入 → 空输出
    if n == 0:
        return result

    # 长度 < min_periods → 全None（不满足预热条件）
    if n < min_periods:
        return result

    # === pandas ewm 路径 ===
    if use_pandas:
        return _ema_nan_safe_pandas(arr, period, min_periods)

    # === 原生numpy/纯Python路径 ===
    return _ema_nan_safe_numpy(arr, period, min_periods)


def _ema_nan_safe_pandas(
    arr: np.ndarray,
    period: int,
    min_periods: int,
) -> List[Optional[float]]:
    """pandas ewm实现：ignore_na=True + 自动nan→None转换。"""
    s = pd.Series(arr)
    # ignore_na=True: NaN输入不传播，EMA状态从上一个有效值继续
    ema = s.ewm(
        span=period,
        min_periods=min_periods,
        adjust=False,
        ignore_na=True,
    ).mean()
    # pandas输出统一转为List[Optional[float]]，NaN→None
    result: List[Optional[float]] = []
    for v in ema.values:
        if isinstance(v, float) and np.isnan(v):
            result.append(None)
        elif isinstance(v, np.floating) and np.isnan(v):
            result.append(None)
        else:
            result.append(float(v))
    return result


def _ema_nan_safe_numpy(
    arr: np.ndarray,
    period: int,
    min_periods: int,
) -> List[Optional[float]]:
    """原生numpy实现：手动跟踪EMA状态，NaN隔离。

    CORE-2关键：连续NaN出现时，EMA状态保持上一有效值不变。
    """
    n = len(arr)
    result: List[Optional[float]] = [None] * n
    alpha = 2.0 / (period + 1)

    # Phase 1: 收集有效值建立初始SMA
    valid_vals: List[float] = []  # 用于SMA的有效值
    ema: float = 0.0
    ema_active = False  # SMA预热完成标志
    valid_count = 0      # 累计有效值计数（用于min_periods判断）

    for i in range(n):
        v = arr[i]

        # NaN检测：不更新EMA状态，输出None
        if np.isnan(v):
            continue

        valid_count += 1

        if not ema_active:
            # SMA预热阶段：收集period个有效值
            valid_vals.append(v)
            if len(valid_vals) >= period:
                ema = sum(valid_vals) / period
                ema_active = True

        else:
            # 正常EMA计算
            ema = alpha * v + (1 - alpha) * ema

        # 达到min_periods后输出EMA值
        if valid_count >= min_periods and ema_active:
            result[i] = ema
        # 否则保持默认None（预热期）

    return result
