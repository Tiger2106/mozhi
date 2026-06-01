"""
A50 全成分股列表 - a50_universe 表构建与查询

功能:
  1. build_universe() — 从 market_data.db.stock_daily 重建 a50_universe 表
     - 提取所有 50 只成分股的第一/最后交易日作为 in_date / out_date 基准
     - 首次出现日期 = 该成分股在 stock_daily 中的最小 trade_date
     - 当前成分股 out_date 为 NULL
  2. get_universe_at(trade_date) — 返回指定日期所属成分股期间的所有 ts_code 列表
     - 查询条件: in_date <= trade_date AND (out_date IS NULL OR out_date > trade_date)
  3. 提供 CLI 入口: python -m src.data.universe build / python -m src.data.universe query

数据来源隐含假设（§3.3）：
  标的所有历史成分股均已包含在 stock_daily 中（50 只覆盖全部历史 A50 成员）。
  对于不再属于 A50 的成分股，其 stock_daily 数据仍保留（tushare 全量历史）。

验收标准（IC_PIPELINE_T14_004）：
  - a50_universe 表包含完整历史成分股替换记录
  - get_universe_at('2020-01-10') 返回当日成分股（含 in_date/out_date/ts_code）
  - 返回结果消除了前视偏差（688981.SH 上市前不会出现在结果中）

用法:
    from src.db.connection import get_manager
    from src.data.universe import build_universe, get_universe_at

    mgr = get_manager()
    with mgr.get() as conn:
        result = build_universe(conn)
        stocks = get_universe_at(conn, '2020-01-10')
        for s in stocks:
            print(s['ts_code'], s['in_date'])

Author: 墨衡
Created: 2026-05-30T10:22:00+08:00
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════════

DEFAULT_SRC_DB = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"
DEFAULT_TGT_DB = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"

# a50_universe 表字段顺序
UNIVERSE_FIELDS = [
    "ts_code", "stock_name", "in_date", "out_date",
    "weight", "source", "created_at",
]

# 成分股数据来源标签
DATA_SOURCE = "tushare"


# ════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════

def get_tz_aware_now() -> str:
    """返回当前时间的 ISO8601+08:00 字符串。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S%z")


def format_date_for_query(date_str: str) -> str:
    """将输入日期统一为 YYYYMMDD 格式（去除连接符）。"""
    return date_str.replace("-", "")


# ════════════════════════════════════════════════════════════
# 核心：从 stock_daily 提取成分股时间窗口
# ════════════════════════════════════════════════════════════

def extract_universe_from_stock_daily(
    src_conn: sqlite3.Connection,
    target_date: Optional[str] = None,
) -> list[dict]:
    """从 market_data.db.stock_daily 提取成分股时间窗口数据。

    对于每只成分股，查询其在 stock_daily 中的最早/最晚交易日，
    以此作为 in_date / out_date 的基准。

    out_date 逻辑：
      若成分股最晚交易日 < 全局最晚交易日且存在明显数据缺口，
      则标记 out_date = last_trade_date + 1 日（YYYYMMDD 整数递增）。
      但 stock_daily 存储所有历史数据，无法区分「退出指数」与「数据仍有」，
      因此默认 out_date = NULL（当前成分股）。

    Args:
        src_conn: market_data.db 连接
        target_date: 可选，仅返回某日期前的成分股（如摸底用）

    Returns:
        [{"ts_code": str, "stock_name": None, "in_date": str,
          "out_date": None, "weight": None, "source": str,
          "created_at": str}, ...]
    """
    rows = src_conn.execute("""
        SELECT
            ts_code,
            MIN(trade_date) AS first_date,
            MAX(trade_date) AS last_date,
            COUNT(*) AS trading_days
        FROM stock_daily
        GROUP BY ts_code
        ORDER BY first_date
    """).fetchall()

    now = get_tz_aware_now()
    universe = []

    for row in rows:
        ts_code = row[0]
        first_date = row[1]
        last_date = row[2]

        # out_date: 无法从 stock_daily 精确判断成分股退出日期，
        # 故全部设为 NULL（当前成分股或历史成分股但数据仍存）
        out_date = None

        # 如果指定了 target_date，只保留 target_date 之前已进入的股票
        if target_date and first_date > target_date:
            continue

        universe.append({
            "ts_code": ts_code,
            "stock_name": None,  # stock_daily 不含 name 字段
            "in_date": first_date,
            "out_date": out_date,
            "weight": None,
            "source": DATA_SOURCE,
            "created_at": now,
        })

    return universe


