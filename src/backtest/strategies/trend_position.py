"""
墨枢 - P2-08 / P2-09 / P2-10 / P2-11 仓位管理模块

趋势策略专用的仓位计算与风控逻辑。

模块组成:
  P2-08  FixedPosition      — 固定比例开仓，全量平仓
  P2-09  TrendScorePosition — 根据趋势强度线性映射仓位比例
  P2-10  PyramidPosition    — 信号持续 N 天后金字塔加仓
  P2-11  StopLossTakeProfit — 固定止损 / 移动止损(MA20) / ATR止盈

用法::

    from backtest.strategies.trend_position import FixedPosition

    pos_mgr = FixedPosition(position_ratio=0.3)
    qty = pos_mgr.calc_open_quantity(capital=1_000_000, price=50.0)

    # 配合止损使用
    sl = StopLossTakeProfit(fixed_stop_loss=0.05)
    should_exit, reason = sl.check_exit(position, bar, bars, idx)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backtest.backtest_engine import Bar
from backtest.position_manager import Position


# ============================================================
# 常量
# ============================================================

DEFAULT_TREND_MAP: List[Tuple[float, float]] = [
    (60.0, 0.15),   # 60分 → 15%仓位
    (80.0, 0.30),   # 80分 → 30%仓位
    (100.0, 0.50),  # 100分 → 50%仓位
]


# ============================================================
# P2-08: 固定仓位模式
# ============================================================


class FixedPosition:
    """
    固定仓位模式（P2-08）。

    每次开仓使用固定比例的资金，平仓时全部卖出。

    参数
    ----------
    position_ratio : float
        开仓资金比例（0 < position_ratio <= 1），如 0.3 = 30%。
    """

    def __init__(self, position_ratio: float = 0.3):
        if not (0 < position_ratio <= 1):
            raise ValueError(
                f"position_ratio 应在 (0, 1] 区间，收到 {position_ratio}"
            )
        self._position_ratio = position_ratio

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {"position_ratio": self._position_ratio, "mode": "fixed"}

    @property
    def position_ratio(self) -> float:
        return self._position_ratio

    # ── 仓位计算 ──────────────────────────────────────────

    def calc_open_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """
        计算开仓数量（基于固定资金比例）。

        参数
        ----------
        capital : float
            当前可用资金。
        price : float
            开仓价格。
        min_shares : int
            最小交易单位（A 股 100 股）。

        返回
        -------
        int
            买入股数（向下取整到最小交易单位）。
        """
        target_amount = capital * self._position_ratio
        raw_shares = int(target_amount / price)
        return max(0, (raw_shares // min_shares) * min_shares)

    def calc_close_quantity(self, position: Position) -> int:
        """
        计算平仓数量（全部卖出）。

        参数
        ----------
        position : Position
            当前持仓对象。

        返回
        -------
        int
            平仓股数（持仓数量）。
        """
        return position.quantity


# ============================================================
# P2-09: 趋势强度仓位
# ============================================================


class TrendScorePosition:
    """
    趋势强度仓位管理（P2-09）。

    根据 trend_score（0~100 分）线性映射到仓位比例。
    默认映射表：
      - 60分 → 15%
      - 80分 → 30%
      - 100分 → 50%

    低于最低分时返回 0（不开仓）；
    超出最高分时按最高分对应比例；
    中间值线性插值。

    参数
    ----------
    score_map : List[Tuple[float, float]], optional
        映射表，元素为 (score, ratio)。
        默认 [(60.0, 0.15), (80.0, 0.30), (100.0, 0.50)]。
        要求 score 严格递增。
    """

    def __init__(
        self,
        score_map: Optional[List[Tuple[float, float]]] = None,
    ):
        self._score_map = sorted(
            score_map or DEFAULT_TREND_MAP,
            key=lambda x: x[0],
        )

        # 校验严格递增
        for i in range(1, len(self._score_map)):
            if self._score_map[i][0] <= self._score_map[i - 1][0]:
                raise ValueError(
                    f"score_map 要求 score 严格递增: "
                    f"{self._score_map[i - 1][0]} >= {self._score_map[i][0]}"
                )

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "score_map": [(round(s, 2), round(r, 4)) for s, r in self._score_map],
            "mode": "trend_score",
        }

    # ── 核心：分数 → 比例线性插值 ─────────────────────────

    def score_to_ratio(self, score: float) -> float:
        """
        将 trend_score 线性映射到仓位比例。

        参数
        ----------
        score : float
            趋势评分（0~100）。

        返回
        -------
        float
            仓位比例 [0, 1]。
        """
        if not self._score_map:
            return 0.0

        # 低于最低分 → 0
        if score < self._score_map[0][0]:
            return 0.0

        # 高于最高分 → 最高比例
        if score >= self._score_map[-1][0]:
            return self._score_map[-1][1]

        # 线性插值
        for i in range(len(self._score_map) - 1):
            s1, r1 = self._score_map[i]
            s2, r2 = self._score_map[i + 1]
            if s1 <= score <= s2:
                # ratio = r1 + (score - s1) * (r2 - r1) / (s2 - s1)
                ratio = r1 + (score - s1) * (r2 - r1) / (s2 - s1)
                return ratio

        return self._score_map[-1][1]

    # ── 仓位计算 ──────────────────────────────────────────

    def calc_open_quantity(
        self,
        capital: float,
        price: float,
        trend_score: float,
        min_shares: int = 100,
    ) -> int:
        """
        根据趋势评分计算开仓数量。

        参数
        ----------
        capital : float
            当前可用资金。
        price : float
            开仓价格。
        trend_score : float
            当前趋势评分（0~100）。
        min_shares : int
            最小交易单位（默认为 100）。

        返回
        -------
        int
            买入股数；score 低于最低分时为 0。
        """
        ratio = self.score_to_ratio(trend_score)
        if ratio <= 0:
            return 0

        target_amount = capital * ratio
        raw_shares = int(target_amount / price)
        return max(0, (raw_shares // min_shares) * min_shares)

    def calc_close_quantity(self, position: Position) -> int:
        """平仓时全部卖出。"""
        return position.quantity


# ============================================================
# P2-10: 金字塔加仓
# ============================================================


class PyramidPosition:
    """
    金字塔加仓模式（P2-10）。

    开仓后，信号持续 N 天触发一次加仓；
    每次加仓比例递减，最大加仓次数有限制。

    参数
    ----------
    initial_ratio : float
        首次开仓资金比例（默认 0.3）。
    add_wait_days : int
        触发加仓前需要等待的天数（默认 5）。
    max_adds : int
        最大加仓次数（默认 3，含首次开仓后第 1 次加仓）。
    add_decay : float
        加仓比例递减系数（默认 0.5）。
        第 N 次加仓比例 = initial_ratio * (add_decay ** N)，N >= 1。
    """

    def __init__(
        self,
        initial_ratio: float = 0.3,
        add_wait_days: int = 5,
        max_adds: int = 3,
        add_decay: float = 0.5,
    ):
        if not (0 < initial_ratio <= 1):
            raise ValueError(
                f"initial_ratio 应在 (0, 1] 区间，收到 {initial_ratio}"
            )
        if add_wait_days < 1:
            raise ValueError(f"add_wait_days 应 >= 1，收到 {add_wait_days}")
        if max_adds < 0:
            raise ValueError(f"max_adds 应 >= 0，收到 {max_adds}")
        if not (0 <= add_decay <= 1):
            raise ValueError(f"add_decay 应在 [0, 1] 区间，收到 {add_decay}")

        self._initial_ratio = initial_ratio
        self._add_wait_days = add_wait_days
        self._max_adds = max_adds
        self._add_decay = add_decay

        # 运行时状态（每次回测复位）
        self._add_count: int = 0        # 已加仓次数
        self._last_add_day: int = -1     # 上次加仓的 bar 索引
        self._open_day: int = -1         # 首次开仓的 bar 索引

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "initial_ratio": self._initial_ratio,
            "add_wait_days": self._add_wait_days,
            "max_adds": self._max_adds,
            "add_decay": self._add_decay,
            "mode": "pyramid",
        }

    # ── 状态管理 ──────────────────────────────────────────

    def reset(self) -> None:
        """回测开始前复位状态。"""
        self._add_count = 0
        self._last_add_day = -1
        self._open_day = -1

    def on_open(self, bar_index: int) -> None:
        """记录首次开仓时的 bar 索引。"""
        self._open_day = bar_index
        self._add_count = 0
        self._last_add_day = bar_index

    def on_close_all(self) -> None:
        """平仓后复位。"""
        self.reset()

    @property
    def add_count(self) -> int:
        return self._add_count

    @property
    def can_add_more(self) -> bool:
        """是否还可以继续加仓。"""
        return self._add_count < self._max_adds

    # ── 计算当前加仓比例 ──────────────────────────────────

    def current_add_ratio(self) -> float:
        """
        返回下一次加仓的资金比例（递减）。

        首次开仓: initial_ratio
        第 1 次加仓: initial_ratio * (add_decay ** 1)
        第 2 次加仓: initial_ratio * (add_decay ** 2)
        ...
        """
        return self._initial_ratio * (self._add_decay ** (self._add_count))

    # ── 触发条件判断 ──────────────────────────────────────

    def should_add(self, bar_index: int, signal_active: bool) -> bool:
        """
        判断当前是否满足加仓条件。

        条件：
          1. 已开仓（_open_day >= 0）
          2. 加仓次数未达上限
          3. 信号持续：距离上次加仓 >= add_wait_days 天
          4. 当前信号仍有效

        参数
        ----------
        bar_index : int
            当前 Bar 索引。
        signal_active : bool
            当前 Bar 信号是否仍为 BUY（持续看好）。

        返回
        -------
        bool
            True = 触发加仓。
        """
        if self._open_day < 0 or not signal_active:
            return False

        if self._add_count >= self._max_adds:
            return False

        days_since_last = bar_index - self._last_add_day
        return days_since_last >= self._add_wait_days

    # ── 提交加仓（调用后内部计数 +1）───────────────────────

    def commit_add(self, bar_index: int) -> None:
        """
        提交一次加仓（内部计数增加并更新状态）。

        必须在 should_add() 返回 True 后方可调用。
        """
        if self._add_count >= self._max_adds:
            raise RuntimeError(
                f"加仓次数已达上限 ({self._max_adds})，无法继续加仓"
            )
        self._add_count += 1
        self._last_add_day = bar_index

    # ── 仓位计算 ──────────────────────────────────────────

    def calc_open_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """首次开仓数量（基于 initial_ratio）。"""
        target_amount = capital * self._initial_ratio
        raw_shares = int(target_amount / price)
        return max(0, (raw_shares // min_shares) * min_shares)

    def calc_add_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """
        计算本次加仓数量（基于递减比例）。

        参数
        ----------
        capital : float
            当前可用资金。
        price : float
            加仓价格。
        min_shares : int
            最小交易单位。

        返回
        -------
        int
            加仓股数（可能为 0）。
        """
        ratio = self.current_add_ratio()
        if ratio <= 0:
            return 0
        target_amount = capital * ratio
        raw_shares = int(target_amount / price)
        return max(0, (raw_shares // min_shares) * min_shares)

    def calc_close_quantity(self, position: Position) -> int:
        """平仓时全部卖出。"""
        return position.quantity


# ============================================================
# P2-11: 止损止盈
# ============================================================


@dataclass
class ExitSignal:
    """
    平仓信号。

    Attributes
    ----------
    should_exit : bool
        是否应平仓。
    reason : str
        平仓原因描述。
    """
    should_exit: bool = False
    reason: str = ""


class StopLossTakeProfit:
    """
    止损止盈风控模块（P2-11）。

    支持三种风控机制，可独立或组合使用：
      1. 固定止损 — 价格跌幅超过阈值时平仓
      2. 移动止损（MA20）— 价格跌破 MA20 时平仓
      3. 止盈（ATR 倍数）— 盈利超过 N 倍 ATR 时平仓

    参数
    ----------
    fixed_stop_loss : float, optional
        固定止损比例（0~1）。如 0.05 = 跌幅超过 5% 止损。
        启用条件：不为 None 且 > 0。
    trailing_stop_ma_period : int, optional
        移动止损均线周期（默认 20）。启用条件：不为 None 且 > 0。
        当价格跌破该均线时平仓。
    take_profit_atr_multiple : float, optional
        ATR 止盈倍数。如 2.0 = 盈利超过 2 倍 ATR 时止盈。
        启用条件：不为 None 且 > 0。
    atr_period : int
        ATR 计算周期（默认 14，仅止盈启用时生效）。
    """

    def __init__(
        self,
        fixed_stop_loss: Optional[float] = None,
        trailing_stop_ma_period: Optional[int] = 20,
        take_profit_atr_multiple: Optional[float] = None,
        atr_period: int = 14,
    ):
        # ── 参数校验 ──────────────────────────────────
        if fixed_stop_loss is not None and not (0 < fixed_stop_loss < 1):
            raise ValueError(
                f"fixed_stop_loss 应在 (0, 1) 区间，收到 {fixed_stop_loss}"
            )
        if trailing_stop_ma_period is not None and trailing_stop_ma_period < 1:
            raise ValueError(
                f"trailing_stop_ma_period 应 > 0，收到 {trailing_stop_ma_period}"
            )
        if take_profit_atr_multiple is not None and take_profit_atr_multiple <= 0:
            raise ValueError(
                f"take_profit_atr_multiple 应 > 0，收到 {take_profit_atr_multiple}"
            )
        if atr_period < 2:
            raise ValueError(f"atr_period 应 >= 2，收到 {atr_period}")

        self.fixed_stop_loss = fixed_stop_loss
        self.trailing_stop_ma_period = trailing_stop_ma_period
        self.take_profit_atr_multiple = take_profit_atr_multiple
        self.atr_period = atr_period

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "fixed_stop_loss": self.fixed_stop_loss,
            "trailing_stop_ma_period": self.trailing_stop_ma_period,
            "take_profit_atr_multiple": self.take_profit_atr_multiple,
            "atr_period": self.atr_period,
            "mode": "stop_loss_take_profit",
        }

    # ── 辅助计算 ──────────────────────────────────────────

    @staticmethod
    def _calc_atr(bars: List[Bar], period: int) -> List[Optional[float]]:
        """
        计算 ATR（平均真实波幅）。

        返回长度与 bars 一致，前 period 个为 None。
        """
        n = len(bars)
        if n < period + 1:
            return [None] * n

        tr_values: List[float] = [0.0] * n
        for i in range(1, n):
            high = bars[i].high
            low = bars[i].low
            prev_close = bars[i - 1].close
            tr_values[i] = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )

        # Wilder 平滑 ATR
        atr: List[Optional[float]] = [None] * n
        atr[period] = sum(tr_values[1: period + 1]) / period
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr_values[i]) / period

        return atr

    @staticmethod
    def _calc_sma(values: List[float], period: int) -> List[Optional[float]]:
        """简单移动平均。"""
        n = len(values)
        result: List[Optional[float]] = [None] * n
        if n < period:
            return result
        window_sum = sum(values[:period])
        result[period - 1] = window_sum / period
        for i in range(period, n):
            window_sum += values[i] - values[i - period]
            result[i] = window_sum / period
        return result

    # ── 核心检查逻辑 ──────────────────────────────────────

    def check_exit(
        self,
        position: Position,
        bar: Bar,
        bars: List[Bar],
        bar_index: int,
    ) -> ExitSignal:
        """
        检查是否触发止损/止盈平仓条件。

        按优先级检查：固定止损 → 移动止损(MA20) → ATR止盈。
        任一条件满足即返回退出信号。

        参数
        ----------
        position : Position
            当前持仓对象（需有 avg_price 和 quantity）。
        bar : Bar
            当前 Bar。
        bars : List[Bar]
            完整的 Bar 序列（用于计算 MA20 和 ATR）。
        bar_index : int
            当前 Bar 的索引。

        返回
        -------
        ExitSignal
            should_exit=True 表示应平仓，reason 说明原因。
        """
        if position.is_empty:
            return ExitSignal()

        avg_cost = position.avg_cost
        if avg_cost <= 0:
            return ExitSignal()

        # ── 1. 固定止损 ─────────────────────────────
        if self.fixed_stop_loss is not None:
            pnl_pct = (bar.close - avg_cost) / avg_cost
            if pnl_pct <= -self.fixed_stop_loss:
                return ExitSignal(
                    should_exit=True,
                    reason=f"固定止损: 跌幅 {abs(pnl_pct):.2%} >= {self.fixed_stop_loss:.2%}",
                )

        # ── 2. 移动止损（MA20）─────────────────────
        if self.trailing_stop_ma_period is not None:
            # 从 bars 中获取最近 N 个 close 计算 SMA
            ma = self._calc_sma(
                [b.close for b in bars[: bar_index + 1]],
                self.trailing_stop_ma_period,
            )
            if bar_index < len(ma) and ma[bar_index] is not None:
                if bar.close < ma[bar_index]:
                    return ExitSignal(
                        should_exit=True,
                        reason=(
                            f"移动止损(MA{self.trailing_stop_ma_period}): "
                            f"价格 {bar.close:.2f} < MA "
                            f"{ma[bar_index]:.2f}"
                        ),
                    )

        # ── 3. ATR 止盈 ────────────────────────────
        if self.take_profit_atr_multiple is not None:
            pnl_pct = (bar.close - avg_cost) / avg_cost
            # 只在盈利时检查
            if pnl_pct > 0:
                atr = self._calc_atr(bars[: bar_index + 1], self.atr_period)
                if bar_index < len(atr) and atr[bar_index] is not None:
                    atr_val = atr[bar_index]
                    if atr_val > 0:
                        pnl_in_atr = (bar.close - avg_cost) / atr_val
                        if pnl_in_atr >= self.take_profit_atr_multiple:
                            return ExitSignal(
                                should_exit=True,
                                reason=(
                                    f"ATR止盈: 盈利 {pnl_in_atr:.1f}倍ATR "
                                    f">= {self.take_profit_atr_multiple}倍"
                                ),
                            )

        return ExitSignal()


# ============================================================
# 组合仓位管理器
# ============================================================


class TrendPositionManager:
    """
    组合仓位管理器。

    将仓位计算（Fixed/TrendScore/Pyramid）与
    风控（StopLossTakeProfit）组合使用。

    用法::

        pos = FixedPosition(position_ratio=0.3)
        sl = StopLossTakeProfit(fixed_stop_loss=0.05)
        mgr = TrendPositionManager(position_logic=pos, risk_control=sl)

        qty = mgr.calc_open_quantity(capital=1_000_000, price=50.0)

        exit_signal = mgr.check_exit(position, bar, bars, idx)
        if exit_signal.should_exit:
            # 平仓
            ...
    """

    def __init__(
        self,
        position_logic: Any,  # FixedPosition | TrendScorePosition | PyramidPosition
        risk_control: Optional[StopLossTakeProfit] = None,
    ):
        self.position_logic = position_logic
        self.risk_control = risk_control

    @property
    def params(self) -> Dict[str, Any]:
        p = {
            "position_logic": self.position_logic.params,
        }
        if self.risk_control is not None:
            p["risk_control"] = self.risk_control.params
        return p

    def calc_open_quantity(
        self,
        capital: float,
        price: float,
        trend_score: Optional[float] = None,
        min_shares: int = 100,
    ) -> int:
        """
        计算开仓数量，转发给具体的 position_logic 实现。

        参数
        ----------
        capital : float
            可用资金。
        price : float
            开仓价格。
        trend_score : float, optional
            趋势评分（TrendScorePosition 需要）。
        min_shares : int
            最小交易单位。
        """
        if isinstance(self.position_logic, FixedPosition):
            return self.position_logic.calc_open_quantity(capital, price, min_shares)
        elif isinstance(self.position_logic, TrendScorePosition):
            score = trend_score if trend_score is not None else 60.0
            return self.position_logic.calc_open_quantity(
                capital, price, score, min_shares
            )
        elif isinstance(self.position_logic, PyramidPosition):
            return self.position_logic.calc_open_quantity(capital, price, min_shares)
        else:
            raise TypeError(f"不支持的 position_logic 类型: {type(self.position_logic)}")

    def calc_close_quantity(self, position: Position) -> int:
        """计算平仓数量。"""
        if hasattr(self.position_logic, "calc_close_quantity"):
            return self.position_logic.calc_close_quantity(position)
        return position.quantity

    def check_exit(
        self,
        position: Position,
        bar: Bar,
        bars: List[Bar],
        bar_index: int,
    ) -> ExitSignal:
        """
        检查止损止盈条件。

        如果未配置 risk_control，返回默认 ExitSignal(should_exit=False)。
        """
        if self.risk_control is not None:
            return self.risk_control.check_exit(position, bar, bars, bar_index)
        return ExitSignal()


# ═══════════════════════════════════════════════════════════════
# 便捷函数：根据模式名快速创建仓位管理器
# ═══════════════════════════════════════════════════════════════

_POSITION_MODES = {
    "fixed": FixedPosition,
    "trend_score": TrendScorePosition,
    "pyramid": PyramidPosition,
}


def create_position_manager(
    mode: str = "fixed",
    position_ratio: float = 0.3,
    risk_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> TrendPositionManager:
    """
    工厂函数：根据模式名快速创建 TrendPositionManager。

    参数
    ----------
    mode : str
        仓位模式。可选 "fixed" / "trend_score" / "pyramid"。
    position_ratio : float
        固定仓位比例（mode="fixed" 时生效）。
    risk_config : dict, optional
        风控配置，传给 StopLossTakeProfit。
        如 {"fixed_stop_loss": 0.05, "take_profit_atr_multiple": 2.0}。
    **kwargs
        仓位对象的其他参数（如 TrendScorePosition 的 score_map，
        PyramidPosition 的 add_wait_days / max_adds / add_decay）。

    返回
    -------
    TrendPositionManager

    用法::

        # 固定仓位 30% + 固定止损 5%
        mgr = create_position_manager(
            mode="fixed",
            position_ratio=0.3,
            risk_config={"fixed_stop_loss": 0.05},
        )

        # 趋势强度仓位
        mgr = create_position_manager(
            mode="trend_score",
        )

        # 金字塔加仓 + MA20 移动止损
        mgr = create_position_manager(
            mode="pyramid",
            add_wait_days=5,
            max_adds=3,
            add_decay=0.5,
            risk_config={"trailing_stop_ma_period": 20},
        )
    """
    cls = _POSITION_MODES.get(mode)
    if cls is None:
        raise ValueError(
            f"未知仓位模式: {mode}，可选: {list(_POSITION_MODES.keys())}"
        )

    # 构建仓位对象
    if cls is FixedPosition:
        pos_logic = cls(position_ratio=position_ratio)
    else:
        pos_logic = cls(**kwargs)

    # 构建风控
    risk_control: Optional[StopLossTakeProfit] = None
    if risk_config:
        risk_control = StopLossTakeProfit(**risk_config)

    return TrendPositionManager(position_logic=pos_logic, risk_control=risk_control)
