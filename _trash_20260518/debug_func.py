import sys, os, inspect
sys.path.insert(0, 'src')
from backtest.strategies.reversal_strategy import *
print("=== voted_reversal_signal ===")
source = inspect.getsource(voted_reversal_signal)
print(source[:3000])
