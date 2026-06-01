"""Additional DB verification"""
import sqlite3

# Check source DB rows for the 50 stocks
src_db = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"
dst_db = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"

src = sqlite3.connect(src_db)
dst = sqlite3.connect(dst_db)

# Source total rows for A50 stocks
src_count = src.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
src_codes = src.execute("SELECT COUNT(DISTINCT ts_code) FROM stock_daily").fetchone()[0]
print(f"Source DB: {src_count} rows, {src_codes} codes")

# Destination total
dst_count = dst.execute("SELECT COUNT(*) FROM a50_daily_ohlcv").fetchone()[0]
print(f"Dest DB:   {dst_count} rows")

# Difference
diff = src_count - dst_count
print(f"Difference: {diff} rows (source - dest)")

# Check a50_cross_ic_result
ic_count = dst.execute("SELECT COUNT(*) FROM a50_cross_ic_result").fetchone()[0]
print(f"a50_cross_ic_result: {ic_count} rows")

# Verify 600519.SH dividend event continuity (20241219-20241223)
exdiv = dst.execute("""
    SELECT trade_date, close, pre_close, adj_factor
    FROM a50_daily_ohlcv
    WHERE ts_code='600519.SH' AND trade_date BETWEEN '20241219' AND '20241223'
    ORDER BY trade_date
""").fetchall()
print("\nMaotai 202412 ex-dividend event:")
for r in exdiv:
    print(f"  {r[0]} close={r[1]:.2f} pre_close={r[2]:.2f} adj={r[3]:.6f}")

# Verify continuity
if len(exdiv) >= 2:
    for i in range(1, len(exdiv)):
        prev_close = exdiv[i-1][1]
        curr_pre_close = exdiv[i][2]
        bias = abs(curr_pre_close / prev_close - 1) if prev_close > 0 else 999
        print(f"  Continuity: pre_close({exdiv[i][0]})={curr_pre_close:.2f} vs close({exdiv[i-1][0]})={prev_close:.2f} bias={bias:.4%}")

# Check a50_universe sample
print("\na50_universe sample (later entries):")
later = dst.execute("SELECT ts_code, in_date, out_date, source FROM a50_universe ORDER BY in_date DESC LIMIT 5").fetchall()
for r in later:
    print(f"  {r[0]} in={r[1]} out={r[2]} src={r[3]}")

# Are there any stocks with in_date > 20070104?
diff_dates = dst.execute("SELECT COUNT(*) FROM a50_universe WHERE in_date != '20070104'").fetchone()[0]
print(f"\nStocks with in_date != 20070104: {diff_dates}")

src.close()
dst.close()
