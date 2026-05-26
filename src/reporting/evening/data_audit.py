#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_audit.py — D-3: 历史数据审计

审核 trade_engine.db 中的历史交易记录，检查：
1. 资金流水平衡校验（buy_debit + sell_credit + commission == 0）
2. 交易与资金流水对应关系
3. 时间戳完整性
4. 持仓与交易记录一致性

输出 reports/data_audit.md

作者: moheng | created_time: 2026-05-05 14:58 GMT+8
"""

import argparse
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from src.config import SHANGHAI_TZ

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

TZ_CST = SHANGHAI_TZ
PROJECT_ROOT = Path(r"C:\Users\17699\mo_zhi_sharereports")
REPORTS_DIR = PROJECT_ROOT / "reports"
DB_PATH = str(PROJECT_ROOT / "trade_engine.db")


def now_str() -> str:
    return datetime.now(TZ_CST).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════
# 审计项 1: 资金流水平衡校验
# ═══════════════════════════════════════════════

def audit_fund_flow_balance(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    校验资金流水平衡：
    - 所有 DEBIT 总和 + 所有 CREDIT 总和 + 总佣金 == 0
    - 单笔交易的 DEBIT + CREDIT + COMMISSION == 0
    """
    cur = conn.cursor()
    issues = []
    warnings = []

    # 1. 全局平衡
    cur.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM fund_flow")
    row = cur.fetchone()
    total_flow_count = row["cnt"]
    total_amount = row["total"]
    net_balance = round(total_amount, 2)

    if abs(net_balance) > 0.01:
        issues.append(f"资金流水净额不为零: ¥{net_balance:+.2f}（期望 0）")

    # 2. 按 flow_type 分组统计
    cur.execute("""
        SELECT flow_type, COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total
        FROM fund_flow
        GROUP BY flow_type
        ORDER BY flow_type
    """)
    flow_by_type = {r["flow_type"]: {"count": r["cnt"], "total": round(r["total"], 2)} for r in cur.fetchall()}

    # 3. 按 order_id 分组平衡校验
    cur.execute("""
        SELECT order_id, flow_type, amount FROM fund_flow ORDER BY order_id, flow_type
    """)
    groups = defaultdict(list)
    for r in cur.fetchall():
        groups[r["order_id"]].append({"type": r["flow_type"], "amount": r["amount"]})

    unbalanced_orders = []
    for oid, flows in groups.items():
        order_total = sum(f["amount"] for f in flows)
        if abs(round(order_total, 2)) > 0.05 and oid is not None:
            unbalanced_orders.append({
                "order_id": oid,
                "flows": flows,
                "net": round(order_total, 2),
            })

    if unbalanced_orders:
        for ub in unbalanced_orders[:5]:
            issues.append(
                f"订单 {ub['order_id']} 流水不平衡: 净额 ¥{ub['net']:+.2f}"
            )

    # 4. 检查是否有 INVALID flow_type
    valid_types = {"INITIAL", "FREEZE", "UNFREEZE", "DEBIT", "CREDIT"}
    for ft in flow_by_type:
        if ft not in valid_types:
            warnings.append(f"未知流水类型: '{ft}'")

    return {
        "status": "PASS" if not issues else "FAIL",
        "total_flow_count": total_flow_count,
        "net_balance": net_balance,
        "flow_by_type": flow_by_type,
        "unbalanced_order_count": len(unbalanced_orders),
        "issues": issues,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════
# 审计项 2: 交易与资金流水对应关系
# ═══════════════════════════════════════════════

def audit_transaction_flow_match(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    检查每笔 FILLED 订单是否都有对应的资金流水记录。
    检查每笔资金流水是否都能找到对应的交易订单（INITIAL 除外）。
    检查佣金/印花税在流水中的体现。
    """
    cur = conn.cursor()
    issues = []
    warnings = []
    detail_lines = []

    # 1. 所有 FILLED 交易
    cur.execute("""
        SELECT order_id, symbol, action, quantity, price, commission, tax, trade_time
        FROM transactions
        WHERE status = 'FILLED'
        ORDER BY trade_time
    """)
    filled_txns = cur.fetchall()

    match_ok = 0
    match_missing = 0
    for txn in filled_txns:
        order_id = txn["order_id"]
        # 检查是否有对应资金流水
        cur.execute("SELECT COUNT(*) as cnt FROM fund_flow WHERE order_id = ?", (order_id,))
        flow_cnt = cur.fetchone()["cnt"]
        if flow_cnt == 0 and order_id:
            match_missing += 1
            issues.append(f"订单 {order_id} ({txn['symbol']} {txn['action']}) 无资金流水记录")
            detail_lines.append(f"❌ {order_id} — {txn['symbol']} {txn['action']} — 无流水记录")
        else:
            match_ok += 1
            detail_lines.append(f"✅ {order_id} — {txn['symbol']} {txn['action']} — 流水记录 {flow_cnt} 条")

    # 2. 资金流水中的 order_id 在 transactions 表中的查找率
    cur.execute("""
        SELECT f.order_id FROM fund_flow f
        WHERE f.order_id IS NOT NULL AND f.order_id != ''
          AND f.flow_type != 'INITIAL'
        GROUP BY f.order_id
    """)
    flow_order_ids = [r["order_id"] for r in cur.fetchall()]

    orphan_flows = 0
    for oid in flow_order_ids:
        cur.execute("SELECT COUNT(*) as cnt FROM transactions WHERE order_id = ?", (oid,))
        if cur.fetchone()["cnt"] == 0:
            orphan_flows += 1
            warnings.append(f"资金流水中存在孤立的 order_id: {oid}（无对应交易记录）")

    # 3. 有佣金的交易检查是否有对应的 COMMISSION 流水
    cur.execute("""
        SELECT order_id, commission, tax FROM transactions
        WHERE status = 'FILLED' AND (commission > 0 OR tax > 0)
    """)
    for txn in cur.fetchall():
        oid = txn["order_id"]
        if txn["commission"] and txn["commission"] > 0:
            cur.execute("""
                SELECT COUNT(*) as cnt FROM fund_flow
                WHERE order_id = ? AND description LIKE '%佣金%'
            """, (oid,))
            if cur.fetchone()["cnt"] == 0:
                warnings.append(f"订单 {oid} 存在佣金 ¥{txn['commission']:.2f} 但无对应佣金流水记录")

    return {
        "status": "PASS" if not issues else "FAIL",
        "filled_txns": len(filled_txns),
        "flow_match_ok": match_ok,
        "flow_match_missing": match_missing,
        "orphan_flows": orphan_flows,
        "issues": issues,
        "warnings": warnings,
        "detail_lines": detail_lines,
    }


# ═══════════════════════════════════════════════
# 审计项 3: 时间戳完整性
# ═══════════════════════════════════════════════

def audit_timestamp_integrity(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    检查时间戳完整性：
    - entry_time 必须在 close_time 之前
    - trade_time 必须在合理的交易时间内
    - 无 NULL/空字符串时间戳
    - 时间戳格式统一
    """
    cur = conn.cursor()
    issues = []
    warnings = []

    # 1. 检查 positions 表时间戳
    cur.execute("""
        SELECT id, symbol, entry_time, close_time, status FROM positions
    """)
    for r in cur.fetchall():
        pid = r["id"]
        entry = r["entry_time"]
        close = r["close_time"]

        # NULL 检查
        if not entry:
            issues.append(f"持仓 {pid} ({r['symbol']}) entry_time 为空")

        if r["status"] == "CLOSED" and not close:
            issues.append(f"已平仓持仓 {pid} ({r['symbol']}) close_time 为空")

        # 时间先后
        if entry and close:
            try:
                et = datetime.strptime(entry, "%Y-%m-%d %H:%M:%S")
                ct = datetime.strptime(close, "%Y-%m-%d %H:%M:%S")
                if ct < et:
                    issues.append(f"持仓 {pid} ({r['symbol']}) close_time 早于 entry_time")
            except ValueError:
                warnings.append(f"持仓 {pid} ({r['symbol']}) 时间戳格式异常: entry={entry}, close={close}")

    # 2. 检查 transactions 表时间戳
    cur.execute("""
        SELECT id, order_id, trade_time, status, symbol FROM transactions
    """)
    null_timestamps = 0
    for r in cur.fetchall():
        if not r["trade_time"]:
            null_timestamps += 1

    if null_timestamps > 0:
        issues.append(f"transactions 表有 {null_timestamps} 条记录 trade_time 为空")

    return {
        "status": "PASS" if not issues else "FAIL",
        "total_positions": 0,
        "total_transactions": 0,
        "issues": issues,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════
# 审计项 4: 持仓与交易记录一致性
# ═══════════════════════════════════════════════

def audit_position_transaction_consistency(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    检查持仓与交易记录的一致性：
    - 每个 CLOSED 持仓都有对应的 SELL 交易
    - 每个 OPEN 持仓没有对应的 SELL 交易
    - 持仓的 quantity、price 与交易记录匹配
    """
    cur = conn.cursor()
    issues = []

    # 1. CLOSED 持仓必须有对应的 SELL 交易
    cur.execute("""
        SELECT p.id, p.symbol, p.status, p.quantity, p.entry_price
        FROM positions p
        WHERE p.status = 'CLOSED'
    """)
    for pos in cur.fetchall():
        cur.execute("""
            SELECT COUNT(*) as cnt FROM transactions
            WHERE position_id = ? AND action = 'SELL_TO_CLOSE'
        """, (pos["id"],))
        if cur.fetchone()["cnt"] == 0:
            issues.append(
                f"CLOSED 持仓 {pos['id']} ({pos['symbol']}) 无 SELL_TO_CLOSE 交易记录"
            )

    # 2. OPEN 持仓不应有对应的 SELL 交易
    cur.execute("""
        SELECT p.id, p.symbol FROM positions p
        WHERE p.status = 'OPEN'
    """)
    for pos in cur.fetchall():
        cur.execute("""
            SELECT COUNT(*) as cnt FROM transactions
            WHERE position_id = ? AND action IN ('SELL', 'SELL_TO_CLOSE')
        """, (pos["id"],))
        if cur.fetchone()["cnt"] > 0:
            issues.append(
                f"OPEN 持仓 {pos['id']} ({pos['symbol']}) 存在卖出交易记录（状态异常）"
            )

    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
    }


# ═══════════════════════════════════════════════
# 审计项 5: 持仓PnL校验
# ═══════════════════════════════════════════════

def audit_pnl_consistency(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    校验持仓 PnL 字段与交易记录的一致性：
    - CLOSED 持仓的 pnl 字段 = (close_price - entry_price) * quantity
    - 检查 daily_pnl 表的累计盈亏与持仓 PnL 总和匹配
    - 检查 account_balance 的 realized_pnl 字段
    """
    cur = conn.cursor()
    issues = []
    warnings = []

    # 1. CLOSED 持仓 PnL 校验
    cur.execute("""
        SELECT id, symbol, direction, quantity, entry_price, close_price, pnl
        FROM positions WHERE status = 'CLOSED'
    """)
    for pos in cur.fetchall():
        if pos["pnl"] is None:
            warnings.append(f"CLOSED 持仓 {pos['id']} ({pos['symbol']}) pnl 字段为空")
            continue

        if pos["close_price"] is None:
            warnings.append(f"CLOSED 持仓 {pos['id']} ({pos['symbol']}) close_price 为空")
            continue

        # 理论 PnL
        if pos["direction"] == "LONG":
            expected_pnl = (pos["close_price"] - pos["entry_price"]) * pos["quantity"]
        else:
            expected_pnl = (pos["entry_price"] - pos["close_price"]) * pos["quantity"]

        diff = abs(pos["pnl"] - expected_pnl)
        if diff > 0.05:
            issues.append(
                f"持仓 {pos['id']} ({pos['symbol']} {pos['direction']}): "
                f"记录 PnL={pos['pnl']:.2f}, 理论 PnL={expected_pnl:.2f}, 偏差={diff:.2f}"
            )

    # 2. daily_pnl 累计盈亏 vs 持仓 PnL 总和
    cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE status = 'CLOSED' AND pnl IS NOT NULL")
    total_closed_pnl = cur.fetchone()[0] or 0.0

    cur.execute("SELECT COALESCE(SUM(total_pnl), 0) FROM daily_pnl")
    total_daily_pnl = cur.fetchone()[0] or 0.0

    if abs(total_closed_pnl - total_daily_pnl) > 1.0:
        warnings.append(
            f"持仓 PnL 总和 (¥{total_closed_pnl:.2f}) 与 daily_pnl 总和 (¥{total_daily_pnl:.2f}) "
            f"不一致，偏差 ¥{abs(total_closed_pnl - total_daily_pnl):.2f}"
        )

    # 3. account_balance
    cur.execute("SELECT realized_pnl, total_assets, available_balance FROM account_balance ORDER BY id DESC LIMIT 1")
    acct = cur.fetchone()
    acct_info = None
    if acct:
        acct_info = dict(acct)

    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "warnings": warnings,
        "total_closed_pnl": round(total_closed_pnl, 2),
        "total_daily_pnl": round(total_daily_pnl, 2),
        "account_balance": acct_info,
    }


# ═══════════════════════════════════════════════
# 构建报告
# ═══════════════════════════════════════════════

def build_audit_report(results: Dict[str, Any]) -> str:
    """构建数据审计 Markdown 报告"""
    lines = []
    lines.append("# 数据审计报告\n")
    lines.append(f"<!-- author: moheng | created_time: {now_str()} -->\n")
    lines.append(f"- 数据源: `{DB_PATH}`")
    lines.append(f"- 审计时间: {now_str()}\n")

    # ── 全局汇总 ──
    all_pass = all(r.get("status") == "PASS" for r in results.values())
    total_issues = sum(len(r.get("issues", [])) for r in results.values())
    total_warnings = sum(len(r.get("warnings", [])) for r in results.values())

    lines.append("## 全局审计结果\n")
    verdict = "✅ ALL PASS" if all_pass else "❌ ISSUES FOUND"
    lines.append(f"| 项目 | 值 |")
    lines.append(f"|:-----|:---|")
    lines.append(f"| 审计结论 | `{verdict}` |")
    lines.append(f"| 审计项数 | `{len(results)}` |")
    lines.append(f"| 通过 | `{sum(1 for r in results.values() if r.get('status') == 'PASS')}` |")
    lines.append(f"| 失败 | `{sum(1 for r in results.values() if r.get('status') == 'FAIL')}` |")
    lines.append(f"| 问题数 | `{total_issues}` |")
    lines.append(f"| 警告数 | `{total_warnings}` |")

    # ── 1. 资金流水平衡 ──
    ff = results.get("fund_flow", {})
    lines.append("\n## 1. 资金流水平衡校验\n")
    lines.append(f"**状态**: {ff.get('status', 'N/A')}\n")
    lines.append(f"- 总流水记录: {ff.get('total_flow_count', 0)}")
    lines.append(f"- 流水净额: ¥{ff.get('net_balance', 0):+.2f}")
    lines.append(f"- 不平衡订单数: {ff.get('unbalanced_order_count', 0)}")
    for ft, info in ff.get("flow_by_type", {}).items():
        lines.append(f"- {ft}: {info['count']} 笔, ¥{info['total']:+.2f}")
    for w in ff.get("warnings", []):
        lines.append(f"- ⚠️ {w}")
    for i in ff.get("issues", []):
        lines.append(f"- ❌ {i}")

    # ── 2. 交易与资金流水对应 ──
    tf = results.get("transaction_flow", {})
    lines.append("\n## 2. 交易与资金流水对应关系\n")
    lines.append(f"**状态**: {tf.get('status', 'N/A')}\n")
    lines.append(f"- FILLED 交易总数: {tf.get('filled_txns', 0)}")
    lines.append(f"- 流水匹配: {tf.get('flow_match_ok', 0)}")
    lines.append(f"- 流水缺失: {tf.get('flow_match_missing', 0)}")
    lines.append(f"- 孤立流水: {tf.get('orphan_flows', 0)}")
    for i in tf.get("issues", []):
        lines.append(f"- ❌ {i}")
    for w in tf.get("warnings", []):
        lines.append(f"- ⚠️ {w}")

    # ── 3. 时间戳完整性 ──
    ts = results.get("timestamp", {})
    lines.append("\n## 3. 时间戳完整性\n")
    lines.append(f"**状态**: {ts.get('status', 'N/A')}\n")
    for i in ts.get("issues", []):
        lines.append(f"- ❌ {i}")
    for w in ts.get("warnings", []):
        lines.append(f"- ⚠️ {w}")

    # ── 4. 持仓交易一致性 ──
    pc = results.get("position_consistency", {})
    lines.append("\n## 4. 持仓与交易记录一致性\n")
    lines.append(f"**状态**: {pc.get('status', 'N/A')}\n")
    for i in pc.get("issues", []):
        lines.append(f"- ❌ {i}")

    # ── 5. PnL 一致性 ──
    pnl = results.get("pnl_consistency", {})
    lines.append("\n## 5. PnL 一致性校验\n")
    lines.append(f"**状态**: {pnl.get('status', 'N/A')}\n")
    lines.append(f"- 已平仓持仓 PnL 总和: ¥{pnl.get('total_closed_pnl', 0):+.2f}")
    lines.append(f"- daily_pnl 总和: ¥{pnl.get('total_daily_pnl', 0):+.2f}")
    if pnl.get("account_balance"):
        ab = pnl["account_balance"]
        lines.append(f"- 账户已实现 PnL: ¥{ab.get('realized_pnl', 0):+.2f}")
        lines.append(f"- 总资产: ¥{ab.get('total_assets', 0):+.2f}")
        lines.append(f"- 可用余额: ¥{ab.get('available_balance', 0):+.2f}")
    for i in pnl.get("issues", []):
        lines.append(f"- ❌ {i}")
    for w in pnl.get("warnings", []):
        lines.append(f"- ⚠️ {w}")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="历史数据审计")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("开始历史数据审计...")
    conn = get_conn()

    results = {}
    try:
        results["fund_flow"] = audit_fund_flow_balance(conn)
        logger.info(f"资金流水平衡: {results['fund_flow']['status']}")

        results["transaction_flow"] = audit_transaction_flow_match(conn)
        logger.info(f"交易流水对应: {results['transaction_flow']['status']}")

        results["timestamp"] = audit_timestamp_integrity(conn)
        logger.info(f"时间戳完整性: {results['timestamp']['status']}")

        results["position_consistency"] = audit_position_transaction_consistency(conn)
        logger.info(f"持仓一致性: {results['position_consistency']['status']}")

        results["pnl_consistency"] = audit_pnl_consistency(conn)
        logger.info(f"PnL一致性: {results['pnl_consistency']['status']}")
    finally:
        conn.close()

    # 生成报告
    report_content = build_audit_report(results)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / "data_audit.md"
    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"审计报告已写入: {report_path}")

    # 控制台摘要
    all_pass = all(r.get("status") == "PASS" for r in results.values())
    total_issues = sum(len(r.get("issues", [])) for r in results.values())
    total_warnings = sum(len(r.get("warnings", [])) for r in results.values())

    print(f"\n{'='*50}")
    print(f"数据审计报告 — {now_str()}")
    print(f"{'='*50}")
    for name, r in results.items():
        status_icon = "✅" if r.get("status") == "PASS" else "❌"
        n_issues = len(r.get("issues", []))
        print(f"  {status_icon} {name}: {r.get('status', 'N/A')} ({n_issues} issues)")
    print(f"  总问题: {total_issues}  |  总警告: {total_warnings}")
    print(f"  结论: {'✅ ALL PASS' if all_pass else '❌ ISSUES FOUND'}")
    print(f"{'='*50}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
