#!/usr/bin/env python3
"""Check stock code existence using spot API"""
import os
os.environ['NO_PROXY'] = '*'
import akshare as ak

try:
    df = ak.stock_zh_a_spot_em()
    codes = set(df['代码'].tolist())
    print(f"Total codes in spot DB: {len(codes)}")
    
    targets = [
        '600276','600887','600030','600028','601088','600585','600690',
        '600000','600016','688981','002142','000100','002013','300124',
        '000538','002049','002352','300782','002916','300274','002129'
    ]
    
    found_count = 0
    for code in targets:
        found = code in codes
        if found:
            found_count += 1
        print(f"  {code}: {'FOUND' if found else 'NOT IN DB'}")
    
    print(f"\nSpot DB coverage: {found_count}/{len(targets)}")
    
except Exception as e:
    print(f"Error: {e}")
