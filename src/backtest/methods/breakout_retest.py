"""
墨枢 - Research Method: Breakout Retest（R1 阶段二：任务1）

突破回踩确认模型：
  1. find_breakout     — 突破信号（价格突破前高 + 成交量放大）
  2. find_retest       — 回踩确认（价格回落至突破价格附近并企稳）
  3. generate_signals  — 综合信号生成 → List[R1Signal]

依赖:
  - src.backtest.models.signal_types — R1Signal, MarketRegime
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.models.signal_types import R1Signal, MarketRegime


@dataclass
class BreakoutCandidate:
    """突破候选信号"""
    idx: int
    breakout_price: float
    volume_ratio: float
    lookback_high: float
    timestamp: datetime


@dataclass
class RetestConfirmation:
    """回踩确认结果"""
    confirmed: bool
    retest_idx: int
    retest_low: float
    retest_hold_bars: int


# ─── 1. 突破信号检测 ─────────────────────────────────────────

def find_breakout(
    df: pd.DataFrame,
    lookback: int = 20,
    vol_multiplier: float = 1.5,
) -> List[BreakoutCandidate]:
    """检测突破信号。

    逻辑：
      1. 在窗口内寻找前高点 = max(high[-lookback:-1])
      2. 当前 close > 前高点 → 价格突破
      3. 当前 volume > vol_ma * vol_multiplier → 成交量放大
      4. 同时满足为一次突破

    Args:
        df: OHLCV DataFrame，需含 'high', 'close', 'volume' 列
        lookback: 回溯窗口（默认 20）
        vol_multiplier: 成交量倍数阈值（默认 1.5）

    Returns:
        List[BreakoutCandidate]: 突破候选列表
    """
    required = {'high', 'close', 'volume'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame 缺少必要列: {missing}")

    if len(df) < lookback + 2:
        return []

    high = df['high'].values
    close = df['close'].values
    volume = df['volume'].values

    # 成交量移动平均
    vol_ma = pd.Series(volume).rolling(lookback, min_periods=5).mean().values

    candidates: List[BreakoutCandidate] = []

    for i in range(lookback, len(df)):
        lookback_max_high = float(np.max(high[i - lookback:i]))
        current_close = float(close[i])

        # 价格突破前高
        if current_close > lookback_max_high:
            # 成交量放大检查
            if vol_ma[i] > 0 and volume[i] > vol_ma[i] * vol_multiplier:
                timestamp = _resolve_timestamp(df, i)
                candidates.append(BreakoutCandidate(
                    idx=i,
                    breakout_price=current_close,
                    volume_ratio=float(volume[i] / vol_ma[i]) if vol_ma[i] > 0 else 1.0,
                    lookback_high=lookback_max_high,
                    timestamp=timestamp,
                ))

    return candidates


# ─── 2. 回踩确认检测 ─────────────────────────────────────────

def find_retest(
    df: pd.DataFrame,
    breakout_idx: int,
    lookback: int = 5,
) -> RetestConfirmation:
    """在突破后 lookback 根 K 线内检测回踩确认。

    逻辑：
      1. 突破后，价格回落至突破价附近（±0.5%）
      2. 回落不跌破突破价的 1.5%（保持突破有效性）
      3. 在回落区间内成交量呈萎缩状态（抛压减轻）
      4. 随后企稳

    Args:
        df: OHLCV DataFrame
        breakout_idx: 突破信号发生的索引
        lookback: 突破后检测窗口（默认 5 根 K 线）

    Returns:
        RetestConfirmation: 回踩确认结果
    """
    n = len(df)
    if breakout_idx >= n - 1:
        return RetestConfirmation(confirmed=False, retest_idx=-1, retest_low=0.0, retest_hold_bars=0)

    end = min(breakout_idx + lookback, n)
    breakout_price = float(df['close'].iloc[breakout_idx])
    low_series = df['low'].values[breakout_idx + 1:end]
    close_series = df['close'].values[breakout_idx + 1:end]
    volume_series = df['volume'].values[breakout_idx + 1:end]

    if len(low_series) < 1:
        return RetestConfirmation(confirmed=False, retest_idx=-1, retest_low=0.0, retest_hold_bars=0)

    # 寻找回踩（价格回落至突破价附近）
    upper_bound = breakout_price * 1.005   # +0.5%
    lower_bound = breakout_price * 0.985   # -1.5%（跌破则突破无效）

    for j in range(len(close_series)):
        if lower_bound <= close_series[j] <= upper_bound:
            # 检查成交量萎缩（后续2根量 < 突破量的1.2倍）
            vol_check = True
            base_vol = float(df['volume'].iloc[breakout_idx])
            for k in range(j, min(j + 3, len(volume_series))):
                if volume_series[k] > base_vol * 1.2:
                    vol_check = False
                    break

            if vol_check:
                return RetestConfirmation(
                    confirmed=True,
                    retest_idx=breakout_idx + 1 + j,
                    retest_low=float(low_series[j]),
                    retest_hold_bars=j + 1,
                )

    return RetestConfirmation(confirmed=False, retest_idx=-1, retest_low=0.0, retest_hold_bars=0)


# ─── 3. 综合信号生成 ─────────────────────────────────────────

def generate_signals(
    df: pd.DataFrame,
    breakouts: List[BreakoutCandidate],
    retests: List[RetestConfirmation],
) -> List[R1Signal]:
    """综合突破和回踩结果，生成交易信号 R1Signal。

    匹配逻辑：
      突破候选与回踩确认按索引顺序配对（第i个突破对应第i个回踩）。
      只有 confirmed=True 的回踩才产生有效信号。

    Args:
        df: 原 OHLCV DataFrame
        breakouts: 突破候选列表
        retests: 回踩确认结果列表（与 breakouts 一一对应或更少）

    Returns:
        List[R1Signal]: 交易信号列表
    """
    signals: List[R1Signal] = []

    for i, bc in enumerate(breakouts):
        rt = retests[i] if i < len(retests) else RetestConfirmation(
            confirmed=False, retest_idx=-1, retest_low=0.0, retest_hold_bars=0
        )

        if not rt.confirmed:
            continue

        # 计算置信度
        vol_strength = min(bc.volume_ratio / 3.0, 1.0)
        hold_quality = min(rt.retest_hold_bars / 5.0, 1.0)
        confidence = round(0.5 * vol_strength + 0.3 * hold_quality + 0.2, 4)
        confidence = max(0.1, min(confidence, 0.95))

        entry_price = bc.breakout_price
        timestamp = bc.timestamp

        # 判定市场状态
        # 使用突破前的 ADX/均线来辅助判断
        regime = _infer_regime_for_breakout(df, bc.idx)

        signals.append(R1Signal(
            method="breakout_retest",
            direction=1,
            confidence=confidence,
            price=float(entry_price),
            timestamp=timestamp,
            regime=regime,
            metadata={
                "breakout_idx": bc.idx,
                "retest_idx": rt.retest_idx,
                "volume_ratio": round(bc.volume_ratio, 2),
                "lookback_high": round(bc.lookback_high, 2),
            },
        ))

    return signals


# ─── 辅助函数 ───────────────────────────────────────────────

def _resolve_timestamp(df: pd.DataFrame, idx: int) -> datetime:
    """从 DataFrame 索引解析时间戳"""
    if isinstance(df.index, pd.DatetimeIndex):
        return df.index[idx].to_pydatetime()
    return datetime.now()


def _infer_regime_for_breakout(df: pd.DataFrame, idx: int, ma_period: int = 20) -> str:
    """根据均线关系和突破态势推断市场状态"""
    if idx < ma_period + 5:
        return MarketRegime.BREAKOUT.value

    close = df['close'].values[:idx + 1]
    if len(close) < ma_period + 1:
        return MarketRegime.BREAKOUT.value

    ma = pd.Series(close).rolling(ma_period).mean().values
    cur_close = float(close[-1])
    cur_ma = float(ma[-1]) if not np.isnan(ma[-1]) else cur_close

    # 价格远高于均线 → UPTREND
    if cur_close > cur_ma * 1.05:
        return MarketRegime.UPTREND.value
    return MarketRegime.BREAKOUT.value


# ─── 便捷函数：全流程一体调用 ──────────────────────────────

def run_breakout_retest(df: pd.DataFrame, **kwargs) -> List[R1Signal]:
    """全流程：突破检测 → 回踩确认 → 信号生成

    Args:
        df: OHLCV DataFrame
        **kwargs: 传递给 find_breakout / find_retest 的参数

    Returns:
        List[R1Signal]
    """
    lookback = kwargs.get("lookback", 20)
    vol_multiplier = kwargs.get("vol_multiplier", 1.5)
    retest_lookback = kwargs.get("retest_lookback", 5)

    breakouts = find_breakout(df, lookback=lookback, vol_multiplier=vol_multiplier)
    retests = [find_retest(df, bc.idx, lookback=retest_lookback) for bc in breakouts]
    return generate_signals(df, breakouts, retests)
