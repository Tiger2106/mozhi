# -*- coding: utf-8 -*-
"""
signal_position_linker.py — 信号→仓位映射模块
作者：墨衡 (moheng)
创建时间：2026-05-12 17:53 GMT+8

提取自 order_engine.py (V1.1-005 模块拆分)

功能：
1. get_positions() — 从 DB 获取当前净多头持仓
2. 信号→持仓关联查询（根据信号信息定位已有持仓）

依赖：
  - SQLite DB（直接查询 transactions/positions 表）
  - 不依赖 OrderEngine 实例，接受 db_conn 或 db_path 参数
"""

import logging
import sqlite3
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


def get_positions_by_conn(conn: sqlite3.Connection) -> List[Dict]:
    """获取当前净多头持仓（基于 FILLED 交易记录）。

    参数：
        conn — 已连接的 SQLite 连接对象

    返回：
        持仓列表，每个元素为 {symbol, net_qty, avg_cost, total_cost}
        失败返回 []
    """
    try:
        cur = conn.execute(
            "SELECT symbol, "
            "SUM(CASE WHEN action IN ('BUY_TO_OPEN','BUY') THEN fill_quantity ELSE -fill_quantity END) AS net_qty, "
            "AVG(fill_price) AS avg_cost, "
            "SUM(fill_price * fill_quantity) AS total_cost "
            "FROM transactions WHERE status='FILLED' "
            "GROUP BY symbol HAVING net_qty > 0"
        )
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        logger.error(f"[SignalPositionLinker] 查询持仓失败: {e}")
        return []


def find_open_position(conn: sqlite3.Connection, symbol: str) -> Optional[Dict]:
    """根据品种代码查找当前未平仓的持仓记录。

    用于确认卖出（SELL_TO_CLOSE）时定位目标持仓。

    参数：
        conn — 已连接的 SQLite 连接对象
        symbol — 品种代码

    返回：
        持仓字典 {"id", "quantity", "entry_price", ...}，未找到返回 None
    """
    try:
        row = conn.execute(
            "SELECT id, quantity, entry_price, entry_time, stop_loss_price "
            "FROM positions WHERE symbol = ? AND status = 'OPEN' "
            "ORDER BY entry_time ASC LIMIT 1",
            (symbol,)
        ).fetchone()
        if row is None:
            return None
        cols = ["id", "quantity", "entry_price", "entry_time", "stop_loss_price"]
        return dict(zip(cols, row))
    except Exception as e:
        logger.error(f"[SignalPositionLinker] 查找持仓失败: {e}")
        return None


def get_open_position_by_id(conn: sqlite3.Connection, position_id: int) -> Optional[Dict]:
    """通过持仓ID获取持仓详情。

    参数：
        conn — 已连接的 SQLite 连接对象
        position_id — 持仓记录ID

    返回：
        持仓字典，未找到返回 None
    """
    try:
        row = conn.execute(
            "SELECT id, symbol, quantity, entry_price, entry_time, status, stop_loss_price "
            "FROM positions WHERE id = ?",
            (position_id,)
        ).fetchone()
        if row is None:
            return None
        cols = ["id", "symbol", "quantity", "entry_price", "entry_time", "status", "stop_loss_price"]
        return dict(zip(cols, row))
    except Exception as e:
        logger.error(f"[SignalPositionLinker] 查询持仓#{position_id}失败: {e}")
        return None


def get_remaining_qty(conn: sqlite3.Connection, symbol: str) -> int:
    """获取指定品种的剩余未平仓数量。

    参数：
        conn — 已连接的 SQLite 连接对象
        symbol — 品种代码

    返回：
        剩余持仓股数
    """
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM positions "
            "WHERE symbol = ? AND status = 'OPEN'",
            (symbol,)
        ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"[SignalPositionLinker] 查询剩余数量失败: {e}")
        return 0
