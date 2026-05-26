import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mo_zhi_sharereports\trade_engine.db')
cur = conn.cursor()
cur.execute("PRAGMA table_info(transactions)")
cols = cur.fetchall()
print('Transactions cols:')
for c in cols:
    print(f'  {c}')
print()
cur.execute("SELECT * FROM transactions LIMIT 3")
rows = cur.fetchall()
print(f'Sample rows ({len(rows)}):')
for r in rows:
    print(f'  {r}')
conn.close()
