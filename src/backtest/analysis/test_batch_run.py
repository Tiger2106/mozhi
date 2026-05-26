"""Test batch_run_grid with max_workers=1"""
import sys, os, time
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")
os.environ["DB_PATH"] = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

from backtest.strategies.run_grid import batch_run_grid
from backtest.strategies.scan_grid_params import _build_position
from backtest.strategies.grid_strategy import GridConfig, StaticGridSignal, GridVotingSignal
from backtest.strategies.run_grid import GridRunnerConfig

t0 = time.time()

bars = None

def _make_config(idx, gt, nl, cd, pm, sl, vt):
    avg_price = 10.23
    price_lower = round(avg_price * 0.95, 2)
    price_upper = round(avg_price * 1.05, 2)
    config = GridConfig(lower_bound=price_lower, upper_bound=price_upper, n_levels=nl, grid_type=gt)
    signal = StaticGridSignal(grid_config=config)
    if vt > 0.5:
        config2 = GridConfig(lower_bound=price_lower, upper_bound=price_upper, n_levels=nl, grid_type="geometric" if gt == "arithmetic" else "arithmetic")
        signal2 = StaticGridSignal(grid_config=config2)
        signal = GridVotingSignal(sub_grids=[signal, signal2], vote_threshold=vt)
    position = _build_position(position_mode=pm, stop_loss_pct=sl, cool_down_bars=cd)
    return GridRunnerConfig(symbol="601857", signal=signal, position=position, start_date="20260101", end_date="20260208", tag=f"walk_{idx}")

# Build 48 configs (smaller test)
configs = []
for i in range(48):
    gt = "arithmetic" if i % 2 == 0 else "geometric"
    nl = [5, 10, 15, 20][i % 4]
    cd = [1, 3, 5][i % 3]
    pm = ["fixed", "layer", "batcher"][i % 3]
    sl = [0.0, 0.03, 0.05][i % 3]
    vt = 0.5
    configs.append(_make_config(i, gt, nl, cd, pm, sl, vt))

print(f"Testing batch_run_grid with {len(configs)} configs, max_workers=1")
t1 = time.time()
results = batch_run_grid(configs, max_workers=1)
t2 = time.time()

success = sum(1 for r in results if r.status == "SUCCESS")
failed = sum(1 for r in results if r.status == "FAILED")
print(f"Results: {success} success, {failed} failed, time={t2-t1:.1f}s")

best_sharpe = -999.0
for i, r in enumerate(results):
    if r.status == "SUCCESS" and r.backtest_result:
        s = r.backtest_result.metrics.get("sharpe_ratio", 0.0) or 0.0
        if s > best_sharpe:
            best_sharpe = s
            best_idx = i

if best_sharpe > -999:
    print(f"Best: idx={best_idx}, sharpe={best_sharpe:.4f}")
    print(f"Config: {results[best_idx].config_key}")

print(f"Total time: {time.time()-t0:.1f}s")
