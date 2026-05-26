"""Extract METHOD_META from all method files."""
import os, re
base = r'C:\Users\17699\mozhi_platform\src\backtest\methods'
methods = [
    'grid/grid_method.py',
    'momentum/bias_method.py',
    'momentum/kdj_method.py',
    'momentum/rsi_method.py',
    'reversal/reversal_method.py',
    'trend/bollinger_method.py',
    'trend/macd_method.py',
    'trend/ma_cross_method.py',
    'trend/volume_profile_method.py',
    'trend/wyckoff_method.py',
]

for m in methods:
    path = os.path.join(base, m)
    if not os.path.isfile(path):
        print(f'=== {m} === FILE NOT FOUND')
        continue
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f'\n=== {m} ===')
    # Extract METHOD_META block
    m2 = re.search(r'METHOD_META\s*=\s*\{', content)
    if not m2:
        print('  No METHOD_META found')
        continue

    # Find matching closing brace
    start = m2.end() - 1
    depth = 0
    end = start
    for i in range(start, len(content)):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    meta_str = content[start:end+1]
    # Print first 30 lines
    lines = meta_str.split('\n')
    for l in lines[:30]:
        print(f'  {l}')
    
    # Also show setup params
    setup_match = re.search(r'def setup\(self.*?ctx\).*?:(.*?)(?:def generate_signal|def cleanup)', content, re.DOTALL)
    if setup_match:
        setup_body = setup_match.group(1)[:200]
        print(f'  --- setup params ---')
        for l in setup_body.split('\n'):
            if 'ctx.' in l or 'self.' in l or 'params' in l:
                print(f'  {l.strip()[:120]}')
