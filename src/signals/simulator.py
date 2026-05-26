"""
SignalSimulator — 独立验证单个 Signal 效果的模拟器。

轻量级模拟器，仅做基础价格模拟，不依赖 BacktestEngine。
目标是快速验证信号在历史数据上的预期表现，输出简洁统计。

依赖：
  - pandas, numpy（数据计算）
  - Signal 协议 v1（信号输入）

输出：
  SimResult dataclass — 预期收益、风险、持有周期等统计

author: 墨衡
created_time: 2026-05-20
"""

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from .signal_protocol_v1 import Signal

# ── 日志 ──────────────────────────────────────────────────

import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# SimResult
# ═══════════════════════════════════════════════════════════


@dataclass
class SimResult:
    """信号模拟结果。

    Attributes:
        signal_id: 原始信号的 ID。
        symbol: 标的代码。
        direction: 信号方向（BUY / SELL / HOLD）。
        expected_return: 模拟累计收益率（百分比，如 2.5 表示 2.5%）。
        max_drawdown: 模拟期间最大回撤（百分比，如 -3.2 表示 -3.2%）。
        holding_periods: 持有周期数（bar 数量）。
        win_rate: 正收益周期占比（0.0 ~ 1.0）。
        sharpe_approx: 近似夏普比率（收益率均值 / 收益率标准差）。
        total_trades: 总交易次数（此模拟器固定为 1，扩展预留）。
        confidence: 信号原始置信度。
        note: 附加说明。
    """

    signal_id: str = ""
    symbol: str = ""
    direction: str = ""
    expected_return: float = 0.0
    max_drawdown: float = 0.0
    holding_periods: int = 0
    win_rate: float = 0.0
    sharpe_approx: float = 0.0
    total_trades: int = 0
    confidence: float = 0.0
    note: str = ""


# ═══════════════════════════════════════════════════════════
# 默认参数
# ═══════════════════════════════════════════════════════════

DEFAULT_HOLDING_PERIODS = 5      # 默认持有周期数（bar）
DEFAULT_QUANTITY = 100           # 默认模拟数量


# ═══════════════════════════════════════════════════════════
# SignalSimulator
# ═══════════════════════════════════════════════════════════


