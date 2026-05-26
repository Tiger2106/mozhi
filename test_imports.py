"""Quick imports check"""
from backtest.backtest_engine import BacktestEngine, BacktestConfig, Bar, Strategy, OrderRequest, OrderSide, OrderType
from backtest.strategies.trend_strategy import TrendStrategy
from backtest.strategies.reversal_strategy import ReversalStrategy, generate_rsi_signals
from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig
from backtest.strategies.run_trend import TrendBacktestConfig
from backtest.strategies.run_reversal import ReversalBacktestConfig
from backtest.strategies.run_grid import GridRunnerConfig
from backtest.strategies.multi_runner import MultiStrategyRunner, MultiStrategyConfig, StrategyConfig
from backtest.benchmark_data_source import calc_buy_hold_return

print("All imports successful!")

# Check Bar structure
import inspect
if hasattr(Bar, '__dataclass_fields__'):
    print(f"Bar dataclass fields: {list(Bar.__dataclass_fields__.keys())}")

# Check TrendStrategy
ts = TrendStrategy(signal_type="ma", signal_params={"ma_fast": 5, "ma_slow": 20})
print(f"TrendStrategy instantiated: {type(ts).__name__}")

# Try loading data from SQLite
import sqlite3, os
db = os.path.join(os.environ.get('USERPROFILE','C:/Users/17699'), 'mo_zhi_sharereports', 'analysis.db')
conn = sqlite3.connect(db)

# Load all 601857 bars as Bar objects
def make_bar(row):
    code, date_str, open_p, high, low, close, vol, amt = row[:8]
    from datetime import datetime
    dt = datetime.strptime(date_str, '%Y%m%d')
    return Bar(
        date=dt,
        open=open_p,
        high=high,
        low=low,
        close=close,
        volume=vol,
    )

cursor = conn.execute(
    "SELECT * FROM stock_daily WHERE code = ? ORDER BY date", 
    ('601857',)
)
rows = cursor.fetchall()
bars_raw = [make_bar(r) for r in rows]
print(f"Loaded {len(bars_raw)} bars for 601857 from SQLite")
print(f"Date range: {bars_raw[0].date.strftime('%Y-%m-%d')} ~ {bars_raw[-1].date.strftime('%Y-%m-%d')}")

# Test benchmark data source
bh = calc_buy_hold_return(symbol="601857", name="中国石油", start_date="2026-01-05", end_date="2026-05-14")
if bh:
    print(f"Benchmark data: {bh}")
else:
    print("Benchmark data: None (calc_buy_hold_return failed)")

# Run multi-strategy backtest  
# Filter bars to match report period: 2026-01-05 to 2026-05-14
from datetime import datetime
bars_subset = [b for b in bars_raw if datetime(2026, 1, 5) <= b.date <= datetime(2026, 5, 14)]
print(f"Filtered bars for report period: {len(bars_subset)}")

# Note: This may take some time to run  
print("All pre-checks passed! Ready to run full backtest.")
