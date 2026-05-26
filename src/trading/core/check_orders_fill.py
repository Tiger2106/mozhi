#!/usr/bin/env python3
"""
check_orders_fill.py - Rebuilt clean version
Multi-account order fill check at 19:00 settlement
"""
import argparse
import json
import os
import sys
import sqlite3
import traceback
from datetime import datetime, timezone, timedelta

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPT_DIR)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from src.config import SHANGHAI_TZ as CST_TZ
except ImportError:
    CST_TZ = timezone(timedelta(hours=8))

TZ_CST = CST_TZ
NOW = datetime.now(TZ_CST)
DATE_STR = NOW.strftime("%Y%m%d")
DATE_LABEL = NOW.strftime("%Y-%m-%d")

DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"
SIGNALS_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\paper_trade"
REPORTS_BASE = r"C:\Users\17699\mo_zhi_sharereports\reports"

ORDER_WINDOW_START = 8 * 60
ORDER_WINDOW_END = 19 * 60

ACCOUNT_IDS = ["acct_agg", "acct_bal", "acct_con",
               "acct_tech_trend", "acct_tech_reversal", "acct_tech_grid"]

ACCOUNT_DISPLAY = {
    "acct_agg": "Aggressive(AGGRESSIVE)",
    "acct_bal": "Balanced(BALANCED)",
    "acct_con": "Conservative(CONSERVATIVE)",
    "acct_tech_trend": "TechTrend(TECH_TREND)",
    "acct_tech_reversal": "TechReversal(TECH_REVERSAL)",
    "acct_tech_grid": "TechGrid(TECH_GRID)",
}

ACCOUNT_CAPITAL = {
    "acct_agg": 100000.0,
    "acct_bal": 100000.0,
    "acct_con": 100000.0,
    "acct_tech_trend": 100000.0,
    "acct_tech_reversal": 100000.0,
    "acct_tech_grid": 100000.0,
}

def parse_trade_time(trade_time_str):
    """Parse trade_time field to datetime. Assume +08:00 if no tz."""
    if not trade_time_str:
        return None
    try:
        trade_time_str = str(trade_time_str).strip()
        if trade_time_str.endswith('Z'):
            dt = datetime.fromisoformat(trade_time_str.replace('Z', '+00:00'))
        elif '+' not in trade_time_str and '-' not in trade_time_str[10:]:
            dt = datetime.fromisoformat(trade_time_str).replace(tzinfo=TZ_CST)
        else:
            dt = datetime.fromisoformat(trade_time_str)
        return dt.astimezone(TZ_CST)
    except (ValueError, TypeError):
        return None

def is_in_order_window(trade_time_str):
    """Check if order time is within valid window 08:00-19:00 CST."""
    dt = parse_trade_time(trade_time_str)
    if dt is None:
        return False, "INVALID_TIME"
    minutes = dt.hour * 60 + dt.minute
    if minutes < ORDER_WINDOW_START:
        return False, "BEFORE_WINDOW(" + dt.strftime('%H:%M') + " < 08:00)"
    if minutes > ORDER_WINDOW_END:
        return False, "AFTER_WINDOW(" + dt.strftime('%H:%M') + " > 19:00)"
    return True, "OK"

def get_account_orders_raw(account_id):
    """Query transactions for account from trade_engine.db"""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM transactions WHERE account_id = ?", (account_id,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"[check_orders_fill] DB query error: {e}")
        return []

