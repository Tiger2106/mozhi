#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
strategy_kpi.py — C-2: 策略KPI看板

按月/周维度汇总策略核心指标：
  - signal→order 转化率
  - 买/卖价差（买入均价 vs 卖出均价）
  - 盈亏统计（总PnL、日PnL、胜率、最大回撤）

可独立运行或作为 operational_daily.py 的扩展调用。

作者: moheng | created_time: 2026-05-05 14:41 GMT+8
"""

import json
import logging
import math
import os
import sqlite3
import sys
from collections import defaultdict
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

def get_db_connection(db_path: str = DB_PATH) -> Optional[sqlite3.Connection]:
    """获取数据库连接"""
    if not os.path.exists(db_path):
        logger.error(f"[StrategyKPI] 数据库不存在: {db_path}")
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"[StrategyKPI] 数据库连接失败: {e}")
        return None

def query_all_daily_pnl(conn: sqlite3.Connection,
                          account_id: Optional[str] = None) -> List[dict]:
    """查询所有日PnL记录（daily_pnl表无account_id字段，account_id参数保留为占位符）"""
    if account_id:
        logger.debug(f"[StrategyKPI] query_all_daily_pnl: account_id={account_id}, daily_pnl表无account_id字段")
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM daily_pnl ORDER BY date ASC")
        return [dict(r) for r in c.fetchall()]
    except Exception as e:
        logger.error(f"[StrategyKPI] 查询日PnL失败: {e}")
        return []

def query_all_transactions(conn: sqlite3.Connection,
                             account_id: Optional[str] = None) -> List[dict]:
    """查询所有已成交交易

    Args:
        conn: 数据库连接
        account_id: 账户ID过滤（可选，None=不过滤）
    """
    try:
        c = conn.cursor()
        if account_id:
            c.execute(
                "SELECT * FROM transactions WHERE status = 'FILLED' AND account_id = ? ORDER BY trade_time ASC",
                (account_id,)
            )
        else:
            c.execute("SELECT * FROM transactions WHERE status = 'FILLED' ORDER BY trade_time ASC")
        return [dict(r) for r in c.fetchall()]
    except Exception as e:
        logger.error(f"[StrategyKPI] 查询交易失败: {e}")
        return []

def query_signals_for_conversion(conn: sqlite3.Connection) -> Tuple[int, int]:
    """查询 signal→order 转化率近似值
    将 transactions 中的 signal_id 不为空的视为来自信号系统。
    signal_id 有值 = 由信号生成；所有 FILLED = 已执行。
    """
    try:
        c = conn.cursor()
        total_signal_orders = c.execute(
            "SELECT COUNT(*) FROM transactions WHERE signal_id IS NOT NULL AND signal_id != ''"
        ).fetchone()[0]
        filled_signal_orders = c.execute(
            "SELECT COUNT(*) FROM transactions WHERE signal_id IS NOT NULL AND signal_id != '' AND status = 'FILLED'"
        ).fetchone()[0]
        return total_signal_orders, filled_signal_orders
    except Exception as e:
        logger.error(f"[StrategyKPI] 查询信号转化率失败: {e}")
        return 0, 0

def query_daily_order_count(conn: sqlite3.Connection) -> Dict[str, dict]:
    """按天统计订单数量（用于 daily_order_count 表）"""
    try:
        c = conn.cursor()
        c.execute("""
            SELECT date(trade_time) as day, 
                   COUNT(*) as total, 
                   SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) as filled,
                   SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) as rejected
            FROM transactions 
            GROUP BY day 
            ORDER BY day
        """)
        results = {}
        for r in c.fetchall():
            results[str(r[0])] = {
                "total": r[1],
                "filled": r[2],
                "pending": r[3],
                "rejected": r[4],
            }
        return results
    except Exception as e:
        logger.error(f"[StrategyKPI] 查询日订单数失败: {e}")
        return {}

def compute_buy_sell_spread(txns: List[dict]) -> dict:
    """计算买入均价 vs 卖出均价"""
    buys = [t for t in txns if "BUY" in (t.get("action") or "")]
    sells = [t for t in txns if "SELL" in (t.get("action") or "")]

    if not buys or not sells:
        return {
            "buy_avg_price": None,
            "sell_avg_price": None,
            "spread": None,
            "spread_pct": None,
            "has_data": False,
        }

    buy_total_value = sum((t.get("price", 0) or 0) * (t.get("quantity", 0) or 0) for t in buys)
    buy_total_qty = sum(t.get("quantity", 0) or 0 for t in buys)
    sell_total_value = sum((t.get("price", 0) or 0) * (t.get("quantity", 0) or 0) for t in sells)
    sell_total_qty = sum(t.get("quantity", 0) or 0 for t in sells)

    buy_avg = buy_total_value / buy_total_qty if buy_total_qty > 0 else 0
    sell_avg = sell_total_value / sell_total_qty if sell_total_qty > 0 else 0
    spread = sell_avg - buy_avg
    spread_pct = (spread / buy_avg * 100) if buy_avg > 0 else 0

    return {
        "buy_avg_price": round(buy_avg, 4),
        "sell_avg_price": round(sell_avg, 4),
        "spread": round(spread, 4),
        "spread_pct": round(spread_pct, 2),
        "has_data": True,
    }

def compute_pnl_summary(daily_pnls: List[dict]) -> dict:
    """从日PnL序列计算盈亏统计"""
    if not daily_pnls:
        return {
            "total_pnl": 0,
            "avg_daily_pnl": 0,
            "max_daily_pnl": 0,
            "min_daily_pnl": 0,
            "win_count": 0,
            "loss_count": 0,
            "total_count": 0,
            "win_rate": 0,
            "cumulative_pnl": 0,
            "max_drawdown": 0,
            "has_data": False,
        }

    total_pnl = sum(p.get("total_pnl", 0) or 0 for p in daily_pnls)
    cumulative = daily_pnls[-1].get("cumulative_pnl", 0) or 0
    max_drawdown = daily_pnls[-1].get("max_drawdown", 0) or 0

    trade_days = len(daily_pnls)
    avg_daily = total_pnl / trade_days if trade_days > 0 else 0

    # 盈利/亏损天数
    win_days = sum(1 for p in daily_pnls if (p.get("total_pnl", 0) or 0) > 0)
    loss_days = sum(1 for p in daily_pnls if (p.get("total_pnl", 0) or 0) < 0)
    win_rate = (win_days / trade_days * 100) if trade_days > 0 else 0

    max_daily_pnl = max(p.get("total_pnl", 0) or 0 for p in daily_pnls)
    min_daily_pnl = min(p.get("total_pnl", 0) or 0 for p in daily_pnls)

    return {
        "total_pnl": round(total_pnl, 2),
        "avg_daily_pnl": round(avg_daily, 2),
        "max_daily_pnl": round(max_daily_pnl, 2),
        "min_daily_pnl": round(min_daily_pnl, 2),
        "win_count": win_days,
        "loss_count": loss_days,
        "total_count": trade_days,
        "win_rate": round(win_rate, 2),
        "cumulative_pnl": round(cumulative, 2),
        "max_drawdown": round(max_drawdown, 2),
        "has_data": True,
    }

def compute_weekly_pnl(daily_pnls: List[dict]) -> Dict[str, dict]:
    """按周汇总PnL"""
    weekly = defaultdict(list)
    for p in daily_pnls:
        date_str = p.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%W")
            weekly[week_key].append(p)
        except (ValueError, TypeError):
            continue

    result = {}
    for week_key in sorted(weekly.keys()):
        pnls = weekly[week_key]
        result[week_key] = {
            "days": len(pnls),
            "total_pnl": round(sum(p.get("total_pnl", 0) or 0 for p in pnls), 2),
            "win_days": sum(1 for p in pnls if (p.get("total_pnl", 0) or 0) > 0),
            "loss_days": sum(1 for p in pnls if (p.get("total_pnl", 0) or 0) < 0),
            "avg_daily": round(
                sum(p.get("total_pnl", 0) or 0 for p in pnls) / len(pnls), 2
            ),
        }
    return result

def compute_monthly_pnl(daily_pnls: List[dict]) -> Dict[str, dict]:
    """按月汇总PnL"""
    monthly = defaultdict(list)
    for p in daily_pnls:
        date_str = p.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            month_key = dt.strftime("%Y-%m")
            monthly[month_key].append(p)
        except (ValueError, TypeError):
            continue

    result = {}
    for month_key in sorted(monthly.keys()):
        pnls = monthly[month_key]
        result[month_key] = {
            "days": len(pnls),
            "total_pnl": round(sum(p.get("total_pnl", 0) or 0 for p in pnls), 2),
            "win_days": sum(1 for p in pnls if (p.get("total_pnl", 0) or 0) > 0),
            "loss_days": sum(1 for p in pnls if (p.get("total_pnl", 0) or 0) < 0),
            "win_rate": round(
                sum(1 for p in pnls if (p.get("total_pnl", 0) or 0) > 0) / len(pnls) * 100, 1
            ),
            "avg_daily": round(
                sum(p.get("total_pnl", 0) or 0 for p in pnls) / len(pnls), 2
            ),
        }
    return result

def compute_max_drawdown_series(daily_pnls: List[dict]) -> List[dict]:
    """计算最大回撤序列（从累计PnL序列）"""
    cum_pnls = []
    running = 0
    for p in daily_pnls:
        running += p.get("total_pnl", 0) or 0
        cum_pnls.append({"date": p.get("date", ""), "cumulative": running})

    peak = float("-inf")
    drawdown_series = []
    for cp in cum_pnls:
        peak = max(peak, cp["cumulative"])
        dd = cp["cumulative"] - peak
        dd_pct = (dd / peak * 100) if peak > 0 else 0
        drawdown_series.append({
            "date": cp["date"],
            "cumulative": cp["cumulative"],
            "drawdown": round(dd, 2),
            "drawdown_pct": round(dd_pct, 2),
        })
    return drawdown_series

def format_currency(value: Optional[float], unit: str = "¥") -> str:
    if value is None:
        return "—"
    return f"{unit}{value:,.2f}"

def generate_kpi_report(
    month_key: str,
    month_pnl: dict,
    yearly_pnl: dict,
    weekly_pnl: dict,
    pnl_summary: dict,
    spread: dict,
    conversion_total: int,
    conversion_filled: int,
    drawdown_series: List[dict],
) -> str:
    """生成KPI看板 Markdown 内容"""
    now = datetime.now(TZ_CST).strftime("%Y-%m-%d %H:%S")

    lines = [
        f"# 策略KPI看板 | {month_key}",
        f"",
        f"<!-- author: {AUTHOR} | created_time: {CREATED_TIME} -->",
        f"<!-- generated: {now} -->",
        f"",
        f"---",
        f"",
        f"## 一、本月概览（{month_key}）",
        f"",
        f"| 指标 | 数值 |",
        f"|:-----|:----:|",
    ]

    if month_pnl and month_pnl.get('has_data', False):
        lines += [
            f"| 总PnL | {format_currency(month_pnl['total_pnl'])} |",
            f"| 日均PnL | {format_currency(month_pnl['avg_daily_pnl'])} |",
            f"| 交易天数 | {month_pnl['total_count']} |",
            f"| 盈利天数 | {month_pnl['win_count']} |",
            f"| 亏损天数 | {month_pnl['loss_count']} |",
            f"| 月胜率 | {month_pnl['win_rate']:.1f}% |",
        ]
    else:
        lines.append("| 本月 | 无交易数据 |")

    # 二、年度累计
    lines += [
        f"",
        f"---",
        f"",
        f"## 二、年度累计",
        f"",
        f"| 指标 | 数值 |",
        f"|:-----|:----:|",
    ]

    if yearly_pnl:
        lines += [
            f"| 累计PnL | {format_currency(yearly_pnl['total_pnl'])} |",
            f"| 日均PnL | {format_currency(yearly_pnl.get('avg_daily_pnl', 0))} |",
            f"| 交易天数 | {yearly_pnl['total_count']} |",
            f"| 盈利天数 | {yearly_pnl['win_count']} |",
            f"| 亏损天数 | {yearly_pnl['loss_count']} |",
            f"| **年度胜率** | **{yearly_pnl['win_rate']:.1f}%** |",
            f"| 最大单日盈利 | {format_currency(yearly_pnl['max_daily_pnl'])} |",
            f"| 最大单日亏损 | {format_currency(yearly_pnl['min_daily_pnl'])} |",
            f"| 最大回撤 | {format_currency(yearly_pnl['max_drawdown'])} |",
            f"| 累计PnL(终值) | {format_currency(yearly_pnl['cumulative_pnl'])} |",
        ]
    else:
        lines.append("| 年度 | 无数据 |")

    # 三、周度明细
    lines += [
        f"",
        f"---",
        f"",
        f"## 三、周度PnL明细",
        f"",
    ]

    if weekly_pnl:
        lines += [
            f"| 周次 | 交易天数 | 总PnL | 日均PnL | 盈利天数 | 亏损天数 |",
            f"|:----:|:--------:|:-----:|:--------:|:--------:|:--------:|",
        ]
        for wk_key in sorted(weekly_pnl.keys()):
            w = weekly_pnl[wk_key]
            lines.append(
                f"| {wk_key} | {w['days']} | {format_currency(w['total_pnl'])} | "
                f"{format_currency(w['avg_daily'])} | {w['win_days']} | {w['loss_days']} |"
            )
    else:
        lines.append("⚠️ 无周度数据")

    # 四、买卖价差
    lines += [
        f"",
        f"---",
        f"",
        f"## 四、买卖价差统计",
        f"",
    ]

    if spread.get("has_data"):
        lines += [
            f"| 指标 | 数值 |",
            f"|:-----|:----:|",
            f"| 买入均价 | {format_currency(spread['buy_avg_price'])} |",
            f"| 卖出均价 | {format_currency(spread['sell_avg_price'])} |",
            f"| **价差** | **{format_currency(spread['spread'])}** |",
            f"| 价差率 | {spread['spread_pct']:+.2f}% |",
        ]
    else:
        lines.append("⚠️ 数据不足（需至少各有一笔买入/卖出成交记录）")

    # 五、信号转化率
    lines += [
        f"",
        f"---",
        f"",
        f"## 五、信号→订单转化率",
        f"",
    ]

    if conversion_total > 0:
        conversion_rate = (conversion_filled / conversion_total * 100) if conversion_total > 0 else 0
        lines += [
            f"| 指标 | 数值 |",
            f"|:-----|:----:|",
            f"| 信号来源订单总量 | {conversion_total} |",
            f"| 已成交 | {conversion_filled} |",
            f"| **转化率** | **{conversion_rate:.1f}%** |",
        ]
    else:
        lines.append("⚠️ 无信号来源交易记录")

    # 六、最大回撤序列（摘要）
    lines += [
        f"",
        f"---",
        f"",
        f"## 六、最大回撤序列（累计PnL回撤）",
        f"",
    ]

    if drawdown_series:
        max_dd_point = min(drawdown_series, key=lambda x: x["drawdown"])
        lines += [
            f"| 回撤极值 | {format_currency(max_dd_point['drawdown'])} ({max_dd_point['drawdown_pct']:.2f}%) |",
            f"| 发生日期 | {max_dd_point['date']} |",
            f"| 当前累计PnL | {drawdown_series[-1]['cumulative']:.2f} |",
            f"",
            f"| 日期 | 累计PnL | 回撤幅度 |",
            f"|:----:|:-------:|:--------:|",
        ]
        for dd in drawdown_series[-10:]:  # 最近10个
            lines.append(
                f"| {dd['date']} | {format_currency(dd['cumulative'])} | "
                f"{format_currency(dd['drawdown'])} ({dd['drawdown_pct']:+.2f}%) |"
            )
    else:
        lines.append("⚠️ 无回撤数据")

    # 尾部
    lines += [
        f"",
        f"---",
        f"",
        f"*KPI看板由 {AUTHOR} 自动生成*",
        f"*version: {VERSION}*",
    ]

    return "\n".join(lines)

def generate_strategy_kpi(
    month_key: Optional[str] = None,
    db_path: str = DB_PATH,
    account_id: Optional[str] = None,
) -> Optional[Path]:
    """
    生成策略KPI看板。

    Args:
        month_key: 月份 YYYY-MM，默认当前月
        db_path: 数据库路径
        account_id: 账户ID过滤（可选，None=不过滤）

    Returns:
        KPI文件路径，失败返回 None
    """
    if month_key is None:
        month_key = datetime.now(TZ_CST).strftime("%Y-%m")

    # 连接数据库
    conn = get_db_connection(db_path)
    if conn is None:
        logger.error("[StrategyKPI] 无法连接数据库")
        return None

    try:
        # 查询数据
        daily_pnls = query_all_daily_pnl(conn, account_id=account_id)
        txns = query_all_transactions(conn, account_id=account_id)
        signal_total, signal_filled = query_signals_for_conversion(conn)

        # 计算
        yearly_summary = compute_pnl_summary(daily_pnls)

        # 按月筛选
        month_pnls = [
            p for p in daily_pnls
            if p.get("date", "").startswith(month_key)
        ]
        month_summary = compute_pnl_summary(month_pnls)

        # 周度
        weekly = compute_weekly_pnl(daily_pnls)

        # 按年筛选月度
        year_key = month_key[:4]
        year_pnls = [
            p for p in daily_pnls
            if p.get("date", "").startswith(year_key)
        ]
        yearly_summary = compute_pnl_summary(year_pnls)
        monthly_summary = compute_monthly_pnl(daily_pnls)

        # 买卖价差
        spread = compute_buy_sell_spread(txns)

        # 回撤序列
        drawdown_series = compute_max_drawdown_series(daily_pnls)

        # 生成
        report = generate_kpi_report(
            month_key=month_key,
            month_pnl=month_summary,
            yearly_pnl=yearly_summary,
            weekly_pnl=weekly,
            pnl_summary=yearly_summary,
            spread=spread,
            conversion_total=signal_total,
            conversion_filled=signal_filled,
            drawdown_series=drawdown_series,
        )

        # 写入文件
        kpi_filename = f"kpi_{month_key}.md"
        kpi_path = REPORTS_DIR / kpi_filename

        tmp = kpi_path.with_suffix(".md.tmp")
        tmp.write_text(report, encoding="utf-8")
        tmp.rename(kpi_path)

        logger.info(f"[StrategyKPI] KPI看板已写入: {kpi_path}")
        return kpi_path

    except Exception as e:
        logger.error(f"[StrategyKPI] KPI生成异常: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        conn.close()

def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="生成策略KPI看板")
    parser.add_argument("--month", type=str, default=None, help="月份 YYYY-MM，默认当前月")
    parser.add_argument("--db-path", type=str, default=DB_PATH, help="数据库路径")
    parser.add_argument("--account-id", type=str, default=None, help="账户ID过滤")
    parser.add_argument("--verbose", action="store_true", help="详细输出")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    result = generate_strategy_kpi(month_key=args.month, db_path=args.db_path,
                                    account_id=args.account_id)
    if result:
        print(f"[OK] KPI看板已生成: {result}")
        return 0
    else:
        print(f"[FAIL] KPI看板生成失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
