"""
EXP-2026-INVFAC-002: 数据质量前置检查 (§2.3) — 可导入模块
============================================================
author: 墨衡 (moheng)
created: 2026-05-25T17:10+08:00
updated: 2026-05-25T17:17+08:00

可同时作为独立脚本或导入模块使用。

检查项:
  1. adj_factor NULL 检查（硬阻断）
  2. adj_factor 异常跳变 >50% 检查（硬阻断）
  3. 数据连续性、字段完整性（硬阻断）
  4. Buy & Hold 验证（信息校验）

使用:
  python scripts/exp_invfac002/data_qc_check.py [--skip-bh]
"""

import argparse
import sqlite3
import sys
import os
from datetime import datetime

# ── 项目路径 ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")

# ── 除权除息事件白名单 ──
# Step 1 QC 确认为合法除权除息的 adj_factor 跳变，直接放行，不触发 FAIL
# 格式: {(ts_code, trade_date): "事件说明"}
# ts_code 与数据库存储格式一致（纯数字，无交易所后缀）
CORPORATE_ACTION_WHITELIST: dict[tuple[str, str], str] = {
    ("300750.SZ", "20230426"): "10送8拆分，Step 1 QC 已确认为除权除息",
    ("002594.SZ", "20250729"): "203.58% 跳变，已确认为合法除权除息",
    ("002475.SZ", "20200617"): "30.29% 跳变，已确认为合法除权除息",
}


def validate_adj_factor_null(cursor, ts_code: str, start: str, end: str) -> bool:
    """检查 adj_factor NULL（硬阻断）"""
    cursor.execute("""
        SELECT COUNT(*) FROM stock_daily
        WHERE ts_code=? AND trade_date BETWEEN ? AND ?
        AND adj_factor IS NULL
    """, (ts_code, start, end))
    null_count = cursor.fetchone()[0]
    if null_count > 0:
        print(f"[FAIL]  {ts_code} | adj_factor NULL 检查: {null_count} 个 NULL 值")
        return False
    print(f"[PASS] {ts_code} | adj_factor NULL 检查: 0 个 NULL")
    return True


def validate_adj_factor_jump(cursor, ts_code: str, start: str, end: str) -> bool:
    """检查 adj_factor 异常跳变 >50%（硬阻断）"""
    cursor.execute("""
        SELECT trade_date, adj_factor FROM stock_daily
        WHERE ts_code=? AND trade_date BETWEEN ? AND ?
        AND adj_factor IS NOT NULL
        ORDER BY trade_date
    """, (ts_code, start, end))
    rows = cursor.fetchall()

    jumps = []
    whitelisted = []
    prev_adj = None
    for date_str, adj_factor in rows:
        if prev_adj is not None and prev_adj > 0:
            change = abs(adj_factor - prev_adj) / prev_adj
            if change > 0.50:
                # 检查是否在白名单中（确认为合法除权除息事件）
                wl_key = (ts_code, date_str)
                if wl_key in CORPORATE_ACTION_WHITELIST:
                    whitelisted.append(
                        (date_str, prev_adj, adj_factor, change,
                         CORPORATE_ACTION_WHITELIST[wl_key])
                    )
                else:
                    jumps.append((date_str, prev_adj, adj_factor, change))
        prev_adj = adj_factor

    # 输出白名单放行信息（无论是否有跳变）
    if whitelisted:
        for date_str, prev_val, curr_val, chg, reason in whitelisted:
            print(f"  [INFO] {ts_code} | {date_str}: {chg*100:.1f}% 跳变在白名单中 → {reason}，放行")

    if jumps:
        print(f"[FAIL]  {ts_code} | adj_factor 异常跳变: {len(jumps)} 次 >50%（白名单外）")
        for date_str, prev_val, curr_val, chg in jumps[:5]:
            print(f"       {date_str}: {prev_val:.4f} -> {curr_val:.4f} ({chg*100:.1f}%)")
        return False

    print(f"[PASS] {ts_code} | adj_factor 异常跳变: 无 >50%")
    return True


def validate_data_continuity(cursor, ts_code: str, start: str, end: str) -> bool:
    """数据连续性和字段完整性检查（硬阻断）"""
    cursor.execute("""
        SELECT COUNT(*) FROM stock_daily
        WHERE ts_code=? AND trade_date BETWEEN ? AND ?
    """, (ts_code, start, end))
    total_count = cursor.fetchone()[0]

    # 期望大致天数
    try:
        from datetime import datetime as dt
        s = dt.strptime(start, "%Y%m%d")
        e = dt.strptime(end, "%Y%m%d")
        expected = (e - s).days * 5 // 7  # 约5/7 交易日
        expected = max(expected, 200)
    except Exception:
        expected = 500

    if total_count < expected * 0.5:
        print(f"[FAIL]  {ts_code} | 数据连续性: 仅 {total_count} 行, 期望约 {expected}")
        return False

    # 字段完整性：检查关键字段 NULL 比例
    cursor.execute("""
        SELECT
            SUM(CASE WHEN open IS NULL THEN 1 ELSE 0 END) AS null_open,
            SUM(CASE WHEN high IS NULL THEN 1 ELSE 0 END) AS null_high,
            SUM(CASE WHEN low IS NULL THEN 1 ELSE 0 END) AS null_low,
            SUM(CASE WHEN close IS NULL THEN 1 ELSE 0 END) AS null_close,
            SUM(CASE WHEN volume IS NULL THEN 1 ELSE 0 END) AS null_vol
        FROM stock_daily
        WHERE ts_code=? AND trade_date BETWEEN ? AND ?
    """, (ts_code, start, end))
    null_counts = cursor.fetchone()
    col_names = ["open", "high", "low", "close", "volume"]
    null_fields = []
    for i, name in enumerate(col_names):
        if null_counts[i] > 0:
            null_fields.append(f"{name}:{null_counts[i]}")
            print(f"[FAIL]  {ts_code} | 字段完整性: {name} 有 {null_counts[i]} 个 NULL")

    if null_fields:
        return False

    print(f"[PASS] {ts_code} | 数据连续性: {total_count} 行, 字段完整性通过")
    return True


