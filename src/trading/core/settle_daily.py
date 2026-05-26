#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
settle_daily.py — D-1: PnL日结自动接入

在收盘后（16:00）或 morning cron 中调用。
流程：
1. 调用 PnLManager.daily_settlement() 计算当日盈亏
2. 计算持仓市值、未实现PnL、当日已实现PnL
3. 写入 reports/pnl_daily_YYYY-MM-DD.md

也支持 --dry-run 模式预览结算内容而不落库。

作者: moheng | created_time: 2026-05-05 14:58 GMT+8
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

TZ_CST = SHANGHAI_TZ
PROJECT_ROOT = Path(r"C:\Users\17699\mo_zhi_sharereports")
REPORTS_DIR = PROJECT_ROOT / "reports"
DB_PATH = str(PROJECT_ROOT / "trade_engine.db")

# ── 导入 PnLManager ──
sys.path.insert(0, str(PROJECT_ROOT / "automation_v2" / "phase1_core"))
from pnl_manager import PnLManager
from trade_dao import DatabaseManager

def now_str() -> str:
    return datetime.now(TZ_CST).isoformat()

def today_str() -> str:
    return datetime.now(TZ_CST).strftime("%Y-%m-%d")

def today_compact() -> str:
    return datetime.now(TZ_CST).strftime("%Y%m%d")

def build_pnl_report(settle_result: Dict[str, Any], dry_run: bool = False) -> str:
    """构建 PnL 日结报告 Markdown"""
    date = settle_result.get("settlement_date", today_str())
    lines = []
    lines.append(f"# PnL 日结报告 — {date}\n")
    lines.append(f"<!-- author: moheng | created_time: {now_str()} -->\n")

    if dry_run:
        lines.append("> ⚠️ **预览模式** — 以下数据尚未写入数据库\n")
    else:
        lines.append(f"> ✅ 结算记录 ID: `{settle_result.get('pnl_id', 'N/A')}`\n")

    lines.append("## 核心指标\n")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|:-----|:---|")
    lines.append(f"| 已实现盈亏 (Realized PnL) | `{settle_result.get('realized_pnl', 0.0):.2f}` |")
    lines.append(f"| 未实现盈亏 (Unrealized PnL) | `{settle_result.get('unrealized_pnl', 0.0):.2f}` |")
    lines.append(f"| 当日总盈亏 (Total PnL) | `{settle_result.get('total_pnl', 0.0):.2f}` |")
    lines.append(f"| 累计盈亏 (Cumulative PnL) | `{settle_result.get('cumulative_pnl', 0.0):.2f}` |")
    lines.append(f"| 交易笔数 | `{settle_result.get('trade_count', 0)}` |")
    lines.append(f"| 盈利笔数 | `{settle_result.get('win_count', 0)}` |")
    lines.append(f"| 亏损笔数 | `{settle_result.get('loss_count', 0)}` |")

    lines.append("\n## 持仓概览\n")
    # 从数据库直接查询补充持仓数据
    lines.append("> (持仓数据见报表正文)\n")

    lines.append("\n## 结算明细\n")
    lines.append(f"- 结算时间: {now_str()}")
    lines.append(f"- 数据源: trade_engine.db")
    lines.append(f"- 结算方式: PnLManager.daily_settlement()")

    if settle_result.get("success"):
        lines.append(f"- 结算结果: ✅ 成功")
    else:
        lines.append(f"- 结算结果: ❌ 失败 — {settle_result.get('error', '未知错误')}")

    return "\n".join(lines) + "\n"

def enrich_with_portfolio(settle_result: Dict[str, Any], manager: PnLManager) -> Dict[str, Any]:
    """补充投资组合概要到结算结果"""
    try:
        summary = manager.get_portfolio_summary()
        settle_result["total_exposure"] = summary.total_exposure
        settle_result["total_unrealized_pnl"] = summary.total_unrealized_pnl
        settle_result["open_positions_count"] = summary.open_positions_count
        settle_result["closed_positions_count"] = summary.closed_positions_count
    except Exception as e:
        logger.warning(f"获取投资组合概要失败: {e}")
        settle_result["total_exposure"] = 0.0
        settle_result["open_positions_count"] = 0
        settle_result["closed_positions_count"] = 0
    return settle_result

