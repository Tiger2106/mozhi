"""验证 stock_daily 表复权状态"""
import sqlite3
import pandas as pd
import os, sys

db_path = r'C:\Users\17699\mozhi_platform\data\analysis.db'
print(f'db exists: {os.path.exists(db_path)}')
print(f'db size: {os.path.getsize(db_path)} bytes')

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# === 1. stock_daily 表结构 ===
cur.execute("PRAGMA table_info(stock_daily)")
cols = cur.fetchall()
print('\n=== stock_daily 表结构 ===')
for c in cols:
    print(f'  {c}')

# === 2. adj_factor 列统计 ===
cur.execute("""
    SELECT count(*),
           sum(CASE WHEN adj_factor IS NOT NULL THEN 1 ELSE 0 END),
           sum(CASE WHEN adj_factor IS NULL THEN 1 ELSE 0 END)
    FROM stock_daily WHERE code='601857'
""")
cnt, notnull, isnull = cur.fetchone()
print(f'\n=== stock_daily 601857 adj_factor 统计 ===')
print(f'  总记录数: {cnt}')
print(f'  adj_factor 非NULL: {notnull}')
print(f'  adj_factor 为NULL: {isnull}')

# === 3. 首/末日 close 对比 ===
cur.execute("""
    SELECT date, open, high, low, close, volume, adj_factor
    FROM stock_daily WHERE code='601857' ORDER BY date LIMIT 3
""")
rows = cur.fetchall()
print(f'\n=== stock_daily 601857 前三行 ===')
for r in rows:
    print(f'  {r}')

cur.execute("""
    SELECT date, open, high, low, close, volume, adj_factor
    FROM stock_daily WHERE code='601857' ORDER BY date DESC LIMIT 3
""")
rows = cur.fetchall()
print(f'\n=== stock_daily 601857 末三行 ===')
for r in rows:
    print(f'  {r}')

# === 4. 所有标的 adj_factor 统计 ===
cur.execute("SELECT DISTINCT code FROM stock_daily ORDER BY code")
codes = [r[0] for r in cur.fetchall()]
print(f'\n=== 所有标的 adj_factor 全局统计 ===')
all_null = True
for code in codes[:30]:  # 最多查前30个
    cur.execute("SELECT count(*), sum(CASE WHEN adj_factor IS NOT NULL THEN 1 ELSE 0 END) FROM stock_daily WHERE code=?", (code,))
    cnt2, notnull2 = cur.fetchone()
    if notnull2 > 0:
        all_null = False
    print(f'  {code}: total={cnt2}, adj_factor_notnull={notnull2}')
if len(codes) > 30:
    print(f'  ... and {len(codes)-30} more codes')

print(f'\n=== 全局结论: adj_factor 全为 NULL? {all_null} ===')

# === 5. 对比 stock_daily.close vs 前复权 close ===
print(f'\n=== 数据对比验证 ===')
qfq_df = pd.read_parquet(r'C:\Users\17699\mozhi_platform\backtest_data_cache\601857_20200102_20260515_qfq.parquet')
print(f'前复权文件: {len(qfq_df)} 行, {qfq_df["date"].iloc[0]} ~ {qfq_df["date"].iloc[-1]}')

cur.execute("""
    SELECT date, close FROM stock_daily
    WHERE code='601857' AND date >= '2020-01-02'
    ORDER BY date
""")
raw_rows = cur.fetchall()
raw_dict = {r[0]: r[1] for r in raw_rows}
print(f'stock_daily 表: {len(raw_rows)} 行')

# Compare first day
first_qfq = qfq_df.iloc[0]
first_date_qfq = str(first_qfq['date'])[:10]
first_date_raw = first_date_qfq.replace('-', '')
first_raw = raw_dict.get(first_date_raw)
print(f'\n首日 ({first_date_raw} / qfq={first_date_qfq}):')
print(f'  前复权 close: {first_qfq["close"]:.2f}')
print(f'  stock_daily close: {first_raw}')
if first_raw:
    ratio = first_qfq["close"] / first_raw
    print(f'  比例: {ratio:.4f}')

last_qfq = qfq_df.iloc[-1]
last_date_qfq = str(last_qfq['date'])[:10]
last_date_raw = last_date_qfq.replace('-', '')
last_raw = raw_dict.get(last_date_raw)
print(f'\n末日 ({last_date_raw} / qfq={last_date_qfq}):')
print(f'  前复权 close: {last_qfq["close"]:.2f}')
print(f'  stock_daily close: {last_raw}')
if last_raw:
    ratio = last_qfq["close"] / last_raw
    print(f'  比例: {ratio:.4f}')

conn.close()
print('\n=== stock_daily 验证完成 ===')
