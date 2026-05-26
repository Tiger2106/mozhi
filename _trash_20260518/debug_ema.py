import sys, os
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np

# Test that _ema matches pandas ewm
from backtest.strategies.trend_strategy import _ema

np.random.seed(42)
n = 120
close = 100 + np.cumsum(np.random.randn(n) * 0.5)

# Verify shapes
print("close type:", type(close))
print("close len:", len(close))
print("close[0]:", close[0])

# _ema
old_ema = _ema(close, 12)
print("old_ema type:", type(old_ema))
print("old_ema len:", len(old_ema))
print("old_ema[0]:", old_ema[0])
print("old_ema[11]:", old_ema[11])

# pandas ewm
s = pd.Series(close)
new_ema = s.ewm(span=12, adjust=False).mean()
print("new_ema type:", type(new_ema))
print("new_ema len:", len(new_ema))
print("new_ema[0]:", new_ema.iloc[0])
print("new_ema[11]:", new_ema.iloc[11])

# Compare all
diffs = []
for i in range(n):
    if old_ema[i] is not None and not pd.isna(new_ema.iloc[i]):
        diff = abs(old_ema[i] - new_ema.iloc[i])
        if diff > 1e-10:
            diffs.append((i, old_ema[i], new_ema.iloc[i], diff))

print(f"\nTotal EMA12 differences > 1e-10: {len(diffs)}")
if diffs:
    print("First 5 differences:")
    for i, ov, nv, d in diffs[:5]:
        print(f"  [{i}]: old={ov:.10f}, new={nv:.10f}, diff={d:.10f}")
else:
    print("  All values match!")

# Check _ema formula manually
alpha = 2.0 / (12 + 1)
print(f"\nManual EMA calc:")
print(f"  alpha = {alpha}")
print(f"  manual[0] = {close[0]}")
man11 = 0
for i in range(1):
    man11 = alpha * close[i] + (1-alpha) * close[i-1]
print(f"  This is wrong, need loop")

# Actually compute manually
man_ema = np.zeros(120)
man_ema[0] = close[0]
for i in range(1, 120):
    man_ema[i] = alpha * close[i] + (1 - alpha) * man_ema[i-1]
print(f"  manual[11] = {man_ema[11]:.10f}")
print(f"  old_ema[11] = {old_ema[11]:.10f}")
print(f"  match: {abs(man_ema[11] - old_ema[11]) < 1e-10}")
