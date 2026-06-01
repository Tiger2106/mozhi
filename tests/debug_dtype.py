"""Debug dtype issue in compute_forward_return"""
import sqlite3, pandas as pd

conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\a50_ic.db')

td = '20260520'

today = pd.read_sql(
    """SELECT ts_code, close FROM a50_daily_ohlcv
       WHERE trade_date = ? AND close IS NOT NULL
         AND (null_reason IS NULL OR null_reason != 'SUSPENDED')""",
    conn, params=[td]
)
print("=== today_close ===")
print("dtypes:", today.dtypes.to_dict())
print("head:", today.head())
print("close[0]:", repr(today['close'].iloc[0]), type(today['close'].iloc[0]))

# Check a few more
for i in range(min(5, len(today))):
    print(f"  [{i}] close={repr(today['close'].iloc[i])}, type={type(today['close'].iloc[i]).__name__}")

# Future data
future = pd.read_sql(
    """SELECT ts_code, trade_date, close FROM a50_daily_ohlcv
       WHERE trade_date > ? AND ts_code = '601857.SH'
         AND (null_reason IS NULL OR null_reason != 'SUSPENDED')
       ORDER BY trade_date LIMIT 5""",
    conn, params=[td]
)
print("\n=== future_close ===")
print("dtypes:", future.dtypes.to_dict())
for i in range(min(5, len(future))):
    print(f"  [{i}] close={repr(future['close'].iloc[i])}, type={type(future['close'].iloc[i]).__name__}")

conn.close()
