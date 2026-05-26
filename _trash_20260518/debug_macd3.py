import sys, os
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np
from types import SimpleNamespace

from backtest.strategies.trend_strategy import generate_macd_signals, _ema
from backtest.methods.trend.macd_method import MACDMethod

np.random.seed(42)
n = 120
dates = pd.date_range("2025-01-01", periods=n, freq="D")
close = 100 + np.cumsum(np.random.randn(n) * 0.5)
df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))

high = close + np.abs(np.random.randn(n)) * 1.5
low = close - np.abs(np.random.randn(n)) * 1.5
volume = np.random.randint(1000, 10000, n)
bars = [SimpleNamespace(
    datetime=dates[i], date=dates[i].strftime("%Y-%m-%d"), symbol="TEST",
    open=float((high[i] + low[i]) / 2), high=float(high[i]), low=float(low[i]),
    close=float(close[i]), volume=int(volume[i]),
) for i in range(n)]

old = generate_macd_signals(bars, fast_period=12, slow_period=26, signal_period=9)

class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)

method = MACDMethod()
method.setup(MockContext({"fast_period": 12, "slow_period": 26, "signal_period": 9}))
new = method.generate_signal(df)

# Check EMA computation
fast_ema_old = _ema(close, 12)
slow_ema_old = _ema(close, 26)
fast_ema_new = df["close"].ewm(span=12, adjust=False).mean()
slow_ema_new = df["close"].ewm(span=26, adjust=False).mean()

print("EMA12 comparison (indices 0-15):")
for i in range(0, 15):
    old_val = fast_ema_old[i]
    new_val = fast_ema_new.iloc[i]
    if old_val is not None and not pd.isna(new_val):
        diff = old_val - new_val
        if abs(diff) > 0.001:
            print(f"  {i}: old={old_val:.6f}, new={new_val:.6f}, diff={diff:.10f}")

print("\nFirst valid DIF: index 25")
dif_old = old[25].get("dif")
print(f"  old DIF[25]: {dif_old}")
print(f"  new DIF[25]: {new['dif'].iloc[25]}")
print(f"  new DIF[26]: {new['dif'].iloc[26]}")

# Check differences at the key indices
print("\nKey differences:")
for idx in [34, 37, 39, 41]:
    osig = old[idx].get("signal", 0)
    nsig = new["signal"].iloc[idx]
    odif = old[idx].get("dif")
    ndeif = new["dif"].iloc[idx]
    odea = old[idx].get("dea")
    ndea = new["dea"].iloc[idx]
    print(f"  idx={idx}: osig={osig}, nsig={nsig}, "
          f"odif={odif:.4f if odif is not None else 'None'}, "
          f"ndeif={ndeif:.4f if not pd.isna(ndeif) else 'None'}, "
          f"odea={odea:.4f if odea is not None else 'None'}, "
          f"ndea={ndea:.4f if not pd.isna(ndea) else 'None'}")
