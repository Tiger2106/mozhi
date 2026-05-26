"""restore_verify — 验证 backup_manager.restore() 恢复过程的数据完整性和一致性

功能：
  1. 备份文件存在性校验
  2. 恢复后表结构一致性校验
  3. 恢复后数据完整性校验（行数、行哈希、关键字段）

使用方式：
  python -m paper_trade.restore_verify --backup-file <备份文件路径>

输出：
  校验报告 JSON（stdout），含 status、pass/fail、详细校验项

依赖：
  - backup_manager.py（P1-MH-4）
  - SQLite3（标准库）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timezone, timedelta

from utils.backup_manager import BackupManager
from src.config import SHANGHAI_TZ

logger = logging.getLogger("paper_trade.restore_verify")

TZ_SHANGHAI = SHANGHAI_TZ

# ============================================================
# 辅助函数
# ============================================================


def _parse_date_from_filename(filename: str) -> date | None:
    """从备份文件名 trade_engine_YYYYMMDD.db 中解析日期。"""
    m = re.search(r"trade_engine_(\d{8})\.db$", os.path.basename(filename))
    if not m:
        return None
    d = m.group(1)
    return date(int(d[:4]), int(d[4:6]), int(d[6:8]))


def _get_table_names(conn: sqlite3.Connection) -> list[str]:
    """获取数据库中所有用户表（排除 sqlite_ 系统表）。"""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r[0] for r in cur.fetchall()]


def _get_table_schema(conn: sqlite3.Connection) -> dict[str, str]:
    """获取每张表的 CREATE TABLE SQL。"""
    cur = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def _get_table_row_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(f"SELECT COUNT(*) FROM [{table}]")
    return cur.fetchone()[0]


def _get_table_column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"SELECT * FROM [{table}] LIMIT 0")
    return [desc[0] for desc in cur.description]


def _checksum_table(conn: sqlite3.Connection, table: str) -> str:
    """计算整表的 md5 校验和（逐行 -> 拼接 -> 哈希）。"""
    cur = conn.execute(f"SELECT * FROM [{table}] ORDER BY rowid")
    h = hashlib.md5()
    for row in cur.fetchall():
        h.update(str(tuple(row)).encode("utf-8"))
    return h.hexdigest()


# ============================================================
# 校验核心
# ============================================================


def verify_restore_backup(
    backup_path: str,
    db_path: str,
    backup_dir: str,
) -> dict:
    """执行恢复 + 校验全流程。

    参数：
        backup_path — 原始备份文件路径
        db_path — 备份管理器 db_path
        backup_dir — 备份管理器 backup_dir

    返回：
        dict JSON 校验报告
    """
    report: dict = {
        "status": "READY",
        "tool": "restore_verify",
        "backup_file": backup_path,
        "start_time": datetime.now(tz=TZ_SHANGHAI).isoformat(),
        "checks": [],
        "summary": {"total": 0, "passed": 0, "failed": 0},
    }
    all_passed = True

    def _check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal all_passed
        entry = {"name": name, "passed": passed}
        if detail:
            entry["detail"] = detail
        report["checks"].append(entry)
        report["summary"]["total"] += 1
        if passed:
            report["summary"]["passed"] += 1
        else:
            report["summary"]["failed"] += 1
            all_passed = False

    # -------------------------------------------------------
    # 1. 备份文件存在性校验
    # -------------------------------------------------------
    backup_exists = os.path.exists(backup_path) and os.path.isfile(backup_path)
    _check(
        "backup_file_exists",
        backup_exists,
        f"path={backup_path}, size={os.path.getsize(backup_path) if backup_exists else 'N/A'}",
    )
    if not backup_exists:
        report["status"] = "FAILED"
        report["error"] = f"备份文件不存在: {backup_path}"
        report["end_time"] = datetime.now(tz=TZ_SHANGHAI).isoformat()
        return report

    # 备份文件大小 > 0
    backup_size = os.path.getsize(backup_path)
    _check("backup_file_nonzero", backup_size > 0, f"size={backup_size}")

    # -------------------------------------------------------
    # 2. 识别日期并调用 restore()
    # -------------------------------------------------------
    backup_date = _parse_date_from_filename(backup_path)
    if backup_date is None:
        report["status"] = "FAILED"
        report["error"] = f"无法从文件名解析日期: {backup_path}（期望格式: trade_engine_YYYYMMDD.db）"
        report["end_time"] = datetime.now(tz=TZ_SHANGHAI).isoformat()
        return report

    bm = BackupManager(db_path=db_path, backup_dir=backup_dir)
    restored_path = bm.restore(backup_date)

    _check(
        "restore_returned_non_none",
        restored_path is not None,
        f"restored_path={restored_path}",
    )
    if restored_path is None:
        report["status"] = "FAILED"
        report["error"] = "restore() 返回 None，恢复失败"
        report["end_time"] = datetime.now(tz=TZ_SHANGHAI).isoformat()
        return report

    # -------------------------------------------------------
    # 3. 恢复文件存在性 & 可读性
    # -------------------------------------------------------
    restored_exists = os.path.exists(restored_path) and os.path.isfile(restored_path)
    _check(
        "restored_file_exists",
        restored_exists,
        f"path={restored_path}, size={os.path.getsize(restored_path) if restored_exists else 'N/A'}",
    )
    if not restored_exists:
        report["status"] = "FAILED"
        report["error"] = f"restore() 生成的文件不存在: {restored_path}"
        report["end_time"] = datetime.now(tz=TZ_SHANGHAI).isoformat()
        return report

    # -------------------------------------------------------
    # 4. SQLite 连接 & 表结构对比
    # -------------------------------------------------------
    try:
        backup_conn = sqlite3.connect(backup_path)
        backup_conn.row_factory = sqlite3.Row
        restored_conn = sqlite3.connect(restored_path)
        restored_conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        _check("sqlite_connect", False, f"连接失败: {e}")
        report["status"] = "FAILED"
        report["error"] = f"SQLite 连接失败: {e}"
        report["end_time"] = datetime.now(tz=TZ_SHANGHAI).isoformat()
        return report

    # 表名集合一致
    backup_tables = set(_get_table_names(backup_conn))
    restored_tables = set(_get_table_names(restored_conn))
    _check(
        "table_names_match",
        backup_tables == restored_tables,
        f"backup={sorted(backup_tables)}, restored={sorted(restored_tables)}",
    )

    # 表结构一致（CREATE TABLE SQL 逐表对比）
    backup_schemas = _get_table_schema(backup_conn)
    restored_schemas = _get_table_schema(restored_conn)
    schema_mismatches = {}
    for tbl in backup_tables:
        b_sql = backup_schemas.get(tbl, "").strip()
        r_sql = restored_schemas.get(tbl, "").strip()
        if b_sql != r_sql:
            schema_mismatches[tbl] = {"backup": b_sql, "restored": r_sql}
    _check(
        "table_schemas_match",
        len(schema_mismatches) == 0,
        f"mismatches={schema_mismatches}" if schema_mismatches else "all schemas identical",
    )

    # 列名一致（逐表）
    col_mismatches = {}
    for tbl in backup_tables:
        b_cols = _get_table_column_names(backup_conn, tbl)
        r_cols = _get_table_column_names(restored_conn, tbl)
        if b_cols != r_cols:
            col_mismatches[tbl] = {"backup": b_cols, "restored": r_cols}
    _check(
        "column_names_match",
        len(col_mismatches) == 0,
        f"mismatches={col_mismatches}" if col_mismatches else "all column names identical",
    )

    # -------------------------------------------------------
    # 5. 数据完整性校验
    # -------------------------------------------------------
    row_count_mismatches = {}
    for tbl in backup_tables:
        b_count = _get_table_row_count(backup_conn, tbl)
        r_count = _get_table_row_count(restored_conn, tbl)
        if b_count != r_count:
            row_count_mismatches[tbl] = {"backup": b_count, "restored": r_count}
    _check(
        "row_counts_match",
        len(row_count_mismatches) == 0,
        f"mismatches={row_count_mismatches}" if row_count_mismatches else "all row counts identical",
    )

    # 行数据 md5 校验和对比
    checksum_mismatches = {}
    for tbl in backup_tables:
        b_ck = _checksum_table(backup_conn, tbl)
        r_ck = _checksum_table(restored_conn, tbl)
        if b_ck != r_ck:
            checksum_mismatches[tbl] = {"backup": b_ck, "restored": r_ck}
    _check(
        "data_checksums_match",
        len(checksum_mismatches) == 0,
        f"mismatches={checksum_mismatches}" if checksum_mismatches else "all data checksums identical",
    )

    # 总行数
    total_backup_rows = sum(_get_table_row_count(backup_conn, t) for t in backup_tables)
    total_restored_rows = sum(_get_table_row_count(restored_conn, t) for t in backup_tables)
    _check(
        "total_row_count_match",
        total_backup_rows == total_restored_rows,
        f"backup={total_backup_rows}, restored={total_restored_rows}",
    )

    backup_conn.close()
    restored_conn.close()

    # -------------------------------------------------------
    # 6. 清理恢复文件
    # -------------------------------------------------------
    try:
        os.unlink(restored_path)
        _check("cleanup_restored_file", True, f"已删除: {restored_path}")
    except OSError as e:
        _check("cleanup_restored_file", False, f"删除失败: {e}")

    # -------------------------------------------------------
    # 7. 最终状态
    # -------------------------------------------------------
    report["status"] = "PASSED" if all_passed else "FAILED"
    report["end_time"] = datetime.now(tz=TZ_SHANGHAI).isoformat()

    return report


# ============================================================
# CLI 入口
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="验证 backup_manager.restore() 恢复过程的数据库完整性",
    )
    parser.add_argument(
        "--backup-file",
        required=True,
        help="备份文件路径（例如: mo_zhi_sharereports/backup/trade_engine_20260512.db）",
    )
    parser.add_argument(
        "--db-path",
        default="mo_zhi_sharereports/trade_engine.db",
        help="数据库路径（默认: mo_zhi_sharereports/trade_engine.db）",
    )
    parser.add_argument(
        "--backup-dir",
        default="mo_zhi_sharereports/backup",
        help="备份目录路径（默认: mo_zhi_sharereports/backup）",
    )

    args = parser.parse_args()

    # 解析参数
    backup_file = args.backup_file
    db_path = args.db_path
    backup_dir = args.backup_dir

    # 如果 backup-file 是相对路径，从工作目录解析
    if not os.path.isabs(backup_file):
        backup_file = os.path.abspath(backup_file)

    if not os.path.isabs(db_path):
        db_path = os.path.abspath(db_path)

    if not os.path.isabs(backup_dir):
        backup_dir = os.path.abspath(backup_dir)

    # 友好提示
    if not os.path.exists(backup_file):
        err = {
            "status": "FAILED",
            "error": f"备份文件不存在: {backup_file}",
            "tool": "restore_verify",
            "hint": "请检查路径是否正确，或先执行备份操作创建备份文件",
        }
        print(json.dumps(err, ensure_ascii=False, indent=2))
        return 1

    report = verify_restore_backup(backup_file, db_path, backup_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
