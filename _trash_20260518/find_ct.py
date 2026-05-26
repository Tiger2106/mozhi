import sys

path = "src/backtest/tests/test_bitable_sync.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "record[\"completed_time\"]" in line or "record['completed_time']" in line:
        print(f"Line {i+1}: {line.rstrip()[:120]}")
