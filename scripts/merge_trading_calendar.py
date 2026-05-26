"""
merge_trading_calendar.py
=========================
DB_UNIFY_0525 — P1-2 交易日历合并

目标：将 analysis.db 的完整交易日历（A + OIL 市场，2020-01 ~ 2028-12）
合并到 market_data.db，补充缺失的：
  1. 2026-06 ~ 2028-12 的A股交易日历
  2. OIL 市场的交易日历

日期格式统一为 YYYYMMDD（与 stock_daily.date 一致）。

Author: moheng
Created: 2026-05-25T16:00+08:00
"""
import sqlite3
from datetime import datetime

# ===== 路径 =====
ANALYSIS_DB = r"C:\Users\17699\mozhi_platform\data\analysis.db"
MARKET_DB   = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"

def normalize_date(d):
    """将任意日期格式统一为 YYYYMMDD"""
    if d is None:
        return None
    d_str = str(d).replace("-", "")
    return d_str

def main():
    print(f"[{datetime.now().isoformat()}] 开始合并交易日历...")

    # ===== 1. 读取 source: analysis.db =====
    conn_src = sqlite3.connect(ANALYSIS_DB)
    cur_src = conn_src.cursor()

    # analysis.db 结构: date, market, is_trading_day, market_type, note, created_at
    # 日期格式: YYYY-MM-DD
    cur_src.execute("SELECT date, market, is_trading_day, market_type, note, created_at FROM trading_calendar")
    src_rows = cur_src.fetchall()
    conn_src.close()

    print(f"  analysis.db trading_calendar: {len(src_rows)} 行")

    # ===== 2. 读取 target: market_data.db =====
    conn_tgt = sqlite3.connect(MARKET_DB)
    cur_tgt = conn_tgt.cursor()

    # market_data.db 结构: market, date, is_trading_day, pretrade_date, created_at
    # 日期格式: YYYYMMDD
    cur_tgt.execute("SELECT market, date, is_trading_day, pretrade_date, created_at FROM trading_calendar")
    tgt_rows = cur_tgt.fetchall()

    # 构建已有集合: {(market, date)}
    existing = set()
    # 保存现有行的完整信息，用于索引加速
    existing_rows = {}
    for row in tgt_rows:
        mkt, dt, *_ = row
        existing.add((mkt, str(dt)))
        existing_rows[(mkt, str(dt))] = row

    print(f"  market_data.db trading_calendar: {len(tgt_rows)} 行")
    print(f"    已有 market-date 组合: {len(existing)} 个")

    # ===== 3. 确定缺失行 =====
    # 统一 source 日期格式
    missing_rows = []
    for sdate, smarket, sis_trading, stype, snote, screated in src_rows:
        sdate_norm = normalize_date(sdate)
        key = (smarket, sdate_norm)
        if key not in existing:
            # 新行：用 source 数据 + 推导 pretrade_date
            missing_rows.append((smarket, sdate_norm, sis_trading, stype, snote, screated))

    # ===== 4. 计算 pretrade_date =====
    # 对于 market_data.db，pretrade_date 是上一个交易日
    # 我们需要对所有缺失行按 market + date 排序后填充
    all_a_rows = {}
    all_oil_rows = {}

    # 先收集所有已有行和缺失行的信息
    full_by_market = {}
    for row in tgt_rows:
        mkt, dt, is_td, pretrade, *_ = row
        key = str(dt)
        if mkt not in full_by_market:
            full_by_market[mkt] = {}
        full_by_market[mkt][key] = {
            "date": str(dt),
            "is_trading_day": is_td,
            "pretrade_date": pretrade,
            "market_type": "A股" if mkt == "A" else "原油",
            "note": None,
        }

    # 添加缺失行（先不加 pretrade）
    for smarket, sdate_norm, sis_trading, stype, snote, screated in missing_rows:
        if smarket not in full_by_market:
            full_by_market[smarket] = {}
        full_by_market[smarket][sdate_norm] = {
            "date": sdate_norm,
            "is_trading_day": sis_trading,
            "pretrade_date": None,  # 稍后填充
            "market_type": stype,
            "note": snote,
        }

    # 对每个 market，按日期排序后填充 pretrade_date
    for market in full_by_market:
        sorted_dates = sorted(full_by_market[market].keys())
        prev_trading_date = None
        for d in sorted_dates:
            info = full_by_market[market][d]
            if info["is_trading_day"] == 1:
                if prev_trading_date is None:
                    info["pretrade_date"] = None
                else:
                    info["pretrade_date"] = prev_trading_date
                prev_trading_date = d
            else:
                # 非交易日：pretrade_date 维持 None 或原值
                if info["pretrade_date"] is None and prev_trading_date:
                    info["pretrade_date"] = prev_trading_date

    # ===== 5. 写回新表 =====
    # 创建 tgt_trading_calendar 新表（替代原表）
    cur_tgt.execute("DROP TABLE IF EXISTS trading_calendar_new")
    cur_tgt.execute("""
        CREATE TABLE trading_calendar_new (
            market          TEXT,
            date            TEXT,
            is_trading_day  INTEGER,
            pretrade_date   TEXT,
            market_type     TEXT,
            note            TEXT,
            created_at      TEXT
        )
    """)

    insert_count = 0
    for market in sorted(full_by_market.keys()):
        for d in sorted(full_by_market[market].keys()):
            info = full_by_market[market][d]
            now_ts = datetime.now().isoformat()
            cur_tgt.execute(
                "INSERT INTO trading_calendar_new (market, date, is_trading_day, pretrade_date, market_type, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (market, info["date"], info["is_trading_day"], info["pretrade_date"],
                 info["market_type"], info["note"], now_ts)
            )
            insert_count += 1

    # 原子替换
    cur_tgt.execute("DROP TABLE IF EXISTS trading_calendar_old")
    cur_tgt.execute("ALTER TABLE trading_calendar RENAME TO trading_calendar_old")
    cur_tgt.execute("ALTER TABLE trading_calendar_new RENAME TO trading_calendar")
    cur_tgt.execute("DROP TABLE IF EXISTS trading_calendar_old")

    conn_tgt.commit()

    # ===== 6. 验证 =====
    cur_tgt.execute("SELECT COUNT(*) FROM trading_calendar")
    total = cur_tgt.fetchone()[0]
    cur_tgt.execute("SELECT market, COUNT(*), MIN(date), MAX(date) FROM trading_calendar GROUP BY market")
    print(f"\n  合并后 trading_calendar: {total} 行")
    for row in cur_tgt.fetchall():
        print(f"    {row}")

    conn_tgt.close()

    # ===== 7. 创建 trading_calendar_full 视图（可选，兼容旧查询） =====
    conn_tgt2 = sqlite3.connect(MARKET_DB)
    cur_tgt2 = conn_tgt2.cursor()
    try:
        cur_tgt2.execute("""
            CREATE VIEW IF NOT EXISTS trading_calendar_full AS
            SELECT market, date, is_trading_day, pretrade_date, market_type, note, created_at
            FROM trading_calendar
        """)
        conn_tgt2.commit()
        print(f"  视图 trading_calendar_full 已创建（{total} 行）")
    except Exception as e:
        print(f"  视图创建失败（非关键）：{e}")
    conn_tgt2.close()

    print(f"\n[{datetime.now().isoformat()}] 合并完成。补充了 {total - len(tgt_rows)} 行新数据。")

if __name__ == "__main__":
    main()
