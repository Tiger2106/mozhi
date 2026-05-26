import sys, os
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np
from backtest.strategies.reversal_strategy import _rsi, generate_rsi_signals
from backtest.methods.momentum.rsi_method import RSIMethod

# Test data - constant uptrend
closes = [100 + i * 2.0 for i in range(50)]

# Old system RSI
old_rsi = _rsi(closes, period=14)
print("Old _rsi last 10:", old_rsi[-10:])
print("Old _rsi max:", max(r for r in old_rsi if r is not None))
print("Old _rsi NaN count:", sum(1 for r in old_rsi if r is None))

# Check the old system formula
from backtest.strategies.reversal_strategy import _ema_wilder
print("\nOld avg_gain/avg_loss check:")
delta = [closes[i] - closes[i-1] for i in range(1, len(closes))]
gains = [max(d, 0) for d in delta]
losses = [max(-d, 0) for d in delta]
print("Gains (first 20):", gains[:20])
print("Losses (first 20):", losses[:20])
