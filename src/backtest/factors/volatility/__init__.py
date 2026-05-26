"""
mozhi_platform.src.backtest.factors.volatility — 波动率类因子子包

提供：
- ATRFactor          — 平均真实波幅（Average True Range）
- BollingerFactor    — 布林带（Bollinger Bands）
"""

from .atr_factor import ATRFactor, FACTOR_META as ATR_FACTOR_META
from .bollinger_factor import BollingerFactor, FACTOR_META as BOLLINGER_FACTOR_META

__all__ = [
    "ATRFactor",
    "ATR_FACTOR_META",
    "BollingerFactor",
    "BOLLINGER_FACTOR_META",
]
