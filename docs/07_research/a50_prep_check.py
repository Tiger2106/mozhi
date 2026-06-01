#!/usr/bin/env python3
"""
A50 data prep check script.
Check 39 missing stocks for akshare API availability, data range and quality.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import akshare as ak
import pandas as pd
import time
import json
from datetime import datetime, timedelta

STOCKS_39 = [
    "600276", "601166", "600887", "600030", "600028", "601088", "600585", "600690",
    "601398", "601939", "600000", "600016", "600019", "600104", "601328", "601288",
    "601988", "601668", "000333", "000002", "002714", "002304", "000568", "000725",
    "002230", "300059", "000651", "002142", "000100", "002013", "300124", "000538",
    "002049", "002352", "300782", "688981", "002916", "300274", "002129"
]

FULL_TEST_STOCKS = ["601166", "000333", "300059", "002714", "688981"]

def get_exchange(code):
    if code.startswith(('6', '9')):
        return 'SH'
    elif code.startswith(('0', '2', '3')):
        return 'SZ'
    elif code.startswith(('4', '8')):
        return 'BJ'
    return 'UNKNOWN'

def check_stock_full(code, delay=1.5):
    result = {
        "code": code, "exchange": get_exchange(code),
        "api_available": False, "earliest_date": None, "latest_date": None,
        "total_rows": 0, "fields_complete": False, "fields_missing": [],
        "adj_factor_available": False, "has_gaps": False, "gap_dates": [], "error": None
    }
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20000101", end_date="20260525", adjust="")
        if df is not None and len(df) > 0:
            result["api_available"] = True
            result["total_rows"] = len(df)
            date_col = None
            for c in ["日期", "date", "Date", "trade_date"]:
                if c in df.columns: date_col = c; break
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col])
                result["earliest_date"] = df[date_col].min().strftime("%Y-%m-%d")
                result["latest_date"] = df[date_col].max().strftime("%Y-%m-%d")
            
            expected = {"open": ["开盘","open"], "high": ["最高","high"], "low": ["最低","low"], "close": ["收盘","close"], "volume": ["成交量","volume"]}
            missing = []
            for fname, aliases in expected.items():
                if not any(a in df.columns for a in aliases):
                    missing.append(fname)
            result["fields_missing"] = missing
            result["fields_complete"] = len(missing) == 0
            
            # Check adj factor by getting qfq data
            try:
                df_qfq = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20000101", end_date="20260525", adjust="qfq")
                df_hfq = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20000101", end_date="20260525", adjust="hfq")
                if df_qfq is not None and df_hfq is not None and len(df_qfq) > 0 and len(df_hfq) > 0:
                    result["adj_factor_available"] = True
            except:
                pass
            
            # Check gaps (>10 days)
            if date_col and len(df) > 20:
                df_sorted = df.sort_values(date_col)
                date_diffs = df_sorted[date_col].diff().dropna()
                large_gaps = date_diffs[date_diffs > pd.Timedelta(days=10)]
                if len(large_gaps) > 0:
                    result["has_gaps"] = True
                    for idx in large_gaps.index[:10]:
                        prev_date = (df_sorted.loc[idx, date_col] - large_gaps.loc[idx]).strftime("%Y-%m-%d")
                        curr_date = df_sorted.loc[idx, date_col].strftime("%Y-%m-%d")
                        result["gap_dates"].append(f"{prev_date} -> {curr_date} ({large_gaps.loc[idx].days}d)")
            time.sleep(delay)
        else:
            result["error"] = "empty data"
    except Exception as e:
        result["error"] = str(e)
    return result

def check_stock_light(code, delay=0.8):
    result = {
        "code": code, "exchange": get_exchange(code),
        "api_available": False, "rows_estimate": 0,
        "earliest_date": None, "latest_date": None, "error": None
    }
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20230101", end_date="20260525", adjust="")
        if df is not None and len(df) > 0:
            result["api_available"] = True
            result["rows_estimate"] = len(df)
            for c in ["日期", "date", "Date", "trade_date"]:
                if c in df.columns:
                    df[c] = pd.to_datetime(df[c])
                    result["earliest_date"] = df[c].min().strftime("%Y-%m-%d")
                    result["latest_date"] = df[c].max().strftime("%Y-%m-%d")
                    break
            time.sleep(delay)
        else:
            result["error"] = "empty data"
    except Exception as e:
        result["error"] = str(e)
    return result

if __name__ == "__main__":
    all_results = {"full_test": [], "light_test": [], "summary": {}}
    
    print("=" * 60)
    print("A50 data prep check - Start")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total stocks: {len(STOCKS_39)} (full=5, light={len(STOCKS_39)-len(FULL_TEST_STOCKS)})")
    print("=" * 60)
    
    # Phase 1: Full test (5 stocks)
    print("\n[Phase 1] Full test (5 stocks)...")
    for code in FULL_TEST_STOCKS:
        print(f"  checking {code}({get_exchange(code)}) ... ", end="", flush=True)
        result = check_stock_full(code)
        all_results["full_test"].append(result)
        mark = "OK" if result["api_available"] else "ERR"
        print(f"  [{mark}] rows={result['total_rows']}, date=[{result['earliest_date']}, {result['latest_date']}]")
        if result["error"]:
            print(f"    error: {result['error']}")
    
    # Phase 2: Light test (34 stocks)
    light_stocks = [s for s in STOCKS_39 if s not in FULL_TEST_STOCKS]
    print(f"\n[Phase 2] Light test ({len(light_stocks)} stocks)...")
    
    for i, code in enumerate(light_stocks):
        print(f"  [{i+1}/{len(light_stocks)}] {code}({get_exchange(code)}) ... ", end="", flush=True)
        result = check_stock_light(code)
        all_results["light_test"].append(result)
        mark = "OK" if result["api_available"] else "ERR"
        print(f"  [{mark}] rows={result['rows_estimate']}, date=[{result['earliest_date']}, {result['latest_date']}]")
        if result["error"]:
            print(f"    error: {result['error']}")
    
    # Summary
    total = len(STOCKS_39)
    available = sum(1 for r in all_results["full_test"] + all_results["light_test"] if r["api_available"])
    failed = total - available
    
    full_rows = sum(r["total_rows"] for r in all_results["full_test"])
    light_rows_sum = sum(r["rows_estimate"] for r in all_results["light_test"])
    
    # Estimate full rows for light-tested stocks
    estimated_light_full = 0
    for r in all_results["light_test"]:
        if r["api_available"] and r["earliest_date"]:
            try:
                e = datetime.strptime(r["earliest_date"], "%Y-%m-%d")
                years = max(1, (datetime.now() - e).days / 365)
                estimated_light_full += int(r["rows_estimate"] / min(3, years) * years)
            except:
                estimated_light_full += r["rows_estimate"]
        else:
            estimated_light_full += 0
    
    total_estimated_rows = full_rows + estimated_light_full
    
    all_results["summary"] = {
        "total_stocks": total,
        "api_available": available,
        "api_unavailable": failed,
        "api_availability_rate": f"{available/total*100:.1f}%",
        "full_test_count": len(FULL_TEST_STOCKS),
        "light_test_count": len(light_stocks),
        "full_test_rows": full_rows,
        "estimated_light_to_full_rows": estimated_light_full,
        "estimated_full_rows_total": total_estimated_rows,
        "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total stocks: {total}")
    print(f"API available: {available} ({all_results['summary']['api_availability_rate']})")
    print(f"API unavailable: {failed}")
    print(f"Full test rows: {full_rows}")
    print(f"Estimated light->full rows: {estimated_light_full}")
    print(f"Estimated total rows (all 39): {total_estimated_rows}")
    
    # Save JSON result
    serializable = {
        "summary": all_results["summary"],
        "full_test": [{k: (str(v) if isinstance(v, list) else v) for k, v in r.items()} for r in all_results["full_test"]],
        "light_test": [{k: (str(v) if isinstance(v, list) else v) for k, v in r.items()} for r in all_results["light_test"]]
    }
    json_path = r"C:\Users\17699\mozhi_platform\docs\07_research\a50_prep_check_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {json_path}")
    print("=" * 60)
