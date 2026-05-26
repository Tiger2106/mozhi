import os, sqlite3

base = r'C:\Users\17699\mozhi_platform\data'
files = [f for f in os.listdir(base) if f.endswith('.db') and f != 'market_data.db']

for fname in sorted(files):
    path = os.path.join(base, fname)
    size_kb = os.path.getsize(path) // 1024
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cur.fetchall()
    tnames = [t[0] for t in tables]
    
    # Get row counts for important tables
    info = []
    for t in tables[:5]:
        cur.execute(f"SELECT COUNT(*) FROM {t[0]}")
        info.append(f"{t[0]}({cur.fetchone()[0]}行)")
    
    # Get modified time
    mtime = os.path.getmtime(path)
    from datetime import datetime
    dt = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
    
    print(f"{fname:40s} {size_kb:>5}KB  {dt}")
    print(f"  表: {', '.join(tnames[:6])}")
    if info:
        print(f"  行: {', '.join(info[:3])}")
    print()
    conn.close()
