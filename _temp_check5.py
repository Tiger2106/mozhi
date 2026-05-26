"""Check float_share values more carefully"""
import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
cursor = conn.cursor()

# Check float_share values
cursor.execute("SELECT MIN(float_share), MAX(float_share), AVG(float_share), COUNT(*) FROM stock_daily WHERE float_share IS NOT NULL")
minv, maxv, avgv, cnt = cursor.fetchone()
print('float_share non-NULL: min=%s max=%s avg=%s count=%s' % (minv, maxv, avgv, cnt))

# Check actual sample values
cursor.execute("SELECT code, date, float_share, circ_mv, total_mv FROM stock_daily LIMIT 10")
rows = cursor.fetchall()
print('\nSample float_share values:')
for r in rows:
    print('  ', r)

# Check free_float or free_float_source
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
if 'config' in tables:
    cursor.execute("SELECT * FROM config")
    configs = cursor.fetchall()
    print('\nConfig:', configs)

if 'market_daily' in tables:
    cursor.execute('PRAGMA table_info(market_daily)')
    cols = cursor.fetchall()
    col_names = [c[1] for c in cols]
    print('\nmarket_daily columns:', col_names)
    cursor.execute("SELECT * FROM market_daily LIMIT 3")
    for r in cursor.fetchall():
        print('  ', dict(zip(col_names, r)))

if 'adj_factor' in tables:
    cursor.execute('PRAGMA table_info(adj_factor)')
    cols = cursor.fetchall()
    col_names = [c[1] for c in cols]
    print('\nadj_factor columns:', col_names)
    cursor.execute("SELECT * FROM adj_factor LIMIT 3")
    for r in cursor.fetchall():
        print('  ', dict(zip(col_names, r)))

conn.close()
