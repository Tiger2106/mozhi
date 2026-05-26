"""methods/trend/ — 趋势类信号方法

包含：
- MaCrossMethod      — 双均线交叉（金叉/死叉）
- MACDMethod         — MACD 策略（DIF-DEA 穿越）
- BollingerMethod    — 布林带策略（突破/回归）
- VolumeProfileMethod— 成交量分布分析方法（新）
- WyckoffMethod      — 威科夫量价分析方法（新）
"""

from .ma_cross_method import MaCrossMethod
from .macd_method import MACDMethod
from .bollinger_method import BollingerMethod
from .volume_profile_method import VolumeProfileMethod
from .wyckoff_method import WyckoffMethod

__all__ = [
    "MaCrossMethod",
    "MACDMethod",
    "BollingerMethod",
    "VolumeProfileMethod",
    "WyckoffMethod",
]
