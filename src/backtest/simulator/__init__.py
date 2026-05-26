"""墨枢 - 红蓝信号模拟器子包（R1 阶段二）

提供：
- execution_simulator    — 区间单模拟 + 滑点成本
- red_blue_parallel — 红蓝并行执行引擎
"""

from .execution_simulator import ExecutionSimulator, FillRecord, fill_range_order, apply_slippage
from .red_blue_parallel import ParallelEngine

__all__ = [
    "ExecutionSimulator", "FillRecord", "fill_range_order", "apply_slippage",
    "ParallelEngine", "DualResult",
]
