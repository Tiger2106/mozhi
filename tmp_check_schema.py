import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
cur = conn.cursor()
cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = [r[0] for r in cur.fetchall()]
print('Tables:', tables)
for t in tables:
    cur.execute(f'PRAGMA table_info({t})')
    cols = cur.fetchall()
    print(f'\n{t}:')
    for c in cols:
        print(f'  {c}')
conn.close()
