"""
engine.calc_layer — 计算层 (BT-001/BT-003/GP-002/GP-004)
=========================================================
导出接口:
    Signal                  — 标准信号协议
    SignalList              — 信号列表
    Strategy                — 策略基类（BT-003）
    MaCrossoverStrategy     — MA交叉策略实现
    ComputeEngine           — 计算引擎（接收BacktestData → 输出Signal[]）
    compute                 — 一站式信号计算函数

依赖:
    mozhi_platform.src.backtest.layers.compute_layer

作者: moheng
版本: v1.0
"""
from .signals import (
    Signal,
    Strategy,
    MaCrossoverStrategy,
    ComputeEngine,
    compute,
)

__all__ = [
    "Signal",
    "Strategy",
    "MaCrossoverStrategy",
    "ComputeEngine",
    "compute",
]
