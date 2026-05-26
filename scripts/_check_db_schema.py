#!/usr/bin/env python3
"""Check analysis.db schema"""
import sqlite3
from pathlib import Path

db_path = Path.home() / "mo_zhi_sharereports" / "analysis.db"
print(f"DB: {db_path}")
conn = sqlite3.connect(str(db_path))

# List tables
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print(f"\nTables: {tables}")

# Show schema for each table
for t in tables:
    cur = conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{t}'")
    sql = cur.fetchone()
    if sql:
        print(f"\n--- {t} ---")
        print(sql[0])

# Show record count per table
print("\n--- Record counts ---")
for t in tables:
    cur = conn.execute(f"SELECT COUNT(*) FROM {t}")
    cnt = cur.fetchone()[0]
    print(f"  {t}: {cnt} rows")

conn.close()
