"""
墨枢 - ArchiveManager
历史回测归档管理器（方案B：异步后置同步）。

建立只追加不覆盖的历史回测归档库（backtest_back_YYYYMM.db），
每次回测运行结果自动写入该库，与 backtest.db 当前回测工作区解耦。

设计要求：
  1. 只同步 version_status='final' 的记录
  2. 归档库 schema 镜像主库 analysis_* 系列表（不含 archive_files 和 analysis_ingested_run_ids）
  3. 按月分区滚动，文件名格式 backtest_back_YYYYMM.db
  4. 建立 sync_checkpoint 同步检查点日志表
  5. 幂等保护：同一 run_id 不会重复同步
  6. 异常处理：归档失败不影响主库

author: 墨衡 (DeepSeek R1)
created_time: 2026-05-23T18:59:00+08:00
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import PROJECT_ROOT, SHANGHAI_TZ


# ── 可归档的表清单 ──────────────────────────────────────
# 不含 archive_files 和 analysis_ingested_run_ids
TABLES_TO_ARCHIVE = [
    "analysis_meta",
    "analysis_metrics_core",
    "analysis_metrics_ext",
    "analysis_docs",
    "schema_version",
    "trade_log",
    "daily_snapshot",
    "performance_summary",
    "factor_result",
    "validation_check",
    "strategy_config",
    "backtest_run",
]

# 同步顺序（考虑外键依赖：先写父表再写子表）
SYNC_ORDER = [
    "backtest_run",
    "strategy_config",
    "analysis_meta",
    "schema_version",
    "analysis_metrics_core",
    "analysis_metrics_ext",
    "analysis_docs",
    "trade_log",
    "daily_snapshot",
    "performance_summary",
    "factor_result",
    "validation_check",
]


class ArchiveError(Exception):
    """归档阶段异常"""


class SchemaVersionMismatch(Exception):
    """schema 版本不匹配，拒绝同步"""


class ArchiveManager:
    """
    历史回测归档管理器。

    用法::

        mgr = ArchiveManager(source_db="data/backtest.db", archive_dir="data/")
        result = mgr.sync()
        # result.synced_run_ids → 本次同步的 run_id 列表
        # result.row_counts → 各表同步行数
    """

    def __init__(
        self,
        source_db: str | Path,
        archive_dir: str | Path | None = None,
        logger: logging.Logger | None = None,
        verbose: bool = False,
    ):
        self.source_path = Path(source_db)
        self.archive_dir = Path(archive_dir) if archive_dir else PROJECT_ROOT / "data"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logger or logging.getLogger("archive_manager")
        self._verbose = verbose

    # ── 公开 API ─────────────────────────────────────────

    def sync(self) -> SyncResult:
        """
        执行归档同步：将 source_db 中 version_status='final' 且
        尚未归档的 analysis_meta 记录及其关联数据同步到归档库。

        幂等保护：通过 sync_checkpoint 表避免重复同步同一 run_id。

        Returns:
            SyncResult: 同步结果
        """
        source_conn = self._connect_source()
        archive_conn = None
        result = None
        try:
            # 1. 确定目标归档库路径（按月分区）
            archive_path = self._resolve_archive_path()
            self._log("INFO", f"目标归档库: {archive_path}")

            # 2. 确保归档库 schema 就绪
            archive_conn = self._connect_archive(str(archive_path))
            self._ensure_archive_schema(archive_conn)

            # 3. 获取当前同步检查点
            checkpoint = self._get_checkpoint(archive_conn)

            # 4. 从 source_db 查询待归档的 analysis_meta 记录
            pending = self._find_pending_analyses(source_conn, checkpoint)
            if not pending:
                self._log("INFO", "没有待归档的分析记录")
                result = SyncResult(
                    status="NOOP",
                    synced_run_ids=[],
                    row_counts={},
                    archive_path=str(archive_path),
                )
                archive_conn.close()
                return result

            self._log("INFO", f"待归档分析记录数: {len(pending)}")

            # 5. 逐条事务同步
            synced_run_ids = []
            total_row_counts: Dict[str, int] = {}

            for row in pending:
                run_id = row["run_id"]
                analysis_id = row["id"]
                self._log("INFO", f"正在归档: run_id={run_id} analysis_id={analysis_id}")

                try:
                    row_counts = self._sync_one_analysis(
                        source_conn, archive_conn, run_id, analysis_id
                    )
                    synced_run_ids.append(run_id)
                    for table, count in row_counts.items():
                        total_row_counts[table] = total_row_counts.get(table, 0) + count

                    # 写检查点
                    self._write_checkpoint(archive_conn, run_id, analysis_id)
                    archive_conn.commit()

                except Exception as e:
                    archive_conn.rollback()
                    self._log("ERROR", f"归档失败: run_id={run_id}: {e}")
                    # 继续同步下一条（不影响主库）

            self._log(
                "INFO",
                f"归档完成: {len(synced_run_ids)} 条记录, "
                f"写入行数: {total_row_counts}",
            )

            archive_conn.commit()
            result = SyncResult(
                status="SUCCESS",
                synced_run_ids=synced_run_ids,
                row_counts=total_row_counts,
                archive_path=str(archive_path),
            )
            archive_conn.close()
            return result

        except SchemaVersionMismatch:
            self._close_archive_conn(archive_conn)
            raise
        except Exception as e:
            self._close_archive_conn(archive_conn)
            self._log("ERROR", f"归档同步失败: {e}")
            raise ArchiveError(f"归档同步失败: {e}") from e
        finally:
            source_conn.close()

    def sync_run_id(self, run_id: str) -> SyncResult:
        """
        归档指定 run_id 的记录。

        用于首次部署时单次归档或手动触发特定 run_id 的归档。
        """
        source_conn = self._connect_source()
        archive_conn = None
        try:
            archive_path = self._resolve_archive_path()
            archive_conn = self._connect_archive(str(archive_path))
            self._ensure_archive_schema(archive_conn)

            # 检查是否已归档
            checkpoint = self._get_checkpoint(archive_conn)
            if checkpoint and checkpoint.get("last_run_id") == run_id:
                self._log("INFO", f"run_id={run_id} 已归档，跳过")
                archive_conn.close()
                return SyncResult(
                    status="SKIP_ALREADY_SYNCED",
                    synced_run_ids=[run_id],
                    row_counts={},
                    archive_path=str(archive_path),
                )

            # 查询 source_db 中该 run_id 的记录
            row = source_conn.execute(
                """SELECT id, run_id, version_status FROM analysis_meta
                   WHERE run_id = ? AND version_status = 'final'
                   ORDER BY id DESC LIMIT 1""",
                (run_id,),
            ).fetchone()

            if not row:
                self._log("WARNING", f"未找到 run_id={run_id} 的 final 分析记录")
                archive_conn.close()
                return SyncResult(
                    status="NOT_FOUND",
                    synced_run_ids=[],
                    row_counts={},
                    archive_path=str(archive_path),
                )

            analysis_id = row["id"]
            row_counts = self._sync_one_analysis(
                source_conn, archive_conn, run_id, analysis_id
            )
            self._write_checkpoint(archive_conn, run_id, analysis_id)
            archive_conn.commit()
            archive_conn.close()

            self._log(
                "INFO",
                f"归档完成: run_id={run_id}, 写入行数: {row_counts}",
            )

            return SyncResult(
                status="SUCCESS",
                synced_run_ids=[run_id],
                row_counts=row_counts,
                archive_path=str(archive_path),
            )

        except Exception as e:
            if archive_conn:
                try:
                    archive_conn.close()
                except Exception:
                    pass
            self._log("ERROR", f"归档 run_id={run_id} 失败: {e}")
            raise ArchiveError(f"归档 run_id={run_id} 失败: {e}") from e
        finally:
            source_conn.close()

    def sync_latest(self) -> SyncResult:
        """
        便捷方法：归档所有未归档的 final 分析记录。
        等同于无参数的 sync()，适合在回测流程末尾调用。
        """
        return self.sync()

    # ── 内部连接管理 ──────────────────────────────────────

    def _connect_source(self) -> sqlite3.Connection:
        """连接源数据库（backtest.db）。"""
        if not self.source_path.exists():
            raise ArchiveError(f"源数据库不存在: {self.source_path}")
        conn = sqlite3.connect(str(self.source_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_archive(self, archive_path: str) -> sqlite3.Connection:
        """连接归档数据库，使用 WAL 模式减少锁竞争。"""
        conn = sqlite3.connect(archive_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _close_archive_conn(self, archive_conn) -> None:
        """安全关闭归档连接（可能未定义）。"""
        try:
            if archive_conn is not None:
                archive_conn.close()
        except (sqlite3.Error, AttributeError):
            pass

    def _now_iso(self) -> str:
        return datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%dT%H:%M:%S")

    def _log(self, level: str, message: str) -> None:
        if self._verbose:
            print(f"[ArchiveManager] {level}: {message}")
        log_fn = getattr(self._logger, level.lower(), self._logger.info)
        log_fn(message)

    # ── 按月分区 ────────────────────────────────────────

    def _resolve_archive_path(self) -> Path:
        """
        按月分区：根据当前时间确定归档库路径。

        文件名格式：backtest_back_YYYYMM.db
        跨月时自动创建新文件，存在则复用。
        """
        now = datetime.now(SHANGHAI_TZ)
        month_key = now.strftime("%Y%m")
        archive_path = self.archive_dir / f"backtest_back_{month_key}.db"
        return archive_path

    # ── Schema 管理 ──────────────────────────────────────

    ARCHIVE_TABLE_DEFINITIONS = {
        "backtest_run": """
            CREATE TABLE IF NOT EXISTS backtest_run (
                id TEXT PRIMARY KEY,
                run_name TEXT,
                version_tag TEXT,
                created_at TEXT,
                status TEXT DEFAULT 'pending',
                triggered_by TEXT,
                periods TEXT,
                notes TEXT
            )
        """,
        "strategy_config": """
            CREATE TABLE IF NOT EXISTS strategy_config (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                strategy_type TEXT,
                signal_defined_path TEXT,
                entry_rules TEXT,
                exit_rules TEXT,
                initial_capital REAL DEFAULT 1000000.0,
                commission_rate REAL DEFAULT 0.0003,
                min_fee REAL DEFAULT 5.0,
                slippage_rate REAL DEFAULT 0.001,
                position_sizing TEXT DEFAULT 'equal',
                max_positions INTEGER DEFAULT 5
            )
        """,
        "analysis_meta": """
            CREATE TABLE IF NOT EXISTS analysis_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                parent_session_id INTEGER,
                tags TEXT,
                version_schema TEXT,
                version_content INTEGER,
                version_status TEXT DEFAULT 'draft',
                author TEXT,
                analysis_type TEXT,
                created_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S', 'now')),
                updated_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S', 'now'))
            )
        """,
        "analysis_metrics_core": """
            CREATE TABLE IF NOT EXISTS analysis_metrics_core (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER,
                run_id TEXT,
                metric_group TEXT,
                total_return_pct REAL,
                annual_return_pct REAL,
                final_equity REAL,
                total_pnl REAL,
                benchmark_return_pct REAL,
                excess_return_pct REAL,
                max_drawdown_pct REAL,
                annual_volatility_pct REAL,
                sharpe_ratio REAL,
                calmar_ratio REAL,
                sortino_ratio REAL,
                var_95_pct REAL,
                total_trades INTEGER,
                winning_trades INTEGER,
                losing_trades INTEGER,
                win_rate_pct REAL,
                total_profit REAL,
                total_loss REAL,
                profit_loss_ratio REAL,
                max_consecutive_wins INTEGER,
                max_consecutive_losses INTEGER,
                max_single_win REAL,
                max_single_loss REAL,
                verdict TEXT,
                risk_level TEXT DEFAULT 'mid',
                core_issue TEXT,
                improvement_potential TEXT,
                created_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S','now')),
                updated_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S','now'))
            )
        """,
        "analysis_metrics_ext": """
            CREATE TABLE IF NOT EXISTS analysis_metrics_ext (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER,
                run_id TEXT,
                metric_group TEXT,
                metric_name TEXT,
                metric_value REAL,
                metric_label TEXT,
                created_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S', 'now'))
            )
        """,
        "analysis_docs": """
            CREATE TABLE IF NOT EXISTS analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER,
                run_id TEXT,
                doc_type TEXT,
                file_path TEXT,
                content_hash TEXT,
                file_size_bytes INTEGER,
                word_count INTEGER,
                is_deleted INTEGER DEFAULT 0,
                deleted_at TEXT,
                created_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S', 'now')),
                updated_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S', 'now'))
            )
        """,
        "schema_version": """
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                applied_at TEXT,
                description TEXT,
                checksum TEXT
            )
        """,
        "trade_log": """
            CREATE TABLE IF NOT EXISTS trade_log (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                ts_code TEXT,
                signal_date TEXT,
                entry_date TEXT,
                exit_date TEXT,
                entry_price REAL,
                exit_price REAL,
                avg_trade_price REAL,
                volume REAL,
                amount REAL,
                direction TEXT DEFAULT 'buy',
                order_type TEXT DEFAULT 'market',
                pnl REAL,
                pnl_pct REAL,
                commission REAL,
                slippage REAL,
                exit_reason TEXT
            )
        """,
        "daily_snapshot": """
            CREATE TABLE IF NOT EXISTS daily_snapshot (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                ts_code TEXT,
                trade_date TEXT,
                holding_shares REAL DEFAULT 0,
                avg_cost REAL,
                market_value REAL DEFAULT 0,
                daily_pnl REAL,
                cumulative_pnl REAL,
                weight_pct REAL
            )
        """,
        "performance_summary": """
            CREATE TABLE IF NOT EXISTS performance_summary (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                ts_code TEXT,
                total_return REAL,
                annualized_return REAL,
                benchmark_return REAL,
                excess_return REAL,
                max_drawdown REAL,
                max_drawdown_start TEXT,
                max_drawdown_end TEXT,
                sharpe_ratio REAL,
                calmar_ratio REAL,
                sortino_ratio REAL,
                win_rate REAL,
                profit_factor REAL,
                total_trades INTEGER,
                avg_holding_days REAL,
                turnover_rate REAL,
                volatility REAL,
                downside_volatility REAL,
                var_95_pct REAL,
                max_consecutive_wins INTEGER DEFAULT 0,
                max_consecutive_losses INTEGER DEFAULT 0,
                final_equity REAL,
                equity_curve TEXT,
                daily_returns TEXT
            )
        """,
        "factor_result": """
            CREATE TABLE IF NOT EXISTS factor_result (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                factor_id TEXT,
                ts_code TEXT,
                mean_ic REAL,
                std_ic REAL,
                ir REAL,
                ic_positive_ratio REAL,
                test_days INTEGER,
                ic_ts TEXT,
                ic_cumulative TEXT
            )
        """,
        "validation_check": """
            CREATE TABLE IF NOT EXISTS validation_check (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                check_name TEXT,
                check_type TEXT,
                result TEXT,
                actual_value REAL,
                threshold_value REAL,
                detail TEXT,
                checked_at TEXT DEFAULT (strftime('%%Y-%%m-%%dT%%H:%%M:%%S', 'now'))
            )
        """,
        "sync_checkpoint": """
            CREATE TABLE IF NOT EXISTS sync_checkpoint (
                checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                last_run_id TEXT,
                last_analysis_id INTEGER,
                synced_at TEXT
            )
        """,
    }

    # 同步检查点表 DDL（单独列出便于管理）
    SYNC_CHECKPOINT_DDL = """
        CREATE TABLE IF NOT EXISTS sync_checkpoint (
            checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            last_run_id TEXT,
            last_analysis_id INTEGER,
            synced_at TEXT NOT NULL
        )
    """

    # 归档库索引定义
    ARCHIVE_INDEX_DEFINITIONS = [
        "CREATE INDEX IF NOT EXISTS idx_a_run ON analysis_meta(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_a_status ON analysis_meta(version_status)",
        "CREATE INDEX IF NOT EXISTS idx_amc_run ON analysis_metrics_core(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_ame_run ON analysis_metrics_ext(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_ad_run ON analysis_docs(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_tl_run ON trade_log(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_ds_run ON daily_snapshot(run_id, trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_ps_run ON performance_summary(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_fr_run ON factor_result(run_id, factor_id)",
        "CREATE INDEX IF NOT EXISTS idx_vc_run ON validation_check(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_sc_run ON strategy_config(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_br_run ON backtest_run(id)",
    ]

    def _ensure_archive_schema(self, conn: sqlite3.Connection) -> None:
        """
        确保归档库 schema 就绪。

        1. 检查 schema_version 表是否存在，若存在则验证版本兼容性
        2. 创建缺失的表
        3. 创建缺失的索引
        """
        # 检查 schema_version 表
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]

        if "schema_version" in tables:
            # 验证 schema 版本兼容性
            sv_row = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if sv_row:
                existing_version = sv_row["version"]
                # 要求 4.0+（analysis 层 schema）
                try:
                    if float(existing_version) < 4.0:
                        raise SchemaVersionMismatch(
                            f"归档库 schema_version={existing_version} < 4.0，拒绝同步。"
                            f"请先升级归档库 schema。"
                        )
                except ValueError:
                    raise SchemaVersionMismatch(
                        f"无法解析归档库 schema_version: {existing_version}"
                    )

        # 创建所有表（IF NOT EXISTS）
        for table_name, ddl in self.ARCHIVE_TABLE_DEFINITIONS.items():
            try:
                conn.execute(ddl)
            except sqlite3.Error as e:
                self._log("ERROR", f"创建表 {table_name} 失败: {e}")
                raise

        # 创建索引
        for idx_ddl in self.ARCHIVE_INDEX_DEFINITIONS:
            try:
                conn.execute(idx_ddl)
            except sqlite3.Error as e:
                self._log("WARNING", f"创建索引失败: {e}")

        conn.commit()

    # ── 同步检查点 ──────────────────────────────────────

    def _get_checkpoint(self, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """读取最新同步检查点。"""
        try:
            row = conn.execute(
                "SELECT * FROM sync_checkpoint ORDER BY checkpoint_id DESC LIMIT 1"
            ).fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.OperationalError:
            # sync_checkpoint 表可能还不存在
            return None

    def _write_checkpoint(
        self, conn: sqlite3.Connection, run_id: str, analysis_id: int
    ) -> int:
        """写入同步检查点记录。"""
        now = self._now_iso()
        conn.execute(
            "INSERT INTO sync_checkpoint (last_run_id, last_analysis_id, synced_at) "
            "VALUES (?, ?, ?)",
            (run_id, analysis_id, now),
        )
        cp_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return cp_id

    # ── 核心同步逻辑 ──────────────────────────────────────

    def _find_pending_analyses(
        self, source_conn: sqlite3.Connection, checkpoint: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        从 source_db 查找待归档的 analysis_meta 记录。

        筛选条件：
          1. version_status = 'final'
          2. 未出现在 sync_checkpoint 中

        如果 checkpoint 为 None（首次归档），则返回所有 final 记录。
        """
        if checkpoint and checkpoint.get("last_analysis_id"):
            # 增量同步：只同步比检查点更新的记录
            rows = source_conn.execute(
                """SELECT am.id, am.run_id, am.analysis_type, am.version_status,
                           am.created_at, am.updated_at
                   FROM analysis_meta am
                   WHERE am.version_status = 'final'
                     AND am.id > ?
                   ORDER BY am.id ASC""",
                (checkpoint["last_analysis_id"],),
            ).fetchall()
        else:
            # 全量同步：所有 final 记录
            rows = source_conn.execute(
                """SELECT am.id, am.run_id, am.analysis_type, am.version_status,
                           am.created_at, am.updated_at
                   FROM analysis_meta am
                   WHERE am.version_status = 'final'
                   ORDER BY am.id ASC"""
            ).fetchall()

        # 二次过滤：检查 sync_checkpoint 中是否已有该 run_id
        # （用于断电恢复场景，补录已写入部分数据但检查点未提交的记录）
        try:
            archive_path = self._resolve_archive_path()
            archive_conn = self._connect_archive(str(archive_path))
            try:
                already_synced = set()
                for r in archive_conn.execute(
                    "SELECT DISTINCT last_run_id FROM sync_checkpoint"
                ).fetchall():
                    already_synced.add(r["last_run_id"])
            finally:
                archive_conn.close()
        except Exception:
            already_synced = set()

        result = [dict(r) for r in rows if r["run_id"] not in already_synced]
        return result

    def _find_backtest_run_id(
        self,
        source_conn: sqlite3.Connection,
        analysis_run_id: str,
    ) -> Optional[str]:
        """
        从分析 run_id 找到对应的回测 run_id。

        查找策略：
        1. 直接匹配：backtest_run.id == analysis_run_id
        2. 通过 analysis_ingested_run_ids 连接
        3. 通过时间最近原则（先找时间最近的 backtest_run）

        Returns:
            Optional[str]: 回测 run_id，未找到返回 None
        """
        # 策略1：直接匹配
        row = source_conn.execute(
            "SELECT id FROM backtest_run WHERE id = ?", (analysis_run_id,)
        ).fetchone()
        if row:
            return row["id"]

        # 策略2：通过 analysis_ingested_run_ids
        try:
            # 查找 analysis_meta 中该 run_id 的创建时间
            am_row = source_conn.execute(
                "SELECT created_at FROM analysis_meta WHERE run_id = ?",
                (analysis_run_id,),
            ).fetchone()
            if am_row:
                # 找创建时间最接近的 backtest_run
                row = source_conn.execute(
                    """SELECT id FROM backtest_run
                       ORDER BY ABS(
                           julianday(created_at) - julianday(?)
                       ) ASC LIMIT 1""",
                    (am_row["created_at"],),
                ).fetchone()
                if row:
                    return row["id"]
        except Exception:
            pass

        return None

    def _sync_one_analysis(
        self,
        source_conn: sqlite3.Connection,
        archive_conn: sqlite3.Connection,
        run_id: str,
        analysis_id: int,
    ) -> Dict[str, int]:
        """
        同步单个分析记录及其关联数据，逐表复制。

        Args:
            source_conn: 源数据库连接
            archive_conn: 归档数据库连接
            run_id: 分析 run_id (analysis_meta.run_id)
            analysis_id: analysis_meta.id

        Returns:
            Dict[str, int]: 各表同步行数
        """
        row_counts: Dict[str, int] = {}

        # 尝试查找回测 run_id（backtest_run.id 可能不等于 analysis_run_id）
        backtest_run_id = self._find_backtest_run_id(source_conn, run_id)

        # 按同步顺序执行
        for table in SYNC_ORDER:
            if table == "analysis_meta":
                count = self._sync_table_where(
                    source_conn, archive_conn, table,
                    where_clause="id = ?", where_params=(analysis_id,),
                )
            elif table in ("analysis_metrics_core", "analysis_metrics_ext", "analysis_docs"):
                count = self._sync_table_where(
                    source_conn, archive_conn, table,
                    where_clause="analysis_id = ?", where_params=(analysis_id,),
                )
            elif table == "schema_version":
                # schema_version 是全局表，整个复制
                count = self._sync_table_where(
                    source_conn, archive_conn, table,
                    where_clause=None, where_params=None,
                )
            elif table == "backtest_run":
                if backtest_run_id:
                    count = self._sync_table_where(
                        source_conn, archive_conn, table,
                        where_clause="id = ?", where_params=(backtest_run_id,),
                    )
                else:
                    count = 0
            else:
                # 其他表（trade_log, daily_snapshot, performance_summary 等）
                rid = backtest_run_id if backtest_run_id else run_id
                count = self._sync_table_where(
                    source_conn, archive_conn, table,
                    where_clause="run_id = ?", where_params=(rid,),
                )

            if count > 0:
                row_counts[table] = count

        return row_counts

    def _sync_table_where(
        self,
        source_conn: sqlite3.Connection,
        archive_conn: sqlite3.Connection,
        table: str,
        where_clause: Optional[str] = None,
        where_params: Optional[tuple] = None,
        upsert_on: Optional[List[str]] = None,
    ) -> int:
        """
        从 source_db 复制符合 WHERE 条件的记录到归档库。

        使用 INSERT OR IGNORE 实现幂等性（通过主键去重）。
        只同步 source 和 archive 共同的列，避免列数不匹配。

        Args:
            source_conn: 源数据库连接
            archive_conn: 归档数据库连接
            table: 表名
            where_clause: WHERE 子句（不含 WHERE 关键字）
            where_params: WHERE 参数
            upsert_on: 冲突列（默认使用主键）

        Returns:
            int: 实际写入行数
        """
        # 1. 获取 source 和 archive 各自的列
        src_cols = [
            r[1]
            for r in source_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        ]
        arch_cols = [
            r[1]
            for r in archive_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        ]

        if not src_cols:
            self._log("WARNING", f"源表 {table} 无列信息，跳过")
            return 0
        if not arch_cols:
            self._log("WARNING", f"归档表 {table} 无列信息，跳过")
            return 0

        # 2. 取交集：只同步双方都有的列
        common_cols = [c for c in src_cols if c in arch_cols]
        if not common_cols:
            self._log("WARNING", f"表 {table} 无共同列，跳过")
            return 0

        col_names = ", ".join(f'"{c}"' for c in common_cols)
        placeholders = ", ".join(["?" for _ in common_cols])

        # 3. 构建查询（仅查询共同列）
        sql = f'SELECT {col_names} FROM "{table}"'
        if where_clause:
            sql += f" WHERE {where_clause}"

        try:
            rows = source_conn.execute(sql, where_params or ()).fetchall()
        except sqlite3.Error as e:
            self._log("WARNING", f"查询源表 {table} 失败: {e}")
            return 0

        if not rows:
            return 0

        # 4. 批量插入到归档库（INSERT OR IGNORE）
        insert_sql = (
            f'INSERT OR IGNORE INTO "{table}" ({col_names}) VALUES ({placeholders})'
        )

        try:
            params = [
                tuple(r[c] if isinstance(r, sqlite3.Row) else r[i]
                      for i, c in enumerate(common_cols))
                for r in rows
            ]
            before = archive_conn.total_changes
            archive_conn.executemany(insert_sql, params)
            inserted = archive_conn.total_changes - before
            return inserted
        except sqlite3.Error as e:
            self._log("ERROR", f"写入归档表 {table} 失败: {e}")
            self._log("ERROR", f"  SQL: {insert_sql}")
            self._log("ERROR", f"  COLS: {common_cols}")
            return 0

    # ── 实用方法 ──────────────────────────────────────────

    def get_archive_status(self) -> Dict[str, Any]:
        """
        查询归档状态：检查点信息 + 归档库大小 + 各表行数。

        Returns:
            dict: 归档状态信息
        """
        archive_path = self._resolve_archive_path()
        if not archive_path.exists():
            return {
                "archive_path": str(archive_path),
                "exists": False,
                "size_bytes": 0,
            }

        conn = self._connect_archive(str(archive_path))
        try:
            checkpoint = self._get_checkpoint(conn)

            table_counts = {}
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
            ).fetchall():
                cnt = conn.execute(f'SELECT COUNT(*) FROM "{row["name"]}"').fetchone()[0]
                table_counts[row["name"]] = cnt

            schema_version = None
            try:
                sv = conn.execute(
                    "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
                ).fetchone()
                if sv:
                    schema_version = sv["version"]
            except Exception:
                pass

            return {
                "archive_path": str(archive_path),
                "exists": True,
                "size_bytes": archive_path.stat().st_size,
                "last_checkpoint": dict(checkpoint) if checkpoint else None,
                "schema_version": schema_version,
                "table_counts": table_counts,
            }
        finally:
            conn.close()

    def list_archive_dbs(self) -> List[Dict[str, Any]]:
        """
        列出归档目录下所有归档数据库文件。

        Returns:
            list[dict]: 归档文件信息列表
        """
        results = []
        for f in sorted(self.archive_dir.glob("backtest_back_*.db")):
            results.append({
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "modified": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=SHANGHAI_TZ
                ).isoformat(),
            })
        return results


