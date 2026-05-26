import sys, os, inspect
sys.path.insert(0, 'src')
from backtest.strategies.trend_strategy import generate_macd_signals
source = inspect.getsource(generate_macd_signals)
print(source[:3000])
