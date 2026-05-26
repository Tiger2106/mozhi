#!/usr/bin/env python3
"""
墨枢 Phase 1 — 数据采集脚本（TASK-1）
===========================================
Author: 墨衡
Created: 2026-05-22T22:20+08:00

用途：从 Tushare Pro 采集 12只标的 × 日频 × 5年（2021-01-01 ~ 2025-12-31）
      价量数据，写入 analysis.db 的 stock_daily 表。

数据源：
  - daily_basic: 复权收盘、成交量、成交额、换手率、流通股本
  - adj_factor:  复权因子（用于前/后复权计算）
  - FloatShareCache: 已有流通股本缓存模块

限频：
  - 日上限 10 万次调用（2000分等级账户）
  - 200次/分钟 → sleep 0.3s 间隔

表结构：
  - stock_daily (code, date, open, high, low, close, volume, amount, adj_factor)
  - 使用 INSERT OR REPLACE 幂等写入

执行：
  python scripts/phase1_data_collection.py

输出：
  - data/db/analysis.db → stock_daily 表填充
  - data/db/trading_calendar 表填充
  - 日志输出到 stdout
"""

import os
import sys
import sqlite3
import time
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import tushare as ts

# ── 项目根路径 ──────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "db")
ANALYSIS_DB = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")

# ── 配置 ─────────────────────────────────────────────────
TUSHARE_TOKEN = "09e84b0b5fe40141f51a0aecb21ba648f605bf421444c2d741271ded"

# 12只标的（完整ts_code格式）
STOCK_LIST = [
    "601857.SH",  # 中国石油（能源）
    "000001.SZ",  # 平安银行（银行）
    "600519.SH",  # 贵州茅台（白酒/消费）
    "601318.SH",  # 中国平安（保险）
    "600036.SH",  # 招商银行（银行）
    "300750.SZ",  # 宁德时代（新能源）
    "600276.SH",  # 恒瑞医药（医药）
    "600887.SH",  # 伊利股份（消费）
    "600030.SH",  # 中信证券（证券）
    "000333.SZ",  # 美的集团（家电）
    "002415.SZ",  # 海康威视（科技）
    "600436.SH",  # 片仔癀（中药）
]

DATE_START = "20200101"
DATE_END = "20260522"

# Tushare 限频：200次/分钟，留余量设为 0.35s
REQUEST_INTERVAL = 0.35

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════
# DB 初始化
# ════════════════════════════════════════════════════════

