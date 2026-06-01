"""
ETL: 从 market_data.db.stock_daily 提取上证50成分股日线数据写入 a50_daily_ohlcv

功能：
  - 查询 stock_daily 表所有 50 只 A50 成分股（25 SH + 25 SZ）的日线数据
  - 按 ts_code + trade_date 去重写入（INSERT OR REPLACE 利用唯一索引）
  - null_reason 标记：
      - volume=0 AND amount=0 → 'SUSPENDED'
      - 关键价格/量字段缺失 → 'MISSING'
      - 正常交易数据 → NULL
  - source_version = 'v1'
  - 外键连接时显式开启（DatabaseManager 自动设置 PRAGMA foreign_keys=ON）

验收标准（IC_PIPELINE_T14_002）：
  - ETL 执行后 a50_daily_ohlcv 含 2007-2026 年 A50 成分股完整日线数据
  - 停牌行 volume=0/amount=0 且 null_reason=SUSPENDED
  - 缺失字段正确标记 null_reason

使用方式：
    python -m src.data.etl_a50_daily
    python -m src.data.etl_a50_daily --src-db=... --tgt-db=...
    python -m src.data.etl_a50_daily --dry-run   # 仅提取不写入

Author: 墨衡
Created: 2026-05-30T09:42:00+08:00
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── 项目路径 ──────────────────────────────────────
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.db.connection import DatabaseManager
from src.db.schema import create_tables, table_exists

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 配置常量
# ════════════════════════════════════════════════════════════

DEFAULT_SRC_DB = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"
DEFAULT_TGT_DB = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"

BATCH_SIZE = 5000

# ── 关键字段（用于 null_reason 判定） ─────────────
# 只有以下字段的 NULL 才会触发 MISSING 标记。
# turnover_rate/pe/pb/total_mv/circ_mv/free_float 等非关键字段即使为 NULL，
# 也属于「API 未返回该字段」的正常情况，不触发缺失标记。
CRITICAL_FIELDS = [
    "open", "high", "low", "close",
    "pre_close", "volume", "amount",
    "adj_factor",
]

# ── COLUMN_MAP: 目标表字段 → 源表字段 ─────────────
# 仅包含数据字段（不含 id/source_version/null_reason/created_at）
COLUMN_MAP = {
    "ts_code": "ts_code",
    "trade_date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "pre_close": "pre_close",
    "volume": "volume",
    "amount": "amount",
    "turnover_rate": "turnover_rate",
    "pe": "pe",
    "pb": "pb",
    "adj_factor": "adj_factor",
    "total_mv": "total_mv",
    "circ_mv": "circ_mv",
    "free_float": "free_float_share",
}


# ════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════

def get_tz_aware_now() -> str:
    """返回当前时间的 ISO8601+08:00 字符串。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S%z")


def check_target_schema(conn: sqlite3.Connection) -> list[str]:
    """检查目标表 a50_daily_ohlcv 的现有列名。"""
    cols = conn.execute("PRAGMA table_info(a50_daily_ohlcv)").fetchall()
    return [c[1] for c in cols]


def reconcile_column_map(existing_columns: list[str]) -> dict[str, str]:
    """根据实际存在的目标表列名，过滤 COLUMN_MAP 中不存在的映射。"""
    return {tgt: src for tgt, src in COLUMN_MAP.items() if tgt in existing_columns}


# ════════════════════════════════════════════════════════════
# 核心 ETL 函数
# ════════════════════════════════════════════════════════════

