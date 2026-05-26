# -*- coding: utf-8 -*-
"""
account_manager.py — 模拟炒股账户资金管理器
作者：墨衡 (moheng)
创建时间：2026-05-04 16:03 GMT+8
版本：v2.0 — P0-MH-6

变更记录：
  v2.0 (2026-05-12):
    - __init__ 新增 repository 参数（IRepository），可选用 Repository 模式管理 DB
    - freeze() 签名改为 freeze(amount, commission_amount, order_id)
    - freeze() 事务内额外更新 transactions 表为 FROZEN 状态
    - get_balance() 返回增加 loss_streak 字段
    - ensure_account() 在 repository 模式下使用 repo.init_db() 初始化
    - 新增 loss_streak 列迁移（直接 SQLite 模式）
    - 冻结金额 = principal + estimated_commission（P0-2 修复）

功能：
1. 账户资金初始化（幂等 ensure_account）
2. 资金冻结/解冻/扣款/入账原子操作
3. 资金流水审计追踪（fund_flow 表）
4. 持仓市值更新与总资产重算
5. 账户重置（清空所有记录）

设计依据：
- PaperTrader 设计方案 Part A1
- IRepository 接口（BS-2 / SB-4）
- 玄知复核条件 #1: 统一事务管理（接受可选外部 conn）
- 玄知复核条件 #2: freeze 金额 = 本金 + 预估佣金（P0-2 修复）
- 玄知复核条件 #3: 卖出时先算净收入再一次性 credit

费率配置（A 股实际费率，可配置）：
    commission_rate: 0.00025 (万2.5)
    min_commission: 5.0 (最低佣金5元)
    stamp_tax_rate: 0.001 (千1, 仅卖出)
    stamp_tax_on_buy: False (买入不收印花税)
"""
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple, Union

from trading.core.db_repository import IRepository
from paper_trade import InsufficientFrozenError

# P0#2#3: 并发重试工具
from automation_v2.phase1_core.db_utils import retry_on_busy, create_conn
from src.config import SHANGHAI_TZ

# 时区
TZ = SHANGHAI_TZ

logger = logging.getLogger(__name__)

# 默认数据库路径
DEFAULT_DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"
DEFAULT_INITIAL_CAPITAL = 200_000.0  # 主人指定

# 费率配置
TRADE_FEE_CONFIG = {
    "commission_rate": 0.00025,       # 佣金 万2.5
    "min_commission": 5.0,            # 最低佣金 5元
    "stamp_tax_rate": 0.001,          # 印花税 千1(仅卖出)
    "stamp_tax_on_buy": False,        # 买入不收印花税
}


# =============================================
# 工具函数
# =============================================

def now_str() -> str:
    """返回当前时间 ISO8601 +08:00"""
    return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def calculate_commission(amount: float, config: Optional[Dict] = None) -> float:
    """
    计算佣金（含最低佣金限制）
    Args:
        amount: 成交金额
        config: 费率配置，默认 TRADE_FEE_CONFIG
    Returns:
        佣金金额
    """
    cfg = config or TRADE_FEE_CONFIG
    commission = amount * cfg["commission_rate"]
    return max(commission, cfg["min_commission"])


def calculate_stamp_tax(amount: float, is_sell: bool = True, config: Optional[Dict] = None) -> float:
    """
    计算印花税（仅卖出时收取）
    Args:
        amount: 成交金额
        is_sell: 是否为卖出
        config: 费率配置
    Returns:
        印花税金额
    """
    cfg = config or TRADE_FEE_CONFIG
    if not is_sell and not cfg.get("stamp_tax_on_buy", False):
        return 0.0
    return amount * cfg["stamp_tax_rate"]


def calculate_frozen_amount(principal: float, is_sell: bool = False, config: Optional[Dict] = None) -> Dict[str, float]:
    """
    计算预计冻结金额（本金 + 佣金 + 印花税）
    Args:
        principal: 交易本金 = quantity * price
        is_sell: 是否为卖出
        config: 费率配置
    Returns:
        {frozen_total, estimated_commission, estimated_tax}
    """
    cfg = config or TRADE_FEE_CONFIG
    est_commission = calculate_commission(principal, cfg)
    est_tax = calculate_stamp_tax(principal, is_sell, cfg)
    return {
        "frozen_total": round(principal + est_commission + est_tax, 2),
        "estimated_commission": round(est_commission, 2),
        "estimated_tax": round(est_tax, 2),
    }


# =============================================
# SQL DDL（直接 SQLite 模式使用）
# =============================================

ACCOUNT_BALANCE_DDL = """
CREATE TABLE IF NOT EXISTS account_balance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_assets REAL NOT NULL DEFAULT 0.0,
    available_balance REAL NOT NULL DEFAULT 0.0,
    frozen_amount REAL NOT NULL DEFAULT 0.0,
    position_market_value REAL NOT NULL DEFAULT 0.0,
    initial_capital REAL NOT NULL DEFAULT 0.0,
    realized_pnl REAL NOT NULL DEFAULT 0.0,
    loss_streak INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

FUND_FLOW_DDL = """
CREATE TABLE IF NOT EXISTS fund_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_before REAL NOT NULL,
    balance_after REAL NOT NULL,
    order_id TEXT,
    position_id INTEGER,
    description TEXT,
    account_id TEXT NOT NULL DEFAULT '1',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""

TRANSACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS transactions (
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
);
"""

POSITIONS_DDL = """
CREATE TABLE IF NOT EXISTS positions (
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
);
"""


# =============================================
# AccountManager
# =============================================

class AccountManager:
    """
    账户资金管理器

    支持 Repository 模式和直接 SQLite 模式两种运行方式：
      - Repository 模式：通过 IRepository 接口管理所有 DB 操作（推荐）
      - 直接 SQLite 模式：通过内部连接管理（向后兼容）

    支持冻结/解冻/扣款/入账原子操作，所有资金操作均在同一个事务中完成。
    接受可选外部 SQLite connection，与 OrderEngine / signal_trade_executor
    复用同一连接，避免事务嵌套问题（直接 SQLite 模式）。
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH,
                 initial_capital: float = DEFAULT_INITIAL_CAPITAL,
                 account_id: str = "1",
                 repository: Optional[IRepository] = None):
        """
        初始化 AccountManager

        Args:
            db_path: 数据库路径（直接 SQLite 模式使用）
            initial_capital: 初始资金
            account_id: 账户标识
            repository: IRepository 实例（可选）。传入后优先使用 Repository 模式管理 DB。
        """
        self.db_path = db_path
        self.initial_capital = initial_capital
        self.account_id = account_id
        self._repository = repository       # IRepository 实例（可选）
        self._conn = None                   # 可选外部注入连接（直接 SQLite 模式）

    # ── 数据库连接管理 ──

    def set_connection(self, conn: Optional[sqlite3.Connection]):
        """
        设置外部注入的 SQLite 连接（直接 SQLite 模式）。
        当传入外部连接时，所有操作复用该连接（不支持自动 commit/rollback）。
        当 conn=None 时，每操作建立独立连接。

        注意：此方法仅在 Repository 模式（self._repository 不为 None）时无效。
        """
        self._conn = conn

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
                    logger.warning(f"[AccountManager] SQLITE_BUSY (attempt {attempt+1}/3), 等待 {delay:.2f}s: {e}")
                    time.sleep(delay)
                    continue
                raise
        raise sqlite3.OperationalError(f"[AccountManager] _get_conn 重试3次失败: {last_error}")

    def _ensure_tables(self, conn: sqlite3.Connection):
        """确保所有表存在（幂等）—— 直接 SQLite 模式"""
        conn.execute(ACCOUNT_BALANCE_DDL)
        conn.execute(FUND_FLOW_DDL)
        conn.execute(TRANSACTIONS_DDL)
        conn.execute(POSITIONS_DDL)
        self._migrate_schema_if_needed(conn)

    def _migrate_schema_if_needed(self, conn: sqlite3.Connection):
        """检查 account_balance 表是否缺少 loss_streak/updated_at，若缺则 ALTER TABLE ADD COLUMN"""
        cursor = conn.execute("PRAGMA table_info(account_balance)")
        columns = {row[1] for row in cursor.fetchall()}
        if "updated_at" not in columns:
            logger.info("[AccountManager] 迁移 schema: 添加 updated_at 列到 account_balance")
            conn.execute("ALTER TABLE account_balance ADD COLUMN updated_at TEXT DEFAULT (datetime('now', 'localtime'))")
        if "loss_streak" not in columns:
            logger.info("[AccountManager] 迁移 schema: 添加 loss_streak 列到 account_balance")
            conn.execute("ALTER TABLE account_balance ADD COLUMN loss_streak INTEGER NOT NULL DEFAULT 0")

    # ── 工具方法 ──

    def _now(self) -> str:
        return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

    def _validate_fund_flow_row_pre_commit(self, flow_type: str, amount: float,
                                               balance_before: float, balance_after: float) -> bool:
        """
        资金流水行级平衡校验（pre-commit）

        在 INSERT 前验证 balance_before/balance_after/amount 三者关系正确。
        根据 flow_type 判断资金流向：
          INFLOW （余额增加）:  CREDIT, UNFREEZE, INITIAL, PRINCIPAL_RETURN, PROFIT_SETTLEMENT
          OUTFLOW（余额减少）:  FREEZE
          NEUTRAL（余额不变）:  DEBIT, COMMISSION, TAX  （仅 frozen 变化，available_balance 不变）

        Raises:
            ValueError: 校验不通过，阻止后续写入/commit

        Returns:
            True: 校验通过
        """
        inflow_types = {"CREDIT", "UNFREEZE", "INITIAL", "PRINCIPAL_RETURN", "PROFIT_SETTLEMENT"}
        outflow_types = {"FREEZE"}
        neutral_types = {"DEBIT", "COMMISSION", "TAX"}

        expected_within = 0.01  # 浮点容差

        if flow_type in inflow_types:
            expected_after = round(balance_before + amount, 2)
            diff = abs(balance_after - expected_after)
            if diff > expected_within:
                msg = (f"资金流水余额校验失败 (INFLOW {flow_type}): "
                       f"expected_after={expected_after:.2f}, actual_after={balance_after:.2f}, "
                       f"balance_before={balance_before:.2f}, amount={amount:.2f}, diff={diff:.4f}")
                logger.error(f"[AccountManager] {msg}")
                raise ValueError(msg)

        elif flow_type in outflow_types:
            expected_after = round(balance_before - amount, 2)
            diff = abs(balance_after - expected_after)
            if diff > expected_within:
                msg = (f"资金流水余额校验失败 (OUTFLOW {flow_type}): "
                       f"expected_after={expected_after:.2f}, actual_after={balance_after:.2f}, "
                       f"balance_before={balance_before:.2f}, amount={amount:.2f}, diff={diff:.4f}")
                logger.error(f"[AccountManager] {msg}")
                raise ValueError(msg)

        elif flow_type in neutral_types:
            diff = abs(balance_after - balance_before)
            if diff > expected_within:
                msg = (f"资金流水余额校验失败 (NEUTRAL {flow_type}): "
                       f"expected_after={balance_before:.2f}, actual_after={balance_after:.2f}, "
                       f"balance_before={balance_before:.2f}, amount={amount:.2f}, diff={diff:.4f}")
                logger.error(f"[AccountManager] {msg}")
                raise ValueError(msg)

        else:
            # 未知 flow_type：记录警告但放行（向后兼容）
            logger.warning(f"[AccountManager] 未知 flow_type={flow_type}，跳过 pre-commit 校验")

        return True

    def _log_fund_flow(self, conn: sqlite3.Connection, flow_type: str, amount: float,
                        balance_before: float, balance_after: float,
                        order_id: Optional[str] = None, position_id: Optional[int] = None,
                        description: Optional[str] = None):
        """写入资金流水记录（带 None 防御性检查 + pre-commit 余额校验）"""
        # W-2: 防御性修复 — 确保关键参数不为 None
        if any(v is None for v in [flow_type, amount, balance_before, balance_after]):
            logger.warning(f"[AccountManager] _log_fund_flow 跳过 None 参数: "
                           f"flow_type={flow_type}, amount={amount}, "
                           f"balance_before={balance_before}, balance_after={balance_after}")
            return

        # P2-i: pre-commit 资金流水平衡校验（在 INSERT 前拦截不平衡数据）
        self._validate_fund_flow_row_pre_commit(flow_type, amount, balance_before, balance_after)

        conn.execute(
            """INSERT INTO fund_flow (flow_type, amount, balance_before, balance_after,
               order_id, position_id, description, account_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (flow_type, amount, balance_before, balance_after,
             order_id, position_id, description, self.account_id, self._now())
        )

        logger.debug(f"[AccountManager] fund_flow 写入: {flow_type} ¥{amount:.2f}, "
                     f"balance {balance_before:.2f}→{balance_after:.2f}, order_id={order_id}")

    def _update_account_ts(self, conn: sqlite3.Connection):
        """更新时间戳"""
        conn.execute(
            "UPDATE account_balance SET updated_at = ? WHERE id = 1",
            (self._now(),)
        )

    def _recalc_total_assets(self, conn: sqlite3.Connection) -> float:
        """重算 total_assets = available_balance + frozen_amount + position_market_value"""
        row = conn.execute(
            "SELECT available_balance, frozen_amount, position_market_value FROM account_balance WHERE id = 1"
        ).fetchone()
        if row is None:
            return 0.0
        total = row[0] + row[1] + row[2]
        conn.execute("UPDATE account_balance SET total_assets = ? WHERE id = 1", (round(total, 2),))
        return round(total, 2)

    # ── 初始化 ──

    @retry_on_busy()
    def ensure_account(self, conn: Optional[sqlite3.Connection] = None) -> bool:
        """
        检查账户是否存在，不存在则创建（幂等）。
        初始化资金 = initial_capital，全部在 available_balance 中。

        支持 Repository 模式和直接 SQLite 模式：
          - Repository 模式：使用 repo.init_db() 创建 DDL + repo.execute() 写入
          - 直接 SQLite 模式：使用内部 _ensure_tables() + 直接 SQL
        """
        if self._repository is not None:
            return self._ensure_account_repo()
        return self._ensure_account_direct(conn)

    def _ensure_account_repo(self) -> bool:
        """Repository 模式：通过 IRepository 接口远程创建账户"""
        try:
            repo = self._repository

            # Repository 模式：repo.init_db() 负责 DDL 创建
            repo.init_db()

            # 幂等检查
            row = repo.fetch_one("SELECT id FROM account_balance WHERE id = ?", (1,))
            if row is None:
                with repo.transaction():
                    repo.execute(
                        """INSERT INTO account_balance
                           (id, total_assets, available_balance, frozen_amount,
                            position_market_value, initial_capital, realized_pnl, loss_streak, updated_at)
                           VALUES (?, ?, ?, 0, 0, ?, 0, 0, ?)""",
                        (1, self.initial_capital, self.initial_capital,
                         self.initial_capital, self._now())
                    )
                    repo.execute(
                        """INSERT INTO fund_flow (flow_type, amount, balance_before, balance_after,
                           order_id, description, account_id, created_at)
                           VALUES ('INITIAL', ?, 0, ?, NULL, ?, ?, ?)""",
                        (self.initial_capital, self.initial_capital,
                         f"账户初始化，初始资金 ¥{self.initial_capital:,.2f}",
                         self.account_id, self._now())
                    )
                logger.info(f"[AccountManager] 账户已创建（Repository模式），初始资金 ¥{self.initial_capital:,.2f}")
            else:
                logger.debug("[AccountManager] 账户已存在（Repository模式），跳过初始化")
            return True
        except Exception as e:
            logger.error(f"[AccountManager] 账户初始化失败（Repository模式）: {e}")
            raise

    def _ensure_account_direct(self, conn: Optional[sqlite3.Connection] = None) -> bool:
        """直接 SQLite 模式：通过内部连接创建账户"""
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)

            # 检查是否已有账户行（按 account_id）
            row = c.execute(
                "SELECT id FROM account_balance WHERE account_id = ? ORDER BY id DESC LIMIT 1",
                (self.account_id,)
            ).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO account_balance
                       (account_id, total_assets, available_balance, frozen_amount,
                        position_market_value, initial_capital, realized_pnl, loss_streak, updated_at)
                       VALUES (?, ?, ?, 0, 0, ?, 0, 0, ?)""",
                    (self.account_id, self.initial_capital, self.initial_capital,
                     self.initial_capital, self._now())
                )
                self._log_fund_flow(c, "INITIAL", self.initial_capital,
                                    0, self.initial_capital,
                                    description=f"账户初始化，初始资金 ¥{self.initial_capital:,.2f}")
                logger.info(f"[AccountManager] 账户已创建，初始资金 ¥{self.initial_capital:,.2f}")
                c.commit()
            else:
                logger.debug("[AccountManager] 账户已存在，跳过初始化")

            if own_conn:
                c.commit()
            return True
        except Exception as e:
            logger.error(f"[AccountManager] 账户初始化失败: {e}")
            if own_conn:
                c.rollback()
            raise
        finally:
            if own_conn:
                c.close()

    # ── 查询 ──

    def get_balance(self, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        """
        获取账户余额全览

        Returns:
            dict with keys:
                total_assets        — 总资产（含持仓市值）
                available_balance   — 可用余额
                frozen_amount       — 冻结金额
                position_market_value — 持仓市值
                initial_capital     — 初始本金
                loss_streak         — 连续亏损次数
                realized_pnl        — 已实现盈亏
        """
        if self._repository is not None:
            return self._get_balance_repo()
        return self._get_balance_direct(conn)

    def _get_balance_repo(self) -> Dict[str, Any]:
        """Repository 模式获取余额（取最新行）"""
        repo = self._repository
        row = repo.fetch_one(
            """SELECT total_assets, available_balance, frozen_amount,
                      position_market_value, realized_pnl, initial_capital, loss_streak
               FROM account_balance ORDER BY id DESC LIMIT 1"""
        )
        if row is None:
            return {
                "total_assets": self.initial_capital,
                "available_balance": self.initial_capital,
                "frozen_amount": 0.0,
                "position_market_value": 0.0,
                "realized_pnl": 0.0,
                "initial_capital": self.initial_capital,
                "loss_streak": 0,
            }
        return {
            "total_assets": row["total_assets"],
            "available_balance": row["available_balance"],
            "frozen_amount": row["frozen_amount"],
            "position_market_value": row["position_market_value"],
            "realized_pnl": row["realized_pnl"],
            "initial_capital": row["initial_capital"],
            "loss_streak": row["loss_streak"],
        }

    def _get_balance_direct(self, conn: Optional[sqlite3.Connection] = None) -> dict:
        """直接 SQLite 模式获取余额（取最新行）"""
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)
            row = c.execute(
                """SELECT total_assets, available_balance, frozen_amount,
                          position_market_value, realized_pnl, initial_capital, loss_streak
                   FROM account_balance WHERE account_id = ? ORDER BY id DESC LIMIT 1""",
                (self.account_id,)
            ).fetchone()
            if row is None:
                return {
                    "total_assets": self.initial_capital,
                    "available_balance": self.initial_capital,
                    "frozen_amount": 0.0,
                    "position_market_value": 0.0,
                    "realized_pnl": 0.0,
                    "initial_capital": self.initial_capital,
                    "loss_streak": 0,
                }
            return {
                "total_assets": row[0],
                "available_balance": row[1],
                "frozen_amount": row[2],
                "position_market_value": row[3],
                "realized_pnl": row[4],
                "initial_capital": row[5],
                "loss_streak": row[6],
            }
        finally:
            if own_conn:
                c.close()

    def can_afford(self, amount: float, conn: Optional[sqlite3.Connection] = None) -> bool:
        """可用余额是否 ≥ amount"""
        balance = self.get_balance(conn)
        return balance["available_balance"] >= amount

    # ── 资金流水校验（P0-1 1a） ──

    def _validate_fund_flow_balance(self, order_id: str,
                                     conn: Optional[sqlite3.Connection] = None) -> dict:
        """
        校验单笔订单的资金流水借贷平衡：
        sum(DEBIT + FREEZE + COMMISSION + TAX) == sum(CREDIT + UNFREEZE + PRINCIPAL_RETURN + PROFIT_SETTLEMENT)

        Returns: {"balanced": bool, "total_out": float, "total_in": float, "flows": list}
        """
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            rows = c.execute(
                "SELECT flow_type, amount, description FROM fund_flow WHERE order_id = ? ORDER BY id",
                (order_id,)
            ).fetchall()

            out_types = {"DEBIT", "FREEZE", "COMMISSION", "TAX"}
            in_types = {"CREDIT", "UNFREEZE", "PRINCIPAL_RETURN", "PROFIT_SETTLEMENT"}

            total_out = 0.0
            total_in = 0.0
            flows = []
            for row in rows:
                ftype, amt, desc = row[0], row[1], row[2]
                flows.append({"flow_type": ftype, "amount": amt, "description": desc})
                if ftype in out_types:
                    total_out += amt
                elif ftype in in_types:
                    total_in += amt
                else:
                    logger.warning(f"[validate] 未知 flow_type={ftype}, amount={amt}, order_id={order_id}")
                    total_out += amt

            balanced = abs(total_in - total_out) < 0.01
            if not balanced:
                logger.warning(
                    f"[validate] fund_flow 不平衡: order_id={order_id}, "
                    f"总流出={total_out:.2f}, 总流入={total_in:.2f}"
                )

            return {
                "balanced": balanced,
                "total_out": round(total_out, 2),
                "total_in": round(total_in, 2),
                "flows": flows,
            }
        finally:
            if own_conn:
                c.close()

    def validate_all_fund_flow_balances(self,
                                         conn: Optional[sqlite3.Connection] = None) -> dict:
        """
        批量校验所有资金流水平衡。

        Returns: {"total_orders": int, "balanced": int, "unbalanced": int, "details": []}
        """
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            order_ids = c.execute(
                "SELECT DISTINCT order_id FROM fund_flow WHERE order_id IS NOT NULL"
            ).fetchall()

            balanced_count = 0
            unbalanced_count = 0
            details = []

            for (oid,) in order_ids:
                result = self._validate_fund_flow_balance(oid, c)
                if result["balanced"]:
                    balanced_count += 1
                else:
                    unbalanced_count += 1
                    details.append({"order_id": oid, **result})

            summary = {
                "total_orders": len(order_ids),
                "balanced": balanced_count,
                "unbalanced": unbalanced_count,
                "details": details,
            }
            logger.info(f"[validate] fund_flow 批量校验: {balanced_count}/{len(order_ids)} 平衡")
            return summary
        finally:
            if own_conn:
                c.close()

    # ── 资金操作（原子事务） ──

    @retry_on_busy()
    def freeze(self, amount: float, commission_amount: float, order_id: str,
               conn: Optional[sqlite3.Connection] = None) -> bool:
        """
        冻结资金（下单前调用）

        P0-2 修复：冻结金额 = 本金 + 预估佣金（commission_amount）
        逻辑:
          1. available_balance -= total_frozen
          2. frozen_amount += total_frozen
          3. 写入 fund_flow 记录（flow_type=FREEZE）
          4. 更新 transactions 表中对应 order_id 的状态为 FROZEN

        Args:
            amount: 本金部分（quantity × price）
            commission_amount: 预估佣金
            order_id: 订单ID
            conn: 外部 SQLite 连接（直接模式使用）

        Returns:
            bool: 冻结成功返回 True，失败（余额不足等）返回 False
        """
        if self._repository is not None:
            return self._freeze_repo(amount, commission_amount, order_id)
        return self._freeze_direct(amount, commission_amount, order_id, conn)

    def _freeze_repo(self, amount: float, commission_amount: float, order_id: str) -> bool:
        """Repository 模式：通过 IRepository 冻结资金"""
        total_frozen = round(amount + commission_amount, 2)
        repo = self._repository
        try:
            with repo.transaction():
                # 1. 检查账户可用余额
                row = repo.fetch_one(
                    "SELECT available_balance, frozen_amount FROM account_balance WHERE id = ?",
                    (1,)
                )
                if row is None:
                    logger.warning(f"[AccountManager] freeze 失败（Repository模式）：账户未初始化, order_id={order_id}")
                    return False

                avail = row["available_balance"]
                frozen = row["frozen_amount"]

                if avail < total_frozen:
                    logger.warning(
                        f"[AccountManager] freeze 失败（Repository模式）：可用余额不足 "
                        f"(需要 {total_frozen:.2f}, 可用 {avail:.2f}), order_id={order_id}"
                    )
                    return False

                # 2. 更新 account_balance
                new_avail = round(avail - total_frozen, 2)
                new_frozen = round(frozen + total_frozen, 2)
                repo.execute(
                    "UPDATE account_balance SET available_balance = ?, frozen_amount = ?, updated_at = ? WHERE id = 1",
                    (new_avail, new_frozen, self._now())
                )

                # 3. 写入资金流水
                repo.execute(
                    """INSERT INTO fund_flow (flow_type, amount, balance_before, balance_after,
                       order_id, description, account_id, created_at)
                       VALUES ('FREEZE', ?, ?, ?, ?, ?, ?, ?)""",
                    (total_frozen, avail, new_avail, order_id,
                     f"冻结 ¥{total_frozen:.2f}（本金 ¥{amount:.2f} + 佣金 ¥{commission_amount:.2f}）",
                     self.account_id, self._now())
                )

                # 4. 更新 transactions 表状态为 FROZEN
                repo.execute(
                    "UPDATE transactions SET status = 'FROZEN', notes = CASE WHEN notes IS NULL THEN ? ELSE notes || '; ' || ? END WHERE order_id = ?",
                    (f"冻结 ¥{total_frozen:.2f}", f"冻结 ¥{total_frozen:.2f}", order_id)
                )

            logger.info(
                f"[AccountManager] freeze OK（Repository模式）: principal={amount:.2f}, "
                f"commission={commission_amount:.2f}, total={total_frozen:.2f}, "
                f"available={avail:.2f}→{new_avail:.2f}, order_id={order_id}"
            )
            return True

        except Exception as e:
            logger.error(f"[AccountManager] freeze 异常（Repository模式）: {e}, order_id={order_id}")
            return False

    def _freeze_direct(self, amount: float, commission_amount: float, order_id: str,
                        conn: Optional[sqlite3.Connection] = None) -> bool:
        """直接 SQLite 模式：通过内部连接冻结资金"""
        total_frozen = round(amount + commission_amount, 2)
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)
            row = c.execute(
                "SELECT available_balance, frozen_amount FROM account_balance WHERE id = 1"
            ).fetchone()
            if row is None:
                logger.warning(f"[AccountManager] freeze 失败：账户未初始化, order_id={order_id}")
                if own_conn:
                    c.rollback()
                return False

            avail, frozen = row[0], row[1]

            if avail < total_frozen:
                logger.warning(
                    f"[AccountManager] freeze 失败：可用余额不足 "
                    f"(需要 {total_frozen:.2f}, 可用 {avail:.2f}), order_id={order_id}"
                )
                if own_conn:
                    c.rollback()
                return False

            new_avail = round(avail - total_frozen, 2)
            new_frozen = round(frozen + total_frozen, 2)

            c.execute(
                "UPDATE account_balance SET available_balance = ?, frozen_amount = ? WHERE id = 1",
                (new_avail, new_frozen)
            )
            self._log_fund_flow(c, "FREEZE", total_frozen, avail, new_avail,
                                order_id=order_id,
                                description=f"冻结 ¥{total_frozen:.2f}（本金 ¥{amount:.2f} + 佣金 ¥{commission_amount:.2f}）")

            # 更新 transactions 表状态为 FROZEN
            c.execute(
                "UPDATE transactions SET status = 'FROZEN', notes = CASE WHEN notes IS NULL THEN ? ELSE notes || '; ' || ? END WHERE order_id = ?",
                (f"冻结 ¥{total_frozen:.2f}", f"冻结 ¥{total_frozen:.2f}", order_id)
            )

            logger.info(
                f"[AccountManager] freeze OK: principal={amount:.2f}, "
                f"commission={commission_amount:.2f}, total={total_frozen:.2f}, "
                f"available={avail:.2f}→{new_avail:.2f}, order_id={order_id}"
            )

            if own_conn:
                c.commit()
            return True
        except Exception as e:
            logger.error(f"[AccountManager] freeze 异常: {e}, order_id={order_id}")
            if own_conn:
                c.rollback()
            return False
        finally:
            if own_conn:
                c.close()

    @retry_on_busy()
    def unfreeze(self, amount: float, order_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
        """
        解冻资金（订单取消/拒绝/多余部分返还时调用）
        逻辑: frozen_amount -= amount, available_balance += amount
        失败条件: frozen_amount < amount → 返回 False
        """
        if self._repository is not None:
            return self._unfreeze_repo(amount, order_id)
        return self._unfreeze_direct(amount, order_id, conn)

    def _unfreeze_repo(self, amount: float, order_id: str) -> bool:
        repo = self._repository
        try:
            with repo.transaction():
                row = repo.fetch_one(
                    "SELECT available_balance, frozen_amount FROM account_balance WHERE id = ?",
                    (1,)
                )
                if row is None:
                    logger.warning(f"[AccountManager] unfreeze 失败（Repository模式）：账户未初始化, order_id={order_id}")
                    return False

                avail, frozen = row["available_balance"], row["frozen_amount"]

                if frozen < amount:
                    logger.warning(
                        f"[AccountManager] unfreeze 失败（Repository模式）：冻结资金不足 "
                        f"(需解冻 {amount:.2f}, 冻结中 {frozen:.2f}), order_id={order_id}"
                    )
                    return False

                new_frozen = round(frozen - amount, 2)
                new_avail = round(avail + amount, 2)

                repo.execute(
                    "UPDATE account_balance SET available_balance = ?, frozen_amount = ?, updated_at = ? WHERE id = 1",
                    (new_avail, new_frozen, self._now())
                )
                repo.execute(
                    """INSERT INTO fund_flow (flow_type, amount, balance_before, balance_after,
                       order_id, description, account_id, created_at)
                       VALUES ('UNFREEZE', ?, ?, ?, ?, ?, ?, ?)""",
                    (amount, avail, new_avail, order_id,
                     f"解冻 ¥{amount:.2f}", self.account_id, self._now())
                )

            logger.info(
                f"[AccountManager] unfreeze OK（Repository模式）: amount={amount:.2f}, "
                f"available={avail:.2f}→{new_avail:.2f}, order_id={order_id}"
            )
            return True
        except Exception as e:
            logger.error(f"[AccountManager] unfreeze 异常（Repository模式）: {e}, order_id={order_id}")
            return False

    def _unfreeze_direct(self, amount: float, order_id: str,
                          conn: Optional[sqlite3.Connection] = None) -> bool:
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)
            row = c.execute(
                "SELECT available_balance, frozen_amount FROM account_balance WHERE id = 1"
            ).fetchone()
            if row is None:
                logger.warning(f"[AccountManager] unfreeze 失败：账户未初始化, order_id={order_id}")
                if own_conn:
                    c.rollback()
                return False

            avail, frozen = row[0], row[1]

            if frozen < amount:
                logger.warning(
                    f"[AccountManager] unfreeze 失败：冻结资金不足 "
                    f"(需解冻 {amount:.2f}, 冻结中 {frozen:.2f}), order_id={order_id}"
                )
                if own_conn:
                    c.rollback()
                return False

            new_frozen = round(frozen - amount, 2)
            new_avail = round(avail + amount, 2)

            c.execute(
                "UPDATE account_balance SET available_balance = ?, frozen_amount = ? WHERE id = 1",
                (new_avail, new_frozen)
            )
            self._log_fund_flow(c, "UNFREEZE", amount, avail, new_avail,
                                order_id=order_id, description=f"解冻 ¥{amount:.2f}")

            logger.info(
                f"[AccountManager] unfreeze OK: amount={amount:.2f}, "
                f"available={avail:.2f}→{new_avail:.2f}, order_id={order_id}"
            )

            if own_conn:
                c.commit()
            return True
        except Exception as e:
            logger.error(f"[AccountManager] unfreeze 异常: {e}, order_id={order_id}")
            if own_conn:
                c.rollback()
            return False
        finally:
            if own_conn:
                c.close()

    @retry_on_busy()
    def debit(self, amount: float, order_id: str, position_id: Optional[int] = None,
              conn: Optional[sqlite3.Connection] = None,
              flow_type: Optional[str] = None) -> bool:
        """
        扣款（成交确认时调用）

        预置条件: 该笔资金已被冻结
        逻辑: frozen_amount -= amount

        核心语义（与 freeze 配合）：
        - freeze 时：available 减少，frozen 增加（资金已从可用余额扣除）
        - debit 时：frozen 减少，available 不变（资金从冻结转入实际消耗）
        - 因此可用余额在 freeze→debit 的整个过程中保持不变

        注意：
        - 不更改 available_balance（freeze 时已扣除）
        - 如需要扣除佣金/印花税（这些费用冻结时已包含在 frozen_amount 中），
          也通过 debit 从 frozen_amount 中移走
        """
        if self._repository is not None:
            return self._debit_repo(amount, order_id, position_id, flow_type)
        return self._debit_direct(amount, order_id, position_id, conn, flow_type)

    def _debit_repo(self, amount: float, order_id: str,
                     position_id: Optional[int] = None,
                     flow_type: Optional[str] = None) -> bool:
        """
        Repository 模式：从冻结资金中扣款

        Raises:
            InsufficientFrozenError: frozen_balance < amount 时抛出（P0-NEW-2）
        """
        repo = self._repository
        try:
            with repo.transaction():
                row = repo.fetch_one(
                    "SELECT frozen_amount FROM account_balance WHERE id = ?",
                    (1,)
                )
                if row is None:
                    logger.warning(f"[AccountManager] debit 失败（Repository模式）：账户未初始化, order_id={order_id}")
                    return False

                frozen = row["frozen_amount"]
                if frozen < amount:
                    logger.warning(
                        f"[AccountManager] debit 失败（Repository模式）：冻结资金不足 "
                        f"(需扣款 {amount:.2f}, 冻结中 {frozen:.2f}), order_id={order_id}"
                    )
                    raise InsufficientFrozenError(frozen, amount, order_id)

                new_frozen = round(frozen - amount, 2)
                repo.execute(
                    "UPDATE account_balance SET frozen_amount = ?, updated_at = ? WHERE id = 1",
                    (new_frozen, self._now())
                )

                # 获取变动前可用余额用于流水记录
                avail_row = repo.fetch_one(
                    "SELECT available_balance FROM account_balance WHERE id = ?",
                    (1,)
                )
                avail_before = avail_row["available_balance"] if avail_row else 0.0

                actual_flow_type = flow_type or "DEBIT"
                suffix = {"COMMISSION": "(佣金)", "TAX": "(印花税)", "DEBIT": "(冻结资金移出)"}.get(actual_flow_type, "")
                repo.execute(
                    """INSERT INTO fund_flow (flow_type, amount, balance_before, balance_after,
                       order_id, position_id, description, account_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (actual_flow_type, amount, avail_before, avail_before,
                     order_id, position_id,
                     f"扣款 ¥{amount:.2f} {suffix}", self.account_id, self._now())
                )

            logger.info(
                f"[AccountManager] debit OK（Repository模式）: amount={amount:.2f}, "
                f"frozen={frozen:.2f}→{new_frozen:.2f}, order_id={order_id}"
            )
            return True
        except InsufficientFrozenError:
            raise  # Let it propagate to caller per docstring
        except Exception as e:
            logger.error(f"[AccountManager] debit 异常（Repository模式）: {e}, order_id={order_id}")
            return False

    def _debit_direct(self, amount: float, order_id: str,
                       position_id: Optional[int] = None,
                       conn: Optional[sqlite3.Connection] = None,
                       flow_type: Optional[str] = None) -> bool:
        """
        直接 SQLite 模式：从冻结资金中扣款

        Raises:
            InsufficientFrozenError: frozen_balance < amount 时抛出（P0-NEW-2）
        """
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)
            row = c.execute(
                "SELECT frozen_amount FROM account_balance WHERE id = 1"
            ).fetchone()
            if row is None:
                logger.warning(f"[AccountManager] debit 失败：账户未初始化, order_id={order_id}")
                if own_conn:
                    c.rollback()
                return False

            frozen = row[0]
            if frozen < amount:
                logger.warning(
                    f"[AccountManager] debit 失败：冻结资金不足 "
                    f"(需扣款 {amount:.2f}, 冻结中 {frozen:.2f}), order_id={order_id}"
                )
                if own_conn:
                    c.rollback()
                raise InsufficientFrozenError(frozen, amount, order_id)

            new_frozen = round(frozen - amount, 2)

            c.execute(
                "UPDATE account_balance SET frozen_amount = ? WHERE id = 1",
                (new_frozen,)
            )

            avail_row = c.execute(
                "SELECT available_balance FROM account_balance WHERE id = 1"
            ).fetchone()
            avail_before = avail_row[0] if avail_row else 0.0

            actual_flow_type = flow_type or "DEBIT"
            suffix = {"COMMISSION": "(佣金)", "TAX": "(印花税)", "DEBIT": "(冻结资金移出)"}.get(actual_flow_type, "")
            self._log_fund_flow(c, actual_flow_type, amount, avail_before, avail_before,
                                order_id=order_id, position_id=position_id,
                                description=f"扣款 ¥{amount:.2f} {suffix}")

            logger.info(
                f"[AccountManager] debit OK: amount={amount:.2f}, "
                f"frozen={frozen:.2f}→{new_frozen:.2f}, order_id={order_id}"
            )

            if own_conn:
                c.commit()
            return True
        except InsufficientFrozenError:
            if own_conn:
                c.rollback()
            raise  # Let it propagate to caller per docstring
        except Exception as e:
            logger.error(f"[AccountManager] debit 异常: {e}, order_id={order_id}")
            if own_conn:
                c.rollback()
            return False
        finally:
            if own_conn:
                c.close()

    @retry_on_busy()
    def credit(self, amount: float, order_id: str, position_id: Optional[int] = None,
               conn: Optional[sqlite3.Connection] = None,
               flow_type: Optional[str] = None) -> bool:
        """
        入账（卖出成交时调用）
        逻辑: available_balance += amount

        注意：
        - 卖出时的佣金和印花税应在 credit 前从 amount 中扣减，
          即 credit 传入的是净收入（收入 - 费用）
        - 玄知条件#3: 卖出净收入 = 一次性 credit
        """
        if self._repository is not None:
            return self._credit_repo(amount, order_id, position_id, flow_type)
        return self._credit_direct(amount, order_id, position_id, conn, flow_type)

    def _credit_repo(self, amount: float, order_id: str,
                      position_id: Optional[int] = None,
                      flow_type: Optional[str] = None) -> bool:
        repo = self._repository
        try:
            with repo.transaction():
                row = repo.fetch_one(
                    "SELECT available_balance FROM account_balance WHERE id = ?",
                    (1,)
                )
                if row is None:
                    logger.warning(f"[AccountManager] credit 失败（Repository模式）：账户未初始化, order_id={order_id}")
                    return False

                avail = row["available_balance"]
                new_avail = round(avail + amount, 2)

                repo.execute(
                    "UPDATE account_balance SET available_balance = ?, updated_at = ? WHERE id = 1",
                    (new_avail, self._now())
                )
                actual_flow_type = flow_type or "CREDIT"
                suffix = {"PRINCIPAL_RETURN": "(本金回笼)", "PROFIT_SETTLEMENT": "(盈亏结算)", "CREDIT": ""}.get(actual_flow_type, "")
                repo.execute(
                    """INSERT INTO fund_flow (flow_type, amount, balance_before, balance_after,
                       order_id, position_id, description, account_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (actual_flow_type, amount, avail, new_avail,
                     order_id, position_id,
                     f"入账 ¥{amount:.2f} {suffix}", self.account_id, self._now())
                )

            logger.info(
                f"[AccountManager] credit OK（Repository模式）: amount={amount:.2f}, "
                f"available={avail:.2f}→{new_avail:.2f}, order_id={order_id}"
            )
            return True
        except Exception as e:
            logger.error(f"[AccountManager] credit 异常（Repository模式）: {e}, order_id={order_id}")
            return False

    def _credit_direct(self, amount: float, order_id: str,
                        position_id: Optional[int] = None,
                        conn: Optional[sqlite3.Connection] = None,
                        flow_type: Optional[str] = None) -> bool:
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)
            row = c.execute(
                "SELECT available_balance FROM account_balance WHERE id = 1"
            ).fetchone()
            if row is None:
                logger.warning(f"[AccountManager] credit 失败：账户未初始化, order_id={order_id}")
                if own_conn:
                    c.rollback()
                return False

            avail = row[0]
            new_avail = round(avail + amount, 2)

            c.execute(
                "UPDATE account_balance SET available_balance = ? WHERE id = 1",
                (new_avail,)
            )
            actual_flow_type = flow_type or "CREDIT"
            suffix = {"PRINCIPAL_RETURN": "(本金回笼)", "PROFIT_SETTLEMENT": "(盈亏结算)", "CREDIT": ""}.get(actual_flow_type, "")
            self._log_fund_flow(c, actual_flow_type, amount, avail, new_avail,
                                order_id=order_id, position_id=position_id,
                                description=f"入账 ¥{amount:.2f} {suffix}")

            logger.info(
                f"[AccountManager] credit OK: amount={amount:.2f}, "
                f"available={avail:.2f}→{new_avail:.2f}, order_id={order_id}"
            )

            if own_conn:
                c.commit()
            return True
        except Exception as e:
            logger.error(f"[AccountManager] credit 异常: {e}, order_id={order_id}")
            if own_conn:
                c.rollback()
            return False
        finally:
            if own_conn:
                c.close()

    # ── 佣金扣除 ──

    @retry_on_busy()
    def debit_commission(self, amount: float, order_id: str,
                          conn: Optional[sqlite3.Connection] = None) -> bool:
        """
        扣除佣金（成交确认时调用）。

        复用 debit 的 frozen_balance 校验逻辑：
          - frozen_balance >= amount → 正常扣除，写 fund_flow(COMMISSION)
          - frozen_balance < amount  → raise InsufficientFrozenError（P0-NEW-2）

        注意：佣金冻结时已计入 frozen_amount（P0-2），debit_commission 仅做
        frozen_amount 移出操作，不涉及 available_balance。
        """
        logger.info(f"[AccountManager] debit_commission: amount={amount:.2f}, order_id={order_id}")
        return self.debit(amount, order_id, conn=conn, flow_type="COMMISSION")

    # ── 已实现盈亏更新 ──

    @retry_on_busy()
    def update_realized_pnl(self, pnl: float, order_id: str,
                             conn: Optional[sqlite3.Connection] = None) -> bool:
        """
        更新已实现盈亏（平仓时调用）。

        逻辑：
          UPDATE account_balance SET realized_pnl = realized_pnl + pnl
          写入 fund_flow(PNL_SETTLEMENT) 记录

        Args:
            pnl: 本次交易的盈亏金额（正=盈利，负=亏损）
            order_id: 订单ID
            conn: 外部 SQLite 连接

        Returns:
            bool: 更新成功返回 True
        """
        if self._repository is not None:
            return self._update_pnl_repo(pnl, order_id)
        return self._update_pnl_direct(pnl, order_id, conn)

    def _update_pnl_repo(self, pnl: float, order_id: str) -> bool:
        repo = self._repository
        try:
            with repo.transaction():
                row = repo.fetch_one("SELECT realized_pnl FROM account_balance WHERE id = ?", (1,))
                if row is None:
                    logger.warning(f"[AccountManager] update_realized_pnl 失败（Repository模式）：账户未初始化")
                    return False
                current_pnl = row["realized_pnl"]
                new_pnl = round(current_pnl + pnl, 2)
                repo.execute("UPDATE account_balance SET realized_pnl = ?, updated_at = ? WHERE id = 1",
                             (new_pnl, self._now()))
                repo.execute(
                    """INSERT INTO fund_flow (flow_type, amount, balance_before, balance_after,
                       order_id, description, account_id, created_at)
                       VALUES ('PNL_SETTLEMENT', ?, ?, ?, ?, ?, ?, ?)""",
                    (pnl, current_pnl, new_pnl, order_id,
                     f"已实现盈亏更新: {pnl:+.2f}", self.account_id, self._now())
                )
            logger.info(f"[AccountManager] update_realized_pnl OK（Repository模式）: {pnl:+.2f}, order_id={order_id}")
            return True
        except Exception as e:
            logger.error(f"[AccountManager] update_realized_pnl 异常（Repository模式）: {e}")
            return False

    def _update_pnl_direct(self, pnl: float, order_id: str,
                            conn: Optional[sqlite3.Connection] = None) -> bool:
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)
            row = c.execute("SELECT realized_pnl FROM account_balance WHERE id = 1").fetchone()
            if row is None:
                logger.warning(f"[AccountManager] update_realized_pnl 失败：账户未初始化")
                if own_conn:
                    c.rollback()
                return False
            current_pnl = row[0]
            new_pnl = round(current_pnl + pnl, 2)
            c.execute("UPDATE account_balance SET realized_pnl = ? WHERE id = 1", (new_pnl,))
            self._log_fund_flow(c, "PNL_SETTLEMENT", pnl, current_pnl, new_pnl,
                                order_id=order_id,
                                description=f"已实现盈亏更新: {pnl:+.2f}")
            logger.info(f"[AccountManager] update_realized_pnl OK: {pnl:+.2f}, order_id={order_id}")
            if own_conn:
                c.commit()
            return True
        except Exception as e:
            logger.error(f"[AccountManager] update_realized_pnl 异常: {e}")
            if own_conn:
                c.rollback()
            return False
        finally:
            if own_conn:
                c.close()

    # ── 持仓市值更新 ──

    def update_position_market_value(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """
        更新持仓市值 = sum(open_positions quantity × entry_price)。
        然后更新 total_assets = available_balance + frozen_amount + position_market_value。

        注意：当前使用 entry_price 作为近似，实际应为当前市价。
        未来改进：传入实时市价字典。
        """
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        try:
            self._ensure_tables(c)

            # 计算持仓市值（OPEN 状态仓位）
            row = c.execute(
                "SELECT COALESCE(SUM(quantity * entry_price), 0) FROM positions WHERE status = 'OPEN'"
            ).fetchone()
            market_value = round(row[0], 2) if row else 0.0

            c.execute(
                "UPDATE account_balance SET position_market_value = ? WHERE id = 1",
                (market_value,)
            )

            # 重算总资产
            self._recalc_total_assets(c)

            logger.info(f"[AccountManager] 持仓市值更新: ¥{market_value:.2f}")

            if own_conn:
                c.commit()
        except Exception as e:
            logger.error(f"[AccountManager] update_position_market_value 异常: {e}")
            if own_conn:
                c.rollback()
        finally:
            if own_conn:
                c.close()

    # ── 账户重置 ──

    def reset_account(self, conn: Optional[sqlite3.Connection] = None) -> bool:
        """
        重置账户到初始状态（清空所有数据，重新初始化）

        用于：
        - 测试环境重置
        - 新策略上线时资金重算
        """
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        reset_pending = False
        try:
            self._ensure_tables(c)

            # 清空数据
            for tbl in ["fund_flow", "positions", "transactions"]:
                c.execute(f"DELETE FROM {tbl}")
                logger.debug(f"[AccountManager] 重置: {tbl} 已清空")

            # 重置 account_balance
            c.execute("DELETE FROM account_balance")
            self._now()  # 确保时间戳一致性
            c.execute(
                """INSERT INTO account_balance
                   (id, total_assets, available_balance, frozen_amount,
                    position_market_value, initial_capital, realized_pnl, loss_streak, updated_at)
                   VALUES (1, ?, ?, 0, 0, ?, 0, 0, ?)""",
                (self.initial_capital, self.initial_capital,
                 self.initial_capital, self._now())
            )

            # 记录重置流水
            self._log_fund_flow(c, "INITIAL", self.initial_capital,
                                0, self.initial_capital,
                                description=f"账户重置，初始资金 ¥{self.initial_capital:,.2f}")

            if own_conn:
                c.commit()
            logger.info(f"[AccountManager] 账户已重置，初始资金 ¥{self.initial_capital:,.2f}")
            return True
        except Exception as e:
            logger.error(f"[AccountManager] reset_account 异常: {e}")
            if own_conn:
                c.rollback()
            return False
        finally:
            if own_conn:
                c.close()

    # ── 审计校验 ──

    def audit_fund_flow(self, conn: Optional[sqlite3.Connection] = None) -> dict:
        """
        fund_flow 审计：校验所有记录的 balance_before/balance_after/amount 关系正确性。
        并行校验 fund_flow 记录顺序正确性。

        Returns:
            {"total": int, "errors": int, "error_details": list}
        """
        own_conn = conn is None
        c = conn if conn else self._get_conn()
        errors = []
        try:
            self._ensure_tables(c)
            rows = c.execute(
                "SELECT flow_type, amount, balance_before, balance_after, order_id, created_at FROM fund_flow ORDER BY id"
            ).fetchall()

            # 校验顺序正确性：每行的 balance_before 应与上一行的 balance_after 一致
            last_balance = None
            for i, row in enumerate(rows):
                flow_type, amount, bal_before, bal_after, oid, created_at = row
                try:
                    self._validate_fund_flow_row_pre_commit(
                        flow_type, amount, bal_before, bal_after
                    )
                except ValueError as e:
                    errors.append({
                        "row": i + 1,
                        "order_id": oid,
                        "error": str(e),
                        "created_at": created_at,
                    })

                if last_balance is not None and abs(bal_before - last_balance) > 0.01:
                    errors.append({
                        "row": i + 1,
                        "order_id": oid,
                        "error": f"余额不连续: 上一行末尾={last_balance:.2f}, 本行开始={bal_before:.2f}",
                        "created_at": created_at,
                    })

                last_balance = bal_after

            summary = {
                "total": len(rows),
                "errors": len(errors),
                "error_details": errors,
            }
            logger.info(f"[AccountManager] fund_flow 审计: {len(rows)} 条记录, {len(errors)} 个错误")
            return summary
        finally:
            if own_conn:
                c.close()
