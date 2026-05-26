import sqlite3
conn = sqlite3.connect('C:/Users/17699/mozhi_platform/data/backtest.db')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cursor.fetchall()]
print('Tables:', tables)
for t in tables:
    cursor = conn.execute(f'SELECT sql FROM sqlite_master WHERE name="{t}"')
    row = cursor.fetchone()
    if row:
        print(f'\n--- {t} ---')
        print(row[0])
conn.close()
