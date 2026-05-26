"""Check profit_factor after fix"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from backtest.strategies.run_reversal import run_reversal_backtest, ReversalBacktestConfig

cfg = ReversalBacktestConfig(symbol="601857", signal_type="rsi", position_mode="fixed", tag="test_pf")
result = run_reversal_backtest(cfg)
MI = result.metrics
print(f"Total trades: {result.total_trades}")
print(f"profit_factor = {MI.get('profit_factor', 'N/A')}")
print(f"profit_loss_ratio = {MI.get('profit_loss_ratio', 'N/A')}")
print(f"win_rate_pct = {MI.get('win_rate_pct', 'N/A')}")

# Test grid too
from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig
from backtest.strategies.run_grid import run_grid_backtest, make_grid_config

b_601857 = (2.51, 14.25)  # from earlier run
cfg2 = make_grid_config(
    symbol="601857.SH",
    signal=StaticGridSignal(
        grid_config=GridConfig(lower_bound=b_601857[0], upper_bound=b_601857[1], n_levels=10, grid_type="arithmetic")
    ),
    position_mode="batcher",
    position_kwargs={"total_grid_rows": 10},
    risk_config={"cool_down": {"cool_down_bars": 3}},
    tag="test_pf2",
)
result2 = run_grid_backtest(cfg2)
MI2 = result2.metrics
print(f"\nGrid trades: {result2.total_trades}")
print(f"Grid profit_factor = {MI2.get('profit_factor', 'N/A')}")
print(f"Grid profit_loss_ratio = {MI2.get('profit_loss_ratio', 'N/A')}")
print(f"Grid win_rate_pct = {MI2.get('win_rate_pct', 'N/A')}")
