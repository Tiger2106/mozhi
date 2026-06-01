"""
ComputeLayer — 计算层 (BT-001/GP-002/GP-004)
===========================================
职责：
1. 接收 BacktestData 合约，计算交易信号（Signal）
2. GP-002: 循环内零新分配（预分配缓冲区）
3. GP-004: 确定性执行，固定种子 seed=42
4. 策略接口标准化（BT-003）

约束：
- 输入：必须为 BacktestData 合约对象
- 输出：List[Signal]（标准信号协议）
- 禁止使用未来数据（由 TimeAlignmentGuard 保证）
- 所有随机数操作使用固定种子 seed=42

作者: moheng
版本: v1.0
"""
import abc
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Callable
from datetime import datetime, timezone, timedelta

import numpy as np

from ..contracts.backtest_data_contract import BacktestData, BacktestBar

_TZ_CN = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════════════
# 标准信号协议 (BT-003)
# ═══════════════════════════════════════════════════════════

@dataclass
class Signal:
    """计算层标准输出信号（精简版，不含订单执行细节）"""
    symbol: str
    direction: str                    # "BUY" | "SELL"
    confidence: float                 # [0, 1]
    bar_index: int                    # 信号触发的 bar 索引
    bar_date: str                     # 信号触发的日期
    signal_type: str                  # "trend" | "reversal" | "grid" | "momentum"
    extras: Dict[str, Any] = field(default_factory=dict)
    signal_id: str = ""


def _make_signal_id(symbol: str, direction: str, bar_index: int, signal_type: str) -> str:
    """确定性信号 ID（基于输入，不依赖随机数）"""
    raw = f"{symbol}_{direction}_{bar_index}_{signal_type}_{42}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════
# 策略基类 (BT-003)
# ═══════════════════════════════════════════════════════════

class Strategy(abc.ABC):
    """策略接口：所有具体策略必须实现 on_bar

    使用方式:
        class MyStrategy(Strategy):
            def on_bar(self, data: BacktestData, bar_idx: int,
                       context: Dict) -> Optional[Signal]:
                ...
    """

    def __init__(self):
        self._seed = 42
        np.random.seed(self._seed)  # GP-004: 固定种子

    @abc.abstractmethod
    def on_bar(self, data: BacktestData, bar_idx: int,
               context: Dict[str, Any]) -> Optional[List[Signal]]:
        """处理单根 K 线

        Args:
            data: 完整的 BacktestData 合约（只读，含前后文）
            bar_idx: 当前 bar 的索引（data.bars[bar_idx]）
            context: 跨 bar 状态字典（strategy 自行维护）

        Returns:
            None 或 List[Signal]
        """
        ...

    def on_start(self, context: Dict[str, Any]):
        """策略初始化回调"""
        pass

    def on_end(self, context: Dict[str, Any]):
        """策略结束回调"""
        pass


# ═══════════════════════════════════════════════════════════
# 简单 MA 交叉策略实现
# ═══════════════════════════════════════════════════════════

