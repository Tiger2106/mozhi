import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\backtest.db')
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('\n'.join(sorted(tables)))
conn.close()
