"""Check market_data.db content"""
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
    col_names = [c[1] for c in cols]
    print('\nstock_daily columns:', col_names)

    # Check required fields
    required = ['open', 'high', 'low', 'close', 'volume']
    actual = set(col_names)
    missing = [f for f in required if f not in actual]
    if missing:
        print(f'MISSING required fields: {missing}')
    else:
        print('All required price fields present: open/high/low/close/volume ✓')

    # free_float check - look for similar
    float_fields = [c for c in col_names if 'float' in c.lower()]
    print('Float-related columns:', float_fields)

    cursor.execute('SELECT DISTINCT code FROM stock_daily ORDER BY code')
    codes = cursor.fetchall()
    codes_list = [c[0] for c in codes]
    print(f'\nDistinct codes ({len(codes_list)}):')
    for c in codes_list:
        print(f'  {c}')

    cursor.execute('SELECT MIN(date), MAX(date) FROM stock_daily')
    dr = cursor.fetchone()
    print(f'\nDate range: {dr[0]} ~ {dr[1]}')

    # Check first 12 stocks data coverage 2021-2025
    print('\n--- Data coverage per stock (2021-2025) ---')
    for code in codes_list[:15]:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE code=? AND date BETWEEN 20210101 AND 20251231', (code,))
        cnt = cursor.fetchone()[0]
        cursor.execute('SELECT MIN(date), MAX(date) FROM stock_daily WHERE code=?', (code,))
        min_d, max_d = cursor.fetchone()
        print(f'  {code}: {cnt} days [{min_d} ~ {max_d}]')

    # Check free_float-like field (float_share)
    if 'float_share' in col_names:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE float_share IS NOT NULL AND float_share > 0')
        has_ff = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM stock_daily')
        total = cursor.fetchone()[0]
        print(f'\nfloat_share coverage: {has_ff}/{total} rows')

    # Check adj_factor
    if 'adj_factor' in col_names:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE adj_factor IS NULL')
        null_adj = cursor.fetchone()[0]
        print(f'adj_factor NULL count: {null_adj}')

    # Check a sample row
    cursor.execute('SELECT * FROM stock_daily LIMIT 1')
    sample = cursor.fetchone()
    print('\nSample row:', dict(zip(col_names, sample)))

conn.close()
print('\nDone.')
