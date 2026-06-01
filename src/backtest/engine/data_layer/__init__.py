"""
engine.data_layer — 数据层 (BT-001/BT-004/GP-001)
=================================================
导出接口:
    DataLayer.load(symbol, start_date, end_date) → BacktestData
    BacktestBar / BacktestData — 数据合约
    TimeAlignmentGuard — 前视偏差运行时检测
    MissingValuePolicy — 缺失值处理

依赖:
    mozhi_platform.src.backtest.contracts.backtest_data_contract
    mozhi_platform.src.backtest.layers.data_layer

作者: moheng
版本: v1.0
"""
from .loader import DataLayer
from .contract import BacktestBar, BacktestData, MissingValuePolicy
from .guard import TimeAlignmentGuard, LookaheadRuntimeGuard

__all__ = [
    "DataLayer",
    "BacktestBar",
    "BacktestData",
    "MissingValuePolicy",
    "TimeAlignmentGuard",
    "LookaheadRuntimeGuard",
]
