"""
墨枢 - P3-09 / P3-10 / P3-11 / P3-12 反转仓位管理

反转策略专用的仓位计算与风控逻辑。

模块组成:
  P3-09  FixedReversalPosition   — 保守固定仓位（15%/20%）
  P3-10  OversoldDepthPosition   — RSI 超卖深度仓位映射
  P3-11  BatchReversalPosition   — 分批建仓（首日部分+次日确认）
  P3-12  ReversalStopLoss        — 反转止损（买入价-ATR×2 / 固定-5%）

用法::

    from backtest.strategies.reversal_position import FixedReversalPosition

    pos_mgr = FixedReversalPosition(position_ratio=0.20)
    qty = pos_mgr.calc_open_quantity(capital=1_000_000, price=50.0)

    # 配合反转止损使用
    sl = ReversalStopLoss(entry_price=50.0)
    should_exit, reason = sl.check_exit(position, bar, bars, idx)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backtest.backtest_engine import Bar
from backtest.position_manager import Position


# ============================================================
# P3-09: 固定仓位模式
# ============================================================


class FixedReversalPosition:
    """
    固定仓位模式（P3-09）。

    反转策略专用，相对保守的固定仓位比例（默认 15%~20%）。
    每次开仓使用固定比例的资金，平仓时全部卖出。
    买入数量向下取整到 100 股。

    参数
    ----------
    position_ratio : float
        开仓资金比例（0 < position_ratio <= 1），如 0.15 = 15%。
        默认 0.20（20%），相对趋势策略保守。
    """

    def __init__(self, position_ratio: float = 0.20):
        if not (0 < position_ratio <= 1):
            raise ValueError(
                f"position_ratio 应在 (0, 1] 区间，收到 {position_ratio}"
            )
        self._position_ratio = position_ratio

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {"position_ratio": self._position_ratio, "mode": "reversal_fixed"}

    @property
    def position_ratio(self) -> float:
        return self._position_ratio

    # ── 仓位计算 ──────────────────────────────────────────

    def calc_open_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """
        计算开仓数量（基于固定资金比例，取整 100 股）。

        参数
        ----------
        capital : float
            当前可用资金。
        price : float
            开仓价格。
        min_shares : int
            最小交易单位（A 股 100 股，默认 100）。

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
# P3-10: 超卖深度仓位映射
# ============================================================


