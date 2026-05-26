#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
operational_daily.py — C-1: 运行日报自动生成

从 trade_engine.db 读取当日交易记录 + 资金流水，汇总生成运行日报。
写入 reports/operational_daily_YYYY-MM-DD.md

在 midday cron (12:30) 后调用，也可在收盘后手动执行。

作者: moheng | created_time: 2026-05-05 14:41 GMT+8
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 项目路径 ──
PROJECT_ROOT = Path(r"C:\Users\17699\mo_zhi_sharereports")
REPORTS_DIR = PROJECT_ROOT / "reports"
DB_PATH = str(PROJECT_ROOT / "trade_engine.db")

TZ_CST = SHANGHAI_TZ

AUTHOR = "moheng"
CREATED_TIME = "2026-05-05 14:41 GMT+8"
VERSION = "1.0"

def now_str() -> str:
    return datetime.now(TZ_CST).isoformat()

def today_str() -> str:
    return datetime.now(TZ_CST).strftime("%Y-%m-%d")

def today_compact() -> str:
    return datetime.now(TZ_CST).strftime("%Y%m%d")

def get_db_connection(db_path: str = DB_PATH) -> Optional[sqlite3.Connection]:
    """获取数据库连接"""
    if not os.path.exists(db_path):
        logger.error(f"[OperationalDaily] 数据库不存在: {db_path}")
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"[OperationalDaily] 数据库连接失败: {e}")
        return None

def query_today_transactions(conn: sqlite3.Connection, date_str: str,
                               account_id: Optional[str] = None) -> List[dict]:
    """查询当日所有交易

    Args:
        conn: 数据库连接
        date_str: 日期 YYYY-MM-DD
        account_id: 账户ID过滤（可选，None=不过滤）
    """
    if account_id:
        query = """
            SELECT * FROM transactions
            WHERE date(trade_time) = ? AND account_id = ?
            ORDER BY trade_time ASC
        """
        params = (date_str, account_id)
    else:
        query = """
            SELECT * FROM transactions
            WHERE date(trade_time) = ?
            ORDER BY trade_time ASC
        """
        params = (date_str,)
    try:
        c = conn.cursor()
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]
    except Exception as e:
        logger.error(f"[OperationalDaily] 查询交易记录失败: {e}")
        return []

def query_today_fund_flow(conn: sqlite3.Connection, date_str: str,
                            account_id: Optional[str] = None) -> List[dict]:
    """查询当日资金流水

    Args:
        conn: 数据库连接
        date_str: 日期 YYYY-MM-DD
        account_id: 账户ID过滤（可选，None=不过滤）
    """
    if account_id:
        query = """
            SELECT * FROM fund_flow
            WHERE date(created_at) = ? AND account_id = ?
            ORDER BY created_at ASC
        """
        params = (date_str, account_id)
    else:
        query = """
            SELECT * FROM fund_flow
            WHERE date(created_at) = ?
            ORDER BY created_at ASC
        """
        params = (date_str,)
    try:
        c = conn.cursor()
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]
    except Exception as e:
        logger.error(f"[OperationalDaily] 查询资金流水失败: {e}")
        return []

def query_daily_pnl(conn: sqlite3.Connection, date_str: str,
                     account_id: Optional[str] = None) -> Optional[dict]:
    """查询当日PnL（daily_pnl表无account_id字段，account_id参数保留为占位符）"""
    if account_id:
        # daily_pnl 表没有 account_id 字段，仅记录日志提示
        logger.debug(f"[OperationalDaily] query_daily_pnl: account_id={account_id}, daily_pnl表无account_id字段")
    query = """
        SELECT * FROM daily_pnl
        WHERE date = ?
        ORDER BY created_at DESC
        LIMIT 1
    """
    try:
        c = conn.cursor()
        c.execute(query, (date_str,))
        row = c.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"[OperationalDaily] 查询日PnL失败: {e}")
        return None

def query_account_balance(conn: sqlite3.Connection) -> Optional[dict]:
    """查询账户余额"""
    query = "SELECT * FROM account_balance ORDER BY id DESC LIMIT 1"
    try:
        c = conn.cursor()
        c.execute(query)
        row = c.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"[OperationalDaily] 查询账户余额失败: {e}")
        return None

def query_positions(conn: sqlite3.Connection, status: str = "OPEN") -> List[dict]:
    """查询持仓信息"""
    query = "SELECT * FROM positions WHERE status = ?"
    try:
        c = conn.cursor()
        c.execute(query, (status,))
        return [dict(r) for r in c.fetchall()]
    except Exception as e:
        logger.error(f"[OperationalDaily] 查询持仓失败: {e}")
        return []

