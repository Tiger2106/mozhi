"""Fix field name assertions in test_bitable_sync.py to match actual table."""
import sys
sys.path.insert(0, "src")

path = "src/backtest/tests/test_bitable_sync.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

replacements = [
    ('record["insight_category"], "regime_insight"',
     'record["category"], "regime_insight"'),
    ('record["sharpe"], 1.5',
     'record["sharpe_ratio"], 1.5'),
    ('record["parameters"], expected_params',
     'record["params"], expected_params'),
    ('record["statistics"], expected_stats',
     'record["extra"], expected_stats'),
    ('record["normalized_params"], expected_norm',
     'record["source"], expected_norm'),
    ('self.assertIn("review_status", record)\n        self.assertEqual(record["review_status"], "pending")',
     'self.assertNotIn("review_status", record)'),
]

for old, new in replacements:
    count = content.count(old)
    if count > 0:
        content = content.replace(old, new)
        print(f"Replaced {count} x {old[:30]}... -> {new[:30]}...")
    else:
        print(f"NOT FOUND: {old[:40]}...")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("\nDone")
