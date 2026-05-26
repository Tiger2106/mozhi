import sys

path = "src/backtest/tests/test_bitable_sync.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix lines 268-270: indentation broken
old_block = """                    if field_name in ("signal_ratio", "n_trades"):
            continue
self.assertIn(field_name, record, f"""

new_block = """            if field_name in ("signal_ratio", "n_trades"):
                continue
            self.assertIn(field_name, record, f"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Indentation fixed")
else:
    print("Pattern not found")
    idx = content.find('if field_name in ("signal_ratio"')
    if idx >= 0:
        print("Found at", idx)
        print(repr(content[idx:idx+200]))
