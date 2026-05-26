import sys
sys.path.insert(0, "src")

path = "src/backtest/tests/test_bitable_sync.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix test_build_record_all_fields
content = content.replace(
    'params = json.loads(record["parameters"])',
    'params = json.loads(record["params"])'
)

# Fix test_sync_with_normalized
old_normalized = '''self.assertEqual(record["normalized_params"], '{\"param_key\": \"param_value\"}')'''
new_normalized = '''self.assertEqual(record["source"], '{\"param_key\": \"param_value\"}')'''
if old_normalized in content:
    content = content.replace(old_normalized, new_normalized)
    print("Replaced normalized_params assertion")
else:
    print("normalized_params assertion not found, checking actual text...")
    idx = content.find("normalized_params")
    if idx >= 0:
        print(content[idx:idx+80])
    else:
        print("normalized_params not in file")

# Also fix test_sync_with_normalized code that checks record fields
content = content.replace(
    'record["normalized_params"]',
    'record["source"]'
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
