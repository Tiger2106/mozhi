import sys, os
sys.path.insert(0, 'src')
import inspect
from backtest.strategies.reversal_strategy import _rsi
print(inspect.signature(_rsi))
import backtest.strategies.reversal_strategy as rs
print(rs._rsi.__code__.co_varnames[:rs._rsi.__code__.co_argcount])
