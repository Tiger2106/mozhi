"""
墨枢 - p0_fixes.engine_preflight_integration
引擎预检集成模块 — OrderPreflightValidator

在引擎执行订单前插入预检逻辑：
  1. 涨跌停限制检查（买入不追涨停，卖出不追跌停）
  2. 流动性约束检查
  3. 容量约束检查
  4. 返回综合判定

依赖：preflight 模块（P1_001b，已通过 ✓）

P1 流水线：stage_1_p1_001c
author: moheng
created_time: 2026-05-28T12:43+08:00
"""
from __future__ import annotations

from typing import Any, List, Optional

from .preflight import (
    MarketType,
    check_limit_trade,
    get_market_type,
    preflight_check,
)


# ═══════════════════════════════════════════════════════════════
# Bar 字段提取工具
# ═══════════════════════════════════════════════════════════════

def _get_bar_field(bar: Any, *aliases: str, default: Any = None) -> Any:
    """从 bar 对象按别名列表依次取字段，支持 dict 和属性访问。"""
    if bar is None:
        return default
    for name in aliases:
        if isinstance(bar, dict):
            if name in bar:
                return bar[name]
        else:
            if hasattr(bar, name):
                return getattr(bar, name)
    return default


def _normalize_side(side: str) -> str:
    """归一化交易方向。"""
    s = side.strip().lower() if side else ""
    if s in ("buy", "long", "open"):
        return "buy"
    if s in ("sell", "short", "close"):
        return "sell"
    return s


# ═══════════════════════════════════════════════════════════════
# OrderPreflightValidator 类
# ═══════════════════════════════════════════════════════════════

