"""
墨枢 - Regime 因子（R1 阶段一：第1组-4）

市场状态识别器。使用 ATR + ADX + 布林带宽度 + POC 判断当前市场所处的 5 种状态：
  - UPTREND：上涨趋势
  - DOWNTREND：下跌趋势
  - RANGE：横盘震荡
  - BREAKOUT：突破（区间突破的初期）
  - CLIMAX：高潮（加速后的极端状态，预示反转）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.backtest.factors.trend.trend_quality_factor import (
    calc_adx,
    calc_trend_strength,
)


def classify_regime(
    df: pd.DataFrame,
    adx_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    atr_period: int = 14,
    climax_threshold: float = 3.0,
) -> Dict[str, Any]:
    """
    识别当前市场状态。

    Parameters
    ----------
    df : pd.DataFrame
        必须包含 'high', 'low', 'close', 'volume' 列。
    adx_period : int
        ADX 周期。
    bb_period : int
        布林带周期。
    bb_std : float
        布林带标准差倍数。
    atr_period : int
        ATR 周期。
    climax_threshold : float
        高潮判断的 ATR 倍数阈值。

    Returns
    -------
    Dict[str, Any]
        {
            "regime": str,        # UPTREND / DOWNTREND / RANGE / BREAKOUT / CLIMAX / UNKNOWN
            "confidence": float,  # 0~1 置信度
            "evidence": Dict[str, Any]  # 判定依据
        }
    """
    n = len(df)
    if n < bb_period + atr_period:
        return {
            "regime": "UNKNOWN",
            "confidence": 0.0,
            "evidence": {"reason": "数据不足", "n": n},
        }

    # ── 1. 计算各指标 ──────────────────────────────
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ADX & 趋势强度
    adx_series = calc_adx(df, adx_period)
    trend_strength = calc_trend_strength(adx_series)
    current_adx = adx_series.iloc[-1]
    current_ts = trend_strength.iloc[-1]

    # 布林带
    bb_mid = close.rolling(bb_period).mean()
    bb_std_val = close.rolling(bb_period).std()
    bb_upper = bb_mid + bb_std * bb_std_val
    bb_lower = bb_mid - bb_std * bb_std_val
    bb_width = (bb_upper - bb_lower) / bb_mid  # 相对带宽

    current_bb_upper = bb_upper.iloc[-1]
    current_bb_lower = bb_lower.iloc[-1]
    current_close = close.iloc[-1]
    current_bb_width = bb_width.iloc[-1]

    # ATR
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    current_atr = atr.iloc[-1]
    recent_atr_mean = atr.iloc[-20:].mean() if len(atr) >= 20 else current_atr

    # 价格动量
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean() if n >= 60 else close.rolling(20).mean()
    price_vs_ma20 = (current_close - ma20.iloc[-1]) / ma20.iloc[-1]
    price_vs_ma60 = (current_close - ma60.iloc[-1]) / ma60.iloc[-1]

    # 价格相对于布林带的位置
    bb_pos = (
        (current_close - current_bb_lower) / (current_bb_upper - current_bb_lower)
        if current_bb_upper > current_bb_lower
        else 0.5
    )

    # ── 2. 状态判定 ──────────────────────────────
    evidence: Dict[str, Any] = {
        "adx": round(current_adx, 2) if pd.notna(current_adx) else None,
        "trend_strength": round(current_ts, 4) if pd.notna(current_ts) else None,
        "bb_width": round(current_bb_width, 6) if pd.notna(current_bb_width) else None,
        "atr_ratio": round(current_atr / recent_atr_mean, 4) if recent_atr_mean > 0 else 1.0,
        "price_vs_ma20": round(price_vs_ma20, 6),
        "price_vs_ma60": round(price_vs_ma60, 6),
        "bb_position": round(bb_pos, 4),
    }

    # Climax：ATR 突然放大 + 布林带异常宽 + 价格远偏离均线
    atr_ratio = current_atr / recent_atr_mean if recent_atr_mean > 0 else 1.0
    if atr_ratio > climax_threshold and current_bb_width > 0.05:
        if bb_pos > 0.9 and price_vs_ma20 > 0.05:
            return _make_result("CLIMAX", 0.8, evidence)
        elif bb_pos < 0.1 and price_vs_ma20 < -0.05:
            return _make_result("CLIMAX", 0.8, evidence)

    # Breakout：ADX 上升 + 价格突破布林带 + 布林带温和宽度
    if pd.notna(current_adx) and current_adx > 25 and current_ts > 0.4:
        if current_close > current_bb_upper and bb_pos > 0.95:
            return _make_result("BREAKOUT", min(current_ts + 0.2, 1.0), evidence)
        elif current_close < current_bb_lower and bb_pos < 0.05:
            return _make_result("BREAKOUT", min(current_ts + 0.2, 1.0), evidence)

    # UPTREND / DOWNTREND：ADX > 20 且价格在均线上/下方且趋势强度足够
    if pd.notna(current_adx) and current_adx > 20 and current_ts > 0.3:
        if price_vs_ma20 > 0.02 and price_vs_ma60 > 0.01:
            return _make_result("UPTREND", min(current_ts, 0.9), evidence)
        elif price_vs_ma20 < -0.02 and price_vs_ma60 < -0.01:
            return _make_result("DOWNTREND", min(current_ts, 0.9), evidence)

    # RANGE：ADX < 20 或趋势强度低 + 布林带窄
    if pd.notna(current_adx) and current_adx < 20:
        return _make_result("RANGE", 0.6, {"...": "ADX < 20", **evidence})
    if current_ts < 0.2 and abs(price_vs_ma20) < 0.015 and current_bb_width < 0.03:
        return _make_result("RANGE", 0.7, evidence)

    # 默认
    return _make_result("UNKNOWN", 0.3, evidence)


def _make_result(
    regime: str, confidence: float, evidence: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "regime": regime,
        "confidence": round(confidence, 4),
        "evidence": evidence,
    }
