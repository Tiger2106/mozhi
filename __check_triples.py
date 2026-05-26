import sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'r', encoding='utf-8', errors='replace') as f:
    text = f.read()
text = text.replace('\ufffd', '')
lines = text.split('\n')

# Find ALL unclosed triple-quotes
in_triple = False
triple_lines = []
for i, line in enumerate(lines):
    count = line.count('"""')
    if count > 0:
        if count % 2 == 1:
            if not in_triple:
                triple_lines.append(('OPEN', i, line))
                in_triple = True
            else:
                triple_lines.append(('CLOSE', i, line))
                in_triple = False

if in_triple:
    print(f'STILL UNCLOSED at end of file!')
    
print(f'\nAll triple-quote lines:')
for t, i, line in triple_lines:
    print(f'{t} line {i+1}: {repr(line[:120])}')
