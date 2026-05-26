"""墨枢 - 策略模块（Phase 2）"""

from .trend_position import (
    FixedPosition,
    TrendScorePosition,
    PyramidPosition,
    StopLossTakeProfit,
    TrendPositionManager,
    ExitSignal,
    create_position_manager,
)
from .trend_strategy import TrendStrategy
# ReversalStrategy 尚未就绪，暂时注释掉
# from .reversal_strategy import ReversalStrategy

__all__ = [
    # P2-01 ~ P2-07 趋势信号
    "TrendStrategy",
    # P3-01 ~ P3-04 反转信号
    # "ReversalStrategy",
    # P2-08 ~ P2-11 仓位管理
    "FixedPosition",
    "TrendScorePosition",
    "PyramidPosition",
    "StopLossTakeProfit",
    "TrendPositionManager",
    "ExitSignal",
    "create_position_manager",
]