# ── 结果类型 ────────────────────────────────────────────


class SyncResult:
    """归档同步结果。"""

    def __init__(
        self,
        status: str,
        synced_run_ids: List[str],
        row_counts: Dict[str, int],
        archive_path: str,
    ):
        self.status = status
        self.synced_run_ids = synced_run_ids
        self.row_counts = row_counts
        self.archive_path = archive_path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "synced_run_ids": self.synced_run_ids,
            "row_counts": self.row_counts,
            "archive_path": self.archive_path,
        }

    def __repr__(self) -> str:
        return (
            f"SyncResult(status={self.status}, "
            f"synced={len(self.synced_run_ids)} runs, "
            f"rows={self.row_counts})"
        )


# ── 便捷函数 ─────────────────────────────────────────────


def sync_backtest_archive(
    source_db: str | Path | None = None,
    archive_dir: str | Path | None = None,
    verbose: bool = True,
) -> SyncResult:
    """
    便捷函数：执行一次完整的回测归档同步。

    在 run_tsi_backtest.py 末尾调用，或首次部署时手动调用。

    Args:
        source_db: 源数据库路径（默认 backtest.db）
        archive_dir: 归档目录（默认 data/）
        verbose: 是否打印详细输出

    Returns:
        SyncResult: 同步结果
    """
    if source_db is None:
        source_db = PROJECT_ROOT / "data" / "backtest.db"
    if archive_dir is None:
        archive_dir = PROJECT_ROOT / "data"

    mgr = ArchiveManager(
        source_db=source_db,
        archive_dir=archive_dir,
        verbose=verbose,
    )

    return mgr.sync()


def sync_single_run_id(
    run_id: str,
    source_db: str | Path | None = None,
    archive_dir: str | Path | None = None,
    verbose: bool = True,
) -> SyncResult:
    """
    便捷函数：归档指定的 run_id。

    用于首次部署时，将上一次回测结果归档入 backtest_back.db。

    Args:
        run_id: 回测运行 ID
        source_db: 源数据库路径（默认 backtest.db）
        archive_dir: 归档目录（默认 data/）
        verbose: 是否打印详细输出

    Returns:
        SyncResult: 同步结果
    """
    if source_db is None:
        source_db = PROJECT_ROOT / "data" / "backtest.db"
    if archive_dir is None:
        archive_dir = PROJECT_ROOT / "data"

    mgr = ArchiveManager(
        source_db=source_db,
        archive_dir=archive_dir,
        verbose=verbose,
    )

    return mgr.sync_run_id(run_id)
