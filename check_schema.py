import sqlite3, os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'market', 'market_data.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# market_daily 是否真的含2026年数据
cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM market_daily")
print(f"market_daily 日期范围: {cur.fetchone()}")

cur.execute("SELECT symbol, trade_date, turnover_rate FROM market_daily WHERE turnover_rate > 0 LIMIT 5")
print(f"\nmarket_daily turnover_rate>0 示例: {cur.fetchall()}")

# stock_daily 日期范围
cur.execute("SELECT MIN(date), MAX(date) FROM stock_daily")
print(f"\nstock_daily 日期范围: {cur.fetchone()}")

# 以 601857 展示 stock_daily 数据切换点附近的精确数据
print("\n=== 601857 切换点附近数据 ===")
cur.execute("SELECT date, open, high, low, close, volume, amount FROM stock_daily WHERE code='601857' AND date BETWEEN '20251230' AND '20260110' ORDER BY date")
for r in cur.fetchall():
    avg = r[5] / r[6] if r[6] > 0 else 0
    print(f"  {r[0]}: O={r[1]} H={r[2]} L={r[3]} C={r[4]} vol={r[5]} amt={r[6]} avg={avg:.4f}")

# 检查 market_daily turnover_rate 的整体质量
cur.execute("SELECT COUNT(*) FROM market_daily WHERE turnover_rate IS NULL OR turnover_rate = 0")
null_cnt = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM market_daily")
total = cur.fetchone()[0]
print(f"\nmarket_daily turnover_rate 质量: {null_cnt}/{total} 为空或0 ({null_cnt/total*100:.1f}%)")

# 看看 turnover_rate 非零的数据分布
cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM market_daily WHERE turnover_rate > 0")
r = cur.fetchone()
print(f"turnover_rate>0 的日期范围: {r}")

# kcboot 那边是怎么写入 market_daily 的
print("\n=== knowledge.db 中是否有 daily_basic 相关信息 ===")
kd_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'knowledge.db')
kd = sqlite3.connect(kd_path)
kd_cur = kd.cursor()
kd_cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for t in kd_cur.fetchall():
    print(f"  {t[0]}")
kd.close()

conn.close()