class OrderPreflightValidator:
    """
    订单预检验证器——在引擎执行订单前插入。

    职责：
        1. 检查涨跌停限制（买入不追涨停，卖出不追跌停）
        2. 检查流动性约束
        3. 检查容量约束
        4. 返回综合判定

    Parameters
    ----------
    max_retries : int
        最大重试次数，默认 1（暂未使用，为扩展预留）。
    """

    def __init__(self, max_retries: int = 1):
        self.max_retries = max(max_retries, 0)

    # ── 核心验证 ──

    def validate(self, bar, order: dict) -> dict:
        """
        逐笔订单预检。

        Parameters
        ----------
        bar : dict | object | None
            当前 bar 数据。可以 dict 或对象，需包含：
                prev_close / preClose : float — 前收盘价
                close / price / current_price : float — 当前价
                stock_code / code / symbol : str — 股票代码
                (可选) market_type / market: str — 板块类型
                (可选) volume / amount — 成交量（流动性标志）
        order : dict
            订单信息，需包含：
                side : str — 'buy' | 'sell' | 'long' | 'short' | 'open' | 'close'
                price : float — 订单价格（可选，无则使用 bar 的当前价）
                (可选) volume : int | float — 订单数量
                (可选) type : str — 订单类型
                (可选) stock_code : str — 股票代码（优先于 bar）

        Returns
        -------
        dict
            {
                "pass": bool,             # 全部检查通过 → True
                "reject_reason": str,     # 拒绝原因，pass=True 时为空字符串
                "checks": {
                    "limit_check": bool,
                    "liquidity_check": bool,
                    "capacity_check": bool,
                },
                "details": {
                    "limit_trade": dict,   # check_limit_trade 返回的 detail
                    "liquidity": dict,     # 流动性检查详情
                    "capacity": dict,      # 容量检查详情
                },
            }
        """
        # ── 前置校验 ──
        fail_result = {
            "pass": False,
            "reject_reason": "",
            "checks": {
                "limit_check": False,
                "liquidity_check": False,
                "capacity_check": False,
            },
            "details": {
                "limit_trade": {},
                "liquidity": {},
                "capacity": {},
            },
        }

        if bar is None:
            fail_result["reject_reason"] = "bar 为空，无法预检"
            return fail_result

        if not order or not isinstance(order, dict):
            fail_result["reject_reason"] = "order 无效或为空"
            return fail_result

        # ── 提取字段 ──
        prev_close = _get_bar_field(
            bar, "prev_close", "preClose", "preclose", "yesterday_close",
            default=0.0,
        )
        current_price = _get_bar_field(
            bar, "close", "price", "current_price", "last_price",
            default=0.0,
        )
        stock_code = _get_bar_field(
            bar, "stock_code", "code", "symbol", "stock", "ticker",
            default="",
        )

        # order 中的 stock_code 可覆盖 bar 的
        if not stock_code:
            stock_code = order.get("stock_code", "")
        if not stock_code:
            stock_code = order.get("code", "")

        side = _normalize_side(order.get("side", ""))
        order_price = order.get("price", None)
        effective_price = order_price if order_price is not None and order_price > 0 else current_price

        # 检查是否传入了显式的 market_type（引擎侧可能已判定好）
        explicit_market_type = _get_bar_field(
            bar, "market_type", "market", "mt",
        ) or order.get("market_type", None)
        if explicit_market_type and isinstance(explicit_market_type, str):
            # 字符串转枚举
            from .preflight import MarketType
            mt_map = {
                "main": MarketType.MAIN_BOARD,
                "chinext": MarketType.CHINEXT,
                "star": MarketType.STAR,
                "bei": MarketType.BEI,
                "st": MarketType.ST,
                "ipo": MarketType.IPO_FIRST_DAY,
            }
            explicit_market_type = mt_map.get(explicit_market_type.lower().strip())

        # ── Step 1: 涨跌停检查 ──
        limit_allowed, limit_reason, limit_detail = check_limit_trade(
            prev_close=prev_close,
            current_price=effective_price,
            stock_code=stock_code,
            side=side,
            market_type=explicit_market_type,  # 显式 market_type 或 None（自动推断）
        )

        # ── Step 2: 流动性检查（预留） ──
        liquidity_passed = True
        liquidity_detail = {
            "status": "skipped",
            "note": "流动性检查未实现（预留扩展点）",
        }

        # ── Step 3: 容量检查（预留） ──
        order_volume = order.get("volume", 0) or 0
        capacity_passed = True
        capacity_detail = {
            "status": "skipped",
            "volume": order_volume,
            "note": "容量检查未实现（预留扩展点）",
        }

        # ── 综合判定 ──
        checks = {
            "limit_check": limit_allowed,
            "liquidity_check": liquidity_passed,
            "capacity_check": capacity_passed,
        }

        all_passed = all(checks.values())
        reject_reason = ""
        if not all_passed:
            if not limit_allowed:
                reject_reason = limit_reason
            # 后续扩展：若 liquidity/capacity 失败，按优先级返回

        return {
            "pass": all_passed,
            "reject_reason": reject_reason,
            "checks": checks,
            "details": {
                "limit_trade": limit_detail,
                "liquidity": liquidity_detail,
                "capacity": capacity_detail,
            },
        }

    # ── 批量验证 ──

    def validate_batch(self, orders: list[dict], bar=None) -> list[dict]:
        """
        批量预检多个订单。一个订单失败不阻塞其他。

        Parameters
        ----------
        orders : list[dict]
            订单列表，每个元素同 validate() 的 order 参数。
        bar : dict | object | None, optional
            共享 bar 数据。若未提供，从每个 order 中提取
            (order.get('bar', None))。

        Returns
        -------
        list[dict]
            每个订单的预检结果，顺序与输入一致。
        """
        results: list[dict] = []
        for order in orders:
            order_bar = bar
            if order_bar is None:
                order_bar = order.get("bar", None)
            result = self.validate(order_bar, order)
            results.append(result)
        return results

    # ── 重试接口（为后续扩展预留） ──

    def validate_with_retry(self, bar, order: dict) -> dict:
        """
        带重试的订单预检。

        当前实现为直接调用 validate()，后续可扩展为：
          - 第一次失败后等待短暂间隔重试
          - 重试次数不超过 self.max_retries

        Parameters
        ----------
        bar : dict | object | None
        order : dict

        Returns
        -------
        dict
        """
        return self.validate(bar, order)

    def __repr__(self) -> str:
        return f"OrderPreflightValidator(max_retries={self.max_retries})"
