import sys, os
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np

# Test pandas ewm with NaN at start
s = pd.Series([np.nan, np.nan, 10.0, 12.0, 11.0])
result = s.ewm(span=9, adjust=False).mean()
print("NaN-start ewm:")
print(result)

# Test with no NaN
s2 = pd.Series([10.0, 12.0, 11.0])
result2 = s2.ewm(span=9, adjust=False).mean()
print("\nNo-NaN ewm:")
print(result2)

# Test separately
result3 = pd.Series([10.0, 12.0, 11.0]).ewm(span=9, adjust=False).mean()
print("\nOne-line:")
print(result3)
