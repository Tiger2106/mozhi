import sqlite3, sys
try:
    conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall()]
    print('Tables:', tables)

    if 'stock_daily' in tables:
        cursor.execute('PRAGMA table_info(stock_daily)')
        cols = cursor.fetchall()
        col_names = [c[1] for c in cols]
        print('Columns:', col_names)

        # Required fields
        req = ['open','high','low','close','volume']
        miss = [f for f in req if f not in col_names]
        print('Missing required:', miss if miss else 'None - ALL OK')

        # Float fields
        print('Float fields:', [c for c in col_names if 'float' in c.lower()])

        # Distinct codes
        cursor.execute('SELECT DISTINCT code FROM stock_daily ORDER BY code')
        codes = [c[0] for c in cursor.fetchall()]
        print('Codes (%d):' % len(codes))
        for c in codes:
            print('  -', c)

        # Date range
        cursor.execute('SELECT MIN(date), MAX(date) FROM stock_daily')
        mn, mx = cursor.fetchone()
        print('Date range: %s ~ %s' % (mn, mx))

        # Per-stock coverage 2021-2025
        print('\\nCoverage (2021-2025):')
        for code in codes[:15]:
            cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE code=? AND date BETWEEN 20210101 AND 20251231', (code,))
            cnt = cursor.fetchone()[0]
            cursor.execute('SELECT MIN(date),MAX(date) FROM stock_daily WHERE code=?', (code,))
            dmin, dmax = cursor.fetchone()
            print('  %s: %d days [%s-%s]' % (code, cnt, dmin, dmax))

        # adj_factor
        if 'adj_factor' in col_names:
            cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE adj_factor IS NULL')
            print('adj_factor NULLs:', cursor.fetchone()[0])

        # float_share coverage
        if 'float_share' in col_names:
            cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE float_share>0')
            has = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM stock_daily')
            tot = cursor.fetchone()[0]
            print('float_share >0: %d/%d rows (%.1f%%)' % (has, tot, has*100.0/tot if tot else 0))

        # free_float_source check
        if 'free_float_source' in col_names:
            cursor.execute('SELECT DISTINCT free_float_source FROM stock_daily WHERE free_float_source IS NOT NULL')
            srcs = cursor.fetchall()
            print('free_float_source values:', [s[0] for s in srcs])

    conn.close()
    print('\\nCheck complete.')
except Exception as e:
    print('ERROR:', e, file=sys.stderr)
