"""
信号计算层 (BT-003/GP-002/GP-004)
==================================
职责:
    1. 接收 BacktestData 合约，计算交易信号
    2. GP-002: 循环内零新分配（预分配缓冲区）
    3. GP-004: 固定种子 seed=42
    4. 策略接口标准化（BT-003）

实现:
    基于 layers.compute_layer，提供一站式接口。

用法:
    from engine.calc_layer import compute
    signals = compute(data, strategy="ma_cross", fast=5, slow=20)

作者: moheng
版本: v1.0
"""
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from ...layers.compute_layer import (
    Signal as _Signal,
    Strategy,
    MaCrossoverStrategy,
    ComputeEngine,
)
from ...contracts.backtest_data_contract import BacktestData


# 重导出标准类型
@dataclass
class Signal:
    """标准信号协议 (BT-003)"""
    symbol: str
    direction: str                    # "BUY" | "SELL"
    confidence: float                 # [0, 1]
    bar_index: int                    # 信号触发的 bar 索引
    bar_date: str                     # 信号触发的日期
    signal_type: str                  # "trend" | "reversal" | "grid" | "momentum"
    extras: Dict[str, Any] = field(default_factory=dict)
    signal_id: str = ""


SignalList = List[Signal]


def compute(
    data: BacktestData,
    strategy_type: str = "ma_cross",
    strategy_params: Optional[Dict[str, Any]] = None,
    initial_capital: float = 1_000_000.0,
) -> List[_Signal]:
    """一站式信号计算

    Args:
        data: BacktestData 合约（已验证指纹）
        strategy_type: 策略类型，目前支持 "ma_cross"
        strategy_params: 策略参数 dict
        initial_capital: 初始资金（用于策略上下文）

    Returns:
        List[Signal] — 所有信号的扁平列表

    GP-002: 策略层保证循环内零新分配
    GP-004: 固定种子 seed=42
    """
    if strategy_params is None:
        strategy_params = {"fast": 5, "slow": 20}

    # 构建策略
    if strategy_type == "ma_cross":
        strategy = MaCrossoverStrategy(
            fast=strategy_params.get("fast", 5),
            slow=strategy_params.get("slow", 20),
            position_ratio=strategy_params.get("position_ratio", 0.3),
            stop_loss=strategy_params.get("stop_loss", 0.05),
        )
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

    # 计算引擎
    engine = ComputeEngine(strategy=strategy)
    raw_signals = engine.compute(data, initial_capital=initial_capital)

    # 转换为标准信号
    return raw_signals


__all__ = ["Signal", "SignalList", "Strategy", "MaCrossoverStrategy",
           "ComputeEngine", "compute"]
