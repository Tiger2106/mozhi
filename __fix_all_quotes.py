import sys, re

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'r', encoding='utf-8', errors='replace') as f:
    text = f.read()
text = text.replace('\ufffd', '')
lines = text.split('\n')

# Find all docstrings (triple-quoted strings used as function docstrings)
# and check for the pattern: starts with '    """' and ends with '"""'
# If one ends with '""' (two quotes), add the third quote
fixed_lines = []
for i, line in enumerate(lines):
    stripped = line.strip()
    # Check if this is a docstring line that should end with """
    if stripped.startswith('"""') and stripped.endswith('""') and not stripped.endswith('"""'):
        # This is likely missing the closing quote
        lines[i] = line + '"'
        print(f'Fixed line {i+1}: {repr(line[:80])}')

# Write back
text = '\n'.join(lines)
with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

# Verify
with open(path, 'r', encoding='utf-8') as f:
    text2 = f.read()
try:
    compile(text2 + '\n', path, 'exec')
    print('SUCCESS!')
except SyntaxError as e:
    print(f'FAILED: {e} at line {e.lineno}')
    lines2 = text2.split('\n')
    if e.lineno and e.lineno <= len(lines2):
        print(f'Line: {repr(lines2[e.lineno - 1][:120])}')
