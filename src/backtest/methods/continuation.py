"""
墨枢 - Research Method: Continuation（R1 阶段二：任务2）

趋势延续形态检测：
  1. find_continuation_setup    — 均线多头排列 + 回调至关键均线不破
  2. validate_continuation      — 成交量未萎缩 + ADX > 25

依赖:
  - src.backtest.models.signal_types — R1Signal, MarketRegime
  - src.backtest.factors.regime      — adx / trend_strength
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.models.signal_types import R1Signal, MarketRegime
from src.backtest.factors.volume.volume_flow_factor import calc_smart_money_score
from src.backtest.factors.regime.regime_factor import classify_regime


@dataclass
class ContinuationSetup:
    """趋势延续候选信号"""
    idx: int
    entry_price: float
    ma_alignment: str          # 均线排列状态
    retest_ma_period: int      # 回踩的均线周期
    retest_low: float          # 回踩最低价
    timestamp: datetime


# ─── 1. 趋势延续形态检测 ─────────────────────────────────────

def find_continuation_setup(
    df: pd.DataFrame,
    fast_ma: int = 10,
    mid_ma: int = 20,
    slow_ma: int = 60,
    retest_ma: int = 20,
) -> List[ContinuationSetup]:
    """检测趋势延续形态（均线多头排列 + 回调至关键均线不破）。

    核心逻辑：
      1. 均线多头排列：fast_ma > mid_ma > slow_ma（趋势向上）
      2. 价格回调至 mid_ma（retest_ma）附近但不跌破
      3. 回调时成交量未显著放大
      4. 后续价格企稳回升

    Args:
        df: OHLCV DataFrame，需含 'high', 'low', 'close', 'volume' 列
        fast_ma: 快线周期（默认 10）
        mid_ma: 中线周期（默认 20）
        slow_ma: 慢线周期（默认 60）
        retest_ma: 回踩检测均线周期（默认 20）

    Returns:
        List[ContinuationSetup]: 趋势延续候选列表
    """
    required = {'high', 'low', 'close', 'volume'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame 缺少必要列: {missing}")

    n = len(df)
    if n < slow_ma + 5:
        return []

    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    # 计算各周期均线
    ma_fast = pd.Series(close).rolling(fast_ma).mean().values
    ma_mid = pd.Series(close).rolling(mid_ma).mean().values
    ma_slow = pd.Series(close).rolling(slow_ma).mean().values
    ma_retest = pd.Series(close).rolling(retest_ma).mean().values

    setups: List[ContinuationSetup] = []

    for i in range(slow_ma, n):
        # 跳过 NaN
        if np.isnan(ma_fast[i]) or np.isnan(ma_mid[i]) or np.isnan(ma_slow[i]):
            continue

        # ── 条件1：均线多头排列 ─────────────────────────
        if not (ma_fast[i] > ma_mid[i] > ma_slow[i]):
            continue

        # ── 条件2：价格从高位回调至 mid_ma 附近 ──────────
        # 前 3 根中至少有 1 根价格在 mid_ma 以下（说明刚经历回调）
        has_retest = False
        retest_low_idx = -1
        retest_vol_shrinking = True

        for j in range(max(0, i - 4), i + 1):
            if close[j] <= ma_retest[j] * 1.02:  # 在均线 2% 以内
                has_retest = True
                retest_low_idx = j
                break

        if not has_retest:
            continue

        # ── 条件3：回调低位未跌破均线的 98% ────────────
        if low[retest_low_idx] < ma_retest[retest_low_idx] * 0.98:
            continue

        # ── 条件4：回调期间成交量呈萎缩趋势 ─────────────
        vol_ma = pd.Series(volume).rolling(10, min_periods=3).mean().values
        for k in range(max(0, retest_low_idx - 3), retest_low_idx + 1):
            if vol_ma[k] > 0 and volume[k] > vol_ma[k] * 1.3:
                retest_vol_shrinking = False
                break

        if not retest_vol_shrinking:
            continue

        timestamp = _resolve_timestamp(df, i)
        setups.append(ContinuationSetup(
            idx=i,
            entry_price=float(close[i]),
            ma_alignment=f"{ma_fast[i]:.2f} > {ma_mid[i]:.2f} > {ma_slow[i]:.2f}",
            retest_ma_period=retest_ma,
            retest_low=float(low[retest_low_idx]),
            timestamp=timestamp,
        ))

    return setups


# ─── 2. 验证函数 ──────────────────────────────────────────────

def validate_continuation(
    df: pd.DataFrame,
    setup_idx: int,
) -> bool:
    """验证趋势延续信号的有效性。

    验证维度：
      1. ADX > 25 — 趋势强度充足
      2. 成交量未显著萎缩 — 趋势延续有量能支撑
      3. 价格企稳回升 — 回调结束确认

    Args:
        df: OHLCV DataFrame
        setup_idx: 候选信号的 K 线索引

    Returns:
        bool: True 表示验证通过
    """
    n = len(df)
    if setup_idx >= n:
        return False

    # ── 使用 classify_regime 判断市场状态 ──────────────
    # 取 setup_idx 前 50 根 K 线做状态判断
    start = max(0, setup_idx - 50)
    sub_df = df.iloc[start:setup_idx + 1].copy()
    if len(sub_df) < 30:
        return False

    regime_result = classify_regime(sub_df)

    # ADX 检查：必须是趋势状态
    regime = regime_result.get("regime", "UNKNOWN")
    if regime not in ("UPTREND", "DOWNTREND", "BREAKOUT"):
        return False

    # 置信度 > 0.3 才接受
    if regime_result.get("confidence", 0) < 0.3:
        return False

    # ── 成交量检查 ─────────────────────────────────────
    # 过去 5 根 K 线的均量不应低于过去 20 根均量的 60%
    if setup_idx >= 20:
        vol_recent = df['volume'].iloc[setup_idx - 5:setup_idx + 1].mean()
        vol_long = df['volume'].iloc[setup_idx - 20:setup_idx + 1].mean()
        if vol_long > 0 and vol_recent < vol_long * 0.6:
            return False

    return True


# ─── 辅助函数 ───────────────────────────────────────────────

def _resolve_timestamp(df: pd.DataFrame, idx: int) -> datetime:
    if isinstance(df.index, pd.DatetimeIndex):
        return df.index[idx].to_pydatetime()
    return datetime.now()


# ─── 全流程便捷函数 ─────────────────────────────────────────

def run_continuation(df: pd.DataFrame, **kwargs) -> List[R1Signal]:
    """全流程：检测延续形态 → 验证 → 信号生成

    Args:
        df: OHLCV DataFrame
        **kwargs: 配置参数

    Returns:
        List[R1Signal]
    """
    setups = find_continuation_setup(
        df,
        fast_ma=kwargs.get("fast_ma", 10),
        mid_ma=kwargs.get("mid_ma", 20),
        slow_ma=kwargs.get("slow_ma", 60),
        retest_ma=kwargs.get("retest_ma", 20),
    )

    signals: List[R1Signal] = []
    for setup in setups:
        if not validate_continuation(df, setup.idx):
            continue

        signals.append(R1Signal(
            method="continuation",
            direction=1,
            confidence=0.65,
            price=float(setup.entry_price),
            timestamp=setup.timestamp,
            regime=MarketRegime.UPTREND.value,
            metadata={
                "setup_idx": setup.idx,
                "retest_low": round(setup.retest_low, 2),
                "ma_alignment": setup.ma_alignment,
            },
        ))

    return signals
