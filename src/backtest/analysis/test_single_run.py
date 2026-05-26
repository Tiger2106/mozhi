"""Single backtest run test"""
import sys, os, time
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")
os.environ["DB_PATH"] = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

t0 = time.time()

from backtest.strategies.run_grid import run_grid_backtest, GridRunnerConfig
from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig
from backtest.strategies.grid_position import GridPositionManager, GridFixedPosition

# Simple config
# 601857 均价 ~10 元，网格范围 [8.5, 11.5]
signal = StaticGridSignal(grid_config=GridConfig(lower_bound=8.5, upper_bound=11.5, n_levels=5))
position = GridPositionManager(position_logic=GridFixedPosition(quantity=100))

cfg = GridRunnerConfig(
    symbol="601857",
    signal=signal,
    position=position,
    start_date="20260101",
    end_date="20260208",
)

print("Running single grid backtest...")
result = run_grid_backtest(cfg)
print(f"Status: {result.status}")
if result.status == "SUCCESS" and result.backtest_result:
    bt = result.backtest_result
    print(f"Trades: {bt.total_trades}")
    print(f"Sharpe: {bt.metrics.get('sharpe_ratio', 'N/A')}")
    print(f"Total Return: {bt.metrics.get('total_return_pct', 'N/A')}%")
    print(f"Win Rate: {bt.metrics.get('win_rate_pct', 'N/A')}%")
    print(f"Max DD: {bt.metrics.get('max_drawdown_pct', 'N/A')}%")
elif result.error:
    print(f"Error: {result.error}")

print(f"Time: {time.time()-t0:.1f}s")
