"""
墨枢 - Research Method: Volume Price Expansion（R1 阶段二：任务3）

量价齐升启动信号检测：
  1. find_vpe_setup          — 成交量递增 + 价格逐级上台阶
  2. calc_expansion_factor   — 扩张因子（累计量比 × 价格变动比）

依赖:
  - src.backtest.models.signal_types — R1Signal, MarketRegime
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.models.signal_types import R1Signal, MarketRegime


@dataclass
class VpeSetup:
    """量价齐升候选信号"""
    idx: int
    entry_price: float
    vol_steps: int             # 连续量增阶数
    price_steps: int           # 连续价升阶数
    expansion_factor: float    # 扩张因子
    timestamp: datetime


# ─── 1. 量价齐升启动信号检测 ────────────────────────────────

def find_vpe_setup(
    df: pd.DataFrame,
    price_lookback: int = 3,
    vol_lookback: int = 3,
    min_vol_ratio: float = 1.2,
    min_price_rise_pct: float = 0.5,
) -> List[VpeSetup]:
    """检测量价齐升启动信号。

    核心逻辑：
      1. 成交量递增：连续 vol_lookback 根 K 线成交量单调递增
      2. 价格逐级上台阶：连续 price_lookback 根 K 线收盘价逐级抬高
      3. 量价同步：量增和价升的时间窗口重叠
      4. 当前成交量 > 前 20 日均量的 min_vol_ratio 倍

    Args:
        df: OHLCV DataFrame，需含 'close', 'volume' 列
        price_lookback: 价格连续抬升检查窗（默认 3）
        vol_lookback: 成交量连续递增检查窗（默认 3）
        min_vol_ratio: 最小量比（默认 1.2倍）
        min_price_rise_pct: 最小价格涨幅（默认 0.5%）

    Returns:
        List[VpeSetup]: 量价齐升候选列表
    """
    required = {'close', 'volume'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame 缺少必要列: {missing}")

    n = len(df)
    window = max(price_lookback, vol_lookback) + 20
    if n < window:
        return []

    close = df['close'].values
    volume = df['volume'].values

    # 成交量移动平均（20日）
    vol_ma_20 = pd.Series(volume).rolling(20, min_periods=5).mean().values

    setups: List[VpeSetup] = []

    for i in range(window, n):
        # ── 条件1：连续 price_lookback 根收盘价递增 ────
        price_increasing = all(
            close[i - k] > close[i - k - 1]
            for k in range(price_lookback)
        )

        # ── 条件2：连续 vol_lookback 根成交量递增 ────
        vol_increasing = all(
            volume[i - k] > volume[i - k - 1]
            for k in range(vol_lookback)
        )

        if not (price_increasing and vol_increasing):
            continue

        # ── 条件3：当前量 > 20日均量 × min_vol_ratio ──
        if vol_ma_20[i] > 0 and volume[i] < vol_ma_20[i] * min_vol_ratio:
            continue

        # ── 条件4：累计涨幅满足最小要求 ───────────────
        price_change_pct = (close[i] - close[i - price_lookback]) / close[i - price_lookback] * 100
        if price_change_pct < min_price_rise_pct:
            continue

        ef = calc_expansion_factor(
            df.iloc[max(0, i - 20): i + 1],
        )

        timestamp = _resolve_timestamp(df, i)
        setups.append(VpeSetup(
            idx=i,
            entry_price=float(close[i]),
            vol_steps=_count_consecutive_vol_increase(volume, i, vol_lookback),
            price_steps=_count_consecutive_price_increase(close, i, price_lookback),
            expansion_factor=ef,
            timestamp=timestamp,
        ))

    return setups


# ─── 2. 扩张因子计算 ────────────────────────────────────────

def calc_expansion_factor(df: pd.DataFrame) -> float:
    """扩张因子：衡量量价扩张的综合强度。

    公式：
      扩张因子 = 累计量比 × 价格变动比

      - 累计量比 = 窗口内总成交量 / 同期均量
      - 价格变动比 = (最新close - 最早close) / 最早close × 100

    Args:
        df: OHLCV DataFrame，至少含 'close', 'volume' 列
             建议传入 20 根 K 线的窗口

    Returns:
        float: 扩张因子值，越大表示扩张越强
    """
    if len(df) < 5:
        return 0.0

    close = df['close'].values
    volume = df['volume'].values

    # 累计量比
    total_vol = float(np.sum(volume))
    avg_vol = float(np.mean(volume))
    vol_ratio = total_vol / avg_vol if avg_vol > 0 else 1.0

    # 价格变动比（百分比）
    first_close = float(close[0])
    last_close = float(close[-1])
    price_change_pct = (last_close - first_close) / first_close * 100 if first_close > 0 else 0.0

    # 扩张因子
    expansion = vol_ratio * price_change_pct
    return round(expansion, 4)


# ─── 辅助函数 ───────────────────────────────────────────────

def _count_consecutive_vol_increase(volume: np.ndarray, idx: int, lookback: int) -> int:
    """计算连续成交量递增的阶数"""
    count = 0
    for k in range(lookback):
        if idx - k >= 1 and volume[idx - k] > volume[idx - k - 1]:
            count += 1
        else:
            break
    return count


def _count_consecutive_price_increase(close: np.ndarray, idx: int, lookback: int) -> int:
    """计算连续价格抬升的阶数"""
    count = 0
    for k in range(lookback):
        if idx - k >= 1 and close[idx - k] > close[idx - k - 1]:
            count += 1
        else:
            break
    return count


def _resolve_timestamp(df: pd.DataFrame, idx: int) -> datetime:
    if isinstance(df.index, pd.DatetimeIndex):
        return df.index[idx].to_pydatetime()
    return datetime.now()


# ─── 全流程便捷函数 ─────────────────────────────────────────

def run_vpe(df: pd.DataFrame, **kwargs) -> List[R1Signal]:
    """全流程：检测VPE → 信号生成

    Args:
        df: OHLCV DataFrame
        **kwargs: 配置参数

    Returns:
        List[R1Signal]
    """
    setups = find_vpe_setup(
        df,
        price_lookback=kwargs.get("price_lookback", 3),
        vol_lookback=kwargs.get("vol_lookback", 3),
        min_vol_ratio=kwargs.get("min_vol_ratio", 1.2),
        min_price_rise_pct=kwargs.get("min_price_rise_pct", 0.5),
    )

    signals: List[R1Signal] = []
    for setup in setups:
        # 扩张因子 >= 0.5 才生成信号
        if setup.expansion_factor < 0.5:
            continue

        confidence = min(setup.expansion_factor / 10.0, 0.9)

        signals.append(R1Signal(
            method="volume_price_expansion",
            direction=1,
            confidence=round(confidence, 4),
            price=float(setup.entry_price),
            timestamp=setup.timestamp,
            regime=MarketRegime.BREAKOUT.value,
            metadata={
                "setup_idx": setup.idx,
                "expansion_factor": round(setup.expansion_factor, 4),
                "vol_steps": setup.vol_steps,
                "price_steps": setup.price_steps,
            },
        ))

    return signals
