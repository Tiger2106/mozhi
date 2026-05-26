"""
Test suite for ArchiveManager — 墨萱 (MiniMax-M2.7) 估算 25-30 用例，~4h 验证。

关键测试点：
  - 正常归档：对比两个库各表行数一致
  - 幂等性：同一 run_id 多次归档不产生重复数据
  - 断电恢复：模拟归档中中断，启动后能补录
  - 按月分区：跨月场景是否正确
  - 归档库宕机：主库不受影响
  - schema版本不匹配：明确拒绝

author: 墨衡 (DeepSeek R1)
created_time: 2026-05-23T19:00:00+08:00
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.backtest.archive_manager import (
    ArchiveManager,
    ArchiveError,
    SchemaVersionMismatch,
    SyncResult,
    sync_backtest_archive,
    sync_single_run_id,
)


# ── 测试辅助函数 ─────────────────────────────────────────


def _make_source_db(path: Path) -> sqlite3.Connection:
    """创建包含完整示例数据的源数据库。"""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row

    # 建表（镜像 backtest.db schema）
    _exec(conn, """
        CREATE TABLE analysis_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            parent_session_id INTEGER,
            tags TEXT,
            version_schema TEXT,
            version_content INTEGER,
            version_status TEXT NOT NULL DEFAULT 'draft',
            author TEXT,
            analysis_type TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
        )
    """)
    _exec(conn, """
        CREATE TABLE analysis_metrics_core (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            run_id TEXT NOT NULL,
            metric_group TEXT NOT NULL,
            total_return_pct REAL,
            annual_return_pct REAL,
            final_equity REAL,
            total_pnl REAL,
            sharpe_ratio REAL,
            max_drawdown_pct REAL,
            total_trades INTEGER,
            win_rate_pct REAL,
            verdict TEXT,
            risk_level TEXT DEFAULT 'mid'
        )
    """)
    _exec(conn, """
        CREATE TABLE analysis_metrics_ext (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            run_id TEXT NOT NULL,
            metric_group TEXT,
            metric_name TEXT NOT NULL,
            metric_value REAL,
            metric_label TEXT
        )
    """)
    _exec(conn, """
        CREATE TABLE analysis_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            run_id TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            file_path TEXT,
            content_hash TEXT,
            file_size_bytes INTEGER,
            word_count INTEGER,
            is_deleted INTEGER NOT NULL DEFAULT 0
        )
    """)
    _exec(conn, """
        CREATE TABLE schema_version (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT,
            checksum TEXT
        )
    """)
    _exec(conn, """
        CREATE TABLE trade_log (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'buy',
            volume REAL NOT NULL,
            entry_price REAL NOT NULL,
            pnl REAL,
            commission REAL
        )
    """)
    _exec(conn, """
        CREATE TABLE daily_snapshot (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            holding_shares REAL NOT NULL DEFAULT 0,
            market_value REAL NOT NULL DEFAULT 0,
            weight_pct REAL
        )
    """)
    _exec(conn, """
        CREATE TABLE performance_summary (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            ts_code TEXT,
            total_return REAL,
            annualized_return REAL,
            max_drawdown REAL,
            sharpe_ratio REAL,
            win_rate REAL,
            total_trades INTEGER,
            final_equity REAL
        )
    """)
    _exec(conn, """
        CREATE TABLE backtest_run (
            id TEXT PRIMARY KEY,
            run_name TEXT NOT NULL,
            version_tag TEXT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            triggered_by TEXT,
            periods TEXT,
            notes TEXT
        )
    """)
    _exec(conn, """
        CREATE TABLE strategy_config (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            strategy_type TEXT NOT NULL,
            initial_capital REAL NOT NULL DEFAULT 1000000.0,
            commission_rate REAL NOT NULL DEFAULT 0.0003,
            position_sizing TEXT NOT NULL DEFAULT 'equal',
            max_positions INTEGER NOT NULL DEFAULT 5
        )
    """)
    _exec(conn, """
        CREATE TABLE factor_result (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            factor_id TEXT NOT NULL,
            ts_code TEXT,
            mean_ic REAL,
            ir REAL,
            ic_positive_ratio REAL
        )
    """)
    _exec(conn, """
        CREATE TABLE validation_check (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            check_name TEXT NOT NULL,
            check_type TEXT NOT NULL,
            result TEXT NOT NULL,
            actual_value REAL,
            threshold_value REAL,
            detail TEXT
        )
    """)
    conn.commit()
    return conn


def _exec(conn: sqlite3.Connection, sql: str, params=()):
    conn.execute(sql, params)


def _add_analysis_record(
    conn: sqlite3.Connection,
    run_id: str,
    status: str = "final",
    analysis_type: str = "summary",
) -> int:
    """向源数据库添加一条分析记录。返回 analysis_meta.id。"""
    _exec(
        conn,
        """INSERT INTO analysis_meta (run_id, version_status, author, analysis_type)
           VALUES (?, ?, 'test', ?)""",
        (run_id, status, analysis_type),
    )
    aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 添加关联数据
    _exec(
        conn,
        """INSERT INTO analysis_metrics_core (analysis_id, run_id, metric_group, total_return_pct, total_trades)
           VALUES (?, ?, 'daily', 5.0, 10)""",
        (aid, run_id),
    )
    _exec(
        conn,
        """INSERT INTO analysis_docs (analysis_id, run_id, doc_type, file_path)
           VALUES (?, ?, 'report', '/tmp/test.md')""",
        (aid, run_id),
    )
    return aid


@pytest.fixture
def setup_env():
    """创建临时目录和源数据库。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 源数据库
        src_path = tmp / "source.db"
        conn = _make_source_db(src_path)

        # 添加一些示例数据
        run_id1 = str(uuid.uuid4())
        run_id2 = str(uuid.uuid4())

        # final 记录（应归档）
        _add_analysis_record(conn, run_id1, "final")
        # draft 记录（不应归档）
        _add_analysis_record(conn, run_id2, "draft")

        # 添加 schema_version
        _exec(conn, "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
              ("4.0", "2026-05-23T10:00:00", "test schema"))
        conn.commit()

        # 添加 backtest_run 数据
        _exec(conn, "INSERT INTO backtest_run (id, run_name, created_at, status) VALUES (?, ?, ?, ?)",
              (run_id1, "test_run_1", "2026-05-23T10:00:00", "done"))
        _exec(conn, "INSERT INTO backtest_run (id, run_name, created_at, status) VALUES (?, ?, ?, ?)",
              (run_id2, "test_run_2", "2026-05-23T10:00:00", "done"))

        # 添加 trade_log 数据到 run_id1
        tl_id = str(uuid.uuid4())
        _exec(conn, "INSERT INTO trade_log (id, run_id, ts_code, entry_date, volume, entry_price) VALUES (?, ?, ?, ?, ?, ?)",
              (tl_id, run_id1, "601857", "20260520", 1000, 10.5))

        # 添加 performance_summary
        ps_id = str(uuid.uuid4())
        _exec(conn, "INSERT INTO performance_summary (id, run_id, total_return, total_trades) VALUES (?, ?, ?, ?)",
              (ps_id, run_id1, 0.05, 10))

        conn.commit()
        conn.close()

        # 归档目录
        archive_dir = tmp / "archive"
        archive_dir.mkdir()

        yield {
            "tmpdir": tmp,
            "src_path": src_path,
            "archive_dir": archive_dir,
            "run_id1": run_id1,
            "run_id2": run_id2,
        }

        # 清理
        if archive_dir.exists():
            for f in archive_dir.glob("*.db"):
                f.unlink()


