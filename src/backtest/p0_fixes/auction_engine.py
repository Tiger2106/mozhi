"""
墨枢 - p0_fixes.auction_engine
A股集合竞价撮合引擎（P1_004a）

实现：
  - AuctionPhase: 竞价阶段枚举
  - get_auction_phase: 根据时间戳判定竞价阶段
  - match_auction_price: 开盘集合竞价撮合定价（最大成交量算法）
  - calc_auction_volume: 计算每个价格点的累计买卖委托量

符合A股交易规则（上交所/深交所）：
  - 9:15-9:20: 集合竞价可撤单阶段
  - 9:20-9:25: 集合竞价不可撤单阶段
  - 9:30-15:00: 连续竞价
  - 撮合原则：最大成交量 → 最小未成交差量 → 最接近前收盘价

author: moheng
created_time: 2026-05-28T12:20+08:00
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional


class AuctionPhase(str, Enum):
    """A股竞价阶段枚举"""
    PRE_OPEN = "pre_open"               # 9:15-9:25 集合竞价
    PRE_OPEN_CHECK = "pre_check"        # 9:20-9:25 不可撤单阶段
    CONTINUOUS = "continuous"           # 9:30后 连续竞价


def get_auction_phase(timestamp: datetime.datetime) -> AuctionPhase:
    """根据时间戳判定当前竞价阶段

    A股交易时段：
        - 9:15-9:20  集合竞价（可撤单）
        - 9:20-9:25  集合竞价（不可撤单）
        - 9:25-9:30  不接受交易申报（可接收委托）
        - 9:30-11:30 连续竞价
        - 11:30-13:00 午休
        - 13:00-15:00 连续竞价

    本函数将 9:25-9:30 归入 CONTINUOUS（已产生开盘价，实际进入等待连续竞价状态）。

    Args:
        timestamp: 待判定时间戳

    Returns:
        AuctionPhase 枚举值

    Raises:
        ValueError: 时间戳不在 A 股交易时段内
    """
    if not isinstance(timestamp, datetime.datetime):
        raise TypeError("timestamp must be a datetime.datetime object")

    t = timestamp.time()

    # 9:20-9:25 不可撤单集合竞价
    if datetime.time(9, 20) <= t < datetime.time(9, 25):
        return AuctionPhase.PRE_OPEN_CHECK
    # 9:15-9:20 可撤单集合竞价
    elif datetime.time(9, 15) <= t < datetime.time(9, 20):
        return AuctionPhase.PRE_OPEN
    # 9:25-9:30 等待期 → 归入连续竞价（已有开盘价）
    # 9:30-11:30 连续竞价
    elif datetime.time(9, 25) <= t < datetime.time(11, 30):
        return AuctionPhase.CONTINUOUS
    # 13:00-15:00 连续竞价
    elif datetime.time(13, 0) <= t < datetime.time(15, 0):
        return AuctionPhase.CONTINUOUS
    else:
        raise ValueError(
            f"时间戳 {timestamp} 不在 A 股交易时段内（9:15-11:30 or 13:00-15:00）"
        )


def calc_auction_volume(
    order_book: dict,
    price_points: list[float],
) -> dict:
    """计算每个价格点的累计买卖委托量

    Args:
        order_book: 委托簿
            {
                "buy": [{"price": 10.0, "volume": 100}, ...],
                "sell": [{"price": 10.05, "volume": 200}, ...]
            }
        price_points: 待计算的价格点列表（升序或降序均可）

    Returns:
        {
            price_points: [
                {"price": 10.0, "cum_buy": 1500, "cum_sell": 500, "matched_vol": 500},
                ...
            ]
        }

    算法：
        cum_buy  = Σ{买单 | price >= price_point}
        cum_sell = Σ{卖单 | price <= price_point}
        matched_vol = min(cum_buy, cum_sell)
    """
    buy_orders = order_book.get("buy", [])
    sell_orders = order_book.get("sell", [])

    results = []

    for pp in sorted(set(price_points)):
        # 累计买单：价格高于等于价格点的买单全部有效
        cum_buy = sum(
            o["volume"] for o in buy_orders
            if o["price"] >= pp
        )
        # 累计卖单：价格低于等于价格点的卖单全部有效
        cum_sell = sum(
            o["volume"] for o in sell_orders
            if o["price"] <= pp
        )
        matched_vol = min(cum_buy, cum_sell)

        results.append({
            "price": round(pp, 2),
            "cum_buy": cum_buy,
            "cum_sell": cum_sell,
            "matched_vol": matched_vol,
        })

    return {"price_points": results}


def _accumulate_orders(orders: list[dict]) -> list[dict]:
    """合并同价位订单

    将多笔同价格订单合并为一笔，简化撮合计算。

    Args:
        orders: 原始订单列表 [{"price": 10.0, "volume": 100}, ...]

    Returns:
        按价格排序的合并订单列表 [{"price": 10.0, "volume": 300}, ...]
    """
    merged: dict[float, int] = {}
    for o in orders:
        p = round(o["price"], 2)
        merged[p] = merged.get(p, 0) + o["volume"]
    return sorted(
        [{"price": p, "volume": v} for p, v in merged.items()],
        key=lambda x: x["price"],
    )


def match_auction_price(
    buy_orders: list[dict],
    sell_orders: list[dict],
    prev_close: Optional[float] = None,
) -> tuple[Optional[float], int]:
    """A股开盘集合竞价撮合定价算法

    原则（按优先级）：
        1. 可实现最大成交量的价格
        2. 若多个价格成交量相同，选未成交差量最小的价格
        3. 若仍未决出，选最接近前收盘价的价格
        4. 若仍未决出，选最接近即时行情最新价的价格
        5. 若仍未决出，选较高价格

    Args:
        buy_orders: 买单列表 [{"price": 10.0, "volume": 100}, ...]
        sell_orders: 卖单列表 [{"price": 10.05, "volume": 200}, ...]
        prev_close: 前收盘价（可选，用于平局判定）

    Returns:
        (matched_price, matched_volume)
        - 成功匹配: (价格, 成交量)
        - 无有效匹配: (None, 0)
    """
    if not buy_orders or not sell_orders:
        return (None, 0)

    # 合并同价位订单
    merged_buy = _accumulate_orders(buy_orders)
    merged_sell = _accumulate_orders(sell_orders)

    # 收集所有可能的价格点（买卖双方出现的所有价格）
    all_prices = set()
    for o in merged_buy:
        all_prices.add(o["price"])
    for o in merged_sell:
        all_prices.add(o["price"])

    if not all_prices:
        return (None, 0)

    # 对每个价格点计算成交量
    candidates = []
    for pp in sorted(all_prices):
        # 累计买单：价格 >= pp
        cum_buy = sum(
            o["volume"] for o in merged_buy
            if o["price"] >= pp
        )
        # 累计卖单：价格 <= pp
        cum_sell = sum(
            o["volume"] for o in merged_sell
            if o["price"] <= pp
        )
        matched_vol = min(cum_buy, cum_sell)
        imbalance = abs(cum_buy - cum_sell)

        candidates.append({
            "price": pp,
            "matched_vol": matched_vol,
            "imbalance": imbalance,
            "cum_buy": cum_buy,
            "cum_sell": cum_sell,
        })

    # 筛选最大成交量
    max_vol = max(c["matched_vol"] for c in candidates)

    # 检查是否有任何匹配
    if max_vol == 0:
        return (None, 0)

    # 保留成交量最大的候选
    best = [c for c in candidates if c["matched_vol"] == max_vol]

    if len(best) == 1:
        return (best[0]["price"], best[0]["matched_vol"])

    # 平局判定1：选未成交差量最小的
    min_imbalance = min(c["imbalance"] for c in best)
    best = [c for c in best if c["imbalance"] == min_imbalance]

    if len(best) == 1:
        return (best[0]["price"], best[0]["matched_vol"])

    # 平局判定2：选最接近前收盘价的价格
    if prev_close is not None:
        best.sort(key=lambda c: abs(c["price"] - prev_close))
        if len(best) > 1 and abs(best[0]["price"] - prev_close) != abs(best[1]["price"] - prev_close):
            return (best[0]["price"], best[0]["matched_vol"])

    # 平局判定3：选较高价格
    return (best[-1]["price"], best[-1]["matched_vol"])
