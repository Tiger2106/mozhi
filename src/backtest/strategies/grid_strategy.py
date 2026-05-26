"""
墨枢 - P4-01~P4-05 网格策略核心模块

P4-01 GridStrategy 基类
    - 网格生成支持等距/等比/波动率加权
    - 价格穿透检测（每条网格线每Bar最多触发一次）
    - 网格重建/自适应

P4-02 StaticGridSignal
    - 固定网格线位置，用户指定 lower/upper/n_levels
    - 3种网格间距类型：arithmetic_gap / geometric_gap / volatility_grid

P4-03 DynamicGridSignal
    - 网格中心 = MA(close, lookback)，宽度 = ATR × width_multiplier
    - 支持每根Bar重算或每N根Bar重算

P4-04 GridBreakoutSignal / GridReversalSignal
    - 网格最外线突破 → 趋势信号
    - 网格最外线反弹 → 反转信号

P4-05 GridVotingSignal
    - 多网格策略投票，信号强度 = 投票比例

用法::

    from backtest.strategies.grid_strategy import (
        StaticGridSignal, DynamicGridSignal,
        GridBreakoutSignal, GridReversalSignal, GridVotingSignal,
        GridConfig,
    )

Author: 墨衡
Created: 2026-05-15
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union, Callable

from backtest.backtest_engine import Bar
from backtest.signal_bridge import SignalStrategy, SignalBridgeConfig
from src.signals.signal_protocol_v1 import Signal as ProtocolSignal

# 时区
_TZ_CN = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════
# 类型与常量
# ═══════════════════════════════════════════════════════════════

class GridLevelType(Enum):
    """网格线类型"""
    BUY_AT = "buy_at"       # 价格触及此线 → 买入
    SELL_AT = "sell_at"     # 价格触及此线 → 卖出
    TAKE_PROFIT = "take_profit"  # 止盈线


class GridGapType(Enum):
    """网格间距类型"""
    ARITHMETIC = "arithmetic"   # 等距（价格差固定）
    GEOMETRIC = "geometric"     # 等比（百分比固定）
    VOLATILITY = "volatility"   # 波动率加权


class SignalType(Enum):
    """网格信号触发类型"""
    CROSS = "cross"         # 价格穿透网格线
    REVERSE = "reverse"     # 价格反弹/回落触发
    BREAKOUT = "breakout"   # 突破最外线
    BOUNCE = "bounce"       # 从最外线反弹


DEFAULT_DEFAULT_QUANTITY = 100
DEFAULT_ORDER_TYPE = "MARKET"  # 字符串常量（已剥离交易依赖）


# ═══════════════════════════════════════════════════════════════
# 网格数据模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class GridLevel:
    """单个网格线"""
    price: float
    level_type: GridLevelType
    triggered: bool = False  # 当前Bar周期是否已触发，每Bar重置

    def reset_trigger(self) -> None:
        """重置触发标记（新Bar开始时调用）"""
        self.triggered = False

    def __repr__(self) -> str:
        return f"GridLevel(price={self.price:.4f}, type={self.level_type.value}, triggered={self.triggered})"


@dataclass
class GridConfig:
    """
    网格策略配置参数

    Parameters
    ----------
    lower_bound : float
        网格下界（价格）。Static 模式下固定；Dynamic 选参。
    upper_bound : float
        网格上界（价格）。
    n_levels : int
        网格线数量（含上下界）。
    grid_type : str
        网格间距类型: "arithmetic" | "geometric" | "volatility"
    cool_down_bars : int
        网格重建冷却期（多少根Bar后允许再次重建），避免频繁重建。
    reverse_order : bool
        是否启用反向挂单（价格反弹/回落触发而非穿透触发）。
    default_quantity : int
        每笔默认下单数量。
    """
    lower_bound: float = 0.0
    upper_bound: float = 0.0
    n_levels: int = 10
    grid_type: str = "arithmetic"
    cool_down_bars: int = 5
    reverse_order: bool = False
    default_quantity: int = DEFAULT_DEFAULT_QUANTITY

    def validate(self) -> None:
        """校验参数有效性"""
        if self.lower_bound <= 0:
            raise ValueError(f"lower_bound 必须为正数，收到 {self.lower_bound}")
        if self.upper_bound <= self.lower_bound:
            raise ValueError(
                f"upper_bound ({self.upper_bound}) 必须大于 lower_bound ({self.lower_bound})"
            )
        if self.n_levels < 2:
            raise ValueError(f"n_levels 至少为2，收到 {self.n_levels}")
        if self.grid_type not in ("arithmetic", "geometric", "volatility"):
            raise ValueError(
                f"grid_type 必须为 arithmetic/geometric/volatility，收到 {self.grid_type}"
            )
        if self.cool_down_bars < 0:
            raise ValueError(f"cool_down_bars 不能为负，收到 {self.cool_down_bars}")


@dataclass
class GridSignal:
    """
    网格信号（独立数据类，不再继承自任何 Signal 基类）。

    字段:
      action: "BUY" / "SELL" / "HOLD"
      strength: 信号强度 [0.0, 1.0]
      trigger_price: 触发时的价格
      level_price: 对应的网格线价格
      level_type: 网格线类型: buy_at/sell_at/take_profit
      signal_type: 信号触发类型: cross/reverse/breakout/bounce
    """
    action: str = "HOLD"
    strength: float = 0.0
    trigger_price: float = 0.0      # 触发时的价格
    level_price: float = 0.0        # 对应的网格线价格
    level_type: str = ""            # 网格线类型: buy_at/sell_at/take_profit
    signal_type: str = ""           # 信号触发类型: cross/reverse/breakout/bounce

    def to_protocol(self, bar: Bar, quantity: int) -> ProtocolSignal:
        """将网格信号转换为 Signal Protocol v1 格式。"""
        return ProtocolSignal(
            signal_id=str(uuid.uuid4()),
            symbol=bar.symbol,
            direction=self.action,
            confidence=min(1.0, self.strength),
            horizon="short",
            signal_type="grid",
            timestamp=datetime.now(_TZ_CN),
            protocol_version="1.0",
            extras={
                "quantity": quantity,
                "trigger_price": self.trigger_price,
                "level_price": self.level_price,
                "level_type": self.level_type,
                "grid_signal_type": self.signal_type,
            },
        )


# ═══════════════════════════════════════════════════════════════
# 内部工具函数
# ═══════════════════════════════════════════════════════════════


def _sma(values: List[float], period: int) -> List[Optional[float]]:
    """
    简单移动平均。

    前 period-1 个元素为 None，period 开始有值。
    """
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result

    window_sum = sum(values[:period])
    result[period - 1] = window_sum / period

    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        result[i] = window_sum / period

    return result


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    """
    指数移动平均。

    公式:
      alpha = 2 / (period + 1)
      EMA(0) = SMA(period)
      EMA(t) = alpha * price(t) + (1 - alpha) * EMA(t-1)
    """
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result

    alpha = 2.0 / (period + 1)
    ema_val = sum(values[:period]) / period
    result[period - 1] = ema_val

    for i in range(period, len(values)):
        ema_val = alpha * values[i] + (1 - alpha) * ema_val
        result[i] = ema_val

    return result


def _true_range(bar: Bar, prev_close: float) -> float:
    """
    计算单根 K 线的真实波幅 TR。

    TR = max(high - low, |high - prev_close|, |low - prev_close|)
    """
    hl = bar.high - bar.low
    hc = abs(bar.high - prev_close)
    lc = abs(bar.low - prev_close)
    return max(hl, hc, lc)


def _atr(bars: List[Bar], period: int = 14) -> List[Optional[float]]:
    """
    计算 ATR（平均真实波幅）。

    返回与 bars 等长的数组，前 period 个元素为 None。
    ATR(0) = SMA(TR, period)，后续为 EMA(TR)。
    """
    n = len(bars)
    if n < period + 1:
        return [None] * n

    tr_values: List[float] = []
    for i in range(1, n):
        tr = _true_range(bars[i], bars[i - 1].close)
        tr_values.append(tr)

    m = len(tr_values)
    atr: List[Optional[float]] = [None] * n

    # 前 period 个 TR 的均值作为初始 ATR
    if m < period:
        return atr

    initial_atr = sum(tr_values[:period]) / period
    atr[period] = initial_atr  # ATR[period] 对应 bars[period] 的前置

    alpha = 2.0 / (period + 1)
    for i in range(period, m):
        atr_val = alpha * tr_values[i] + (1 - alpha) * (atr[i] if atr[i] is not None else initial_atr)
        atr[i + 1] = atr_val

    return atr


def _closes(bars: List[Bar]) -> List[float]:
    """从 Bar 列表提取收盘价列表"""
    return [b.close for b in bars]


def _prices_from_bars(bars: List[Bar], lookback: int) -> List[float]:
    """
    提取最近的 Bar 并返回收盘价。
    """
    return _closes(bars[-lookback:]) if len(bars) >= lookback else _closes(bars)


# ═══════════════════════════════════════════════════════════════
# P4-01: GridStrategy 基类
# ═══════════════════════════════════════════════════════════════


class GridStrategy(SignalStrategy):
    """
    网格策略基类（P4-01）。

    核心能力:
      1. 网格生成：generate_levels() → 等距/等比/波动率加权
      2. 网格信号：on_bar() 检测价格穿透 → List[Signal]
      3. 网格重建：rebuild_grid() 根据最新行情调整范围 + 冷却期

    网格生成时自动分配网格线类型：
      - 中间线以上 → sell_at（卖压区）
      - 中间线以下 → buy_at（买压区）
      - 最上/最下线同时作为 take_profit（止盈）

    子类只需提供 _compute_grid_params() 返回 (lower, upper, n_levels, grid_type)。
    默认实现使用 GridConfig 的固定参数。
    """

    def __init__(
        self,
        grid_config: Optional[GridConfig] = None,
        bridge_config: Optional[SignalBridgeConfig] = None,
    ):
        super().__init__(bridge_config=bridge_config)
        self.grid_config = grid_config or GridConfig()
        self.grid_config.validate()

        # ── 内部状态 ──────────────────────────────────────
        self._grid_levels: List[GridLevel] = []
        self._last_rebuild_bar_idx: int = -1  # 上次重建时的 Bar 索引
        self._bar_count: int = 0  # 累计 Bar 计数
        self._bars_history: List[Bar] = []  # 历史 Bar（用于 ATR 等计算）
        self._center_price: float = 0.0
        self._volatility: float = 0.0
        self._prev_close: Optional[float] = None  # 用于反弹/回落检测
        self._prev_grid_zone: int = 0  # 用于突破/反弹检测
        # 1 = 在最上线之上, -1 = 在最下线之下, 0 = 在网格范围内

        # ── 初始构建网格 ──────────────────────────────────
        if self.grid_config.lower_bound > 0 and self.grid_config.upper_bound > 0:
            self._grid_levels = self.generate_levels(
                self.grid_config.lower_bound,
                self.grid_config.upper_bound,
                self.grid_config.n_levels,
                self.grid_config.grid_type,
            )

    # ═══════════════════════════════════════════════════════════
    # 参数接口
    # ═══════════════════════════════════════════════════════════

    @property
    def params(self) -> Dict[str, Any]:
        """返回可序列化的参数配置"""
        return {
            "lower_bound": self.grid_config.lower_bound,
            "upper_bound": self.grid_config.upper_bound,
            "n_levels": self.grid_config.n_levels,
            "grid_type": self.grid_config.grid_type,
            "cool_down_bars": self.grid_config.cool_down_bars,
            "reverse_order": self.grid_config.reverse_order,
            "default_quantity": self.grid_config.default_quantity,
        }

    def set_params(self, **kwargs) -> None:
        """
        批量更新参数（会触发网格重建）。
        """
        valid_keys = {
            "lower_bound", "upper_bound", "n_levels", "grid_type",
            "cool_down_bars", "reverse_order", "default_quantity",
        }
        for key, value in kwargs.items():
            if key not in valid_keys:
                raise KeyError(f"未知参数: {key}")
            setattr(self.grid_config, key, value)

        self.grid_config.validate()

        # 重建网格
        self._grid_levels = self.generate_levels(
            self.grid_config.lower_bound,
            self.grid_config.upper_bound,
            self.grid_config.n_levels,
            self.grid_config.grid_type,
        )

    # ═══════════════════════════════════════════════════════════
    # 网格生成核心
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def generate_levels(
        lower: float, upper: float, n_levels: int, grid_type: str = "arithmetic"
    ) -> List[GridLevel]:
        """
        生成网格线列表。

        参数
        ----------
        lower : float
            网格下界价格。
        upper : float
            网格上界价格。
        n_levels : int
            网格线数量（含上下界）。
        grid_type : str
            "arithmetic" = 等距（价格差固定）
            "geometric"  = 等比（百分比固定）
            "volatility" = 波动率加权（需要外部传入 volatility）

        返回
        -------
        List[GridLevel]
            按价格升序排列的网格线列表。
            中间线以上 → sell_at，以下 → buy_at，最外线附加 take_profit。
        """
        if lower >= upper:
            raise ValueError(f"lower ({lower}) 必须小于 upper ({upper})")
        if n_levels < 2:
            raise ValueError(f"n_levels 至少为2，收到 {n_levels}")

        levels: List[float] = []

        if grid_type == "arithmetic":
            gap = (upper - lower) / (n_levels - 1)
            for i in range(n_levels):
                levels.append(lower + i * gap)

        elif grid_type == "geometric":
            ratio = (upper / lower) ** (1.0 / (n_levels - 1))
            for i in range(n_levels):
                levels.append(lower * (ratio ** i))

        else:
            # volatility: 等间距退化到 arithmetic
            gap = (upper - lower) / (n_levels - 1)
            for i in range(n_levels):
                levels.append(lower + i * gap)

        # ── 分配网格线类型 ──────────────────────────────
        mid_idx = n_levels // 2
        grid_levels: List[GridLevel] = []

        for i, price in enumerate(levels):
            if i == 0 or i == n_levels - 1:
                # 最外线：卖/买 + 止盈
                lt = GridLevelType.SELL_AT if i == n_levels - 1 else GridLevelType.BUY_AT
                grid_levels.append(
                    GridLevel(price=price, level_type=lt, triggered=False)
                )
            elif i >= mid_idx:
                # 中间线以上 → 卖压区
                grid_levels.append(
                    GridLevel(price=price, level_type=GridLevelType.SELL_AT, triggered=False)
                )
            else:
                # 中间线以下 → 买压区
                grid_levels.append(
                    GridLevel(price=price, level_type=GridLevelType.BUY_AT, triggered=False)
                )

        return grid_levels

    def _compute_grid_params(self) -> Tuple[float, float, int, str]:
        """
        子类覆写此方法以提供动态参数。
        返回 (lower, upper, n_levels, grid_type)。
        基类使用 GridConfig 的固定参数。
        """
        return (
            self.grid_config.lower_bound,
            self.grid_config.upper_bound,
            self.grid_config.n_levels,
            self.grid_config.grid_type,
        )

    # ═══════════════════════════════════════════════════════════
    # 网格重建
    # ═══════════════════════════════════════════════════════════

    def rebuild_grid(
        self,
        center_price: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> None:
        """
        根据最新行情重建网格范围。

        使用最新计算的 center_price 和 volatility 扩展网格：
          - lower = center_price - volatility * n_levels / 2
          - upper = center_price + volatility * n_levels / 2
          - 网格线数量保持不变

        参数
        ----------
        center_price : float, optional
            网格中心价（如使用则覆盖内部值）。
        volatility : float, optional
            波动率（ATR 值）（如使用则覆盖内部值）。
        """
        if center_price is not None:
            self._center_price = center_price
        if volatility is not None:
            self._volatility = volatility

        if self._center_price <= 0 or self._volatility <= 0:
            return  # 参数未就绪，不重建

        n = self.grid_config.n_levels
        half_width = self._volatility * n / 2.0
        lower = self._center_price - half_width
        upper = self._center_price + half_width

        # 确保下界为正数
        if lower <= 0:
            lower = self._center_price * 0.5
            upper = self._center_price * 1.5

        # 更新配置
        self.grid_config.lower_bound = lower
        self.grid_config.upper_bound = upper

        # 重建网格
        self._grid_levels = self.generate_levels(
            lower, upper, n, self.grid_config.grid_type
        )

    def _can_rebuild(self, current_bar_idx: int) -> bool:
        """
        检查是否满足冷却期条件，可以重建网格。

        冷却期内不重建，避免行情正常波动导致频繁调整。
        """
        if self._last_rebuild_bar_idx < 0:
            return True
        return (current_bar_idx - self._last_rebuild_bar_idx) >= self.grid_config.cool_down_bars

    # ═══════════════════════════════════════════════════════════
    # 网格级别访问
    # ═══════════════════════════════════════════════════════════

    @property
    def grid_levels(self) -> List[GridLevel]:
        return self._grid_levels

    @property
    def lowest_level(self) -> Optional[GridLevel]:
        return self._grid_levels[0] if self._grid_levels else None

    @property
    def highest_level(self) -> Optional[GridLevel]:
        return self._grid_levels[-1] if self._grid_levels else None

    @property
    def center_price(self) -> float:
        return self._center_price

    @property
    def volatility(self) -> float:
        return self._volatility

    # ═══════════════════════════════════════════════════════════
    # 价格穿透检测
    # ═══════════════════════════════════════════════════════════

    def _detect_cross_signals(self, bar: Bar, prev_close: Optional[float] = None) -> List[GridSignal]:
        """
        检测价格穿透网格线。

        规则：
          - 价格从下往上穿过 buy_at 线 → BUY
          - 价格从上往下穿过 sell_at 线 → SELL
          - 每条网格线每 Bar 最多触发一次

        Parameters:
            bar: 当前 K 线
            prev_close: 前一 Bar 收盘价。传入 None 时使用 self._prev_close
        """
        signals: List[GridSignal] = []

        if not self._grid_levels:
            return signals

        p_close = self._prev_close if prev_close is None else prev_close

        for level in self._grid_levels:
            if level.triggered:
                continue  # 已触发，不重复

            # 检测穿透
            # 使用 bar 的 low 和 high 判断是否穿透：
            # 如果 prev_close < level.price ≤ high → 向上穿透买线
            # 如果 prev_close > level.price ≥ low  → 向下穿透卖线

            if p_close is None:
                continue

            crossed = False
            action = "HOLD"

            if level.level_type == GridLevelType.BUY_AT:
                # 价格从下往上穿过 buy_at 线
                if prev_close < level.price <= bar.high:
                    crossed = True
                    action = "BUY"
            elif level.level_type == GridLevelType.SELL_AT:
                # 价格从上往下穿过 sell_at 线
                if prev_close > level.price >= bar.low:
                    crossed = True
                    action = "SELL"

            if crossed:
                level.triggered = True
                signals.append(GridSignal(
                    action=action,
                    strength=min(1.0, abs(bar.close - level.price) / (self._volatility or 0.01)),  # 穿透幅度归一化
                    trigger_price=bar.close,
                    level_price=level.price,
                    level_type=level.level_type.value,
                    signal_type=SignalType.CROSS.value,
                ))

        return signals

    def _detect_reverse_signals(self, bar: Bar, prev_close: Optional[float] = None) -> List[GridSignal]:
        """
        检测价格反弹/回落触发。

        反向挂单模式：价格从远侧接近网格线但未穿过，然后反弹时触发。
          - 价格从上方回落到 buy_at 线附近 → BUY（反弹买入）
          - 价格从下方回升到 sell_at 线附近 → SELL（回落卖出）

        Parameters:
            bar: 当前 K 线
            prev_close: 前一 Bar 收盘价。传入 None 时使用 self._prev_close
        """
        signals: List[GridSignal] = []

        if not self._grid_levels:
            return signals

        p_close = self._prev_close if prev_close is None else prev_close
        if p_close is None:
            return signals

        for level in self._grid_levels:
            if level.triggered:
                continue

            # 反向触发逻辑：
            # 价格从网格线"外侧"回到线附近（bar 的高/低触及线但收盘在线的另一侧）
            action = "HOLD"

            if level.level_type == GridLevelType.BUY_AT:
                # 价格从下方打到买线 → 反弹时触发买入
                if bar.low <= level.price <= bar.high:
                    # 价格触及买线但收盘在线之上（反弹已经发生）
                    if bar.close > level.price:
                        level.triggered = True
                        action = "BUY"
            elif level.level_type == GridLevelType.SELL_AT:
                # 价格从上方打到卖线 → 回落时触发卖出
                if bar.low <= level.price <= bar.high:
                    # 价格触及卖线但收盘在线之下（回落已经发生）
                    if bar.close < level.price:
                        level.triggered = True
                        action = "SELL"

            if action != "HOLD":
                signals.append(GridSignal(
                    action=action,
                    strength=min(1.0, abs(level.price - bar.close) / (self._volatility or 0.01)),
                    trigger_price=bar.close,
                    level_price=level.price,
                    level_type=level.level_type.value,
                    signal_type=SignalType.REVERSE.value,
                ))

        return signals

    # ═══════════════════════════════════════════════════════════
    # on_bar — 主信号入口
    # ═══════════════════════════════════════════════════════════

    def on_bar(
        self, context: Any, bar: Bar
    ) -> Optional[List[ProtocolSignal]]:
        """
        每根 Bar 的信号检测回调。

        流程：
          1. 重置所有网格线的触发标记
          2. 记录 prev_close
          3. 检测价格穿透（cross）或反弹/回落（reverse）
          4. GridSignal → ProtocolSignal 转换
          5. 更新网格（由子类 _post_bar_update 触发）

        参数
        ----------
        context : BacktestContext
            回测上下文
        bar : Bar
            当前 K 线

        返回
        -------
        Optional[List[ProtocolSignal]]
            统一信号列表
        """
        self._bar_count += 1
        self._bars_history.append(bar)

        # ── 1. 重置触发标记 ──────────────────────────────
        for level in self._grid_levels:
            level.reset_trigger()

        # ── 2. 重置前收盘价──────────────────────────────
        prev_close = self._prev_close
        self._prev_close = bar.close

        # 首次运行，没有 prev_close，无法检测穿透
        if prev_close is None:
            return None

        # ── 3. 检测信号 ──────────────────────────────────
        grid_signals: List[GridSignal] = []

        if self.grid_config.reverse_order:
            grid_signals.extend(self._detect_reverse_signals(bar, prev_close=prev_close))
        else:
            grid_signals.extend(self._detect_cross_signals(bar, prev_close=prev_close))

        # ── 4. 子类回调（网格内更新） ────────────────────
        self._on_post_bar(bar)

        # ── 5. GridSignal → ProtocolSignal ───────────────
        if not grid_signals:
            return self._post_bar_orders() or None

        signals: List[ProtocolSignal] = []
        for gs in grid_signals:
            quantity = self.grid_config.default_quantity
            # 按资金比例限制（简化计算，保持逻辑不变）
            if context and context.available_capital > 0:
                max_cost = context.available_capital * 0.15
                max_qty = int(max_cost / (bar.close * 1.001))
                quantity = min(quantity, max_qty)
                quantity = max(quantity, 100)
                quantity = (quantity // 100) * 100
            if quantity > 0:
                signals.append(gs.to_protocol(bar, quantity))

        # ── 6. 子类后处理 ────────────────────────────────
        extra_signals = self._post_bar_orders()
        if extra_signals:
            signals.extend(extra_signals)

        return signals if signals else None

    # ═══════════════════════════════════════════════════════════
    # 子类钩子
    # ═══════════════════════════════════════════════════════════

    def _on_post_bar(self, bar: Bar) -> None:
        """
        每 Bar 信号检测后的子类回调。
        子类可在此触发网格更新或额外计算。
        """
        pass

    def _post_bar_orders(self) -> Optional[List[ProtocolSignal]]:
        """
        信号检测后子类可返回额外策略信号（如突破信号）。
        """
        return None


# ═══════════════════════════════════════════════════════════════
# P4-02: 静态网格信号
# ═══════════════════════════════════════════════════════════════


class StaticGridSignal(GridStrategy):
    """
    静态网格信号（P4-02）。

    固定网格线位置，用户指定 lower/upper/n_levels 即可。
    支持3种网格间距类型。

    不同 grid_type 的行为：
      - arithmetic_gap (arithmetic): 间距 = (upper - lower) / (n_levels - 1)
        即价格差固定的等距网格，适合价格波动均匀的品种。
      - geometric_gap (geometric): 比例 = (upper/lower)^(1/(n-1))
        即百分比固定的等比网格，低位密度高位稀疏。
      - volatility_grid (volatility): 需要额外传入 ATR multiplier。
        须在子类或外部设置 self._volatility 后调用 rebuild_grid()。

    用法::

        strategy = StaticGridSignal(
            grid_config=GridConfig(
                lower_bound=95.0,
                upper_bound=105.0,
                n_levels=10,
                grid_type="arithmetic",
                cool_down_bars=5,
            )
        )
        result = engine.run(bars, strategy)
    """

    def __init__(
        self,
        grid_config: Optional[GridConfig] = None,
        bridge_config: Optional[SignalBridgeConfig] = None,
    ):
        super().__init__(grid_config=grid_config, bridge_config=bridge_config)

    def to_dict(self) -> Dict[str, Any]:
        """序列化配置"""
        return {
            "strategy_type": "static_grid",
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StaticGridSignal":
        """从序列化数据重建实例"""
        params = data.get("params", {})
        config = GridConfig(
            lower_bound=params.get("lower_bound", 95.0),
            upper_bound=params.get("upper_bound", 105.0),
            n_levels=params.get("n_levels", 10),
            grid_type=params.get("grid_type", "arithmetic"),
            cool_down_bars=params.get("cool_down_bars", 5),
            reverse_order=params.get("reverse_order", False),
            default_quantity=params.get("default_quantity", 100),
        )
        return cls(grid_config=config)


# ═══════════════════════════════════════════════════════════════
# P4-03: 动态网格信号
# ═══════════════════════════════════════════════════════════════


class DynamicGridSignal(GridStrategy):
    """
    动态网格信号（P4-03）。

    网格随行情自适应：
      - 网格中心价 = SMA(close, lookback)
      - 网格宽度   = ATR(lookback) × width_multiplier × n_levels
      - 网格每根 Bar 或每 N 根 Bar 重算一次

    参数
    ----------
    lookback : int
        SMA / ATR 计算周期（默认 20）。
    width_multiplier : float
        网格宽度乘数（默认 1.0）。越大网格越宽。
    n_levels : int
        网格线数量（默认 10）。
    recalc_freq : str or int
        "each_bar" = 每根 Bar 重算
        "every_n"  = 每 N 根 Bar 重算一次，N 由 recalc_interval 决定
    recalc_interval : int
        当 recalc_freq="every_n" 时，每 N 根 Bar 重算（默认 5）。
    grid_type : str
        网格间距类型（默认 "arithmetic"）。
    cool_down_bars : int
        冷却期（默认 3，动态策略应短一些）。
    reverse_order : bool
        反向挂单（默认 False）。

    用法::

        strategy = DynamicGridSignal(
            lookback=20,
            width_multiplier=2.0,
            n_levels=8,
            recalc_freq="each_bar",
        )
    """

    def __init__(
        self,
        lookback: int = 20,
        width_multiplier: float = 1.0,
        n_levels: int = 10,
        recalc_freq: str = "each_bar",
        recalc_interval: int = 5,
        grid_type: str = "arithmetic",
        cool_down_bars: int = 3,
        reverse_order: bool = False,
        default_quantity: int = DEFAULT_DEFAULT_QUANTITY,
        bridge_config: Optional[SignalBridgeConfig] = None,
    ):
        self._lookback = lookback
        self._width_multiplier = width_multiplier
        self._recalc_freq = recalc_freq
        self._recalc_interval = recalc_interval
        self._bar_since_recalc = 0

        config = GridConfig(
            lower_bound=90.0,  # 占位值，首次 _on_post_bar 会覆盖
            upper_bound=110.0,
            n_levels=n_levels,
            grid_type=grid_type,
            cool_down_bars=cool_down_bars,
            reverse_order=reverse_order,
            default_quantity=default_quantity,
        )
        super().__init__(grid_config=config, bridge_config=bridge_config)

    # ═══════════════════════════════════════════════════════════
    # 动态参数
    # ═══════════════════════════════════════════════════════════

    @property
    def params(self) -> Dict[str, Any]:
        base = super().params
        base.update({
            "lookback": self._lookback,
            "width_multiplier": self._width_multiplier,
            "recalc_freq": self._recalc_freq,
            "recalc_interval": self._recalc_interval,
        })
        return base

    # ═══════════════════════════════════════════════════════════
    # 核心：每 Bar 后更新
    # ═══════════════════════════════════════════════════════════

    def _on_post_bar(self, bar: Bar) -> None:
        """
        每 Bar 后检查是否需要重算网格。
        """
        if not self._bars_history or len(self._bars_history) < self._lookback + 1:
            return

        # ── 判断是否满足重算条件 ──────────────────────────
        should_recalc = False

        if self._recalc_freq == "each_bar":
            should_recalc = True
        elif self._recalc_freq == "every_n":
            self._bar_since_recalc += 1
            if self._bar_since_recalc >= self._recalc_interval:
                should_recalc = True
                self._bar_since_recalc = 0

        if not should_recalc:
            return

        # ── 冷却期检查 ────────────────────────────────────
        if not self._can_rebuild(self._bar_count):
            return

        # ── 计算中心价和波动率 ───────────────────────────
        closes = _closes(self._bars_history)

        # 中心价 = SMA(lookback)
        sma_values = _sma(closes, self._lookback)
        latest_sma = None
        for v in reversed(sma_values):
            if v is not None:
                latest_sma = v
                break

        if latest_sma is None or latest_sma <= 0:
            return

        # ATR
        atr_values = _atr(self._bars_history, self._lookback)
        latest_atr = None
        for v in reversed(atr_values):
            if v is not None and v > 0:
                latest_atr = v
                break

        if latest_atr is None or latest_atr <= 0:
            return

        # ── 重建网格 ──────────────────────────────────────
        self._center_price = latest_sma
        self._volatility = latest_atr * self._width_multiplier
        self.rebuild_grid()
        self._last_rebuild_bar_idx = self._bar_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_type": "dynamic_grid",
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DynamicGridSignal":
        p = data.get("params", {})
        return cls(
            lookback=p.get("lookback", 20),
            width_multiplier=p.get("width_multiplier", 1.0),
            n_levels=p.get("n_levels", 10),
            recalc_freq=p.get("recalc_freq", "each_bar"),
            recalc_interval=p.get("recalc_interval", 5),
            grid_type=p.get("grid_type", "arithmetic"),
            cool_down_bars=p.get("cool_down_bars", 3),
            reverse_order=p.get("reverse_order", False),
            default_quantity=p.get("default_quantity", 100),
        )


# ═══════════════════════════════════════════════════════════════
# P4-04: 网格突破/回归信号
# ═══════════════════════════════════════════════════════════════


class GridBreakoutSignal(GridStrategy):
    """
    网格突破信号（P4-04）。

    当价格突破网格最上/最下线时，发出趋势跟随信号：
      - 价格向上突破最上线 → BUY（追涨趋势）
      - 价格向下突破最下线 → SELL（追跌趋势）

    突破需要 confirmation_bars 根 Bar 的确认：
      - 连续 confirmation_bars 根 Bar 收盘价均在网格线外
      - 降低假突破误报

    参数
    ----------
    confirmation_bars : int
        突破确认所需的连续 Bar 数（默认 1）。
    parent_grid : GridStrategy, optional
        外置网格策略实例。如提供，则共享该策略的网格配置和状态；
        否则独立生成自己的网格。

    用法::

        grid = StaticGridSignal(
            grid_config=GridConfig(lower_bound=95, upper_bound=105, n_levels=10)
        )
        breakout = GridBreakoutSignal(
            grid_config=GridConfig(lower_bound=95, upper_bound=105, n_levels=10),
            confirmation_bars=2,
        )
        # 在回测引擎中分别运行或组合
    """

    def __init__(
        self,
        grid_config: Optional[GridConfig] = None,
        confirmation_bars: int = 1,
        parent_grid: Optional[GridStrategy] = None,
        bridge_config: Optional[SignalBridgeConfig] = None,
    ):
        super().__init__(grid_config=grid_config, bridge_config=bridge_config)
        self.confirmation_bars = max(1, confirmation_bars)
        self._parent_grid = parent_grid

        # 突破确认计数器
        self._breakout_up_count: int = 0   # 连续在上线外的 Bar 数
        self._breakout_down_count: int = 0  # 连续在下线外的 Bar 数
        self._breakout_up_triggered: bool = False
        self._breakout_down_triggered: bool = False

    @property
    def params(self) -> Dict[str, Any]:
        base = super().params
        base["confirmation_bars"] = self.confirmation_bars
        return base

    def _on_post_bar(self, bar: Bar) -> None:
        """
        每 Bar 检查突破状态。
        """
        # ── 如果有父网格，使用父网格的 levels ────────────
        levels = self._parent_grid.grid_levels if self._parent_grid else self._grid_levels
        if not levels:
            return

        lowest = levels[0]
        highest = levels[-1]
        close = bar.close

        # ── 检测向上突破 ──────────────────────────────
        if close > highest.price:
            self._breakout_up_count += 1
            self._breakout_down_count = 0

            if (
                self._breakout_up_count >= self.confirmation_bars
                and not self._breakout_up_triggered
            ):
                self._breakout_up_triggered = True
                self._breakout_up_count = 0  # 重置，等待下次
        else:
            self._breakout_up_count = 0

        # ── 检测向下突破 ──────────────────────────────
        if close < lowest.price:
            self._breakout_down_count += 1
            self._breakout_up_count = 0

            if (
                self._breakout_down_count >= self.confirmation_bars
                and not self._breakout_down_triggered
            ):
                self._breakout_down_triggered = True
                self._breakout_down_count = 0
        else:
            self._breakout_down_count = 0

        # ── 回到网格内部则重置突破标记 ────────────────
        if lowest.price <= close <= highest.price:
            self._breakout_up_triggered = False
            self._breakout_down_triggered = False

    def _post_bar_orders(self) -> Optional[List[ProtocolSignal]]:
        """
        返回突破确认后的额外策略信号。
        """
        signals: List[ProtocolSignal] = []

        def _mk(direction: str, qty: int) -> ProtocolSignal:
            return ProtocolSignal(
                signal_id=str(uuid.uuid4()),
                symbol=bar.symbol if self._bars_history else "",
                direction=direction,
                confidence=1.0,
                horizon="short",
                signal_type="grid",
                timestamp=datetime.now(_TZ_CN),
                protocol_version="1.0",
                extras={"quantity": qty},
            )

        # 向上突破 → BUY
        if self._breakout_up_triggered and self._bars_history:
            bar = self._bars_history[-1]
            qty = self.grid_config.default_quantity
            if bar.close > 0 and qty > 0:
                qty = (qty // 100) * 100
                if qty > 0:
                    signals.append(_mk("BUY", qty))

        # 向下突破 → SELL
        if self._breakout_down_triggered and self._bars_history:
            bar = self._bars_history[-1]
            qty = self.grid_config.default_quantity
            if bar.close > 0 and qty > 0:
                qty = (qty // 100) * 100
                if qty > 0:
                    signals.append(_mk("SELL", qty))

        return signals if signals else None


class GridReversalSignal(GridStrategy):
    """
    网格回归（反转）信号（P4-04）。

    当价格从网格最外线反弹时，发出反转信号：
      - 价格触及最上线后回落至网格内部 → SELL（反转做空）
      - 价格触及最下线后回升至网格内部 → BUY（反转做多）

    回归需要确认：
      - 价格先穿透最外线（突破），然后在一个 Bar 内回到网格内
      - 或连续 confirmation_bars 根 Bar 均在网格内

    参数
    ----------
    confirmation_bars : int
        回归确认所需连续 Bar 数（默认 1）。
    parent_grid : GridStrategy, optional
        外置网格策略实例。

    用法::

        reversal = GridReversalSignal(
            grid_config=GridConfig(lower_bound=95, upper_bound=105, n_levels=10),
            confirmation_bars=1,
        )
    """

    def __init__(
        self,
        grid_config: Optional[GridConfig] = None,
        confirmation_bars: int = 1,
        parent_grid: Optional[GridStrategy] = None,
        bridge_config: Optional[SignalBridgeConfig] = None,
    ):
        super().__init__(grid_config=grid_config, bridge_config=bridge_config)
        self.confirmation_bars = max(1, confirmation_bars)
        self._parent_grid = parent_grid

        # 突破状态跟踪
        self._price_above_upper: bool = False  # 价格在最高线之上
        self._price_below_lower: bool = False  # 价格在最低线之下
        self._reversal_up_triggered: bool = False
        self._reversal_down_triggered: bool = False
        self._reversal_up_count: int = 0
        self._reversal_down_count: int = 0

    @property
    def params(self) -> Dict[str, Any]:
        base = super().params
        base["confirmation_bars"] = self.confirmation_bars
        return base

    def _on_post_bar(self, bar: Bar) -> None:
        """
        每 Bar 检查反转状态。
        """
        levels = self._parent_grid.grid_levels if self._parent_grid else self._grid_levels
        if not levels:
            return

        lowest = levels[0]
        highest = levels[-1]
        close = bar.close

        # ── 更新突破状态 ──────────────────────────────
        was_above = self._price_above_upper
        was_below = self._price_below_lower

        self._price_above_upper = close > highest.price
        self._price_below_lower = close < lowest.price

        # ── 检测向上反转（从上线回落到网格内） ──────────
        if was_above and not self._price_above_upper:
            # 价格从最上线之上回到网格内 → 可能反转
            if lowest.price <= close <= highest.price:
                self._reversal_down_count += 1  # 卖出信号计数
                if self._reversal_down_count >= self.confirmation_bars:
                    self._reversal_down_triggered = True
                    self._reversal_down_count = 0
        else:
            self._reversal_down_count = 0

        # ── 检测向下反转（从最下线回弹到网格内） ──────────
        if was_below and not self._price_below_lower:
            if lowest.price <= close <= highest.price:
                self._reversal_up_count += 1
                if self._reversal_up_count >= self.confirmation_bars:
                    self._reversal_up_triggered = True
                    self._reversal_up_count = 0
        else:
            self._reversal_up_count = 0

    def _post_bar_orders(self) -> Optional[List[ProtocolSignal]]:
        """
        返回反转确认后的策略信号。
        """
        signals: List[ProtocolSignal] = []

        if self._reversal_up_triggered and self._bars_history:
            bar = self._bars_history[-1]
            qty = (self.grid_config.default_quantity // 100) * 100
            if qty > 0:
                signals.append(
                    ProtocolSignal(
                        signal_id=str(uuid.uuid4()),
                        symbol=bar.symbol,
                        direction="BUY",
                        confidence=1.0,
                        horizon="short",
                        signal_type="grid",
                        timestamp=datetime.now(_TZ_CN),
                        protocol_version="1.0",
                        extras={"quantity": qty, "grid_subtype": "reversal"},
                    )
                )
            self._reversal_up_triggered = False  # 一次性触发

        if self._reversal_down_triggered and self._bars_history:
            bar = self._bars_history[-1]
            qty = (self.grid_config.default_quantity // 100) * 100
            if qty > 0:
                signals.append(
                    ProtocolSignal(
                        signal_id=str(uuid.uuid4()),
                        symbol=bar.symbol,
                        direction="SELL",
                        confidence=1.0,
                        horizon="short",
                        signal_type="grid",
                        timestamp=datetime.now(_TZ_CN),
                        protocol_version="1.0",
                        extras={"quantity": qty, "grid_subtype": "reversal"},
                    )
                )
            self._reversal_down_triggered = False

        return signals if signals else None


# ═══════════════════════════════════════════════════════════════
# P4-05: 多网格投票信号
# ═══════════════════════════════════════════════════════════════


class GridVotingSignal:
    """
    多网格投票信号（P4-05）。

    聚合多个子网格策略的买卖信号，按投票比例决定最终信号。
    可用于组合不同类型的网格策略（静态+动态+突破+回归），
    降低单一策略误报风险。

    信号强度计算:
        buy_ratio  = buy_votes / total_active_votes
        sell_ratio = sell_votes / total_active_votes
        net_strength = (buy_ratio - sell_ratio)  # [-1, 1]

    决策规则:
        - net_strength > vote_threshold  → BUY  (strength = net_strength)
        - net_strength < -vote_threshold → SELL (strength = |net_strength|)
        - 其他                         → HOLD

    参数
    ----------
    sub_grids : List[GridStrategy]
        子网格策略列表（至少包含 3 个不同类型）。
    vote_threshold : float
        投票阈值 (0.0 ~ 1.0)，net_strength 绝对值超过此阈值才发信号（默认 0.5）。
    weights : List[float], optional
        各子网格的投票权重（长度需与 sub_grids 一致）。
        权重越大，该子网格的投票影响力越大。默认等权。

    用法::

        grid1 = StaticGridSignal(...)
        grid2 = DynamicGridSignal(...)
        grid3 = GridBreakoutSignal(...)

        voter = GridVotingSignal(
            sub_grids=[grid1, grid2, grid3],
            vote_threshold=0.5,
            weights=[1.0, 2.0, 0.8],  # 动态网格权重更高
        )

        # 所有子网格共享同一个市场, 在 on_bar 中顺序执行
        for bar in bars:
            signals = voter.on_bar(context, bar)
    """

    def __init__(
        self,
        sub_grids: List[GridStrategy],
        vote_threshold: float = 0.5,
        weights: Optional[List[float]] = None,
    ):
        if len(sub_grids) < 1:
            raise ValueError("sub_grids 至少需要 1 个子网格策略")
        if len(sub_grids) >= 3:
            # 建议至少 3 个不同类型
            pass

        self._sub_grids = sub_grids
        self._vote_threshold = max(0.0, min(1.0, vote_threshold))

        # 权重标准化
        if weights is not None:
            if len(weights) != len(sub_grids):
                raise ValueError(
                    f"weights 长度 ({len(weights)}) 须与 sub_grids ({len(sub_grids)}) 一致"
                )
            # 归一化到总和 = N（保持与等权类比的可比性）
            w_sum = sum(weights)
            if w_sum > 0:
                n = len(sub_grids)
                self._weights = [w * n / w_sum for w in weights]
            else:
                self._weights = [1.0] * n
        else:
            self._weights = [1.0] * len(sub_grids)

        # ── 内部状态 ──────────────────────────────────────
        self._latest_vote_detail: Dict[str, Any] = {}
        self._bar_count: int = 0

    @property
    def params(self) -> Dict[str, Any]:
        """返回投票信号参数"""
        return {
            "n_sub_grids": len(self._sub_grids),
            "vote_threshold": self._vote_threshold,
            "weights": self._weights,
            "sub_grid_types": [
                g.__class__.__name__ for g in self._sub_grids
            ],
        }

    @property
    def latest_vote_detail(self) -> Dict[str, Any]:
        """
        返回最近一次投票的详细信息（用于分析）。
        """
        return self._latest_vote_detail

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    def on_bar(
        self, context: Any, bar: Bar
    ) -> Optional[List[ProtocolSignal]]:
        """
        聚合所有子网格的 on_bar 结果并投票。

        每根 Bar：
          1. 顺序调用每个子网格的 on_bar(context, bar)
          2. 收集各子网格的输出信号（ProtocolSignal）
          3. 计算投票比例
          4. 判断是否超过阈值
          5. 如超过，发送聚合后的统一信号

        参数
        ----------
        context : BacktestContext
            回测上下文
        bar : Bar
            当前 K 线

        返回
        -------
        Optional[List[ProtocolSignal]]
        """
        self._bar_count += 1

        # ── 1. 收集各子网格信号 ──────────────────────────
        buy_votes: float = 0.0
        sell_votes: float = 0.0
        total_active: float = 0.0
        sub_results: List[Dict[str, Any]] = []

        for grid, weight in zip(self._sub_grids, self._weights):
            signals = grid.on_bar(context, bar)

            has_buy = False
            has_sell = False
            if signals:
                for sig in signals:
                    if sig.direction == "BUY":
                        has_buy = True
                    elif sig.direction == "SELL":
                        has_sell = True

            vote: int = 0  # -1/sell, 0/hold, 1/buy
            if has_buy and not has_sell:
                vote = 1
                buy_votes += weight
                total_active += weight
            elif has_sell and not has_buy:
                vote = -1
                sell_votes += weight
                total_active += weight

            sub_results.append({
                "grid_type": grid.__class__.__name__,
                "weight": weight,
                "vote": vote,
                "signals": signals,
            })

        # ── 2. 计算投票比例 ──────────────────────────────
        buy_ratio = buy_votes / total_active if total_active > 0 else 0.0
        sell_ratio = sell_votes / total_active if total_active > 0 else 0.0
        net_strength = buy_ratio - sell_ratio

        self._latest_vote_detail = {
            "bar_index": self._bar_count,
            "date": bar.date,
            "symbol": bar.symbol,
            "buy_votes": round(buy_votes, 2),
            "sell_votes": round(sell_votes, 2),
            "total_active": round(total_active, 2),
            "buy_ratio": round(buy_ratio, 4),
            "sell_ratio": round(sell_ratio, 4),
            "net_strength": round(net_strength, 4),
            "threshold": self._vote_threshold,
            "sub_results": sub_results,
        }

        # ── 3. 判断是否超过阈值 ──────────────────────────
        if abs(net_strength) <= self._vote_threshold:
            return None

        # ── 4. 发单 ──────────────────────────────────────
        quantity = self._default_quantity(bar, context)
        signals: List[ProtocolSignal] = []

        if net_strength > 0:
            # BUY
            signals.append(
                ProtocolSignal(
                    signal_id=str(uuid.uuid4()),
                    symbol=bar.symbol,
                    direction="BUY",
                    confidence=abs(net_strength),
                    horizon="short",
                    signal_type="grid",
                    timestamp=datetime.now(_TZ_CN),
                    protocol_version="1.0",
                    extras={"quantity": quantity},
                )
            )
        else:
            # SELL
            if context and context.positions.has_position(bar.symbol):
                pos = context.positions.get(bar.symbol)
                sell_qty = min(quantity, pos.quantity)
                if sell_qty > 0:
                    signals.append(
                        ProtocolSignal(
                            signal_id=str(uuid.uuid4()),
                            symbol=bar.symbol,
                            direction="SELL",
                            confidence=abs(net_strength),
                            horizon="short",
                            signal_type="grid",
                            timestamp=datetime.now(_TZ_CN),
                            protocol_version="1.0",
                            extras={"quantity": sell_qty},
                        )
                    )

        return signals if signals else None

    def _default_quantity(self, bar: Bar, context: Any) -> int:
        """
        根据资金量计算默认下单数量。
        """
        qty = 100
        if context and context.available_capital > 0 and bar.close > 0:
            max_cost = context.available_capital * 0.15
            max_qty = int(max_cost / (bar.close * 1.001))
            qty = min(qty, max_qty)
        qty = (qty // 100) * 100
        return max(qty, 100)

    def to_dict(self) -> Dict[str, Any]:
        """序列化配置"""
        return {
            "strategy_type": "grid_voting",
            "params": self.params,
        }

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any],
        sub_grids: List[GridStrategy],
    ) -> "GridVotingSignal":
        """
        从序列化数据重建。
        需要外部传入已构建好的子网格策略实例。
        """
        p = data.get("params", {})
        return cls(
            sub_grids=sub_grids,
            vote_threshold=p.get("vote_threshold", 0.5),
            weights=p.get("weights", None),
        )


# ═══════════════════════════════════════════════════════════════
# 便捷入口函数
# ═══════════════════════════════════════════════════════════════


def create_grid_strategy(
    strategy_type: str = "static",
    lower_bound: float = 95.0,
    upper_bound: float = 105.0,
    n_levels: int = 10,
    grid_type: str = "arithmetic",
    **kwargs,
) -> GridStrategy:
    """
    便捷工厂函数，一键创建网格策略实例。

    参数
    ----------
    strategy_type : str
        "static" | "dynamic" | "breakout" | "reversal"
    lower_bound, upper_bound : float
        网格上下界（仅 static/breakout/reversal 使用）。
    n_levels : int
        网格线数量。
    grid_type : str
        "arithmetic" | "geometric" | "volatility"
    **kwargs :
        传给特定策略类的额外参数。

    返回
    -------
    GridStrategy
    """
    config = GridConfig(
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        n_levels=n_levels,
        grid_type=grid_type,
    )

    if strategy_type == "static":
        return StaticGridSignal(grid_config=config, **kwargs)
    elif strategy_type == "dynamic":
        return DynamicGridSignal(
            n_levels=n_levels,
            grid_type=grid_type,
            **kwargs,
        )
    elif strategy_type == "breakout":
        return GridBreakoutSignal(grid_config=config, **kwargs)
    elif strategy_type == "reversal":
        return GridReversalSignal(grid_config=config, **kwargs)
    else:
        raise ValueError(f"未知策略类型: {strategy_type}，可选: static/dynamic/breakout/reversal")


__all__ = [
    "GridLevelType",
    "GridGapType",
    "SignalType",
    "GridLevel",
    "GridConfig",
    "GridSignal",
    "GridStrategy",
    "StaticGridSignal",
    "DynamicGridSignal",
    "GridBreakoutSignal",
    "GridReversalSignal",
    "GridVotingSignal",
    "create_grid_strategy",
]
