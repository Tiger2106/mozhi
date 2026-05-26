# -*- coding: utf-8 -*-
"""
order_utils.py — 订单数据模型与工具函数
作者：墨衡 (moheng)
创建时间：2026-05-12 17:52 GMT+8

提取自 order_engine.py (V1.1-005 模块拆分)

功能：
1. 数据模型：OrderAction / OrderStatus / OrderInstruction
2. 工具函数：uuid生成、时间格式化、状态映射
3. 路径常量
4. DDL语句

依赖：无（纯数据 + 标准库）
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
import logging
from src.config import SHANGHAI_TZ

logger = logging.getLogger(__name__)

# ============================================================
# 时区
# ============================================================

TZ = SHANGHAI_TZ

# ============================================================
# 文件系统路径常量
# ============================================================

SIGNALS_BASE = r"C:\Users\17699\mo_zhi_sharereports\signals"
INPROGRESS_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\paper_trade\_inprogress"
PROCESSED_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\paper_trade\_processed"
FILLS_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\paper_trade\fills"
MOZHENG_SIGNALS_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\moheng"
TASKS_SIGNALS_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\tasks"

# ============================================================
# 数据模型
# ============================================================


class OrderAction:
    """订单操作类型常量"""
    BUY_TO_OPEN = "BUY_TO_OPEN"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"
    SELL_TO_OPEN = "SELL_TO_OPEN"
    BUY_TO_CLOSE = "BUY_TO_CLOSE"


class OrderStatus:
    """订单状态常量"""
    PENDING = "PENDING"
    FROZEN = "FROZEN"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"
    SETTLED = "SETTLED"
    MARKET_REJECTED = "MARKET_REJECTED"

    _DB_MAP = {
        "FROZEN": "PENDING",
        "MARKET_REJECTED": "REJECTED",
        "SETTLED": "FILLED",
    }

    @classmethod
    def to_db_status(cls, status: str) -> str:
        """将内部状态映射到 DB 兼容状态"""
        return cls._DB_MAP.get(status, status)


@dataclass
class OrderInstruction:
    """交易指令结构"""
    action: str                     # BUY_TO_OPEN / SELL_TO_CLOSE
    symbol: str
    quantity: int
    price: float
    signal_id: Optional[str] = None
    task_id: Optional[str] = None
    stop_loss_price: Optional[float] = None
    stop_loss_type: Optional[str] = None
    notes: Optional[str] = None


# ============================================================
# DDL 语句
# ============================================================

TRANSACTIONS_DDL = """CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    symbol TEXT,
    action TEXT,
    quantity INTEGER,
    price REAL,
    commission REAL DEFAULT 0.0,
    tax REAL DEFAULT 0.0,
    trade_time TEXT,
    status TEXT DEFAULT 'PENDING',
    signal_id TEXT,
    position_id INTEGER,
    notes TEXT
);"""

POSITIONS_DDL = """CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    direction TEXT DEFAULT 'LONG',
    quantity INTEGER,
    entry_price REAL,
    entry_time TEXT,
    status TEXT DEFAULT 'OPEN',
    close_price REAL,
    close_time TEXT,
    pnl REAL,
    stop_loss_price REAL
);"""


# ============================================================
# 工具函数
# ============================================================


def generate_order_id() -> str:
    """生成唯一订单ID

    格式：ORD_YYYYMMDDHHMMSS_XXXXXXXX
    """
    now_str = datetime.now(TZ).strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:8].upper()
    return f"ORD_{now_str}_{suffix}"


def now_str() -> str:
    """返回当前时间的格式化字符串"""
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def now_iso() -> str:
    """返回当前时间的 ISO 8601 字符串"""
    return datetime.now(TZ).isoformat()
