import sqlite3

mdb = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
adb = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\analysis.db')

# check adj_factor column presence
m_cols = [r[1] for r in mdb.execute("PRAGMA table_info(stock_daily)").fetchall()]
a_cols = [r[1] for r in adb.execute("PRAGMA table_info(stock_daily)").fetchall()]
print("market_data stock_daily 列:", m_cols)
print("analysis stock_daily 列:", a_cols)

# Check adj_factor values
mf = mdb.execute("SELECT date, adj_factor FROM adj_factor WHERE code='601857' ORDER BY date LIMIT 5").fetchall()
print(f"\nmarket_data adj_factor 前5行: {mf}")
af = adb.execute("SELECT date, adj_factor FROM stock_daily WHERE code='601857' ORDER BY date LIMIT 5").fetchall()
print(f"analysis stock_daily.adj_factor 前5行: {af}")

# Check if market_data has adj_factor in stock_daily too
print(f"\nmarket_data stock_daily 有 adj_factor: {'adj_factor' in m_cols}")

# Check first close in detail
m_first = mdb.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' ORDER BY date LIMIT 1").fetchone()
a_first = adb.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' ORDER BY date LIMIT 1").fetchone()
print(f"\n601857 第一条记录:")
print(f"  market_data: date={m_first[0]}, close={m_first[1]}, adj_factor={m_first[2]}")
print(f"  analysis:    date={a_first[0]}, close={a_first[1]}, adj_factor={a_first[2]}")

# Check last records
m_last = mdb.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' ORDER BY date DESC LIMIT 1").fetchone()
a_last = adb.execute("SELECT date, close, adj_factor FROM stock_daily WHERE code='601857' ORDER BY date DESC LIMIT 1").fetchone()
print(f"\n601857 最新记录:")
print(f"  market_data: date={m_last[0]}, close={m_last[1]}, adj_factor={m_last[2]}")
print(f"  analysis:    date={a_last[0]}, close={a_last[1]}, adj_factor={a_last[2]}")

# Check one specific date for exact close price match
# Try 20260515 (latest common date)
print("\n=== 按时间排序的收盘价对比（前10条）===")
m_all = mdb.execute("SELECT date, close FROM stock_daily WHERE code='601857' ORDER BY date").fetchall()
a_all = adb.execute("SELECT date, close FROM stock_daily WHERE code='601857' ORDER BY date").fetchall()
# Align by index
for i in range(10):
    md, mc = m_all[i]
    ad2, ac = a_all[i]
    ratio = mc / ac if ac else 0
    print(f"  idx={i}: date={md} close_m={mc:.4f} close_a={ac:.4f} ratio={ratio:.4f}")

# Try date format matching
m_dates = [r[0] for r in m_all[:5]]
a_dates = [r[0] for r in a_all[:5]]
print(f"\nmarket_data date format: {m_dates}")
print(f"analysis date format: {a_dates}")

# Verify: are the closes just adjusted differently?
print("\n=== 复权因子乘积校验 ===")
# market_data stock_daily has adj_factor column - check if close / adj_factor = analysis close
mdb2 = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\market_data.db')
for i in range(5):
    md, mc = m_all[i]
    ad2, ac = a_all[i]
    # check market_data stock_daily adj_factor for same date
    mf_row = mdb2.execute("SELECT adj_factor FROM stock_daily WHERE code='601857' AND date=? ORDER BY date", (md,)).fetchone()
    mf_val = mf_row[0] if mf_row else None
    adj_factor_ad = adb.execute("SELECT adj_factor FROM stock_daily WHERE code='601857' AND date=? ORDER BY date", (ad2,)).fetchone()
    af_val = adj_factor_ad[0] if adj_factor_ad else None
    print(f"  date={md}: m_close={mc:.4f} m_adj={mf_val}  a_close={ac:.4f} a_adj={af_val}  adjusted_m={mc/mf_val:.4f if mf_val else 'N/A'}")

mdb.close()
adb.close()
mdb2.close()
