"""
Schema DDL 定义与执行器

三张表的 DDL（含字段定义、索引、唯一约束、外键语义）：

1. a50_daily_ohlcv  — 上证50成分股日线行情（26 字段设计，20 字段落地 + 索引）
2. a50_cross_ic_result  — 截面 IC 计算结果（10 字段 + 联合唯一索引）
3. a50_universe — 成分股列表（8 字段 + 2 联合索引）

验收标准（IC_PIPELINE_T14_001）：
  - 执行 DDL 后三表创建成功
  - 联合唯一索引存在（trade_date+factor_name+source_version）
  - PRAGMA foreign_keys=ON 生效

用法:
    from src.db.schema import create_tables, table_exists
    from src.db.connection import get_connection

    with get_connection() as conn:
        create_tables(conn)
        assert table_exists(conn, "a50_daily_ohlcv")

Author: 墨衡
Created: 2026-05-30T09:36:00+08:00
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# DDL 定义
# ════════════════════════════════════════════════════════════

DDL_A50_DAILY_OHLCV = """
CREATE TABLE IF NOT EXISTS a50_daily_ohlcv (
    -- 主键
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 标的标识（§3.1.1）
    ts_code         TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,
    -- 价格字段（§3.1.1 墨萱 T+7 验收要求）
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL    NOT NULL,
    pre_close       REAL,
    -- 量价字段
    volume          REAL,
    amount          REAL,
    -- 基本面字段
    turnover_rate   REAL,
    pe              REAL,
    pb              REAL,
    -- 复权因子（§3.1.3 后复权计算依赖）
    adj_factor      REAL    NOT NULL,
    -- 市值字段
    total_mv        REAL,
    circ_mv         REAL,
    free_float      REAL,
    -- 元数据
    source_version  TEXT    NOT NULL DEFAULT 'v1',
    null_reason     TEXT,
    created_at      TEXT    NOT NULL
);
""".strip()

# a50_daily_ohlcv 索引（§3.1.2）
DDL_IDX_A50_DAILY_PK = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_a50_daily_pk
    ON a50_daily_ohlcv(ts_code, trade_date);
""".strip()

DDL_IDX_A50_DAILY_DATE = """
CREATE INDEX IF NOT EXISTS idx_a50_daily_date
    ON a50_daily_ohlcv(trade_date);
""".strip()

DDL_IDX_A50_DAILY_CODE = """
CREATE INDEX IF NOT EXISTS idx_a50_daily_code
    ON a50_daily_ohlcv(ts_code);
""".strip()

# ════════════════════════════════════════════════════════════
# a50_cross_ic_result — 截面 IC 结果表
# ════════════════════════════════════════════════════════════

DDL_A50_CROSS_IC_RESULT = """
CREATE TABLE IF NOT EXISTS a50_cross_ic_result (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT    NOT NULL,
    factor_name     TEXT    NOT NULL,
    ic_value        REAL,
    rank_ic         REAL,
    p_value         REAL,
    num_stocks      INTEGER NOT NULL,
    adjusted_ic     REAL,
    source_version  TEXT    NOT NULL,
    created_at      TEXT    NOT NULL
);
""".strip()

# a50_cross_ic_result 索引（§3.2.2 — 玄知+墨衡一致同意）
DDL_IDX_IC_UNIQ = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_ic_uniq
    ON a50_cross_ic_result(trade_date, factor_name, source_version);
""".strip()

# ════════════════════════════════════════════════════════════
# a50_universe — 成分股列表表
# ════════════════════════════════════════════════════════════

DDL_A50_UNIVERSE = """
CREATE TABLE IF NOT EXISTS a50_universe (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code         TEXT    NOT NULL,
    stock_name      TEXT,
    in_date         TEXT    NOT NULL,
    out_date        TEXT,
    weight          REAL,
    source          TEXT    NOT NULL,
    created_at      TEXT    NOT NULL
);
""".strip()

# a50_universe 索引（§3.3.2 v2.0 补充）
DDL_IDX_UNIVERSE_CODE_IN_DATE = """
CREATE INDEX IF NOT EXISTS idx_universe_code_in_date
    ON a50_universe(ts_code, in_date);
""".strip()

DDL_IDX_UNIVERSE_IN_OUT_DATE = """
CREATE INDEX IF NOT EXISTS idx_universe_in_out_date
    ON a50_universe(in_date, out_date);
