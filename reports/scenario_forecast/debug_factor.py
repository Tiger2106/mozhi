import akshare as ak
import numpy as np

# Test bid_ask_em
print("=== stock_bid_ask_em ===")
try:
    df = ak.stock_bid_ask_em(symbol="601857")
    print("Columns:", [repr(c) for c in df.columns])
    # Try to find buy1/sell1
    for _, row in df.iterrows():
        item = str(row["item"])
        if "buy1" in item.lower() or "sell1" in item.lower() or "buy" in item.lower() or "sell" in item.lower():
            print(f"  {item}: {row['value']}")
except Exception as e:
    print("Error:", e)

# Test zh_a_hist for turnover
print("\n=== stock_zh_a_hist ===")
try:
    df = ak.stock_zh_a_hist(symbol="601857", period="daily", start_date="20260501", adjust="")
    print("Columns:", [repr(c) for c in df.columns])
    for col in df.columns:
        print(f"  col bytes: {col.encode('utf-8')}")
    # Try matching
    for col in df.columns:
        s = str(col)
        if "\u6362\u624b" in s:
            print(f"UNICODE MATCH: {repr(col)}")
        if "\u6210\u4ea4" in s:
            print(f"VOL MATCH: {repr(col)}")
except Exception as e:
    print("Error:", e)