def get_account_balance(account_id):
    """Get latest balance for account."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM account_balance WHERE account_id = ? ORDER BY id DESC LIMIT 1",
            (account_id,)
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return None
        return dict(row)
    except Exception:
        return None

def build_report(account_id):
    """Build settlement report for given account."""
    display_name = ACCOUNT_DISPLAY.get(account_id, account_id)
    initial_capital = ACCOUNT_CAPITAL.get(account_id, 0.0)

    if not os.path.exists(DB_PATH):
        return {
            "status": "ERROR",
            "account_id": account_id,
            "account_name": display_name,
            "error": "DB path not found: " + DB_PATH,
        }

    raw_orders = get_account_orders_raw(account_id)
    if not raw_orders:
        return {
            "status": "NO_ORDERS",
            "account_id": account_id,
            "account_name": display_name,
            "total_orders": 0,
        }

    balance = get_account_balance(account_id)
    cash_balance = balance.get("cash_balance", 0.0) if balance else 0.0

    valid_orders = []
    invalid_window_orders = 0
    total_filled = 0
    total_pending = 0
    total_frozen = 0
    total_rolled_back = 0
    total_rejected = 0
    all_filled = True
    ghost_frozen_accounts = 0

    for d in raw_orders:
        status = str(d.get("status", "UNKNOWN")).upper()
        qty = int(d.get("quantity", 1))
        price = float(d.get("price", 0.0))

        # In transactions table, filled quantity equals ordered quantity
        is_filled = (status in ("FILLED", "EXECUTED", "DONE"))

        time_valid, time_note = is_in_order_window(d.get("trade_time", ""))

        if not time_valid:
            invalid_window_orders += 1

        if is_filled:
            total_filled += 1
        elif status == "FROZEN":
            total_frozen += 1
            all_filled = False
        elif status == "ROLLED_BACK":
            total_rolled_back += 1
            all_filled = False
        elif status == "PENDING":
            all_filled = False
            total_pending += 1
        elif status in ("REJECTED", "CANCELED"):
            total_rejected += 1

        valid_orders.append({
            "order_id": d.get("order_id", ""),
            "symbol": d.get("symbol", ""),
            "action": d.get("action", "BUY_TO_OPEN"),
            "price": price,
            "quantity": qty,
            "status": status,
            "filled": is_filled,
            "filled_quantity": qty if is_filled else 0,
            "cost": round(price * qty, 2) if is_filled else 0.0,
            "position_id": d.get("position_id"),
            "trade_time": d.get("trade_time", ""),
            "notes": d.get("notes", ""),
            "time_window_valid": time_valid,
            "time_window_note": time_note,
        })

    total_orders = len(valid_orders)
    total_capital_used = round(initial_capital - cash_balance, 2)

    report = {
        "status": "READY",
        "report_type": "19:00_settlement_check",
        "generated_at": NOW.isoformat(),
        "account_id": account_id,
        "account_name": display_name,
        "date": DATE_STR,
        "initial_capital": round(initial_capital, 2),
        "cash_balance": round(cash_balance, 2),
        "total_capital_used": total_capital_used,
        "total_orders": total_orders,
        "summary": {
            "all_filled": all_filled,
            "total_filled": total_filled,
            "total_pending": total_pending,
            "total_frozen": total_frozen,
            "total_rolled_back": total_rolled_back,
            "total_rejected": total_rejected,
            "invalid_window_orders": invalid_window_orders,
            "ghost_frozen_accounts": ghost_frozen_accounts,
        },
        "orders": valid_orders,
    }
    return report

def write_report(account_id, report):
    """Write individual settlement report."""
    report_date = DATE_STR
    report_dir = os.path.join(REPORTS_BASE, "settlement", report_date)
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir,
                               f"settlement_{account_id}_{report_date}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[check_orders_fill] {account_id}: Report -> {report_path}")
    return report_path

def main(mode="check_only"):
    """Main entry: iterate all accounts and check/settle."""
    errors = 0
    all_reports = {}
    all_filled = True

    for account_id in ACCOUNT_IDS:
        report = build_report(account_id=account_id)
        status = report.get("status")

        if status == "ERROR":
            print(f"[check_orders_fill] {account_id}: ERROR - {report.get('error')}")
            errors += 1
            continue
        elif status == "NO_ORDERS":
            print(f"[check_orders_fill] {account_id}: No orders found")
            report_path = write_report(account_id, report)
            all_reports[account_id] = report
            continue

        report_path = write_report(account_id, report)
        all_reports[account_id] = report

        summary = report.get("summary", {})
        if not summary.get("all_filled", False):
            all_filled = False

        print(f"[check_orders_fill] {account_id}: "
              f"Orders={report['total_orders']} "
              f"Filled={summary.get('total_filled', 0)} "
              f"Pending={summary.get('total_pending', 0)} "
              f"Frozen={summary.get('total_frozen', 0)} "
              f"RolledBack={summary.get('total_rolled_back', 0)}")

        if summary.get("invalid_window_orders", 0) > 0:
            print(f"[WARNING] {summary['invalid_window_orders']} orders outside 08:00-19:00 window")

        if summary.get("ghost_frozen_accounts", 0) > 0:
            print(f"[WARNING] {summary['ghost_frozen_accounts']} accounts with ghost frozen (ROLLED_BACK not cleared)")

    if mode == "full":
        if errors > 0:
            print(f"\n[check_orders_fill] {errors} account(s) had errors, skipping settlement")
            return 1

        print("\n[check_orders_fill] All reports done. Running run_settlement()...")
        from trading.core.run_settlement import run_settlement
        result = run_settlement()
        if result.get("status") == "VERIFIED":
            summary = result.get("summary", {})
            print(f"[check_orders_fill] Settlement verified: "
                  f"accounts={summary.get('accounts_checked', 0)} "
                  f"skipped={summary.get('accounts_skipped', 0)} "
                  f"fixes={summary.get('formula_fixes', 0)}")
            ghost_frozen = summary.get("ghost_frozen_warnings", [])
            if ghost_frozen:
                print(f"[VERIFY_WARNING] Ghost frozen: {ghost_frozen}")
            errors_list = summary.get("errors", [])
            if errors_list:
                print(f"[VERIFY_WARNING] Verify errors: {errors_list}")
                return 1
        else:
            print(f"[VERIFY_FAIL] Verify failed: {result.get('error', 'Unknown error')}")
            return 1

    elif mode == "verify":
        print("\n[check_orders_fill] --mode=verify: verification mode")
        from trading.core.run_settlement import run_settlement
        result = run_settlement()
        if result.get("status") == "VERIFIED":
            summary = result.get("summary", {})
            print(f"[check_orders_fill] Settlement verified OK: "
                  f"accounts={summary.get('accounts_checked', 0)}")
            ghost_frozen = summary.get("ghost_frozen_warnings", [])
            if ghost_frozen:
                print(f"[VERIFY_WARNING] Ghost frozen: {ghost_frozen}")
            errors_list = summary.get("errors", [])
            if errors_list:
                print(f"[VERIFY_WARNING] Verify errors: {errors_list}")
                return 1
        else:
            print(f"[VERIFY_FAIL] Verify failed: {result.get('error', 'Unknown error')}")
            return 1

    elif mode == "check_only":
        print("\n[check_orders_fill] --mode=check_only: check only, skip settlement")

    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-account order fill check (19:00)")
    parser.add_argument("--mode",
                        choices=["check_only", "full", "verify"],
                        default="check_only",
                        help="check_only | full | verify")
    args = parser.parse_args()
    sys.exit(main(mode=args.mode))
