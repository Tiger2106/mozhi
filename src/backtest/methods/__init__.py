"""
mozhi_platform.src.backtest.methods — 信号方法子包

提供：
- BaseMethod       — 方法抽象基类（合约四件套之一）
- MethodResult     — 方法执行结果数据类
- MethodManifest   — 方法元信息协议
- FACTOR_META      — 因子元信息协议
- METHOD_META      — 方法元信息模板
- validate_manifest— Manifest 校验工具

子包：
- trend/     — 趋势类信号方法（MaCross、MACD、Bollinger、VolumeProfile、Wyckoff）
- momentum/  — 动量类信号方法（RSI、KDJ、BIAS）
- grid/      — 网格策略方法
- reversal/  — 反转策略方法（带冷却器）
"""

from .base import BaseMethod, MethodResult
from .manifest import MethodManifest, FACTOR_META, METHOD_META, validate_manifest

# ─── 子包导入 ────────────────────────────────────────────
from . import trend
from . import momentum
from . import grid
from . import reversal

__all__ = [
    "BaseMethod",
    "MethodResult",
    "MethodManifest",
    "FACTOR_META",
    "METHOD_META",
    "validate_manifest",
    "trend",
    "momentum",
    "grid",
    "reversal",
]
