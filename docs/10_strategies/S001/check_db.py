import os, sqlite3

db_path = r'C:\Users\17699\mozhi_platform\market_data.db'
analysis_path = r'C:\Users\17699\analysis.db'

# Check current data table schema
for path, label in [(db_path, 'market_data.db'), (analysis_path, 'analysis.db')]:
    if os.path.exists(path):
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cur.fetchall()
        print(f"=== {label} ===")
        for t in tables:
            tname = t[0]
            cur.execute(f"PRAGMA table_info({tname})")
            cols = cur.fetchall()
            print(f"  Table: {tname} ({len(cols)} cols)")
            for c in cols:
                print(f"    {c[1]} ({c[2]})")
            # Sample a row
            cur.execute(f"SELECT * FROM {tname} LIMIT 1")
            row = cur.fetchone()
            if row:
                print(f"    Sample: {row}")
            print()
        conn.close()
    else:
        print(f"{label}: not found")
