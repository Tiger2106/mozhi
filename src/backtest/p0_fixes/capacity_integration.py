"""
墨枢 - p0_fixes.capacity_integration
容量管理器 —— P1_003b：Engine/Executor 容量集成（自包含模块）

内联上游接口 check_volume_capacity 逻辑，不依赖外部模块。

职责：
  1. 接收订单后检查是否超过成交量容量
  2. 超出时自动修剪（partial fill）
  3. 超出但零成交量时拒绝
  4. 记录容量统计（累计修剪量、拒绝次数）

P1 流水线：stage_1_p1_003b
依赖：P1_003a（check_volume_capacity 逻辑内联） ✓
      P1_001c（OrderPreflightValidator 兼容） ✓
author: moheng
created_time: 2026-05-28T12:53+08:00
"""
from __future__ import annotations

from typing import Any, Callable, Optional


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

DEFAULT_VOLUME_CAPACITY_PCT: float = 0.05   # 默认容量比例 5%
MAX_VOLUME_CAPACITY_PCT: float = 0.20       # 最大容量比例 20%


# ═══════════════════════════════════════════════════════════════
# check_volume_capacity — 内联成交量容量检查
# ═══════════════════════════════════════════════════════════════

def check_volume_capacity(
    order_qty: int,
    bar_volume: float,
    max_pct: float = DEFAULT_VOLUME_CAPACITY_PCT,
) -> tuple[bool, int, str]:
    """检查订单数量是否超过 Bar 成交量的容量比例。

    约束规则：
      - max_pct 不得超过 MAX_VOLUME_CAPACITY_PCT (20%)
      - bar_volume 为 0 时，允许的最大数量为 0 → 拒绝
      - 同时受 max_pct 和 bar_volume 下限约束

    Parameters
    ----------
    order_qty : int
        订单数量（股数）。
    bar_volume : float
        Bar 的成交量（股数）。
    max_pct : float, optional
        容量比例，默认 0.05 (5%)。
        不得超过 MAX_VOLUME_CAPACITY_PCT (0.20 / 20%)。

    Returns
    -------
    tuple[bool, int, str]
        (allowed, max_allowed_qty, reason)
        - allowed=True : 订单在容量范围内
        - allowed=False: 超出容量限制
        - max_allowed_qty : 当前容量约束下允许的最大订单数量
        - reason : 描述性原因

    Raises
    ------
    ValueError
        当 max_pct > MAX_VOLUME_CAPACITY_PCT 时抛出。
    """
    # ── 参数校验 ──
    if max_pct > MAX_VOLUME_CAPACITY_PCT:
        raise ValueError(
            f"max_pct={max_pct} 超过最大允许值 {MAX_VOLUME_CAPACITY_PCT}"
        )

    order_qty = max(order_qty, 0)
    bar_volume = max(bar_volume, 0.0)
    max_pct = max(max_pct, 0.0)

    # ── 零成交量 → 最大允许数量为 0 ──
    if bar_volume == 0.0:
        return False, 0, "零成交量，无法成交"

    # ── 计算容量上线 ──
    max_allowed_qty = int(bar_volume * max_pct)
    if max_allowed_qty < 0:
        max_allowed_qty = 0

    # ── 判定 ──
    if order_qty <= max_allowed_qty:
        return True, max_allowed_qty, f"订单量 {order_qty} <= 容量 {max_allowed_qty}，在容量范围内"
    else:
        return False, max_allowed_qty, f"订单量 {order_qty} > 容量 {max_allowed_qty}，超出容量限制"


# ═══════════════════════════════════════════════════════════════
# CapacityManager 类
# ═══════════════════════════════════════════════════════════════