def build_transaction_summary(txns: List[dict]) -> dict:
    """汇总交易数据"""
    total_count = len(txns)
    filled = [t for t in txns if t.get("status") == "FILLED"]
    pending = [t for t in txns if t.get("status") == "PENDING"]
    rejected = [t for t in txns if t.get("status") == "REJECTED"]

    buys = [t for t in filled if "BUY" in (t.get("action") or "")]
    sells = [t for t in filled if "SELL" in (t.get("action") or "")]

    buy_quantity = sum(t.get("quantity", 0) for t in buys)
    sell_quantity = sum(t.get("quantity", 0) for t in sells)
    buy_value = sum((t.get("price", 0) or 0) * (t.get("quantity", 0) or 0) for t in buys)
    sell_value = sum((t.get("price", 0) or 0) * (t.get("quantity", 0) or 0) for t in sells)
    total_commission = sum(t.get("commission", 0) or 0 for t in filled)
    total_tax = sum(t.get("tax", 0) or 0 for t in filled)
    total_fees = total_commission + total_tax

    realized_pnl = sell_value - buy_value - total_commission - total_tax

    return {
        "total_count": total_count,
        "filled_count": len(filled),
        "pending_count": len(pending),
        "rejected_count": len(rejected),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "buy_quantity": buy_quantity,
        "sell_quantity": sell_quantity,
        "buy_value": round(buy_value, 2),
        "sell_value": round(sell_value, 2),
        "total_commission": round(total_commission, 2),
        "total_tax": round(total_tax, 2),
        "total_fees": round(total_fees, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unique_symbols": len(set(t.get("symbol") for t in txns if t.get("symbol"))),
    }

def build_fund_flow_summary(flows: List[dict]) -> dict:
    """汇总资金流水"""
    credits = sum(f.get("amount", 0) for f in flows if f.get("flow_type") == "CREDIT")
    debits = sum(f.get("amount", 0) for f in flows if f.get("flow_type") == "DEBIT")
    freezes = sum(f.get("amount", 0) for f in flows if f.get("flow_type") == "FREEZE")
    unfreezes = sum(f.get("amount", 0) for f in flows if f.get("flow_type") == "UNFREEZE")

    flow_types = set()
    for f in flows:
        if f.get("flow_type"):
            flow_types.add(f["flow_type"])

    start_balance = None
    end_balance = None
    if flows:
        start_balance = flows[0].get("balance_before")
        end_balance = flows[-1].get("balance_after")

    return {
        "total_flows": len(flows),
        "flow_types": sorted(flow_types),
        "total_credit": round(credits, 2),
        "total_debit": round(debits, 2),
        "total_freeze": round(freezes, 2),
        "total_unfreeze": round(unfreezes, 2),
        "start_balance": round(start_balance, 2) if start_balance is not None else None,
        "end_balance": round(end_balance, 2) if end_balance is not None else None,
        "net_flow": round(credits - debits, 2),
    }

def format_currency(value: Optional[float], unit: str = "¥") -> str:
    """格式化货币值"""
    if value is None:
        return "—"
    return f"{unit}{value:,.2f}"

def generate_report(
    date_str: str,
    tx_summary: dict,
    fund_summary: dict,
    daily_pnl: Optional[dict],
    account: Optional[dict],
    open_positions: List[dict],
    is_trading_day: bool = True,
) -> str:
    """生成运行日报 Markdown 内容"""
    now = datetime.now(TZ_CST).strftime("%Y-%m-%d %H:%M:%S")
    is_holiday = "" if is_trading_day else " 🎉 非交易日，以下数据可能为空"

    lines = [
        f"# 运行日报 | {date_str}",
        f"",
        f"<!-- author: {AUTHOR} | created_time: {CREATED_TIME} -->",
        f"<!-- generated: {now} -->",
        f"",
        f"**生成时间**: {now}  {is_holiday}",
        f"",
        f"---",
        f"",
        f"## 一、交易汇总",
        f"",
        f"| 指标 | 数值 |",
        f"|:-----|:----:|",
    ]

    lines.append(f"| 总交易数 | {tx_summary['total_count']} |")
    lines.append(f"|—|—|")
    lines.append(f"| 已成交 | {tx_summary['filled_count']} |")
    lines.append(f"| 待成交 | {tx_summary['pending_count']} |")
    lines.append(f"| 已拒绝 | {tx_summary['rejected_count']} |")
    lines.append(f"|—|—|")
    lines.append(f"| 买入笔数 | {tx_summary['buy_count']} |")
    lines.append(f"| 卖出笔数 | {tx_summary['sell_count']} |")
    lines.append(f"|—|—|")
    lines.append(f"| 买入股数 | {tx_summary['buy_quantity']:,} |")
    lines.append(f"| 卖出股数 | {tx_summary['sell_quantity']:,} |")
    lines.append(f"|—|—|")
    lines.append(f"| 买入总金额 | {format_currency(tx_summary['buy_value'])} |")
    lines.append(f"| 卖出总金额 | {format_currency(tx_summary['sell_value'])} |")
    lines.append(f"|—|—|")
    lines.append(f"| 佣金总计 | {format_currency(tx_summary['total_commission'])} |")
    lines.append(f"| 印花税 | {format_currency(tx_summary['total_tax'])} |")
    lines.append(f"|—|—|")
    lines.append(f"| **已实现PnL** | **{format_currency(tx_summary['realized_pnl'])}** |")
    lines.append(f"| 涉及标的数 | {tx_summary['unique_symbols']} |")

    # 二、资金流水
    lines += [
        f"",
        f"---",
        f"",
        f"## 二、资金流水",
        f"",
        f"| 指标 | 数值 |",
        f"|:-----|:----:|",
    ]

    if fund_summary["start_balance"] is not None:
        lines.append(f"| 期初余额 | {format_currency(fund_summary['start_balance'])} |")
    if fund_summary["end_balance"] is not None:
        lines.append(f"| 期末余额 | {format_currency(fund_summary['end_balance'])} |")
    lines.append(f"|—|—|")
    lines.append(f"| 入账总额 | {format_currency(fund_summary['total_credit'])} |")
    lines.append(f"| 出账总额 | {format_currency(fund_summary['total_debit'])} |")
    lines.append(f"| 冻结总额 | {format_currency(fund_summary['total_freeze'])} |")
    lines.append(f"|—|—|")
    lines.append(f"| **净流入** | **{format_currency(fund_summary['net_flow'])}** |")
    lines.append(f"| 流水笔数 | {fund_summary['total_flows']} |")
    if fund_summary["flow_types"]:
        lines.append(f"| 类型 | {', '.join(fund_summary['flow_types'])} |")

    # 三、日PnL
    lines += [
        f"",
        f"---",
        f"",
        f"## 三、日PnL",
        f"",
    ]

    if daily_pnl:
        lines += [
            f"| 指标 | 数值 |",
            f"|:-----|:----:|",
            f"| 已实现PnL | {format_currency(daily_pnl.get('realized_pnl'))} |",
            f"| 未实现PnL | {format_currency(daily_pnl.get('unrealized_pnl'))} |",
            f"| **当日总PnL** | **{format_currency(daily_pnl.get('total_pnl'))}** |",
            f"|—|—|",
            f"| 累计PnL | {format_currency(daily_pnl.get('cumulative_pnl'))} |",
            f"| 最大回撤 | {format_currency(daily_pnl.get('max_drawdown'))} |",
            f"|—|—|",
            f"| 交易次数 | {daily_pnl.get('trade_count', 0)} |",
            f"| 盈利次数 | {daily_pnl.get('win_count', 0)} |",
            f"| 亏损次数 | {daily_pnl.get('loss_count', 0)} |",
        ]
    else:
        lines.append("⚠️ 当日无PnL记录")

    # 四、账户总览
    lines += [
        f"",
        f"---",
        f"",
        f"## 四、账户总览",
        f"",
    ]

    if account:
        lines += [
            f"| 指标 | 数值 |",
            f"|:-----|:----:|",
            f"| 总资产 | {format_currency(account.get('total_assets'))} |",
            f"| 可用余额 | {format_currency(account.get('available_balance'))} |",
            f"| 冻结金额 | {format_currency(account.get('frozen_amount'))} |",
            f"|—|—|",
            f"| 持仓市值 | {format_currency(account.get('position_market_value'))} |",
            f"| 初始资金 | {format_currency(account.get('initial_capital'))} |",
            f"|—|—|",
            f"| 已实现PnL | {format_currency(account.get('realized_pnl'))} |",
        ]
        if account.get("initial_capital"):
            roi = (account.get("realized_pnl", 0) / account["initial_capital"]) * 100
            lines.append(f"| **ROI** | **{roi:.2f}%** |")
    else:
        lines.append("⚠️ 无账户数据")

    # 五、当前持仓
    lines += [
        f"",
        f"---",
        f"",
        f"## 五、当前持仓",
        f"",
    ]

    if open_positions:
        lines += [
            f"| 标的 | 方向 | 数量 | 入场价 | 浮动PnL |",
            f"|:----:|:----:|:----:|:------:|:-------:|",
        ]
        for pos in open_positions:
            symbol = pos.get("symbol", "—")
            direction = pos.get("direction", "—")
            qty = f"{pos.get('quantity', 0):,}"
            price = format_currency(pos.get("entry_price"))
            pnl = format_currency(pos.get("pnl"))
            lines.append(f"| {symbol} | {direction} | {qty} | {price} | {pnl} |")
        total_market_value = sum(
            (p.get("entry_price", 0) or 0) * (p.get("quantity", 0) or 0)
            for p in open_positions
        )
        total_unrealized_pnl = sum(p.get("pnl", 0) or 0 for p in open_positions)
        lines += [
            f"| **合计** | — | — | — | **{format_currency(total_unrealized_pnl)}** |",
            f"",
            f"持仓市值: {format_currency(total_market_value)}",
        ]
    else:
        lines.append("无持仓")

    # 六、风险指标
    lines += [
        f"",
        f"---",
        f"",
        f"## 六、风险指标",
        f"",
    ]

    total_realized = tx_summary["realized_pnl"]
    if account and account.get("initial_capital"):
        daily_roi = (total_realized / account["initial_capital"]) * 100
        lines.append(f"| 指标 | 数值 |")
        lines.append(f"|:-----|:----:|")
        lines.append(f"| 日收益率 | {daily_roi:+.4f}% |")
        lines.append(f"| 交易胜率 | —（需在交易日收盘后计算） |")
        lines.append(f"| 最大回撤 | —（需完整PnL序列） |")
    else:
        lines.append("无风险指标（初始资金数据缺失）")

    # 尾部
    lines += [
        f"",
        f"---",
        f"",
        f"*运行日报由 {AUTHOR} 自动生成*",
        f"*version: {VERSION}*",
    ]

    return "\n".join(lines)

def generate_operational_daily(
    date_str: Optional[str] = None,
    db_path: str = DB_PATH,
    is_trading_day: bool = True,
    account_id: Optional[str] = None,
) -> Optional[Path]:
    """
    生成运行日报的主入口。

    Args:
        date_str: 日期 YYYY-MM-DD，默认今日
        db_path: 数据库路径
        is_trading_day: 是否为交易日
        account_id: 账户ID过滤（可选，None=不过滤）

    Returns:
        日报文件路径，失败返回 None
    """
    if date_str is None:
        date_str = today_str()

    # 连接数据库
    conn = get_db_connection(db_path)
    if conn is None:
        logger.error("[OperationalDaily] 无法连接数据库，日报生成失败")
        return None

    try:
        # 查询数据
        txns = query_today_transactions(conn, date_str, account_id=account_id)
        flows = query_today_fund_flow(conn, date_str, account_id=account_id)
        daily_pnl = query_daily_pnl(conn, date_str, account_id=account_id)
        account = query_account_balance(conn)
        open_positions = query_positions(conn, "OPEN")

        # 汇总
        tx_summary = build_transaction_summary(txns)
        fund_summary = build_fund_flow_summary(flows)

        # 生成 Markdown
        report = generate_report(
            date_str=date_str,
            tx_summary=tx_summary,
            fund_summary=fund_summary,
            daily_pnl=daily_pnl,
            account=account,
            open_positions=open_positions,
            is_trading_day=is_trading_day,
        )

        # 写入文件
        report_filename = f"operational_daily_{date_str}.md"
        report_path = REPORTS_DIR / report_filename

        # 原子写入
        tmp = report_path.with_suffix(".md.tmp")
        tmp.write_text(report, encoding="utf-8")
        tmp.rename(report_path)

        logger.info(f"[OperationalDaily] 日报已写入: {report_path}")
        return report_path

    except Exception as e:
        logger.error(f"[OperationalDaily] 日报生成异常: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        conn.close()

def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="生成运行日报")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD，默认今日")
    parser.add_argument("--db-path", type=str, default=DB_PATH, help="数据库路径")
    parser.add_argument("--account-id", type=str, default=None, help="账户ID过滤")
    parser.add_argument("--verbose", action="store_true", help="详细输出")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    result = generate_operational_daily(date_str=args.date, db_path=args.db_path,
                                         account_id=args.account_id)
    if result:
        print(f"[OK] 日报已生成: {result}")
        return 0
    else:
        print(f"[FAIL] 日报生成失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
