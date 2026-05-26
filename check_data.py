import pandas as pd, sqlite3, os

c = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
tables = pd.read_sql('SELECT name FROM sqlite_master WHERE type="table"', c)
print("=== market_data.db ===")
for t in tables['name']:
    cnt = pd.read_sql(f'SELECT COUNT(*) as n FROM "{t}"', c).iloc[0,0]
    cols = pd.read_sql(f'SELECT * FROM "{t}" LIMIT 1', c).columns.tolist()
    print(f'  {t}: {cnt} rows, cols({len(cols)}): {cols[:8]}')
    # show distinct codes and date range
    if 'code' in cols or 'ts_code' in cols:
        code_col = 'code' if 'code' in cols else 'ts_code'
        codes = pd.read_sql(f'SELECT DISTINCT "{code_col}" FROM "{t}"', c)[code_col].tolist()
        print(f'    codes: {codes}')
    if 'date' in cols or 'trade_date' in cols:
        date_col = 'date' if 'date' in cols else 'trade_date'
        dr = pd.read_sql(f'SELECT MIN("{date_col}"), MAX("{date_col}") FROM "{t}"', c)
        print(f'    date range: {dr.iloc[0,0]} to {dr.iloc[0,1]}')
c.close()

# factor repo
c2 = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\factors\factor_repository.db')
t2 = pd.read_sql('SELECT name FROM sqlite_master WHERE type="table"', c2)
print("\n=== factor_repository.db ===")
for t in t2['name']:
    cnt = pd.read_sql(f'SELECT COUNT(*) as n FROM "{t}"', c2).iloc[0,0]
    cols = pd.read_sql(f'SELECT * FROM "{t}" LIMIT 1', c2).columns.tolist()
    print(f'  {t}: {cnt} rows, cols({len(cols)}): {cols[:8]}')
c2.close()
