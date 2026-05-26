"""
mozhi_platform.src.backtest.engine.adapters — 适配器子包（R1 阶段四更新）

设计参考: plugin_system_final_design_20260517.md §7

旧实现已在 backtest.adapters._legacy 中归档。
新系统请使用 backtest.adapter（单数）进行红蓝并行信号对齐。
"""

from backtest.adapters._legacy.legacy_runner_adapter import LegacyRunnerAdapter

__all__ = [
    "LegacyRunnerAdapter",
]
