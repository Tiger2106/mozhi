#!/usr/bin/env python3
"""Retest all stocks that had proxy errors"""
import os
os.environ['NO_PROXY'] = '*'

import akshare as ak
import pandas as pd
import json, time
from datetime import datetime

targets = [
    '600276','600887','600030','600028','601088','600585','600690','601398',
    '600000','600016','688981','000333','002714','300059','000651','002142',
    '000100','002013','300124','000538','002049','002352','300782','002916',
    '300274','002129'
]

total_ok = 0
results = {}

for i, code in enumerate(targets):
    time.sleep(0.8)
    print(f"  [{i+1}/{len(targets)}] {code} ... ", end="", flush=True)
    try:
        df = ak.stock_zh_a_hist(symbol=code, period='daily', start_date='20230101', end_date='20260525', adjust='')
        if df is not None and len(df) > 0:
            total_ok += 1
            r = {'code': code, 'ok': True, 'rows': len(df)}
            for c in ['日期', 'date', 'Date']:
                if c in df.columns:
                    df[c] = pd.to_datetime(df[c])
                    r['earliest'] = df[c].min().strftime('%Y-%m-%d')
                    r['latest'] = df[c].max().strftime('%Y-%m-%d')
                    break
            results[code] = r
            print(f"OK {r['rows']} rows [{r['earliest']}, {r['latest']}]")
        else:
            results[code] = {'code': code, 'ok': False, 'error': 'empty data'}
            print("EMPTY")
    except Exception as e:
        results[code] = {'code': code, 'ok': False, 'error': str(e)[:200]}
        print(f"ERR: {str(e)[:80]}")

print(f"\nRetest OK: {total_ok}/{len(targets)}")

out = r'C:\Users\17699\mozhi_platform\docs\07_research\a50_retest_results.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"Saved to {out}")