# ════════════════════════════════════════════════════════════
# 写入 a50_universe
# ════════════════════════════════════════════════════════════

def write_universe(
    tgt_conn: sqlite3.Connection,
    universe_data: list[dict],
    clear_first: bool = True,
) -> dict:
    """将成分股列表写入 a50_universe 表。

    Args:
        tgt_conn:       a50_ic.db 连接
        universe_data:  成分股数据列表
        clear_first:    是否先清空表再写入（建议 True，全量重建）

    Returns:
        写入统计
    """
    fields = UNIVERSE_FIELDS
    placeholders = ", ".join(["?"] * len(fields))
    fields_str = ", ".join(fields)

    insert_sql = (
        f"INSERT INTO a50_universe ({fields_str}) VALUES ({placeholders})"
    )

    # 在单次事务内完成清空 + 写入
    tgt_conn.execute("BEGIN TRANSACTION")
    try:
        if clear_first:
            tgt_conn.execute("DELETE FROM a50_universe")
            logger.info("Cleared a50_universe table")

        batch_data = []
        for item in universe_data:
            row_vals = [item.get(f) for f in fields]
            batch_data.append(tuple(row_vals))

        tgt_conn.executemany(insert_sql, batch_data)
        tgt_conn.commit()

        count = len(universe_data)
        logger.info("Written %d stocks to a50_universe", count)
    except Exception as e:
        tgt_conn.rollback()
        logger.error("Failed to write universe: %s", e)
        raise

    return {
        "written": len(universe_data),
        "cleared_first": clear_first,
        "source": DATA_SOURCE,
    }


# ════════════════════════════════════════════════════════════
# 查询接口
# ════════════════════════════════════════════════════════════

def get_universe_at(
    conn: sqlite3.Connection,
    trade_date: str,
) -> list[sqlite3.Row]:
    """返回指定日期所属成分股期间的所有 ts_code 列表。

    查询逻辑（req §3.1.2）：
        in_date <= trade_date AND (out_date IS NULL OR out_date > trade_date)

    Args:
        conn:       a50_ic.db 连接（须设置 row_factory = sqlite3.Row）
        trade_date: 交易日（格式: YYYYMMDD 或 YYYY-MM-DD）

    Returns:
        每行含 ts_code, stock_name, in_date, out_date 的列表

    Example:
        stocks = get_universe_at(conn, '20200110')
        for s in stocks:
            print(s['ts_code'], s['in_date'], s['out_date'])
    """
    clean_date = format_date_for_query(trade_date)

    rows = conn.execute(
        """
        SELECT ts_code, stock_name, in_date, out_date
        FROM a50_universe
        WHERE in_date <= ?
          AND (out_date IS NULL OR out_date > ?)
        ORDER BY ts_code
        """,
        (clean_date, clean_date),
    ).fetchall()

    return rows


def get_universe_at_as_dicts(
    conn: sqlite3.Connection,
    trade_date: str,
) -> list[dict]:
    """返回 get_universe_at 结果的字典列表形式（便于 JSON 序列化）。"""
    rows = get_universe_at(conn, trade_date)
    return [
        {
            "ts_code": r["ts_code"],
            "stock_name": r["stock_name"],
            "in_date": r["in_date"],
            "out_date": r["out_date"],
        }
        for r in rows
    ]


