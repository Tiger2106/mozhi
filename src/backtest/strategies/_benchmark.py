import sys, time, os
sys.path.insert(0, r'C:\Users\17699\mo_zhi_sharereports')
os.chdir(r'C:\Users\17699\mo_zhi_sharereports')

from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig
from backtest.strategies.grid_position import GridPositionManager, GridFixedPosition, GridCoolDown
from backtest.strategies.run_grid import GridRunnerConfig, run_grid_backtest

signal = StaticGridSignal(
    grid_config=GridConfig(lower_bound=8.5, upper_bound=11.5, n_levels=10, grid_type='arithmetic')
)
pos = GridPositionManager(
    position_logic=GridFixedPosition(quantity=200),
    cool_down=GridCoolDown(cool_down_bars=3),
)
cfg = GridRunnerConfig(
    symbol='601857',
    start_date='20260101',
    end_date='20260514',
    signal=signal,
    position=pos,
    tag='benchmark',
)

t0 = time.time()
result = run_grid_backtest(cfg)
t = time.time() - t0
print(f'Time: {t:.3f}s')
print(f'Status: {result.status}')
if result.backtest_result:
    print(f'Trades: {result.backtest_result.total_trades}')
    print(f'Metrics: {result.metrics}')
