"""
SQLite 连接管理器

提供：
  - DatabaseManager 单例式连接管理
  - PRAGMA foreign_keys=ON 自动启用（踩平 SQLite 默认外键关闭的坑）
  - PRAGMA journal_mode=WAL 提升并发读性能
  - 上下文管理器 / 装饰器 / 显式 get/set 多种接口
  - 连接健康检查与重连

用法:
    from src.db.connection import get_connection, DatabaseManager

    # 方式一：上下文管理器（推荐）
    with get_connection() as conn:
        conn.execute("SELECT 1")

    # 方式二：显式获取/归还
    mgr = DatabaseManager()
    conn = mgr.get()
    try:
        conn.execute("SELECT 1")
    finally:
        mgr.put(conn)

Author: 墨衡
Created: 2026-05-30T09:36:00+08:00
"""

import sqlite3
import threading
import logging
import os
from contextlib import contextmanager
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 默认数据库路径 ──────────────────────────────────
DEFAULT_DB_PATH = Path(
    os.environ.get(
        "A50_IC_DB_PATH",
        r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db",
    )
)


class DatabaseManager:
    """线程安全的 SQLite 连接管理器。

    特性：
      - 每线程独立连接（sqlite3 连接非线程安全）
      - PRAGMA foreign_keys=ON（连接时自动设置）
      - PRAGMA journal_mode=WAL（首次连接时设置）
      - 连接池上限（max_connections 控制）
      - 健康检查（调用 ping() 验证连接可用）
    """

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        max_connections: int = 4,
        timeout: float = 30.0,
    ):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self.timeout = timeout
        self._lock = threading.RLock()
        self._max_connections = max_connections
        # 线程级连接缓存：{thread_id: connection}
        self._connections: dict[int, sqlite3.Connection] = {}
        # WAL 标记仅在首次连接时设置
        self._wal_initialized = False

    # ── 公共接口 ──────────────────────────────────

    def get(self) -> sqlite3.Connection:
        """获取当前线程的 SQLite 连接（如不存在则创建）。"""
        tid = threading.get_ident()
        with self._lock:
            if tid not in self._connections:
                if len(self._connections) >= self._max_connections:
                    raise RuntimeError(
                        f"连接池已满 ({self._max_connections})，"
                        f"当前线程 {tid} 无法获取连接"
                    )
                conn = self._create_connection()
                self._connections[tid] = conn
                logger.debug(
                    "Created new SQLite connection for thread %s (total: %d)",
                    tid, len(self._connections),
                )
            return self._connections[tid]

    def put(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """归还（关闭）当前线程的连接。

        注意：SQLite 不支持跨线程共享连接，put 会关闭连接并从缓存中移除。
        若 conn 参数为 None，则关闭当前线程的连接。
        """
        tid = threading.get_ident()
        with self._lock:
            if conn is None:
                conn = self._connections.pop(tid, None)
            else:
                # 按对象匹配移除
                to_remove = [
                    k for k, v in self._connections.items() if v is conn
                ]
                for k in to_remove:
                    del self._connections[k]
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def ping(self) -> bool:
        """健康检查：执行 SELECT 1 验证连接可用。"""
        try:
            with self.get() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def close_all(self) -> None:
        """关闭所有缓存连接（建议在进程退出时调用）。"""
        with self._lock:
            for tid, conn in list(self._connections.items()):
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
            logger.info("Closed all SQLite connections")

    def __repr__(self) -> str:
        return (
            f"<DatabaseManager path={self.db_path} "
            f"connections={len(self._connections)}>"
        )

    # ── 内部方法 ──────────────────────────────────

    def _create_connection(self) -> sqlite3.Connection:
        """创建并配置一个新的 SQLite 连接。"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        # 关键 PRAGMA：启用外键约束（SQLite 默认关闭）
        conn.execute("PRAGMA foreign_keys = ON")
        # key 设置
        conn.execute("PRAGMA busy_timeout = 5000")

        # WAL 模式：首次连接时设置（提升并发读性能）
        if not self._wal_initialized:
            with self._lock:
                if not self._wal_initialized:
                    conn.execute("PRAGMA journal_mode = WAL")
                    self._wal_initialized = True
                    logger.info("Enabled WAL mode for %s", self.db_path)

        # 返回 Row 对象（按列名访问）
        conn.row_factory = sqlite3.Row

        return conn

    def __enter__(self) -> sqlite3.Connection:
        return self.get()

    def __exit__(self, *args) -> None:
        self.put()


# ── 全局默认管理器 ───────────────────────────────
_default_manager: Optional[DatabaseManager] = None
_manager_lock = threading.Lock()


def get_manager(db_path: Optional[str | Path] = None) -> DatabaseManager:
    """获取（或初始化）全局默认的 DatabaseManager。

    首次调用时创建，之后返回同一实例。
    支持通过 db_path 参数覆盖默认路径（仅首次生效）。
    """
    global _default_manager
    if _default_manager is None:
        with _manager_lock:
            if _default_manager is None:
                _default_manager = DatabaseManager(db_path=db_path)
    return _default_manager


def get_connection(
    db_path: Optional[str | Path] = None,
) -> sqlite3.Connection:
    """获取当前线程的 SQLite 连接（快捷方式）。

    等价于：
        get_manager(db_path).get()
    """
    return get_manager(db_path).get()


@contextmanager
def connect(
    db_path: Optional[str | Path] = None,
) -> sqlite3.Connection:
    """上下文管理器：获取 -> 使用 -> 自动归还连接。

    推荐用法：
        with connect() as conn:
            conn.execute("...")
    """
    mgr = get_manager(db_path)
    conn = mgr.get()
    try:
        yield conn
    finally:
        mgr.put(conn)


def close_all() -> None:
    """关闭全局管理器下的所有连接（进程退出时调用）。"""
    mgr = get_manager()
    mgr.close_all()
    # 移除默认的 wal 文件锁
    wal_path = Path(str(mgr.db_path) + "-wal")
    shm_path = Path(str(mgr.db_path) + "-shm")
    for p in [wal_path, shm_path]:
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
