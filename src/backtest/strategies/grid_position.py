"""
墨枢 - P4-07 / P4-08 / P4-09 网格仓位管理 + 风控模块

网格策略专用的仓位计算、层数阶梯、分批建仓与风控逻辑。

模块组成:
  P4-07  GridFixedPosition   — 固定每笔交易数量（类似 Phase2 FixedPosition）
  P4-07  GridLayerPosition   — 基于网格层数的阶梯仓位（层数越多仓位越大）
  P4-07  GridBatcherPosition — 分批建仓（网格越低越便宜，买入越多）
  P4-08  GridCoolDown        — 网格冷却期（触发后等待 N 根 Bar）
  P4-08  GridStopLoss        — 网格止损（固定止损 + 移动止损）
  P4-08  GridMaxExposure     — 网格总仓位上限（百分比 + 活跃网格数）
  P4-09  create_grid_position / create_grid_risk   — 工厂函数

用法::

    from backtest.strategies.grid_position import GridFixedPosition

    pos = GridFixedPosition(quantity=200)
    buy_qty = pos.on_buy_signal(context, bar)       # → 200
    sell_qty = pos.on_sell_signal(context, bar)     # → min(200, position.quantity)

    # 配合风控使用
    cd = GridCoolDown(cool_down_bars=3)
    if cd.is_cooled_down("level_1", current_bar):
        cd.on_trigger("level_1", current_bar)
        # 执行交易

Author: 墨衡
Created: 2026-05-15
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, Union

from backtest.backtest_engine import Bar
from backtest.position_manager import Position


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

DEFAULT_QUANTITY = 100           # A 股最小交易单位
LOT_SIZE = 100                    # 取整基数


# ═══════════════════════════════════════════════════════════════
# 类型辅助
# ═══════════════════════════════════════════════════════════════

GridTier = Dict[str, float]       # {"level_from": float, "level_to": float, "ratio": float}
PositionType = Union[
    "GridFixedPosition",
    "GridLayerPosition",
    "GridBatcherPosition",
]
RiskType = Union[
    "GridCoolDown",
    "GridStopLoss",
    "GridMaxExposure",
]


# ═══════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════


def _clamp_to_lot(quantity: int, lot_size: int = LOT_SIZE) -> int:
    """
    将数量向下取整到最小交易单位的整数倍。

    参数
    ----------
    quantity : int
        原始数量。
    lot_size : int
        最小交易单位（默认 100）。

    返回
    -------
    int
        取整后的数量（≥ 0）。
    """
    if quantity <= 0:
        return 0
    return (quantity // lot_size) * lot_size


# ═══════════════════════════════════════════════════════════════
# P4-07: GridFixedPosition — 网格固定仓位
# ═══════════════════════════════════════════════════════════════


class GridFixedPosition:
    """
    网格固定仓位（P4-07）。

    每笔交易使用固定股数，不随资金或行情变化。
    平仓时取「固定股数」与「当前持仓」的较小值。

    参数
    ----------
    quantity : int
        每笔交易固定股数，默认为 100（A 股最小单位）。
        须为 100 的倍数。
    """

    def __init__(self, quantity: int = DEFAULT_QUANTITY):
        if quantity < LOT_SIZE:
            raise ValueError(
                f"quantity ({quantity}) 不能小于最小交易单位 ({LOT_SIZE})"
            )
        if quantity % LOT_SIZE != 0:
            raise ValueError(
                f"quantity ({quantity}) 须为 {LOT_SIZE} 的倍数"
            )
        self._quantity = quantity

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "quantity": self._quantity,
            "mode": "grid_fixed",
        }

    @property
    def quantity(self) -> int:
        return self._quantity

    # ── 仓位计算 ──────────────────────────────────────────

    def on_buy_signal(self, context: Any, bar: Bar) -> int:
        """
        买入信号回调：返回固定股数。

        若 context 提供资金约束，自动限额：
          最大买入金额 = available_capital * 15%（单标的风控上限）

        参数
        ----------
        context : BacktestContext
            回测上下文（需有 available_capital 属性）。
        bar : Bar
            当前 K 线。

        返回
        -------
        int
            买入股数（向下取整到 100 的倍数）。
        """
        qty = self._quantity

        # 资金约束
        if context is not None and hasattr(context, "available_capital"):
            capital = getattr(context, "available_capital", 0)
            if capital is not None and capital > 0 and bar.close > 0:
                max_cost = capital * 0.15  # 单标的上限 15%
                max_qty = int(max_cost / (bar.close * 1.001))
                qty = min(qty, max_qty)

        return _clamp_to_lot(qty)

    def on_sell_signal(self, context: Any, bar: Bar) -> int:
        """
        卖出信号回调：返回 min(固定股数, 当前持仓数量)。

        参数
        ----------
        context : BacktestContext
            回测上下文（需有 positions 属性）。
        bar : Bar
            当前 K 线。

        返回
        -------
        int
            卖出股数（向下取整到 100 的倍数）。
        """
        position_qty = 0
        if context is not None and hasattr(context, "positions"):
            positions = getattr(context, "positions", None)
            if positions is not None and hasattr(positions, "get"):
                pos = positions.get(bar.symbol)
                if pos is not None:
                    position_qty = getattr(pos, "quantity", 0)

        qty = min(self._quantity, position_qty or 0)
        return _clamp_to_lot(qty)

    # ── 辅助方法 ──────────────────────────────────────────

    @staticmethod
    def clamp(quantity: int) -> int:
        """
        将数量舍入到 100 的倍数（向下取整）。

        参数
        ----------
        quantity : int
            原始数量。

        返回
        -------
        int
            舍入后的数量。
        """
        return _clamp_to_lot(quantity)

    def validate(self) -> bool:
        """
        校验参数是否合法。

        返回
        -------
        bool
            quantity >= 100 且为 100 的倍数。
        """
        return (
            self._quantity >= LOT_SIZE
            and self._quantity % LOT_SIZE == 0
        )


# ═══════════════════════════════════════════════════════════════
# P4-07: GridLayerPosition — 网格层数阶梯仓位
# ═══════════════════════════════════════════════════════════════


class GridLayerPosition:
    """
    网格层数阶梯仓位（P4-07）。

    基于当前已触发的网格层数，阶梯式增加买入数量。
    每多触发一层，仓位乘以 layer_multiplier，但不超过 multiplier_cap。

    公式：
      effective_multiplier = min(layer_multiplier ** layer_count, multiplier_cap)
      quantity = base_quantity * effective_multiplier

    参数
    ----------
    base_quantity : int
        基准数量（第一层触发时的买入量，默认 100）。
    layer_multiplier : float
        层数乘数（默认 2.0）。
        每多触发一层，base_quantity 乘以该系数。
    max_layers : int
        最大层数（默认 5）。
        超过此层数后不再增加仓位。
    multiplier_cap : float
        最大乘数上限（默认 10.0）。
        防御极端行情下仓位过度放大。
    """

    def __init__(
        self,
        base_quantity: int = DEFAULT_QUANTITY,
        layer_multiplier: float = 2.0,
        max_layers: int = 5,
        multiplier_cap: float = 10.0,
    ):
        if base_quantity < LOT_SIZE:
            raise ValueError(
                f"base_quantity ({base_quantity}) 不能小于最小交易单位 ({LOT_SIZE})"
            )
        if base_quantity % LOT_SIZE != 0:
            raise ValueError(
                f"base_quantity ({base_quantity}) 须为 {LOT_SIZE} 的倍数"
            )
        if layer_multiplier <= 0:
            raise ValueError(
                f"layer_multiplier 应 > 0，收到 {layer_multiplier}"
            )
        if max_layers < 1:
            raise ValueError(
                f"max_layers 应 >= 1，收到 {max_layers}"
            )
        if multiplier_cap < 1.0:
            raise ValueError(
                f"multiplier_cap 应 >= 1.0，收到 {multiplier_cap}"
            )

        self._base_quantity = base_quantity
        self._layer_multiplier = layer_multiplier
        self._max_layers = max_layers
        self._multiplier_cap = multiplier_cap

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "base_quantity": self._base_quantity,
            "layer_multiplier": self._layer_multiplier,
            "max_layers": self._max_layers,
            "multiplier_cap": self._multiplier_cap,
            "mode": "grid_layer",
        }

    @property
    def base_quantity(self) -> int:
        return self._base_quantity

    @property
    def layer_multiplier(self) -> float:
        return self._layer_multiplier

    @property
    def max_layers(self) -> int:
        return self._max_layers

    @property
    def multiplier_cap(self) -> float:
        return self._multiplier_cap

    # ── 层数计算 ──────────────────────────────────────────

    @staticmethod
    def get_layer_count(triggered_levels: List[str]) -> int:
        """
        计算当前已触发的网格层数。

        参数
        ----------
        triggered_levels : List[str]
            已触发的网格线 ID 列表（如 ["level_0", "level_1", ...]）。

        返回
        -------
        int
            已触发层数（0 表示无触发）。
        """
        if not triggered_levels:
            return 0
        return len(triggered_levels)

    # ── 仓位计算 ──────────────────────────────────────────

    def on_buy_signal(
        self,
        context: Any,
        bar: Bar,
        triggered_levels: Optional[List[str]] = None,
    ) -> int:
        """
        买入信号回调：根据当前已触发层数计算买入数量。

        公式：
          effective_mult = min(multiplier ** layer_count, cap)
          quantity = base_quantity * effective_mult

        参数
        ----------
        context : BacktestContext
            回测上下文（需有 available_capital 属性）。
        bar : Bar
            当前 K 线。
        triggered_levels : List[str], optional
            已触发的网格线 ID 列表。
            传入 None 时退化为 base_quantity。

        返回
        -------
        int
            买入股数（向下取整到 100 的倍数）。
        """
        layer_count = self.get_layer_count(triggered_levels)
        effective_layers = min(layer_count, self._max_layers)

        effective_mult = self._layer_multiplier ** effective_layers
        effective_mult = min(effective_mult, self._multiplier_cap)

        qty = int(self._base_quantity * effective_mult)

        # 资金约束
        if context is not None and hasattr(context, "available_capital"):
            capital = getattr(context, "available_capital", 0)
            if capital is not None and capital > 0 and bar.close > 0:
                max_cost = capital * 0.15
                max_qty = int(max_cost / (bar.close * 1.001))
                qty = min(qty, max_qty)

        return _clamp_to_lot(qty)

    def on_sell_signal(self, context: Any, bar: Bar) -> int:
        """
        卖出信号回调：全部卖出（网格层数不做缩仓限制）。

        参数
        ----------
        context : BacktestContext
            回测上下文（需有 positions 属性）。
        bar : Bar
            当前 K 线。

        返回
        -------
        int
            卖出股数（当前持仓数量）。
        """
        position_qty = 0
        if context is not None and hasattr(context, "positions"):
            positions = getattr(context, "positions", None)
            if positions is not None and hasattr(positions, "get"):
                pos = positions.get(bar.symbol)
                if pos is not None:
                    position_qty = getattr(pos, "quantity", 0)

        return _clamp_to_lot(position_qty or 0)

    # ── 辅助方法 ──────────────────────────────────────────

    def validate(self) -> bool:
        """
        校验参数是否合法。

        返回
        -------
        bool
            所有参数在有效范围内。
        """
        return (
            self._base_quantity >= LOT_SIZE
            and self._base_quantity % LOT_SIZE == 0
            and self._layer_multiplier > 0
            and self._max_layers >= 1
            and self._multiplier_cap >= 1.0
        )


# ═══════════════════════════════════════════════════════════════
# P4-07: GridBatcherPosition — 分批建仓
# ═══════════════════════════════════════════════════════════════


class GridBatcherPosition:
    """
    分批建仓（P4-07）。

    网格越低越便宜，买入越多的策略。
    根据价格在网格中的位置（百分比），选择对应的 tier 比例。

    tiers 定义：
      - level_from: 网格区间下界（0.0 ~ 1.0，网格最低到最高）
      - level_to:   网格区间上界（0.0 ~ 1.0）
      - ratio:      该区间对应的仓位比例（0.0 ~ 1.0）

    示例（默认）：
      - 价格在网格最低 0%~33% 区域 → 买入总额的 50%
      - 价格在网格 33%~66% 区域   → 买入总额的 30%
      - 价格在网格 66%~100% 区域  → 买入总额的 20%

    参数
    ----------
    total_grid_rows : int
        总网格行数（用于将价格映射到百分比位置，默认 10）。
    tiers : List[Dict[str, float]], optional
        分批层级定义。每个元素须含 level_from / level_to / ratio 字段。
        默认三档: [50% / 33%], [30% / 33%], [20% / 34%]。
        各 tier 的 level_from 必须覆盖 [0.0, 1.0] 且不重叠。
    """

    DEFAULT_TIERS: List[Dict[str, float]] = [
        {"level_from": 0.0, "level_to": 0.33, "ratio": 0.50},
        {"level_from": 0.33, "level_to": 0.66, "ratio": 0.30},
        {"level_from": 0.66, "level_to": 1.0, "ratio": 0.20},
    ]

    def __init__(
        self,
        total_grid_rows: int = 10,
        tiers: Optional[List[Dict[str, float]]] = None,
    ):
        if total_grid_rows < 2:
            raise ValueError(
                f"total_grid_rows 至少为 2，收到 {total_grid_rows}"
            )

        _tiers = list(tiers) if tiers else list(self.DEFAULT_TIERS)
        self._validate_tiers(_tiers)

        self._total_grid_rows = total_grid_rows
        self._tiers: List[GridTier] = [
            {
                "level_from": float(t.get("level_from", 0.0)),
                "level_to": float(t.get("level_to", 1.0)),
                "ratio": float(t.get("ratio", 0.0)),
            }
            for t in _tiers
        ]

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "total_grid_rows": self._total_grid_rows,
            "tiers": [
                {k: round(v, 4) for k, v in t.items()}
                for t in self._tiers
            ],
            "mode": "grid_batcher",
        }

    @property
    def total_grid_rows(self) -> int:
        return self._total_grid_rows

    @property
    def tiers(self) -> List[GridTier]:
        return list(self._tiers)

    # ── Tier 校验 ──────────────────────────────────────────

    @staticmethod
    def _validate_tiers(tiers: List[Dict[str, float]]) -> None:
        """
        校验 tiers 参数合法性。
        """
        if not tiers:
            raise ValueError("tiers 不能为空")

        # 检查字段完整性
        for i, t in enumerate(tiers):
            if "level_from" not in t or "level_to" not in t or "ratio" not in t:
                raise ValueError(
                    f"tier[{i}] 须包含 level_from/level_to/ratio 字段，"
                    f"收到 {list(t.keys())}"
                )
            lf = float(t["level_from"])
            lt = float(t["level_to"])
            ratio = float(t["ratio"])

            if not (0.0 <= lf < lt <= 1.0):
                raise ValueError(
                    f"tier[{i}]: 需要 0.0 <= level_from ({lf}) < "
                    f"level_to ({lt}) <= 1.0"
                )
            if not (0.0 < ratio <= 1.0):
                raise ValueError(
                    f"tier[{i}]: ratio ({ratio}) 应在 (0, 1] 区间"
                )

        # 检查区间是否不重叠且覆盖 [0, 1]
        sorted_tiers = sorted(tiers, key=lambda t: float(t["level_from"]))
        if abs(float(sorted_tiers[0]["level_from"]) - 0.0) > 1e-6:
            raise ValueError(
                f"第一个 tier 的 level_from 必须为 0.0，"
                f"收到 {sorted_tiers[0]['level_from']}"
            )
        if abs(float(sorted_tiers[-1]["level_to"]) - 1.0) > 1e-6:
            raise ValueError(
                f"最后一个 tier 的 level_to 必须为 1.0，"
                f"收到 {sorted_tiers[-1]['level_to']}"
            )

        for i in range(1, len(sorted_tiers)):
            prev_lt = float(sorted_tiers[i - 1]["level_to"])
            curr_lf = float(sorted_tiers[i]["level_from"])
            if abs(prev_lt - curr_lf) > 1e-6:
                raise ValueError(
                    f"tiers 区间不连续或重叠: "
                    f"tier[{i - 1}].level_to ({prev_lt}) != "
                    f"tier[{i}].level_from ({curr_lf})"
                )

    # ── 核心：价格位置 → Tier 选择 ───────────────────────

    def _price_to_tier_index(self, grid_position: float) -> int:
        """
        根据网格中的价格位置选择 tier 索引。

        参数
        ----------
        grid_position : float
            价格在网格中的位置 [0.0, 1.0]。
            0.0 = 网格最低价，1.0 = 网格最高价。

        返回
        -------
        int
            tier 索引（0-based）。
        """
        pos = max(0.0, min(1.0, grid_position))

        for i, tier in enumerate(self._tiers):
            lf = tier["level_from"]
            lt = tier["level_to"]
            if lf <= pos <= lt:
                return i

        # 边界情况：正好等于 1.0 或精度误差
        return len(self._tiers) - 1

    # ── 仓位计算 ──────────────────────────────────────────

    def on_buy_signal(
        self,
        context: Any,
        bar: Bar,
        grid_position: float = 0.0,
    ) -> int:
        """
        买入信号回调：根据价格在网格中的位置选择对应 tier。

        参数
        ----------
        context : BacktestContext
            回测上下文（需有 available_capital 属性）。
        bar : Bar
            当前 K 线。
        grid_position : float
            价格在网格中的归一化位置 [0.0, 1.0]。
            0.0 = 网格最低价，1.0 = 网格最高价。
            传入方式由调用方根据当前价格与网格边界计算。

        返回
        -------
        int
            买入股数（向下取整到 100 的倍数）。
        """
        tier_idx = self._price_to_tier_index(grid_position)
        tier = self._tiers[tier_idx]
        ratio = tier["ratio"]

        # 计算可用资金
        capital = 0
        if context is not None and hasattr(context, "available_capital"):
            capital = getattr(context, "available_capital", 0) or 0

        if capital <= 0 or bar.close <= 0:
            return 0

        target_amount = capital * ratio
        qty = int(target_amount / (bar.close * 1.001))

        # 单标的上限 15%
        max_qty = int(capital * 0.15 / (bar.close * 1.001))
        qty = min(qty, max_qty)

        return _clamp_to_lot(qty)

    def on_sell_signal(self, context: Any, bar: Bar) -> int:
        """
        卖出信号回调：全部卖出。

        参数
        ----------
        context : BacktestContext
            回测上下文（需有 positions 属性）。
        bar : Bar
            当前 K 线。

        返回
        -------
        int
            卖出股数（当前持仓数量）。
        """
        position_qty = 0
        if context is not None and hasattr(context, "positions"):
            positions = getattr(context, "positions", None)
            if positions is not None and hasattr(positions, "get"):
                pos = positions.get(bar.symbol)
                if pos is not None:
                    position_qty = getattr(pos, "quantity", 0)

        return _clamp_to_lot(position_qty or 0)


# ═══════════════════════════════════════════════════════════════
# P4-08: GridCoolDown — 网格冷却期
# ═══════════════════════════════════════════════════════════════


class GridCoolDown:
    """
    网格冷却期风控（P4-08）。

    每条网格线触发交易后，需要等待一定数量的 Bar 才能再次触发。
    冷却期按网格线独立记录，互不干扰。

    参数
    ----------
    cool_down_bars : int
        触发后需要冷却的 Bar 数量（默认 3）。
        冷却期内该网格线不再接受新的触发。
    """

    def __init__(self, cool_down_bars: int = 3):
        if cool_down_bars < 0:
            raise ValueError(
                f"cool_down_bars 不能为负，收到 {cool_down_bars}"
            )
        self._cool_down_bars = cool_down_bars
        # _last_trigger_bar[grid_line_id] = last_bar_index
        self._last_trigger_bar: Dict[str, int] = {}

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "cool_down_bars": self._cool_down_bars,
            "mode": "grid_cool_down",
        }

    @property
    def cool_down_bars(self) -> int:
        return self._cool_down_bars

    @property
    def last_trigger_bar(self) -> Dict[str, int]:
        """
        返回所有网格线最近一次触发的 Bar 索引快照（只读）。
        """
        return dict(self._last_trigger_bar)

    # ── 状态管理 ──────────────────────────────────────────

    def reset(self) -> None:
        """清除所有冷却状态（新回测开始时调用）。"""
        self._last_trigger_bar.clear()

    def on_trigger(self, grid_line_id: str, current_bar: int) -> None:
        """
        记录当前网格线的触发。

        调用者（GridStrategy）应在确认交易后调用此方法，
        将当前 Bar 索引记录为该网格线的最后触发时间。

        参数
        ----------
        grid_line_id : str
            网格线 ID（如 "level_0", "level_1" 等）。
        current_bar : int
            当前 Bar 索引（0-based）。
        """
        self._last_trigger_bar[grid_line_id] = current_bar

    def is_cooled_down(self, grid_line_id: str, current_bar: int) -> bool:
        """
        检查指定网格线是否已冷却完毕，可以再次触发。

        参数
        ----------
        grid_line_id : str
            网格线 ID。
        current_bar : int
            当前 Bar 索引（0-based）。

        返回
        -------
        bool
            True = 该网格线可以触发（已过冷却期或从未触发过）。
            False = 冷却期中，不可触发。
        """
        # 从未触发过 → 可以直接触发
        if grid_line_id not in self._last_trigger_bar:
            return True

        last_bar = self._last_trigger_bar[grid_line_id]
        # self._cool_down_bars == 0 表示无冷却
        if self._cool_down_bars <= 0:
            return True

        return (current_bar - last_bar) >= self._cool_down_bars


# ═══════════════════════════════════════════════════════════════
# P4-08: GridStopLoss — 网格止损
# ═══════════════════════════════════════════════════════════════


class GridStopLoss:
    """
    网格止损风控（P4-08）。

    支持两种止损方式（独立或组合使用）：
      1. 固定止损 — 价格跌幅超过指定百分比时触发
      2. 移动止损 — 价格从最高点回落超过指定百分比时触发（可选）

    参数
    ----------
    stop_loss_pct : float
        固定止损百分比（0~1）。如 0.05 = 跌幅超过 5% 止损。
    trailing_stop_pct : float, optional
        移动止损百分比（0~1）。如 0.03 = 从最高点回落超过 3% 止损。
        启用条件：不为 None 且 > 0。
    """

    def __init__(
        self,
        stop_loss_pct: float = 0.05,
        trailing_stop_pct: Optional[float] = None,
    ):
        if not (0 < stop_loss_pct < 1):
            raise ValueError(
                f"stop_loss_pct 应在 (0, 1) 区间，收到 {stop_loss_pct}"
            )
        if trailing_stop_pct is not None and not (0 < trailing_stop_pct < 1):
            raise ValueError(
                f"trailing_stop_pct 应在 (0, 1) 区间或为 None，"
                f"收到 {trailing_stop_pct}"
            )

        self._stop_loss_pct = stop_loss_pct
        self._trailing_stop_pct = trailing_stop_pct

        # 运行时状态（移动止损需要跟踪最高价）
        self._highest_price_since_entry: Optional[float] = None

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "stop_loss_pct": self._stop_loss_pct,
            "trailing_stop_pct": self._trailing_stop_pct,
            "mode": "grid_stop_loss",
        }

    @property
    def stop_loss_pct(self) -> float:
        return self._stop_loss_pct

    @property
    def trailing_stop_pct(self) -> Optional[float]:
        return self._trailing_stop_pct

    # ── 状态管理 ──────────────────────────────────────────

    def reset(self) -> None:
        """复位状态（新持仓开始时调用）。"""
        self._highest_price_since_entry = None

    def update_highest(self, current_price: float) -> None:
        """
        更新持仓期间的最高价。

        参数
        ----------
        current_price : float
            当前价格（通常使用 bar.high 或 bar.close）。
        """
        if self._highest_price_since_entry is None:
            self._highest_price_since_entry = current_price
        else:
            self._highest_price_since_entry = max(
                self._highest_price_since_entry, current_price
            )

    # ── 核心检查 ──────────────────────────────────────────

    def check_stop_loss(
        self,
        context: Any = None,
        bar: Optional[Bar] = None,
        entry_price: float = 0.0,
    ) -> bool:
        """
        检查是否触发止损条件。

        检查顺序：固定止损 → 移动止损。
        任一条件满足即返回 True。

        参数
        ----------
        context : Any, optional
            回测上下文（当前未使用，预留接口兼容）。
        bar : Bar, optional
            当前 K 线。如传入，自动更新最高价并基于 bar.close 检查。
        entry_price : float
            持仓均价（avg_cost / entry price）。

        返回
        -------
        bool
            True = 应止损平仓。
        """
        if entry_price <= 0:
            return False

        # 使用 bar.close 作为当前参考价（如提供）
        current_price = bar.close if bar is not None else entry_price

        # ── 更新移动止损最高价 ──────────────────────────
        if self._trailing_stop_pct is not None and bar is not None:
            self.update_highest(max(bar.high, bar.close))

        # ── 1. 固定止损检查 ─────────────────────────────
        pnl_pct = (current_price - entry_price) / entry_price
        if pnl_pct <= -self._stop_loss_pct:
            return True

        # ── 2. 移动止损检查 ─────────────────────────────
        if (
            self._trailing_stop_pct is not None
            and self._highest_price_since_entry is not None
            and self._highest_price_since_entry > entry_price
        ):
            drawdown_pct = (
                (self._highest_price_since_entry - current_price)
                / self._highest_price_since_entry
            )
            if drawdown_pct >= self._trailing_stop_pct:
                return True

        return False


# ═══════════════════════════════════════════════════════════════
# P4-08: GridMaxExposure — 网格总仓位上限
# ═══════════════════════════════════════════════════════════════


class GridMaxExposure:
    """
    网格总仓位上限风控（P4-08）。

    限制网格策略的整体敞口，从两个维度：
      1. 总仓位比例 — 所有持仓市值 / 总资产 ≤ max_position_pct
      2. 活跃网格数 — 同时持仓的网格线数量 ≤ max_grids_active

    参数
    ----------
    max_position_pct : float
        最大总仓位比例（0~1）。如 0.20 = 总持仓不超过总资产的 20%。
    max_grids_active : int
        同时活跃网格数量上限（0 表示不限制，默认 3）。
    """

    def __init__(
        self,
        max_position_pct: float = 0.20,
        max_grids_active: int = 3,
    ):
        if not (0 < max_position_pct <= 1):
            raise ValueError(
                f"max_position_pct 应在 (0, 1] 区间，收到 {max_position_pct}"
            )
        if max_grids_active < 0:
            raise ValueError(
                f"max_grids_active 应 >= 0，收到 {max_grids_active}"
            )

        self._max_position_pct = max_position_pct
        self._max_grids_active = max_grids_active

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        return {
            "max_position_pct": self._max_position_pct,
            "max_grids_active": self._max_grids_active,
            "mode": "grid_max_exposure",
        }

    @property
    def max_position_pct(self) -> float:
        return self._max_position_pct

    @property
    def max_grids_active(self) -> int:
        return self._max_grids_active

    # ── 核心检查 ──────────────────────────────────────────

    def can_open_new(
        self,
        context: Any = None,
        current_active_grids: int = 0,
    ) -> bool:
        """
        检查是否可以开新仓位。

        两个条件同时满足才允许开仓：
          1. 当前总持仓比例 ≤ max_position_pct
          2. 当前活跃网格数 < max_grids_active（如果设置了上限）

        参数
        ----------
        context : BacktestContext, optional
            回测上下文（需有 total_equity / positions 等属性）。
        current_active_grids : int
            当前活跃网格数量。

        返回
        -------
        bool
            True = 可以开新仓位。
        """
        # ── 1. 检查总仓位比例 ──────────────────────────
        if context is not None:
            position_pct = self._calc_position_pct(context)
            if position_pct >= self._max_position_pct:
                return False

        # ── 2. 检查活跃网格数 ──────────────────────────
        if self._max_grids_active > 0:
            if current_active_grids >= self._max_grids_active:
                return False

        return True

    @staticmethod
    def _calc_position_pct(context: Any) -> float:
        """
        计算当前总仓位比例。

        总仓位比例 = 所有持仓市值 / 总资产。
        如果无法获取完整数据，返回 0.0。
        """
        if context is None:
            return 0.0

        # 获取总资产
        total_equity = 0.0
        if hasattr(context, "total_equity"):
            total_equity = getattr(context, "total_equity", 0) or 0
        elif hasattr(context, "available_capital"):
            # 后备方案：用可用资金估算（不精确）
            available = getattr(context, "available_capital", 0) or 0
            # 如果没有持仓，总资产 ≈ 可用资金
            total_equity = available

        if total_equity <= 0:
            return 0.0

        # 获取持仓市值
        position_value = 0.0
        if hasattr(context, "positions"):
            positions = getattr(context, "positions", None)
            if positions is not None and hasattr(positions, "all"):
                all_positions = positions.all() if callable(positions.all) else []
                for pos in all_positions:
                    market_value = getattr(pos, "market_value", 0) or 0
                    position_value += market_value

        if position_value <= 0:
            return 0.0

        return position_value / total_equity

    # ── 辅助 ──────────────────────────────────────────────

    def reset(self) -> None:
        """复位状态（回测开始或结束时调用）。"""
        pass  # 无运行时状态需要复位

    def check_position_limit(self, context: Any = None) -> bool:
        """
        检查当前持仓是否超过最大比例限制。

        返回 True 表示超限（需要减仓）。
        与 can_open_new 互补：can_open_new 用于开仓前检查，
        check_position_limit 用于持仓后监控。

        参数
        ----------
        context : BacktestContext, optional
            回测上下文。

        返回
        -------
        bool
            True = 超限（position_pct > max_position_pct）。
        """
        if context is None:
            return False
        position_pct = self._calc_position_pct(context)
        return position_pct > self._max_position_pct


# ═══════════════════════════════════════════════════════════════
# P4-09: 工厂函数
# ═══════════════════════════════════════════════════════════════


def create_grid_position(
    mode: str = "fixed",
    quantity: int = DEFAULT_QUANTITY,
    **kwargs: Any,
) -> PositionType:
    """
    网格仓位工厂函数（P4-09）。

    根据模式名快速创建仓位管理实例。

    参数
    ----------
    mode : str
        仓位模式。可选:
          - "fixed"    → GridFixedPosition
          - "layer"    → GridLayerPosition
          - "batcher"  → GridBatcherPosition
    quantity : int
        固定仓位时的股数（mode="fixed" 时生效，默认 100）。
    **kwargs :
        传给特定仓位类的专有参数:
          - layer 模式支持: base_quantity, layer_multiplier, max_layers, multiplier_cap
          - batcher 模式支持: total_grid_rows, tiers

    返回
    -------
    GridFixedPosition | GridLayerPosition | GridBatcherPosition

    用法::

        # 固定仓位 200 股
        pos = create_grid_position(mode="fixed", quantity=200)

        # 层数阶梯仓位
        pos = create_grid_position(
            mode="layer",
            base_quantity=100,
            layer_multiplier=2.0,
            max_layers=5,
        )

        # 分批建仓
        pos = create_grid_position(
            mode="batcher",
            total_grid_rows=12,
            tiers=[{"level_from": 0.0, "level_to": 0.5, "ratio": 0.7}, ...],
        )
    """
    _MODES = {
        "fixed": GridFixedPosition,
        "layer": GridLayerPosition,
        "batcher": GridBatcherPosition,
    }

    cls = _MODES.get(mode)
    if cls is None:
        raise ValueError(
            f"未知网格仓位模式: {mode}，可选: {list(_MODES.keys())}"
        )

    if cls is GridFixedPosition:
        return cls(quantity=quantity)
    else:
        return cls(**kwargs)


def create_grid_risk(
    mode: str = "cool_down",
    **kwargs: Any,
) -> RiskType:
    """
    网格风控工厂函数（P4-09）。

    根据模式名快速创建风控模块实例。

    参数
    ----------
    mode : str
        风控模式。可选:
          - "cool_down"   → GridCoolDown
          - "stop_loss"   → GridStopLoss
          - "exposure"    → GridMaxExposure
    **kwargs :
        传给特定风控类的专有参数:
          - cool_down 模式: cool_down_bars
          - stop_loss 模式: stop_loss_pct, trailing_stop_pct
          - exposure 模式: max_position_pct, max_grids_active

    返回
    -------
    GridCoolDown | GridStopLoss | GridMaxExposure

    用法::

        cd = create_grid_risk(mode="cool_down", cool_down_bars=5)
        sl = create_grid_risk(mode="stop_loss", stop_loss_pct=0.05)
        exp = create_grid_risk(mode="exposure", max_position_pct=0.20)
    """
    _MODES = {
        "cool_down": GridCoolDown,
        "stop_loss": GridStopLoss,
        "exposure": GridMaxExposure,
    }

    cls = _MODES.get(mode)
    if cls is None:
        raise ValueError(
            f"未知网格风控模式: {mode}，可选: {list(_MODES.keys())}"
        )

    return cls(**kwargs)


# ═══════════════════════════════════════════════════════════════
# P4-09: 组合仓位管理器（网格版）
# ═══════════════════════════════════════════════════════════════


class GridPositionManager:
    """
    网格组合仓位管理器（P4-09）。

    将网格仓位计算（GridFixedPosition / GridLayerPosition /
    GridBatcherPosition）与网格风控（GridCoolDown / GridStopLoss /
    GridMaxExposure）组合使用。

    用法::

        pos = GridFixedPosition(quantity=200)
        cd = GridCoolDown(cool_down_bars=3)
        sl = GridStopLoss(stop_loss_pct=0.05)
        exp = GridMaxExposure(max_position_pct=0.20)

        mgr = GridPositionManager(
            position_logic=pos,
            cool_down=cd,
            stop_loss=sl,
            exposure=exp,
        )

        # 买入信号
        if mgr.can_open(context, bar, triggered_levels=[]):
            buy_qty = mgr.on_buy_signal(context, bar)

        # 卖出信号
        if mgr.should_exit(context, bar, entry_price=avg_cost):
            sell_qty = mgr.on_sell_signal(context, bar)

        # 触发后记录冷却
        mgr.on_trigger("level_0", current_bar=42)
    """

    def __init__(
        self,
        position_logic: PositionType,
        cool_down: Optional[GridCoolDown] = None,
        stop_loss: Optional[GridStopLoss] = None,
        exposure: Optional[GridMaxExposure] = None,
    ):
        self.position_logic = position_logic
        self.cool_down = cool_down
        self.stop_loss = stop_loss
        self.exposure = exposure

    # ── 序列化接口 ────────────────────────────────────────

    @property
    def params(self) -> Dict[str, Any]:
        p: Dict[str, Any] = {
            "position_logic": self.position_logic.params,
            "mode": "grid_manager",
        }
        if self.cool_down is not None:
            p["cool_down"] = self.cool_down.params
        if self.stop_loss is not None:
            p["stop_loss"] = self.stop_loss.params
        if self.exposure is not None:
            p["exposure"] = self.exposure.params
        return p

    # ── 开仓决策 ──────────────────────────────────────────

    def can_open(
        self,
        context: Any,
        bar: Bar,
        grid_line_id: Optional[str] = None,
        current_active_grids: int = 0,
        current_bar: Optional[int] = None,
    ) -> bool:
        """
        综合判断是否可以开新仓位。

        检查顺序：总敞口 → 冷却状态。
        所有检查通过才返回 True。

        参数
        ----------
        context : BacktestContext
            回测上下文。
        bar : Bar
            当前 K 线。
        grid_line_id : str, optional
            触发信号的网格线 ID（冷却检查需要）。
        current_active_grids : int
            当前活跃网格数（默认 0）。
        current_bar : int, optional
            当前 Bar 索引（冷却检查需要）。

        返回
        -------
        bool
            True = 满足所有风控条件，可以开仓。
        """
        # 1. 总敞口检查
        if self.exposure is not None:
            if not self.exposure.can_open_new(context, current_active_grids):
                return False

        # 2. 冷却检查
        if self.cool_down is not None and grid_line_id is not None and current_bar is not None:
            if not self.cool_down.is_cooled_down(grid_line_id, current_bar):
                return False

        return True

    # ── 仓位计算转发 ──────────────────────────────────────

    def on_buy_signal(
        self,
        context: Any,
        bar: Bar,
        triggered_levels: Optional[List[str]] = None,
        grid_position: float = 0.0,
    ) -> int:
        """
        买入信号回调，转发给 position_logic。

        参数
        ----------
        context : BacktestContext
            回测上下文。
        bar : Bar
            当前 K 线。
        triggered_levels : List[str], optional
            已触发层数列表（GridLayerPosition 需要）。
        grid_position : float, optional
            网格位置（GridBatcherPosition 需要）。

        返回
        -------
        int
            买入股数。
        """
        if isinstance(self.position_logic, GridLayerPosition):
            return self.position_logic.on_buy_signal(
                context, bar, triggered_levels=triggered_levels
            )
        elif isinstance(self.position_logic, GridBatcherPosition):
            return self.position_logic.on_buy_signal(
                context, bar, grid_position=grid_position
            )
        elif isinstance(self.position_logic, GridFixedPosition):
            return self.position_logic.on_buy_signal(context, bar)
        else:
            raise TypeError(
                f"不支持的 position_logic 类型: {type(self.position_logic)}"
            )

    def on_sell_signal(self, context: Any, bar: Bar) -> int:
        """
        卖出信号回调，转发给 position_logic。

        参数
        ----------
        context : BacktestContext
            回测上下文。
        bar : Bar
            当前 K 线。

        返回
        -------
        int
            卖出股数。
        """
        if hasattr(self.position_logic, "on_sell_signal"):
            return self.position_logic.on_sell_signal(context, bar)
        return 0

    # ── 风控检查 ──────────────────────────────────────────

    def check_stop_loss(self, context: Any, bar: Bar, entry_price: float) -> bool:
        """
        检查止损条件。

        参数
        ----------
        context : BacktestContext
            回测上下文。
        bar : Bar
            当前 K 线。
        entry_price : float
            入场价格（持仓均价）。

        返回
        -------
        bool
            True = 触发止损。
        """
        if self.stop_loss is not None:
            return self.stop_loss.check_stop_loss(context, bar, entry_price)
        return False

    def check_exposure_breach(self, context: Any) -> bool:
        """
        检查是否超限（需要减仓）。

        参数
        ----------
        context : BacktestContext
            回测上下文。

        返回
        -------
        bool
            True = 持仓比例超限。
        """
        if self.exposure is not None:
            return self.exposure.check_position_limit(context)
        return False

    # ── 触发记录 ──────────────────────────────────────────

    def on_trigger(self, grid_line_id: str, current_bar: int) -> None:
        """
        记录网格线触发（更新冷却状态）。

        参数
        ----------
        grid_line_id : str
            网格线 ID。
        current_bar : int
            当前 Bar 索引。
        """
        if self.cool_down is not None:
            self.cool_down.on_trigger(grid_line_id, current_bar)

    # ── 状态管理 ──────────────────────────────────────────

    def reset(self) -> None:
        """复位所有状态（新回测开始时调用）。"""
        if self.cool_down is not None:
            self.cool_down.reset()
        if self.stop_loss is not None:
            self.stop_loss.reset()


# ═══════════════════════════════════════════════════════════════
# 便捷函数：快速创建完整 GridPositionManager
# ═══════════════════════════════════════════════════════════════

_MANAGER_POSITION_MODES = {
    "fixed": GridFixedPosition,
    "layer": GridLayerPosition,
    "batcher": GridBatcherPosition,
}

_MANAGER_RISK_MODES = {
    "cool_down": GridCoolDown,
    "stop_loss": GridStopLoss,
    "exposure": GridMaxExposure,
}


def create_grid_manager(
    position_mode: str = "fixed",
    position_kwargs: Optional[Dict[str, Any]] = None,
    risk_config: Optional[Dict[str, Any]] = None,
) -> GridPositionManager:
    """
    便捷函数：快速创建完整的 GridPositionManager。

    参数
    ----------
    position_mode : str
        仓位模式。可选 "fixed" / "layer" / "batcher"。
    position_kwargs : dict, optional
        仓位对象的参数。
        如 {"quantity": 200}、{"base_quantity": 100, "max_layers": 5}。
    risk_config : dict, optional
        风控配置，格式为:
        {
            "cool_down": {"cool_down_bars": 3},
            "stop_loss": {"stop_loss_pct": 0.05, "trailing_stop_pct": 0.03},
            "exposure": {"max_position_pct": 0.20, "max_grids_active": 3},
        }
        各键可选，只传入需要启用的风控模块。

    返回
    -------
    GridPositionManager

    用法::

        mgr = create_grid_manager(
            position_mode="layer",
            position_kwargs={"base_quantity": 100, "layer_multiplier": 2.0},
            risk_config={
                "cool_down": {"cool_down_bars": 3},
                "stop_loss": {"stop_loss_pct": 0.05},
                "exposure": {"max_position_pct": 0.20, "max_grids_active": 3},
            },
        )
    """
    # 构建仓位对象
    pos_cls = _MANAGER_POSITION_MODES.get(position_mode)
    if pos_cls is None:
        raise ValueError(
            f"未知仓位模式: {position_mode}，可选: {list(_MANAGER_POSITION_MODES.keys())}"
        )

    pk = position_kwargs or {}
    if pos_cls is GridFixedPosition:
        position_logic = pos_cls(quantity=pk.get("quantity", DEFAULT_QUANTITY))
    else:
        position_logic = pos_cls(**pk)

    # 构建风控
    cool_down: Optional[GridCoolDown] = None
    stop_loss: Optional[GridStopLoss] = None
    exposure: Optional[GridMaxExposure] = None

    if risk_config:
        rc = risk_config.get("cool_down")
        if rc is not None:
            cool_down = GridCoolDown(**rc)

        rs = risk_config.get("stop_loss")
        if rs is not None:
            stop_loss = GridStopLoss(**rs)

        re = risk_config.get("exposure")
        if re is not None:
            exposure = GridMaxExposure(**re)

    return GridPositionManager(
        position_logic=position_logic,
        cool_down=cool_down,
        stop_loss=stop_loss,
        exposure=exposure,
    )


__all__ = [
    # P4-07: 仓位
    "GridFixedPosition",
    "GridLayerPosition",
    "GridBatcherPosition",
    # P4-08: 风控
    "GridCoolDown",
    "GridStopLoss",
    "GridMaxExposure",
    # P4-09: 组合 + 工厂
    "GridPositionManager",
    "create_grid_position",
    "create_grid_risk",
    "create_grid_manager",
]
