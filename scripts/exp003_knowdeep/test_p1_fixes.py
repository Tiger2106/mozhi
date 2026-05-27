"""
EXP-003 P1修复验证测试
======================
验证两项修复的正确性：
  1. 样本量门限自动降级
  2. 超时自检清单修复

运行方式:
  python scripts/exp003_knowdeep/test_p1_fixes.py
"""

import sys
import os
import json
import time
import io

# ── 控制台编码修复（Windows GBK 兼容） ──
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

# ── 项目路径 ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

print("=" * 60)
print("EXP-003 P1 修复验证测试")
print("=" * 60)

# ── 修复项1验证：样本量门限自动降级 ──
print("\n[Fix 1] 样本量门限自动降级")
print("-" * 40)

from scripts.exp_invfac002.exp_bootstrap import apply_verdict_degradation

THRESHOLD = 3000
LOW_N = 2500
HIGH_N = 5000

test_cases = [
    ("PASS", LOW_N, "WARN", "PASS->WARN: sample size insufficient"),
    ("WARN", LOW_N, "FAIL", "WARN->FAIL: sample size insufficient"),
    ("FAIL", LOW_N, "FAIL", "FAIL->FAIL: stays at FAIL"),
    ("PASS", HIGH_N, "PASS", "PASS->PASS: sufficient samples"),
    ("WARN", HIGH_N, "WARN", "WARN->WARN: sufficient samples"),
    ("FAIL", HIGH_N, "FAIL", "FAIL->FAIL: sufficient samples"),
    ("PASS", 3000, "PASS", "boundary: n=3000 no degradation"),
    ("PASS", 2999, "WARN", "boundary: n=2999 degradation"),
    ("NODATA", 2500, "NODATA", "unknown verdict preserved"),
]

all_passed = True
for i, (verdict, n, expected, desc) in enumerate(test_cases):
    result, note = apply_verdict_degradation(verdict, n, threshold=THRESHOLD)
    ok = result == expected
    if not ok:
        all_passed = False
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] Test {i+1}: {desc}")
    print(f"        Input(verdict={verdict}, n={n}) -> {result} (expected={expected})")
    if n < THRESHOLD:
        print(f"        Note: {note}")
    print()

# Verify degradation note keywords
for verdict in ["PASS", "WARN", "FAIL"]:
    result, note = apply_verdict_degradation(verdict, LOW_N)
    if verdict in ["PASS", "WARN"]:
        assert "\u68c0\u9a8c\u529b\u53d7\u9650" in note, f"Expected note to contain '\u68c0\u9a8c\u529b\u53d7\u9650', got: {note}"
        assert "\u81ea\u52a8\u964d\u7ea7" in note, f"Expected note to contain '\u81ea\u52a8\u964d\u7ea7', got: {note}"

print(f"  Degradation note keyword verification: PASS")
print(f"\nFix 1 Summary: {'ALL PASS' if all_passed else 'SOME FAILED'}")

# ── 修复项2验证：超时自检清单 ──
print("\n[Fix 2] \u8d85\u65f6\u81ea\u68c0\u6e05\u5355")
print("-" * 40)

from scripts.exp003_knowdeep.self_check import check_timeout

# Scenario 1: 77 minutes > 40 minutes threshold
print("[Scenario 1] Actual 77min > threshold 40min")
result = check_timeout(elapsed_seconds=77*60, threshold_seconds=2400)
ok = result["is_timeout"] and not result["passed"]
status = "PASS" if ok else "FAIL"
print(f"  [{status}] is_timeout={result['is_timeout']}")
print(f"       passed={result['passed']}")
print(f"       elapsed={result['elapsed_formatted']} (77m)")
print(f"       threshold={result['threshold_formatted']} (40m)")
print(f"       note={result['note']}")
assert result["is_timeout"] == True, f"Expected timeout, got is_timeout={result['is_timeout']}"
assert "\u8d85\u65f6" in result["note"], f"Expected note to contain '\u8d85\u65f6', got: {result['note']}"
print(f"  Assertions: PASS")
print()

# Scenario 2: 30 minutes < 40 minutes threshold
print("[Scenario 2] Actual 30min < threshold 40min")
result = check_timeout(elapsed_seconds=30*60, threshold_seconds=2400)
ok = not result["is_timeout"] and result["passed"]
status = "PASS" if ok else "FAIL"
print(f"  [{status}] is_timeout={result['is_timeout']}")
print(f"       passed={result['passed']}")
print(f"       elapsed={result['elapsed_formatted']} (30m)")
print(f"       threshold={result['threshold_formatted']} (40m)")
print(f"       note={result['note']}")
assert result["is_timeout"] == False, f"Expected no timeout, got is_timeout={result['is_timeout']}"
print(f"  Assertions: PASS")
print()

# Scenario 3: Boundary 40 minutes
print("[Scenario 3] Boundary: actual 40min = threshold 40min")
result = check_timeout(elapsed_seconds=2400, threshold_seconds=2400)
ok = not result["is_timeout"] and result["passed"]
status = "PASS" if ok else "FAIL"
print(f"  [{status}] is_timeout={result['is_timeout']}")
print(f"       passed={result['passed']}")
print(f"       elapsed={result['elapsed_formatted']} (40m)")
print(f"       note={result['note']}")
assert result["is_timeout"] == False, f"Boundary should not timeout, got is_timeout={result['is_timeout']}"
print(f"  Assertions: PASS")
print()

# Scenario 4: Q1 replay - 77min 34s > 40min
print("[Scenario 4] Q1 replay: 77m34s > 40min threshold")
elapsed_77min = 77*60 + 34
result = check_timeout(elapsed_seconds=elapsed_77min, threshold_seconds=2400)
ok = result["is_timeout"] and not result["passed"]
status = "PASS" if ok else "FAIL"
print(f"  [{status}] is_timeout={result['is_timeout']}")
print(f"       elapsed={result['elapsed_formatted']}")
print(f"       note={result['note']}")
assert result["is_timeout"] == True, "Q1 77min runtime should be marked as timeout"
print(f"  Assertions: PASS")

# ── 综合结论 ──
print("\n" + "=" * 60)
if all_passed:
    print("EXP-003 P1 两项修复验证: ALL PASS")
else:
    print("EXP-003 P1 两项修复验证: SOME FAILED")
print("=" * 60)

sys.exit(0 if all_passed else 1)
