"""Check current state after second backfill attempt."""
from src.backtest.pipeline.knowledge_db import KnowledgeDB
import time

kdb = KnowledgeDB()
kdb.initialize()

with kdb._conn() as c:
    total = c.execute("SELECT COUNT(*) as n FROM market_context").fetchone()
    print(f"Total market_context: {total['n']}")
    need = c.execute(
        "SELECT COUNT(*) as n FROM backtest_runs r "
        "LEFT JOIN market_context mc ON r.run_id=mc.run_id "
        "WHERE mc.run_id IS NULL"
    ).fetchone()
    print(f"Still need backfill: {need['n']}")

    # What symbols are missing?
    missing = c.execute(
        "SELECT r.symbol, COUNT(*) as n FROM backtest_runs r "
        "LEFT JOIN market_context mc ON r.run_id=mc.run_id "
        "WHERE mc.run_id IS NULL GROUP BY r.symbol"
    ).fetchall()
    for m in missing:
        print(f"  Symbol {m['symbol']}: {m['n']} runs missing")

kdb.close()
