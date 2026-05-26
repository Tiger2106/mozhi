"""db_repository — 数据库抽象层（BS-2 / SB-4）

Repository 模式接口 + SQLite 实现 + 事务上下文管理器。

设计目标：
  - IRepository 抽象类定义所有 DB 操作接口
  - SQLiteRepository 实现（当前使用），check_same_thread=False + WAL 模式
  - 未来迁移 PG 时新增 PostgresRepository，替换注入即可
  - DDL 使用标准 SQL 子集（INTEGER PRIMARY KEY、TEXT 等）
  - 所有变更操作支持 transaction() 上下文管理器
  - 嵌套事务使用 SAVEPOINT 保护，互不干扰

事务接口（SB-4）：
  - IRepository.transaction() → 返回 AbstractTransaction 上下文
  - SQLiteTransaction：enter→BEGIN，exit→commit on success / rollback on exception
  - 嵌套事务自动检测：外层 BEGIN/COMMIT，内层 SAVEPOINT/RELEASE
  - 事务隔离级别参数预留：transaction(isolation='SERIALIZABLE')

方法命名约定：
  - 主接口使用 snake_case：init_db() / fetch_one() / fetch_all()
  - 向后兼容别名：initialize_schema = init_db, fetchone = fetch_one, fetchall = fetch_all

Author: 墨衡
Created: 2026-05-12
"""

from __future__ import annotations

import sqlite3
import logging
import sys
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import (
    Any,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    Union,
)

from paper_trade import get_wal_connection

logger = logging.getLogger("paper_trade.db_repository")


