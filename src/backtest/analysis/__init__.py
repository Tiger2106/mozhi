"""墨枢 - 回测分析子包

提供：
- walk_forward — Walk Forward 分析（P4）
- signal_comparator — 红蓝信号偏差检测（可单独导入）
"""

# 不自动导入 signal_comparator（依赖问题由调用方自行处理）
# from .signal_comparator import compare, compare_result

__all__ = [
    "walk_forward",
]
