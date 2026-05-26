import sys, io

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'rb') as f:
    content = f.read()

text = content.decode('utf-8')

# Write to a temp file first, then try to compile it
import tempfile, os
tmp = os.path.join(tempfile.gettempdir(), '_test_check_orders.py')
with open(tmp, 'w', encoding='utf-8') as f:
    f.write(text)

# Try to compile from the temp file
try:
    with open(tmp, 'rb') as f:
        source = f.read()
    compile(source, tmp, 'exec')
    print('Compiled OK from temp file')
except SyntaxError as e:
    print(f'Syntax error in temp file: {e}')
    print(f'Line: {e.lineno}')
