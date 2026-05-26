"""Check stock price ranges and data availability"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from backtest.backtest_engine import Bar

def load_stock_bars(symbol, start_date="", end_date="", db_path=None):
    """Minimal data loader from reversal runner"""
    from backtest.strategies.run_reversal import load_stock_bars as ldr
    return ldr(symbol=symbol, start_date=start_date, end_date=end_date, db_path=db_path)

# Check 601857.SH price range
try:
    bars = load_stock_bars("601857", "", "")
    prices = [b.close for b in bars]
    print(f"601857: min={min(prices):.2f}, max={max(prices):.2f}, avg={sum(prices)/len(prices):.2f}, bars={len(bars)}")
except Exception as e:
    print(f"601857: {e}")

try:
    bars = load_stock_bars("000001.SZ", "", "")
    prices = [b.close for b in bars]
    print(f"000001.SZ: min={min(prices):.2f}, max={max(prices):.2f}, avg={sum(prices)/len(prices):.2f}, bars={len(bars)}")
except Exception as e:
    print(f"000001.SZ: {e}")
