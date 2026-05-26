#!/usr/bin/env python3
"""
knowledge.db 信号相关表 — schema 定义
========================================
用于记录 Signal 对象、消费记录和归档索引。
使用标准 Python sqlite3 模块，无需复杂 ORM。

Created with: moheng (墨衡)
created_time: 2026-05-20T13:33+08:00
version: 1.0
"""

import sqlite3
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── DDL 定义 ────────────────────────────────────────────────

CREATE_SIGNALS_TABLE = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id       TEXT PRIMARY KEY,          -- UUID v4
    symbol          TEXT NOT NULL,             -- 证券代码
    direction       TEXT NOT NULL,             -- BUY / SELL / HOLD
    confidence      REAL NOT NULL,             -- 置信度 [0.0, 1.0]
    horizon         TEXT NOT NULL,             -- short / mid / long
    signal_type     TEXT NOT NULL,             -- 信号类型（如 trend, reversal, momentum）
    timestamp       TEXT NOT NULL,             -- ISO 8601
    protocol_version TEXT NOT NULL DEFAULT '1.0.0',
    extras          TEXT                       -- JSON 扩展字段
);
"""

CREATE_CONSUMED_SIGNALS_TABLE = """
CREATE TABLE IF NOT EXISTS consumed_signals (
    signal_id       TEXT PRIMARY KEY,
    consumed_at     TEXT NOT NULL,             -- ISO 8601
    consumer_id     TEXT NOT NULL
);
"""

CREATE_ARCHIVE_INDEX_TABLE = """
CREATE TABLE IF NOT EXISTS archive_index (
    archive_id      TEXT PRIMARY KEY,
    signal_id       TEXT NOT NULL,
    archived_at     TEXT NOT NULL,             -- ISO 8601
    archive_type    TEXT NOT NULL
);
"""

# ── 索引 ────────────────────────────────────────────────────

CREATE_INDEX_CONSUMED_AT = """
CREATE INDEX IF NOT EXISTS idx_consumed_signals_consumed_at
    ON consumed_signals(consumed_at);
"""

CREATE_INDEX_ARCHIVE_SIGNAL_ID = """
CREATE INDEX IF NOT EXISTS idx_archive_index_signal_id
    ON archive_index(signal_id);
"""

CREATE_INDEX_SIGNALS_SYMBOL = """
CREATE INDEX IF NOT EXISTS idx_signals_symbol
    ON signals(symbol);
"""

CREATE_INDEX_SIGNALS_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS idx_signals_timestamp
    ON signals(timestamp);
"""

ALL_DDL = [
    CREATE_SIGNALS_TABLE,
    CREATE_CONSUMED_SIGNALS_TABLE,
    CREATE_ARCHIVE_INDEX_TABLE,
    CREATE_INDEX_CONSUMED_AT,
    CREATE_INDEX_ARCHIVE_SIGNAL_ID,
    CREATE_INDEX_SIGNALS_SYMBOL,
    CREATE_INDEX_SIGNALS_TIMESTAMP,
]


# ── 初始化入口 ──────────────────────────────────────────────

def init_database(db_path: str) -> bool:
    """
    初始化 knowledge.db，创建信号相关所有表。

    Args:
        db_path: SQLite 数据库文件路径

    Returns:
        True 初始化成功，False 失败
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        for ddl in ALL_DDL:
            cursor.execute(ddl)

        conn.commit()
        logger.info(f"[db_schema] 数据库初始化完成: {db_path}")

        # 验证表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        logger.info(f"[db_schema] 已创建表: {', '.join(tables)}")
        return True

    except sqlite3.Error as e:
        logger.error(f"[db_schema] 数据库初始化失败: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def get_tables(db_path: str) -> List[str]:
    """
    查询数据库中的所有表。

    Args:
        db_path: SQLite 数据库文件路径

    Returns:
        表名列表
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables
    except sqlite3.Error as e:
        logger.error(f"[db_schema] 查询表失败: {e}")
        return []


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("用法: python db_schema.py <db_path>")
        sys.exit(1)

    success = init_database(sys.argv[1])
    sys.exit(0 if success else 1)
