#!/usr/bin/env python3
"""Check which db is tushare-ingested - temp script"""
import sqlite3

def check_db(path, label):
    print(f"\n{'='*60}")
    print(f"=== {label}: {path} ===")
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cur.fetchall()]
    print(f"Tables: {tables}")
    for name in tables:
        cur.execute(f"PRAGMA table_info({name})")
        cols = cur.fetchall()
        colnames = [c[1] for c in cols]
        print(f"  Table '{name}': columns={colnames}")
        cur.execute(f"SELECT COUNT(*) FROM {name}")
        cnt = cur.fetchone()[0]
        print(f"    rows={cnt}")
        if 'date' in colnames:
            cur.execute(f"SELECT MIN(date), MAX(date) FROM {name}")
            dd = cur.fetchone()
            print(f"    date range: {dd[0]} ~ {dd[1]}")
        if 'code' in colnames:
            cur.execute(f"SELECT COUNT(DISTINCT code) FROM {name}")
            dc = cur.fetchone()[0]
            print(f"    distinct codes: {dc}")
        if 'adj_factor' in colnames:
            cur.execute(f"SELECT MIN(adj_factor), MAX(adj_factor), AVG(adj_factor), COUNT(*) FROM {name} WHERE adj_factor IS NOT NULL")
            r = cur.fetchone()
            print(f"    adj_factor: min={r[0]}, max={r[1]}, avg={r[2]}, non_null={r[3]}")
            cur.execute(f"SELECT COUNT(*) FROM {name} WHERE adj_factor IS NULL")
            nulls = cur.fetchone()[0]
            print(f"    adj_factor NULLs: {nulls}")
        if 'adj_factor' in colnames:
            cur.execute(f"SELECT code, date, adj_factor FROM {name} WHERE adj_factor IS NOT NULL AND adj_factor != 1.0 LIMIT 5")
            samples = cur.fetchall()
            print(f"    sample non-1.0 adj_factors: {samples}")
    conn.close()

root = r"C:\Users\17699\mozhi_platform"

check_db(f"{root}\\data\\db\\analysis.db", "data/db/analysis.db (phase1 target)")
check_db(f"{root}\\data\\analysis.db", "data/analysis.db (TSI target)")
check_db(f"{root}\\data\\market\\market_data.db", "data/market/market_data.db (market)")
