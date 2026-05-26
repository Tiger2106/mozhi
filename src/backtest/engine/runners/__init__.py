"""
mozhi_platform.src.backtest.engine.runners — Runner 子包

设计参考: plugin_system_final_design_20260517.md §5.4

实际实现在 backtest.runners.method_backtest_runner。
此文件作为统一入口导出。
"""

from backtest.runners.method_backtest_runner import (
    MethodBacktestRunner,
    discover_methods_recursive,
)

__all__ = [
    "MethodBacktestRunner",
    "discover_methods_recursive",
]
