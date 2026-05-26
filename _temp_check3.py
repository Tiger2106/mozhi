"""Check market_data.db content"""
import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
cursor = conn.cursor()

col_names = None

if ('stock_daily',) in [t[0] for t in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
    cursor.execute('PRAGMA table_info(stock_daily)')
    cols = cursor.fetchall()
    col_names = [c[1] for c in cols]
    print('stock_daily columns:', col_names)

    # Check required fields
    required = ['open', 'high', 'low', 'close', 'volume']
    actual = set(col_names)
    missing = [f for f in required if f not in actual]
    if missing:
        print('MISSING required fields:', missing)
    else:
        print('All required price fields present: OK')

    float_fields = [c for c in col_names if 'float' in c.lower()]
    print('Float-related columns:', float_fields)

    cursor.execute('SELECT DISTINCT code FROM stock_daily ORDER BY code')
    codes = [c[0] for c in cursor.fetchall()]
    print('Distinct codes (%d):' % len(codes))
    for c in codes:
        print('  ', c)

    cursor.execute('SELECT MIN(date), MAX(date) FROM stock_daily')
    dr = cursor.fetchone()
    print('Date range:', dr[0], '~', dr[1])

    print('--- Data coverage per stock (2021-2025) ---')
    for code in codes[:15]:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE code=? AND date BETWEEN 20210101 AND 20251231', (code,))
        cnt = cursor.fetchone()[0]
        cursor.execute('SELECT MIN(date), MAX(date) FROM stock_daily WHERE code=?', (code,))
        min_d, max_d = cursor.fetchone()
        print('  %s: %d days [%s ~ %s]' % (code, cnt, min_d, max_d))

    if 'float_share' in col_names:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE float_share IS NOT NULL AND float_share > 0')
        has_ff = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM stock_daily')
        total = cursor.fetchone()[0]
        print('float_share coverage: %d/%d rows' % (has_ff, total))

    if 'adj_factor' in col_names:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE adj_factor IS NULL')
        null_adj = cursor.fetchone()[0]
        print('adj_factor NULL count:', null_adj)

    cursor.execute('SELECT * FROM stock_daily LIMIT 1')
    sample = cursor.fetchone()
    print('Sample row:', dict(zip(col_names, sample)))

conn.close()
print('Done.')
