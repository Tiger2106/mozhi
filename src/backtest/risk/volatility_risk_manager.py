"""
mozhi_platform.src.backtest.risk.volatility_risk_manager — VolatilityRiskManager

ATR 动态仓位管理器。

基于 ATR（Average True Range）计算动态仓位比例。
波动率高时缩小仓位，波动率低时放大仓位（受 max_position_pct 约束）。

调用现有的 ATRFactor.compute() 获取 ATR 值。

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from backtest.factors.volatility import ATRFactor

logger = logging.getLogger(__name__)


@dataclass
class VolatilityRiskConfig:
    """波动率风险管理器配置"""
    enabled: bool = True
    """总开关，关闭时 position_ratio 全为 1.0。"""

    # ATR 参数
    atr_period: int = 14
    """ATR 计算周期（K 线数）。"""

    atr_method: str = "wilders"
    """ATR 计算方法: "wilders" | "sma" | "ema" """

    atr_threshold: float = 0.001
    """ATR/price < 0.1% 视为低波动（区分于 NaN 信息不足）。"""

    # 风险预算
    risk_per_trade_pct: float = 0.01
    """每笔交易风险预算（占当前权益比例，默认 1%）。"""

    max_position_pct: float = 0.20
    """单标的最大仓位（占当前权益比例，默认 20%）。"""

    # 缩放
    min_scale: float = 0.1
    """最小仓位缩放系数（防止除零或过小仓位）。"""

    max_scale: float = 2.0
    """最大仓位缩放系数（防止杠杆过高）。"""

    # NaN fallback
    nan_fallback_ratio: float = 0.0
    """ATR 为 NaN 时的仓位比例（0 = 停止交易）。"""

    low_vol_ratio: float = 0.10
    """低波动时的保守仓位比例（默认 10%）。"""


@dataclass
class RiskEvent:
    """风控事件结构"""
    event_type: str = ""
    timestamp: str = ""
    severity: str = "low"
    description: str = ""
    value: float = 0.0
    threshold: float = 0.0


class VolatilityRiskManager:
    """ATR 动态仓位管理器。

    基于 ATR（Average True Range）计算动态仓位比例。
    波动率高时缩小仓位，波动率低时放大仓位（受 max_position_pct 约束）。

    Formula:
        position_ratio = min(
            max_position_pct,
            risk_per_trade_pct * equity / (ATR_value * contract_multiplier)
        )

    特殊处理:
        - NaN ATR → 0.0（停止交易，信息不足）
        - atr < threshold → low_vol_ratio（保守 10%，低波动不代表无风险）
        - 零/负信号 → 0.0

    Examples:
        >>> vrm = VolatilityRiskManager()
        >>> sized_signals = vrm.process(signals, df_ohlcv)
        >>> sized_signals["position_ratio"].iloc[0]
        0.15
    """

    def __init__(self, config: Optional[VolatilityRiskConfig] = None):
        self.config = config or VolatilityRiskConfig()
        self._atr_series: Optional[pd.Series] = None
        self._risk_events: List[RiskEvent] = []

        # 创建临时 ATRFactor 实例（无上下文，直接传参）
        self._atr_factor = ATRFactor(params={
            "period": self.config.atr_period,
            "use_ema": self.config.atr_method != "sma",  # wilders/ema → use_ema=True
        })

    def process(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
        current_equity: Optional[float] = None,
    ) -> pd.DataFrame:
        """计算 ATR 并生成动态仓位比例。

        Args:
            signals: 信号 DataFrame（必须含 'signal' 列）。
            df_ohlcv: OHLCV DataFrame（含 high/low/close/volume）。
            current_equity: 当前权益（可选；未提供时用 0 表示只算比例）。

        Returns:
            pd.DataFrame: 新增 'position_ratio' 列的信号 DataFrame。
        """
        if not self.config.enabled:
            result = signals.copy()
            result["position_ratio"] = 1.0
            return result

        result = signals.copy()

        # 1. 通过 ATRFactor 计算 ATR
        atr_df = self._atr_factor.compute(df_ohlcv)
        atr = atr_df["atr"]
        self._atr_series = atr

        # 2. 对齐索引
        common_idx = result.index.intersection(atr.index)
        result = result.loc[common_idx]
        atr_aligned = atr.loc[common_idx]

        # 3. 计算每行的动态仓位比例
        close_prices = df_ohlcv.loc[common_idx, "close"].values.astype(np.float64)

        position_ratios = np.full(len(result), 0.0, dtype=np.float64)
        atr_values = atr_aligned.values.astype(np.float64)

        for i in range(len(result)):
            signal_val = result["signal"].iloc[i]
            if signal_val == 0:
                position_ratios[i] = 0.0
                continue

            atr_val = atr_values[i]
            close_price = close_prices[i]

            if pd.isna(atr_val) or atr_val is None or atr_val <= 0:
                # 信息不足 → 停止交易
                position_ratios[i] = self.config.nan_fallback_ratio
                logger.debug("NaN/零值 ATR，仓位比例设为 %s", self.config.nan_fallback_ratio)
            elif (atr_val / max(close_price, 1e-10)) < self.config.atr_threshold:
                # 低波动 → 保守仓位
                position_ratios[i] = self.config.low_vol_ratio
            else:
                # 正常 ATR 动态仓位: risk / (atr / price) 即能承受多少个百分点波动
                atr_pct = atr_val / close_price
                raw_ratio = self.config.risk_per_trade_pct / max(atr_pct, 0.001)
                clipped = max(self.config.min_scale, min(self.config.max_position_pct, raw_ratio))
                position_ratios[i] = clipped

        result["position_ratio"] = position_ratios

        # 4. 风控事件
        if len(atr_values) > 0 and len(close_prices) > 0:
            valid_mask = ~np.isnan(atr_values) & (close_prices > 0)
            if valid_mask.any():
                mean_atr_pct = float(np.mean(atr_values[valid_mask] / close_prices[valid_mask]))
            else:
                mean_atr_pct = 0.0
            self._risk_events.append(RiskEvent(
                event_type="volatility_assessment",
                timestamp=str(common_idx[-1]) if len(common_idx) > 0 else "",
                severity="low" if mean_atr_pct < 0.02 else ("medium" if mean_atr_pct < 0.04 else "high"),
                description=f"ATR均值占比: {mean_atr_pct:.4f}, 平均仓位比例: {float(np.mean(position_ratios)):.4f}",
                value=float(mean_atr_pct),
                threshold=0.02,
            ))

        return result

    def get_risk_events(self) -> List[RiskEvent]:
        """返回累积的风控事件列表。"""
        return self._risk_events.copy()

    def reset(self) -> None:
        """重置状态。"""
        self._atr_series = None
        self._risk_events.clear()
