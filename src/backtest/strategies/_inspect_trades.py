"""检查 BacktestResult 的 trade 和 equity_curve 数据格式"""
import sys
sys.path.insert(0, r'C:\Users\17699\mozhi_platform')
from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig
from backtest.strategies.grid_position import GridPositionManager, GridFixedPosition, GridCoolDown
from backtest.strategies.run_grid import GridRunnerConfig, run_grid_backtest, load_stock_bars

signal = StaticGridSignal(
    grid_config=GridConfig(lower_bound=9.65, upper_bound=13.05, n_levels=5, grid_type='arithmetic')
)
pos = GridPositionManager(
    position_logic=GridFixedPosition(quantity=200),
    cool_down=GridCoolDown(cool_down_bars=1),
)
cfg = GridRunnerConfig(
    symbol='601857',
    start_date='20260101',
    end_date='20260514',
    signal=signal,
    position=pos,
    tag='inspect',
)
result = run_grid_backtest(cfg)
bt = result.backtest_result
print(f"Status: {result.status}")
print(f"Total trades: {bt.total_trades}")
print(f"\nEquity curve keys (first): {list(bt.equity_curve[0].keys())}")
print(f"Equity curve sample (first 3):")
for ec in bt.equity_curve[:3]:
    print(f"  {ec}")
print(f"\nTrades count: {len(bt.trades)}")
if bt.trades:
    print(f"Trade keys (first): {list(bt.trades[0].keys())}")
    for t in bt.trades:
        print(f"  {t}")

# Also check from load_bars
bars = load_stock_bars('601857', '20260101', '20260514')
print(f"\nBars: {len(bars)} from {bars[0].date} to {bars[-1].date}")
print(f"Price range for {len(bars)} bars: {min(b.close for b in bars):.2f} - {max(b.close for b in bars):.2f}")
