import sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'r', encoding='utf-8', errors='replace') as f:
    text = f.read()
text = text.replace('\ufffd', '')
lines = text.split('\n')

# Check quote balance per line (count " chars and look for unterminated strings)
fixed_anything = False
for i in range(len(lines)):
    line = lines[i]
    
    # Skip single-line full comment lines: if stripped starts with #
    stripped = line.strip()
    
    # Check for docstrings (triple quotes)
    triple_count = line.count('"""')
    
    # Check for single-line string issues
    # Look for lines ending with unclosed quote patterns
    # Pattern: something like `"error": "text` without closing quote
    double_quote_count = line.count('"')
    
    if double_quote_count % 2 == 1 and triple_count == 0:
        # Odd number of double quotes - likely missing one
        # Only fix if it ends with a non-quote character (unterminated string at EOL)
        if not line.rstrip('\r').endswith('"') and not stripped.startswith('#'):
            # Check if this line's content suggests a broken string
            # Look for colon followed by space followed by opening quote
            # e.g., "error": "some text
            # Add a closing quote
            lines[i] = line.rstrip('\r') + '",'
            print(f'Fixed odd quotes line {i+1}: {repr(line[:80])}')
            fixed_anything = True

# Write back
text = '\n'.join(lines)
with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

if not fixed_anything:
    print('No odd quote issues found')

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
        # Show surrounding lines
        for j in range(max(0, e.lineno-3), min(len(lines2), e.lineno+2)):
            m = ' <--' if j == e.lineno-1 else ''
            print(f'{j+1}: {repr(lines2[j][:120])}{m}')
