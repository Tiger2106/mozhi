"""
verify_market_data_coverage.py
==============================
DB_UNIFY_0525 — Data coverage verification

Verification items:
  1. stock_daily row count >= analysis.db stock_daily row count
  2. trading_calendar covers 2020-01 ~ 2028-12 (after merge)
  3. 601857 / 000001 / 600519 monthly completeness (no missing months)

Author: moheng
Created: 2026-05-25T16:00+08:00
"""
import sqlite3
from datetime import datetime

ANALYSIS_DB = r"C:\Users\17699\mozhi_platform\data\analysis.db"
MARKET_DB   = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

PASS = "[PASS]"
WARN = "[WARN]"
FAIL = "[FAIL]"

def check_1_stock_daily_row_count():
    """Check 1: stock_daily row count comparison"""
    conn_mkt = sqlite3.connect(MARKET_DB)
    cur_mkt = conn_mkt.cursor()
    cur_mkt.execute("SELECT COUNT(*) FROM stock_daily")
    mkt_cnt = cur_mkt.fetchone()[0]
    conn_mkt.close()

    conn_ana = sqlite3.connect(ANALYSIS_DB)
    cur_ana = conn_ana.cursor()
    cur_ana.execute("SELECT COUNT(*) FROM stock_daily")
    ana_cnt = cur_ana.fetchone()[0]
    conn_ana.close()

    status = PASS if mkt_cnt >= ana_cnt else FAIL
    print(f"\n{'='*60}")
    print(f"[1] stock_daily row count comparison")
    print(f"{'='*60}")
    print(f"  market_data.db stock_daily: {mkt_cnt} rows")
    print(f"  analysis.db    stock_daily: {ana_cnt} rows")
    print(f"  market_data.db >= analysis.db: {mkt_cnt >= ana_cnt}")
    print(f"  => {status}")
    return mkt_cnt >= ana_cnt


def check_2_trading_calendar_coverage():
    """Check 2: trading_calendar covers 2020-01 ~ 2028-12"""
    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()

    cur.execute("SELECT market, MIN(date), MAX(date) FROM trading_calendar GROUP BY market ORDER BY market")
    results = cur.fetchall()

    conn.close()

    print(f"\n{'='*60}")
    print(f"[2] trading_calendar coverage")
    print(f"{'='*60}")

    all_ok = True
    for market, mind, maxd in results:
        mind_str = str(mind)
        maxd_str = str(maxd)

        covers_2020 = mind_str.startswith("2020")
        covers_2028 = maxd_str.startswith("2028")

        market_ok = covers_2020 and covers_2028
        if not market_ok:
            all_ok = False

        status = PASS if market_ok else WARN
        print(f"  {market}: {mind_str} ~ {maxd_str}")
        print(f"    covers 2020: {covers_2020}, covers 2028: {covers_2028}")
        print(f"    => {status}")

    print(f"\n  Overall: {'[PASS]' if all_ok else '[WARN] incomplete coverage'}")
    return all_ok


def check_3_monthly_completeness():
    """Check 3: monthly completeness for 3 target codes"""
    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()

    codes = ["601857", "000001", "600519"]
    all_ok = True

    print(f"\n{'='*60}")
    print(f"[3] Monthly completeness (3 target codes)")
    print(f"{'='*60}")

    for code in codes:
        cur.execute("""
            SELECT substr(date,1,6) as yyyymm,
                   COUNT(*) as cnt,
                   MIN(date),
                   MAX(date)
            FROM stock_daily
            WHERE code = ?
            GROUP BY yyyymm
            ORDER BY yyyymm
        """, (code,))

        rows = cur.fetchall()

        if len(rows) == 0:
            all_ok = False
            print(f"\n  {code}: {FAIL} no data")
            continue

        gaps = []
        for i in range(1, len(rows)):
            prev_mm = int(rows[i-1][0])
            curr_mm = int(rows[i][0])
            if curr_mm - prev_mm > 1:
                y = prev_mm // 100
                m = prev_mm % 100
                while True:
                    m += 1
                    if m > 12:
                        m = 1
                        y += 1
                    if y * 100 + m >= curr_mm:
                        break
                    gaps.append(f"{y * 100 + m:06d}")

        status = PASS if not gaps else WARN
        if gaps:
            all_ok = False

        first_mm = rows[0][0]
        last_mm = rows[-1][0]
        total_months = len(rows)
        min_cnt = min(r[1] for r in rows)
        max_cnt = max(r[1] for r in rows)

        print(f"\n  {code}: {total_months} months ({first_mm} ~ {last_mm})")
        print(f"    total rows: {sum(r[1] for r in rows)}")
        print(f"    min/month: {min_cnt}, max/month: {max_cnt}")

        if gaps:
            print(f"    missing months: {gaps[:10]}{'...' if len(gaps) > 10 else ''}")

        print(f"    => {status}")

    conn.close()

    print(f"\n  Overall: {'[PASS]' if all_ok else '[WARN] missing months detected'}")
    return all_ok


def main():
    print(f"Market Data Coverage Verification Report")
    print(f"========================================")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"analysis.db:   {ANALYSIS_DB}")
    print(f"market_data.db: {MARKET_DB}")

    r1 = check_1_stock_daily_row_count()
    r2 = check_2_trading_calendar_coverage()
    r3 = check_3_monthly_completeness()

    print(f"\n{'='*60}")
    verdict = PASS if (r1 and r2 and r3) else FAIL
    print(f"Final Verdict: {verdict}")
    if not r1:
        print(f"  - stock_daily row count insufficient")
    if not r2:
        print(f"  - trading_calendar coverage incomplete")
    if not r3:
        print(f"  - target codes have missing months")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
