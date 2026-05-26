#!/usr/bin/env python3
from src.config import SHANGHAI_TZ
"""结算报告生成器 — 运行 run_settlement 后输出摘要"""
import json
import sys
from datetime import datetime, timezone, timedelta

TZ_CST = SHANGHAI_TZ
DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"
ACCOUNT_IDS = [
    "acct_agg", "acct_bal", "acct_con",
    "acct_tech_trend", "acct_tech_reversal", "acct_tech_grid",
]

def main():
    # Run settlement first
    sys.path.insert(0, r"C:\Users\17699\mozhi_platform")
    from trading.core.run_settlement import run_settlement
    result = run_settlement(mode="full")
    
    # Query DB for report
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    now = datetime.now(TZ_CST)
    report = {
        "timestamp": now.isoformat(),
        "settlement_status": result["status"],
        "accounts": {},
        "positions_summary": {},
        "today_transactions": [],
    }
    
    # Accounts
    for aid in ACCOUNT_IDS:
        cur.execute("""
            SELECT total_assets, available_balance, frozen_amount,
                   position_market_value, realized_pnl, initial_capital,
                   loss_streak, updated_at
            FROM account_balance WHERE account_id = ? ORDER BY id DESC LIMIT 1
        """, (aid,))
        r = cur.fetchone()
        if r:
            report["accounts"][aid] = {
                "total_assets": r["total_assets"],
                "available_balance": r["available_balance"],
                "frozen_amount": r["frozen_amount"],
                "position_market_value": r["position_market_value"],
                "realized_pnl": r["realized_pnl"],
                "initial_capital": r["initial_capital"],
                "loss_streak": r["loss_streak"],
                "updated_at": r["updated_at"],
            }
    
    # Positions
    cur.execute("SELECT account_id, COUNT(*) as cnt FROM positions WHERE status='OPEN' GROUP BY account_id")
    for r in cur.fetchall():
        report["positions_summary"][r["account_id"]] = {"open_positions": r["cnt"]}
    
    cur.execute("SELECT account_id, symbol, direction, quantity, current_price, avg_price, unrealized_pnl, realized_pnl, status FROM positions ORDER BY account_id, symbol")
    for p in cur.fetchall():
        aid = p["account_id"]
        if aid not in report["positions_summary"]:
            report["positions_summary"][aid] = {"open_positions": 0}
        if "positions" not in report["positions_summary"][aid]:
            report["positions_summary"][aid]["positions"] = []
        report["positions_summary"][aid]["positions"].append({
            "symbol": p["symbol"],
            "direction": p["direction"],
            "quantity": p["quantity"],
            "avg_price": p["avg_price"],
            "current_price": p["current_price"],
            "unrealized_pnl": p["unrealized_pnl"],
            "realized_pnl": p["realized_pnl"],
            "status": p["status"],
        })
    
    # Today's transactions
    today = now.strftime("%Y-%m-%d")
    cur.execute("""
        SELECT t.order_id, t.account_id, t.symbol, t.action, t.quantity, t.price, t.status, t.created_at
        FROM transactions t
        WHERE DATE(t.created_at) = ?
        ORDER BY t.created_at
    """, (today,))
    for t in cur.fetchall():
        report["today_transactions"].append({
            "time": t["created_at"],
            "account": t["account_id"],
            "symbol": t["symbol"],
            "action": t["action"],
            "quantity": t["quantity"],
            "price": t["price"],
            "status": t["status"],
        })
    
    conn.close()
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
