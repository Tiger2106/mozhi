"""Verify a50_ic.db contents"""
import sqlite3

db = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"
conn = sqlite3.connect(db)

# Tables
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print("Tables:", tables)

# a50_daily_ohlcv stats
r = conn.execute("SELECT COUNT(*), COUNT(DISTINCT ts_code), MIN(trade_date), MAX(trade_date) FROM a50_daily_ohlcv").fetchone()
print(f"a50_daily_ohlcv: rows={r[0]}, codes={r[1]}, range={r[2]}~{r[3]}")

# null_reason
nr = conn.execute("SELECT null_reason, COUNT(*) FROM a50_daily_ohlcv GROUP BY null_reason").fetchall()
print("null_reason dist:", dict(nr))

# close IS NULL
null_close = conn.execute("SELECT COUNT(*) FROM a50_daily_ohlcv WHERE close IS NULL").fetchone()[0]
print(f"close IS NULL: {null_close}")

# close=0 AND volume=0
susp = conn.execute("SELECT COUNT(*) FROM a50_daily_ohlcv WHERE close=0 AND volume=0").fetchone()[0]
print(f"close=0 AND volume=0: {susp}")

# indices
indices = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='a50_daily_ohlcv'").fetchall()
print("a50_daily_ohlcv indices:", [i[0] for i in indices])

# a50_universe
univ_rows = conn.execute("SELECT COUNT(*) FROM a50_universe").fetchone()[0]
print(f"a50_universe rows: {univ_rows}")
src = conn.execute("SELECT source, COUNT(*) FROM a50_universe GROUP BY source").fetchall()
print("universe sources:", dict(src))

# Sample a50_universe
sample = conn.execute("SELECT ts_code, in_date, out_date, source FROM a50_universe ORDER BY in_date LIMIT 5").fetchall()
print("Earliest universe entries:")
for s in sample:
    print(f"  {s[0]} in={s[1]} out={s[2]} src={s[3]}")

# 600519.SH post-adj check
maotai = conn.execute("SELECT trade_date, close, pre_close, adj_factor FROM a50_daily_ohlcv WHERE ts_code='600519.SH' ORDER BY trade_date DESC LIMIT 5").fetchall()
print("\nMaotai latest:")
for m in maotai:
    print(f"  {m[0]} close={m[1]:.2f} pre_close={m[2]:.2f} adj={m[3]:.4f}")

# Cross-section table
ic_tables = [t for t in tables if 'cross' in t or 'ic' in t]
print(f"\nIC-related tables: {ic_tables}")

conn.close()