def validate_buy_and_hold(cursor, ts_code: str, start: str, end: str) -> dict:
    """Buy & Hold 收益率验证（信息校验，不阻断）"""
    cursor.execute("""
        SELECT trade_date, close FROM stock_daily
        WHERE ts_code=? AND trade_date BETWEEN ? AND ?
        AND close IS NOT NULL
        ORDER BY trade_date
    """, (ts_code, start, end))
    rows = cursor.fetchall()
    if len(rows) < 2:
        print(f"[INFO] {ts_code} | Buy & Hold: 数据不足")
        return {"start_price": None, "end_price": None, "return": None}

    start_price = rows[0][1]
    end_price = rows[-1][1]
    total_return = (end_price / start_price - 1) * 100

    print(f"[INFO] {ts_code} | Buy & Hold: {rows[0][0]}~{rows[-1][0]} "
          f"收益={total_return:.2f}%")

    return {
        "start_price": float(start_price),
        "end_price": float(end_price),
        "return": float(total_return),
    }


def check_single_stock(cursor, ts_code: str, start: str, end: str, skip_bh: bool = False) -> dict:
    """对单标的执行全部检查，返回检查结果 dict"""
    checks = {
        "ts_code": ts_code,
        "adj_factor_null": {"passed": False, "detail": ""},
        "adj_factor_jump": {"passed": False, "detail": ""},
        "data_continuity": {"passed": False, "detail": ""},
        "buy_and_hold": {"passed": True, "detail": {}},
    }

    # 1. adj_factor NULL
    checks["adj_factor_null"]["passed"] = validate_adj_factor_null(
        cursor, ts_code, start, end
    )
    checks["adj_factor_null"]["detail"] = "adj_factor NULL 检查"

    # 2. adj_factor 跳跃
    checks["adj_factor_jump"]["passed"] = validate_adj_factor_jump(
        cursor, ts_code, start, end
    )
    checks["adj_factor_jump"]["detail"] = "adj_factor 跳变检查"

    # 3. 数据连续性 + 字段完整性
    checks["data_continuity"]["passed"] = validate_data_continuity(
        cursor, ts_code, start, end
    )
    checks["data_continuity"]["detail"] = "数据连续性/字段完整性"

    # 4. B&H
    if not skip_bh:
        bh = validate_buy_and_hold(cursor, ts_code, start, end)
        checks["buy_and_hold"]["detail"] = bh

    checks["all_passed"] = all(
        checks[k]["passed"]
        for k in ["adj_factor_null", "adj_factor_jump", "data_continuity"]
    )
    return checks


def run_all_checks(
    stock_codes: list[str],
    start: str = "20210101",
    end: str = "20251231",
    skip_bh: bool = False,
) -> dict:
    """对所有标的运行完整数据质量检查。

    Returns
    -------
    dict:
      - overall_passed: bool
      - checks_by_stock: {ts_code: check_dict}
      - completed_time: str
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"数据库不存在: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    completed_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    print(f"\n{'=' * 60}")
    print(f"  数据质量前置检查 (§2.3)")
    print(f"  数据库: {DB_PATH}")
    print(f"  标的数: {len(stock_codes)}, 区间: {start} ~ {end}")
    print(f"{'=' * 60}\n")

    results: dict[str, dict] = {}
    all_passed = True

    for code in stock_codes:
        result = check_single_stock(cursor, code, start, end, skip_bh=skip_bh)
        results[code] = result
        if not result["all_passed"]:
            all_passed = False

    conn.close()

    print(f"\n{'=' * 60}")
    print(f"  QC 结果: [{'PASS' if all_passed else 'FAIL'}]")
    print(f"  完成时间: {completed_at}")
    print(f"{'=' * 60}")

    return {
        "overall_passed": all_passed,
        "checks_by_stock": results,
        "completed_time": completed_at,
    }


def main():
    parser = argparse.ArgumentParser(description="数据质量前置检查 (§2.3)")
    parser.add_argument("--skip-bh", action="store_true", help="跳过 Buy & Hold 验证")
    args = parser.parse_args()

    STOCK_CODES = [
        "601857.SH", "000001.SZ", "600519.SH", "601318.SH",
        "600036.SH", "300750.SZ", "600276.SH", "600887.SH",
        "600030.SH", "000333.SZ", "002415.SZ", "600585.SH",
    ]

    try:
        result = run_all_checks(STOCK_CODES, skip_bh=args.skip_bh)
        sys.exit(0 if result["overall_passed"] else 1)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
