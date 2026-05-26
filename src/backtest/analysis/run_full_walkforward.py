"""Run full WalkForward analysis (Scheme C, 5 windows)"""
import sys, os, time
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")
os.environ["DB_PATH"] = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

from backtest.analysis.walk_forward import WalkForwardRunner

t0 = time.time()

print("=" * 60)
print("  WalkForward Full Analysis - P4 Phase 4b")
print("=" * 60)

runner = WalkForwardRunner(
    symbol="601857",
    start_date="20260101",
    end_date="20260514",
    scheme="C",
    max_workers=1,
)

result = runner.run()

t1 = time.time()

print(f"\n{'='*60}")
print(f"  WalkForward Analysis Complete")
print(f"{'='*60}")
print(f"  Symbol:      {result.symbol}")
print(f"  Scheme:      C (5 rolling windows)")
print(f"  Duration:    {t1-t0:.1f}s")
print(f"  Completed:   {result.completed_time}")
print()
print(f"  Key Metrics:")
print(f"    Avg WFE:       {result.avg_wfe:.4f}")
print(f"    WFE Std:       {result.wfe_std:.4f}")
print(f"    Param Reuse:   {result.param_reuse_rate:.2%}")
print(f"    Dominant:      {result.dominant_param_key}")
print(f"    Non-trading:   {result.non_trading_windows}/5")
print()
for wr in result.window_results:
    train_sharpe = wr.train_metrics.get('sharpe_ratio', 0.0) or 0.0
    test_sharpe = wr.test_metrics.get('sharpe_ratio', 0.0) or 0.0
    print(f"  Window {wr.fold.label}:")
    print(f"    Status:    {wr.status}")
    print(f"    Train:     {wr.optimal_params.get('config_key', 'N/A')}")
    print(f"    Train SR:  {train_sharpe:.4f}")
    print(f"    Test SR:   {test_sharpe:.4f}")
    print(f"    WFE:       {wr.wfe:.4f}")
    print(f"    Trades:    {wr.test_metrics.get('total_trades', 0)}")

# Save
output_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "results",
)
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, "walkforward_601857_C.json")
result.to_json(output_path)
print(f"\nResults saved to: {output_path}")
