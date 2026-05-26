#!/usr/bin/env python3
"""查询结算后账户数据"""
import sqlite3
from datetime import datetime, timezone, timedelta
from src.config import SHANGHAI_TZ

TZ_CST = SHANGHAI_TZ
now = datetime.now(TZ_CST)
db = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== 账户余额 ===")
for aid in ["acct_agg","acct_bal","acct_con","acct_tech_trend","acct_tech_reversal","acct_tech_grid"]:
    cur.execute("SELECT total_assets, available_balance, frozen_amount, position_market_value, realized_pnl, initial_capital, updated_at FROM account_balance WHERE account_id = ? ORDER BY id DESC LIMIT 1", (aid,))
    r = cur.fetchone()
    if r:
        print(f"  {aid}: 总资产={r[0]:.2f} 可用={r[1]:.2f} 冻结={r[2]:.2f} 持仓市值={r[3]:.2f} 已实现盈亏={r[4]:.2f} 初始资金={r[5]:.2f}")

print()
print("=== OPEN 持仓 ===")
cur.execute("SELECT account_id, symbol, direction, quantity, current_price, avg_price, unrealized_pnl, realized_pnl FROM positions WHERE status='OPEN'")
for p in cur.fetchall():
    print(f"  {p[0]}: {p[1]} {p[2]} x{p[3]} @{p[4]:.4f} avg={p[5]:.4f} unrlz={p[6]:.2f} rlz={p[7]:.2f}")

print()
print("=== transactions 表结构 ===")
cur.execute("PRAGMA table_info(transactions)")
for c in cur.fetchall():
    print(f"  {c[1]} ({c[2]})")

today = now.strftime("%Y-%m-%d")
print()
print(f"=== 今日交易 ({today}) ===")
# Try different date columns
for col in ["trade_time", "created_at", "updated_at"]:
    cur.execute(f"SELECT COUNT(*) FROM transactions")
    total = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM transactions WHERE DATE({col}) = ?", (today,))
    cnt = cur.fetchone()[0]
    print(f"  {col}: {cnt}/{total} today")

# Get columns dynamically
cur.execute("PRAGMA table_info(transactions)")
cols = [c[1] for c in cur.fetchall()]
date_cols = [c for c in cols if "time" in c or "date" in c or "at" in c]
print(f"  时间相关列: {date_cols}")

# Use first available date column
if date_cols:
    dc = date_cols[0]
    cur.execute(f"SELECT * FROM transactions WHERE DATE({dc}) = ? ORDER BY id", (today,))
    txns = cur.fetchall()
    if txns:
        for t in txns:
            d = dict(t)
            print(f"  {d}")
    else:
        print("  今日无交易")

conn.close()
