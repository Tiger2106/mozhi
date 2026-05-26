"""
adapter — 红蓝并行信号对齐适配层

用于旧系统 float dict 信号格式 ↔ R1Signal 新系统格式的双向转换。
红蓝并行阶段 signal_diff 一致性校验通过此层实现。

作者: 墨衡 (moheng)
创建时间: 2026-05-18 10:30 +08:00
"""

from .legacy_signal_adapter import legacy_to_r1signal, r1signal_to_legacy

__all__ = [
    "legacy_to_r1signal",
    "r1signal_to_legacy",
]
