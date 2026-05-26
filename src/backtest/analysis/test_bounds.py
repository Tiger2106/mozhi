"""Test grid bounds to ensure signals fire"""
import sys, os
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")
os.environ["DB_PATH"] = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

from backtest.strategies.run_grid import load_stock_bars, run_grid_backtest, GridRunnerConfig
from backtest.strategies.grid_strategy import GridConfig, StaticGridSignal, GridVotingSignal
from backtest.strategies.scan_grid_params import _build_position
from backtest.strategies.run_grid import GridSignalProvider
from backtest.backtest_engine import Bar

bars = load_stock_bars("601857", "20260101", "20260208")
prices = [b.close for b in bars]
print(f"Training period: {bars[0].date} ~ {bars[-1].date}")
print(f"  {len(bars)} bars")
print(f"  Price range: {min(prices):.2f} ~ {max(prices):.2f}")
print(f"  Avg: {sum(prices)/len(prices):.2f}")

# Test different bounds
test_configs = [
    # (name, lower, upper, n_levels)
    ("tight_5pct", round(avg_price := sum(prices)/len(prices)*0.95, 2), round(sum(prices)/len(prices)*1.05, 2), 10),
    ("medium_10pct", round(avg_price := sum(prices)/len(prices)*0.90, 2), round(sum(prices)/len(prices)*1.10, 2), 10),
    ("range_based", round(min(prices)*0.98, 2), round(max(prices)*1.02, 2), 15),
]

avg_p = sum(prices)/len(prices)
print(f"\nAvg price: {avg_p:.2f}")

for name, lower, upper, nl in test_configs:
    print(f"\n--- {name}: [{lower:.2f}, {upper:.2f}], n={nl} ---")
    cfg = GridConfig(lower_bound=lower, upper_bound=upper, n_levels=nl)
    s = StaticGridSignal(grid_config=cfg)
    print(f"  Grid levels:")
    for lvl in s.grid_levels:
        print(f"    {lvl.level_type.name}: {lvl.price:.2f}")

    # Test if any bar triggers
    provider = GridSignalProvider(grid_strategy=s)
    triggered = False
    for b in bars:
        sig = provider.compute_signal(None, b)
        if sig.get("signal", 0) != 0:
            triggered = True
            print(f"  Triggered at {b.date} close={b.close:.2f}: signal={sig}")
            break
    if not triggered:
        print(f"  No triggers across all {len(bars)} bars!")

# Now test with run_grid_backtest
print("\n\n=== END TO END TEST ===")
for name, lower, upper, nl in test_configs:
    signal = StaticGridSignal(grid_config=GridConfig(lower_bound=lower, upper_bound=upper, n_levels=nl))
    pos = _build_position(position_mode="fixed", stop_loss_pct=0.0, cool_down_bars=1)
    cfg = GridRunnerConfig(symbol="601857", signal=signal, position=pos, start_date="20260101", end_date="20260208")
    result = run_grid_backtest(cfg)
    if result.status == "SUCCESS":
        bt = result.backtest_result
        print(f"  {name}: trades={bt.total_trades}, sharpe={bt.metrics.get('sharpe_ratio', 0)}")
    else:
        print(f"  {name}: FAILED")
