"""Run market_context backfill."""
import sys
import time
from src.backtest.pipeline.knowledge_db import KnowledgeDB

kdb = KnowledgeDB()
kdb.initialize()
print("Starting backfill...")
t0 = time.time()
filled = kdb.backfill_market_context()
elapsed = time.time() - t0
print(f"FILLED: {filled} market contexts in {elapsed:.1f}s")
kdb.close()
