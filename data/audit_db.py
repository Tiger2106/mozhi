import os, sqlite3, glob

# Check which backtest db is more current
for fname in ['backtest.db', 'backtest_v3_backup.db']:
    path = os.path.join(r'C:\Users\17699\mozhi_platform\data', fname)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT MAX(created_at) FROM backtest_run")
        max_dt = cur.fetchone()[0]
        print(f"{fname}: last run = {max_dt}")
    except Exception as e:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cur.fetchall()]
        print(f"{fname}: tables={tables}  error={e}")
    conn.close()

# Check which .py files reference each database
dbs_to_check = ['analysis.db', 'backtest.db', 'trade_engine.db', 'knowledge.db']
print()
for dbname in dbs_to_check:
    refs = []
    for root, dirs, files in os.walk(r'C:\Users\17699\mozhi_platform'):
        if 'node_modules' in root or '__pycache__' in root:
            continue
        for f in files:
            if not f.endswith('.py'):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
                if dbname in content:
                    refs.append(fp)
            except:
                pass
    status = "IN USE" if refs else "NO REFERENCES"
    print(f"{dbname:35s} {status}")
    for r in refs[:5]:
        print(f"  └ {r}")
