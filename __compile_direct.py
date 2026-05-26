import sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'

with open(path, 'rb') as f:
    content = f.read()

text = content.decode('utf-8')

# Try to compile
try:
    code = compile(text + '\n', path, 'exec')
    print('Compiled OK!')
except SyntaxError as e:
    print(f'SyntaxError: {e}')
    print(f'Line: {e.lineno}, Offset: {e.offset}')
    if e.lineno:
        lines = text.split('\n')
        the_line = lines[e.lineno - 1]
        print(f'Line content (first 120 chars): {repr(the_line[:120])}')
        print(f'Hex around offset: ')
        for i, c in enumerate(the_line):
            if i >= (e.offset or 0) - 5 and i <= (e.offset or 0) + 5:
                print(f'  pos {i}: U+{ord(c):04X} ({c!r})')