def run_settle(date_str: Optional[str] = None, dry_run: bool = False,
                 account_id: Optional[str] = None) -> Dict[str, Any]:
    """执行日结并返回结果

    Args:
        date_str: 结算日期 (YYYY-MM-DD), 默认今日
        dry_run: 预览模式，不写入数据库
        account_id: 账户ID过滤（可选，None=不过滤）
    """
    if date_str is None:
        date_str = today_str()

    logger.info(f"开始日结: date={date_str}, dry_run={dry_run}, account_id={account_id}")

    # 初始化 PnLManager
    db_manager = DatabaseManager()
    manager = PnLManager(db_manager)

    if dry_run:
        # 预览模式：手动计算，不写入数据库
        import sqlite3

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 从 positions 表获取已实现盈亏
        if account_id:
            cur.execute(
                "SELECT COALESCE(SUM(pnl), 0.0) FROM positions WHERE DATE(close_time) = ? AND status = 'CLOSED' AND account_id = ?",
                (date_str, account_id)
            )
        else:
            cur.execute(
                "SELECT COALESCE(SUM(pnl), 0.0) FROM positions WHERE DATE(close_time) = ? AND status = 'CLOSED'",
                (date_str,)
            )
        realized_pnl = cur.fetchone()[0] or 0.0

        # 从 positions 表获取未平仓持仓（浮动盈亏用持仓市值估算）
        if account_id:
            cur.execute(
                "SELECT COUNT(*) FROM positions WHERE status = 'OPEN' AND DATE(entry_time) <= ? AND account_id = ?",
                (date_str, account_id)
            )
        else:
            cur.execute(
                "SELECT COUNT(*) FROM positions WHERE status = 'OPEN' AND DATE(entry_time) <= ?",
                (date_str,)
            )
        open_count = cur.fetchone()[0]

        # 当日交易笔数
        if account_id:
            cur.execute(
                "SELECT COUNT(*) FROM transactions WHERE DATE(trade_time) = ? AND status = 'FILLED' AND account_id = ?",
                (date_str, account_id)
            )
        else:
            cur.execute(
                "SELECT COUNT(*) FROM transactions WHERE DATE(trade_time) = ? AND status = 'FILLED'",
                (date_str,)
            )
        trade_count = cur.fetchone()[0]

        # 累计盈亏
        cur.execute(
            "SELECT COALESCE(SUM(total_pnl), 0.0) FROM daily_pnl WHERE date <= ?",
            (date_str,)
        )
        cumulative_pnl_before = cur.fetchone()[0] or 0.0

        # 计算总盈亏
        total_pnl = realized_pnl  # 简单模式仅计算已实现盈亏
        cumulative_pnl = cumulative_pnl_before + total_pnl

        conn.close()

        settle_result = {
            "success": True,
            "pnl_id": "DRY_RUN",
            "settlement_date": date_str,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": 0.0,
            "total_pnl": total_pnl,
            "cumulative_pnl": cumulative_pnl,
            "trade_count": trade_count,
            "win_count": 0,
            "loss_count": 0,
            "total_exposure": 0.0,
            "open_positions_count": open_count,
            "closed_positions_count": 0,
        }
        logger.info(f"预览日结: date={date_str}, total_pnl={realized_pnl:.2f}")
        return settle_result

    # 正式结：使用 PnLManager
    try:
        settle_result = manager.daily_settlement(date_str)
        settle_result = enrich_with_portfolio(settle_result, manager)
        logger.info(f"日结完成: date={date_str}, total_pnl={settle_result.get('total_pnl', 0.0):.2f}")
        return settle_result
    except Exception as e:
        logger.error(f"日结失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "settlement_date": date_str,
        }

def main():
    parser = argparse.ArgumentParser(description="PnL 日结自动接入")
    parser.add_argument("--date", type=str, default=None, help="结算日期 (YYYY-MM-DD), 默认今日")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写入数据库")
    parser.add_argument("--account-id", type=str, default=None, help="账户ID过滤")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    date_str = args.date or today_str()
    result = run_settle(date_str, dry_run=args.dry_run, account_id=args.account_id)

    # 写入报告
    report_dir = REPORTS_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"pnl_daily_{date_str}.md"

    report_content = build_pnl_report(result, dry_run=args.dry_run)
    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"报告已写入: {report_path}")

    # 输出关键指标
    print(f"\n{'='*50}")
    print(f"PnL 日结报告 — {date_str}")
    print(f"{'='*50}")
    print(f"  已实现盈亏: {result.get('realized_pnl', 0.0):.2f}")
    print(f"  未实现盈亏: {result.get('unrealized_pnl', 0.0):.2f}")
    print(f"  当日总盈亏: {result.get('total_pnl', 0.0):.2f}")
    print(f"  累计盈亏:   {result.get('cumulative_pnl', 0.0):.2f}")
    print(f"  交易笔数:   {result.get('trade_count', 0)}")
    print(f"  持仓市值:   {result.get('total_exposure', 0.0):.2f}")
    print(f"  结算状态:   {'✅ 成功' if result.get('success') else '❌ 失败'}")
    print(f"{'='*50}")

    return 0 if result.get('success') else 1

if __name__ == "__main__":
    sys.exit(main())
