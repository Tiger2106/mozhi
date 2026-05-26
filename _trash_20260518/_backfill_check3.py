"""Check notes/data_source in market_context."""
from src.backtest.pipeline.knowledge_db import KnowledgeDB
import json

kdb = KnowledgeDB()
kdb.initialize()
with kdb._conn() as c:
    rows = c.execute("SELECT run_id, market_regime, notes, created_at FROM market_context LIMIT 5").fetchall()
    print("First 5 market_context records:")
    for r in rows:
        try:
            notes = json.loads(r['notes'])
        except (json.JSONDecodeError, TypeError):
            notes = r['notes']
        print(f"  {r['run_id'][:50]}: regime={r['market_regime']}, "
              f"notes={notes}, created={r['created_at']}")

    # Check how many have old akshare data_source (from the first run)
    all_notes = c.execute("SELECT notes FROM market_context").fetchall()
    akshare_count = 0
    pickle_count = 0
    for r in all_notes:
        try:
            n = json.loads(r['notes'])
            if n.get('data_source') == 'akshare':
                akshare_count += 1
            else:
                pickle_count += 1
        except:
            pickle_count += 1
    print(f"\nAkshare sourced: {akshare_count}")
    print(f"Other/pickle: {pickle_count}")

    # When were these created?
    times = c.execute("SELECT DISTINCT created_at FROM market_context").fetchall()
    print(f"\nDistinct created_at values:")
    for t in times[:10]:
        print(f"  {t['created_at']}")

kdb.close()
