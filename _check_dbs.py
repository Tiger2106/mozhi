#!/usr/bin/env python3
"""Check all analysis.db instances and market_data.db"""
import sqlite3
import os

paths = [
    r'C:\Users\17699\mo_zhi_sharereports\analysis.db',
    r'C:\Users\17699\mozhi_platform\data\db\analysis.db',
    r'C:\Users\17699\mozhi_platform\data\market\market_data.db',
    r'C:\Users\17699\mozhi_platform\automation_v2\analysis.db',
]

for path in paths:
    print(f"\n{'='*60}")
    print(f"PATH: {path}")
    if not os.path.exists(path):
        print("  NOT FOUND")
        continue
    size = os.path.getsize(path)
    print(f"  SIZE: {size:,} bytes")
    try:
        conn = sqlite3.connect(path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        print(f"  TABLES ({len(tables)}): {tables}")
        for t in tables:
            cur2 = conn.execute(f"SELECT COUNT(*) FROM \"{t}\"")
            cnt = cur2.fetchone()[0]
            print(f"    - {t}: {cnt:,} rows")
        conn.close()
    except Exception as e:
        print(f"  ERROR: {e}")
