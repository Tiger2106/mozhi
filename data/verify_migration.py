import sqlite3

mdb = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
adb = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\analysis.db')

# check stock_daily overlap
md = mdb.execute("SELECT code, COUNT(*) as cnt, MAX(date) FROM stock_daily WHERE code IN ('000001','600519','601857') GROUP BY code ORDER BY code").fetchall()
ad = adb.execute("SELECT code, COUNT(*) as cnt, MAX(date) FROM stock_daily WHERE code IN ('000001','600519','601857') GROUP BY code ORDER BY code").fetchall()

print("=== stock_daily 标的重叠对比 ===")
for (mc,mcnt,mdt), (ac,acnt,adt) in zip(md, ad):
    diff = mcnt - acnt
    print(f"{mc}: market_data={mcnt}行 latest={mdt}  analysis={acnt}行 latest={adt}  diff={diff:+d}")

# close prices for 601857
m_close = {r[0]:r[1] for r in mdb.execute("SELECT date, close FROM stock_daily WHERE code='601857' ORDER BY date").fetchall()}
a_close = {r[0]:r[1] for r in adb.execute("SELECT date, close FROM stock_daily WHERE code='601857' ORDER BY date").fetchall()}
overlap = set(m_close.keys()) & set(a_close.keys())
diff_count = sum(1 for d in overlap if abs(m_close.get(d,0) - a_close.get(d,0)) > 0.01)
print(f"\n601857 重叠日期数: {len(overlap)}, 收盘价差异>0.01: {diff_count}/{len(overlap)}")
if diff_count > 0:
    for d in sorted(overlap)[:5]:
        print(f"  {d}: market={m_close[d]:.2f} vs analysis={a_close[d]:.2f}")

# trading calendar
m_cal = set(r[0] for r in mdb.execute("SELECT date FROM trading_calendar WHERE is_trading_day=1").fetchall())
a_cal = set(r[0] for r in adb.execute("SELECT date FROM trading_calendar WHERE is_trading_day=1").fetchall())
print(f"\n交易日历: market={len(m_cal)}天 analysis={len(a_cal)}天 交集={len(m_cal&a_cal)}天")
print(f"market_data多有: {sorted(m_cal-a_cal)[:3]}...")
print(f"analysis多有: {sorted(a_cal-m_cal)[:3]}...")

# data/db/analysis.db check
db3 = r'C:\Users\17699\mozhi_platform\data\db\analysis.db'
import os
if os.path.exists(db3):
    db3c = sqlite3.connect(db3)
    t3 = [r[0] for r in db3c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"\ndata/db/analysis.db 表: {t3}")
    for tn in t3:
        cnt = db3c.execute(f"SELECT COUNT(*) FROM {tn}").fetchone()[0]
        print(f"  {tn}: {cnt}行")
    db3c.close()

mdb.close()
adb.close()
