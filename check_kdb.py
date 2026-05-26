"""Check KnowledgeDB schema and stock prices"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from backtest.pipeline.knowledge_db import KnowledgeDB

kdb = KnowledgeDB()

# Check tables
tables = kdb._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t['name'] for t in tables])

# Check schema for strategy_runs
cols = kdb._conn.execute("PRAGMA table_info(strategy_runs)").fetchall()
print("\nstrategy_runs columns:")
for c in cols:
    print(f"  {c['name']:20s} {c['type']:15s} {c['notnull']}")

# Check performance_results table if exists
if any(t['name'] == 'performance_results' for t in tables):
    cols2 = kdb._conn.execute("PRAGMA table_info(performance_results)").fetchall()
    print("\nperformance_results columns:")
    for c in cols2:
        print(f"  {c['name']:25s} {c['type']:15s} {c['notnull']}")
    
    # Check profit_factor values
    rows = kdb._conn.execute("""
        SELECT strategy, config_key, symbol, profit_factor, total_return_pct,
               sharpe, max_drawdown_pct
        FROM performance_results
        WHERE profit_factor > 0
        ORDER BY created_at DESC
        LIMIT 10
    """).fetchall()
    print(f"\nprofit_factor > 0 records: {len(rows)}")
    for r in rows:
        print(f"  {r['strategy']:12s} {str(r['config_key'] or ''):40s} {r['symbol']:12s} {r['profit_factor']:.4f}")

# Check get_performance method
print("\nget_performance doc:")
help(kdb.get_performance)

kdb.close()
