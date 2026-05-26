import sys, os
sys.path.insert(0, 'src')
from backtest.strategies.trend_strategy import _ema
import inspect
print(inspect.getsource(_ema))
