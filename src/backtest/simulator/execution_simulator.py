"""
墨枢 - Execution Simulator（R1 阶段二：任务4）

区间单模拟 + 滑点成本计算。

功能：
  1. fill_range_order(signal, market_data, slippage_bps) — 区间单模拟
  2. apply_slippage(price, direction, bps)               — 滑点应用

产出：
  FillRecord — 模拟成交记录（价格、时间、成交比例、滑点成本）

依赖:
  - src.backtest.models.signal_types — R1Signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.backtest.models.signal_types import R1Signal


@dataclass
class FillRecord:
    """模拟成交记录"""
    symbol: str
    fill_price: float
    fill_time: Optional[str]
    fill_ratio: float          # 0~1 成交比例
    slippage_cost: float       # 滑点带来的额外成本（金额）
    direction: int             # 1=买入, -1=卖出
    original_price: float      # 信号触发时的原价
    slippage_bps: float        # 实际应用的滑点（bp）
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "fill_price": round(self.fill_price, 4),
            "fill_time": self.fill_time or "",
            "fill_ratio": round(self.fill_ratio, 4),
            "slippage_cost": round(self.slippage_cost, 4),
            "direction": self.direction,
            "original_price": round(self.original_price, 4),
            "slippage_bps": self.slippage_bps,
            "timestamp": self.timestamp,
        }


# ─── 滑点应用 ────────────────────────────────────────────────

def apply_slippage(price: float, direction: int, bps: float = 3.0) -> float:
    """应用滑点后调整价格。

    买入时价格上移（支付更高价），卖出时价格下移（收到更低价）。

    Args:
        price: 原价
        direction: 1=买入, -1=卖出
        bps: 滑点基点（1bp = 0.01%）

    Returns:
        float: 调整后价格
    """
    slippage = price * bps / 10000.0
    if direction > 0:
        return price + slippage
    else:
        return price - slippage


# ─── 区间单模拟 ──────────────────────────────────────────────

def fill_range_order(
    signal: R1Signal,
    market_data: pd.DataFrame,
    slippage_bps: float = 3.0,
    price_tolerance: float = 0.005,
) -> FillRecord:
    """区间单模拟。

    在 signal 触发后的 market_data 窗口内，寻找可成交价格区间。
    支持部分成交（成交比例取决于价格触及深度）。

    模拟逻辑：
      1. 从 signal 时间点开始向后扫描 market_data
      2. 对于买入信号：寻找价格 <= 触发价 × (1 + 容忍度) 的 K 线
      3. 对于卖出信号：寻找价格 >= 触发价 × (1 - 容忍度) 的 K 线
      4. 按首次触发的价格成交，应用滑点
      5. 成交比例取决于后续 K 线中可成交 K 线的比例

    Args:
        signal: R1Signal 信号（提供 direction, price, timestamp）
        market_data: 信号触发后的市场 OHLCV DataFrame
        slippage_bps: 滑点基点（默认 3.0）
        price_tolerance: 价格容忍度（默认 0.5%）

    Returns:
        FillRecord: 模拟成交记录
    """
    if market_data.empty:
        return FillRecord(
            symbol="",
            fill_price=0.0,
            fill_time=None,
            fill_ratio=0.0,
            slippage_cost=0.0,
            direction=signal.direction,
            original_price=signal.price,
            slippage_bps=slippage_bps,
        )

    entry_price = signal.price
    direction = signal.direction

    # 扫描可成交 K 线
    fill_candidates: List[float] = []
    for _, row in market_data.iterrows():
        high = float(row.get('high', 0))
        low = float(row.get('low', 0))
        close = float(row.get('close', 0))

        if direction > 0:
            # 买入：价格触及容忍区间
            acceptable = entry_price * (1 + price_tolerance)
            if close <= acceptable or low <= acceptable:
                fill_candidates.append(close)
        else:
            # 卖出：价格触及容忍区间
            acceptable = entry_price * (1 - price_tolerance)
            if close >= acceptable or high >= acceptable:
                fill_candidates.append(close)

    if not fill_candidates:
        # 无成交
        return FillRecord(
            symbol="",
            fill_price=0.0,
            fill_time=None,
            fill_ratio=0.0,
            slippage_cost=0.0,
            direction=direction,
            original_price=entry_price,
            slippage_bps=slippage_bps,
        )

    # 成交价格 = 首次触及价格的滑点调整价
    first_fill_price = fill_candidates[0]
    fill_price = apply_slippage(first_fill_price, direction, slippage_bps)

    # 成交比例：可成交 K 线占比（保守估计）
    fill_ratio = min(len(fill_candidates) / max(len(market_data), 1), 1.0)

    # 滑点成本
    fill_quantity_equivalent = 1.0  # 标准化为 1 单位
    theoretical_cost = entry_price * fill_quantity_equivalent * fill_ratio
    actual_cost = fill_price * fill_quantity_equivalent * fill_ratio
    slippage_cost = abs(actual_cost - theoretical_cost)

    # 时间戳
    fill_time = None
    if isinstance(market_data.index, pd.DatetimeIndex) and len(market_data) > 0:
        fill_time = str(market_data.index[0])

    return FillRecord(
        symbol="",
        fill_price=round(fill_price, 4),
        fill_time=fill_time,
        fill_ratio=round(fill_ratio, 4),
        slippage_cost=round(slippage_cost, 4),
        direction=direction,
        original_price=entry_price,
        slippage_bps=slippage_bps,
    )


# ─── ExecutionSimulator 类 ───────────────────────────────────

class ExecutionSimulator:
    """执行模拟器，管理多个信号模拟。"""

    def __init__(self, default_slippage_bps: float = 3.0):
        self.default_slippage_bps = default_slippage_bps
        self.history: List[FillRecord] = []

    def simulate(
        self,
        signal: R1Signal,
        market_data: pd.DataFrame,
        slippage_bps: Optional[float] = None,
    ) -> FillRecord:
        """模拟执行单个信号。

        Args:
            signal: 信号
            market_data: 市场数据（信号后窗口）
            slippage_bps: 滑点基点（None 使用默认值）

        Returns:
            FillRecord: 成交记录
        """
        record = fill_range_order(
            signal,
            market_data,
            slippage_bps=slippage_bps or self.default_slippage_bps,
        )
        self.history.append(record)
        return record

    def get_history(self) -> List[Dict[str, Any]]:
        """获取所有成交记录（dict 格式）"""
        return [r.to_dict() for r in self.history]

    def reset(self) -> None:
        """重置历史"""
        self.history.clear()
