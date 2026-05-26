"""Check market_context state."""
from src.backtest.pipeline.knowledge_db import KnowledgeDB

kdb = KnowledgeDB()
kdb.initialize()
with kdb._conn() as c:
    rows = c.execute(
        "SELECT market_regime, COUNT(*) as n FROM market_context GROUP BY market_regime"
    ).fetchall()
    print("Market context by regime:")
    for r in rows:
        print(f"  {r['market_regime']}: {r['n']}")

    syms = c.execute("SELECT DISTINCT symbol FROM market_context").fetchall()
    print(f"Unique symbols in market_context: {[s['symbol'] for s in syms]}")

    need = c.execute(
        "SELECT COUNT(*) as n FROM backtest_runs r "
        "LEFT JOIN market_context mc ON r.run_id=mc.run_id "
        "WHERE mc.run_id IS NULL"
    ).fetchone()
    print(f"Runs still needing backfill: {need['n']}")

kdb.close()
