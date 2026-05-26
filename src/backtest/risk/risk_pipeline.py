"""
mozhi_platform.src.backtest.risk.risk_pipeline — RiskPipeline

风险流水线：组合 MarketStateFilter + VolatilityRiskManager + DrawdownGuard。

由 PortfolioIntegration 驱动，按顺序执行三个风险模块。

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.risk.drawdown_guard import DrawdownGuard, DrawdownGuardConfig
from backtest.risk.volatility_risk_manager import VolatilityRiskManager, VolatilityRiskConfig
from backtest.risk.market_state_filter import MarketStateFilter, MarketStateFilterConfig
from backtest.risk.regime_context_builder import RegimeContextBuilder, RegimeContextSignal
from backtest.regime.regime_analyzer import RegimeAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class RiskPipelineConfig:
    """风险流水线配置"""
    market_state_filter: MarketStateFilterConfig = field(
        default_factory=MarketStateFilterConfig
    )
    volatility_risk: VolatilityRiskConfig = field(
        default_factory=VolatilityRiskConfig
    )
    drawdown_guard: DrawdownGuardConfig = field(
        default_factory=DrawdownGuardConfig
    )

    enable_market_state_filter: bool = True
    """MarketStateFilter 开关。"""

    enable_volatility_risk: bool = True
    """VolatilityRiskManager 开关。"""

    enable_drawdown_guard: bool = True
    """DrawdownGuard 开关。"""

    enable_signal_fusion: bool = True
    """RegimeContextBuilder 信号融合开关。"""

    signal_fusion_weights: Dict[str, float] = field(default_factory=lambda: {
        "regime": 0.40,
        "vwap": 0.25,
        "volume_profile": 0.20,
        "knowledge": 0.15,
    })
    """信号融合权重配置，传给 RegimeContextBuilder。"""


class RiskPipeline:
    """风险流水线：组合 MarketStateFilter + VolatilityRiskManager + DrawdownGuard。

    由 PortfolioIntegration 驱动，按顺序执行三个风险模块。
    每个模块有独立的 enable_* 开关，关闭时退化为原行为。

    Examples:
        >>> pipeline = RiskPipeline(regime_analyzer=analyzer)
        >>> signals = pipeline.process_pre_filter(signals_df, df_ohlcv)
        >>> sized = pipeline.process_position_sizing(signals, df_ohlcv)
        >>> guard = pipeline.get_drawdown_guard()
        >>> safe_signal = guard.update(equity, timestamp, signal)
    """

    def __init__(
        self,
        regime_analyzer: Optional[RegimeAnalyzer] = None,
        config: Optional[RiskPipelineConfig] = None,
    ):
        cfg = config or RiskPipelineConfig()

        self.market_filter = MarketStateFilter(
            regime_analyzer, cfg.market_state_filter
        )
        self.volatility_mgr = VolatilityRiskManager(cfg.volatility_risk)
        self.drawdown_guard = DrawdownGuard(cfg.drawdown_guard)

        # 信号融合模块
        self.regime_context_builder = RegimeContextBuilder(
            regime_analyzer=regime_analyzer,
            weights=cfg.signal_fusion_weights,
        )

        self._risk_events: List[Dict[str, Any]] = []
        self._enabled = (cfg.enable_market_state_filter
                         or cfg.enable_volatility_risk
                         or cfg.enable_drawdown_guard
                         or cfg.enable_signal_fusion)

        # 各模块独立开关 — 同时传播到子模块 config.enabled
        self._enable_market_state_filter = cfg.enable_market_state_filter
        if not cfg.enable_market_state_filter:
            self.market_filter._enabled = False

        self._enable_volatility_risk = cfg.enable_volatility_risk
        if not cfg.enable_volatility_risk:
            self.volatility_mgr.config.enabled = False

        self._enable_drawdown_guard = cfg.enable_drawdown_guard
        if not cfg.enable_drawdown_guard:
            self.drawdown_guard.config.enabled = False

        self._enable_signal_fusion = cfg.enable_signal_fusion

    @property
    def enabled(self) -> bool:
        """是否启用任何风险模块。"""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        self._enable_market_state_filter = value
        self._enable_volatility_risk = value
        self._enable_drawdown_guard = value
        # 传播到子模块 config
        if hasattr(self, 'market_filter'):
            self.market_filter._enabled = value
        if hasattr(self, 'volatility_mgr'):
            self.volatility_mgr.config.enabled = value
        if hasattr(self, 'drawdown_guard'):
            self.drawdown_guard.config.enabled = value

    def process_pre_filter(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
    ) -> pd.DataFrame:
        """Step 1: 市场状态过滤。

        Args:
            signals: 信号 DataFrame。
            df_ohlcv: OHLCV DataFrame。

        Returns:
            pd.DataFrame: 过滤后的信号。
        """
        if not self._enable_market_state_filter:
            return signals
        result = self.market_filter.process(signals, df_ohlcv)
        self._risk_events.extend(
            self._event_to_dict(e) for e in self.market_filter.get_risk_events()
        )
        return result

    def process_position_sizing(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
        current_equity: Optional[float] = None,
    ) -> pd.DataFrame:
        """Step 2: ATR 动态仓位。

        Args:
            signals: 信号 DataFrame（含 'signal' 列）。
            df_ohlcv: OHLCV DataFrame。
            current_equity: 当前权益（可选）。

        Returns:
            pd.DataFrame: 含 'position_ratio' 列的信号 DataFrame。
        """
        if not self._enable_volatility_risk:
            result = signals.copy()
            result["position_ratio"] = 1.0
            return result
        result = self.volatility_mgr.process(signals, df_ohlcv, current_equity)
        self._risk_events.extend(
            self._event_to_dict(e) for e in self.volatility_mgr.get_risk_events()
        )

        # 如果 market_state_filter 设置了 position_scale，应用降仓系数
        if "position_scale" in result.columns:
            scale = result["position_scale"].iloc[-1] if len(result) > 0 else 1.0
            result["position_ratio"] = result["position_ratio"] * scale
            result.drop(columns=["position_scale"], inplace=True)

        return result

    def process_signal_fusion(
        self,
        df_ohlcv: pd.DataFrame,
        symbol: str = "",
    ) -> RegimeContextSignal:
        """Step 3: RegimeContextBuilder 信号融合。

        整合 Regime + AnchoredVWAP + Volume Profile + Knowledge 信号。

        Args:
            df_ohlcv: OHLCV DataFrame。
            symbol: 标的代码（可选）。

        Returns:
            RegimeContextSignal: 综合信号。
        """
        if not self._enable_signal_fusion:
            return RegimeContextSignal(
                composite_score=0.0,
                action="HOLD",
                confidence=0.0,
                regime="UNKNOWN",
                reasoning="信号融合已关闭",
            )

        signal = self.regime_context_builder.build_signal(df_ohlcv, symbol=symbol)

        self._risk_events.append({
            "event_type": "signal_fusion",
            "severity": "info",
            "description": f"综合信号: {signal.action} (score={signal.composite_score:.4f}, conf={signal.confidence:.2f})",
            "value": float(signal.composite_score),
            "threshold": 0.0,
        })

        return signal

    def get_drawdown_guard(self) -> DrawdownGuard:
        """返回 DrawdownGuard 实例，供循环内逐步调用。

        如果启用了 DrawdownGuard：
            - 每一 bar 调用 guard.update(equity, timestamp, signal) → safe_signal
            - 回测结束时收集 guard.get_risk_events()
        如果未启用：
            guard.update() 会直接原样返回 signal。
        """
        return self.drawdown_guard

    def get_all_risk_events(self) -> List[Dict[str, Any]]:
        """获取所有风控事件（含 drawdown 守卫中累积的）。"""
        events = list(self._risk_events)
        events.extend(
            self._event_to_dict(e) for e in self.drawdown_guard.get_risk_events()
        )
        return events

    def reset(self) -> None:
        """重置所有模块。"""
        self._risk_events.clear()
        self.drawdown_guard.reset()

    # ─── 内部辅助 ─────────────────────────────────────────────

    @staticmethod
    def _event_to_dict(event) -> Dict[str, Any]:
        """将 RiskEvent（dataclass）转换为 dict。"""
        if hasattr(event, "__dataclass_fields__"):
            return {
                "event_type": event.event_type,
                "timestamp": getattr(event, "timestamp", ""),
                "severity": getattr(event, "severity", "low"),
                "description": getattr(event, "description", ""),
                "value": float(getattr(event, "value", 0.0)),
                "threshold": float(getattr(event, "threshold", 0.0)),
            }
        return dict(event)
