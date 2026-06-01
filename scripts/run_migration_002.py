"""
run_migration_002 — 执行 002_add_valuation_ps_pcf.sql 迁移

从 db/migrations/002_add_valuation_ps_pcf.sql 读取 SQL
对 a50_ic.db 执行迁移（新增 pe_ttm / ps_ttm / pcf_ttm / dividend_yield 列）

用法:
    python scripts/run_migration_002.py

作者: 墨衡
创建时间: 2026-05-31T19:22:00+08:00
"""

import sqlite3
import sys
import os
from pathlib import Path

# ── 路径 ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "a50_ic.db"
SQL_PATH = PROJECT_ROOT / "db" / "migrations" / "002_add_valuation_ps_pcf.sql"


def run_migration(dry_run: bool = False) -> dict:
    """执行 002 迁移。dry_run=True 时只检查不提交。"""
    if not SQL_PATH.exists():
        return {"status": "FAILED", "error": f"SQL 文件不存在: {SQL_PATH}"}

    sql_text = SQL_PATH.read_text(encoding="utf-8")

    # 按分号分割 SQL 语句（保留 BEGIN/COMMIT 等语句）
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        # 检查是否已迁移
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        has_schema_version = cursor.fetchone() is not None

        if has_schema_version:
            cursor = conn.execute(
                "SELECT 1 FROM schema_version WHERE version='002'"
            )
            already_applied = cursor.fetchone() is not None
            if already_applied:
                conn.close()
                return {"status": "SKIPPED", "reason": "002 迁移已应用"}

        if not dry_run:
            conn.executescript(sql_text)
            conn.commit()
        else:
            print("[DRY RUN] 模拟执行，未实际写入")

        conn.close()
        return {"status": "SUCCESS", "migration": "002_add_valuation_ps_pcf"}
    except sqlite3.OperationalError as e:
        conn.rollback()
        conn.close()
        return {"status": "FAILED", "error": str(e)}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"status": "FAILED", "error": str(e)}


def verify_columns() -> dict:
    """验证估值列是否存在。"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute('PRAGMA table_info("a50_daily_ohlcv")')
    cols = {row[1] for row in cursor.fetchall()}
    conn.close()

    expected = {"pe_ttm", "ps_ttm", "pcf_ttm", "dividend_yield"}
    present = expected & cols
    missing = expected - cols

    return {
        "expected": sorted(expected),
        "present": sorted(present),
        "missing": sorted(missing),
        "all_present": len(missing) == 0,
    }


def main():
    print(f"=== 002 迁移 ===")
    print(f"数据库: {DB_PATH}")
    print(f"SQL文件: {SQL_PATH}")
    print()

    # 检查文件完整性
    sql_size = os.path.getsize(SQL_PATH)
    print(f"SQL 文件大小: {sql_size} bytes")

    # 执行迁移
    dry_run = "--dry-run" in sys.argv
    result = run_migration(dry_run=dry_run)
    print(f"迁移结果: {result['status']}")
    if "error" in result:
        print(f"错误: {result['error']}")

    # 验证
    if result["status"] in ("SUCCESS", "SKIPPED"):
        v = verify_columns()
        print(f"验证: 目标列={v['expected']}")
        print(f"      已存在={v['present']}")
        print(f"      缺失={v['missing']}")
        print(f"      全部就位={'✅' if v['all_present'] else '❌'}")

    return 0 if result["status"] in ("SUCCESS", "SKIPPED") else 1


if __name__ == "__main__":
    sys.exit(main())
