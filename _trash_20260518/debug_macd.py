import sys, os, inspect
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np
from types import SimpleNamespace

# Old system
from backtest.strategies.trend_strategy import generate_macd_signals, _ema

# New system
from backtest.methods.trend.macd_method import MACDMethod

# Create test data
np.random.seed(42)
n = 120
dates = pd.date_range("2025-01-01", periods=n, freq="D")
close = 100 + np.cumsum(np.random.randn(n) * 0.5)

# DataFrame for new system
df = pd.DataFrame({"close": close}, index=pd.DatetimeIndex(dates))

# Bars for old system
high = close + np.abs(np.random.randn(n)) * 1.5
low = close - np.abs(np.random.randn(n)) * 1.5
volume = np.random.randint(1000, 10000, n)
bars = [
    SimpleNamespace(
        datetime=dates[i],
        date=dates[i].strftime("%Y-%m-%d"),
        symbol="TEST",
        open=float((high[i] + low[i]) / 2),
        high=float(high[i]),
        low=float(low[i]),
        close=float(close[i]),
        volume=int(volume[i]),
    )
    for i in range(n)
]

# Old system call
old = generate_macd_signals(bars, fast_period=12, slow_period=26, signal_period=9)

# New system call
method = MACDMethod()
class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)
method.setup(MockContext({"fast_period": 12, "slow_period": 26, "signal_period": 9}))
new = method.generate_signal(df)

# Compare signals
diff_count = 0
diff_indices = []
for i in range(n):
    old_sig = old[i].get("signal", 0)
    new_sig = new["signal"].iloc[i]
    if old_sig != new_sig:
        diff_count += 1
        diff_indices.append((i, old_sig, new_sig))
        
print(f"Total differences: {diff_count} out of {n}")
print(f"Deviation: {diff_count/n:.6f}")
print("\nFirst 10 differences:")
for idx, osig, nsig in diff_indices[:10]:
    print(f"  index={idx}: old={osig}, new={nsig}, dif={new['dif'].iloc[idx]:.4f}, dea={new['dea'].iloc[idx]:.4f}")

# Also compare DIF and DEA values
print("\nDEA comparison at key positions:")
for idx in range(20, 40):
    old_dea = old[idx].get("dea", None)
    new_dea = new["dea"].iloc[idx]
    old_dif = old[idx].get("dif", None)
    new_dif = new["dif"].iloc[idx]
    old_sig = old[idx].get("signal", 0)
    new_sig = new["signal"].iloc[idx]
    marker = " *** DIFF" if old_sig != new_sig else ""
    print(f"  {idx}: old_dif={old_dif:.4f if old_dif else None}, new_dif={new_dif:.4f if not pd.isna(new_dif) else None}, "
          f"old_dea={old_dea:.4f if old_dea else None}, new_dea={new_dea:.4f if not pd.isna(new_dea) else None}, "
          f"sig: old={old_sig}, new={new_sig}{marker}")