# ============================================================
# DDL（标准 SQL 子集）
# ============================================================

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS account_balance (
        id              INTEGER PRIMARY KEY,
        total_assets    REAL    NOT NULL DEFAULT 0.0,
        available       REAL    NOT NULL DEFAULT 0.0,
        frozen_balance  REAL    NOT NULL DEFAULT 0.0,
        market_value    REAL    NOT NULL DEFAULT 0.0,
        initial_capital REAL    NOT NULL DEFAULT 200000.0,
        loss_streak     INTEGER NOT NULL DEFAULT 0,
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fund_flow (
        id          INTEGER PRIMARY KEY,
        amount      REAL    NOT NULL,
        flow_type   TEXT    NOT NULL,
        order_id    TEXT,
        description TEXT    DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id                  INTEGER PRIMARY KEY,
        order_id            TEXT    NOT NULL UNIQUE,
        task_id             TEXT    NOT NULL,
        action              TEXT    NOT NULL,
        symbol              TEXT    NOT NULL,
        quantity            INTEGER NOT NULL,
        price               REAL    NOT NULL,
        status              TEXT    NOT NULL DEFAULT 'PENDING',
        frozen_amount       REAL    NOT NULL DEFAULT 0.0,
        estimated_commission REAL   NOT NULL DEFAULT 0.0,
        actual_commission   REAL    DEFAULT NULL,
        stamp_tax           REAL    DEFAULT NULL,
        net_amount          REAL    DEFAULT NULL,
        fill_price          REAL    DEFAULT NULL,
        fill_quantity       INTEGER DEFAULT NULL,
        created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id            INTEGER PRIMARY KEY,
        symbol        TEXT    NOT NULL,
        quantity      INTEGER NOT NULL DEFAULT 0,
        status        TEXT    NOT NULL DEFAULT 'OPEN',
        entry_price   REAL    DEFAULT NULL,
        avg_cost      REAL    DEFAULT NULL,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
    """,
]


# ============================================================
# 事务接口
# ============================================================

class AbstractTransaction:
    """事务上下文管理器抽象。

    使用方式：
        with repo.transaction():
            repo.execute(...)
            repo.execute(...)
        # 正常退出 → commit
        # 异常退出 → rollback

    支持嵌套事务：
        如果在已有事务内部再次进入 transaction() 上下文，
        外层使用 BEGIN/COMMIT，内层使用 SAVEPOINT/RELEASE 保护，
        避免嵌套事务相互干扰。即使内层发生异常回滚，外层事务
        仍然可以正常提交（仅内层变更被回滚）。

    预留：
        transaction(isolation='SERIALIZABLE') 参数用于设置隔离级别。
    """

    def __init__(self, conn: sqlite3.Connection, isolation: Optional[str] = None):
        self._conn = conn
        self._isolation = isolation or "SERIALIZABLE"
        self._savepoint: Optional[str] = None
        self._entered = False

    def __enter__(self) -> AbstractTransaction:
        self._entered = True
        # 检测是否已在事务中：SQLite 中 PRAGMA autocommit=0 表示在事务内
        cursor = self._conn.execute("PRAGMA autocommit")
        in_txn = cursor.fetchone()[0] == 0

        if in_txn:
            # 嵌套事务：使用 SAVEPOINT 保护
            # 使用 id(self) 确保同一对象不同上下文使用不同的 savepoint 名
            # 即使同一对象被多次进入（不推荐），savepoint 名也唯一
            self._savepoint = f"sp_{id(self):x}"
            self._conn.execute(f'SAVEPOINT "{self._savepoint}"')
            logger.debug("Nested transaction: SAVEPOINT %s", self._savepoint)
        else:
            # 外层事务：BEGIN
            self._conn.execute("BEGIN")
            logger.debug("Transaction BEGIN (isolation=%s)", self._isolation)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._savepoint:
            # 嵌套事务退出
            if exc_type is None:
                self._conn.execute(f'RELEASE SAVEPOINT "{self._savepoint}"')
                logger.debug("SAVEPOINT %s RELEASE", self._savepoint)
            else:
                self._conn.execute(f'ROLLBACK TO SAVEPOINT "{self._savepoint}"')
                logger.warning(
                    "SAVEPOINT %s ROLLBACK (%s: %s)",
                    self._savepoint, exc_type.__name__, exc_val,
                )
        else:
            # 外层事务退出
            if exc_type is None:
                self._conn.commit()
                logger.debug("Transaction COMMIT")
            else:
                self._conn.rollback()
                logger.warning(
                    "Transaction ROLLBACK (%s: %s)", exc_type.__name__, exc_val,
                )

    @abstractmethod
    def _marker(self) -> str:
        """实现标记，仅用于抽象类标识。"""
        ...


class SQLiteTransaction(AbstractTransaction):
    """SQLite 事务实现。

    支持嵌套事务保护：
        外层使用 BEGIN/COMMIT/ROLLBACK，
        内层使用 SAVEPOINT/RELEASE/ROLLBACK TO。
    """

    def _marker(self) -> str:
        return "sqlite"


# ============================================================
# Repository 接口
# ============================================================

class IRepository(ABC):
    """数据库抽象接口。

    SQLiteRepository 实现此接口；PostgresRepository 未来按此接口实现。

    方法命名约定（接口层）：
        - 主接口方法使用 snake_case：init_db(), fetch_one(), fetch_all()
        - execute() 和 transaction() 已为 snake_case
        - 具体实现类提供 camelCase 向后兼容别名

    使用方式：
        # 依赖注入
        repo = SQLiteRepository("data/trade.db")
        repo.init_db()

        # 查询
        row = repo.fetch_one("SELECT * FROM account_balance WHERE id=?", (1,))
        rows = repo.fetch_all("SELECT * FROM transactions WHERE status=?", ("PENDING",))

        # 事务
        with repo.transaction():
            repo.execute("UPDATE ...", params)
            repo.execute("INSERT ...", params)

        # 嵌套事务（内层自动使用 SAVEPOINT 保护）
        with repo.transaction():
            with repo.transaction():  # → SAVEPOINT
                ...
    """

    @abstractmethod
    def init_db(self) -> None:
        """创建表结构（DDL），幂等。

        首次初始化时调用，后续调用自动跳过已存在的表。
        """
        ...

    @abstractmethod
    def execute(self, sql: str, params: Union[Tuple, Dict, None] = None) -> int:
        """执行单条 SQL（INSERT/UPDATE/DELETE），返回受影响行数。

        参数：
            sql — 要执行的 SQL 语句
            params — 绑定参数，支持 Tuple（位置绑定）或 Dict（命名绑定）

        返回：
            受影响的行数。对于 INSERT，rowcount 通常为 1。
        """
        ...

    @abstractmethod
    def fetch_one(self, sql: str, params: Union[Tuple, Dict, None] = None) -> Optional[Dict[str, Any]]:
        """查询单行，返回 dict。

        参数：
            sql — SELECT 语句
            params — 绑定参数

        返回：
            找到返回 Dict[str, Any]（列名→值），未找到返回 None。
        """
        ...

    @abstractmethod
    def fetch_all(self, sql: str, params: Union[Tuple, Dict, None] = None) -> List[Dict[str, Any]]:
        """查询多行，返回 dict 列表。

        参数：
            sql — SELECT 语句
            params — 绑定参数

        返回：
            找到返回 List[Dict[str, Any]]，未找到返回空列表。
        """
        ...

    @abstractmethod
    def transaction(self, isolation: Optional[str] = None) -> AbstractTransaction:
        """返回事务上下文管理器。

        使用方式：
            with repo.transaction():
                repo.execute("UPDATE account_balance SET available=? WHERE id=?", ...)
                repo.execute("INSERT INTO fund_flow ...", ...)
            # 正常退出 → COMMIT
            # 异常退出 → ROLLBACK

        嵌套事务保护：
            在已有事务内部再次调用 transaction()，
            内层使用 SAVEPOINT 保护，互不干扰。
            内层出错时会 ROLLBACK TO SAVEPOINT，外层可继续操作。

        参数：
            isolation — 隔离级别（预留），如 'SERIALIZABLE'
                        SQLite 默认使用 SERIALIZABLE。
                        未来迁移 PG 时可能需要指定 READ COMMITTED 等。

        返回：
            AbstractTransaction 上下文管理器。
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """关闭数据库连接。

        使用完毕后调用，释放连接资源。
        关闭后的 Repository 不应再调用 execute/fetch 等方法。
        """
        ...


# ============================================================
# SQLite 实现
# ============================================================

class SQLiteRepository(IRepository):
    """SQLite Repository 实现。

    注入方式：
        repo = SQLiteRepository("mo_zhi_sharereports/trade_engine.db")
        am = AccountManager(repository=repo)

    连接特性：
        - WAL 模式（通过 get_wal_connection）
        - check_same_thread=False（允许跨线程使用连接对象）
        - row_factory = sqlite3.Row（返回行可转换为 dict）

    方法：
        - init_db() — 初始化表结构（幂等）
        - execute(sql, params) — 执行变更语句
        - fetch_one(sql, params) — 查询单行
        - fetch_all(sql, params) — 查询多行
        - transaction(isolation) — 事务上下文管理器（支持嵌套）
        - close() — 关闭连接

    向后兼容别名：
        - initialize_schema ≡ init_db
        - fetchone ≡ fetch_one
        - fetchall ≡ fetch_all

    Author: 墨衡
    Created: 2026-05-12
    """

    def __init__(self, db_path: str):
        # check_same_thread=False + WAL 模式连接（通过 get_wal_connection）
        self._conn = get_wal_connection(db_path, check_same_thread=False)
        self._db_path = db_path
        logger.info("SQLiteRepository initialized: %s (check_same_thread=False)", db_path)

    def execute(self, sql: str, params: Union[Tuple, Dict, None] = None) -> int:
        cursor = self._conn.execute(sql, params or ())
        return cursor.rowcount

    def fetch_one(self, sql: str, params: Union[Tuple, Dict, None] = None) -> Optional[Dict[str, Any]]:
        cursor = self._conn.execute(sql, params or ())
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetch_all(self, sql: str, params: Union[Tuple, Dict, None] = None) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(sql, params or ())
        return [dict(row) for row in cursor.fetchall()]

    def init_db(self) -> None:
        """创建表结构（DDL），幂等。

        使用 executescript 批量执行所有 DDL 语句。
        所有表均使用 CREATE TABLE IF NOT EXISTS，重复调用安全。
        """
        for ddl in DDL_STATEMENTS:
            self._conn.executescript(ddl)
        logger.info("Schema initialized (%d tables)", len(DDL_STATEMENTS))

    @contextmanager
    def transaction(self, isolation: Optional[str] = None) -> Generator[AbstractTransaction, None, None]:
        """事务上下文管理器（支持嵌套）。

        使用 SAVEPOINT 实现嵌套事务保护：
            with repo.transaction():
                repo.execute(...)          # 外层 BEGIN
                with repo.transaction():   # 内层 SAVEPOINT
                    repo.execute(...)
                # 内层 RELEASE → 外层正常继续

        参数：
            isolation — 隔离级别（预留），默认 'SERIALIZABLE'
        """
        tx = SQLiteTransaction(self._conn, isolation=isolation)
        tx.__enter__()
        try:
            yield tx
        except BaseException:
            # 使用 sys.exc_info() 传递真实异常信息给 __exit__
            tx.__exit__(*sys.exc_info())
            raise
        else:
            tx.__exit__(None, None, None)

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()
        logger.info("SQLiteRepository connection closed: %s", self._db_path)

    # ============================================================
    # 向后兼容别名（camelCase → snake_case）
    # ============================================================

    initialize_schema = init_db
    """@deprecated 请使用 init_db() 替代。为保持与现有 coder 的兼容性保留。"""

    fetchone = fetch_one
    """@deprecated 请使用 fetch_one() 替代。为保持与现有 coder 的兼容性保留。"""

    fetchall = fetch_all
    """@deprecated 请使用 fetch_all() 替代。为保持与现有 coder 的兼容性保留。"""
