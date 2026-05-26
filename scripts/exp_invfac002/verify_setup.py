"""
EXP-2026-INVFAC-002 Step 2: Quick setup verification script.
Verifies data loading for all 12 stocks before dry-run.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

from scripts.exp_invfac002.run_exp_invfac002 import STOCK_CODES, DB_PATH, load_stock_data, FACTORS

print(f"DB_PATH: {DB_PATH}")
print(f"DB exists: {os.path.exists(DB_PATH)}")
print(f"STOCK_CODES ({len(STOCK_CODES)}): {STOCK_CODES}")
print()

all_ok = True
for code in STOCK_CODES:
    try:
        data = load_stock_data(code)
        n = len(data["dates"])
        print(f"  [{code}] {n} days, {data['dates'][0]}~{data['dates'][-1]}, "
              f"adj_latest={data['adj_factor_raw'][-1]:.4f}")
        if n < 200:
            print(f"    WARNING: only {n} days")
            all_ok = False
    except Exception as e:
        print(f"  [{code}] ERROR: {e}")
        all_ok = False

for fname, fcfg in FACTORS.items():
    print(f"  Factor: {fname}, func={fcfg['func'].__name__}, fields={fcfg['fields']}, params={fcfg['params']}")

print(f"\nAll 12/12 stocks loaded: {all_ok}")
