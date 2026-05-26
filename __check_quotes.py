import sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'rb') as f:
    raw = f.read()

text = raw.decode('utf-8', errors='replace')
text = text.replace('\ufffd', '')
lines = text.split('\n')

print(f'Total lines: {len(lines)}')

# Check for quote balance before line 173
# Count unescaped triple quotes
quote_count = 0
in_triple = False
for i in range(172):  # lines before line 173
    line = lines[i]
    # Count triple double-quotes
    triple_dq = line.count('"""')
    if triple_dq % 2 == 1:
        in_triple = not in_triple

print(f'After line 172, in_triple_string: {in_triple}')

# Actually, let me look at lines 160-180
for i in range(max(0, 160), min(len(lines), 180)):
    line = lines[i]
    triple_dq = line.count('"""')
    marker = ' <-- TRIPLE' if triple_dq > 0 else ''
    print(f'{i+1}: {repr(line[:100])}{marker}')
