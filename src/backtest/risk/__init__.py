"""
mozhi_platform.src.backtest.risk — 风险中间件层

风险模块是 RiskPipeline 的三个组成部分：
- DrawdownGuard          — 回撤断路器
- VolatilityRiskManager  — ATR 动态仓位管理
- MarketStateFilter      — 市场状态信号过滤

导出接口:
    DrawdownGuard, DrawdownGuardConfig, DrawdownState
    VolatilityRiskManager, VolatilityRiskConfig
    MarketStateFilter, MarketStateFilterConfig
    RiskPipeline, RiskPipelineConfig
"""

from .drawdown_guard import DrawdownGuard, DrawdownGuardConfig, DrawdownState
from .volatility_risk_manager import VolatilityRiskManager, VolatilityRiskConfig
from .market_state_filter import MarketStateFilter, MarketStateFilterConfig
from .risk_pipeline import RiskPipeline, RiskPipelineConfig
from .regime_context_builder import RegimeContextBuilder, RegimeContextSignal

__all__ = [
    "DrawdownGuard",
    "DrawdownGuardConfig",
    "DrawdownState",
    "VolatilityRiskManager",
    "VolatilityRiskConfig",
    "MarketStateFilter",
    "MarketStateFilterConfig",
    "RiskPipeline",
    "RiskPipelineConfig",
    "RegimeContextBuilder",
    "RegimeContextSignal",
]
