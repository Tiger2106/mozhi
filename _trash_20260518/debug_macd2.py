import sys, os, inspect
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np
from types import SimpleNamespace

from backtest.strategies.trend_strategy import generate_macd_signals
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

print("DEA comparison at positions 25-45:")
for idx in range(25, 45):
    old_dea = old[idx].get("dea")
    new_dea = new["dea"].iloc[idx]
    old_dif = old[idx].get("dif")
    new_dif = new["dif"].iloc[idx]
    old_sig = old[idx].get("signal", 0)
    new_sig = new["signal"].iloc[idx]
    dea_diff = ""
    if old_dea is not None and not pd.isna(new_dea):
        if abs(old_dea - new_dea) > 0.001:
            dea_diff = f" ** dea diff: {old_dea - new_dea}"
    old_state = 1 if (old_dif is not None and old_dea is not None and old_dif > old_dea) else (-1 if (old_dif is not None and old_dea is not None and old_dif < old_dea) else 0)
    new_state = 1 if not pd.isna(new_dif) and not pd.isna(new_dea) and new_dif > new_dea else (-1 if not pd.isna(new_dif) and not pd.isna(new_dea) and new_dif < new_dea else 0)
    marker = " *** DIFF" if old_sig != new_sig else ""
    print(f"  {idx}: old_sig={old_sig}, new_sig={new_sig}, "
          f"old_state={old_state}, new_state={new_state}, "
          f"old_dea={old_dea:.4f if old_dea is not None else None}, new_dea={new_dea:.4f if not pd.isna(new_dea) else None}"
          f"{dea_diff}{marker}")
