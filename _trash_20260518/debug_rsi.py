import sys, os
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np
from backtest.methods.momentum.rsi_method import RSIMethod

dates = pd.date_range('2025-01-01', periods=50, freq='D')
close = 100 + np.arange(50) * 2.0
df = pd.DataFrame({'close': close}, index=pd.DatetimeIndex(dates))

class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
    def get_config(self, key, default=None):
        return self._config.get(key, default)

m = RSIMethod()
m.setup(MockContext({'period': 14, 'oversold': 30.0, 'overbought': 70.0}))
result = m.generate_signal(df)
rsi = result['rsi']
print('RSI last 10:')
print(rsi.tail(10).to_dict())
print('\nSignal last 10:')
print(result['signal'].tail(10).to_dict())
print('\nMax RSI:', rsi.max())
print('\nSignal value counts:', result['signal'].value_counts().to_dict())
