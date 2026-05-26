import sys, inspect
sys.path.insert(0, r'C:\Users\17699\mozhi_platform')
from backtest.backtest_engine import BacktestResult
print('BacktestResult class members:')
for attr in dir(BacktestResult):
    if not attr.startswith('_'):
        val = getattr(BacktestResult, attr, None)
        if not callable(val):
            print(f'  {attr}: {type(val).__name__}')

# Also check methods
import dataclasses
if hasattr(BacktestResult, '__dataclass_fields__'):
    print('\nDataclass fields:')
    for f, fdef in BacktestResult.__dataclass_fields__.items():
        print(f'  {f}: {fdef.type}')
