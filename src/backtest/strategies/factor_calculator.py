"""
墨枢 - 趋势因子计算器（P2-05）

提供多种趋势强度指标供 TrendStrategy 调用：
  - ADX（平均趋向指数）：衡量趋势强度，值越大趋势越强
  - MA_Slope（均线斜率）：衡量趋势陡峭程度
  - Volatility_Ratio（波动率比）：当前波动率与历史波动率的比值
  - 综合趋势评分（composite_score）：加权融合上述因子
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ============================================================
# 内部辅助
# ============================================================


def _tr(high: float, low: float, prev_close: float) -> float:
    """单个 True Range。"""
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _sma(values: List[float], period: int) -> List[Optional[float]]:
    """简单移动平均。"""
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result
    window_sum = sum(values[:period])
    result[period - 1] = window_sum / period
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        result[i] = window_sum / period
    return result


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    """指数移动平均（带NaN隔离防护）。"""
    from src.core.ema_nan_safe import ema_nan_safe
    return ema_nan_safe(values, period, min_periods=period, use_pandas=False)


# ============================================================
# 单个因子计算
# ============================================================


def calc_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> List[Optional[float]]:
    """
    计算 ADX（平均趋向指数）。

    ADX 范围 0~100：
      - ADX < 20  → 弱趋势 / 盘整
      - 20 <= ADX < 40 → 中等趋势
      - ADX >= 40 → 强趋势

    返回长度与输入一致，前 period 个为 None。
    """
    n = len(highs)
    if n < period + 1:
        return [None] * n

    # ── 1. 计算 +DM / -DM / TR ──────────────────────
    up_move: List[float] = [0.0] * n
    down_move: List[float] = [0.0] * n
    tr_values: List[float] = [0.0] * n

    for i in range(1, n):
        up_move[i] = highs[i] - highs[i - 1]
        down_move[i] = lows[i - 1] - lows[i]
        tr_values[i] = _tr(highs[i], lows[i], closes[i - 1])

    # ── 2. 平滑（Wilder 方法：修正 EMA）─────────────
    def wilder_smooth(raw: List[float], p: int) -> List[float]:
        out: List[float] = [0.0] * n
        out[p] = sum(raw[1 : p + 1])  # 第一个用简单均值
        for i in range(p + 1, n):
            out[i] = out[i - 1] - out[i - 1] / p + raw[i]
        return out

    tr_smooth = wilder_smooth(tr_values, period)
    up_smooth = wilder_smooth(up_move, period)
    down_smooth = wilder_smooth(down_move, period)

    # ── 3. 计算 +DI / -DI / DX ──────────────────────
    pdi: List[Optional[float]] = [None] * n
    ndi: List[Optional[float]] = [None] * n
    dx: List[Optional[float]] = [None] * n

    for i in range(period, n):
        if tr_smooth[i] != 0:
            pdi[i] = 100.0 * max(up_smooth[i], 0.0) / tr_smooth[i]
            ndi[i] = 100.0 * max(down_smooth[i], 0.0) / tr_smooth[i]
            di_sum = pdi[i] + ndi[i]
            if di_sum != 0:
                dx[i] = 100.0 * abs(pdi[i] - ndi[i]) / di_sum

    # ── 4. ADX = EMA of DX ──────────────────────────
    # 提取有效 DX 值
    valid_dx: List[float] = []
    valid_idx: List[int] = []
    for i in range(n):
        if dx[i] is not None:
            valid_dx.append(dx[i])
            valid_idx.append(i)

    adx_raw = _ema(valid_dx, period) if valid_dx else []

    adx: List[Optional[float]] = [None] * n
    for j, idx in enumerate(valid_idx):
        if j < len(adx_raw):
            adx[idx] = adx_raw[j]

    return adx


def calc_ma_slope(
    closes: List[float],
    ma_period: int = 20,
    slope_period: int = 5,
) -> List[Optional[float]]:
    """
    计算均线斜率（归一化后）。

    使用 SMA(ma_period) 作为基准，对其最近 slope_period 个值做
    线性回归得到斜率，然后除以当前价格做归一化。

    返回：斜率值（正值 = 上升趋势，负值 = 下降趋势）。
    """
    ma = _sma(closes, ma_period)
    n = len(closes)

    slope: List[Optional[float]] = [None] * n

    # 需要至少 ma_period + slope_period 个值
    start = ma_period + slope_period - 1
    if start >= n:
        return slope

    for i in range(start, n):
        # 取最近 slope_period 个有效 MA 值做线性回归
        segment: List[float] = []
        for j in range(i - slope_period + 1, i + 1):
            if ma[j] is not None:
                segment.append(ma[j])
        if len(segment) < 2:
            continue

        x_vals = list(range(len(segment)))
        x_mean = sum(x_vals) / len(x_vals)
        y_mean = sum(segment) / len(segment)

        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, segment))
        den = sum((x - x_mean) ** 2 for x in x_vals)

        if den == 0:
            continue

        raw_slope = num / den
        # 归一化：除以当前价格
        if closes[i] != 0:
            slope[i] = raw_slope / closes[i]

    return slope


def calc_volatility_ratio(
    closes: List[float],
    short_period: int = 5,
    long_period: int = 20,
) -> List[Optional[float]]:
    """
    计算波动率比（短期波动率 / 长期波动率）。

    波动率定义为对数收益率的标准差。
    ratio > 1 → 波动加剧；ratio < 1 → 波动衰减。
    """
    n = len(closes)
    if n < long_period + 1:
        return [None] * n

    # 对数收益率
    log_ret: List[float] = [0.0] * n
    for i in range(1, n):
        if closes[i - 1] > 0:
            log_ret[i] = math.log(closes[i] / closes[i - 1])
        else:
            log_ret[i] = 0.0

    result: List[Optional[float]] = [None] * n

    for i in range(long_period, n):
        short_start = i - short_period + 1
        short_vol = sum((r - sum(log_ret[short_start:i + 1]) / short_period) ** 2 for r in log_ret[short_start:i + 1])
        short_vol = math.sqrt(short_vol / short_period) if short_period > 0 else 0.0

        long_start = i - long_period + 1
        long_vol = sum((r - sum(log_ret[long_start:i + 1]) / long_period) ** 2 for r in log_ret[long_start:i + 1])
        long_vol = math.sqrt(long_vol / long_period) if long_period > 0 else 0.0

        if long_vol > 0:
            result[i] = short_vol / long_vol
        else:
            result[i] = 1.0

    return result


# ============================================================
# 综合趋势强度评分
# ============================================================


def compute_trend_score(
    bars: List[Any],
    adx_period: int = 14,
    ma_period: int = 20,
    slope_period: int = 5,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    综合趋势强度评分。

    融合三个因子：
      - ADX：趋势强度（0~100）
      - MA_Slope：趋势方向 & 陡峭度（归一化，范围 -1~1）
      - Volatility_Ratio：波动率状态

    评分规则：
      1. 各因子先映射到 [0, 1] 区间
      2. 加权求和得到 composite_score
      3. composite_score < threshold → 视为弱趋势

    参数
    ----------
    bars : List[Bar]
        按时间升序的 K 线列表。
    adx_period : int
        ADX 计算周期（默认 14）。
    ma_period : int
        均线周期（默认 20）。
    slope_period : int
        斜率计算窗口（默认 5）。
    weights : dict, optional
        各因子权重。默认 {"adx": 0.5, "ma_slope": 0.3, "vol_ratio": 0.2}。

    返回
    -------
    List[Dict[str, Any]]
        每条记录含:
          - date / symbol
          - adx, ma_slope, vol_ratio（原始因子值）
          - adx_score, slope_score, vol_score（归一化到 [0,1]）
          - composite_score（加权综合评分）
          - trend_direction（1=上升, -1=下降, 0=震荡）
    """
    if not bars:
        return []

    n = len(bars)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]

    # 默认权重
    default_weights = {"adx": 0.5, "ma_slope": 0.3, "vol_ratio": 0.2}
    if weights is None:
        weights = default_weights

    # ── 1. 计算各因子 ──────────────────────────────
    adx = calc_adx(highs, lows, closes, adx_period)
    ma_slope = calc_ma_slope(closes, ma_period, slope_period)
    vol_ratio = calc_volatility_ratio(closes)

    # ── 2. 因子归一化 & 合成 ──────────────────────
    result: List[Dict[str, Any]] = []

    for i in range(n):
        raw_adx = adx[i]
        raw_slope = ma_slope[i]
        raw_vol = vol_ratio[i]

        # ADX → [0,1]：0->0, 25->0.5, 50->1.0
        adx_score = min(raw_adx / 50.0, 1.0) if raw_adx is not None else 0.0

        # MA_Slope → [0,1]：取绝对值并映射，slope 0.001 左右为强趋势
        slope_abs = abs(raw_slope) if raw_slope is not None else 0.0
        # 经验值：0.005 对应满分的斜率
        slope_score = min(slope_abs / 0.005, 1.0)

        # Volatility_Ratio → [0,1]：越偏离 1.0 趋势越强
        # |ratio-1| = 0 → 0.0; |ratio-1| >= 0.5 → 1.0
        if raw_vol is not None:
            vol_dev = abs(raw_vol - 1.0)
            vol_score = min(vol_dev / 0.5, 1.0)
        else:
            vol_score = 0.0

        # 加权合成
        composite = (
            weights.get("adx", 0.5) * adx_score
            + weights.get("ma_slope", 0.3) * slope_score
            + weights.get("vol_ratio", 0.2) * vol_score
        )

        # 趋势方向
        if raw_slope is not None and raw_slope > 1e-8:
            direction = 1
        elif raw_slope is not None and raw_slope < -1e-8:
            direction = -1
        else:
            direction = 0

        result.append({
            "date": bars[i].date,
            "symbol": bars[i].symbol,
            "adx": raw_adx,
            "ma_slope": raw_slope,
            "vol_ratio": raw_vol,
            "adx_score": round(adx_score, 4),
            "slope_score": round(slope_score, 4),
            "vol_score": round(vol_score, 4),
            "composite_score": round(composite, 4),
            "trend_direction": direction,
        })

    return result