def extract_from_source(src_conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """从 market_data.db.stock_daily 提取全量 A50 日线数据。"""
    logger.info("Extracting data from stock_daily...")
    rows = src_conn.execute("""
        SELECT
            ts_code, trade_date,
            open, high, low, close, pre_close,
            volume, amount,
            turnover_rate, pe, pb,
            adj_factor,
            total_mv, circ_mv, free_float_share
        FROM stock_daily
        ORDER BY ts_code, trade_date
    """).fetchall()
    logger.info("Extracted %d rows from stock_daily", len(rows))
    return rows


def determine_null_reason(row: sqlite3.Row) -> Optional[str]:
    """确定 null_reason。

    NULL语义约定（§3.1.1 墨萱 T+7 验收要求）：
      - NULL  → 正常交易数据
      - 'SUSPENDED' → 当日停牌（volume=0 AND amount=0）
      - 'MISSING'   → 关键价格/量字段缺失

    规则：
      1. volume=0 AND amount=0 → SUSPENDED（退化停牌判别）
      2. CRITICAL_FIELDS 中任一为 NULL → MISSING
      3. 以上都不满足 → None（正常数据）
    """
    vol = row["volume"]
    amt = row["amount"]

    # 规则1：退化停牌判别
    if vol is not None and amt is not None and vol == 0 and amt == 0:
        return "SUSPENDED"

    # 规则2：关键字段缺失检测
    # 只检查 CRITICAL_FIELDS（open/high/low/close/pre_close/volume/amount/adj_factor）
    # turnover_rate/pe/pb/total_mv/circ_mv/free_float 等非关键字段即使 NULL 也不视为缺失
    for fld in CRITICAL_FIELDS:
        if row[fld] is None:
            return "MISSING"

    return None


def load_to_target(
    tgt_conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    column_map: dict[str, str],
    batch_size: int = BATCH_SIZE,
) -> dict:
    """将数据批量写入 a50_daily_ohlcv 表。

    使用 INSERT OR REPLACE 以处理 ts_code+trade_date 唯一键冲突。
    """
    # 构建字段列表
    metadata_fields = ["source_version", "null_reason", "created_at"]
    data_fields = list(column_map.keys())
    all_fields = data_fields + metadata_fields
    placeholders = ", ".join(["?"] * len(all_fields))
    fields_str = ", ".join(all_fields)

    now = get_tz_aware_now()
    source_version = "v1"

    insert_sql = (
        f"INSERT OR REPLACE INTO a50_daily_ohlcv "
        f"({fields_str}) VALUES ({placeholders})"
    )

    total = len(rows)
    suspension_count = 0
    missing_count = 0

    tgt_conn.execute("BEGIN TRANSACTION")
    try:
        for i in range(0, total, batch_size):
            batch = rows[i: i + batch_size]
            batch_data = []

            for row in batch:
                null_reason = determine_null_reason(row)
                if null_reason == "SUSPENDED":
                    suspension_count += 1
                elif null_reason == "MISSING":
                    missing_count += 1

                # 填充行数据
                row_vals = [row[column_map[tgt]] for tgt in data_fields]
                row_vals += [source_version, null_reason, now]
                batch_data.append(tuple(row_vals))

            tgt_conn.executemany(insert_sql, batch_data)

            if (i + batch_size) % (batch_size * 10) == 0 or i + batch_size >= total:
                logger.info(
                    "  Progress: %d / %d rows (%.1f%%)",
                    min(i + batch_size, total), total,
                    min(100.0, (i + batch_size) / total * 100),
                )

        tgt_conn.commit()
        logger.info(
            "Load complete: inserted=%d, suspension=%d, missing=%d",
            total, suspension_count, missing_count,
        )
    except Exception as e:
        tgt_conn.rollback()
        logger.error("Load FAILED: %s", e)
        raise

    return {
        "extracted": total,
        "inserted": total,
        "failed": 0,
        "suspension_count": suspension_count,
        "missing_count": missing_count,
    }


def validate_load(
    tgt_conn: sqlite3.Connection,
    expected_count: int,
    src_conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """验证写入结果。

    如果提供 src_conn，还会执行源-目标数据一致性抽检。
    """
    actual = tgt_conn.execute(
        "SELECT COUNT(*) FROM a50_daily_ohlcv"
    ).fetchone()[0]

    date_range = tgt_conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM a50_daily_ohlcv"
    ).fetchone()

    code_count = tgt_conn.execute(
        "SELECT COUNT(DISTINCT ts_code) FROM a50_daily_ohlcv"
    ).fetchone()[0]

    null_reasons = tgt_conn.execute(
        "SELECT null_reason, COUNT(*) as cnt "
        "FROM a50_daily_ohlcv GROUP BY null_reason"
    ).fetchall()

    result = {
        "actual_rows": actual,
        "expected_rows": expected_count,
        "row_match": actual == expected_count,
        "date_range": f"{date_range[0]} ~ {date_range[1]}",
        "distinct_codes": code_count,
        "null_reason_distribution": [
            {"reason": r[0] if r[0] else "NULL", "count": r[1]}
            for r in null_reasons
        ],
    }

    # ── 前复权一致性校验（提供 src_conn 时执行） ──
    if src_conn is not None and actual > 0:
        adj_check = validate_adj_consistency(src_conn, tgt_conn)
        result["adj_consistency"] = adj_check

    return result


def validate_adj_consistency(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    sample_size: int = 100,
) -> dict:
    """校验源-目标表的前复权数据一致性。

    对随机抽样的行，比较源表 stock_daily 与目标表 a50_daily_ohlcv
    的关键价格/复权字段是否完全一致（直通 ETL，无变换，应精确匹配）。

    校验字段：close, pre_close, adj_factor
    """
    # 获取目标表行数
    total = tgt_conn.execute(
        "SELECT COUNT(*) FROM a50_daily_ohlcv"
    ).fetchone()[0]

    if total == 0:
        return {
            "checked": 0,
            "matched": 0,
            "mismatched": 0,
            "passed": True,
            "note": "empty table, skipped",
        }

    # 随机抽样 sample_size 行
    sample_rows = tgt_conn.execute(
        f"""
        SELECT ts_code, trade_date
        FROM a50_daily_ohlcv
        WHERE ABS(RANDOM()) % MAX(1, (SELECT COUNT(*) FROM a50_daily_ohlcv)) < {sample_size}
        LIMIT {sample_size}
        """
    ).fetchall()

    if not sample_rows:
        sample_rows = tgt_conn.execute(
            f"SELECT ts_code, trade_date FROM a50_daily_ohlcv LIMIT {sample_size}"
        ).fetchall()

    checked = 0
    matched = 0
    mismatches = []

    check_fields = ["close", "pre_close", "adj_factor"]

    for row in sample_rows:
        ts_code = row["ts_code"]
        trade_date = row["trade_date"]

        tgt_row = tgt_conn.execute(
            "SELECT close, pre_close, adj_factor FROM a50_daily_ohlcv "
            "WHERE ts_code=? AND trade_date=?",
            (ts_code, trade_date),
        ).fetchone()

        src_row = src_conn.execute(
            "SELECT close, pre_close, adj_factor FROM stock_daily "
            "WHERE ts_code=? AND trade_date=?",
            (ts_code, trade_date),
        ).fetchone()

        if tgt_row is None or src_row is None:
            continue

        checked += 1
        row_ok = True
        diff_detail = {}

        for fld in check_fields:
            src_val = src_row[fld]
            tgt_val = tgt_row[fld]

            # 两者均为 NULL → 匹配
            if src_val is None and tgt_val is None:
                continue
            # 一方为 NULL → 不匹配
            if src_val is None or tgt_val is None:
                row_ok = False
                diff_detail[fld] = {"src": src_val, "tgt": tgt_val}
                continue

            # 数值比较（允许浮点误差 1e-6）
            if abs(float(src_val) - float(tgt_val)) > 1e-6:
                row_ok = False
                diff_detail[fld] = {"src": float(src_val), "tgt": float(tgt_val)}

        if row_ok:
            matched += 1
        else:
            mismatches.append({
                "ts_code": ts_code,
                "trade_date": trade_date,
                "diffs": diff_detail,
            })

    passed = len(mismatches) == 0

    logger.info(
        "Adj consistency check: checked=%d, matched=%d, mismatched=%d, passed=%s",
        checked, matched, len(mismatches), passed,
    )
    if mismatches:
        logger.warning("First mismatch: %s", json.dumps(mismatches[0], ensure_ascii=False))

    return {
        "checked": checked,
        "matched": matched,
        "mismatched": len(mismatches),
        "passed": passed,
        "sample_mismatches": mismatches[:5],
    }


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════

def run_etl(
    src_db_path: str = DEFAULT_SRC_DB,
    tgt_db_path: str = DEFAULT_TGT_DB,
    dry_run: bool = False,
) -> dict:
    """执行完整的 ETL 流程。"""
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("ETL: stock_daily → a50_daily_ohlcv")
    logger.info("  Source DB: %s", src_db_path)
    logger.info("  Target DB: %s", tgt_db_path)
    logger.info("=" * 60)

    # ── 1. 源数据库连接 ──
    src_conn = sqlite3.connect(src_db_path)
    src_conn.row_factory = sqlite3.Row
    logger.info("Connected to source DB")

    # ── 2. 目标数据库连接（使用 DatabaseManager，含 PRAGMA foreign_keys=ON） ──
    tgt_mgr = DatabaseManager(db_path=tgt_db_path)
    tgt_conn = tgt_mgr.get()
    fk_enabled = tgt_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    logger.info("Connected to target DB (foreign_keys=ON: %s)", fk_enabled)

    # ── 3. 确保目标表存在 ──
    if not table_exists(tgt_conn, "a50_daily_ohlcv"):
        logger.warning("Table a50_daily_ohlcv does not exist — creating...")
        create_tables(tgt_conn)
    else:
        logger.info("Table a50_daily_ohlcv already exists")

    # ── 4. 检查目标表列名，调和映射 ──
    existing_cols = check_target_schema(tgt_conn)
    logger.info("Target table columns (%d): %s", len(existing_cols), existing_cols)
    effective_map = reconcile_column_map(existing_cols)
    logger.info(
        "Effective column map (%d fields): %s",
        len(effective_map), list(effective_map.keys()),
    )

    # ── 5. 提取源数据 ──
    rows = extract_from_source(src_conn)

    if dry_run:
        logger.info("DRY RUN: extracted %d rows, skipping load", len(rows))
        src_conn.close()
        tgt_mgr.put(tgt_conn)
        return {"extracted": len(rows), "inserted": 0, "status": "dry_run"}

    # ── 6. 写入目标表 ──
    load_stats = load_to_target(tgt_conn, rows, effective_map)

    # ── 7. 验证 ──
    validation = validate_load(tgt_conn, load_stats["extracted"], src_conn=src_conn)
    load_stats["validation"] = validation

    logger.info("=" * 60)
    logger.info("Validation Summary:")
    logger.info("  Rows: %d (expected %d) — %s",
                validation["actual_rows"], validation["expected_rows"],
                "✅ MATCH" if validation["row_match"] else "❌ MISMATCH")
    logger.info("  Date range: %s", validation["date_range"])
    logger.info("  Distinct codes: %d", validation["distinct_codes"])
    logger.info("  null_reason: %s", validation["null_reason_distribution"])
    logger.info("  Time elapsed: %.2f seconds", time.time() - start_time)
    logger.info("=" * 60)

    # ── 8. 清理 ──
    src_conn.close()
    tgt_mgr.put(tgt_conn)

    return load_stats


# ════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ETL: 从 market_data.db.stock_daily 提取 A50 日线数据到 a50_daily_ohlcv"
    )
    parser.add_argument(
        "--src-db", default=DEFAULT_SRC_DB,
        help=f"源数据库路径 (默认: {DEFAULT_SRC_DB})",
    )
    parser.add_argument(
        "--tgt-db", default=DEFAULT_TGT_DB,
        help=f"目标数据库路径 (默认: {DEFAULT_TGT_DB})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅提取不写入",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细日志输出",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    stats = run_etl(
        src_db_path=args.src_db,
        tgt_db_path=args.tgt_db,
        dry_run=args.dry_run,
    )

    print("\n--- ETL Summary ---")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0 if stats.get("validation", {}).get("row_match", True) else 1


if __name__ == "__main__":
    sys.exit(main())
