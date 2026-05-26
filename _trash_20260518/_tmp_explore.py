import sqlite3
conn = sqlite3.connect("data/knowledge.db")
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", cur.fetchall())

cur.execute("PRAGMA table_info(backtest_runs)")
print("backtest_runs cols:", cur.fetchall())

cur.execute("SELECT COUNT(*) FROM backtest_runs")
print("Count:", cur.fetchone()[0])

cur.execute("SELECT * FROM backtest_runs LIMIT 2")
rows = cur.fetchall()
print("Samples:")
for r in rows:
    print(" ", r)

# Check knowledge_entries too
cur.execute("PRAGMA table_info(knowledge_entries)")
print("knowledge_entries cols:", cur.fetchall())

cur.execute("SELECT COUNT(*) FROM knowledge_entries")
print("knowledge_entries count:", cur.fetchone()[0])

conn.close()
