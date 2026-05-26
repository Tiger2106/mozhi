import sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'rb') as f:
    content = f.read()

# Check first few bytes for BOM
print(f'First bytes: {content[:10]}')

# Check encoding declaration
first_lines = content[:200].decode('utf-8', errors='replace')
print(f'First lines: {repr(first_lines[:150])}')

# Split into lines
lines = content.split(b'\n')
line173 = lines[172]

print(f'\nLine 173 bytes ({len(line173)}):')
print(repr(line173))

# Find U+FF0C bytes
idx = line173.find(b'\xef\xbc\x8c')
if idx >= 0:
    chunk = line173[max(0, idx-10):min(len(line173), idx+15)]
    print(f'\nContext bytes: {repr(chunk)}')
    print(f'Context hex: {chunk.hex()}')

    # Decode 3 bytes as UTF-8
    test = line173[idx:idx+3]
    print(f'3 bytes: {repr(test)} = {test.decode("utf-8")!r}')
    print(f'Unicode code point: U+{ord(test.decode("utf-8")):04X}')