""".strip()

# ════════════════════════════════════════════════════════════
# DDL 执行顺序（表间无交叉外键引用，顺序无关）
# ════════════════════════════════════════════════════════════

DDL_SEQUENCE = [
    # 表创建
    ("a50_daily_ohlcv", DDL_A50_DAILY_OHLCV),
    ("a50_cross_ic_result", DDL_A50_CROSS_IC_RESULT),
    ("a50_universe", DDL_A50_UNIVERSE),
    # a50_daily_ohlcv 索引
    ("idx_a50_daily_pk", DDL_IDX_A50_DAILY_PK),
    ("idx_a50_daily_date", DDL_IDX_A50_DAILY_DATE),
    ("idx_a50_daily_code", DDL_IDX_A50_DAILY_CODE),
    # a50_cross_ic_result 索引
    ("idx_ic_uniq", DDL_IDX_IC_UNIQ),
    # a50_universe 索引
    ("idx_universe_code_in_date", DDL_IDX_UNIVERSE_CODE_IN_DATE),
    ("idx_universe_in_out_date", DDL_IDX_UNIVERSE_IN_OUT_DATE),
]


# ════════════════════════════════════════════════════════════
# 执行器
# ════════════════════════════════════════════════════════════

def create_tables(conn, ddl_sequence=None) -> list[dict]:
    """依次执行 DDL 建表（幂等：CREATE IF NOT EXISTS）。

    Args:
        conn: SQLite 连接对象（须已设置 PRAGMA foreign_keys=ON）
        ddl_sequence: 可选的 DDL 列表覆盖（默认使用 DDL_SEQUENCE）

    Returns:
        每个 DDL 的执行结果列表：
        [{"name": "a50_daily_ohlcv", "success": True}, ...]

    注：使用 execute 而非 executescript 以便逐条捕获异常。
    """
    ddl_sequence = ddl_sequence or DDL_SEQUENCE
    results = []

    for name, ddl in ddl_sequence:
        try:
            conn.execute(ddl)
            results.append({"name": name, "success": True})
            logger.info("DDL OK: %s", name)
        except Exception as e:
            results.append({"name": name, "success": False, "error": str(e)})
            logger.error("DDL FAIL: %s — %s", name, e)

    return results


def drop_tables(conn, confirm: bool = False) -> list[dict]:
    """删除所有三张表（仅供测试用）。必须显式确认。

    Args:
        conn: SQLite 连接对象
        confirm: 必须为 True 才会执行删除

    Returns:
        删除操作结果列表
    """
    if not confirm:
        raise RuntimeError("drop_tables() 需要 confirm=True 确认")

    table_names = [
        "a50_daily_ohlcv",
        "a50_cross_ic_result",
        "a50_universe",
    ]
    results = []
    for name in reversed(table_names):  # 逆序删除避免外键依赖
        try:
            conn.execute(f"DROP TABLE IF EXISTS {name}")
            results.append({"name": name, "dropped": True})
            logger.warning("DROPPED TABLE: %s", name)
        except Exception as e:
            results.append({"name": name, "dropped": False, "error": str(e)})
            logger.error("DROP FAIL: %s — %s", name, e)
    return results


# ════════════════════════════════════════════════════════════
# 验证辅助
# ════════════════════════════════════════════════════════════

def table_exists(conn, table_name: str) -> bool:
    """检查表是否存在。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def index_exists(conn, index_name: str) -> bool:
    """检查索引是否存在。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchone()
    return row is not None


def verify_schema(conn) -> dict:
    """验证三表及关键索引是否全部已创建。

    Returns:
        {
            "all_tables_created": True/False,
            "all_indexes_created": True/False,
            "tables": {"a50_daily_ohlcv": True, ...},
            "indexes": {"idx_a50_daily_pk": True, ...},
            "foreign_keys_enabled": True/False,
            "table_column_count": {...}
        }
    """
    required_tables = [
        "a50_daily_ohlcv",
        "a50_cross_ic_result",
        "a50_universe",
    ]
    required_indexes = [
        "idx_a50_daily_pk",
        "idx_a50_daily_date",
        "idx_a50_daily_code",
        "idx_ic_uniq",
        "idx_universe_code_in_date",
        "idx_universe_in_out_date",
    ]

    result = {
        "tables": {},
        "indexes": {},
        "foreign_keys_enabled": False,
        "table_column_count": {},
    }

    # 检查表
    for t in required_tables:
        exists = table_exists(conn, t)
        result["tables"][t] = exists
        if exists:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
            result["table_column_count"][t] = len(cols)

    result["all_tables_created"] = all(result["tables"].values())

    # 检查索引
    for idx in required_indexes:
        exists = index_exists(conn, idx)
        result["indexes"][idx] = exists

    result["all_indexes_created"] = all(result["indexes"].values())

    # 检查 foreign_keys
    row = conn.execute("PRAGMA foreign_keys").fetchone()
    result["foreign_keys_enabled"] = row[0] == 1 if row else False

    # 汇总
    result["passed"] = (
        result["all_tables_created"]
        and result["all_indexes_created"]
        and result["foreign_keys_enabled"]
    )

    return result


def get_schema_ddl() -> str:
    """返回完整的可执行 DDL 脚本字符串（含注释）。"""
    lines = [
        "-- =================================================",
        "-- A50 截面IC 管线 — Schema DDL",
        "-- Generated by src.db.schema",
        f"-- Created: 2026-05-30T09:36:00+08:00",
        "-- =================================================",
        "",
        "PRAGMA foreign_keys = ON;",
        "PRAGMA journal_mode = WAL;",
        "",
    ]
    for _, ddl in DDL_SEQUENCE:
        lines.append(ddl)
        lines.append("")
    return "\n".join(lines)
