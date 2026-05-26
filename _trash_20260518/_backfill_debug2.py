"""Debug backfill using a real run_id."""
import sys
print("Starting debug...", flush=True)

from src.backtest.pipeline.knowledge_db import KnowledgeDB
import time

kdb = KnowledgeDB()
kdb.initialize()
print("DB initialized", flush=True)

# Get a real run_id
with kdb._conn() as c:
    row = c.execute("SELECT run_id, symbol, end_date FROM backtest_runs WHERE symbol='601857' LIMIT 1").fetchone()
    if row is None:
        row = c.execute("SELECT run_id, symbol, end_date FROM backtest_runs LIMIT 1").fetchone()
    print(f"Using: run_id={row['run_id']}, symbol={row['symbol']}, end_date={row['end_date']}", flush=True)

# Test single market context store for a real run
ctx = KnowledgeDB._estimate_market_regime(row['symbol'], row['end_date'][:8])
print(f"Context: {ctx}", flush=True)

success = kdb.store_market_context(row['run_id'], ctx)
print(f"Store success: {success}", flush=True)

# Verify
with kdb._conn() as c:
    cnt = c.execute("SELECT COUNT(*) as n FROM market_context").fetchone()
    print(f"Market context after test: {cnt['n']}", flush=True)
    cnt2 = c.execute("SELECT COUNT(*) as n FROM market_context WHERE run_id=?", (row['run_id'],)).fetchone()
    print(f"Records for this run_id: {cnt2['n']}", flush=True)
    # Show one record
    mc = c.execute("SELECT * FROM market_context LIMIT 1").fetchone()
    if mc:
        print(f"Market context record:", flush=True)
        for k in mc.keys():
            print(f"  {k}: {mc[k]}", flush=True)
    
kdb.close()
print("Done", flush=True)
