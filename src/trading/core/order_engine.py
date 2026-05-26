# -*- coding: utf-8 -*-
"""
order_engine.py — 模拟炒股订单生命周期管理器（入口模块）
作者：墨衡 (moheng)
创建时间：2026-05-04 16:15 GMT+8
版本：v4.0 — V1.1-005 模块拆分

变更记录：
  v4.0 (2026-05-12): V1.1-005 模块拆分。核心逻辑移至以下模块：
    - order_lifecycle.py：订单生命周期管理
    - order_utils.py：数据模型与工具函数
    - order_fees.py：费用计算接口
    - price_utils.py：行情价格与滑点
    - signal_position_linker.py：信号→仓位映射
  本文件仅保留：
    - __init__（账户管理器初始化、连接管理）
    - set_slippage（运行时配置）
    - set_connection / _get_conn / _ensure_tables
    - 从各模块导入并委托分发

# 向后兼容性：
  所有 import 路径不变：
    from paper_trade.order_engine import OrderEngine
    engine = OrderEngine(db_path, account_manager)
    engine.submit_order(...)
    engine.confirm_fill(...)
  所有方法签名和返回值保持不变。

设计依据：
  - PaperTrader 设计方案 Part A2
  - 墨萱评审 2.3: confirm_fill 滑点差额补冻逻辑
  - 玄知条件#1：统一事务管理（接受可选外部 conn）
  - 玄知条件#2：佣金冻结（AccountManager 层处理）
  - 玄知条件#3：卖出净收入 = 一次性 credit
"""

import json
import logging
import os
import sys
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

# ── 从子模块重新导出数据模型 ──
from .order_utils import (
    OrderAction, OrderStatus, OrderInstruction,
    generate_order_id, now_str, now_iso, TZ,
    SIGNALS_BASE, INPROGRESS_DIR, PROCESSED_DIR, FILLS_DIR,
    MOZHENG_SIGNALS_DIR, TASKS_SIGNALS_DIR,
    TRANSACTIONS_DDL, POSITIONS_DDL,
)

# ── 费用计算接口 ──
from .order_fees import (
    calculate_commission, calculate_stamp_tax, calculate_frozen_amount,
    estimate_commission,
)

# ── 价格工具 ──
from utils.price_utils import (
    get_current_price, apply_slippage, apply_slippage_if_needed,
)

# ── 信号→仓位映射 ──
from paper_trade.signal_position_linker import (
    get_positions_by_conn, find_open_position, get_open_position_by_id, get_remaining_qty,
)

# ── 订单生命周期方法（作为实例方法赋值给 OrderEngine） ──
from .order_lifecycle import (
    submit_order, _submit_order_saga, _submit_order_instruction,
    confirm_fill, _saga_confirm_buy, _saga_confirm_sell,
    reject_order, cancel_pending, settle_daily,
    rollback_inprogress, scan_orphan_fills,
    _cleanup_inprogress, get_order_status,
)

# 兼容导入字符串路径
try:
    from .account_manager import AccountManager
except ImportError:
    _PAPER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _PAPER_DIR not in sys.path:
        sys.path.insert(0, _PAPER_DIR)
    from account_manager import AccountManager
    del _PAPER_DIR

from automation_v2.phase1_core.db_utils import retry_on_busy, create_conn

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"


class OrderEngine:
    """
    成交模拟引擎 — 统一入口（v4.0 委托模式）

    核心逻辑已拆分至独立模块，本类仅保留：
      - __init__ / set_connection / _get_conn / _ensure_tables
      - set_slippage
      - 其余 public 方法通过模块级函数委托分发

    方法签名和返回值与 v3.x 完全一致。
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH,
                 account_manager: "AccountManager" = None):
        """
        P0-MH-8: 简化 __init__ 签名，account_manager 为必选参数。

        Args:
            db_path: SQLite 数据库路径
            account_manager: AccountManager 实例
        """
        self.db_path = db_path
        self.am = account_manager or AccountManager(db_path=db_path)
        self.slippage = 0.0  # 保持向后兼容
        self._conn = None

    # ── 连接管理 ──

    def _ensure_tables(self, conn: sqlite3.Connection):
        """确保 transactions 和 positions 表存在（幂等）"""
        conn.execute(TRANSACTIONS_DDL)
        conn.execute(POSITIONS_DDL)

    def set_connection(self, conn: Optional[sqlite3.Connection]):
        """设置外部注入的 SQLite 连接，与 AccountManager 共享"""
        self._conn = conn
        self.am.set_connection(conn)

    def _get_conn(self) -> sqlite3.Connection:
        """获取连接实例（WAL 模式 + 并发重试）"""
        if self._conn is not None:
            return self._conn
        last_error = None
        for attempt in range(3):
            try:
                conn = create_conn(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                return conn
            except sqlite3.OperationalError as e:
                last_error = e
                if attempt < 2:
                    delay = 0.1 * (2 ** attempt)
                    logger.warning(f"[OrderEngine] SQLITE_BUSY (attempt {attempt+1}/3), 等待 {delay:.2f}s: {e}")
                    time.sleep(delay)
                    continue
                raise
        raise sqlite3.OperationalError(f"[OrderEngine] _get_conn 重试3次失败: {last_error}")

    # ── 运行时配置 ──

    def set_slippage(self, slippage: float):
        """运行时调整滑点参数"""
        self.slippage = slippage
        logger.info(f"[OrderEngine] 滑点调整为: {slippage}")

    # ── 订单生命周期（委托至 order_lifecycle） ──

    submit_order = submit_order
    get_order_status = get_order_status
    confirm_fill = confirm_fill
    reject_order = reject_order
    cancel_pending = cancel_pending
    settle_daily = settle_daily
    rollback_inprogress = rollback_inprogress
    scan_orphan_fills = scan_orphan_fills

    # ── 持仓查询（委托至 signal_position_linker） ──

    def get_positions(self) -> List[Dict]:
        """获取当前净多头持仓（基于 FILLED 记录）"""
        try:
            conn = self._get_conn()
            try:
                result = get_positions_by_conn(conn)
            finally:
                if self._conn is None:
                    conn.close()
            return result
        except Exception as e:
            logger.error(f"[OrderEngine] 查询持仓失败: {e}")
            return []


# ============================================================
# __all__ — 确保所有公开符号可导入
# ============================================================

__all__ = [
    "OrderEngine",
    "OrderAction",
    "OrderStatus",
    "OrderInstruction",
    "generate_order_id",
    "now_str",
    "now_iso",
    "TZ",
    "SIGNALS_BASE",
    "INPROGRESS_DIR",
    "PROCESSED_DIR",
    "FILLS_DIR",
    "MOZHENG_SIGNALS_DIR",
    "TASKS_SIGNALS_DIR",
    "TRANSACTIONS_DDL",
    "POSITIONS_DDL",
    "calculate_commission",
    "calculate_stamp_tax",
    "calculate_frozen_amount",
    "estimate_commission",
    "get_current_price",
    "apply_slippage",
    "apply_slippage_if_needed",
    "get_positions_by_conn",
    "find_open_position",
    "get_open_position_by_id",
    "get_remaining_qty",
]
