"""
DataLayer — 数据层加载器 (GP-001: 一次性加载)
==============================================
职责:
    - 从数据库/CSV一次性加载数据
    - 输出 BacktestData 合约（BT-004）
    - GP-001: 仅加载一次，防重复加载

实现:
    基于 layers.data_layer.DataLayer，封装确定性 API。

用法:
    from engine.data_layer import DataLayer
    dl = DataLayer()
    data = dl.load("601857.SH", start_date="20200101", end_date="20260515")

作者: moheng
版本: v1.0
"""
from ...layers.data_layer import DataLayer

__all__ = ["DataLayer"]