class OversoldDepthPosition:
    """
    超卖深度仓位映射（P3-10）。

    根据 RSI 超卖程度动态决定仓位比例：RSI 越低，仓位越大。

    默认映射:
      - RSI >= 30 → 0%（不开仓）
      - RSI < 25  → 25%
      - RSI < 15  → 35%
      - RSI 在 25~30 之间线性插值（0%~25%）
      - RSI 在 15~25 之间线性插值（25%~35%）

    参数
    ----------
    rsi_max_threshold : float
        RSI 最高阈值，高于此值不开仓（默认 30）。
    oversold_25_ratio : float
        RSI < 25 时的仓位比例（默认 0.25）。
    rsi_25_threshold : float
        第二个阈值（默认 25）。
    oversold_15_ratio : float
        RSI < 15 时的仓位比例（默认 0.35）。
    rsi_15_threshold : float
        最低阈值（默认 15）。
    """

    def __init__(
        self,
        rsi_max_threshold: float = 30.0,
        oversold_25_ratio: float = 0.25,
        rsi_25_threshold: float = 25.0,
        oversold_15_ratio: float = 0.35,
        rsi_15_threshold: float = 15.0,
    ):
        # 校验阈值顺序
        if not (rsi_15_threshold < rsi_25_threshold < rsi_max_threshold):
            raise ValueError(
                f"需要 rsi_15_threshold ({rsi_15_threshold}) < "
                f"rsi_25_threshold ({rsi_25_threshold}) < "
                f"rsi_max_threshold ({rsi_max_threshold})"
            )
        # 超卖越深仓位越大，所以 oversold_15_ratio >= oversold_25_ratio
        if not (0 <= oversold_25_ratio <= oversold_15_ratio <= 1):
            raise ValueError(
                f"需要 0 <= oversold_25_ratio ({oversold_25_ratio}) "
                f"<= oversold_15_ratio ({oversold_15_ratio}) <= 1"
            )

        self.rsi_max_threshold = rsi_max_threshold
        self.oversold_25_ratio = oversold_25_ratio
        self.rsi_25_threshold = rsi_25_threshold
        self.oversold_15_ratio = oversold_15_ratio
        self.rsi_15_threshold = rsi_15_threshold

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "rsi_max_threshold": self.rsi_max_threshold,
            "oversold_25_ratio": self.oversold_25_ratio,
            "rsi_25_threshold": self.rsi_25_threshold,
            "oversold_15_ratio": self.oversold_15_ratio,
            "rsi_15_threshold": self.rsi_15_threshold,
            "mode": "oversold_depth",
        }

    # ── 核心：RSI → 比例映射（线性插值） ─────────────────

    def rsi_to_ratio(self, rsi_value: float) -> float:
        """
        将 RSI 值线性映射到仓位比例。

        参数
        ----------
        rsi_value : float
            当前 RSI 值。

        返回
        -------
        float
            仓位比例 [0, 1]。
        """
        # 高于最高阈值 → 不开仓
        if rsi_value >= self.rsi_max_threshold:
            return 0.0

        # 低于最低阈值 → 最高仓位
        if rsi_value <= self.rsi_15_threshold:
            return self.oversold_15_ratio

        # RSI 在 15~25 之间 → 线性插值到 25%~35%
        if rsi_value <= self.rsi_25_threshold:
            # ratio = rsi_15_ratio + (value - 15) * (rsi_25_ratio - rsi_15_ratio) / (25 - 15)
            ratio = self.oversold_15_ratio + (
                (rsi_value - self.rsi_15_threshold)
                * (self.oversold_25_ratio - self.oversold_15_ratio)
                / (self.rsi_25_threshold - self.rsi_15_threshold)
            )
            return ratio

        # RSI 在 25~30 之间 → 线性插值到 0%~25%
        ratio = self.oversold_25_ratio + (
            (rsi_value - self.rsi_25_threshold)
            * (0.0 - self.oversold_25_ratio)
            / (self.rsi_max_threshold - self.rsi_25_threshold)
        )
        return max(0.0, ratio)

    # ── 仓位计算 ──────────────────────────────────────────

    def calc_open_quantity(
        self,
        capital: float,
        price: float,
        rsi_value: float,
        min_shares: int = 100,
    ) -> int:
        """
        根据 RSI 超卖程度计算开仓数量。

        参数
        ----------
        capital : float
            当前可用资金。
        price : float
            开仓价格。
        rsi_value : float
            当前 RSI 值。
        min_shares : int
            最小交易单位（默认 100）。

        返回
        -------
        int
            买入股数；RSI >= threshold 时返回 0。
        """
        ratio = self.rsi_to_ratio(rsi_value)
        if ratio <= 0:
            return 0

        target_amount = capital * ratio
        raw_shares = int(target_amount / price)
        return max(0, (raw_shares // min_shares) * min_shares)

    def calc_close_quantity(self, position: Position) -> int:
        """平仓时全部卖出。"""
        return position.quantity


# ============================================================
# P3-11: 分批建仓模式
# ============================================================


class BatchReversalPosition:
    """
    分批建仓模式（P3-11）。

    超卖信号出现后，首日开部分仓位；
    确认日后（信号持续 / 价格未恶化）加仓至目标仓位。

    参数
    ----------
    first_ratio : float
        首日开仓资金比例（默认 0.10，即 10%）。
    second_ratio : float
        次日确认加仓资金比例（默认 0.15，即 15%）。
    confirm_days : int
        确认间隔天数（默认 1，即次日确认）。
    """

    def __init__(
        self,
        first_ratio: float = 0.10,
        second_ratio: float = 0.15,
        confirm_days: int = 1,
    ):
        if not (0 < first_ratio <= 1):
            raise ValueError(
                f"first_ratio 应在 (0, 1] 区间，收到 {first_ratio}"
            )
        if not (0 < second_ratio <= 1):
            raise ValueError(
                f"second_ratio 应在 (0, 1] 区间，收到 {second_ratio}"
            )
        if confirm_days < 0:
            raise ValueError(
                f"confirm_days 应 >= 0，收到 {confirm_days}"
            )

        self._first_ratio = first_ratio
        self._second_ratio = second_ratio
        self._confirm_days = confirm_days

        # 运行时状态
        self._first_open_day: int = -1    # 首次开仓的 bar 索引
        self._confirmed: bool = False     # 是否已确认加仓

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "first_ratio": self._first_ratio,
            "second_ratio": self._second_ratio,
            "confirm_days": self._confirm_days,
            "mode": "batch_reversal",
        }

    # ── 状态管理 ──────────────────────────────────────────

    def reset(self) -> None:
        """回测开始前或平仓后复位状态。"""
        self._first_open_day = -1
        self._confirmed = False

    def on_first_open(self, bar_index: int) -> None:
        """记录首次开仓的 bar 索引。"""
        self._first_open_day = bar_index
        self._confirmed = False

    def on_confirm(self) -> None:
        """标记确认加仓完成。"""
        self._confirmed = True

    def on_close_all(self) -> None:
        """平仓后复位。"""
        self.reset()

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    @property
    def has_first_open(self) -> bool:
        return self._first_open_day >= 0

    # ── 确认条件判断 ──────────────────────────────────────

    def should_confirm(self, bar_index: int, signal_active: bool) -> bool:
        """
        判断当前是否满足确认加仓条件。

        条件：
          1. 已开首仓（_first_open_day >= 0）
          2. 未确认（未加过仓）
          3. 距离首仓 >= confirm_days 天
          4. 信号仍有效（价格未恶化）

        参数
        ----------
        bar_index : int
            当前 Bar 索引。
        signal_active : bool
            当前信号是否仍为 BUY（反转持续）。

        返回
        -------
        bool
            True = 触发确认加仓。
        """
        if self._first_open_day < 0 or self._confirmed:
            return False

        if not signal_active:
            return False

        days_since = bar_index - self._first_open_day
        return days_since >= self._confirm_days

    # ── 仓位计算 ──────────────────────────────────────────

    def calc_first_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """
        计算首次开仓数量（基于 first_ratio）。

        参数
        ----------
        capital : float
            当前可用资金。
        price : float
            开仓价格。
        min_shares : int
            最小交易单位（默认 100）。

        返回
        -------
        int
            首开股数。
        """
        target_amount = capital * self._first_ratio
        raw_shares = int(target_amount / price)
        return max(0, (raw_shares // min_shares) * min_shares)

    def calc_confirm_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """
        计算确认加仓数量（基于 second_ratio）。

        参数
        ----------
        capital : float
            当前可用资金。
        price : float
            加仓价格。
        min_shares : int
            最小交易单位（默认 100）。

        返回
        -------
        int
            加仓股数。
        """
        target_amount = capital * self._second_ratio
        raw_shares = int(target_amount / price)
        return max(0, (raw_shares // min_shares) * min_shares)

    def calc_close_quantity(self, position: Position) -> int:
        """平仓时全部卖出。"""
        return position.quantity


# ============================================================
# P3-12: 反转止损设置
# ============================================================


@dataclass
class ReversalExitSignal:
    """
    反转平仓信号。

    Attributes
    ----------
    should_exit : bool
        是否应平仓。
    reason : str
        平仓原因描述。
    """
    should_exit: bool = False
    reason: str = ""


class ReversalStopLoss:
    """
    反转止损设置（P3-12）。

    反转策略止损风控模块，支持两种策略（可独立或组合使用）：
      1. ATR 止损 — 入场价 - ATR × 倍数（默认 2 倍）
      2. 固定止损 — 价格跌幅超过固定百分比（默认 -5%）

    参数
    ----------
    atr_multiple : float, optional
        ATR 止损倍数。如 2.0 = 价格跌破「入场价 - 2 × ATR」时止损。
        启用条件：不为 None 且 > 0。
    fixed_stop_pct : float, optional
        固定止损比例（0~1）。如 0.05 = 跌幅超过 5% 止损。
        启用条件：不为 None 且 > 0。
    atr_period : int
        ATR 计算周期（默认 14）。
    """

    def __init__(
        self,
        atr_multiple: Optional[float] = 2.0,
        fixed_stop_pct: Optional[float] = 0.05,
        atr_period: int = 14,
    ):
        # ── 参数校验 ──────────────────────────────────
        if atr_multiple is not None and atr_multiple <= 0:
            raise ValueError(
                f"atr_multiple 应 > 0，收到 {atr_multiple}"
            )
        if fixed_stop_pct is not None and not (0 < fixed_stop_pct < 1):
            raise ValueError(
                f"fixed_stop_pct 应在 (0, 1) 区间，收到 {fixed_stop_pct}"
            )
        if atr_period < 2:
            raise ValueError(f"atr_period 应 >= 2，收到 {atr_period}")

        # 至少启用一种止损
        if atr_multiple is None and fixed_stop_pct is None:
            raise ValueError(
                "至少需要启用一种止损方式（atr_multiple 或 fixed_stop_pct）"
            )

        self.atr_multiple = atr_multiple
        self.fixed_stop_pct = fixed_stop_pct
        self.atr_period = atr_period

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "atr_multiple": self.atr_multiple,
            "fixed_stop_pct": self.fixed_stop_pct,
            "atr_period": self.atr_period,
            "mode": "reversal_stop_loss",
        }

    # ── ATR 计算 ──────────────────────────────────────────

    @staticmethod
    def _calc_atr(bars: List[Bar], period: int) -> List[Optional[float]]:
        """
        计算 ATR（平均真实波幅，Wilder 平滑法）。

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

    # ── 止损价格计算 ──────────────────────────────────────

    def calc_stop_price(
        self, entry_price: float, bars: List[Bar], bar_index: int
    ) -> Optional[float]:
        """
        计算当前止损价格。

        返回两种止损方式中较激进（价格较高）的那个，
        确保在任一种止损条件触发时都会离场：

          - ATR 止损价 = entry_price - ATR × atr_multiple
          - 固定止损价 = entry_price × (1 - fixed_stop_pct)

        参数
        ----------
        entry_price : float
            入场价格（持仓均价）。
        bars : List[Bar]
            完整的 Bar 序列（用于 ATR 计算）。
        bar_index : int
            当前 Bar 索引。

        返回
        -------
        Optional[float]
            止损价格；若无法计算返回 None（不设止损）。
        """
        stop_prices: List[float] = []

        # 1. ATR 止损价
        if self.atr_multiple is not None and self.atr_multiple > 0:
            atr = self._calc_atr(bars[: bar_index + 1], self.atr_period)
            if bar_index < len(atr) and atr[bar_index] is not None:
                atr_val = atr[bar_index]
                stop_prices.append(entry_price - atr_val * self.atr_multiple)

        # 2. 固定止损价
        if self.fixed_stop_pct is not None and self.fixed_stop_pct > 0:
            stop_prices.append(entry_price * (1.0 - self.fixed_stop_pct))

        if not stop_prices:
            return None

        # 取两个止损价中较高的（更宽松/更激进）
        # 这样任何一个止损条件触发都会被告警
        return max(stop_prices)

    # ── 核心检查逻辑 ──────────────────────────────────────

    def check_exit(
        self,
        position: Position,
        bar: Bar,
        bars: List[Bar],
        bar_index: int,
    ) -> ReversalExitSignal:
        """
        检查是否触发反转止损平仓条件。

        优先使用 ATR 止损，其次固定止损。

        参数
        ----------
        position : Position
            当前持仓对象（需有 avg_cost 和 quantity）。
        bar : Bar
            当前 Bar。
        bars : List[Bar]
            完整的 Bar 序列（用于 ATR 计算）。
        bar_index : int
            当前 Bar 的索引。

        返回
        -------
        ReversalExitSignal
            should_exit=True 表示应平仓，reason 说明原因。
        """
        if position.is_empty:
            return ReversalExitSignal()

        avg_cost = position.avg_cost
        if avg_cost <= 0:
            return ReversalExitSignal()

        # 计算止损价
        stop_price = self.calc_stop_price(avg_cost, bars, bar_index)
        if stop_price is None:
            return ReversalExitSignal()

        # 当前价格跌破止损价 → 触发止损
        if bar.close <= stop_price:
            # 判断触发原因（供日志参考）
            reasons = []
            if self.atr_multiple is not None:
                atr = self._calc_atr(bars[: bar_index + 1], self.atr_period)
                if bar_index < len(atr) and atr[bar_index] is not None:
                    atr_val = atr[bar_index]
                    atr_stop = avg_cost - atr_val * self.atr_multiple
                    if bar.close <= atr_stop:
                        reasons.append(
                            f"ATR止损: 价 {bar.close:.2f} <= "
                            f"入场 {avg_cost:.2f} - {self.atr_multiple}×ATR "
                            f"({atr_stop:.2f})"
                        )

            if self.fixed_stop_pct is not None:
                fixed_stop = avg_cost * (1.0 - self.fixed_stop_pct)
                pnl_pct = (bar.close - avg_cost) / avg_cost
                if bar.close <= fixed_stop:
                    reasons.append(
                        f"固定止损: 跌幅 {abs(pnl_pct):.2%} >= "
                        f"{self.fixed_stop_pct:.2%}"
                    )

            reason = "; ".join(reasons) if reasons else "反转止损触发"
            return ReversalExitSignal(should_exit=True, reason=reason)

        return ReversalExitSignal()


# ============================================================
# 组合仓位管理器
# ============================================================


class ReversalPositionManager:
    """
    反转组合仓位管理器。

    将反转仓位计算（FixedReversalPosition / OversoldDepthPosition /
    BatchReversalPosition）与反转风控（ReversalStopLoss）组合使用。

    用法::

        pos = FixedReversalPosition(position_ratio=0.20)
        sl = ReversalStopLoss(atr_multiple=2.0, fixed_stop_pct=0.05)
        mgr = ReversalPositionManager(position_logic=pos, risk_control=sl)

        qty = mgr.calc_open_quantity(capital=1_000_000, price=50.0)

        exit_signal = mgr.check_exit(position, bar, bars, idx)
        if exit_signal.should_exit:
            # 平仓
            ...
    """

    def __init__(
        self,
        position_logic: Any,  # FixedReversalPosition | OversoldDepthPosition | BatchReversalPosition
        risk_control: Optional[ReversalStopLoss] = None,
    ):
        self.position_logic = position_logic
        self.risk_control = risk_control

    # ── 序列化 ────────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        p = {
            "position_logic": self.position_logic.params,
        }
        if self.risk_control is not None:
            p["risk_control"] = self.risk_control.params
        return p

    # ── 仓位计算转发 ──────────────────────────────────────

    def calc_open_quantity(
        self,
        capital: float,
        price: float,
        rsi_value: Optional[float] = None,
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
        rsi_value : float, optional
            RSI 值（OversoldDepthPosition 需要）。
        min_shares : int
            最小交易单位（默认 100）。
        """
        if isinstance(self.position_logic, FixedReversalPosition):
            return self.position_logic.calc_open_quantity(
                capital, price, min_shares
            )
        elif isinstance(self.position_logic, OversoldDepthPosition):
            rsi = rsi_value if rsi_value is not None else 30.0
            return self.position_logic.calc_open_quantity(
                capital, price, rsi, min_shares
            )
        elif isinstance(self.position_logic, BatchReversalPosition):
            return self.position_logic.calc_first_quantity(
                capital, price, min_shares
            )
        else:
            raise TypeError(
                f"不支持的 position_logic 类型: {type(self.position_logic)}"
            )

    def calc_close_quantity(self, position: Position) -> int:
        """计算平仓数量。"""
        if hasattr(self.position_logic, "calc_close_quantity"):
            return self.position_logic.calc_close_quantity(position)
        return position.quantity

    def calc_first_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """BatchReversalPosition 首日开仓（委托给内部对象）。"""
        if isinstance(self.position_logic, BatchReversalPosition):
            return self.position_logic.calc_first_quantity(
                capital, price, min_shares
            )
        # 非分批模式退化为普通开仓
        return self.calc_open_quantity(capital, price, min_shares=min_shares)

    def calc_confirm_quantity(
        self, capital: float, price: float, min_shares: int = 100
    ) -> int:
        """BatchReversalPosition 确认加仓。"""
        if isinstance(self.position_logic, BatchReversalPosition):
            return self.position_logic.calc_confirm_quantity(
                capital, price, min_shares
            )
        return 0

    def should_confirm(self, bar_index: int, signal_active: bool) -> bool:
        """BatchReversalPosition 确认条件判断。"""
        if isinstance(self.position_logic, BatchReversalPosition):
            return self.position_logic.should_confirm(bar_index, signal_active)
        return False

    # ── 风控检查 ──────────────────────────────────────────

    def check_exit(
        self,
        position: Position,
        bar: Bar,
        bars: List[Bar],
        bar_index: int,
    ) -> ReversalExitSignal:
        """
        检查反转止损条件。

        如果未配置 risk_control，返回默认 ReversalExitSignal(should_exit=False)。
        """
        if self.risk_control is not None:
            return self.risk_control.check_exit(position, bar, bars, bar_index)
        return ReversalExitSignal()

    def calc_stop_price(
        self, entry_price: float, bars: List[Bar], bar_index: int
    ) -> Optional[float]:
        """获取当前止损价格（委托给 risk_control）。"""
        if self.risk_control is not None:
            return self.risk_control.calc_stop_price(entry_price, bars, bar_index)
        return None

    # ── 状态转发 ──────────────────────────────────────────

    def reset(self) -> None:
        """复位状态（BatchReversalPosition 需要）。"""
        if hasattr(self.position_logic, "reset"):
            self.position_logic.reset()

    def on_first_open(self, bar_index: int) -> None:
        """记录首仓开仓（BatchReversalPosition 需要）。"""
        if isinstance(self.position_logic, BatchReversalPosition):
            self.position_logic.on_first_open(bar_index)

    def on_confirm(self) -> None:
        """标记确认加仓（BatchReversalPosition 需要）。"""
        if isinstance(self.position_logic, BatchReversalPosition):
            self.position_logic.on_confirm()

    def on_close_all(self) -> None:
        """平仓后复位状态。"""
        if hasattr(self.position_logic, "on_close_all"):
            self.position_logic.on_close_all()


# ═══════════════════════════════════════════════════════════════
# 便捷函数：根据模式名快速创建反转仓位管理器
# ═══════════════════════════════════════════════════════════════

_REVERSAL_POSITION_MODES = {
    "fixed": FixedReversalPosition,
    "oversold_depth": OversoldDepthPosition,
    "batch": BatchReversalPosition,
}


def create_reversal_position_manager(
    mode: str = "fixed",
    position_ratio: float = 0.20,
    risk_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> ReversalPositionManager:
    """
    工厂函数：根据模式名快速创建 ReversalPositionManager。

    参数
    ----------
    mode : str
        仓位模式。可选 "fixed" / "oversold_depth" / "batch"。
    position_ratio : float
        固定仓位比例（mode="fixed" 时生效，默认 0.20）。
    risk_config : dict, optional
        风控配置，传给 ReversalStopLoss。
        如 {"atr_multiple": 2.0, "fixed_stop_pct": 0.05}。
    **kwargs
        仓位对象的其他专有参数：
          - oversold_depth 模式支持：rsi_max_threshold, oversold_25_ratio,
            rsi_25_threshold, oversold_15_ratio, rsi_15_threshold
          - batch 模式支持：first_ratio, second_ratio, confirm_days

    返回
    -------
    ReversalPositionManager

    用法::

        # 保守固定 20% + ATR×2 止损
        mgr = create_reversal_position_manager(
            mode="fixed",
            position_ratio=0.20,
            risk_config={"atr_multiple": 2.0},
        )

        # 超卖深度仓位 + 固定止损 5%
        mgr = create_reversal_position_manager(
            mode="oversold_depth",
            risk_config={"fixed_stop_pct": 0.05},
        )

        # 分批建仓（首日 10% + 次日确认 15%）+ ATR×2 + 固定止损 5%
        mgr = create_reversal_position_manager(
            mode="batch",
            first_ratio=0.10,
            second_ratio=0.15,
            confirm_days=1,
            risk_config={"atr_multiple": 2.0, "fixed_stop_pct": 0.05},
        )
    """
    cls = _REVERSAL_POSITION_MODES.get(mode)
    if cls is None:
        raise ValueError(
            f"未知反转仓位模式: {mode}，可选: {list(_REVERSAL_POSITION_MODES.keys())}"
        )

    # 构建仓位对象
    if cls is FixedReversalPosition:
        pos_logic = cls(position_ratio=position_ratio)
    else:
        pos_logic = cls(**kwargs)

    # 构建风控
    risk_control: Optional[ReversalStopLoss] = None
    if risk_config:
        risk_control = ReversalStopLoss(**risk_config)

    return ReversalPositionManager(
        position_logic=pos_logic, risk_control=risk_control
    )