class MaCrossoverStrategy(Strategy):
    """MA 交叉策略 (BT-003 标准接口示例)

    参数:
        fast: 快均线周期 (默认 5)
        slow: 慢均线周期 (默认 20)
        position_ratio: 单次仓位比例 (默认 0.3)
        stop_loss: 止损比例 (默认 0.05)

    GP-002: 使用固定大小的 close_prices 列表，不额外分配
    """

    def __init__(self, fast: int = 5, slow: int = 20,
                 position_ratio: float = 0.3,
                 stop_loss: float = 0.05):
        super().__init__()
        self._fast = fast
        self._slow = slow
        self._position_ratio = position_ratio
        self._stop_loss = stop_loss

        # GP-002: 预分配
        self._close_cache: List[float] = [0.0] * (slow + 10)
        self._close_idx = 0

        # 状态
        self._in_position = False
        self._entry_price = 0.0
        self._prev_fast = None
        self._prev_slow = None

    def _sma(self, period: int) -> Optional[float]:
        """计算 SMA（使用环形缓冲区，GP-002 零新分配）"""
        if self._close_idx < period:
            return None
        total = 0.0
        for i in range(period):
            total += self._close_cache[(self._close_idx - 1 - i)
                                       % len(self._close_cache)]
        return total / period

    def on_bar(self, data: BacktestData, bar_idx: int,
               context: Dict[str, Any]) -> Optional[List[Signal]]:
        """MA 交叉策略的核心逻辑"""
        bar = data.bars[bar_idx]
        signals: List[Signal] = []

        # GP-002: 写入环形缓冲区（零新分配）
        self._close_cache[self._close_idx % len(self._close_cache)] = bar.close
        self._close_idx += 1

        # 计算均线
        fast_ma = self._sma(self._fast)
        slow_ma = self._sma(self._slow)
        if fast_ma is None or slow_ma is None:
            return None

        # 当前状态
        curr_fast = 1 if fast_ma > slow_ma else (-1 if fast_ma < slow_ma else 0)

        # 止损检查
        if self._in_position:
            pnl_pct = (bar.close - self._entry_price) / self._entry_price
            if pnl_pct <= -self._stop_loss:
                signals.append(Signal(
                    symbol=bar.symbol,
                    direction="SELL",
                    confidence=1.0,
                    bar_index=bar_idx,
                    bar_date=bar.date,
                    signal_type="trend",
                    extras={"reason": "stop_loss", "quantity": context.get("qty", 0)},
                    signal_id=_make_signal_id(bar.symbol, "SELL", bar_idx, "trend"),
                ))
                self._in_position = False
                return signals

        # 交叉检测
        prev_state = 0
        if self._prev_fast is not None:
            prev_state = 1 if self._prev_fast > self._prev_slow else (
                -1 if self._prev_fast < self._prev_slow else 0
            )

        self._prev_fast, self._prev_slow = fast_ma, slow_ma

        if curr_fast == 1 and prev_state <= 0 and not self._in_position:
            # BUY
            available = context.get("available_capital", 1000000)
            qty = int((available * self._position_ratio) / bar.close / 100) * 100
            if qty > 0:
                signals.append(Signal(
                    symbol=bar.symbol,
                    direction="BUY",
                    confidence=1.0,
                    bar_index=bar_idx,
                    bar_date=bar.date,
                    signal_type="trend",
                    extras={"quantity": qty},
                    signal_id=_make_signal_id(bar.symbol, "BUY", bar_idx, "trend"),
                ))
                self._in_position = True
                self._entry_price = bar.close
                context["qty"] = qty

        elif curr_fast == -1 and prev_state >= 0 and self._in_position:
            # SELL
            qty = context.get("qty", 0)
            if qty > 0:
                signals.append(Signal(
                    symbol=bar.symbol,
                    direction="SELL",
                    confidence=1.0,
                    bar_index=bar_idx,
                    bar_date=bar.date,
                    signal_type="trend",
                    extras={"quantity": qty, "reason": "ma_cross"},
                    signal_id=_make_signal_id(bar.symbol, "SELL", bar_idx, "trend"),
                ))
                self._in_position = False

        return signals if signals else None


# ═══════════════════════════════════════════════════════════
# 计算引擎
# ═══════════════════════════════════════════════════════════

class ComputeEngine:
    """计算引擎：将策略应用于 BacktestData

    GP-004: 所有随机数操作使用固定种子 seed=42
    GP-002: 策略层保证零新分配
    """

    def __init__(self, strategy: Strategy):
        self._strategy = strategy
        np.random.seed(42)

    def compute(self, data: BacktestData,
                initial_capital: float = 1_000_000.0) -> List[Signal]:
        """对 data 中的所有 bar 进行计算，返回信号列表

        Args:
            data: BacktestData 合约（必须已验证指纹）
            initial_capital: 初始资金

        Returns:
            List[Signal] — 所有信号的扁平列表
        """
        # 指纹验证
        if not data.verify_fingerprint():
            raise ValueError("Data fingerprint mismatch! Data may be corrupted.")

        context: Dict[str, Any] = {
            "available_capital": initial_capital,
            "qty": 0,
        }

        self._strategy.on_start(context)
        all_signals: List[Signal] = []

        # GP-002: 主循环——不在此层分配新对象（策略层自行管理）
        for idx in range(data.total_bars):
            result = self._strategy.on_bar(data, idx, context)
            if result:
                all_signals.extend(result)

        self._strategy.on_end(context)
        return all_signals
