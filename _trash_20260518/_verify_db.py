"""Verify knowledge.db tables exist and initialize if needed."""
from backtest.pipeline.knowledge_db import KnowledgeDB
import sqlite3

kdb = KnowledgeDB()
kdb.initialize()
print("DB initialized successfully")

# Verify tables exist
conn = sqlite3.connect(kdb.db_path)
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cur.fetchall()]
print("Tables:", tables)
print("backtest_equity_series exists:", "backtest_equity_series" in tables)
print("backtest_trades exists:", "backtest_trades" in tables)

# Count existing records
if "backtest_equity_series" in tables:
    cur = conn.execute("SELECT COUNT(*) FROM backtest_equity_series")
    print(f"Existing equity records: {cur.fetchone()[0]}")

if "backtest_trades" in tables:
    cur = conn.execute("SELECT COUNT(*) FROM backtest_trades")
    print(f"Existing trade records: {cur.fetchone()[0]}")

conn.close()
