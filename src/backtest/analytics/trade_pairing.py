"""
墨枢 — 交易配对（FIFO Round-Trip 配对/盈亏计算）
从 performance.py 独立拆分，保持向后兼容。
"""
from __future__ import annotations

from typing import Any, Dict, List


def pair_trades_to_roundtrips(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将平铺的填单记录（独立的 BUY/SELL）按时序列配对为 round-trip 完整买卖过程。

    配对规则（完整 FIFO 双队列）：
    - 使用两个队列（buy_queue, sell_queue）分别维护未平仓买单和卖单
    - BUY 填单：先匹配 sell_queue（平空仓），剩余部分入 buy_queue（开多仓）
    - SELL 填单：先匹配 buy_queue（平多仓），剩余部分入 sell_queue（开空仓）
    - 部分平仓：拆分队列头部的订单为已平部分和剩余部分
    - 手续费按成交比例摊销

    Args:
        fills: 平铺填单列表，每项含 date/symbol/side(BUY|SELL)/price/quantity/fee

    Returns:
        round-trip 列表，每项含：
        entry_date, exit_date, direction(多/空),
        entry_price, exit_price, quantity,
        realized_pnl, return_pct, holding_days, entry_fee, exit_fee
    """
    from datetime import datetime

    def _parse_date(d: str) -> datetime:
        return datetime.strptime(d, "%Y-%m-%d") if "-" in d else datetime.strptime(d, "%Y%m%d")

    def _close_trade(entry: dict, exit_price: float, exit_fee: float, exit_date: str,
                     close_qty: int) -> dict:
        """构建单笔 round-trip 记录（手续费调用方已摊销）。"""
        entry_fee_share = entry["fee"] * (close_qty / entry["qty"])
        direction = entry["side"]
        if direction == "long":
            cost = entry["price"] * close_qty
            proceeds = exit_price * close_qty
            ret_pct = round(((exit_price / entry["price"]) - 1.0) * 100, 2)
        else:
            proceeds = entry["price"] * close_qty
            cost = exit_price * close_qty
            ret_pct = round(((entry["price"] / exit_price) - 1.0) * 100, 2)

        realized_pnl = round(proceeds - cost - entry_fee_share - exit_fee, 2)

        try:
            d1 = _parse_date(entry["date"])
            d2 = _parse_date(exit_date)
            holding_days = max(1, (d2 - d1).days)
        except Exception:
            holding_days = 1

        return {
            "entry_date": entry["date"],
            "exit_date": exit_date,
            "direction": direction,
            "entry_price": round(entry["price"], 4),
            "exit_price": round(exit_price, 4),
            "quantity": close_qty,
            "realized_pnl": realized_pnl,
            "return_pct": ret_pct,
            "holding_days": holding_days,
            "entry_fee": round(entry_fee_share, 2),
            "exit_fee": round(exit_fee, 2),
        }

    roundtrips: List[Dict[str, Any]] = []
    # 双队列 FIFO 匹配
    buy_queue: List[Dict[str, Any]] = []    # 未平仓买单（多头仓位）
    sell_queue: List[Dict[str, Any]] = []   # 未平仓卖单（空头仓位）

    for fill in fills:
        side = fill.get("side", "")
        if isinstance(side, str):
            side = side.upper()
        price = float(fill.get("price", 0))
        qty = int(fill.get("quantity", 0))
        fee = float(fill.get("fee", 0))
        date = fill.get("date", "")

        if side == "BUY":
            remaining = qty
            # 1. 先平空头仓位（匹配 sell_queue FIFO）
            while remaining > 0 and sell_queue:
                entry = sell_queue[0]
                close_qty = min(entry["qty"], remaining)
                exit_fee_share = fee * (close_qty / qty)

                roundtrips.append(_close_trade(entry, price, exit_fee_share, date, close_qty))

                entry["qty"] -= close_qty
                entry["fee"] -= entry["fee"] * (close_qty / (entry["qty"] + close_qty))
                remaining -= close_qty
                if entry["qty"] <= 0:
                    sell_queue.pop(0)

            # 2. 剩余部分开多头仓位（入 buy_queue）
            if remaining > 0:
                buy_fee = fee * (remaining / qty) if qty > 0 else 0
                buy_queue.append({
                    "side": "long", "date": date, "price": price,
                    "qty": remaining, "fee": buy_fee,
                })

        elif side == "SELL":
            remaining = qty
            # 1. 先平多头仓位（匹配 buy_queue FIFO）
            while remaining > 0 and buy_queue:
                entry = buy_queue[0]
                close_qty = min(entry["qty"], remaining)
                exit_fee_share = fee * (close_qty / qty)

                roundtrips.append(_close_trade(entry, price, exit_fee_share, date, close_qty))

                entry["qty"] -= close_qty
                entry["fee"] -= entry["fee"] * (close_qty / (entry["qty"] + close_qty))
                remaining -= close_qty
                if entry["qty"] <= 0:
                    buy_queue.pop(0)

            # 2. 剩余部分开空头仓位（入 sell_queue）
            if remaining > 0:
                sell_fee = fee * (remaining / qty) if qty > 0 else 0
                sell_queue.append({
                    "side": "short", "date": date, "price": price,
                    "qty": remaining, "fee": sell_fee,
                })

    return roundtrips


def compute_trade_distribution(roundtrips: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    从 round-trip 交易列表计算盈亏分布统计。

    Returns:
        dict with:
        - total_rounds: int, 完整买卖笔数
        - win_count: int, 盈利笔数
        - loss_count: int, 亏损笔数
        - win_rate: float, 胜率%
        - total_profit: float, 总盈利金额
        - total_loss: float, 总亏损金额
        - avg_profit: float, 平均单笔盈利
        - avg_loss: float, 平均单笔亏损
        - profit_loss_ratio: float, 盈亏比（平均盈利/平均亏损绝对值）
        - max_win_pnl: float, 最大单笔盈利
        - max_loss_pnl: float, 最大单笔亏损
        - max_win_return: float, 最大单笔收益率%
        - max_loss_return: float, 最大单笔亏损率%
        - avg_return_pct: float, 平均收益率%
        - avg_holding_days: float, 平均持仓天数
        - max_holding_days: int, 最长持仓天数
        - min_holding_days: int, 最短持仓天数
    """
    if not roundtrips:
        return {
            "total_rounds": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "total_profit": 0.0,
            "total_loss": 0.0,
            "avg_profit": 0.0,
            "avg_loss": 0.0,
            "profit_loss_ratio": 0.0,
            "max_win_pnl": 0.0,
            "max_loss_pnl": 0.0,
            "max_win_return": 0.0,
            "max_loss_return": 0.0,
            "avg_return_pct": 0.0,
            "avg_holding_days": 0.0,
            "max_holding_days": 0,
            "min_holding_days": 0,
        }

    wins = [t for t in roundtrips if t["realized_pnl"] > 0]
    losses = [t for t in roundtrips if t["realized_pnl"] <= 0]

    total_profit = sum(t["realized_pnl"] for t in wins)
    total_loss = sum(abs(t["realized_pnl"]) for t in losses)
    avg_profit = total_profit / len(wins) if wins else 0.0
    avg_loss = total_loss / len(losses) if losses else 0.0

    all_returns = [t["return_pct"] for t in roundtrips]
    all_holdings = [t["holding_days"] for t in roundtrips]

    return {
        "total_rounds": len(roundtrips),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(roundtrips) * 100, 2) if roundtrips else 0.0,
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_loss_ratio": round(avg_profit / avg_loss, 4) if avg_loss > 0 else (999.0 if avg_profit > 0 else 0.0),
        "max_win_pnl": max(t["realized_pnl"] for t in wins) if wins else 0.0,
        "max_loss_pnl": max(abs(t["realized_pnl"]) for t in losses) if losses else 0.0,
        "max_win_return": max(t["return_pct"] for t in wins) if wins else 0.0,
        "max_loss_return": min(t["return_pct"] for t in losses) if losses else 0.0,
        "avg_return_pct": round(sum(all_returns) / len(all_returns), 2) if all_returns else 0.0,
        "avg_holding_days": round(sum(all_holdings) / len(all_holdings), 1) if all_holdings else 0.0,
        "max_holding_days": max(all_holdings) if all_holdings else 0,
        "min_holding_days": min(all_holdings) if all_holdings else 0,
    }
