"""
mozhi_platform.src.backtest.methods.trend.wyckoff_method — WyckoffMethod

威科夫量价分析方法（Wyckoff Method）。
基于威科夫量价关系原理，通过分析成交量和价格行为判定吸筹/派发阶段。

旧系统源：无（全新实现）
创建日期：2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd
import numpy as np

from backtest.methods.base import BaseMethod
from backtest.methods.manifest import METHOD_META as _BASE_METHOD_META

# ──────────────────────────────────────────────────────────────────────
# METHOD_META 协议常量
# ──────────────────────────────────────────────────────────────────────

METHOD_META = {
    "name": "wyckoff",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "威科夫量价分析：通过成交量-价格关系判定吸筹/派发阶段，生成趋势反转信号",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {
        "lookback": 20,
        "volume_surge_ratio": 1.5,
        "price_change_threshold": 0.02,
    },
    "dependencies": [],
    "tags": ["trend", "wyckoff", "volume_price"],
}


# ──────────────────────────────────────────────────────────────────────
# WyckoffMethod
# ──────────────────────────────────────────────────────────────────────


class WyckoffMethod(BaseMethod):
    METHOD_META = METHOD_META
    """威科夫量价分析信号方法（全新实现）。

    **核心逻辑**（基于威科夫原理简化实现）：

    威科夫理论的核心量价关系：
    1. **吸筹（Accumulation）阶段特征**：
        - 价格在低位盘整
        - 下跌时成交量萎缩，上涨时成交量放大
        - 出现＂弹簧效应＂(Spring)：价格短暂跌破支撑后快速收回
    2. **派发（Distribution）阶段特征**：
        - 价格在高位盘整
        - 上涨时成交量萎缩，下跌时成交量放大
        - 出现＂上冲回落＂(UTAD)：价格短暂突破阻力后快速回落

    本方法通过分析窗口内的量价模式综合评分：

    - **吸筹评分（accumulation_score）**：
        * 下跌日缩量超过阈值 → +1
        * 上涨日放量超过阈值 → +1
        * 出现弹簧效应 → +2
    - **派发评分（distribution_score）**：
        * 上涨日缩量超过阈值 → +1
        * 下跌日放量超过阈值 → +1
        * 出现上冲回落 → +2

    **信号规则**：
        - accumulation_score - distribution_score >= 2 → signal = 1（BUY）
        - distribution_score - accumulation_score >= 2 → signal = -1（SELL）
        - 其他 → signal = 0

    **默认参数**：
        - ``lookback``：分析窗口（默认 20）
        - ``volume_surge_ratio``：放量/缩量阈值倍率（默认 1.5）
        - ``price_change_threshold``：价格变化幅度阈值（默认 0.02）

    Examples:
        >>> method = WyckoffMethod()
        >>> method.setup(ctx)
        >>> result = method.generate_signal(df)
        >>> result["signal"]
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.lookback: int = ctx.get_config("lookback", 20)
        self.volume_surge_ratio: float = ctx.get_config("volume_surge_ratio", 1.5)
        self.price_change_threshold: float = ctx.get_config("price_change_threshold", 0.02)

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成威科夫量价分析信号。

        Args:
            df: 必须包含 ``close``、``high``、``low``、``volume`` 列的 OHLCV DataFrame，
                索引为 DatetimeIndex。

        Returns:
            pd.DataFrame: 包含以下列的 DataFrame，索引与 ``df`` 对齐：
                - ``signal``: {-1, 0, 1}
                - ``accumulation_score``: 吸筹评分（整数）
                - ``distribution_score``: 派发评分（整数）
                - ``volume_ma_ratio``: 当前量 / 均量比值
                - ``wyckoff_phase``: 阶段标签（"accumulation" / "distribution" / "neutral"）

        Raises:
            ValueError: 如果必要列缺失。
        """
        required = {"close", "high", "low", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"输入 DataFrame 缺少列: {missing}")

        n = len(df)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)
        accumulation_score = pd.Series(np.zeros(n, dtype=int), index=df.index)
        distribution_score = pd.Series(np.zeros(n, dtype=int), index=df.index)
        volume_ma_ratio = pd.Series(np.nan, index=df.index)
        wyckoff_phase = pd.Series(["neutral"] * n, index=df.index)

        # ── 1. 计算基础指标 ──────────────────────────────────────
        volume_ma = volume.rolling(window=self.lookback).mean()

        # ── 2. 滚动窗口分析 ──────────────────────────────────────
        for i in range(self.lookback, n):
            # 窗口数据
            win_close = close.iloc[i - self.lookback + 1:i + 1]
            win_high = high.iloc[i - self.lookback + 1:i + 1]
            win_low = low.iloc[i - self.lookback + 1:i + 1]
            win_volume = volume.iloc[i - self.lookback + 1:i + 1]
            win_vol_ma = volume_ma.iloc[i - self.lookback + 1:i + 1]

            price_min = win_low.min()
            price_max = win_high.max()
            price_range = price_max - price_min

            if price_range == 0:
                continue

            current_close = close.iloc[i]
            current_volume = volume.iloc[i]
            current_vol_ma = volume_ma.iloc[i]

            vol_ratio = current_volume / current_vol_ma if current_vol_ma > 0 else 1.0
            volume_ma_ratio.iloc[i] = vol_ratio

            # ── 价格位置（0~1，0=最低，1=最高） ─────────────────
            price_position = (current_close - price_min) / price_range

            acc_score = 0
            dist_score = 0

            # ── 逐日分析量价关系 ────────────────────────────────
            for j in range(1, self.lookback):
                prev_close = win_close.iloc[j - 1]
                curr_close = win_close.iloc[j]
                curr_vol = win_volume.iloc[j]
                prev_vol_ma = win_vol_ma.iloc[j - 1]

                price_change = (curr_close - prev_close) / prev_close if prev_close > 0 else 0
                vol_ratio_j = curr_vol / prev_vol_ma if prev_vol_ma > 0 else 1.0

                # 吸筹特征
                if price_change < -self.price_change_threshold and vol_ratio_j < (1 / self.volume_surge_ratio):
                    acc_score += 1  # 下跌缩量
                if price_change > self.price_change_threshold and vol_ratio_j > self.volume_surge_ratio:
                    acc_score += 1  # 上涨放量

                # 派发特征
                if price_change > self.price_change_threshold and vol_ratio_j < (1 / self.volume_surge_ratio):
                    dist_score += 1  # 上涨缩量
                if price_change < -self.price_change_threshold and vol_ratio_j > self.volume_surge_ratio:
                    dist_score += 1  # 下跌放量

            # ── 弹簧效应（Spring）检测 ──────────────────────────
            # 价格短暂跌破前低后快速收回
            prev_low = win_low.iloc[-2] if self.lookback >= 2 else price_min
            if current_close < prev_low and current_close > win_close.iloc[-1] * (1 - self.price_change_threshold * 2):
                # 最新收盘跌破前低但跌幅不大，可能弹簧
                acc_score += 2

            # ── 上冲回落（UTAD）检测 ────────────────────────────
            prev_high = win_high.iloc[-2] if self.lookback >= 2 else price_max
            if current_close > prev_high and current_close < win_close.iloc[-1] * (1 + self.price_change_threshold * 2):
                dist_score += 2

            accumulation_score.iloc[i] = acc_score
            distribution_score.iloc[i] = dist_score

            # ── 信号判定 ────────────────────────────────────────
            net = acc_score - dist_score
            if net >= 2:
                signal.iloc[i] = 1
                wyckoff_phase.iloc[i] = "accumulation"
            elif net <= -2:
                signal.iloc[i] = -1
                wyckoff_phase.iloc[i] = "distribution"

        result = pd.DataFrame(
            {
                "signal": signal,
                "accumulation_score": accumulation_score,
                "distribution_score": distribution_score,
                "volume_ma_ratio": volume_ma_ratio,
                "wyckoff_phase": wyckoff_phase,
            },
            index=df.index,
        )
        return result
