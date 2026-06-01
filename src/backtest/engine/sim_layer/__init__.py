"""
engine.sim_layer — 模拟交易层 (BT-001/BT-005/BT-008)
========================================================
导出接口:
    ConstraintAwareExecutor — 约束感知执行器（BT-008）
    SimulateResult          — 模拟层输出
    TradeRecord             — 交易记录（BT-005）
    PositionSnapshot        — 日终持仓快照
    simulate                — 一站式模拟执行
    ConstraintManager       — 约束管理器（BT-008 优先级）
    TradeLogger             — 交易日志审计器（BT-005）
    BaseSlippageModel       — 滑点模型基类（可扩展）
    TieredSlippageModel     — 按流动性分档的滑点模型（P1-2）
    SlippageParams          — 滑点参数配置

P1 修复:
    P1-1: 涨跌停板约束增强（prev_close 计算价格边界）
    P1-2: 按流动性分档的滑点模型
    P1-3: 交易量容量约束

作者: moheng
版本: v1.1
"""
from .simulator import (
    ConstraintAwareExecutor,
    SimulateResult,
    TradeRecord,
    PositionSnapshot,
    simulate,
    BaseSlippageModel,
    TieredSlippageModel,
    SlippageParams,
    SLIPPAGE_LARGE_CAP,
    SLIPPAGE_SMALL_CAP,
    MARKET_CAP_THRESHOLD,
)
from .constraints import ConstraintManager, VOLUME_CAPACITY_PCT
from .logger import TradeLogger

__all__ = [
    "ConstraintAwareExecutor",
    "SimulateResult",
    "TradeRecord",
    "PositionSnapshot",
    "simulate",
    "ConstraintManager",
    "TradeLogger",
    "BaseSlippageModel",
    "TieredSlippageModel",
    "SlippageParams",
    "SLIPPAGE_LARGE_CAP",
    "SLIPPAGE_SMALL_CAP",
    "MARKET_CAP_THRESHOLD",
    "VOLUME_CAPACITY_PCT",
]
