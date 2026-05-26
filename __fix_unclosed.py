import re

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'rb') as f:
    raw = f.read()

text = raw.decode('utf-8', errors='replace')
text = text.replace('\ufffd', '')
lines = text.split('\n')

# Fix line 155 (0-indexed 154): unclosed triple-quote
# Current: '    """\\u67e5\\u8be2\\u6307\\u5b9a\\u8d26\\u6237account_balance ""'
# Should be: '    """\\u67e5\\u8be2\\u6307\\u5b9a\\u8d26\\u6237account_balance """'
line155 = lines[154]
print(f'Line 155 before: {repr(line155)}')

# Check if it ends with '""' (two quotes) instead of '"""' (three)
if line155.endswith('""'):
    lines[154] = line155 + '"'
    print(f'Line 155 after: {repr(lines[154])}')

# Also check for similar patterns throughout the file
fixed_count = 0
for i, line in enumerate(lines):
    if '""' in line and '\""' not in line and '\""' not in line:
        # Check for docstrings that might be missing a quote
        pass

# Write back
text = '\n'.join(lines)
with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

# Now verify
with open(path, 'r', encoding='utf-8') as f:
    text2 = f.read()
try:
    compile(text2 + '\n', path, 'exec')
    print('SUCCESS: File now compiles!')
except SyntaxError as e:
    print(f'FAILED: {e} at line {e.lineno}')
    lines2 = text2.split('\n')
    if e.lineno and e.lineno <= len(lines2):
        print(f'Line: {repr(lines2[e.lineno - 1][:120])}')