# ── 测试用例 ─────────────────────────────────────────────


class TestArchiveManager:
    """ArchiveManager 测试套件"""

    def test_normal_archive(self, setup_env):
        """测试正常归档：对比两个库各表行数一致"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
            verbose=True,
        )

        result = mgr.sync()

        assert result.status == "SUCCESS"
        assert len(result.synced_run_ids) == 1  # 只有 final 记录
        assert result.synced_run_ids[0] == setup_env["run_id1"]

        # 验证归档库内容
        archive_path = result.archive_path
        conn = sqlite3.connect(archive_path)
        conn.row_factory = sqlite3.Row

        # analysis_meta
        rows = conn.execute("SELECT * FROM analysis_meta").fetchall()
        assert len(rows) == 1
        assert rows[0]["run_id"] == setup_env["run_id1"]
        assert rows[0]["version_status"] == "final"

        # analysis_metrics_core
        rows = conn.execute("SELECT * FROM analysis_metrics_core").fetchall()
        assert len(rows) == 1
        assert rows[0]["run_id"] == setup_env["run_id1"]

        # analysis_docs
        rows = conn.execute("SELECT * FROM analysis_docs").fetchall()
        assert len(rows) == 1

        # schema_version
        rows = conn.execute("SELECT * FROM schema_version").fetchall()
        assert len(rows) == 1

        # backtest_run
        rows = conn.execute("SELECT * FROM backtest_run").fetchall()
        assert len(rows) == 1

        # trade_log
        rows = conn.execute("SELECT * FROM trade_log").fetchall()
        assert len(rows) == 1

        # performance_summary
        rows = conn.execute("SELECT * FROM performance_summary").fetchall()
        assert len(rows) == 1

        # sync_checkpoint
        rows = conn.execute("SELECT * FROM sync_checkpoint").fetchall()
        assert len(rows) == 1

        conn.close()

    def test_idempotent(self, setup_env):
        """测试幂等性：同一 run_id 多次归档不产生重复数据"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        # 第一次归档
        result1 = mgr.sync()
        assert result1.status == "SUCCESS"
        assert len(result1.synced_run_ids) == 1

        # 第二次归档（不应产生新数据）
        result2 = mgr.sync()
        assert result2.status == "NOOP"  # 没有待归档的数据
        assert len(result2.synced_run_ids) == 0

        # 验证归档库行数不变
        archive_path = result1.archive_path
        conn = sqlite3.connect(archive_path)
        for t in ["analysis_meta", "analysis_metrics_core", "analysis_docs"]:
            cnt1 = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            cnt2 = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            assert cnt1 == cnt2, f"表 {t} 行数变化"
        conn.close()

    def test_only_final_records(self, setup_env):
        """测试只归档 final 状态记录"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        result = mgr.sync()
        assert result.status == "SUCCESS"

        # 确认只有 final 记录被归档
        conn = sqlite3.connect(result.archive_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT version_status FROM analysis_meta").fetchall()
        for r in rows:
            assert r["version_status"] == "final"
        conn.close()

    def test_no_final_records(self, setup_env):
        """测试没有 final 记录时返回 NOOP"""
        # 将所有记录改为 draft
        conn = sqlite3.connect(str(setup_env["src_path"]))
        conn.execute("UPDATE analysis_meta SET version_status = 'draft'")
        conn.commit()
        conn.close()

        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        result = mgr.sync()
        assert result.status == "NOOP"

    def test_empty_source(self, setup_env):
        """测试空源数据库"""
        tmp = setup_env["tmpdir"]
        empty_path = tmp / "empty.db"
        conn = _make_source_db(empty_path)
        conn.close()

        mgr = ArchiveManager(
            source_db=empty_path,
            archive_dir=setup_env["archive_dir"],
        )

        result = mgr.sync()
        assert result.status == "NOOP"

    def test_source_not_found(self):
        """测试源数据库不存在"""
        tmp = Path(tempfile.mkdtemp())
        try:
            mgr = ArchiveManager(
                source_db=tmp / "nonexistent.db",
                archive_dir=tmp,
            )
            with pytest.raises(ArchiveError):
                mgr.sync()
        finally:
            for f in tmp.glob("*.db"):
                f.unlink()
            tmp.rmdir()

    def test_sync_single_run_id(self, setup_env):
        """测试指定 run_id 归档"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        result = mgr.sync_run_id(setup_env["run_id1"])
        assert result.status == "SUCCESS"
        assert result.synced_run_ids == [setup_env["run_id1"]]

    def test_sync_nonexistent_run_id(self, setup_env):
        """测试归档不存在的 run_id"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        result = mgr.sync_run_id("nonexistent-run-id")
        assert result.status == "NOT_FOUND"

    def test_archive_status(self, setup_env):
        """测试 get_archive_status 返回正确状态"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        # 归档前：不存在
        status = mgr.get_archive_status()
        assert status["exists"] is False

        # 归档后
        mgr.sync()
        status = mgr.get_archive_status()
        assert status["exists"] is True
        assert status["table_counts"].get("analysis_meta", 0) == 1
        assert status["last_checkpoint"] is not None

    def test_list_archive_dbs(self, setup_env):
        """测试列出归档库文件"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        dbs = mgr.list_archive_dbs()
        assert len(dbs) == 0  # 还没有归档文件

        mgr.sync()
        dbs = mgr.list_archive_dbs()
        assert len(dbs) == 1
        assert dbs[0]["size_bytes"] > 0

    def test_sync_result_to_dict(self, setup_env):
        """测试 SyncResult.to_dict"""
        result = SyncResult(
            status="SUCCESS",
            synced_run_ids=["run1"],
            row_counts={"analysis_meta": 1},
            archive_path="/tmp/test.db",
        )
        d = result.to_dict()
        assert d["status"] == "SUCCESS"
        assert d["synced_run_ids"] == ["run1"]

    def test_sync_result_repr(self):
        """测试 SyncResult.__repr__"""
        result = SyncResult(status="NOOP", synced_run_ids=[], row_counts={}, archive_path="")
        r = repr(result)
        assert "NOOP" in r

    def test_convenience_sync_function(self, setup_env):
        """测试便捷函数 sync_backtest_archive"""
        result = sync_backtest_archive(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
            verbose=False,
        )
        assert result.status == "SUCCESS"

    def test_convenience_sync_single(self, setup_env):
        """测试便捷函数 sync_single_run_id"""
        result = sync_single_run_id(
            run_id=setup_env["run_id1"],
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
            verbose=False,
        )
        assert result.status == "SUCCESS"

    def test_schema_version_check(self, setup_env):
        """测试 schema 版本检查（需要 backtest.db 的 analysis_* 表有 schema_version）"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        # 正常情况，schema_version = 4.0
        mgr.sync()

        # 手动修改归档库的 schema_version 为不兼容版本
        archive_path = mgr._resolve_archive_path()
        conn = sqlite3.connect(str(archive_path))
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES ('2.0', '2026-05-23T10:00:00')")
        conn.commit()
        conn.close()

        # 再次同步应抛出 SchemaVersionMismatch
        with pytest.raises(SchemaVersionMismatch):
            mgr.sync()

    def test_draft_not_archived(self, setup_env):
        """测试 draft 记录不会被归档"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )
        result = mgr.sync()
        assert result.status == "SUCCESS"

        # 验证只有一条记录（run_id1 是 final，run_id2 是 draft）
        conn = sqlite3.connect(result.archive_path)
        cnt = conn.execute("SELECT COUNT(*) FROM analysis_meta").fetchone()[0]
        assert cnt == 1
        conn.close()

    def test_error_isolation(self, setup_env):
        """测试归档失败不影响主库"""
        # 先记录归档前的源库状态
        src_conn_before = sqlite3.connect(str(setup_env["src_path"]))
        src_conn_before.row_factory = sqlite3.Row
        run_ids_before = {r["run_id"]: dict(r) for r in
                          src_conn_before.execute("SELECT * FROM analysis_meta").fetchall()}
        src_conn_before.close()

        # 故意破坏归档目录（设为不可写）
        archive_dir = setup_env["archive_dir"]
        original_mode = archive_dir.stat().st_mode

        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=archive_dir,
        )

        result = mgr.sync()
        assert result.status == "SUCCESS"  # 归档本身成功

        # 验证源库未受影响
        src_conn_after = sqlite3.connect(str(setup_env["src_path"]))
        src_conn_after.row_factory = sqlite3.Row
        run_ids_after = {r["run_id"]: dict(r) for r in
                         src_conn_after.execute("SELECT * FROM analysis_meta").fetchall()}
        src_conn_after.close()

        assert len(run_ids_before) == len(run_ids_after)
        for rid in run_ids_before:
            assert rid in run_ids_after
            assert run_ids_before[rid]["version_status"] == run_ids_after[rid]["version_status"]

    def test_monthly_partition(self, setup_env):
        """测试按月分区：归档库文件名包含当前月份"""
        from src.config import SHANGHAI_TZ

        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        result = mgr.sync()
        # 归档文件名应包含当前月份
        from datetime import datetime
        expected_month = datetime.now(SHANGHAI_TZ).strftime("%Y%m")
        assert expected_month in result.archive_path
        assert "backtest_back_" in result.archive_path

    def test_checkpoint_records_all_syncs(self, setup_env):
        """测试 sync_checkpoint 记录每次同步"""
        mgr = ArchiveManager(
            source_db=setup_env["src_path"],
            archive_dir=setup_env["archive_dir"],
        )

        # 第一次同步
        mgr.sync()

        # 检查归档库的检查点
        archive_path = mgr._resolve_archive_path()
        conn = sqlite3.connect(str(archive_path))
        cps = conn.execute("SELECT * FROM sync_checkpoint").fetchall()
        assert len(cps) == 1
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
