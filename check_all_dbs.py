"""检查所有数据库中的 stock_daily 表"""
import sqlite3, os

# 1. data/analysis.db (TSI使用)
db1 = r'C:\Users\17699\mozhi_platform\data\analysis.db'
conn1 = sqlite3.connect(db1)
c1 = conn1.cursor()
tables = c1.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('=== data/analysis.db 表 ===')
for t in tables:
    cnt = c1.execute(f'SELECT COUNT(*) FROM "{t[0]}"').fetchone()[0]
    print(f'  {t[0]}: {cnt} rows')
conn1.close()

# 2. data/db/analysis.db
db2 = r'C:\Users\17699\mozhi_platform\data\db\analysis.db'
conn2 = sqlite3.connect(db2)
c2 = conn2.cursor()
tables2 = c2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('\n=== data/db/analysis.db 表 ===')
for t in tables2:
    cnt = c2.execute(f'SELECT COUNT(*) FROM "{t[0]}"').fetchone()[0]
    print(f'  {t[0]}: {cnt} rows')
    
c2.execute("PRAGMA table_info('stock_daily')")
cols2 = c2.fetchall()
if cols2:
    codes = c2.execute("SELECT code, count(*) FROM stock_daily GROUP BY code").fetchall()
    print('\n  stock_daily 标的分布:')
    for code, cnt in codes:
        n = c2.execute("SELECT sum(CASE WHEN adj_factor IS NOT NULL THEN 1 ELSE 0 END) FROM stock_daily WHERE code=?", (code,)).fetchone()[0]
        print(f'    {code}: {cnt} rows, adj_factor_notnull={n}')
    
    # 比较两个 stock_daily 的价格
    c2.execute("SELECT date, close FROM stock_daily WHERE code='601857' AND date='20200102'")
    row2 = c2.fetchone()
    print(f'\n  data/db stock_daily 首日: {row2}')
conn2.close()

# 3. market_data.db
db3 = r'C:\Users\17699\mozhi_platform\data\market\market_data.db'
conn3 = sqlite3.connect(db3)
c3 = conn3.cursor()
tables3 = c3.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('\n=== data/market/market_data.db 表 ===')
for t in tables3:
    cnt = c3.execute(f'SELECT COUNT(*) FROM "{t[0]}"').fetchone()[0]
    print(f'  {t[0]}: {cnt} rows')
    cols = c3.execute(f"PRAGMA table_info('{t[0]}')").fetchall()
    for col in cols:
        print(f'    {col}')
conn3.close()

print('\n==== 数据溯源分析完成 ====')
