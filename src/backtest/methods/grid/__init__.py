"""methods/grid/ — 网格类信号方法

包含：
- GridMethod — 网格策略（逐 Bar 判断，requires_state=True）
"""

from .grid_method import GridMethod

__all__ = [
    "GridMethod",
]
