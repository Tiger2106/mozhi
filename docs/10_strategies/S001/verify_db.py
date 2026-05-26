import os, sqlite3

# Verify the two databases
dbs = [
    (r'C:\Users\17699\mozhi_platform\data\market\market_data.db', 'market_data.db'),
    (r'C:\Users\17699\mozhi_platform\data\analysis.db', 'analysis.db'),
]

for path, label in dbs:
    if not os.path.exists(path):
        print(f"❌ {label}: NOT FOUND at {path}")
        continue
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cur.fetchall()
    print(f"=== {label} ({os.path.getsize(path)//1024} KB) ===")
    print(f"  Tables: {[t[0] for t in tables]}")
    for t in tables:
        tname = t[0]
        cur.execute(f"PRAGMA table_info({tname})")
        cols = cur.fetchall()
        print(f"  {tname}: {len(cols)} cols")
        for c in cols:
            print(f"    {c[1]} ({c[2]})")
        cur.execute(f"SELECT COUNT(*) FROM {tname}")
        cnt = cur.fetchone()[0]
        print(f"    Rows: {cnt}")
        # date range if date col exists
        for c in cols:
            if 'date' in c[1].lower():
                cur.execute(f"SELECT MIN({c[1]}), MAX({c[1]}) FROM {tname}")
                dr = cur.fetchone()
                print(f"    Date range: {dr[0]} ~ {dr[1]}")
                break
    conn.close()
    print()

# Also check stock_daily specifically in analysis.db
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\analysis.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_daily'")
if cur.fetchone():
    cur.execute("SELECT DISTINCT code FROM stock_daily ORDER BY code")
    codes = [r[0] for r in cur.fetchall()]
    print(f"stock_daily unique codes: {codes}")
    cur.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM stock_daily WHERE code='sh601857'")
    r = cur.fetchone()
    print(f"sh601857 in stock_daily: {r[0]} ~ {r[1]}, {r[2]} rows")
conn.close()

# Check market_data.db for 601857
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
for t in cur.fetchall():
    tname = t[0]
    cur.execute(f"PRAGMA table_info({tname})")
    cols = [c[1] for c in cur.fetchall()]
    print(f"\nmarket_data.{tname} columns: {cols}")
    cur.execute(f"SELECT COUNT(*) FROM {tname} LIMIT 1")
    print(f"  Has data: {cur.fetchone()[0] > 0}")
    # check for 601857
    for code_col in ['symbol', 'code', 'ts_code']:
        if code_col in cols:
            cur.execute(f"SELECT DISTINCT {code_col} FROM {tname}")
            codes = [r[0] for r in cur.fetchall()[:5]]
            print(f"  Sample codes: {codes}")
            break
conn.close()
