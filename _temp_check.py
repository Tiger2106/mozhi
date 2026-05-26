"""Temporary: check market_data.db content"""
import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
cursor = conn.cursor()

# List tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Tables:', tables)

if ('stock_daily',) in tables:
    cursor.execute('PRAGMA table_info(stock_daily)')
    cols = cursor.fetchall()
    print('\nstock_daily columns:', [c[1] for c in cols])

    # Check required fields
    required = ['open', 'high', 'low', 'close', 'volume', 'free_float']
    actual = set(c[1] for c in cols)
    missing = [f for f in required if f not in actual]
    if missing:
        print(f'MISSING fields: {missing}')
    else:
        print('All required fields present ✓')

    cursor.execute('SELECT DISTINCT ts_code FROM stock_daily ORDER BY ts_code')
    codes = cursor.fetchall()
    codes_list = [c[0] for c in codes]
    print(f'\nDistinct ts_codes ({len(codes_list)}):', codes_list[:15])

    cursor.execute('SELECT MIN(trade_date), MAX(trade_date) FROM stock_daily')
    dr = cursor.fetchone()
    print(f'Date range: {dr[0]} ~ {dr[1]}')

    # Check per-code data continuity
    for code in codes_list[:12]:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE ts_code=? AND trade_date BETWEEN 20210101 AND 20251231', (code,))
        cnt = cursor.fetchone()[0]
        print(f'  {code}: {cnt} trading days (2021-2025)')

    # Check free_float presence
    cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE free_float IS NOT NULL AND free_float > 0')
    has_ff = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM stock_daily')
    total = cursor.fetchone()[0]
    print(f'\nfree_float coverage: {has_ff}/{total} rows')

conn.close()
