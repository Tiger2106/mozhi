#!/usr/bin/env python3
"""
check_orders_fill_runner.py - Wrapper to run the check_orders_fill logic.
Bypasses encoding issues in the original file by importing the core functions directly.
"""
import sys, os, json, traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_SCRIPT_DIR)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

def main():
    timestamp = datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S %z')
    print(f"[check_orders_fill] Running at {timestamp}")
    
    try:
        from trading.core.run_settlement import run_settlement
        run_settlement()
        print("[check_orders_fill] Settlement completed successfully")
    except Exception as e:
        print(f"[check_orders_fill] Error during settlement: {e}")
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