class CapacityManager:
    """
    容量管理器——集成到 BacktestEngine 的订单执行链。

    职责：
        1. 接收订单后检查是否超过成交量容量
        2. 超出时自动修剪（partial fill）
        3. 超出但零成交量时拒绝
        4. 记录容量统计（累计修剪量、拒绝次数）

    Parameters
    ----------
    default_max_pct : float, optional
        默认容量比例，默认 0.05 (5%)。
    """

    def __init__(self, default_max_pct: float = DEFAULT_VOLUME_CAPACITY_PCT):
        self.default_max_pct = max(default_max_pct, 0.0)
        self.stats: dict[str, int] = {
            "trimmed_qty": 0,
            "rejected_count": 0,
            "total_checked": 0,
        }

    # ── 单笔强制执行 ──

    def enforce_capacity(
        self,
        order_qty: int,
        bar_volume: float,
        max_pct: Optional[float] = None,
    ) -> dict[str, Any]:
        """强制执行容量限制。

        Parameters
        ----------
        order_qty : int
            订单数量（股数）。
        bar_volume : float
            Bar 的成交量（股数）。
        max_pct : float, optional
            容量比例，默认使用 self.default_max_pct。

        Returns
        -------
        dict
            {
                "action": str,       # "FULL" | "TRIMMED" | "REJECTED"
                "final_qty": int,    # 最终允许成交数量
                "max_allowed": int,  # 容量限制下允许的最大数量
                "reason": str,       # 描述性原因
                "original_qty": int, # 原始订单数量
                "bar_volume": float, # 参考成交量
                "max_pct": float,    # 使用的容量比例
            }

        状态说明：
            - FULL     : 订单量在容量范围内，原样通过
            - TRIMMED  : 超出容量，修剪到 max_allowed
            - REJECTED : 零成交量或订单量为 0，直接拒绝

        Raises
        ------
        ValueError
            当 max_pct > MAX_VOLUME_CAPACITY_PCT 时抛出。
        """
        effective_max_pct = max_pct if max_pct is not None else self.default_max_pct

        # 每次调用都增加统计计数
        self.stats["total_checked"] += 1

        # 归一化
        order_qty = max(order_qty, 0)
        bar_volume = max(bar_volume, 0.0)

        # ── 参数校验（委托给 check_volume_capacity） ──
        allowed, max_allowed, reason = check_volume_capacity(
            order_qty, bar_volume, effective_max_pct,
        )

        # ── 结果判定 ──
        result = {
            "original_qty": order_qty,
            "bar_volume": bar_volume,
            "max_pct": effective_max_pct,
            "max_allowed": max_allowed,
        }

        if bar_volume == 0.0 or order_qty == 0:
            # 零成交量或零订单 → 拒绝
            self.stats["rejected_count"] += 1
            result["action"] = "REJECTED"
            result["final_qty"] = 0
            result["reason"] = reason
            return result

        if allowed:
            # 容量内 → 原样通过
            result["action"] = "FULL"
            result["final_qty"] = order_qty
            result["reason"] = reason
            return result

        # 超出容量 → 修剪
        if max_allowed > 0:
            trimmed_amount = order_qty - max_allowed
            self.stats["trimmed_qty"] += trimmed_amount
            result["action"] = "TRIMMED"
            result["final_qty"] = max_allowed
            result["reason"] = f"超出容量，从 {order_qty} 修剪到 {max_allowed}: {reason}"
            return result

        # 超出容量且 max_allowed == 0 → 拒绝
        self.stats["rejected_count"] += 1
        result["action"] = "REJECTED"
        result["final_qty"] = 0
        result["reason"] = reason
        return result

    # ── 批量强制执行 ──

    def apply_capacity_to_orders(
        self,
        orders: list[dict],
        bar_volume_func: Callable[[dict], float],
    ) -> list[dict]:
        """批量对订单应用容量约束，修改订单数量和状态。

        每个订单会被注入：
          {
            "capacity_action": str,     # "FULL" | "TRIMMED" | "REJECTED"
            "capacity_final_qty": int,  # 容量约束后的最终数量
            "capacity_reason": str,     # 描述
            "capacity_max_allowed": int,# 允许的最大数量
          }

        同时根据 action 修改原始订单的 "volume" 字段：
          - FULL     : volume 不变
          - TRIMMED  : volume 设置为 final_qty
          - REJECTED : volume 设置为 0

        Parameters
        ----------
        orders : list[dict]
            订单列表。每个订单必须包含 "volume" 字段（int）。
        bar_volume_func : Callable[[dict], float]
            从每个订单提取对应 Bar 成交量的函数。
            签名：bar_volume_func(order) -> float

        Returns
        -------
        list[dict]
            修改后的订单列表（被操作的是原列表的可变副本）。
            顺序与输入一致。
        """
        modified_orders: list[dict] = []
        for order in orders:
            raw_vol = order.get("volume", 0)
            if raw_vol is None:
                raw_vol = 0
            order_qty = max(int(raw_vol), 0)
            bar_volume = bar_volume_func(order)
            max_pct = order.get("max_capacity_pct", self.default_max_pct)

            result = self.enforce_capacity(order_qty, bar_volume, max_pct)

            # 复制订单并注入容量约束信息
            modified_order = dict(order)
            modified_order["capacity_action"] = result["action"]
            modified_order["capacity_final_qty"] = result["final_qty"]
            modified_order["capacity_reason"] = result["reason"]
            modified_order["capacity_max_allowed"] = result["max_allowed"]

            # 根据 action 修改 volume 字段
            if result["action"] == "FULL":
                modified_order["volume"] = order_qty
            elif result["action"] == "TRIMMED":
                modified_order["volume"] = result["final_qty"]
            elif result["action"] == "REJECTED":
                modified_order["volume"] = 0

            modified_orders.append(modified_order)

        return modified_orders

    # ── 统计管理 ──

    def reset_stats(self) -> None:
        """重置统计。"""
        self.stats = {
            "trimmed_qty": 0,
            "rejected_count": 0,
            "total_checked": 0,
        }

    def get_stats(self) -> dict[str, int]:
        """返回当前统计快照。"""
        return dict(self.stats)

    def __repr__(self) -> str:
        return (
            f"CapacityManager(default_max_pct={self.default_max_pct}, "
            f"total_checked={self.stats['total_checked']}, "
            f"trimmed={self.stats['trimmed_qty']}, "
            f"rejected={self.stats['rejected_count']})"
        )
