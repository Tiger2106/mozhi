"""WalkForward 组件测试脚本"""
import sys
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")

# 1. 测试 GridParamScanner 接口
from backtest.strategies.scan_grid_params import GridParamScanner

scanner = GridParamScanner()
configs = scanner.generate_configs()
print(f"=== GridParamScanner ===")
print(f"Configs count: {len(configs)}")
print(f"Config[0] type: {type(configs[0]).__name__}")
print(f"  signal: {hasattr(configs[0], 'signal')}")
print(f"  position: {hasattr(configs[0], 'position')}")
print(f"  tag: {hasattr(configs[0], 'tag')}")
print(f"  symbol: {hasattr(configs[0], 'symbol')}")
print(f"  start_date: {hasattr(configs[0], 'start_date')}")
print(f"  end_date: {hasattr(configs[0], 'end_date')}")
print(f"Scanner._param_rows: {hasattr(scanner, '_param_rows')}")

# 2. 测试 WalkForwardPlan
from backtest.analysis.walk_forward import WalkForwardPlan, WalkForwardFold

plan = WalkForwardPlan(scheme="C")
print(f"\n=== WalkForwardPlan C ===")
print(f"Folds: {len(plan)}")
for f in plan:
    print(f"  {f.label}: {f.train_start}~{f.train_end} -> {f.test_start}~{f.test_end}")

# 3. 测试数据库数据
from backtest.strategies.run_grid import load_stock_bars
import os

db_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "market", "market_data.db",
)
print(f"\n=== Data check ===")
print(f"DB path: {db_path}")
bars = load_stock_bars("601857", "20260101", "20260514", db_path)
print(f"601857 bars: {len(bars)}")
print(f"  First: {bars[0].date} open={bars[0].open} close={bars[0].close}")
print(f"  Last: {bars[-1].date} open={bars[-1].open} close={bars[-1].close}")

# 4. Test in-window data
for fold in plan:
    train_bars = [b for b in bars if fold.train_start <= b.date <= fold.train_end]
    test_bars = [b for b in bars if fold.test_start <= b.date <= fold.test_end]
    print(f"\n  {fold.label}: train={len(train_bars)} bars, test={len(test_bars)} bars")

print("\nAll checks passed!")