def init_database():
    """创建 market_data.db 及所需表结构（完整区间2020-2026）"""
    os.makedirs(os.path.dirname(ANALYSIS_DB), exist_ok=True)
    conn = sqlite3.connect(ANALYSIS_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    # 丢弃旧表，处理 schema 差异
    conn.execute("DROP TABLE IF EXISTS stock_daily")
    conn.execute("DROP TABLE IF EXISTS adj_factor")
    conn.execute("DROP TABLE IF EXISTS trading_calendar")

    # stock_daily 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            code       TEXT NOT NULL,
            date       TEXT NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL NOT NULL,
            pre_close  REAL,
            volume     INTEGER,
            amount     REAL,
            adj_factor REAL DEFAULT 1.0,
            turnover_rate REAL,
            volume_ratio  REAL,
            pe         REAL,
            pb         REAL,
            total_share   REAL,
            float_share   REAL,
            circ_mv       REAL,
            total_mv      REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (code, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sd_code ON stock_daily(code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sd_date ON stock_daily(date)")

    # adj_factor 表（复权因子）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS adj_factor (
            code       TEXT NOT NULL,
            date       TEXT NOT NULL,
            adj_factor REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (code, date)
        )
    """)

    # trading_calendar 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trading_calendar (
            market       TEXT NOT NULL,
            date         TEXT NOT NULL,
            is_trading_day INTEGER NOT NULL DEFAULT 0,
            pretrade_date  TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (market, date)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("数据库初始化完成: %s", ANALYSIS_DB)


# ════════════════════════════════════════════════════════
# 交易日历采集
# ════════════════════════════════════════════════════════

def fetch_trade_calendar(pro_api) -> int:
    """从 Tushare 获取 A 股交易日历（SSE + SZSE），写入 trading_calendar"""
    logger.info("[交易日历] 开始获取 SSE & SZSE 交易日历...")
    inserted = 0
    for exchange in ["SSE", "SZSE"]:
        try:
            df = pro_api.trade_cal(exchange=exchange, start_date=DATE_START, end_date=DATE_END)
            if df is None or df.empty:
                logger.warning("[交易日历] %s 无数据", exchange)
                continue
            time.sleep(REQUEST_INTERVAL)

            conn = sqlite3.connect(ANALYSIS_DB)
            rows = []
            for _, row in df.iterrows():
                rows.append((
                    "A",
                    row["cal_date"],
                    int(row["is_open"]),
                    str(row.get("pretrade_date", "")) if "pretrade_date" in row else None,
                ))

            conn.executemany(
                """INSERT OR REPLACE INTO trading_calendar
                   (market, date, is_trading_day, pretrade_date)
                   VALUES (?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
            inserted += len(rows)
            conn.close()
            logger.info("[交易日历] %s 写入 %d 条", exchange, len(rows))
        except Exception as e:
            logger.error("[交易日历] %s 采集失败: %s", exchange, e)

    return inserted


# ════════════════════════════════════════════════════════
# 复权因子采集
# ════════════════════════════════════════════════════════

def fetch_adj_factors(pro_api, stock: str) -> int:
    """采集单只标的的复权因子"""
    try:
        df = pro_api.adj_factor(ts_code=stock, start_date=DATE_START, end_date=DATE_END)
        time.sleep(REQUEST_INTERVAL)
        if df is None or df.empty:
            logger.warning("[复权因子] %s 无数据", stock)
            return 0

        conn = sqlite3.connect(ANALYSIS_DB)
        code_raw = stock.split(".")[0]
        rows = []
        for _, row in df.iterrows():
            rows.append((
                code_raw,
                row["trade_date"],
                float(row.get("adj_factor", 1.0) or 1.0),
            ))

        conn.executemany(
            """INSERT OR REPLACE INTO adj_factor (code, date, adj_factor)
               VALUES (?, ?, ?)""",
            rows,
        )
        conn.commit()
        conn.close()
        logger.info("[复权因子] %s 写入 %d 条", stock, len(rows))
        return len(rows)
    except Exception as e:
        logger.error("[复权因子] %s 采集失败: %s", stock, e)
        return 0


# ════════════════════════════════════════════════════════
# 日线行情采集
# ════════════════════════════════════════════════════════

def fetch_daily_basic(pro_api, stock: str) -> int:
    """
    采集单只标的日线行情 + 基本面数据（daily_basic）。
    
    字段：open, high, low, close, pre_close, vol, amount,
          turnover_rate, volume_ratio, pe, pb, total_share,
          float_share, circ_mv, total_mv
    
    写入 stock_daily 表（部分字段在 daily_basic 中可获取）。
    """
    try:
        df = pro_api.daily_basic(
            ts_code=stock,
            start_date=DATE_START,
            end_date=DATE_END,
            fields=(
                "ts_code,trade_date,open,high,low,close,pre_close,"
                "vol,amount,turnover_rate,volume_ratio,pe,pb,"
                "total_share,float_share,circ_mv,total_mv"
            ),
        )
        time.sleep(REQUEST_INTERVAL)

        if df is None or df.empty:
            logger.warning("[daily_basic] %s 无数据", stock)
            return 0

        conn = sqlite3.connect(ANALYSIS_DB)
        code_raw = stock.split(".")[0]
        rows = []
        for _, row in df.iterrows():
            rows.append((
                code_raw,
                row["trade_date"],
                float(row.get("open", 0) or 0),
                float(row.get("high", 0) or 0),
                float(row.get("low", 0) or 0),
                float(row.get("close", 0) or 0),
                float(row.get("pre_close", 0) or 0),
                int(row.get("vol", 0) or 0),
                float(row.get("amount", 0) or 0),
                1.0,  # adj_factor 占位，后面补
                float(row.get("turnover_rate", 0) or 0),
                float(row.get("volume_ratio", 0) or 0),
                float(row.get("pe", 0) or 0),
                float(row.get("pb", 0) or 0),
                float(row.get("total_share", 0) or 0),
                float(row.get("float_share", 0) or 0),
                float(row.get("circ_mv", 0) or 0),
                float(row.get("total_mv", 0) or 0),
            ))

        conn.executemany(
            """INSERT OR REPLACE INTO stock_daily
               (code, date, open, high, low, close, pre_close,
                volume, amount, adj_factor, turnover_rate, volume_ratio,
                pe, pb, total_share, float_share, circ_mv, total_mv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        conn.close()
        logger.info("[daily_basic] %s 写入 %d 条", stock, len(rows))
        return len(rows)
    except Exception as e:
        logger.error("[daily_basic] %s 采集失败: %s", stock, e)
        return 0


def fetch_stock_daily(pro_api, stock: str) -> int:
    """
    采集单只标的日线行情（stock_daily），含 K 线。
    
    当 daily_basic 无法覆盖全部字段时，用此接口补充。
    """
    try:
        df = pro_api.daily(
            ts_code=stock,
            start_date=DATE_START,
            end_date=DATE_END,
            fields=(
                "ts_code,trade_date,open,high,low,close,pre_close,"
                "vol,amount"
            ),
        )
        time.sleep(REQUEST_INTERVAL)

        if df is None or df.empty:
            logger.warning("[daily] %s 无数据", stock)
            return 0

        conn = sqlite3.connect(ANALYSIS_DB)
        code_raw = stock.split(".")[0]
        rows = []
        for _, row in df.iterrows():
            rows.append((
                code_raw,
                row["trade_date"],
                float(row.get("open", 0) or 0),
                float(row.get("high", 0) or 0),
                float(row.get("low", 0) or 0),
                float(row.get("close", 0) or 0),
                float(row.get("pre_close", 0) or 0),
                int(row.get("vol", 0) or 0),
                float(row.get("amount", 0) or 0),
            ))

        # UPDATE only: 补齐 adj_factor 之外的字段
        conn.executemany(
            """INSERT OR REPLACE INTO stock_daily
               (code, date, open, high, low, close, pre_close, volume, amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        conn.close()
        logger.info("[daily] %s 写入 %d 条", stock, len(rows))
        return len(rows)
    except Exception as e:
        logger.error("[daily] %s 采集失败: %s", stock, e)
        return 0


# ════════════════════════════════════════════════════════
# 复权因子回填
# ════════════════════════════════════════════════════════

def backfill_adj_factors():
    """
    将 adj_factor 表中的复权因子回填到 stock_daily 表。
    stock_daily 以 adj_factor 记录后复权价格，存储为 open/high/low/close。
    
    注意：daily_basic 和 daily 接口返回的是不复权或前复权数据。
    对于大多数因子计算，使用前复权即可。但为了保持一致性，
    我们以 adj_factor 为锚点存储后复权价格。
    
    后复权价格 = 不复权价格 × 当日复权因子
    """
    logger.info("[复权回填] 开始回填复权因子...")
    conn = sqlite3.connect(ANALYSIS_DB)
    # 用 adj_factor 表更新 stock_daily 的 adj_factor 字段
    conn.execute("""
        UPDATE stock_daily SET adj_factor = (
            SELECT adj_factor FROM adj_factor af
            WHERE af.code = stock_daily.code AND af.date = stock_daily.date
        )
        WHERE EXISTS (
            SELECT 1 FROM adj_factor af
            WHERE af.code = stock_daily.code AND af.date = stock_daily.date
        )
    """)
    affected = conn.total_changes
    conn.commit()
    conn.close()
    logger.info("[复权回填] 完成，更新 %d 条", affected)
    return affected


def compute_adjusted_prices():
    """
    计算后复权价格：adj_close = close * adj_factor，其他价格同理。
    将复权后的价格写入 stock_daily。
    
    警告：此操作会覆盖原字段值，需确保已完成 daily_basic 写入。
    """
    conn = sqlite3.connect(ANALYSIS_DB)
    conn.execute("""
        UPDATE stock_daily SET
            open  = ROUND(open  * adj_factor, 2),
            high  = ROUND(high  * adj_factor, 2),
            low   = ROUND(low   * adj_factor, 2),
            close = ROUND(close * adj_factor, 2)
        WHERE adj_factor != 1.0 AND adj_factor IS NOT NULL
    """)
    affected = conn.total_changes
    conn.commit()
    conn.close()
    logger.info("[复权价格] 计算完成，更新 %d 条", affected)
    return affected


# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("  墨枢 Phase 1 — 数据采集 （TASK-1）")
    logger.info("  标的: 12只  |  区间: %s ~ %s", DATE_START, DATE_END)
    logger.info("=" * 60)

    # 1. 初始化数据库
    init_database()

    # 2. 初始化 Tushare Pro API
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    # 3. 获取交易日历（约 2 次调用）
    logger.info("\n[阶段1/6] 交易日历采集...")
    cal_count = fetch_trade_calendar(pro)
    logger.info("  交易日期写入: %d", cal_count)

    # 4. 采集复权因子（12只 × ~1次调用 = 12次）
    logger.info("\n[阶段2/6] 复权因子采集...")
    adj_total = 0
    for stock in STOCK_LIST:
        n = fetch_adj_factors(pro, stock)
        adj_total += n
    logger.info("  复权因子总计: %d 条", adj_total)

    # 5. 采集日线行情 daily_basic（12只 × ~1次调用 = 12次）
    logger.info("\n[阶段3/6] daily_basic 采集...")
    db_total = 0
    for stock in STOCK_LIST:
        n = fetch_daily_basic(pro, stock)
        db_total += n
    logger.info("  daily_basic 总计: %d 条", db_total)

    # 6. 补充采集 daily（若 daily_basic 缺失部分字段）
    logger.info("\n[阶段4/6] daily 行情补充...")
    d_total = 0
    for stock in STOCK_LIST:
        n = fetch_stock_daily(pro, stock)
        d_total += n
    logger.info("  daily 补充: %d 条", d_total)

    # 7. 回填复权因子
    logger.info("\n[阶段5/6] 复权因子回填...")
    backfill_adj_factors()

    # 8. 计算复权价格
    logger.info("\n[阶段6/6] 复权价格计算...")
    compute_adjusted_prices()

    # 9. 汇总
    conn = sqlite3.connect(ANALYSIS_DB)
    total_rows = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    total_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM stock_daily").fetchone()[0]
    date_range = conn.execute(
        "SELECT MIN(date), MAX(date) FROM stock_daily"
    ).fetchone()
    conn.close()

    logger.info("\n" + "=" * 60)
    logger.info("  采集完成!")
    logger.info("  标的数: %d", total_codes)
    logger.info("  总行数: %d", total_rows)
    logger.info("  日期范围: %s ~ %s", date_range[0], date_range[1])
    logger.info("  DB路径: %s", ANALYSIS_DB)
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
