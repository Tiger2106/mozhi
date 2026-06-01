#!/usr/bin/env python3
"""Retry remaining failed stocks with longer delays and more retries"""
import os
os.environ['NO_PROXY'] = '*'

import akshare as ak
import json, time
from datetime import datetime, timedelta
import random

# Stocks still needing data
targets = {
    '600276': {'exchange': 'SH'},
    '600887': {'exchange': 'SH'},
    '600030': {'exchange': 'SH'},
    '600028': {'exchange': 'SH'},
    '601088': {'exchange': 'SH'},
    '600585': {'exchange': 'SH'},
    '600690': {'exchange': 'SH'},
    '600000': {'exchange': 'SH'},
    '600016': {'exchange': 'SH'},
    '688981': {'exchange': 'SH', 'expected': '2021-01'},
    '002142': {'exchange': 'SZ'},
    '000100': {'exchange': 'SZ'},
    '002013': {'exchange': 'SZ'},
    '300124': {'exchange': 'SZ'},
    '000538': {'exchange': 'SZ'},
    '002049': {'exchange': 'SZ'},
    '002352': {'exchange': 'SZ', 'expected': '2014-01'},
    '300782': {'exchange': 'SZ'},
    '002916': {'exchange': 'SZ'},
    '300274': {'exchange': 'SZ'},
    '002129': {'exchange': 'SZ'},
}

results = {}

for code in targets:
    for attempt in range(3):
        delay = 2.5 + random.uniform(0, 1)
        time.sleep(delay)
        try:
            df = ak.stock_zh_a_hist(symbol=code, period='daily', start_date='20230101', end_date='20260525', adjust='')
            if df is not None and len(df) > 0:
                r = {'code': code, 'ok': True, 'rows': len(df)}
                for c in ['日期', 'date', 'Date']:
                    if c in df.columns:
                        df[c] = pd.to_datetime(df[c])
                        r['earliest'] = df[c].min().strftime('%Y-%m-%d')
                        r['latest'] = df[c].max().strftime('%Y-%m-%d')
                        break
                results[code] = r
                print(f"OK {code}: {r['rows']} rows [{r['earliest']}, {r['latest']}] (attempt {attempt+1})")
                break
            else:
                results[code] = {'code': code, 'ok': False, 'error': 'empty'}
                print(f"EMPTY {code} (attempt {attempt+1})")
        except Exception as e:
            err = str(e)[:150]
            if attempt < 2:
                print(f"  retry {code} (attempt {attempt+1}): {err[:60]}...")
            else:
                results[code] = {'code': code, 'ok': False, 'error': err}
                print(f"FAIL {code} (attempt {attempt+1}): {err[:80]}")

print(f"\nRetry results: {len(results)}")

with open(r'C:\Users\17699\mozhi_platform\docs\07_research\a50_retry2_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("Done.")
