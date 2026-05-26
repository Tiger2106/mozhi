"""Debug: test akshare and check unique symbols."""
from src.backtest.pipeline.knowledge_db import KnowledgeDB

kdb = KnowledgeDB()
kdb.initialize()
with kdb._conn() as c:
    rows = c.execute(
        "SELECT DISTINCT r.symbol, MIN(r.end_date) as first_date, MAX(r.end_date) as last_date, COUNT(*) as cnt "
        "FROM backtest_runs r LEFT JOIN market_context mc ON r.run_id = mc.run_id "
        "WHERE mc.run_id IS NULL GROUP BY r.symbol ORDER BY cnt DESC"
    ).fetchall()
    
    print(f"Unique symbols without market_context: {len(rows)}")
    for r in rows[:10]:
        print(f"  {r['symbol']}: {r['cnt']} runs, {r['first_date']} -> {r['last_date']}")
    
    # Also count total unique symbols overall
    total = c.execute("SELECT COUNT(DISTINCT symbol) FROM backtest_runs").fetchone()
    print(f"Total unique symbols: {total[0]}")

# Test akshare
print("\nTesting akshare for 601857.SH...")
import time
t0 = time.time()
ctx = KnowledgeDB._estimate_market_regime("601857.SH", "20260515")
elapsed = time.time() - t0
print(f"Result: {ctx}")
print(f"Took: {elapsed:.1f}s")

kdb.close()
