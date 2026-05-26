import sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'rb') as f:
    raw = f.read()

text = raw.decode('utf-8', errors='replace')
text = text.replace('\ufffd', '')
lines = text.split('\n')

# Track triple-quote balance
# We need to be smarter: track in what context triple quotes appear
# For simplicity, let's just find where the unclosed triple-quote starts

# Look for docstrings that weren't closed
in_triple = False
triple_start_line = -1
for i in range(172):
    line = lines[i]
    # Count triple double-quotes - simple approach
    # In real parsing we'd need to handle strings inside strings, etc.
    # But for docstrings at line start, this usually works
    idx = 0
    while True:
        pos = line.find('"""', idx)
        if pos == -1:
            break
        # Check if this is inside a single-quoted string - skip for simplicity
        in_triple = not in_triple
        if in_triple:
            triple_start_line = i
        idx = pos + 3

if in_triple:
    print(f'Unclosed triple-quote started at line {triple_start_line + 1}')
    # Show the opening line
    print(f'Opening: {repr(lines[triple_start_line])}')
    # Show surrounding lines
    for i in range(max(0, triple_start_line-2), min(len(lines), triple_start_line+3)):
        m = ' <-- START' if i == triple_start_line else ''
        print(f'{i+1}: {repr(lines[i][:100])}{m}')