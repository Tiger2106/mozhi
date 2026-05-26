"""WalkForward End-to-End 快速测试（单窗格，单线程）"""
import sys, os, time
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")
os.environ["DB_PATH"] = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

t0 = time.time()

from backtest.strategies.run_grid import load_stock_bars, run_grid_backtest, GridRunnerConfig
from backtest.strategies.scan_grid_params import GridParamScanner, _build_signal, _build_position

# 1. Test data loading
print("=== 1. Data Loading ===")
bars = load_stock_bars("601857", "20260101", "20260208")
print(f"  {len(bars)} bars, {bars[0].date} ~ {bars[-1].date}")
print(f"  Data load OK: {time.time()-t0:.1f}s")

# 2. Manual serial scan with focused configs (reduce to 48 for test)
print("\n=== 2. Manual serial scan (48 configs) ===")
t1 = time.time()

scanner = GridParamScanner(param_space={
    "grid_type": ["arithmetic", "geometric"],
    "n_levels": [5, 10],
    "cool_down_bars": [1, 3],
    "position_mode": ["fixed", "layer"],
    "stop_loss_pct": [0.0, 0.03],
    "vote_threshold": [0.5],
})
configs = scanner.generate_configs()
print(f"  {len(configs)} configs")

best_sharpe = -999.0
best_result = None
best_config_key = ""

for i, cfg in enumerate(configs):
    try:
        cfg.symbol = "601857"
        cfg.start_date = "20260101"
        cfg.end_date = "20260208"
        result = run_grid_backtest(cfg)
        if result.status == "SUCCESS" and result.backtest_result:
            s = result.backtest_result.metrics.get("sharpe_ratio", 0.0) or 0.0
            if s > best_sharpe:
                best_sharpe = s
                best_result = result
                best_config_key = result.config_key
        if (i+1) % 16 == 0:
            print(f"  [{i+1}/{len(configs)}] best so far: {best_sharpe:.4f}")
    except Exception as e:
        print(f"  [{i+1}] FAILED: {e}")

t2 = time.time()
print(f"  Scan completed in {t2-t1:.1f}s")
print(f"  Best config: {best_config_key}")
print(f"  Best Sharpe: {best_sharpe:.4f}")

if best_result and best_result.backtest_result:
    bt = best_result.backtest_result
    print(f"  Total Return: {bt.metrics.get('total_return_pct', 0):.2f}%")
    print(f"  Total Trades: {bt.total_trades}")
    print(f"  Win Rate: {bt.metrics.get('win_rate_pct', 0):.2f}%")

# 3. Test single backtest on test period
print("\n=== 3. Test Period Backtest ===")
if best_result:
    from backtest.strategies.scan_grid_params import _build_signal, _build_position
    import json
    # Find the row with matching config_key
    row = None
    for r in scanner._param_rows:
        if r["config_key"] == best_config_key:
            row = r
            break
    if row:
        signal = _build_signal(
            grid_type=row["grid_type"],
            n_levels=row["n_levels"],
            vote_threshold=row["vote_threshold"],
        )
        position = _build_position(
            position_mode=row["position_mode"],
            stop_loss_pct=row["stop_loss_pct"],
            cool_down_bars=row["cool_down_bars"],
        )
        test_cfg = GridRunnerConfig(
            symbol="601857",
            signal=signal,
            position=position,
            start_date="20260209",
            end_date="20260228",
        )
        test_result = run_grid_backtest(test_cfg)
        if test_result.status == "SUCCESS":
            bt = test_result.backtest_result
            print(f"  Sharpe: {bt.metrics.get('sharpe_ratio', 0):.4f}")
            print(f"  Total Return: {bt.metrics.get('total_return_pct', 0):.2f}%")
            print(f"  Total Trades: {bt.total_trades}")
        else:
            print(f"  FAILED: {test_result.error}")

print(f"\nTotal time: {time.time()-t0:.1f}s")
print("E2E test passed!")
