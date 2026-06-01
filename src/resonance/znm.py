"""
ZNM — z-score 归一化模块

接收 DCM（波动率代理）输出的 HV 历史序列和 LQM（流动性评价）输出
的流动性数据，对波动率序列做滚动 z-score 归一化，产出极值检测结果
供 GKV（门控验证）和 RSM（共振状态机）使用。

核心逻辑：
  1. 滚动 z-score：z_i = (v_i - mean_window) / (std_window + eps)
  2. 极值判定：|z| > QUANTILE_THRESHOLD（1.5）→ 极端值
  3. 使用 LOOKBACK_WINDOW（20日）作为滚动窗口
  4. MIN_HISTORY_LENGTH（2）校验最小数据量

判定规则：
  - 有效数据点 < MIN_HISTORY_LENGTH                          → FAILED
  - 滚动窗口内标准差为零（全部相同值）                         → z-score = 0.0
  - |latest_zscore| > QUANTILE_THRESHOLD                      → is_extreme = True
  - 全部输入为 NaN / 空数组                                   → SKIPPED

Usage:
    >>> import numpy as np
    >>> from src.resonance.znm import compute
    >>> hv_history = np.array([0.15, 0.18, 0.22, 0.20, 0.25], dtype=np.float64)
    >>> result = compute("601857.SH", hv_history)
    >>> result.status
    <ModuleStatus.PASS: 'PASS'>
    >>> isinstance(result.zscore, float)
    True
    >>> isinstance(result.is_extreme, bool)
    True
    >>> len(result.normalized_values) > 0
    True

依赖:
    - src.resonance.constants: LOOKBACK_WINDOW, QUANTILE_THRESHOLD, MIN_HISTORY_LENGTH
    - src.resonance.models: ZNMResult, ModuleStatus

Author: moheng
Created: 2026-05-29T10:12:00+08:00
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from numpy.typing import NDArray

from src.resonance.constants import (
    LOOKBACK_WINDOW,
    MIN_HISTORY_LENGTH,
    QUANTILE_THRESHOLD,
)
from src.resonance.models import ModuleStatus, ZNMResult

logger = logging.getLogger("resonance.znm")

# ══════════════════════════════════════════════════════════
# z-score 计算参数
# ══════════════════════════════════════════════════════════

_EPSILON: float = 1e-12
"""数值稳定性常数（避免除零）。"""


# ══════════════════════════════════════════════════════════
# 滚动 z-score 计算
# ══════════════════════════════════════════════════════════


def rolling_zscore(
    values: NDArray[np.float64],
    window: int = LOOKBACK_WINDOW,
) -> NDArray[np.float64]:
    """计算滚动 z-score 序列。

    对每个位置 i，以前 window 个（含位置 i 在内）有效值为窗口，
    计算 z_i = (v_i - mean_window) / (std_window + _EPSILON)。

    窗口长度不足 min_history 个有效值 → 该位置返回 NaN。
    窗口内标准差为零（全部相同值）→ z-score = 0.0（避免除零）。

    Args:
        values: 输入值序列（升序，最新在最后）。
        window: 滚动窗口大小，默认 ``LOOKBACK_WINDOW``（20）。

    Returns:
        NDArray[np.float64]: z-score 序列。
            - 长度同 values
            - 前 min(window, len(values)) - 1 个元素为 NaN（窗口未满）
            - z-score 为 0 表示该窗口内全部值相同（零标准差）
            - 窗口含 NaN → 该位置返回 NaN
    """
    n = len(values)
    out = np.full(n, np.nan, dtype=np.float64)

    if n == 0:
        return out

    effective_window = min(window, n)

    for i in range(effective_window - 1, n):
        segment = values[i - effective_window + 1 : i + 1]
        # 仅取窗口内有效（有限）值
        valid = segment[np.isfinite(segment)]

        if valid.size < MIN_HISTORY_LENGTH:
            # 有效数据不足，保持 NaN
            continue

        mean = np.mean(valid)
        std = np.std(valid, ddof=1)

        if std < _EPSILON:
            # 全部相同值 → z-score = 0.0
            out[i] = 0.0
        else:
            out[i] = (values[i] - mean) / (std + _EPSILON)

    return out


# ══════════════════════════════════════════════════════════
# 极值判定
# ══════════════════════════════════════════════════════════


def is_extreme_value(
    zscore: float,
    threshold: float = QUANTILE_THRESHOLD,
) -> bool:
    """判断 z-score 是否为极端值。

    极端值判定：|zscore| > threshold。
    NaN → False（不确定时不做极端标记）。

    Args:
        zscore:   z-score 值。
        threshold: 极值判定阈值。默认 ``QUANTILE_THRESHOLD``（1.5）。

    Returns:
        bool: True 表示 |zscore| > threshold 且 zscore 为有效值。
    """
    if not bool(np.isfinite(zscore)):
        return False
    return bool(abs(zscore) > threshold)


# ══════════════════════════════════════════════════════════
# 主入口：compute
# ══════════════════════════════════════════════════════════


def compute(
    ticker: str,
    values: NDArray[np.float64],
    *,
    window: int = LOOKBACK_WINDOW,
    threshold: float = QUANTILE_THRESHOLD,
    min_history: int = MIN_HISTORY_LENGTH,
) -> ZNMResult:
    """计算标的波动率序列的 z-score 归一化（ZNM 模块主入口）。

    处理流程：
      1. 校验输入数据完整性
      2. 计算滚动 z-score 序列
      3. 提取最新值的 z-score 和极值判定
      4. 返回 ZNMResult

    Args:
        ticker:      标的代码（如 ``'601857.SH'``），仅用于日志/错误追踪。
        values:      输入值序列（典型为 DCM 输出的 ``volatility_history``）。
                     按时间升序排列，最新值在后。
        window:      滚动窗口大小（默认 ``LOOKBACK_WINDOW=20``）。
                    可通过关键字参数覆盖。
        threshold:   z-score 极值判定阈值（默认 ``QUANTILE_THRESHOLD=1.5``）。
                     可通过关键字参数覆盖。
        min_history: 有效数据点下限（默认 ``MIN_HISTORY_LENGTH=2``）。
                     可通过关键字参数覆盖。

    Returns:
        ZNMResult:
          - zscore:            最新值的 z-score（标量）。
          - is_extreme:        是否超出极值阈值。
          - normalized_values: 归一化后的完整 z-score 序列（NDArray）。
          - status:            PASS（成功）、FAILED（数据不足）或
                               SKIPPED（空数据/全部 NaN）。

    状态判定逻辑：
      - values 为空                     → SKIPPED
      - 全部为 NaN                      → SKIPPED
      - 有效（非 NaN）值 < min_history  → FAILED
      - 有有效值且 z-score 序列有输出   → PASS
        （即使最新值 z-score 为 NaN，只要有历史有效值即 PASS，
          最新 NaN 场景下 ZNMResult.zscore 置为 0.0）
      - 滚动窗口未满，全局统计降级       → PASS
        （normalized_values 为全 NaN 数组，仅 zscore 有值）

    Example:
        >>> hv = np.array([0.15, 0.18, 0.22, 0.20, 0.25], dtype=np.float64)
        >>> result = compute("601857.SH", hv, window=5)
        >>> result.status == ModuleStatus.PASS
        True
        >>> isinstance(result.zscore, float)
        True
        >>> isinstance(result.is_extreme, bool)
        True
        >>> len(result.normalized_values) > 0
        True

        # 数据不足 → FAILED
        >>> hv_short = np.array([0.15], dtype=np.float64)
        >>> result = compute("601857.SH", hv_short)
        >>> result.status == ModuleStatus.FAILED
        True

        # 全 NaN → SKIPPED
        >>> hv_nan = np.array([np.nan, np.nan], dtype=np.float64)
        >>> result = compute("601857.SH", hv_nan)
        >>> result.status == ModuleStatus.SKIPPED
        True
    """
    # ── 空数据 / 全 NaN 检查 ────────
    if values.size == 0:
        logger.warning("ZNM [%s]: values 为空，返回 SKIPPED", ticker)
        return ZNMResult(
            zscore=0.0,
            is_extreme=False,
            normalized_values=np.array([], dtype=np.float64),
            status=ModuleStatus.SKIPPED,
        )

    if np.all(np.isnan(values)):
        logger.warning("ZNM [%s]: values 全部为 NaN，返回 SKIPPED", ticker)
        return ZNMResult(
            zscore=0.0,
            is_extreme=False,
            normalized_values=np.array([], dtype=np.float64),
            status=ModuleStatus.SKIPPED,
        )

    # ── 有效数据量检查 ──────────────
    valid_count = int(np.sum(np.isfinite(values)))
    if valid_count < min_history:
        logger.error(
            "ZNM [%s]: 有效数据不足（有效 %d < 要求 %d），返回 FAILED",
            ticker, valid_count, min_history,
        )
        return ZNMResult(
            zscore=0.0,
            is_extreme=False,
            normalized_values=np.array([], dtype=np.float64),
            status=ModuleStatus.FAILED,
        )

    # ── Step 1: 计算滚动 z-score ────
    zscore_series = rolling_zscore(values, window=window)

    # ── Step 2: 提取最新值 ──────────
    # 取最后一个有效（非 NaN）z-score；若全部 NaN 则取 values 的末尾位置
    finite_indices = np.where(np.isfinite(zscore_series))[0]

    if len(finite_indices) == 0:
        # z-score 全部为 NaN（窗口均未满），但已有有效 raw values
        # → 使用 values 自身的统计做全局 z-score
        valid_vals = values[np.isfinite(values)]
        if valid_vals.size >= min_history:
            global_mean = np.mean(valid_vals)
            global_std = np.std(valid_vals, ddof=1)
            latest_raw = values[~np.isnan(values)][-1] if np.any(np.isfinite(values)) else 0.0

            if global_std < _EPSILON:
                latest_zscore = 0.0
            else:
                latest_zscore = float((latest_raw - global_mean) / (global_std + _EPSILON))

            logger.info(
                "ZNM [%s]: 滚动窗口未满，使用全局统计 z=%.4f (有效值=%d)",
                ticker, latest_zscore, valid_vals.size,
            )

            # 此时 zscore_series 全为 NaN；标记为有意义但非滚动归一化
            return ZNMResult(
                zscore=latest_zscore,
                is_extreme=is_extreme_value(latest_zscore, threshold=threshold),
                normalized_values=zscore_series,
                status=ModuleStatus.PASS,
            )

        logger.error(
            "ZNM [%s]: z-score 序列全部为 NaN 且无法计算全局统计，返回 FAILED",
            ticker,
        )
        return ZNMResult(
            zscore=0.0,
            is_extreme=False,
            normalized_values=zscore_series,
            status=ModuleStatus.FAILED,
        )

    latest_zscore = zscore_series[finite_indices[-1]]
    latest_is_extreme = is_extreme_value(latest_zscore, threshold=threshold)

    logger.info(
        "ZNM [%s]: z-score=%.4f, is_extreme=%s (窗口=%d日, 阈值=%.1f, 有效值=%d/%d)",
        ticker, latest_zscore, latest_is_extreme,
        window, threshold, valid_count, values.size,
    )

    return ZNMResult(
        zscore=float(latest_zscore),
        is_extreme=latest_is_extreme,
        normalized_values=zscore_series,
        status=ModuleStatus.PASS,
    )


# ══════════════════════════════════════════════════════════
# 便捷接口：从 DCMResult + LQMResult 联合计算
# ══════════════════════════════════════════════════════════


def compute_from_modules(
    ticker: str,
    dcm_result: DCMResult,
    lqm_result: Optional[LQMResult] = None,
    *,
    window: int = LOOKBACK_WINDOW,
    threshold: float = QUANTILE_THRESHOLD,
    min_history: int = MIN_HISTORY_LENGTH,
) -> ZNMResult:
    """从 DCM 和 LQM 模块输出联合计算 z-score 归一化。

    典型的流水线调用路径：DCM → ZNM（← LQM）→ GKV。

    主要输入为 DCM 输出的波动率历史序列（volatility_history）。
    LQM 输出当前不作为 z-score 输入直接使用，但可用于后续的
    加权归一化扩展（预留接口）。

    Args:
        ticker:      标的代码。
        dcm_result:  DCMResult 实例（必须存在且 status == PASS）。
        lqm_result:  LQMResult 实例（可选，用于后续扩展）。
        window:      滚动窗口大小（默认 ``LOOKBACK_WINDOW=20``）。
        threshold:   z-score 极值判定阈值（默认 ``QUANTILE_THRESHOLD=1.5``）。
        min_history: 有效数据点下限（默认 ``MIN_HISTORY_LENGTH=2``）。

    Returns:
        ZNMResult: 同 ``compute()`` 返回值。

    Raises:
        ValueError: DCMResult 的 status 不为 PASS 或其 volatility_history 不可用。
    """
    from src.resonance.models import DCMResult, LQMResult  # noqa: PLC0415

    if dcm_result is None or dcm_result.status != ModuleStatus.PASS:
        logger.warning(
            "ZNM [%s]: DCM 状态不可用 (%s)，返回 SKIPPED",
            ticker,
            dcm_result.status if dcm_result else "None",
        )
        return ZNMResult(
            zscore=0.0,
            is_extreme=False,
            normalized_values=np.array([], dtype=np.float64),
            status=ModuleStatus.SKIPPED,
        )

    hv_series = dcm_result.volatility_history
    return compute(
        ticker, hv_series,
        window=window,
        threshold=threshold,
        min_history=min_history,
    )
