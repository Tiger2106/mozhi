#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy_router.py — ADR-003 MarketStateFilter 矛盾解决方案

ADR-003 问题:
  - MarketStateFilter 当前允许所有策略类型在 TREND_UP 状态下交易
  - 网格策略 (grid) 的核心假设是价格在区间内震荡 (OSCILLATION)
  - 在 TREND_UP 状态下运行网格策略存在理论矛盾：
    趋势行情中网格容易过早平仓（逆趋势行为），导致机会成本
  - 当前解决方案: 实现策略路由器，将 grid 策略自动路由到 OSCILLATION 状态

路由器规则:
  1. grid 策略 → 仅在 OSCILLATION / SIDEWAYS / LOW_VOL 状态下交易
  2. trend 策略 → 仅在 TREND_UP / TREND_DOWN 状态下交易
  3. reversal 策略 → 允许在所有状态下交易（但标记 WARN）
  4. factor 策略 → 不限制状态（因子自身包含状态信息）

作者: 墨衡 (moheng)
创建时间: 2026-05-19 17:45 +08:00
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("strategy_router")


# ============================================================
# 策略类型枚举
# ============================================================

class StrategyType:
    """策略类型常量"""
    GRID = "grid"
    TREND = "trend"
    REVERSAL = "reversal"
    FACTOR = "factor"


# ============================================================
# 市场状态常量
# ============================================================

class MarketState:
    """标准化市场状态常量"""
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    SIDEWAYS = "SIDEWAYS"
    OSCILLATION = "OSCILLATION"
    HIGH_VOL = "HIGH_VOL"
    LOW_VOL = "LOW_VOL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def all_states(cls) -> list[str]:
        return [
            cls.TREND_UP, cls.TREND_DOWN, cls.SIDEWAYS,
            cls.OSCILLATION, cls.HIGH_VOL, cls.LOW_VOL,
            cls.MIXED, cls.UNKNOWN,
        ]


# ============================================================
# 路由结果
# ============================================================

@dataclass
class RoutingResult:
    """策略路由结果

    Attributes
    ----------
    original_state : str
        原始市场状态
    routed_state : str
        路由后的目标市场状态（可能与原始状态不同）
    is_rerouted : bool
        是否发生了状态路由
    reason : str
        路由原因说明
    warnings : list[str]
        路由警告
    should_block : bool
        是否应阻止策略在此状态下交易
    recommended_action : str
        建议操作: "ALLOW" / "REROUTE" / "BLOCK"
    """
    original_state: str
    routed_state: str
    is_rerouted: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    should_block: bool = False
    recommended_action: str = "ALLOW"


# ============================================================
# 策略路由器
# ============================================================

class StrategyRouter:
    """策略路由器 — 解决 MarketStateFilter 与策略类型的矛盾

    根据策略类型自动路由到合适的市场状态。

    路由规则:
    ┌────────────────┬────────────────────┬────────────────────────┐
    │ 策略类型        │ 原始状态           │ 路由后状态             │
    ├────────────────┼────────────────────┼────────────────────────┤
    │ grid           │ TREND_UP           │ → OSCILLATION (reroute)│
    │ grid           │ TREND_DOWN         │ → OSCILLATION (reroute)│
    │ grid           │ OSCILLATION/SIDEWAY│ → 保持不变 (allow)     │
    │ trend          │ TREND_UP/DOWN      │ → 保持不变 (allow)     │
    │ trend          │ OSCILLATION/SIDEWAY│ → OSCILLATION (warn)   │
    │ reversal       │ any                │ → 保持不变 (warn)     │
    │ factor         │ any                │ → 保持不变 (allow)     │
    └────────────────┴────────────────────┴────────────────────────┘
    """

    # 策略类型 → 兼容的市场状态映射
    _COMPATIBLE_STATES: dict[str, set[str]] = {
        StrategyType.GRID: {
            MarketState.SIDEWAYS, MarketState.OSCILLATION,
            MarketState.LOW_VOL, MarketState.MIXED,
        },
        StrategyType.TREND: {
            MarketState.TREND_UP, MarketState.TREND_DOWN,
            MarketState.HIGH_VOL,
        },
        StrategyType.REVERSAL: set(MarketState.all_states()),
        StrategyType.FACTOR: set(MarketState.all_states()),
    }

    # 策略类型 → 优先路由的目标状态
    _PREFERRED_ROUTE: dict[str, str] = {
        StrategyType.GRID: MarketState.OSCILLATION,
        StrategyType.TREND: MarketState.TREND_UP,
        StrategyType.REVERSAL: MarketState.MIXED,
        StrategyType.FACTOR: MarketState.MIXED,
    }

    @classmethod
    def route(
        cls,
        strategy_type: str,
        current_state: str,
        params: Optional[dict[str, Any]] = None,
    ) -> RoutingResult:
        """执行策略路由

        Parameters
        ----------
        strategy_type : str
            策略类型 (grid/trend/reversal/factor)
        current_state : str
            当前市场状态
        params : dict | None
            策略参数（可选，用于更精细的路由判断）

        Returns
        -------
        RoutingResult
        """
        result = RoutingResult(
            original_state=current_state,
            routed_state=current_state,
        )

        # 标准化输入
        stype = strategy_type.lower()
        state = current_state.upper()
        params = params or {}

        # 检查策略类型是否有效
        if stype not in cls._COMPATIBLE_STATES:
            result.warnings.append(f"未知策略类型: {stype}，按 reversal 处理")
            stype = StrategyType.REVERSAL

        # 检查状态是否有效
        if state not in cls._COMPATIBLE_STATES.get(stype, set()):
            # 状态不兼容 → 需要路由
            compatible = cls._COMPATIBLE_STATES.get(stype, set())
            if not compatible:
                result.warnings.append(f"策略类型 {stype} 无兼容状态")
                result.recommended_action = "BLOCK"
                result.should_block = True
                return result

            preferred = cls._PREFERRED_ROUTE.get(stype, MarketState.MIXED)

            if preferred in compatible:
                result.routed_state = preferred
            else:
                result.routed_state = next(iter(compatible))

            # 特殊规则：趋势策略在震荡/低波动状态下仅警告，不重新路由
            if stype == StrategyType.TREND and state in (
                MarketState.SIDEWAYS, MarketState.OSCILLATION, MarketState.LOW_VOL,
            ):
                result.is_rerouted = False
                result.routed_state = state
                result.recommended_action = "ALLOW"
                result.reason = (
                    f"趋势策略在 '{state}' 状态下仍可交易，但信号质量可能下降。"
                    f"震荡行情中假突破概率增加，建议减小仓位。"
                )
            else:
                result.is_rerouted = True
                result.recommended_action = "REROUTE"
                if preferred in compatible:
                    result.routed_state = preferred
                else:
                    result.routed_state = next(iter(compatible))

                # 生成路由说明
                if stype == StrategyType.GRID:
                    result.reason = (
                        f"网格策略在 '{state}' 状态下运行存在理论矛盾。"
                        f"网格假设价格在区间内震荡，趋势行情中容易过早平仓。"
                        f"路由至 '{result.routed_state}' 状态。"
                    )
                elif stype == StrategyType.TREND:
                    result.reason = (
                        f"趋势策略在 '{state}' 状态下运行时信号质量可能不佳。"
                        f"推荐在 '{result.routed_state}' 状态下运行。"
                    )
                else:
                    result.reason = (
                        f"策略类型 '{stype}' 在当前状态 '{state}' 下路由至 '{result.routed_state}'"
                    )

            result.warnings.append(result.reason)

        else:
            # 状态兼容
            if stype == StrategyType.REVERSAL:
                result.warnings.append(
                    "反转策略在所有状态下都允许交易，但需注意不同状态下的反转信号质量差异"
                )

        # 检查是否需要阻止交易
        if stype == StrategyType.GRID and state in (
            MarketState.TREND_UP, MarketState.TREND_DOWN,
        ):
            result.should_block = True
            result.recommended_action = "REROUTE"

        return result

    @classmethod
    def check_compatibility(
        cls,
        strategy_type: str,
        state: str,
    ) -> bool:
        """检查策略类型与市场状态是否兼容"""
        stype = strategy_type.lower()
        s = state.upper()
        compatible = cls._COMPATIBLE_STATES.get(stype, set())
        return s in compatible

    @classmethod
    def get_compatible_states(cls, strategy_type: str) -> list[str]:
        """获取策略类型兼容的市场状态列表"""
        stype = strategy_type.lower()
        return sorted(cls._COMPATIBLE_STATES.get(stype, set()))


