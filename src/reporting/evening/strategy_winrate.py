#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy_winrate.py — D-2: 策略胜率统计引擎

读取所有已完结交易（买入→卖出闭环），统计：
- 每笔盈亏（买入均价 vs 卖出均价 × 数量 - 佣金 - 印花税）
- 胜率：盈利笔数 / 总笔数
- 平均盈/亏幅度
- 最大盈利/亏损
- 总PnL

输出 reports/strategy_winrate_YYYY-MM-DD.md

作者: moheng | created_time: 2026-05-05 14:58 GMT+8
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from src.config import SHANGHAI_TZ

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

TZ_CST = SHANGHAI_TZ
PROJECT_ROOT = Path(r"C:\Users\17699\mo_zhi_sharereports")
REPORTS_DIR = PROJECT_ROOT / "reports"
DB_PATH = str(PROJECT_ROOT / "trade_engine.db")

AUTHOR = "moheng"
CREATED_TIME = "2026-05-05 14:58 GMT+8"


def now_str() -> str:
    return datetime.now(TZ_CST).isoformat()


def today_str() -> str:
    return datetime.now(TZ_CST).strftime("%Y-%m-%d")


def today_compact() -> str:
    return datetime.now(TZ_CST).strftime("%Y%m%d")


def get_closed_trades(db_path: str,
                        account_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    获取所有已完结交易（买入→卖出闭环）。
    匹配规则：同一 position_id 的 BUY_TO_OPEN 和 SELL_TO_CLOSE。

    Args:
        db_path: 数据库路径
        account_id: 账户ID过滤（可选，None=不过滤）
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 获取所有 CLOSED 持仓记录
    if account_id:
        cur.execute("""
            SELECT p.*, 
                   (SELECT SUM(t.commission) FROM transactions t 
                    WHERE t.position_id = p.id AND t.status = 'FILLED') as total_commission,
                   (SELECT SUM(t.tax) FROM transactions t 
                    WHERE t.position_id = p.id AND t.status = 'FILLED') as total_tax
            FROM positions p
            WHERE p.status = 'CLOSED' AND p.account_id = ?
            ORDER BY p.close_time DESC
        """, (account_id,))
    else:
        cur.execute("""
            SELECT p.*, 
                   (SELECT SUM(t.commission) FROM transactions t 
                    WHERE t.position_id = p.id AND t.status = 'FILLED') as total_commission,
                   (SELECT SUM(t.tax) FROM transactions t 
                    WHERE t.position_id = p.id AND t.status = 'FILLED') as total_tax
            FROM positions p
            WHERE p.status = 'CLOSED'
            ORDER BY p.close_time DESC
        """)
    rows = cur.fetchall()

    trades = []
    for r in rows:
        # 获取买入交易
        cur.execute("""
            SELECT price, quantity, commission, tax, trade_time
            FROM transactions
            WHERE position_id = ? AND action IN ('BUY', 'BUY_TO_OPEN') AND status = 'FILLED'
            ORDER BY trade_time ASC
        """, (r["id"],))
        buy_txns = cur.fetchall()

        # 获取卖出交易
        cur.execute("""
            SELECT price, quantity, commission, tax, trade_time
            FROM transactions
            WHERE position_id = ? AND action IN ('SELL', 'SELL_TO_CLOSE') AND status = 'FILLED'
            ORDER BY trade_time ASC
        """, (r["id"],))
        sell_txns = cur.fetchall()

        if not buy_txns or not sell_txns:
            logger.warning(f"持仓 {r['id']} ({r['symbol']}) 缺少买入或卖出记录，跳过")
            conn.close()
            continue

        # 计算买入均价（加权平均）
        buy_total_cost = sum(
            (t["price"] * t["quantity"]) + (t["commission"] or 0) + (t["tax"] or 0)
            for t in buy_txns
        )
        buy_total_qty = sum(t["quantity"] for t in buy_txns)
        buy_avg_price = buy_total_cost / buy_total_qty if buy_total_qty > 0 else 0

        # 卖出成交金额
        sell_total_revenue = sum(
            (t["price"] * t["quantity"]) - (t["commission"] or 0) - (t["tax"] or 0)
            for t in sell_txns
        )
        sell_total_qty = sum(t["quantity"] for t in sell_txns)
        sell_avg_price = sum(t["price"] * t["quantity"] for t in sell_txns) / sell_total_qty if sell_total_qty > 0 else 0

        # 总盈亏
        total_pnl = r["pnl"] or (sell_total_revenue - buy_total_cost * (sell_total_qty / buy_total_qty) if buy_total_qty > 0 else 0)

        # 计算盈亏幅度
        entry_notional = r["entry_price"] * r["quantity"]
        pnl_percent = (total_pnl / entry_notional * 100) if entry_notional > 0 else 0

        # 持仓天数
        if r["entry_time"] and r["close_time"]:
            entry_dt = datetime.strptime(r["entry_time"], "%Y-%m-%d %H:%M:%S")
            close_dt = datetime.strptime(r["close_time"], "%Y-%m-%d %H:%M:%S")
            hold_days = (close_dt - entry_dt).days
        else:
            hold_days = 0

        trade = {
            "position_id": r["id"],
            "symbol": r["symbol"],
            "direction": r["direction"],
            "entry_price": r["entry_price"],
            "close_price": r["close_price"],
            "entry_time": r["entry_time"],
            "close_time": r["close_time"],
            "quantity": r["quantity"],
            "buy_avg_price": round(buy_avg_price, 4),
            "sell_avg_price": round(sell_avg_price, 4),
            "total_commission": round(r["total_commission"] or 0, 2),
            "total_tax": round(r["total_tax"] or 0, 2),
            "pnl": round(total_pnl, 2),
            "pnl_percent": round(pnl_percent, 2),
            "hold_days": hold_days,
            "is_profitable": total_pnl > 0,
        }
        trades.append(trade)

    conn.close()
    return trades


def compute_winrate_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算胜率统计"""
    if not trades:
        return {
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "avg_profit": 0.0,
            "avg_loss": 0.0,
            "max_profit": 0.0,
            "max_loss": 0.0,
            "total_pnl": 0.0,
            "avg_hold_days": 0.0,
            "avg_profit_percent": 0.0,
            "avg_loss_percent": 0.0,
        }

    total = len(trades)
    profitable = [t for t in trades if t["is_profitable"]]
    losing = [t for t in trades if not t["is_profitable"]]
    win_count = len(profitable)
    loss_count = len(losing)

    win_rate = win_count / total * 100 if total > 0 else 0
    avg_profit = sum(t["pnl"] for t in profitable) / win_count if win_count > 0 else 0
    avg_loss = sum(t["pnl"] for t in losing) / loss_count if loss_count > 0 else 0
    max_profit = max((t["pnl"] for t in profitable), default=0.0)
    max_loss = min((t["pnl"] for t in losing), default=0.0)
    total_pnl = sum(t["pnl"] for t in trades)
    avg_hold = sum(t["hold_days"] for t in trades) / total if total > 0 else 0
    avg_profit_percent = sum(t["pnl_percent"] for t in profitable) / win_count if win_count > 0 else 0
    avg_loss_percent = sum(t["pnl_percent"] for t in losing) / loss_count if loss_count > 0 else 0

    return {
        "total_trades": total,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 2),
        "avg_profit": round(avg_profit, 2),
        "avg_loss": round(avg_loss, 2),
        "max_profit": round(max_profit, 2),
        "max_loss": round(max_loss, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_hold_days": round(avg_hold, 1),
        "avg_profit_percent": round(avg_profit_percent, 2),
        "avg_loss_percent": round(avg_loss_percent, 2),
    }


def build_winrate_report(trades: List[Dict[str, Any]], stats: Dict[str, Any]) -> str:
    """构建策略胜率报告"""
    lines = []
    lines.append(f"# 策略胜率统计报告 — {today_str()}\n")
    lines.append(f"<!-- author: {AUTHOR} | created_time: {CREATED_TIME} -->\n")

    if not trades:
        lines.append("> ⚠️ 当前无已完结交易记录。\n")
        return "\n".join(lines) + "\n"

    # ── 概览 ──
    lines.append("## 概览\n")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|:-----|:---|")
    lines.append(f"| 总交易笔数 | `{stats['total_trades']}` |")
    lines.append(f"| 盈利笔数 | `{stats['win_count']}` |")
    lines.append(f"| 亏损笔数 | `{stats['loss_count']}` |")
    lines.append(f"| **胜率** | **`{stats['win_rate']:.1f}%`** |")
    lines.append(f"| 总盈亏 | `{stats['total_pnl']:+.2f}` |")
    lines.append(f"| 平均盈利 | `{stats['avg_profit']:+.2f}` |")
    lines.append(f"| 平均亏损 | `{stats['avg_loss']:+.2f}` |")
    lines.append(f"| 最大盈利 | `{stats['max_profit']:+.2f}` |")
    lines.append(f"| 最大亏损 | `{stats['max_loss']:+.2f}` |")
    lines.append(f"| 平均持仓天数 | `{stats['avg_hold_days']} 天` |")
    lines.append(f"| 平均盈利幅度 | `{stats['avg_profit_percent']:+.2f}%` |")
    lines.append(f"| 平均亏损幅度 | `{stats['avg_loss_percent']:+.2f}%` |")

    # ── 逐笔明细 ──
    lines.append("\n## 逐笔交易明细\n")
    lines.append("| # | 标的 | 方向 | 买入均价 | 卖出均价 | 数量 | 总佣金 | 总印花税 | 盈亏 | 盈亏幅度 | 持仓天数 | 开仓时间 | 平仓时间 |")
    lines.append("|--:|:----|:----:|:--------:|:--------:|:----:|:------:|:--------:|:----:|:--------:|:--------:|:---------|:---------|")
    for i, t in enumerate(trades, 1):
        pnl_icon = "✅" if t["is_profitable"] else "❌"
        lines.append(
            f"| {i} | {t['symbol']} | {t['direction']} "
            f"| {t['buy_avg_price']:.2f} | {t['sell_avg_price']:.2f} "
            f"| {t['quantity']} | {t['total_commission']:.2f} | {t['total_tax']:.2f} "
            f"| {pnl_icon} {t['pnl']:+.2f} | {t['pnl_percent']:+.2f}% "
            f"| {t['hold_days']}天 "
            f"| {t['entry_time'] if t['entry_time'] else 'N/A'} "
            f"| {t['close_time'] if t['close_time'] else 'N/A'} |"
        )

    # ── 按月汇总 ──
    monthly = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        if t["close_time"]:
            month = t["close_time"][:7]
            monthly[month]["trades"] += 1
            if t["is_profitable"]:
                monthly[month]["wins"] += 1
            monthly[month]["pnl"] += t["pnl"]

    lines.append("\n## 月度汇总\n")
    lines.append("| 月份 | 交易笔数 | 盈利笔数 | 胜率 | 月盈亏 |")
    lines.append("|:-----|:--------:|:--------:|:----:|:------:|")
    for month in sorted(monthly.keys()):
        m = monthly[month]
        mr = (m["wins"] / m["trades"] * 100) if m["trades"] > 0 else 0
        lines.append(f"| {month} | {m['trades']} | {m['wins']} | {mr:.0f}% | {m['pnl']:+.2f} |")

    # ── 信号转化率 ──
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT signal_id) FROM transactions WHERE signal_id IS NOT NULL AND signal_id != ''")
    signal_count = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(DISTINCT signal_id) FROM transactions WHERE signal_id IS NOT NULL AND signal_id != '' AND status = 'FILLED'")
    signal_filled = cur.fetchone()[0] or 0
    signal_conv = (signal_filled / signal_count * 100) if signal_count > 0 else 0
    lines.append(f"\n## 信号转化率\n")
    lines.append(f"- 有信号标记的交易: `{signal_count}`")
    lines.append(f"- 信号成交: `{signal_filled}`")
    lines.append(f"- 信号转化率: `{signal_conv:.1f}%`")
    conn.close()

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="策略胜率统计引擎")
    parser.add_argument("--account-id", type=str, default=None, help="账户ID过滤")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("开始统计策略胜率...")

    trades = get_closed_trades(DB_PATH, account_id=args.account_id)
    logger.info(f"获取到 {len(trades)} 笔已完结交易")

    stats = compute_winrate_stats(trades)
    logger.info(f"胜率: {stats['win_rate']:.1f}% ({stats['win_count']}/{stats['total_trades']})")

    report_content = build_winrate_report(trades, stats)

    # 写入报告
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"strategy_winrate_{today_str()}.md"
    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"报告已写入: {report_path}")

    # 控制台摘要
    print(f"\n{'='*50}")
    print(f"策略胜率统计报告 — {today_str()}")
    print(f"{'='*50}")
    print(f"  总交易:   {stats['total_trades']}")
    print(f"  胜率:     {stats['win_rate']:.1f}% ({stats['win_count']}/{stats['total_trades']})")
    print(f"  总盈亏:   {stats['total_pnl']:+.2f}")
    print(f"  平均盈利: {stats['avg_profit']:+.2f}")
    print(f"  平均亏损: {stats['avg_loss']:+.2f}")
    print(f"  最大盈利: {stats['max_profit']:+.2f}")
    print(f"  最大亏损: {stats['max_loss']:+.2f}")
    print(f"  平均持仓: {stats['avg_hold_days']} 天")
    print(f"{'='*50}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
