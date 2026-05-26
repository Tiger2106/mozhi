"""
EXP-2026-INVFAC-002: 数据质量前置检查脚本
================================================
author: 墨衡 (moheng)
created: 2026-05-25T17:10+08:00

执行实验设计 §2.3 的数据质量检查：
  - adj_factor NULL 检查（硬阻断）
  - adj_factor 异常跳变 >50% 检查（硬阻断）
  - Buy & Hold 验证（信息校验）

使用: python scripts/qc/data_qc_check.py --ts_code 601857 --start 20210101 --end 20251231
"""

import argparse
import sqlite3
import sys
import os
from datetime import datetime

# ── 项目路径 ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")


def validate_adj_factor_null(cursor, ts_code: str, start: str, end: str) -> bool:
    """检查 adj_factor NULL（硬阻断）"""
    cursor.execute("""
        SELECT COUNT(*) FROM stock_daily
        WHERE code=? AND date BETWEEN ? AND ?
        AND adj_factor IS NULL
    """, (ts_code, start, end))
    null_count = cursor.fetchone()[0]
    if null_count > 0:
        print(f"[FAIL] adj_factor NULL 检查: {null_count} 个 NULL 值")
        return False
    print("[PASS] adj_factor NULL 检查: 0 个 NULL")
    return True


def validate_adj_factor_jump(cursor, ts_code: str, start: str, end: str) -> bool:
    """检查 adj_factor 异常跳变 >50%（硬阻断）"""
    cursor.execute("""
        SELECT date, adj_factor FROM stock_daily
        WHERE code=? AND date BETWEEN ? AND ?
        AND adj_factor IS NOT NULL
        ORDER BY date
    """, (ts_code, start, end))
    rows = cursor.fetchall()

    jumps = []
    prev_adj = None
    for date_str, adj_factor in rows:
        if prev_adj is not None and prev_adj > 0:
            change = abs(adj_factor - prev_adj) / prev_adj
            if change > 0.50:
                jumps.append((date_str, prev_adj, adj_factor, change))
        prev_adj = adj_factor

    if jumps:
        print(f"[FAIL] adj_factor 异常跳变检查: {len(jumps)} 次 >50% 跳变")
        for date_str, prev_val, curr_val, chg in jumps[:5]:
            print(f"  {date_str}: {prev_val:.4f} -> {curr_val:.4f} ({chg*100:.1f}%)")
        return False

    print("[PASS] adj_factor 异常跳变检查: 无 >50% 跳变")
    return True


def validate_buy_and_hold(cursor, ts_code: str, start: str, end: str) -> dict:
    """Buy & Hold 收益率验证（信息校验，不阻断）"""
    cursor.execute("""
        SELECT date, close FROM stock_daily
        WHERE code=? AND date BETWEEN ? AND ?
        AND close IS NOT NULL
        ORDER BY date
    """, (ts_code, start, end))
    rows = cursor.fetchall()
    if len(rows) < 2:
        print("[INFO] Buy & Hold 验证: 数据不足")
        return {"start_price": None, "end_price": None, "return": None}

    start_price = rows[0][1]
    end_price = rows[-1][1]
    total_return = (end_price / start_price - 1) * 100

    print(f"[INFO] Buy & Hold 验证: {rows[0][0]}~{rows[-1][0]}")
    print(f"  start_price={start_price:.2f}, end_price={end_price:.2f}")
    print(f"  total_return={total_return:.2f}%")

    return {
        "start_price": float(start_price),
        "end_price": float(end_price),
        "return": float(total_return),
    }


def main():
    parser = argparse.ArgumentParser(description="数据质量前置检查 (§2.3)")
    parser.add_argument("--ts_code", required=True, help="标的代码")
    parser.add_argument("--start", default="20210101", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", default="20251231", help="结束日期 YYYYMMDD")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"[ERROR] 数据库不存在: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    all_passed = True

    # 1. adj_factor NULL 检查
    if not validate_adj_factor_null(cursor, args.ts_code, args.start, args.end):
        all_passed = False

    # 2. adj_factor 异常跳变检查
    if not validate_adj_factor_jump(cursor, args.ts_code, args.start, args.end):
        all_passed = False

    # 3. Buy & Hold 验证
    bh_result = validate_buy_and_hold(cursor, args.ts_code, args.start, args.end)

    # 记录 validation_check
    final_status = "PASS" if all_passed else "FAIL"
    print(f"\n{'=' * 50}")
    print(f"检查完成时间: {completed_at}")
    print(f"最终结果: [{'TECHNICAL_' + final_status}]")
    print(f"标的: {args.ts_code}, 区间: {args.start} ~ {args.end}")

    conn.close()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
