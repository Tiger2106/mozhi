"""Debug the forward return computation step by step"""
import sqlite3, pandas as pd
import numpy as np

conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\data\market\a50_ic.db')

trade_date = '20260521'
forward_window = 5

# Step 1: future data
sql = """
    SELECT ts_code, trade_date, close
    FROM a50_daily_ohlcv
    WHERE trade_date > ?
      AND (null_reason IS NULL OR null_reason != 'SUSPENDED')
    ORDER BY ts_code, trade_date
"""
future_df = pd.read_sql(sql, conn, params=[trade_date])
print(f"future_df: {len(future_df)} rows")
print(f"dtypes: {future_df.dtypes.to_dict()}")
print(f"close dtype: {future_df['close'].dtype}")
print()

# Step 2: groupby apply
def _get_future_close(group, fwd=forward_window):
    if len(group) >= fwd:
        return group.iloc[fwd - 1]['close']
    return None

_fc = future_df.groupby('ts_code').apply(_get_future_close, include_groups=False)
print(f"groupby.apply result type: {type(_fc).__name__}")
print(f"dtypes: {_fc.dtypes}")
print(f"_fc head: {_fc.head()}")
if isinstance(_fc, pd.DataFrame):
    print(f"columns: {_fc.columns.tolist()}")
    print(f"first col dtype: {_fc.iloc[:,0].dtype}")
    print(f"first col values sample: {_fc.iloc[:5,0].values}")
    # Try conversion
    fc_series = _fc.iloc[:,0]
    fc_renamed = fc_series.rename('future_close')
    print(f"renamed dtype: {fc_renamed.dtype}")
    print(f"renamed values: {fc_renamed.head()}")
elif isinstance(_fc, pd.Series):
    fc_renamed = _fc.rename('future_close')
    print(f"renamed dtype: {fc_renamed.dtype}")

# Step 3: today_close
today_close = pd.read_sql(
    """SELECT ts_code, close FROM a50_daily_ohlcv
       WHERE trade_date = ? AND close IS NOT NULL
         AND (null_reason IS NULL OR null_reason != 'SUSPENDED')""",
    conn, params=[trade_date]
)
today_close = today_close.set_index('ts_code')['close']
print(f"\ntoday_close dtype: {today_close.dtype}")
print(f"today_close sample: {today_close.head()}")

# Step 4: test division
print("\n--- Testing division ---")
if isinstance(_fc, pd.DataFrame):
    fc = _fc.iloc[:, 0].rename('future_close')
elif isinstance(_fc, pd.Series):
    fc = _fc.rename('future_close')
else:
    fc = pd.Series(dtype=float)

print(f"fc dtype: {fc.dtype if not fc.empty else 'empty'}")
print(f"fc index dtype: {fc.index.dtype}")

common = today_close.index.intersection(fc.index)
print(f"common: {len(common)} items")
print(f"common[:5]: {common[:5]}")
print(f"fc[common] dtype: {fc[common].dtype}")
print(f"today_close[common] dtype: {today_close[common].dtype}")
print(f"fc[common] sample: {fc[common].head()}")
print(f"today_close[common] sample: {today_close[common].head()}")

try:
    result = fc[common] / today_close[common] - 1
    print(f"RESULT: {len(result)} items")
    print(result.head())
except Exception as e:
    print(f"ERROR: {e}")
    # Try to convert
    print("Trying pd.to_numeric...")
    fc_num = pd.to_numeric(fc[common], errors='coerce')
    print(f"fc_num dtype: {fc_num.dtype}")
    try:
        result = fc_num / today_close[common] - 1
        print(f"RESULT after conversion: {len(result)} items")
    except Exception as e2:
        print(f"STILL ERROR: {e2}")

conn.close()
