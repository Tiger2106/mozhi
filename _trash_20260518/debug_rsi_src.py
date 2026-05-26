import sys, os
sys.path.insert(0, 'src')
import inspect
from backtest.strategies.reversal_strategy import _rsi
print(inspect.getsource(_rsi))
