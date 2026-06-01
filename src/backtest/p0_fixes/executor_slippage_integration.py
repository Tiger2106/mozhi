"""
墨枢 - p0_fixes.executor_slippage_integration
OrderExecutor 滑点集成模块 — SlippageAwareExecutor (P1_002c)

在 OrderExecutor 的市价单/限价单执行链中插入：
  1. 动态滑点计算（DynamicSlippage） — 替代固定 slippage_rate
  2. 容量约束强制执行（CapacityManager）
  3. 预检（OrderPreflightValidator）— 涨跌停拦截
  4. 三者可独立启用/关闭（通过 None 控制）

P1 流水线：stage_1_p1_002c
依赖：
  P1_002b (DynamicSlippage) ✓
  P1_003b (CapacityManager) ✓ (内联)
  P1_001c (OrderPreflightValidator) ✓ (内联)

author: moheng
created_time: 2026-05-28T13:04+08:00
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..order_executor import (
    FillReport,
    OrderExecutor,
    OrderSide,
    OrderType,
    TradeRecord,
)
from .dynamic_slippage import DynamicSlippage


# ═══════════════════════════════════════════════════════════════
# CapacityManager 导入（尝试内联，失败时使用占位）
# ═══════════════════════════════════════════════════════════════

try:
    from .capacity_integration import CapacityManager

    _HAS_CAPACITY = True
except ImportError:
    CapacityManager = None  # type: ignore[assignment,misc]
    _HAS_CAPACITY = False


# ═══════════════════════════════════════════════════════════════
# OrderPreflightValidator 导入（尝试内联，失败时使用占位）
# ═══════════════════════════════════════════════════════════════

try:
    from .engine_preflight_integration import OrderPreflightValidator

    _HAS_PREFLIGHT = True
except ImportError:
    OrderPreflightValidator = None  # type: ignore[assignment,misc]
    _HAS_PREFLIGHT = False


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

# 动态滑点未配置时的回退值（直接使用 OrderExecutor 默认的 slippage_rate）
_FALLBACK_SLIPPAGE_RATE: float = 0.001


# ═══════════════════════════════════════════════════════════════
# SlippageAwareExecutor
# ═══════════════════════════════════════════════════════════════

class SlippageAwareExecutor:
    """
    滑点感知的 OrderExecutor 包装器。

    在 OrderExecutor 的标准市价单/限价单执行链中插入：
      1. 动态滑点计算（DynamicSlippage）— 替代固定 slippage_rate
      2. 容量约束强制执行（CapacityManager）— 超容量自动修剪
      3. 预检（OrderPreflightValidator）— 涨跌停拦截

    三者均可独立启用/关闭：
      - slippage_model=None → 使用 OrderExecutor 的默认 slippage_rate
      - capacity_manager=None → 跳过容量检查
      - preflight_validator=None → 跳过预检

    Parameters
    ----------
    executor : OrderExecutor
        被包装的 OrderExecutor 实例。
    slippage_model : DynamicSlippage, optional
        动态滑点模型。None 时清退到 executor.slippage_rate。
    capacity_manager : CapacityManager, optional
        容量管理器。None 时跳过容量检查。
    preflight_validator : OrderPreflightValidator, optional
        订单预检验证器。None 时跳过预检。
    """

    def __init__(
        self,
        executor: OrderExecutor,
        slippage_model: Optional[DynamicSlippage] = None,
        capacity_manager: Optional["CapacityManager"] = None,
        preflight_validator: Optional["OrderPreflightValidator"] = None,
    ):
        if not isinstance(executor, OrderExecutor):
            raise TypeError("executor 必须是 OrderExecutor 实例")
        self.executor = executor
        self.slippage_model = slippage_model
        self.capacity_manager = capacity_manager
        self.preflight_validator = preflight_validator

        # ── 集成统计 ──
        self.stats: Dict[str, int] = {
            "total_orders": 0,
            "preflight_rejected": 0,
            "capacity_trimmed": 0,
            "capacity_rejected": 0,
            "delegated_executions": 0,
        }

    # ── 核心方法：市价单执行 ──

    def execute_market(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        fee_rate: Optional[float] = None,
        bar: Any = None,
        market_cap: Optional[float] = None,
        board_code: Optional[str] = None,
        daily_volume_value: Optional[float] = None,
        volatility: Optional[float] = None,
        max_capacity_pct: Optional[float] = None,
        skip_preflight: bool = False,
    ) -> FillReport:
        """
        执行市价单（集成滑点 + 容量 + 预检）。

        参数 (除 OrderExecutor 参数外):
        ----------
        bar : Any, optional
            Bar 数据，传递给 preflight_validator 检查。
        market_cap : float, optional
            市值（亿元），用于动态滑点计算。
        board_code : str, optional
            板块代码，用于动态滑点计算。
        daily_volume_value : float, optional
            日均成交额（元），用于动态滑点计算和容量检查。
        volatility : float, optional
            近期波动率，用于动态滑点计算。
        max_capacity_pct : float, optional
            容量比例覆盖，用于容量检查。
        skip_preflight : bool
            是否跳过预检。默认 False。
        """
        self.stats["total_orders"] += 1

        # ── Step 1: 预检 ──
        if not skip_preflight and self.preflight_validator is not None:
            order_dict = {
                "side": side.value if hasattr(side, "value") else str(side),
                "price": price,
                "volume": quantity,
            }
            preflight_result = self.preflight_validator.validate(bar, order_dict)
            if not preflight_result.get("pass", False):
                self.stats["preflight_rejected"] += 1
                return FillReport(
                    filled=False,
                    fill_price=0.0,
                    fill_quantity=0,
                    fill_fee=0.0,
                    message=(
                        preflight_result.get("reject_reason", "")
                        or "预检未通过"
                    ),
                )

        # ── Step 2: 容量检查 ──
        if self.capacity_manager is not None and daily_volume_value is not None:
            cap_result = self.capacity_manager.enforce_capacity(
                quantity, daily_volume_value, max_capacity_pct,
            )
            action = cap_result["action"]
            if action == "REJECTED":
                self.stats["capacity_rejected"] += 1
                return FillReport(
                    filled=False,
                    fill_price=0.0,
                    fill_quantity=0,
                    fill_fee=0.0,
                    message=cap_result.get("reason", "容量检查拒绝"),
                )
            if action == "TRIMMED":
                self.stats["capacity_trimmed"] += 1
                quantity = cap_result["final_qty"]

        # ── Step 3: 计算动态滑点率 ──
        effective_slippage_rate = self._compute_slippage_rate(
            price, quantity, market_cap, board_code,
            daily_volume_value, volatility,
        )

        # ── Step 4: 暂存滑点率到 executor 并执行 ──
        original_rate = self.executor.slippage_rate
        self.executor.slippage_rate = effective_slippage_rate
        try:
            result = self.executor.execute_market(
                symbol, side, quantity, price, fee_rate,
            )
            # 为成交记录注入动态滑点信息
            self._annotate_trade(result, effective_slippage_rate)
            self.stats["delegated_executions"] += 1
            return result
        finally:
            self.executor.slippage_rate = original_rate

    # ── 核心方法：限价单执行 ──

    def execute_limit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        limit_price: float,
        current_price: float,
        fee_rate: Optional[float] = None,
        bar: Any = None,
        market_cap: Optional[float] = None,
        board_code: Optional[str] = None,
        daily_volume_value: Optional[float] = None,
        volatility: Optional[float] = None,
        max_capacity_pct: Optional[float] = None,
        skip_preflight: bool = False,
    ) -> FillReport:
        """
        执行限价单（集成滑点 + 容量 + 预检）。

        限价单的特殊处理：
          - 限价单触发后，以限价成交（无额外滑点加成）。
          - 但动态滑点率仍会记录到 TradeRecord 的 slippage 字段。
          - 容量检查基于数量而非订单价值。
        """
        self.stats["total_orders"] += 1

        # ── Step 1: 预检 ──
        if not skip_preflight and self.preflight_validator is not None:
            order_dict = {
                "side": side.value if hasattr(side, "value") else str(side),
                "price": limit_price,
                "volume": quantity,
            }
            preflight_result = self.preflight_validator.validate(bar, order_dict)
            if not preflight_result.get("pass", False):
                self.stats["preflight_rejected"] += 1
                return FillReport(
                    filled=False,
                    fill_price=0.0,
                    fill_quantity=0,
                    fill_fee=0.0,
                    message=(
                        preflight_result.get("reject_reason", "")
                        or "预检未通过"
                    ),
                )

        # ── Step 2: 容量检查 ──
        if self.capacity_manager is not None and daily_volume_value is not None:
            cap_result = self.capacity_manager.enforce_capacity(
                quantity, daily_volume_value, max_capacity_pct,
            )
            action = cap_result["action"]
            if action == "REJECTED":
                self.stats["capacity_rejected"] += 1
                return FillReport(
                    filled=False,
                    fill_price=0.0,
                    fill_quantity=0,
                    fill_fee=0.0,
                    message=cap_result.get("reason", "容量检查拒绝"),
                )
            if action == "TRIMMED":
                self.stats["capacity_trimmed"] += 1
                quantity = cap_result["final_qty"]

        # ── Step 3: 计算动态滑点率（仅用于记录，限价成交价不变）──
        effective_slippage_rate = self._compute_slippage_rate(
            limit_price, quantity, market_cap, board_code,
            daily_volume_value, volatility,
        )

        # ── Step 4: 执行 ──
        # 限价单以限价成交，滑点率为 0（无额外滑点加成）
        result = self.executor.execute_limit(
            symbol, side, quantity, limit_price, current_price, fee_rate,
        )

        # 如果是真正的限价单（已触发），覆盖滑点记录
        # (OrderExecutor 的限价单 TradeRecord 的 slippage 字段为 0.0)
        if result.trade is not None:
            result.trade.slippage = effective_slippage_rate

        self.stats["delegated_executions"] += 1
        return result

    # ── 滑点率计算 ──

    def _compute_slippage_rate(
        self,
        price: float,
        quantity: int,
        market_cap: Optional[float] = None,
        board_code: Optional[str] = None,
        daily_volume_value: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> float:
        """计算综合滑点率。

        有 DynamicSlippage → 使用动态滑点计算。
        无 DynamicSlippage → 使用 executor 的默认 slippage_rate。

        Returns
        -------
        float
            滑点率（如 0.001 表示 0.1%）。
        """
        if self.slippage_model is not None:
            order_value = abs(price * quantity)
            return self.slippage_model.get_slippage_rate(
                market_cap=market_cap,
                board_code=board_code,
                order_value=order_value,
                daily_volume_value=daily_volume_value,
                volatility=volatility,
            )
        return self.executor.slippage_rate

    # ── 辅助方法 ──

    def _annotate_trade(self, result: FillReport, slippage_rate: float) -> None:
        """为成交记录的 TradeRecord 注入动态滑点信息。"""
        if result.trade is not None:
            result.trade.slippage = slippage_rate

    def get_trade_history(self) -> List[Dict[str, Any]]:
        """委托给内部 executor 获取成交记录。"""
        return self.executor.get_trade_history()

    def clear_trade_history(self) -> None:
        """委托给内部 executor 清空成交记录。"""
        self.executor.clear_trade_history()

    def reset_stats(self) -> None:
        """重置集成统计。"""
        self.stats = {
            "total_orders": 0,
            "preflight_rejected": 0,
            "capacity_trimmed": 0,
            "capacity_rejected": 0,
            "delegated_executions": 0,
        }

    def get_stats(self) -> Dict[str, int]:
        """返回当前统计快照。"""
        return dict(self.stats)

    # ── 委托属性 ──

    @property
    def trade_history(self) -> list:
        """委托到内部 executor 的成交记录列表。"""
        return self.executor.trade_history

    @property
    def context(self):
        """委托到内部 executor 的回测上下文。"""
        return self.executor.context

    @property
    def slippage_rate(self) -> float:
        """外部可见的滑点率（从内部 executor 读取）。"""
        return self.executor.slippage_rate

    @slippage_rate.setter
    def slippage_rate(self, value: float) -> None:
        """设置内部 excutor 的滑点率。"""
        self.executor.slippage_rate = value

    def __repr__(self) -> str:
        parts = ["SlippageAwareExecutor"]
        parts.append(f"model={'Dynamic' if self.slippage_model else 'Fixed'}")
        parts.append(f"cap={'ON' if self.capacity_manager else 'OFF'}")
        parts.append(f"preflight={'ON' if self.preflight_validator else 'OFF'}")
        parts.append(f"total={self.stats['total_orders']}")
        return f"<{' | '.join(parts)}>"
