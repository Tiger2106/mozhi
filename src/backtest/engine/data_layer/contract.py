"""
BacktestData 合约 (BT-004) — 数据层→计算层数据契约
====================================================
直接导出 contracts.backtest_data_contract 的类型。

包含:
    BacktestBar     — 单根K线数据合约
    BacktestData    — 完整数据合约（含指纹）
    MissingValuePolicy — 缺失值处理策略
    BarField        — K线字段约束

用法:
    from engine.data_layer.contract import BacktestData, BacktestBar

作者: moheng
版本: v1.0
"""
from ...contracts.backtest_data_contract import (
    BacktestBar,
    BacktestData,
    MissingValuePolicy,
    BarField,
)

__all__ = [
    "BacktestBar",
    "BacktestData",
    "MissingValuePolicy",
    "BarField",
]
