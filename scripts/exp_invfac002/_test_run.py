"""Test: Run the full pipeline step by step."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

print("=== Data Loading Test ===", flush=True)
from scripts.exp_invfac002.run_exp_invfac002 import load_stock_data, STOCK_CODES, DB_PATH
print(f"DB: {DB_PATH}", flush=True)
print(f"DB exists: {os.path.exists(DB_PATH)}", flush=True)

for code in STOCK_CODES:
    data = load_stock_data(code)
    n = len(data["dates"])
    print(f"  {code}: {n} days, {data['dates'][0]}~{data['dates'][-1]}", flush=True)

print("\n=== Factor Calculation Test ===", flush=True)
from scripts.exp_invfac002.exp_factors import calc_trend_quality
from scripts.exp_invfac002.exp_market_state import classify_market_state

# Test just one stock
d = load_stock_data(STOCK_CODES[0])
tq = calc_trend_quality(d["high"], d["low"], d["close"], period=20)
print(f"  TrendQuality: {len(tq)} values, nan={sum(1 for v in tq if v is None or (hasattr(v, 'shape') and not v.shape))}", flush=True)

# Test classify_market_state
states, hi, lo = classify_market_state(d["close"])
print(f"  Market states: {sum(states==0)} low, {sum(states==1)} mid, {sum(states==2)} high", flush=True)

print("\nAll basic tests passed!", flush=True)
