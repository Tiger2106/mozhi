import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mo_zhi_sharereports\trade_engine.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print(f'Tables: {tables}')
conn.close()
