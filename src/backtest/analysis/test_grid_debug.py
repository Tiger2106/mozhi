"""Debug: StaticGridSignal grid structure and backtest"""
import sys, os
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")
os.environ["DB_PATH"] = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

from backtest.strategies.grid_strategy import GridConfig, StaticGridSignal
from backtest.strategies.run_grid import load_stock_bars

# Print grid levels
cfg = GridConfig(lower_bound=8.5, upper_bound=11.5, n_levels=5)
s = StaticGridSignal(grid_config=cfg)
print("=== Grid Levels ===")
for level in s.grid_levels:
    attrs = [a for a in dir(level) if not a.startswith("_")]
    print(f"  Type={type(level).__name__}")
    for a in attrs:
        print(f"    {a}={getattr(level, a)}")

# Check what compute_signal does
from backtest.strategies.run_grid import GridSignalProvider
from backtest.backtest_engine import Bar

provider = GridSignalProvider(grid_strategy=s)

# Load first few bars of data
bars = load_stock_bars("601857", "20260101", "20260208")
print(f"\n=== First 10 bars of {len(bars)} ===")
for b in bars[:10]:
    print(f"  {b.date}: open={b.open}, high={b.high}, low={b.low}, close={b.close}, vwap={b.vwap}")

# Test compute_signal with these bars
print("\n=== Signal Computation ===")
for b in bars[:10]:
    signal = provider.compute_signal(None, b)
    print(f"  {b.date} close={b.close:.2f}: signal={signal}")

print("\nDone!")
