"""
adapters — 旧适配器层（已标记 LEGACY）

所有旧适配器实现已移至 adapters._legacy 子包。
新系统请使用 adapter（单数）包进行红蓝并行信号对齐。

作者: 墨衡 (moheng)
创建时间: 2026-05-18 +08:00
标记时间: 2026-05-18 +08:00（R1 阶段四清理）
"""

# 向后兼容导出
from ._legacy.legacy_runner_adapter import LegacyRunnerAdapter

__all__ = [
    "LegacyRunnerAdapter",
]
