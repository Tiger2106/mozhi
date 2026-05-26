# -*- coding: utf-8 -*-
"""Debug: check run_multi benchmark behavior."""
import sys, sqlite3
sys.path.insert(0, r"C:\Users\17699\mozhi_platform")

from pathlib import Path
from backtest.backtest_engine import Bar
from backtest.strategies.multi_runner import MultiStrategyRunner, MultiStrategyConfig, StrategyConfig
from backtest.strategies.trend_strategy import TrendStrategy
from backtest.strategies.grid_strategy import GridConfig
from backtest.strategies.run_grid import GridStrategy

DB_PATH = Path(r"C:\Users\17699\mo_zhi_sharereports\analysis.db")
conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute("SELECT * FROM stock_daily WHERE code = ? ORDER BY date", ("601857",)).fetchall()
conn.close()

def mb(r):
    _, ds, op, hi, lo, cl, vo, am = r[:8]
    return Bar(date=ds, symbol="601857", open=op, high=hi, low=lo, close=cl, volume=vo)

bars = [mb(r) for r in rows]
bars_rep = [b for b in bars if "20260105" <= b.date <= "20260514"]
print("Period bars:", len(bars_rep))

config = MultiStrategyConfig(symbol="601857", start_date="20260105", end_date="20260514",
                              initial_capital=1_000_000.0)
runner = MultiStrategyRunner(config=config)

bench_eq = MultiStrategyRunner.compute_benchmark_equity(bars_rep, initial_capital=500_000.0)
print("benchmark_equity:", type(bench_eq), "len:", len(bench_eq))
print("  first:", bench_eq[0], "last:", bench_eq[-1])

ts = TrendStrategy(signal_type="crossover", ma_fast=5, ma_slow=20)
gs = GridStrategy(grid_config=GridConfig(lower_bound=95, upper_bound=105, n_levels=10))

result = runner.run_multi(
    strategies={"trend": StrategyConfig(strategy=ts), "grid": StrategyConfig(strategy=gs)},
    bars=bars_rep,
    benchmark_equity=bench_eq,
    benchmark_name="中国石油(买入持有)",
)

cr = result.combined
print("\nCombined result:")
print("  benchmark_name:", repr(cr.benchmark_name))
print("  benchmark_total_return:", cr.benchmark_total_return)
if cr.equity_curve is not None:
    ec = cr.equity_curve
    print("  equity_curve columns:", list(ec.columns))
    print("  equity_curve rows:", len(ec))
    has_bm = "benchmark_equity" in ec.columns
    print("  has benchmark_equity column:", has_bm)
    if has_bm:
        print("  benchmark_equity range:", ec["benchmark_equity"].iloc[0], "~", ec["benchmark_equity"].iloc[-1])
else:
    print("  equity_curve is None")
