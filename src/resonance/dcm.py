"""
DCM — 波动率代理模块

计算标的 LOOKBACK_WINDOW（20日）滚动年化历史波动率（HV），
为 ZNM（z-score 归一化）和 GKV（门控验证）提供波动率基础数据。

核心逻辑：
  1. 日度对数收益率：r_t = ln(close_t / close_{t-1})
  2. 滚动窗口标准差（LOOKBACK_WINDOW），年化（sqrt(ANNUALIZATION_FACTOR)）
  3. 前值填充（MAX_FILL_FORWARD），处理短区间缺失

Usage:
    >>> import numpy as np
    >>> from src.resonance.dcm import compute
    >>> prices = np.array([...], dtype=np.float64)
    >>> result = compute("601857.SH", prices)
    >>> result.status
    <ModuleStatus.PASS: 'PASS'>
    >>> result.volatility
    0.2538

依赖:
    - src.resonance.constants: LOOKBACK_WINDOW, ANNUALIZATION_FACTOR, MAX_FILL_FORWARD
    - src.resonance.models: DCMResult, ModuleStatus

Author: moheng
Created: 2026-05-29T10:01:00+08:00
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from numpy.typing import NDArray

from src.resonance.constants import (
    ANNUALIZATION_FACTOR,
    LOOKBACK_WINDOW,
    MAX_FILL_FORWARD,
)
from src.resonance.models import DCMResult, ModuleStatus

logger = logging.getLogger("resonance.dcm")

# ══════════════════════════════════════════════════════════
# 波动率计算参数
# ══════════════════════════════════════════════════════════

# 计算 log return 所需的最小数据点（2 日：前收盘 + 当日收盘）
_MIN_RETURN_POINTS: int = 2

# 数值稳定性常数（避免 log(0) / 除零）
_EPSILON: float = 1e-12


# ══════════════════════════════════════════════════════════
# 前值填充
# ══════════════════════════════════════════════════════════


def fill_forward(
    values: NDArray[np.float64],
    max_fill: int = MAX_FILL_FORWARD,
) -> NDArray[np.float64]:
    """向前填充缺失值（NaN），最多填充 ``max_fill`` 个连续缺失。

    用于处理行情数据中的短区间价格缺失：
      - 单个 NaN → 取前值
      - 连续 NaN 长度 ≤ max_fill → 全部用最后一个有效值填充
      - 连续 NaN 长度 > max_fill → 超出部分保持 NaN
      - 首个值即为 NaN → 保持 NaN（没有前值可填充）

    Args:
        values:  输入浮点数组，可包含 NaN。
        max_fill: 最大连续填充次数（默认 MAX_FILL_FORWARD=3）。

    Returns:
        填充后的数组（返回新数组，不修改输入）。

    Example:
        >>> fill_forward(np.array([1.0, np.nan, np.nan, 4.0, np.nan]))
        array([1.0, 1.0, 1.0, 4.0, 4.0])

        # 超过 max_fill 限制的部分保持 NaN
        >>> fill_forward(np.array([1.0, np.nan, np.nan, np.nan, np.nan, 6.0]), max_fill=2)
        array([1.0, 1.0, 1.0, nan, nan, 6.0])
    """
    if values.size == 0:
        return values.copy()

    out = values.copy()
    n = len(out)

    i = 0
    while i < n:
        if np.isnan(out[i]):
            # 定位连续 NaN 块的起始和结束
            j = i
            while j < n and np.isnan(out[j]):
                j += 1
            gap_len = j - i

            if i > 0:
                # 有前值 → 填充不超过 max_fill
                fill_len = min(gap_len, max_fill)
                out[i : i + fill_len] = out[i - 1]
                # 超出 max_fill 的部分保持 NaN（不变）
            # i == 0：数组以 NaN 开头，不做任何填充
            i = j
        else:
            i += 1

    return out


# ══════════════════════════════════════════════════════════
# 对数收益率
# ══════════════════════════════════════════════════════════


def log_returns(
    close_prices: NDArray[np.float64],
) -> NDArray[np.float64]:
    """计算日度对数收益率序列。

    收益率 = ln(close_t / close_{t-1})。
    结果长度 = len(close_prices) - 1。

    使用 _EPSILON 避免 ln(0) / 除零异常：
      - 若 close_{t-1} <= 0 或 close_t <= 0，该位置返回 NaN。

    Args:
        close_prices: 收盘价序列（升序，至少 2 个元素）。

    Returns:
        NDArray[np.float64]: 对数收益率数组（长度 = n - 1）。
            NaN 表示异常值（价格为 0 或负值）。

    Raises:
        ValueError: close_prices 长度不足 2。
    """
    if close_prices.size < _MIN_RETURN_POINTS:
        raise ValueError(
            f"收盘价数据点不足（{close_prices.size} < {_MIN_RETURN_POINTS}）"
        )

    prev = close_prices[:-1]
    curr = close_prices[1:]

    # 保护：价格须为正数
    valid_mask = (prev > _EPSILON) & (curr > _EPSILON)
    ratio = np.full_like(prev, np.nan, dtype=np.float64)
    ratio[valid_mask] = curr[valid_mask] / prev[valid_mask]

    return np.log(ratio)


# ══════════════════════════════════════════════════════════
# 滚动年化历史波动率
# ══════════════════════════════════════════════════════════


def rolling_hv(
    log_ret: NDArray[np.float64],
    window: int = LOOKBACK_WINDOW,
    annualization: int = ANNUALIZATION_FACTOR,
) -> NDArray[np.float64]:
    """计算滚动年化历史波动率（HV = rolling_std × sqrt(annualization)）。

    用遍历方式（纯 Python 循环）计算每个滚动窗口的标准差，然后年化。

    Args:
        log_ret:          对数收益率序列。
        window:           滚动窗口大小，默认 LOOKBACK_WINDOW（20）。
        annualization:    年化因子，默认 ANNUALIZATION_FACTOR（252）。

    Returns:
        NDArray[np.float64]:
          - 长度为 len(log_ret) - window + 1
          - NaN 表示该窗口内存在 NaN 收益率（数据不足或价格异常）
          - 元素 i 对应 log_ret[i : i + window] 窗口的年化波动率

    Example:
        >>> log_ret = np.random.randn(100)
        >>> hv = rolling_hv(log_ret)
        >>> len(hv) == 100 - 20 + 1
        True
    """
    if log_ret.size < window:
        return np.array([], dtype=np.float64)

    n = log_ret.size
    out = np.full(n - window + 1, np.nan, dtype=np.float64)

    # 对每个窗口计算 std（忽略 NaN → 窗口含 NaN 则 std 为 NaN）
    for i in range(out.size):
        segment = log_ret[i : i + window]
        if np.all(np.isfinite(segment)):
            out[i] = np.std(segment, ddof=1) * np.sqrt(float(annualization))
        # else: 保持 NaN（至少有一个 NaN 收益率）

    return out


# ══════════════════════════════════════════════════════════
# 主入口：compute
# ══════════════════════════════════════════════════════════


def compute(
    ticker: str,
    close_prices: NDArray[np.float64],
    *,
    window: int = LOOKBACK_WINDOW,
    annualization: int = ANNUALIZATION_FACTOR,
    max_fill: int = MAX_FILL_FORWARD,
) -> DCMResult:
    """计算标的的滚动年化历史波动率（DCM 模块主入口）。

    处理流程：
      1. 前值填充缺失价格（max_fill 日限制）
      2. 计算日度对数收益率
      3. 滚动窗口标准差 → 年化
      4. 返回 DCMResult（含最新波动率 + 历史序列）

    Args:
        ticker:         标的代码（如 ``'601857.SH'``），仅用于日志/错误追踪。
        close_prices:   收盘价序列（numpy 浮点数组，至少 21 个元素）。
        window:         滚动窗口大小（默认 LOOKBACK_WINDOW=20）。可通过
                        关键字参数覆盖（参考 PipelineConfig.lookback_window）。
        annualization:  年化因子（默认 ANNUALIZATION_FACTOR=252）。可通过
                        关键字参数覆盖。
        max_fill:       前值填充最大连续缺失数（默认 MAX_FILL_FORWARD=3）。
                        可通过关键字参数覆盖。

    Returns:
        DCMResult:
          - volatility:           最新窗口的年化波动率（标量）。
          - volatility_history:   波动率历史序列（NDArray），长度 ≥ 1
                                  时包含最新值；数据不足时为空数组。
          - status:               PASS（成功）、FAILED（数据不足）或
                                  SKIPPED（空数据/全部 NaN）。

    数据不足判定：
      - close_prices 为空或全 NaN                    → SKIPPED
      - 有效数据点 < window + 1 (21)                 → FAILED
      - 年化后无有效波动率（全部 NaN）               → FAILED
      - 有部分有效波动率但最新值为 NaN               → PASS（使用最近有效值）

    Example:
        >>> prices = np.array([...], dtype=np.float64)  # 至少 21 个值
        >>> result = compute("601857.SH", prices)
        >>> result.status == ModuleStatus.PASS
        True
        >>> result.volatility > 0
        True
        >>> len(result.volatility_history) >= 1
        True
    """
    # ── 空数据 / 全 NaN 检查 ────────
    if close_prices.size == 0:
        logger.warning("DCM [%s]: close_prices 为空，返回 SKIPPED", ticker)
        return DCMResult(
            volatility=0.0,
            volatility_history=np.array([], dtype=np.float64),
            status=ModuleStatus.SKIPPED,
        )

    if np.all(np.isnan(close_prices)):
        logger.warning("DCM [%s]: close_prices 全部为 NaN，返回 SKIPPED", ticker)
        return DCMResult(
            volatility=0.0,
            volatility_history=np.array([], dtype=np.float64),
            status=ModuleStatus.SKIPPED,
        )

    # ── Step 1: 前值填充 ────────────
    filled = fill_forward(close_prices, max_fill=max_fill)

    if np.all(np.isnan(filled)):
        # 填充后仍全 NaN（说明全部价格都是 NaN，已被过滤）
        logger.warning("DCM [%s]: 填充后全部为 NaN，返回 SKIPPED", ticker)
        return DCMResult(
            volatility=0.0,
            volatility_history=np.array([], dtype=np.float64),
            status=ModuleStatus.SKIPPED,
        )

    # 有效收盘价计数（非 NaN）
    valid_count = int(np.sum(~np.isnan(filled)))
    min_required = window + 1

    if valid_count < min_required:
        logger.error(
            "DCM [%s]: 数据不足（有效 %d < 要求 %d），返回 FAILED",
            ticker, valid_count, window + 1,
        )
        return DCMResult(
            volatility=0.0,
            volatility_history=np.array([], dtype=np.float64),
            status=ModuleStatus.FAILED,
        )

    # ── Step 2: 对数收益率 ──────────
    try:
        lr = log_returns(filled)
    except ValueError as exc:
        logger.error("DCM [%s]: 收益率计算失败: %s", ticker, exc)
        return DCMResult(
            volatility=0.0,
            volatility_history=np.array([], dtype=np.float64),
            status=ModuleStatus.FAILED,
        )

    # ── Step 3: 滚动年化 HV ─────────
    hv_series = rolling_hv(lr, window=window, annualization=annualization)

    if hv_series.size == 0:
        logger.error(
            "DCM [%s]: 波动率序列为空（收益率长度 %d < 窗口 %d），返回 FAILED",
            ticker, lr.size, window,
        )
        return DCMResult(
            volatility=0.0,
            volatility_history=np.array([], dtype=np.float64),
            status=ModuleStatus.FAILED,
        )

    # ── Step 4: 提取最新波动率 ──────
    # 优先取最后一个有效（非 NaN）值；若全部 NaN 则返回 0（FAILED）
    finite_mask = np.isfinite(hv_series)

    if not np.any(finite_mask):
        logger.error(
            "DCM [%s]: 全部波动率值为 NaN（收益率序列质量异常），返回 FAILED",
            ticker,
        )
        return DCMResult(
            volatility=0.0,
            volatility_history=hv_series,
            status=ModuleStatus.FAILED,
        )

    # 取最后一个有效波动率值
    valid_indices = np.where(finite_mask)[0]
    latest_vol = hv_series[valid_indices[-1]]

    logger.info(
        "DCM [%s]: HV=%.4f（年化因子=%d, 窗口=%d日, 有效点=%d/%d）",
        ticker, latest_vol, annualization, window,
        valid_count, close_prices.size,
    )

    return DCMResult(
        volatility=float(latest_vol),
        volatility_history=hv_series,
        status=ModuleStatus.PASS,
    )


# ══════════════════════════════════════════════════════════
# 便捷接口
# ══════════════════════════════════════════════════════════


def compute_from_dataframe(
    ticker: str,
    df,
    *,
    close_column: str = "close",
    **kwargs,
) -> DCMResult:
    """从 OHLCV DataFrame 提取 ``close_column`` 列后调用 ``compute()``。

    提供与 ``data_bridge.fetch_ohlcv()`` 的便捷对接：
      1. 从 DataFrame 提取收盘价列
      2. 转换为 ``numpy.ndarray(dtype=np.float64)``
      3. 调用 ``compute(ticker, close_prices, **kwargs)``

    Args:
        ticker:        标的代码。
        df:            OHLCV DataFrame（必须包含 ``close_column`` 列）。
        close_column:  收盘价列名（默认 ``'close'``）。
        **kwargs:      传递给 ``compute()`` 的关键字参数（如 window / annualization
                       / max_fill 覆盖值）。

    Returns:
        DCMResult: 同 ``compute()`` 返回值。

    Raises:
        KeyError:      DataFrame 中不存在 ``close_column`` 列。
        ValueError:    DataFrame 为空。
    """
    if df is None or (hasattr(df, "empty") and df.empty):
        return DCMResult(
            volatility=0.0,
            volatility_history=np.array([], dtype=np.float64),
            status=ModuleStatus.SKIPPED,
        )

    if close_column not in df.columns:
        raise KeyError(
            f"DCM [ticker={ticker}]: DataFrame 缺少列 '{close_column}'"
        )

    close_prices = df[close_column].to_numpy(dtype=np.float64)
    return compute(ticker, close_prices, **kwargs)