class SignalSimulator:
    """独立验证 Signal 效果，不接触真实订单路径。

    使用方法：
      simulator = SignalSimulator()
      result = simulator.evaluate(signal, price_data)

    模拟逻辑：
      1. 按 signal.direction 决定开仓方向
      2. 在开仓点以 entry_price 建仓
      3. 持有 holding_periods 个 bar 后平仓
      4. 统计收益、回撤、胜率、近似夏普
    """

    def __init__(self, holding_periods: int = DEFAULT_HOLDING_PERIODS):
        """初始化模拟器。

        Args:
            holding_periods: 每个信号默认持有多少个 bar（K线周期）。
                            可在 evaluate() 中通过 signal.extras 覆盖。
        """
        self.holding_periods = holding_periods

    # ── 公共方法 ─────────────────────────────────────────

    def evaluate(
        self,
        signal: Signal,
        price_data: pd.DataFrame,
    ) -> SimResult:
        """模拟信号在历史价格数据上的效果。

        步骤:
          1. 检查数据完备性
          2. 确定入场点（使用 signal.extras.get("entry_index", 0)）
          3. 计算方向逻辑
          4. 模拟持有周期内的收益
          5. 统计并返回 SimResult

        Args:
            signal: Signal 协议 v1 信号对象。
            price_data: 包含价格数据的 DataFrame，至少需要列 "close"。
                        可选 "open", "high", "low" 用于更精确计算。
                        索引建议为 datetime 或 int 序号。

        Returns:
            SimResult: 模拟统计结果。
        """
        # ── 数据校验 ──
        if price_data is None or len(price_data) == 0:
            return self._empty_result(signal, "price_data 为空")

        if "close" not in price_data.columns:
            return self._empty_result(signal, "price_data 缺少 'close' 列")

        closes = price_data["close"].values
        n = len(closes)
        if n < 2:
            return self._empty_result(signal, "价格数据不足 2 个周期")

        # ── 入场点 ──
        entry_index = self._resolve_entry_index(signal, n)
        if entry_index >= n:
            entry_index = 0

        entry_price = closes[entry_index]
        if entry_price <= 0:
            return self._empty_result(signal, f"入场价格无效: {entry_price}")

        # ── 持有周期 ──
        periods = self._resolve_holding_periods(signal, n, entry_index)
        end_index = min(entry_index + periods, n - 1)

        # ── 方向判断 ──
        if signal.direction == "HOLD":
            return self._empty_result(signal, "HOLD 方向模拟无意义")

        multiplier = 1.0 if signal.direction == "BUY" else -1.0

        # ── 周期切片 ──
        period_prices = closes[entry_index : end_index + 1]
        period_returns = np.diff(period_prices) / period_prices[:-1] * multiplier

        if len(period_returns) == 0:
            return SimResult(
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                direction=signal.direction,
                expected_return=0.0,
                max_drawdown=0.0,
                holding_periods=1,
                win_rate=0.0,
                sharpe_approx=0.0,
                total_trades=1,
                confidence=signal.confidence,
                note="持有期过短，无有效 return",
            )

        # ── 累计收益（百分比） ──
        cumulative_return = (
            (period_prices[-1] - entry_price) / entry_price * multiplier * 100
        )

        # ── 最大回撤 ──
        if signal.direction == "BUY":
            peak = np.maximum.accumulate(period_prices)
            dd = (period_prices - peak) / peak * 100
            max_dd = float(np.min(dd))
        else:
            # SELL: 做空 — 价格上升 = 浮亏
            trough = np.minimum.accumulate(period_prices)
            dd = (trough - period_prices) / period_prices * 100 * multiplier
            max_dd = float(np.min(dd)) if len(dd) > 0 else 0.0

        # ── 胜率 ──
        win_rate = float(np.mean(period_returns > 0))

        # ── 近似夏普 ──
        mean_ret = float(np.mean(period_returns))
        std_ret = float(np.std(period_returns, ddof=1))
        sharpe = mean_ret / std_ret if std_ret > 1e-10 else 0.0

        return SimResult(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.direction,
            expected_return=round(cumulative_return, 4),
            max_drawdown=round(max_dd, 4),
            holding_periods=len(period_prices),
            win_rate=round(win_rate, 4),
            sharpe_approx=round(sharpe, 4),
            total_trades=1,
            confidence=signal.confidence,
            note="模拟完成",
        )

    # ── 内部方法 ─────────────────────────────────────────

    def _resolve_entry_index(self, signal: Signal, n: int) -> int:
        """从 signal.extras 或默认值解析入场索引。

        Args:
            signal: Signal 对象。
            n: 价格数据长度。

        Returns:
            int: 入场索引（0 ≤ index < n）。
        """
        idx = signal.extras.get("entry_index", 0)
        try:
            idx = int(idx)
        except (ValueError, TypeError):
            idx = 0
        return max(0, min(idx, n - 1))

    def _resolve_holding_periods(
        self, signal: Signal, n: int, entry_index: int
    ) -> int:
        """解析持有周期数。

        优先级: signal.extras["holding_periods"] > self.holding_periods

        Args:
            signal: Signal 对象。
            n: 价格数据长度。
            entry_index: 入场索引。

        Returns:
            int: 持有周期数（保证 ≤ n - entry_index - 1 且 ≥ 1）。
        """
        periods = signal.extras.get("holding_periods", self.holding_periods)
        try:
            periods = int(periods)
        except (ValueError, TypeError):
            periods = self.holding_periods
        # 确保不会超出数据范围
        max_periods = max(n - entry_index - 1, 1)
        return max(1, min(periods, max_periods))

    def _empty_result(self, signal: Signal, reason: str) -> SimResult:
        """返回一个空的模拟结果（用于数据不足等异常情况）。

        Args:
            signal: Signal 对象。
            reason: 原因说明。

        Returns:
            SimResult: 空统计结果。
        """
        logger.warning(
            "simulate: signal=%s symbol=%s → %s",
            signal.signal_id, signal.symbol, reason,
        )
        return SimResult(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            direction=signal.direction,
            expected_return=0.0,
            max_drawdown=0.0,
            holding_periods=0,
            win_rate=0.0,
            sharpe_approx=0.0,
            total_trades=0,
            confidence=signal.confidence,
            note=reason,
        )
