"""
LQM — 流动性评价模块

基于 OHLCV 数据计算标的的流动性评价指标，为 GKV（门控验证）
和 RSM（共振状态机）提供流动性维度输入。

核心指标：
  1. 振幅（Amplitude）：(high - low) / prev_close × 100，衡量日内波动范围
  2. 成交量比（Volume Ratio）：当日成交量 / 滚动窗口平均成交量
  3. 换手率（Turnover Rate）：当日成交量 / 流通股本 × 100（流通股本需外部提供）
  4. 综合流动性评分（Liquidity Score）：[0, 1] 多维度加权

判定规则：
  - 振幅为 0（全天无波动）→ 流动性极差
  - 成交量比 < 0.5 → 流动性萎缩
  - 综合评分 < 0.3 → 流动性不足建议谨慎
  - 综合评分 >= 0.7 → 流动性充裕

Usage:
    >>> import pandas as pd
    >>> from src.resonance.lqm import compute
    >>> df = pd.DataFrame({"close": [...], "high": [...], "low": [...], "volume": [...]})
    >>> result = compute("601857.SH", df)
    >>> result.status
    <ModuleStatus.PASS: 'PASS'>
    >>> result.liquidity_score
    0.72

依赖:
    - src.resonance.constants: LOOKBACK_WINDOW, MAX_FILL_FORWARD
    - src.resonance.models: LQMResult, ModuleStatus

Author: moheng
Created: 2026-05-29T10:09:00+08:00
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from src.resonance.constants import (
    LOOKBACK_WINDOW,
    MAX_FILL_FORWARD,
)
from src.resonance.models import LQMResult, ModuleStatus

logger = logging.getLogger("resonance.lqm")

# ══════════════════════════════════════════════════════════
# 流动性评价参数
# ══════════════════════════════════════════════════════════

_MIN_DATA_POINTS: int = 2
"""计算所需的最少数据点数（至少 2 日以计算振幅和成交量比）。"""

_LIQUIDITY_AMPLITUDE_WEIGHT: float = 0.3
"""振幅在综合评分中的权重。振幅反映价格活跃度。"""

_LIQUIDITY_VOLUME_WEIGHT: float = 0.4
"""成交量比在综合评分中的权重。成交量是流动性的核心指标。"""

_LIQUIDITY_TURNOVER_WEIGHT: float = 0.3
"""换手率在综合评分中的权重。换手率反映交易活跃度。"""

_AMPLITUDE_IDEAL: float = 2.0
"""振幅理想值（百分比）。过大可能异常波动，过小表示流动性不足。"""

_AMPLITUDE_SCALE: float = 3.0
"""振幅评分衰减尺度。振幅偏离理想值时的衰减强度。"""

_VOLUME_RATIO_LOW: float = 0.5
"""成交量比低阈值。低于此值认为流动性严重萎缩。"""

_VOLUME_RATIO_HIGH: float = 1.5
"""成交量比高阈值。高于此值认为流动性充裕。"""

_TURNOVER_LIQUID: float = 1.0
"""换手率充裕阈值（百分比）。高于此值认为换手活跃。"""

_EPSILON: float = 1e-12
"""数值稳定性常数。"""


# ══════════════════════════════════════════════════════════
# 前值填充（复用 DCM 模式）
# ══════════════════════════════════════════════════════════


def fill_forward(
    values: NDArray[np.float64],
    max_fill: int = MAX_FILL_FORWARD,
) -> NDArray[np.float64]:
    """向前填充缺失值（NaN），最多填充 ``max_fill`` 个连续缺失。

    实现复用 DCM 模块相同策略，用于处理成交量/价格数据的短区间缺失。

    Args:
        values:  输入浮点数组，可包含 NaN。
        max_fill: 最大连续填充次数（默认 ``MAX_FILL_FORWARD=3``）。

    Returns:
        填充后的数组（返回新数组，不修改输入）。
    """
    if values.size == 0:
        return values.copy()

    out = values.copy()
    n = len(out)

    i = 0
    while i < n:
        if np.isnan(out[i]):
            j = i
            while j < n and np.isnan(out[j]):
                j += 1
            gap_len = j - i
            if i > 0:
                fill_len = min(gap_len, max_fill)
                out[i : i + fill_len] = out[i - 1]
            i = j
        else:
            i += 1

    return out


# ══════════════════════════════════════════════════════════
# 振幅计算
# ══════════════════════════════════════════════════════════


def compute_amplitude(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
) -> NDArray[np.float64]:
    """计算每日振幅（百分比）。

    使用前收盘价作为基准，而非当日收盘价：
      amplitude_i = (high_i - low_i) / prev_close_i × 100

    第一个元素为 NaN（无前一日的收盘价作为基准）。

    Args:
        high:  最高价序列（至少 2 个元素）。
        low:   最低价序列（长度同 high）。
        close: 收盘价序列（长度同 high）。

    Returns:
        NDArray[np.float64]: 每日振幅数组（百分比）。
            - 长度同 high
            - 索引 0 为 NaN（无前日收盘价基准）
            - 后续元素可能为 NaN（前日收盘价 <= 0 或当日价格为 0）

    Raises:
        ValueError: 数组长度不足 2 或长度不一致。
    """
    n = len(high)
    if n < _MIN_DATA_POINTS:
        raise ValueError(f"数据点不足 ({n} < {_MIN_DATA_POINTS})")
    if not (len(low) == n and len(close) == n):
        raise ValueError("high / low / close 长度不一致")

    prev_close = close[:-1]
    curr_high = high[1:]
    curr_low = low[1:]

    amplitude = np.full(n, np.nan, dtype=np.float64)

    valid_mask = (prev_close > _EPSILON) & (curr_high > _EPSILON) & (curr_low > _EPSILON)
    amplitude[1:][valid_mask] = (
        (curr_high[valid_mask] - curr_low[valid_mask]) / prev_close[valid_mask] * 100.0
    )

    return amplitude


# ══════════════════════════════════════════════════════════
# 滚动平均成交量
# ══════════════════════════════════════════════════════════


def rolling_avg_volume(
    volume: NDArray[np.float64],
    window: int = LOOKBACK_WINDOW,
) -> NDArray[np.float64]:
    """计算滚动平均成交量。

    对每个位置 i（i >= window - 1），计算前 window 个有效成交量的均值。
    窗口内有效数据点不足 window 个时返回 NaN。

    Args:
        volume: 成交量序列（升序，至少 window 个元素）。
        window: 滚动窗口大小，默认 ``LOOKBACK_WINDOW``（20）。

    Returns:
        NDArray[np.float64]: 滚动平均成交量数组。
            - 长度同 volume
            - 前 window - 1 个元素为 NaN（窗口未满）
            - 包含 NaN 的窗口 → 该位置返回 NaN
    """
    n = len(volume)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < window:
        return out

    for i in range(window - 1, n):
        segment = volume[i - window + 1 : i + 1]
        if np.all(np.isfinite(segment)):
            out[i] = np.mean(segment)
        # else: 保持 NaN（窗口含无效成交量）

    return out


# ══════════════════════════════════════════════════════════
# 成交量比计算
# ══════════════════════════════════════════════════════════


def compute_volume_ratio(
    volume: NDArray[np.float64],
    window: int = LOOKBACK_WINDOW,
) -> NDArray[np.float64]:
    """计算每日成交量比 = 当日成交量 / 滚动窗口平均成交量。

    Args:
        volume: 成交量序列（升序，至少 window 个元素）。
        window: 滚动窗口大小，默认 ``LOOKBACK_WINDOW``（20）。

    Returns:
        NDArray[np.float64]: 成交量比序列。
            - 长度同 volume
            - 前 window - 1 个元素为 NaN（窗口未满）
            - 滚动平均为 0 时返回 0（防止除零）
    """
    avg_vol = rolling_avg_volume(volume, window=window)
    ratio = np.full_like(volume, np.nan, dtype=np.float64)

    valid_mask = np.isfinite(avg_vol) & (avg_vol > _EPSILON)
    ratio[valid_mask] = volume[valid_mask] / avg_vol[valid_mask]
    # 滚动平均为 0 但 volume 也为 0 时 → 0
    zero_avg_mask = np.isfinite(avg_vol) & (avg_vol <= _EPSILON) & np.isfinite(volume)
    ratio[zero_avg_mask] = 0.0

    return ratio


# ══════════════════════════════════════════════════════════
# 换手率计算
# ══════════════════════════════════════════════════════════


def compute_turnover_rate(
    volume: NDArray[np.float64],
    outstanding_shares: float,
) -> NDArray[np.float64]:
    """计算每日换手率（百分比）。

    换手率 = 成交量 / 流通股本 × 100。

    Args:
        volume: 成交量序列。
        outstanding_shares: 流通股本。若为 0 或负值，全序列返回 -1.0（表示数据不可用）。

    Returns:
        NDArray[np.float64]: 换手率序列（百分比）。
            若流通股本不可用则全部返回 -1.0。
    """
    n = len(volume)
    if outstanding_shares <= _EPSILON:
        return np.full(n, -1.0, dtype=np.float64)

    return volume / outstanding_shares * 100.0


# ══════════════════════════════════════════════════════════
# 流动性各维度评分
# ══════════════════════════════════════════════════════════


def _score_amplitude(amplitude: float) -> float:
    """振幅评分 [0, 1]。

    以 _AMPLITUDE_IDEAL (2%) 为理想值，偏离越远得分越低。
    使用高斯型衰减：score = exp(-|amplitude - ideal| / scale)。

    Args:
        amplitude: 当日振幅（百分比）。

    Returns:
        float: [0, 1] 的评分。NaN → 0.5（中性）。
    """
    if not np.isfinite(amplitude):
        return 0.5
    deviation = abs(amplitude - _AMPLITUDE_IDEAL)
    return float(np.exp(-deviation / _AMPLITUDE_SCALE))


def _score_volume_ratio(ratio: float) -> float:
    """成交量比评分 [0, 1]。

    线性分段：
      - ratio <= _VOLUME_RATIO_LOW (0.5) → 0.0（流动性严重不足）
      - ratio >= _VOLUME_RATIO_HIGH (1.5) → 1.0（流动性充裕）
      - 中间线性插值

    Args:
        ratio: 成交量比。

    Returns:
        float: [0, 1] 的评分。NaN → 0.5（中性）。
    """
    if not np.isfinite(ratio):
        return 0.5
    if ratio <= _VOLUME_RATIO_LOW:
        return 0.0
    if ratio >= _VOLUME_RATIO_HIGH:
        return 1.0
    return (ratio - _VOLUME_RATIO_LOW) / (_VOLUME_RATIO_HIGH - _VOLUME_RATIO_LOW)


def _score_turnover_rate(turnover: float) -> float:
    """换手率评分 [0, 1]。

    线性分段：
      - turnover < 0 → 0.5（数据不可用，中性评分）
      - turnover >= _TURNOVER_LIQUID (1.0%) → 1.0（换手活跃）
      - 0 ~ 1% 线性插值

    Args:
        turnover: 换手率（百分比）。

    Returns:
        float: [0, 1] 的评分。
    """
    if not np.isfinite(turnover):
        return 0.5
    if turnover < 0:
        # 负值表示数据不可用（流通股本未提供）→ 中性评分
        return 0.5
    if turnover >= _TURNOVER_LIQUID:
        return 1.0
    return turnover / _TURNOVER_LIQUID


# ══════════════════════════════════════════════════════════
# 综合流动性评分
# ══════════════════════════════════════════════════════════


def compute_liquidity_score(
    amplitude: float,
    volume_ratio: float,
    turnover_rate: float,
) -> float:
    """计算综合流动性评分 [0, 1]。

    加权组合各维度评分：
      score = w_amp × s_amp + w_vol × s_vol + w_turn × s_turn

    权重见模块参数常量（_LIQUIDITY_*_WEIGHT），总和为 1.0。

    Args:
        amplitude:    当日振幅（百分比）。
        volume_ratio: 成交量比。
        turnover_rate: 换手率（百分比），-1.0 表示数据不可用。

    Returns:
        float: [0, 1] 综合流动性评分。
    """
    s_amp = _score_amplitude(amplitude)
    s_vol = _score_volume_ratio(volume_ratio)
    s_turn = _score_turnover_rate(turnover_rate)

    # 换手率可用时（>= 0）按标准权重计算
    if turnover_rate >= 0:
        score = (
            _LIQUIDITY_AMPLITUDE_WEIGHT * s_amp
            + _LIQUIDITY_VOLUME_WEIGHT * s_vol
            + _LIQUIDITY_TURNOVER_WEIGHT * s_turn
        )
    else:
        # 换手率不可用时，权重重新分配到成交量比和振幅
        total_weight = _LIQUIDITY_AMPLITUDE_WEIGHT + _LIQUIDITY_VOLUME_WEIGHT
        score = (
            _LIQUIDITY_AMPLITUDE_WEIGHT * s_amp
            + _LIQUIDITY_VOLUME_WEIGHT * s_vol
        ) / total_weight

    return float(np.clip(score, 0.0, 1.0))


# ══════════════════════════════════════════════════════════
# 主入口：compute
# ══════════════════════════════════════════════════════════


def compute(
    ticker: str,
    df: pd.DataFrame,
    *,
    window: int = LOOKBACK_WINDOW,
    max_fill: int = MAX_FILL_FORWARD,
    outstanding_shares: float = 0.0,
) -> LQMResult:
    """计算标的的流动性评价指标（LQM 模块主入口）。

    处理流程：
      1. 校验 OHLCV 数据完整性
      2. 前值填充成交量/价格缺失
      3. 计算每日振幅、成交量比、换手率
      4. 提取最新值，计算综合流动性评分
      5. 返回 LQMResult

    Args:
        ticker:             标的代码（如 ``'601857.SH'``），仅用于日志/错误追踪。
        df:                 OHLCV DataFrame。必须包含 ``close``, ``high``, ``low``,
                            ``volume`` 列。按日期升序排列。
        window:             成交量滚动窗口大小（默认 ``LOOKBACK_WINDOW=20``）。
                            可通过关键字参数覆盖。
        max_fill:           前值填充最大连续缺失数（默认 ``MAX_FILL_FORWARD=3``）。
                            可通过关键字参数覆盖。
        outstanding_shares: 流通股本（股数）。若为 0 或负值，换手率返回 -1.0
                            （不参与评分降权处理）。默认 0.0。

    Returns:
        LQMResult:
          - amplitude:       当日振幅（百分比）。数据不足时为 0.0。
          - volume_ratio:    成交量比。数据不足时为 0.0。
          - turnover_rate:   换手率（百分比）。流通股本不可用时为 -1.0。
          - liquidity_score: 综合流动性评分 [0, 1]。
          - status:          PASS（成功）、FAILED（数据不足/无效）或
                             SKIPPED（空数据）。

    状态判定逻辑：
      - df 为空/缺少必需列                         → SKIPPED
      - 必要列全 NaN                              → SKIPPED
      - 数据行数 < 2                                → FAILED
      - 振幅最新值为 NaN 且无其他有效值               → FAILED
      - 有部分有效数据但最新值计算正常                → PASS

    Example:
        >>> df = pd.DataFrame({
        ...     "close": [10.0, 10.5, 10.3, 10.8, 10.6],
        ...     "high":  [10.2, 10.7, 10.5, 11.0, 10.8],
        ...     "low":   [9.8,  10.3, 10.1, 10.6, 10.4],
        ...     "volume":[1e6, 1.2e6, 0.9e6, 1.5e6, 1.1e6],
        ... })
        >>> result = compute("601857.SH", df, window=3)
        >>> result.status == ModuleStatus.PASS
        True
        >>> 0 <= result.liquidity_score <= 1
        True
    """
    # ── 空数据 / 无效输入检查 ────────
    if df is None or (hasattr(df, "empty") and df.empty):
        logger.warning("LQM [%s]: DataFrame 为空，返回 SKIPPED", ticker)
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.SKIPPED,
        )

    required_cols = ["close", "high", "low", "volume"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.warning(
            "LQM [%s]: 缺少必需列 %s，返回 SKIPPED", ticker, missing,
        )
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.SKIPPED,
        )

    # ── 提取并验证数据 ────────────────
    close_arr = df["close"].to_numpy(dtype=np.float64)
    high_arr = df["high"].to_numpy(dtype=np.float64)
    low_arr = df["low"].to_numpy(dtype=np.float64)
    volume_arr = df["volume"].to_numpy(dtype=np.float64)

    n = len(close_arr)
    if n < _MIN_DATA_POINTS:
        logger.error(
            "LQM [%s]: 数据行数不足（%d < %d），返回 FAILED",
            ticker, n, _MIN_DATA_POINTS,
        )
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.FAILED,
        )

    if np.all(np.isnan(close_arr)):
        logger.warning("LQM [%s]: close 全部为 NaN，返回 SKIPPED", ticker)
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.SKIPPED,
        )

    # ── Step 1: 前值填充缺失值 ──────
    close_filled = fill_forward(close_arr, max_fill=max_fill)
    high_filled = fill_forward(high_arr, max_fill=max_fill)
    low_filled = fill_forward(low_arr, max_fill=max_fill)
    volume_filled = fill_forward(volume_arr, max_fill=max_fill)

    # 填充后检查
    if np.all(np.isnan(close_filled)):
        logger.warning("LQM [%s]: 填充后 close 全部为 NaN，返回 SKIPPED", ticker)
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.SKIPPED,
        )

    # ── Step 2: 计算振幅 ────────────
    try:
        amplitude_series = compute_amplitude(high_filled, low_filled, close_filled)
    except ValueError as exc:
        logger.error("LQM [%s]: 振幅计算失败: %s", ticker, exc)
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.FAILED,
        )

    # ── Step 3: 计算成交量比 ─────────
    # 成交量比需要滚动窗口计算，取最新有效值
    volume_ratio_series = compute_volume_ratio(volume_filled, window=window)

    # ── Step 4: 计算换手率 ───────────
    turnover_series = compute_turnover_rate(volume_filled, outstanding_shares)

    # ── Step 5: 提取最新有效值 ──────
    # 振幅：取最后一个有效（非 NaN）值
    finite_amp = np.where(np.isfinite(amplitude_series))[0]
    if len(finite_amp) == 0:
        logger.error(
            "LQM [%s]: 振幅序列全部为 NaN（数据质量异常），返回 FAILED",
            ticker,
        )
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.FAILED,
        )
    latest_amplitude = amplitude_series[finite_amp[-1]]

    # 成交量比：取最后一个有效值
    finite_vr = np.where(np.isfinite(volume_ratio_series))[0]
    if len(finite_vr) == 0:
        logger.error(
            "LQM [%s]: 成交量比序列全部为 NaN（数据量不足），返回 FAILED",
            ticker,
        )
        return LQMResult(
            amplitude=0.0,
            volume_ratio=0.0,
            turnover_rate=-1.0,
            liquidity_score=0.0,
            status=ModuleStatus.FAILED,
        )
    latest_volume_ratio = volume_ratio_series[finite_vr[-1]]

    # 换手率：取最后一个有效值
    finite_tr = np.where(np.isfinite(turnover_series))[0]
    latest_turnover = turnover_series[finite_tr[-1]] if len(finite_tr) > 0 else -1.0

    # ── Step 6: 综合流动性评分 ──────
    liquidity_score = compute_liquidity_score(
        latest_amplitude, latest_volume_ratio, latest_turnover,
    )

    logger.info(
        "LQM [%s]: 振幅=%.2f%%, 成交量比=%.2f, 换手率=%.2f%%, "
        "流动性评分=%.4f (窗口=%d日)",
        ticker, latest_amplitude, latest_volume_ratio,
        latest_turnover, liquidity_score, window,
    )

    return LQMResult(
        amplitude=float(latest_amplitude),
        volume_ratio=float(latest_volume_ratio),
        turnover_rate=float(latest_turnover),
        liquidity_score=liquidity_score,
        status=ModuleStatus.PASS,
    )


# ══════════════════════════════════════════════════════════
# 便捷接口：从原始数组计算
# ══════════════════════════════════════════════════════════


def compute_from_arrays(
    ticker: str,
    close: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    volume: NDArray[np.float64],
    *,
    window: int = LOOKBACK_WINDOW,
    max_fill: int = MAX_FILL_FORWARD,
    outstanding_shares: float = 0.0,
) -> LQMResult:
    """从原始 numpy 数组计算流动性评价（便捷接口）。

    适用于不经过 DataFrame 的调用场景（如回测循环中的批量计算）。

    Args:
        ticker:             标的代码。
        close:              收盘价序列。
        high:               最高价序列。
        low:                最低价序列。
        volume:             成交量序列。
        window:             成交量滚动窗口大小。
        max_fill:           前值填充最大连续缺失数。
        outstanding_shares: 流通股本（股数）。默认 0.0。

    Returns:
        LQMResult: 同 ``compute()`` 返回值。
    """
    # 构造临时 DataFrame 后调用 compute()
    import pandas as pd  # noqa: PLC0415

    df = pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
    })
    return compute(
        ticker, df,
        window=window,
        max_fill=max_fill,
        outstanding_shares=outstanding_shares,
    )
