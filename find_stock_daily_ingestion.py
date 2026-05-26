"""搜索写入 stock_daily 表的代码"""
import os

scripts = [
    r'C:\Users\17699\mozhi_platform\src\backtest\data_loader.py',
    r'C:\Users\17699\mozhi_platform\src\backtest\data_filler.py',
    r'C:\Users\17699\mozhi_platform\backtest_engine\data_ingestion\etl_normalizer.py',
    r'C:\Users\17699\mozhi_platform\scripts\phase1_data_collection.py',
]

root = r'C:\Users\17699\mozhi_platform'

for script in scripts:
    if os.path.exists(script):
        rel = os.path.relpath(script, root)
        print(f'=== {rel} ===')
        with open(script, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if 'stock_daily' in line.lower():
                start = max(0, i-2)
                end = min(len(lines), i+3)
                for j in range(start, end):
                    print(f'  L{j+1}: {lines[j]}', end='')
                print()
        print()

# Also search for data ingestion of stock_daily in data_contract.py
contract = r'C:\Users\17699\mozhi_platform\backtest_engine\data_ingestion\data_contract.py'
if os.path.exists(contract):
    print(f'=== data_contract.py (stock_daily lines) ===')
    with open(contract, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if 'stock_daily' in line.lower():
            start = max(0, i-1)
            end = min(len(lines), i+2)
            for j in range(start, end):
                print(f'  L{j+1}: {lines[j]}', end='')
            print()