# ============================================================
# MarketStateFilter 适配器
# ============================================================

class MarketStateFilterAdapter:
    """将 StrategyRouter 集成到现有的 MarketStateFilter 中

    现有 MarketStateFilter 的原始判断逻辑：
      - 状态 = "TREND_UP" → 允许所有策略交易
      - 状态 ≠ "TREND_UP" → 禁止所有策略交易

    适配后的逻辑：
      - 通过 StrategyRouter 路由策略到兼容状态
      - 若路由后状态与原始状态不同，则标记为 rerouted
      - 仅 rerouted 的策略需要特殊处理
    """

    @staticmethod
    def should_trade(
        strategy_type: str,
        current_state: str,
        original_allowed: bool,
    ) -> tuple[bool, Optional[RoutingResult]]:
        """判断是否应该交易

        Parameters
        ----------
        strategy_type : str
        current_state : str
        original_allowed : bool
            原始 MarketStateFilter 的判断结果

        Returns
        -------
        tuple[bool, RoutingResult | None]
            (是否允许交易, 路由结果)
        """
        routing = StrategyRouter.route(strategy_type, current_state)

        if routing.recommended_action == "BLOCK":
            return (False, routing)

        if routing.recommended_action == "REROUTE":
            # 被路由的策略：允许交易但标记
            return (original_allowed, routing)

        # 正常兼容
        return (original_allowed, routing if routing.warnings else None)


# ============================================================
# 使用示例
# ============================================================

def demo() -> None:
    """演示策略路由器的典型使用"""
    print("=" * 60)
    print("Strategy Router Demo — ADR-003 实现")
    print("=" * 60)

    test_cases = [
        ("grid", "TREND_UP"),
        ("grid", "SIDEWAYS"),
        ("grid", "OSCILLATION"),
        ("trend", "TREND_UP"),
        ("trend", "OSCILLATION"),
        ("reversal", "TREND_UP"),
        ("reversal", "OSCILLATION"),
        ("factor", "HIGH_VOL"),
        ("grid", "TREND_DOWN"),
    ]

    print(f"\n{'策略类型':<12} {'当前状态':<15} {'路由后状态':<15} {'重新路由':<10} {'建议操作':<10}")
    print("-" * 62)

    for stype, state in test_cases:
        result = StrategyRouter.route(stype, state)
        rerouted = "✅" if result.is_rerouted else "—"
        action = result.recommended_action
        print(f"{stype:<12} {result.original_state:<15} {result.routed_state:<15} "
              f"{rerouted:<10} {action:<10}")
        if result.warnings:
            for w in result.warnings[:1]:
                print(f"  ↳ {w[:80]}")

    print("\n✅ 演示完成")


if __name__ == "__main__":
    demo()
