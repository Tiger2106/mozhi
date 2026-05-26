"""
墨枢 — 双系统并行验证测试套件

Phase 3 双系统并行验证：确保新路径（Signal+Consumer）与旧路径（SignalBridge）输出一致。

author: 墨衡
created_time: 2026-05-20
"""

from .dual_validator import DualValidator, ValidationReport, DeviationItem

__all__ = [
    "DualValidator",
    "ValidationReport",
    "DeviationItem",
]
