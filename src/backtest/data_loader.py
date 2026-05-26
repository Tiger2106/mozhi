"""
墨枢 - 数据灌入脚本

用 AkshareDataSource 获取 A 股日线数据并写入 SQLite stock_daily 表，
与 load_stock_bars() 兼容，支持多标的、长周期回测数据准备。

用法::

    from backtest.data_loader import populate_stock_daily

    written = populate_stock_daily("601857", "20200101", "20260515")
    print(f"写入 {written} 条记录")
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, List, Optional

from backtest.data_source import AkshareDataSource


def _get_default_db() -> str:
    """获取默认市场数据库路径（stock_daily 写入目标）。"""
    return str(
        Path(__file__).resolve().parent.parent.parent
        / "data" / "market" / "market_data.db"
    )


def populate_stock_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    db_path: Optional[str] = None,
    ds: Optional[AkshareDataSource] = None,
) -> int:
    """
    用 AkshareDataSource 获取日线数据并写入 stock_daily 表。

    与 load_stock_bars() 兼容的表结构:
        stock_daily(code TEXT, date TEXT, open REAL, high REAL, low REAL,
                    close REAL, volume INTEGER, amount REAL)

    写入策略：
      - 自动创建表（如不存在）
      - 重复写入去重（INSERT OR IGNORE，基于 (code, date) 联合唯一约束）
      - 已有的 (code, date) 不会覆盖

    参数
    ----------
    symbol : str
        股票代码，如 "601857"。注意 AkshareDataSource.fetch_daily 使用纯代码，
        不含后缀（与 load_stock_bars 查询 stock_daily 的 code 字段一致）。
    start_date : str
        起始日期 "YYYYMMDD"。
    end_date : str
        结束日期 "YYYYMMDD"。
    db_path : str, optional
        SQLite 数据库路径。None 使用默认路径。
    ds : AkshareDataSource, optional
        数据源实例。None 则自动创建。

    返回
    -------
    int
        本次写入的记录数。
    """
    db = db_path or os.environ.get("DB_PATH") or _get_default_db()
    ds = ds or AkshareDataSource()

    # 1. 获取日线数据
    df = ds.fetch_daily(symbol, start_date, end_date)

    if df is None or df.empty:
        return 0

    # 2. 连接数据库并建表
    conn = sqlite3.connect(db)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_daily (
            code    TEXT,
            date    TEXT,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  INTEGER,
            amount  REAL,
            PRIMARY KEY (code, date)
        )
        """
    )

    # 3. 逐行写入（INSERT OR IGNORE 去重）
    inserted = 0
    for _, row in df.iterrows():
        date_val = row["date"]
        # 如果 date 是 datetime 类型，格式化为 YYYYMMDD 字符串
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y%m%d")
        else:
            date_str = str(date_val).replace("-", "")

        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO stock_daily
                    (code, date, open, high, low, close, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    date_str,
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    int(row["volume"]),
                    float(row["amount"]),
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
        except (ValueError, TypeError):
            # 跳过异常行
            continue

    conn.commit()
    conn.close()

    print(
        f"[data_loader] {symbol}: 获取 {len(df)} 条, "
        f"实际写入 {inserted} 条 (去重后)"
    )
    return inserted


_DEFAULT_DB = str(
    Path(__file__).resolve().parent.parent.parent
    / "data" / "market" / "market_data.db"
)


def load_stock_bars(
    symbol: str,
    start_date: str = "",
    end_date: str = "",
    db_path: Optional[str] = None,
) -> List["Bar"]:
    """
    (共享函数) 从 stock_daily 表加载股票K线数据。

    VWAP = amount / volume 直接从数据库字段计算。

    数据库表结构:
        stock_daily(code, date, open, high, low, close, volume, amount, ...)

    返回按日期升序排列的 Bar 列表。
    """
    from backtest.backtest_engine import Bar

    db = db_path or os.environ.get("DB_PATH") or _DEFAULT_DB
    if not os.path.exists(db):
        raise FileNotFoundError(f"数据库文件不存在: {db}")

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    query = (
        "SELECT date, open, high, low, close, volume, amount "
        "FROM stock_daily WHERE code=?"
    )
    # 兼容 "601857.SH" 或 "000001.SZ" 或 "600519" 格式
    query_code = symbol.split(".")[0]
    params: List[Any] = [query_code]

    if start_date:
        start_date_clean = start_date.replace("-", "")
        query += " AND date >= ?"
        params.append(start_date_clean)
    if end_date:
        end_date_clean = end_date.replace("-", "")
        query += " AND date <= ?"
        params.append(end_date_clean)

    query += " ORDER BY date ASC"

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        raise ValueError(
            f"未找到 {symbol} 在 {start_date or '起始'} ~ {end_date or '至今'} 的数据"
        )

    bars: List[Bar] = []
    for row in rows:
        date_str, open_, high_, low_, close_, volume_, amount_ = row
        bar = Bar(
            date=str(date_str),
            symbol=symbol,
            open=float(open_),
            high=float(high_),
            low=float(low_),
            close=float(close_),
            volume=int(volume_),
            vwap=float(amount_) / float(volume_) if float(volume_) > 0 else 0.0,
        )
        bars.append(bar)

    return bars
