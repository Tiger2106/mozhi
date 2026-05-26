"""
mozhi_platform.src.backtest.risk.market_state_filter — MarketStateFilter

市场状态信号过滤器。

基于 RegimeAnalyzer 的市场状态判定，对信号进行过滤/衰减。
在 DOWNTREND/CLIMAX 状态下阻止开新仓，在 RANGE 状态下降低仓位。

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.regime.regime_analyzer import RegimeAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class RiskEvent:
    """风控事件结构"""
    event_type: str = ""
    timestamp: str = ""
    severity: str = "low"
    description: str = ""
    value: float = 0.0
    threshold: float = 0.0


@dataclass
class MarketStateFilterConfig:
    """市场状态过滤器配置"""
    enabled: bool = True
    """总开关，关闭时原样通过信号。"""

    block_regimes: List[str] = field(default_factory=lambda: ["DOWNTREND", "CLIMAX"])
    """在这些市场状态下阻止开新仓。"""

    reduce_regimes: List[str] = field(default_factory=lambda: ["RANGE"])
    """在这些市场状态下降低仓位。"""

    reduce_factor: float = 0.5
    """降仓系数（RANGE 状态时的仓位乘数）。"""

    min_confidence: float = 0.3
    """RegimeAnalyzer 置信度低于此值时视为 UNKNOWN，按保守处理。"""

    transition_penalty: float = 0.3
    """状态转换频繁（transitions > threshold）时的额外减仓系数。"""

    transition_threshold: int = 5
    """窗口内转换次数超过此值视为高波动期。"""

    cooldown_bars: int = 3
    """阻止信号后，冷却期内仍可通过持仓信号（不新开仓）。"""


class MarketStateFilter:
    """市场状态信号过滤器。

    基于 RegimeAnalyzer 的市场状态判定，对信号进行过滤/衰减。
    在 DOWNTREND/CLIMAX 状态下阻止开新仓，在 RANGE 状态下降低仓位。

    Examples:
        >>> filter = MarketStateFilter(regime_analyzer)
        >>> filtered = filter.process(signals_df, ohlcv_df)
        >>> # 返回的 DataFrame 中 signal=0 表示被过滤
    """

    def __init__(
        self,
        regime_analyzer: Optional[RegimeAnalyzer] = None,
        config: Optional[MarketStateFilterConfig] = None,
    ):
        self.regime_analyzer = regime_analyzer or RegimeAnalyzer()
        self.config = config or MarketStateFilterConfig()
        self._risk_events: List[RiskEvent] = []

    def process(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
    ) -> pd.DataFrame:
        """对信号逐行应用市场状态过滤。

        Args:
            signals: 信号 DataFrame（必须含 'signal' 列，索引 DatetimeIndex）。
            df_ohlcv: OHLCV DataFrame（索引与 signals 对齐）。

        Returns:
            pd.DataFrame: 过滤后的信号（未通过的行 signal → 0）。
        """
        if not self.config.enabled:
            return signals

        result = signals.copy()
        common_idx = signals.index.intersection(df_ohlcv.index)
        if len(common_idx) == 0:
            logger.warning("MarketStateFilter: 信号索引与 OHLCV 索引无交集")
            return result

        result = result.loc[common_idx]

        # 滑动窗口分析市场状态
        window_result = self.regime_analyzer.analyze_window(
            df_ohlcv, lookback=min(60, len(df_ohlcv))
        )

        current = self.regime_analyzer.get_current_regime()
        regime = current.get("regime", "UNKNOWN")
        confidence = current.get("confidence", 0.0)
        transitions = window_result.transitions

        # 是否需要阻断信号
        block_open = False
        position_scale = 1.0

        if regime in self.config.block_regimes and confidence >= self.config.min_confidence:
            block_open = True
            self._risk_events.append(RiskEvent(
                event_type="regime_block",
                timestamp=str(common_idx[-1]) if len(common_idx) > 0 else "",
                severity="high",
                description=f"市场状态 {regime}，阻止开新仓",
                value=float(confidence),
                threshold=self.config.min_confidence,
            ))

        elif regime in self.config.reduce_regimes:
            position_scale = self.config.reduce_factor

        # 高转换期附加惩罚
        if transitions > self.config.transition_threshold:
            position_scale *= self.config.transition_penalty

        # 应用过滤
        if block_open:
            # 只允许持仓平仓（signal=-1 保持，signal=1 → 0）
            result.loc[result["signal"] == 1, "signal"] = 0
        elif position_scale < 1.0:
            # 在 result 中记录降仓系数，供 VolatilityRiskManager 使用
            result["position_scale"] = position_scale
            logger.debug("市场状态 %s，仓位缩放系数: %.2f", regime, position_scale)

        return result

    def get_risk_events(self) -> List[RiskEvent]:
        """返回本次处理中产生的风控事件。"""
        return self._risk_events.copy()