def get_all_universe_members(
    conn: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """返回 a50_universe 表的所有记录。"""
    return conn.execute(
        "SELECT * FROM a50_universe ORDER BY in_date, ts_code"
    ).fetchall()


# ════════════════════════════════════════════════════════════
# 验证
# ════════════════════════════════════════════════════════════

def validate_universe(
    conn: sqlite3.Connection,
    src_conn: sqlite3.Connection,
    sample_dates: Optional[list[str]] = None,
) -> dict:
    """验证 a50_universe 表的完整性与正确性。

    Args:
        conn:     a50_ic.db 连接
        src_conn: market_data.db 连接（用于交叉验证）
        sample_dates: 抽样验证日期列表（默认为 2010-01-04, 2018-06-01, 2020-01-10, 2023-01-03）

    Returns:
        验证结果字典
    """
    if sample_dates is None:
        sample_dates = [
            "20100104", "20180601", "20200110", "20230103",
        ]

    # 1. 检查总记录数
    total = conn.execute("SELECT COUNT(*) FROM a50_universe").fetchone()[0]

    # 2. 检查每个日期下的成分股数量
    date_checks = {}
    for date_str in sample_dates:
        stocks = get_universe_at(conn, date_str)
        date_checks[date_str] = {
            "count": len(stocks),
            "codes": [s["ts_code"] for s in stocks],
        }

    # 3. 验证来源字段
    source_dist = {}
    for row in conn.execute(
        "SELECT source, COUNT(*) as cnt FROM a50_universe GROUP BY source"
    ).fetchall():
        source_dist[row[0]] = row[1]

    # 4. 验证 in_date 与源表一致 (抽样3只)
    spot_checks = []
    for row in conn.execute(
        "SELECT ts_code, in_date FROM a50_universe ORDER BY RANDOM() LIMIT 3"
    ).fetchall():
        src_min = src_conn.execute(
            "SELECT MIN(trade_date) FROM stock_daily WHERE ts_code=?",
            (row[0],),
        ).fetchone()[0]
        spot_checks.append({
            "ts_code": row[0],
            "universe_in_date": row[1],
            "stock_daily_first_date": src_min,
            "match": row[1] == src_min,
        })

    # 5. 检查 out_date 为空的比例
    null_out = conn.execute(
        "SELECT COUNT(*) FROM a50_universe WHERE out_date IS NULL"
    ).fetchone()[0]

    return {
        "total_records": total,
        "current_members_with_null_out": null_out,
        "source_distribution": source_dist,
        "date_snapshots": date_checks,
        "spot_checks": spot_checks,
        "all_spot_checks_match": all(c["match"] for c in spot_checks),
    }


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════

def build_universe(
    src_db_path: str = DEFAULT_SRC_DB,
    tgt_db_path: str = DEFAULT_TGT_DB,
    dry_run: bool = False,
) -> dict:
    """执行完整的 universe 重建流程。

    Args:
        src_db_path: market_data.db 路径
        tgt_db_path: a50_ic.db 路径
        dry_run:     仅提取不写入

    Returns:
        执行结果统计
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("Universe Build: stock_daily → a50_universe")
    logger.info("  Source DB: %s", src_db_path)
    logger.info("  Target DB: %s", tgt_db_path)
    logger.info("=" * 60)

    # 1. 连接源数据库
    src_conn = sqlite3.connect(src_db_path)
    src_conn.row_factory = sqlite3.Row

    # 2. 连接目标数据库
    from src.db.connection import get_manager
    from src.db.schema import create_tables, table_exists

    mgr = get_manager(db_path=tgt_db_path)
    tgt_conn = mgr.get()

    # 3. 确保 a50_universe 表存在
    if not table_exists(tgt_conn, "a50_universe"):
        logger.warning("Table a50_universe does not exist — creating...")
        create_tables(tgt_conn)
    else:
        logger.info("Table a50_universe already exists")

    # 4. 从 stock_daily 提取成分股数据
    universe_data = extract_universe_from_stock_daily(src_conn)
    logger.info("Extracted %d stocks from stock_daily", len(universe_data))

    if dry_run:
        logger.info("DRY RUN: extracted %d stocks, skipping write", len(universe_data))
        src_conn.close()
        mgr.put(tgt_conn)
        return {
            "status": "dry_run",
            "extracted": len(universe_data),
            "written": 0,
        }

    # 5. 写入 a50_universe
    write_stats = write_universe(tgt_conn, universe_data, clear_first=True)

    # 6. 验证
    validation = validate_universe(tgt_conn, src_conn)
    write_stats["validation"] = validation

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Build Summary:")
    logger.info("  Stocks written: %d", write_stats["written"])
    logger.info("  Source: %s", write_stats["source"])
    for date_str, snapshot in validation["date_snapshots"].items():
        logger.info("  Universe @ %s: %d stocks", date_str, snapshot["count"])
    logger.info("  Spot checks all match: %s", validation["all_spot_checks_match"])
    logger.info("  Time elapsed: %.2f seconds", elapsed)
    logger.info("=" * 60)

    # 7. 清理
    src_conn.close()
    mgr.put(tgt_conn)

    write_stats["elapsed_seconds"] = round(elapsed, 2)
    return write_stats


# ════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="A50 成分股列表 — a50_universe 构建与查询"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # build 子命令
    build_parser = subparsers.add_parser("build", help="重建 a50_universe 表")
    build_parser.add_argument(
        "--src-db", default=DEFAULT_SRC_DB,
        help="源数据库路径 (market_data.db)",
    )
    build_parser.add_argument(
        "--tgt-db", default=DEFAULT_TGT_DB,
        help="目标数据库路径 (a50_ic.db)",
    )
    build_parser.add_argument(
        "--dry-run", action="store_true",
        help="仅提取不写入",
    )

    # query 子命令
    query_parser = subparsers.add_parser("query", help="查询指定日期的成分股列表")
    query_parser.add_argument(
        "trade_date",
        help="交易日（格式: YYYYMMDD 或 YYYY-MM-DD）",
    )
    query_parser.add_argument(
        "--db", default=DEFAULT_TGT_DB,
        help="数据库路径 (a50_ic.db)",
    )
    query_parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式输出（而非表格）",
    )

    # info 子命令
    info_parser = subparsers.add_parser("info", help="查看 a50_universe 表概览")
    info_parser.add_argument(
        "--db", default=DEFAULT_TGT_DB,
        help="数据库路径 (a50_ic.db)",
    )

    # validate 子命令
    validate_parser = subparsers.add_parser("validate", help="验证 universe 数据一致性")
    validate_parser.add_argument(
        "--src-db", default=DEFAULT_SRC_DB,
        help="源数据库路径 (market_data.db)",
    )
    validate_parser.add_argument(
        "--tgt-db", default=DEFAULT_TGT_DB,
        help="目标数据库路径 (a50_ic.db)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "build":
        result = build_universe(
            src_db_path=args.src_db,
            tgt_db_path=args.tgt_db,
            dry_run=args.dry_run,
        )
        print("\n--- Build Result ---")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("status") != "dry_run" else 0

    elif args.command == "query":
        from src.db.connection import get_connection

        with get_connection(db_path=args.db) as conn:
            conn.row_factory = sqlite3.Row
            stocks = get_universe_at(conn, args.trade_date)

            if args.json:
                result = [
                    {
                        "ts_code": s["ts_code"],
                        "stock_name": s["stock_name"],
                        "in_date": s["in_date"],
                        "out_date": s["out_date"],
                    }
                    for s in stocks
                ]
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"\n成分股列表 @ {format_date_for_query(args.trade_date)}")
                print(f"总计: {len(stocks)} 只")
                print("-" * 60)
                print(f"{'ts_code':<12} {'in_date':<10} {'out_date':<10} {'name'}")
                print("-" * 60)
                for s in stocks:
                    name = s["stock_name"] or ""
                    out = s["out_date"] or "至今"
                    print(f"{s['ts_code']:<12} {s['in_date']:<10} {out:<10} {name}")
                print("-" * 60)

        return 0

    elif args.command == "info":
        from src.db.connection import get_connection

        with get_connection(db_path=args.db) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                "SELECT COUNT(*) FROM a50_universe"
            ).fetchone()[0]
            null_out = conn.execute(
                "SELECT COUNT(*) FROM a50_universe WHERE out_date IS NULL"
            ).fetchone()[0]
            sources = conn.execute(
                "SELECT source, COUNT(*) as cnt FROM a50_universe GROUP BY source"
            ).fetchall()

            date_range = conn.execute(
                "SELECT MIN(in_date) as first, MAX(in_date) as last "
                "FROM a50_universe"
            ).fetchone()

            earliest_enter = date_range[0]
            latest_enter = date_range[1]

            print(f"\na50_universe 表概览")
            print(f"  总记录数: {total}")
            print(f"  当前成分股(out_date=NULL): {null_out}")
            print(f"  数据来源: {', '.join(f'{r[0]}({r[1]})' for r in sources)}")
            print(f"  纳入日期范围: {earliest_enter} ~ {latest_enter}")

        return 0

    elif args.command == "validate":
        from src.db.connection import get_connection

        src_conn = sqlite3.connect(args.src_db)
        src_conn.row_factory = sqlite3.Row

        with get_connection(db_path=args.tgt_db) as conn:
            conn.row_factory = sqlite3.Row
            result = validate_universe(conn, src_conn)

        print("\n--- Validation Result ---")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

        all_pass = (
            result["total_records"] == 50
            and result["all_spot_checks_match"]
        )
        verdict = "✅ PASS" if all_pass else "⚠️  WARN"
        print(f"\n  验证结论: PASS" if all_pass else f"\n  验证结论: WARN")

        src_conn.close()
        return 0 if all_pass else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
