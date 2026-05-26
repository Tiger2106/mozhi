"""Check data/analysis.db (A0)"""
import sqlite3, os

p = r'C:\Users\17699\mozhi_platform\data\analysis.db'
print(f"PATH: {p}")
if not os.path.exists(p):
    print("  NOT FOUND")
else:
    s = os.path.getsize(p)
    print(f"  SIZE: {s:,} bytes")
    conn = sqlite3.connect(p)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print(f"  TABLES ({len(tables)}): {tables}")
    for t in tables:
        cnt = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"    - {t}: {cnt:,} rows")
    conn.close()
