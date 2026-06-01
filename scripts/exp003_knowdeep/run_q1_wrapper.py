#!/usr/bin/env python3
"""Wrapper to run Q1 backtest with proper error handling and logging."""
import sys
import os
import traceback
import time
from datetime import datetime

# Add project root to path for import
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

start = time.time()
log_path = r"C:\Users\17699\mozhi_platform\exp003_wrapper_run.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

log("=" * 60)
log(f"启动 Q1 回测: {datetime.now().isoformat()}")
log(f"Python: {sys.version}")
log(f"CWD: {os.getcwd()}")

try:
    from scripts.exp003_knowdeep.run_exp003_q1 import main
    main(dry_run=False, skip_qc=True)
    elapsed = time.time() - start
    log(f"完成! 耗时: {elapsed:.1f}s")
    print(f"\n[DONE] 总耗时: {elapsed:.1f}s")
except Exception:
    elapsed = time.time() - start
    err = traceback.format_exc()
    log(f"失败! 耗时: {elapsed:.1f}s")
    log(f"错误:\n{err}")
    print(f"\n[FAIL] 耗时: {elapsed:.1f}s")
    print(err)
    sys.exit(1)
