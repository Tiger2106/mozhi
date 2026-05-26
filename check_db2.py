"""检查 data/db/analysis.db 中 601857 的复权数据"""
import sqlite3

db = r'C:\Users\17699\mozhi_platform\data\db\analysis.db'
conn = sqlite3.connect(db)
c = conn.cursor()

# Get first/last record for 601857
c.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' ORDER BY date LIMIT 3")
print('=== data/db/analysis.db 601857 前三行 ===')
for r in c.fetchall():
    print(f'  date={r[0]}, close={r[1]}, adj_factor={r[2]}')

c.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' ORDER BY date DESC LIMIT 3")
print('\n=== data/db/analysis.db 601857 末三行 ===')
for r in c.fetchall():
    print(f'  date={r[0]}, close={r[1]}, adj_factor={r[2]}')

# Calculate adjusted price for first/last
c.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' AND date='20200102'")
r = c.fetchone()
if r:
    print(f'\n首日: close={r[1]}, adj_factor={r[2]:.6f}, adj_close={r[1]*r[2]:.2f}')

c.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' AND date='20260515'")
r = c.fetchone()
if r:
    print(f'末日: close={r[1]}, adj_factor={r[2]:.6f}, adj_close={r[1]*r[2]:.2f}')

# Check adj_factor table
print('\n=== adj_factor 表结构 ===')
c.execute("PRAGMA table_info('adj_factor')")
for col in c.fetchall():
    print(f'  {col}')

c.execute("SELECT code, date, adj_factor FROM adj_factor WHERE code='601857' ORDER BY date LIMIT 3")
print('\n=== adj_factor 表 601857 前三行 ===')
for r in c.fetchall():
    print(f'  code={r[0]}, date={r[1]}, adj_factor={r[2]}')

c.execute("SELECT count(*) FROM adj_factor WHERE code='601857'")
cnt = c.fetchone()[0]
print(f'\nadj_factor 表 601857 总行数: {cnt}')

conn.close()
