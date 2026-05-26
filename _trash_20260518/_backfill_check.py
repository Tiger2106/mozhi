"""Check DB state before backfill."""
from src.backtest.pipeline.knowledge_db import KnowledgeDB

kdb = KnowledgeDB()
kdb.initialize()
with kdb._conn() as c:
    cnt = c.execute("SELECT COUNT(*) as n FROM backtest_runs").fetchone()
    print(f"Backtest runs: {cnt['n']}")
    cnt2 = c.execute("SELECT COUNT(*) as n FROM market_context").fetchone()
    print(f"Market context records: {cnt2['n']}")
kdb.close()
