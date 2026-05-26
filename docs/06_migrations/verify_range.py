import sqlite3

mdb = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
adb = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\analysis.db')
pdb = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\db\analysis.db')

print('=== market_data.db (行情唯一源) ===')
for t_name in ['market_daily', 'stock_daily', 'adj_factor', 'trading_calendar', 'config']:
    try:
        cnt = mdb.execute(f'SELECT COUNT(*) FROM {t_name}').fetchone()[0]
        dr = mdb.execute(f'SELECT MIN(date), MAX(date) FROM {t_name}').fetchone()
        print(f'  {t_name:25s} {cnt:>6}行  {dr[0]} ~ {dr[1]}')
    except:
        pass

# stock_daily by code
codes = [r[0] for r in mdb.execute("SELECT DISTINCT code FROM stock_daily ORDER BY code").fetchall()]
print(f'  stock_daily 标的数: {len(codes)} 个')
for c in codes[:6]:
    r = mdb.execute(f"SELECT MIN(date), MAX(date), COUNT(*) FROM stock_daily WHERE code='{c}'").fetchone()
    print(f'    {c:8s}  {r[0]} ~ {r[1]}  {r[2]}行')
if len(codes) > 6:
    print(f'    ... 还有 {len(codes)-6} 个标的')

print()
print('=== analysis.db (->pipeline_cache.db) ===')
for t_name in ['stock_daily', 'oil_daily', 'tech_indicators', 'trading_calendar']:
    try:
        cnt = adb.execute(f'SELECT COUNT(*) FROM {t_name}').fetchone()[0]
        dr = adb.execute(f'SELECT MIN(date), MAX(date) FROM {t_name}').fetchone()
        print(f'  {t_name:25s} {cnt:>6}行  {str(dr[0])[:20]} ~ {str(dr[1])[:20]}')
    except:
        pass

# stock_daily_raw
cnt = adb.execute("SELECT COUNT(*) FROM stock_daily_raw").fetchone()[0]
dr = adb.execute("SELECT MIN(date), MAX(date) FROM stock_daily_raw").fetchone()
print(f'  {"stock_daily_raw":25s} {cnt:>6}行  {dr[0]} ~ {dr[1]}')

# stock_minute
cnt = adb.execute("SELECT COUNT(*) FROM stock_minute").fetchone()[0]
dr = adb.execute("SELECT MIN(date), MAX(date) FROM stock_minute").fetchone()
print(f'  {"stock_minute":25s} {cnt:>6}行  {dr[0]} ~ {dr[1]}')

print()
print('=== data/db/analysis.db (Phase1旧库) ===')
for t_name in ['stock_daily', 'adj_factor', 'daily_factors', 'trading_calendar']:
    try:
        cnt = pdb.execute(f'SELECT COUNT(*) FROM {t_name}').fetchone()[0]
        dr = pdb.execute(f'SELECT MIN(date), MAX(date) FROM {t_name}').fetchone()
        print(f'  {t_name:25s} {cnt:>6}行  {str(dr[0])[:20]} ~ {str(dr[1])[:20]}')
    except:
        pass

# data/db stocks
codes = [r[0] for r in pdb.execute("SELECT DISTINCT code FROM stock_daily ORDER BY code").fetchall()]
print(f'  标的: {len(codes)} 个')

mdb.close()
adb.close()
pdb.close()
