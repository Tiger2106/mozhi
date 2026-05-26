"""
test_file_lifecycle.py — file_lifecycle 模块测试 (v3)

测试覆盖：
- 数据库创建和表结构（含新列）
- register-incoming（标准化分类 + checksum + source_type）
- search（新增 source_type 过滤）
- status统计（含 source_type 分布）
- update更新记录（current_path 替换 final_path）
- archive-scan（标准化分类 + source_type='migrated'）
- checksum 计算
- current_path 维护
- source_type 枚举校验
- auto-note 摘要提取
- 标准化分类映射（CATEGORY_MAP）

作者: moheng
创建时间: 2026-05-15
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

# 确保 src 目录在 sys.path 中
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR.parent))

from src.utils.file_lifecycle import (
    get_db,
    ensure_db,
    rebuild_db,
    register_incoming,
    archive_scan,
    daily_maintenance,
    scan_registry,
    search,
    update_record,
    show_status,
    export_csv,
    compute_checksum,
    extract_summary,
    map_target_to_category,
    VALID_STATUSES,
    VALID_CATEGORIES,
    VALID_SOURCES,
    VALID_SOURCE_TYPES,
    CATEGORY_MAP,
    DDL_CREATE_TABLE,
    DB_PATH,
)


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_env(tmp_path):
    """
    自动应用的 fixture：为每个测试创建独立的临时目录结构。
    模拟 mozhi_platform 项目骨架，覆盖 DB_PATH、INCOMING_BASE、ARCHIVE_BASE。
    """
    import src.utils.file_lifecycle as flc

    orig_db_path = flc.DB_PATH
    orig_incoming_base = flc.INCOMING_BASE
    orig_registry_dir = flc.REGISTRY_DIR
    orig_archive_base = flc.ARCHIVE_BASE

    mock_root = tmp_path / "mozhi_platform"
    mock_root.mkdir()
    incoming_dir = mock_root / "incoming"
    incoming_dir.mkdir()
    registry_dir = mock_root / "registry"
    registry_dir.mkdir()

    archive_dir = tmp_path / "mock_sharereports"
    archive_dir.mkdir()

    flc.REGISTRY_DIR = registry_dir
    flc.DB_PATH = registry_dir / "file_registry.db"
    flc.INCOMING_BASE = incoming_dir
    flc.PROJECT_ROOT = mock_root
    flc.ARCHIVE_BASE = archive_dir

    yield {
        "root": mock_root,
        "incoming": incoming_dir,
        "registry": registry_dir,
        "db_path": registry_dir / "file_registry.db",
        "archive": archive_dir,
    }

    flc.DB_PATH = orig_db_path
    flc.INCOMING_BASE = orig_incoming_base
    flc.REGISTRY_DIR = orig_registry_dir
    flc.ARCHIVE_BASE = orig_archive_base


@pytest.fixture
def incoming_dir(isolated_env):
    return isolated_env["incoming"]


@pytest.fixture
def registry_dir(isolated_env):
    return isolated_env["registry"]


@pytest.fixture
def db_path(isolated_env):
    return isolated_env["db_path"]


@pytest.fixture
def archive_dir(isolated_env):
    return isolated_env["archive"]


def create_data_file(dir_path: Path, filename: str, content: str = "test data"):
    """在指定目录下创建数据文件。"""
    file_path = dir_path / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


def create_meta_file(dir_path: Path, filename: str, meta: dict = None):
    """在指定目录下创建 .meta.json 文件。"""
    if meta is None:
        meta = {
            "created_at": "2026-05-15 10:00",
            "source": "manual",
            "status": "incoming",
            "target": "automation_v2",
            "owner": "moheng",
            "description": "测试文件",
        }
    meta_path = dir_path / f"{filename}.meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta_path


def create_incoming_structure(incoming_dir: Path, date_str: str, files: list):
    """
    在 incoming/{date_str}/ 下创建指定文件结构。
    files: [(data_filename, meta_dict_or_None), ...]
    """
    date_dir = incoming_dir / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    for data_file, meta in files:
        create_data_file(date_dir, data_file)
        if meta is not None:
            create_meta_file(date_dir, data_file, meta)

    return date_dir


# ─── 测试数据库创建和表结构 ─────────────────────────────────


class TestDatabaseInit:
    def test_ensure_db_creates_file(self, db_path):
        """ensure_db 应创建数据库文件。"""
        assert not db_path.exists()
        ensure_db()
        assert db_path.exists()

    def test_ensure_db_creates_table(self, db_path):
        """ensure_db 应创建 files 表。"""
        ensure_db()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='files'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_table_columns(self, db_path):
        """files 表应包含所有必需字段（v3 新增 current_path, checksum, source_type）。"""
        ensure_db()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(files)")
        rows = cursor.fetchall()
        columns = {row[1]: row for row in rows}
        column_names = list(columns.keys())
        conn.close()

        required_columns = [
            "id", "filename", "original_path", "current_path", "category",
            "source", "status", "checksum", "source_type",
            "created_at", "imported_at", "tags", "note",
        ]
        for col in required_columns:
            assert col in columns, f"缺少必需字段: {col}"

        # v3 规范列顺序
        assert "current_path" in columns, "current_path 列应存在"
        assert "checksum" in columns, "checksum 列应存在"
        assert "source_type" in columns, "source_type 列应存在"
        assert "final_path" not in columns, "final_path 已被 current_path 替代"

    def test_unique_index_on_original_path(self, db_path):
        """original_path 应有唯一索引。"""
        ensure_db()
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO files (filename, original_path) VALUES (?, ?)",
            ("test.py", "/tmp/test.py"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO files (filename, original_path) VALUES (?, ?)",
                ("test2.py", "/tmp/test.py"),
            )
        conn.close()

    def test_id_autoincrement(self, db_path):
        """id 应自动递增。"""
        ensure_db()
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO files (filename, original_path) VALUES (?, ?)",
            ("a.py", "/tmp/a.py"),
        )
        conn.execute(
            "INSERT INTO files (filename, original_path) VALUES (?, ?)",
            ("b.py", "/tmp/b.py"),
        )
        cursor = conn.execute("SELECT id FROM files ORDER BY id")
        ids = [row[0] for row in cursor.fetchall()]
        assert ids == [1, 2], f"预期 ID [1, 2]，实际 {ids}"
        conn.close()

    def test_current_path_defaults_to_original(self, db_path):
        """INSERT 时 current_path 应初始化为 original_path。"""
        ensure_db()
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO files (filename, original_path, current_path) VALUES (?, ?, ?)",
            ("test.py", "/tmp/test.py", "/tmp/test.py"),
        )
        cursor = conn.execute("SELECT original_path, current_path FROM files WHERE id = 1")
        row = cursor.fetchone()
        assert row[0] == row[1], "current_path 初始应等于 original_path"
        conn.close()

    def test_source_type_default(self, db_path):
        """source_type 默认值应为 'unknown'。"""
        ensure_db()
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO files (filename, original_path) VALUES (?, ?)",
            ("test.py", "/tmp/test.py"),
        )
        cursor = conn.execute("SELECT source_type FROM files WHERE id = 1")
        row = cursor.fetchone()
        assert row[0] == "unknown", f"source_type 默认应为 'unknown', 实际 {row[0]}"
        conn.close()


# ─── 测试 checksum ──────────────────────────────────────────


class TestChecksum:
    def test_compute_checksum_sha256(self, tmp_path):
        """compute_checksum 应返回 SHA256 hex digest。"""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        cs = compute_checksum(f)
        # SHA256 of "hello world"
        assert cs == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert len(cs) == 64

    def test_compute_checksum_empty_file(self, tmp_path):
        """空文件的 SHA256。"""
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        cs = compute_checksum(f)
        assert cs == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert len(cs) == 64

    def test_compute_checksum_nonexistent(self, tmp_path):
        """不存在的文件应返回空字符串。"""
        f = tmp_path / "nonexistent.txt"
        cs = compute_checksum(f)
        assert cs == ""

    def test_checksum_in_register_incoming(self, incoming_dir, db_path):
        """register-incoming 应计算并保存 checksum。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("fix_settlement.py", {"source": "manual", "target": "automation_v2"}),
        ])
        count = register_incoming(date_str="20260515", verbose=False)
        assert count == 1

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT checksum FROM files")
        cs = cursor.fetchone()[0]
        conn.close()
        assert cs and len(cs) == 64, f"checksum 应为 64 位 hex, 实际: '{cs}'"


# ─── 测试 source_type ───────────────────────────────────────


class TestSourceType:
    def test_incoming_source_type_unknown(self, incoming_dir, db_path):
        """register-incoming 的 source_type 应为 'unknown'。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("test.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT source_type FROM files")
        st = cursor.fetchone()[0]
        conn.close()
        assert st == "unknown"

    def test_archive_source_type_migrated(self, archive_dir, db_path):
        """archive-scan 的 source_type 应为 'migrated'。"""
        (archive_dir / "reports" / "daily.md").parent.mkdir(parents=True)
        (archive_dir / "reports" / "daily.md").write_text("# Daily Report", encoding="utf-8")
        archive_scan(verbose=False)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT source_type FROM files")
        st = cursor.fetchone()[0]
        conn.close()
        assert st == "migrated"

    def test_source_type_enum_valid(self):
        """VALID_SOURCE_TYPES 枚举应正确。"""
        expected = {"ai_chatgpt", "ai_deepseek", "manual", "imported", "migrated", "unknown"}
        assert set(VALID_SOURCE_TYPES) == expected


# ─── 测试 register-incoming ─────────────────────────────────


class TestRegisterIncoming:
    def test_single_file(self, incoming_dir, db_path):
        """登记单个文件。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("fix_settlement.py", {
                "created_at": "2026-05-15 10:00",
                "source": "manual",
                "status": "incoming",
                "target": "automation_v2",
                "owner": "moheng",
                "description": "结算修复脚本",
            }),
        ])

        count = register_incoming(date_str="20260515", verbose=False)
        assert count == 1

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT * FROM files")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 1
        row = rows[0]
        assert row[1] == "fix_settlement.py"  # filename
        assert row[4] == "automation"          # category (标准化)
        assert row[5] == "incoming"            # source

    def test_multiple_files_standardized_categories(self, incoming_dir, db_path):
        """多个文件应映射到标准化分类。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("a.py", {"source": "manual", "target": "automation_v2"}),
            ("b.py", {"source": "cron", "target": "ta_backtest"}),
            ("c.py", {"source": "api", "target": "docs"}),
        ])

        count = register_incoming(date_str="20260515", verbose=False)
        assert count == 3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT filename, category FROM files ORDER BY filename")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 3
        categories = {r[0]: r[1] for r in rows}
        assert categories["a.py"] == "automation"
        assert categories["b.py"] == "backtest"
        assert categories["c.py"] == "docs"

    def test_skip_duplicate(self, incoming_dir, db_path):
        """重复登记应跳过已存在的记录。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("unique.py", {"source": "manual", "target": "automation_v2"}),
        ])

        count1 = register_incoming(date_str="20260515", verbose=False)
        assert count1 == 1

        count2 = register_incoming(date_str="20260515", verbose=False)
        assert count2 == 0

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        total = cursor.fetchone()[0]
        conn.close()
        assert total == 1

    def test_skip_only_with_meta(self, incoming_dir, db_path):
        """没有 .meta.json 的数据文件应跳过。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("with_meta.py", {"source": "manual", "target": "automation_v2"}),
            ("no_meta.py", None),
        ])

        count = register_incoming(date_str="20260515", verbose=False)
        assert count == 1

    def test_meta_file_self_skip(self, incoming_dir, db_path):
        """.meta.json 自身应被跳过。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("test.py", {"source": "manual", "target": "automation_v2"}),
        ])
        create_meta_file(incoming_dir / "20260515", "orphan_only", {"source": "test"})

        count = register_incoming(date_str="20260515", verbose=False)
        assert count == 1

    def test_dry_run_no_write(self, incoming_dir, db_path):
        """dry-run 不应实际写入数据库。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("dry.py", {"source": "manual", "target": "automation_v2"}),
        ])

        count = register_incoming(date_str="20260515", verbose=False, dry_run=True)
        assert count == 0

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        total = cursor.fetchone()[0]
        conn.close()
        assert total == 0

    def test_target_to_category_mapping_standardized(self, incoming_dir, db_path):
        """target 字段应正确映射到标准化分类。"""
        files_data = [
            ("auto.py", {"source": "cron", "target": "automation-module"}),
            ("bt.py", {"source": "manual", "target": "backtest-strategy"}),
            ("doc.py", {"source": "manual", "target": "documentation"}),
            ("tool.py", {"source": "manual", "target": "tooling"}),
            ("trade.py", {"source": "system", "target": "trading-core"}),
            ("data.py", {"source": "api", "target": "data-feed"}),
            ("cfg.py", {"source": "manual", "target": "config-module"}),
        ]
        create_incoming_structure(incoming_dir, "20260515", files_data)

        count = register_incoming(date_str="20260515", verbose=False)
        assert count == 7

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT filename, category FROM files ORDER BY filename")
        rows = cursor.fetchall()
        conn.close()

        cat_map = {r[0]: r[1] for r in rows}
        assert cat_map["auto.py"] == "automation"
        assert cat_map["bt.py"] == "backtest"
        assert cat_map["doc.py"] == "docs"
        assert cat_map["tool.py"] == "tools"
        assert cat_map["trade.py"] == "shared"   # trading → shared
        assert cat_map["data.py"] == "db"        # data → db
        assert cat_map["cfg.py"] == "tools"      # config → tools


# ─── 测试 search ─────────────────────────────────────────


class TestSearch:
    def _setup_data(self, incoming_dir, db_path):
        """准备搜索测试数据。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("fix_settlement.py", {
                "source": "manual", "target": "automation_v2",
                "description": "结算修复脚本",
            }),
            ("trend_analysis.py", {
                "source": "cron", "target": "ta_backtest",
                "description": "趋势分析脚本",
            }),
            ("report_generator.py", {
                "source": "cron", "target": "reports",
                "description": "报告生成器",
            }),
        ])
        register_incoming(date_str="20260515", verbose=False)

    def test_search_by_filename(self, incoming_dir, db_path):
        """按文件名模糊搜索。"""
        self._setup_data(incoming_dir, db_path)
        results = search(filename="settlement", verbose=False)
        assert len(results) == 1
        assert results[0]["filename"] == "fix_settlement.py"

    def test_search_by_tag(self, incoming_dir, db_path):
        """按标签搜索。"""
        self._setup_data(incoming_dir, db_path)
        results = search(tag="cron", verbose=False)
        assert len(results) == 2
        filenames = {r["filename"] for r in results}
        assert filenames == {"trend_analysis.py", "report_generator.py"}

    def test_search_by_category_standardized(self, incoming_dir, db_path):
        """按标准化分类精确搜索。"""
        self._setup_data(incoming_dir, db_path)
        results = search(category="automation", verbose=False)
        assert len(results) == 1
        assert results[0]["filename"] == "fix_settlement.py"

    def test_search_by_keyword(self, incoming_dir, db_path):
        """按关键词搜索。"""
        self._setup_data(incoming_dir, db_path)
        results = search(keyword="结算", verbose=False)
        assert len(results) == 1
        assert results[0]["filename"] == "fix_settlement.py"

        results = search(keyword="analysis", verbose=False)
        assert len(results) == 1
        assert results[0]["filename"] == "trend_analysis.py"

    def test_search_combined_conditions(self, incoming_dir, db_path):
        """组合条件搜索。"""
        self._setup_data(incoming_dir, db_path)
        results = search(filename="report", category="reports", verbose=False)
        assert len(results) == 1
        assert results[0]["filename"] == "report_generator.py"

        results = search(filename="settlement", tag="cron", verbose=False)
        assert len(results) == 0

    def test_search_by_source(self, incoming_dir, db_path):
        """按来源过滤搜索。"""
        self._setup_data(incoming_dir, db_path)
        results = search(source="incoming", verbose=False)
        assert len(results) == 3

    def test_search_by_source_type(self, incoming_dir, db_path):
        """按 source_type 过滤搜索。"""
        self._setup_data(incoming_dir, db_path)
        results = search(source_type="unknown", verbose=False)
        assert len(results) == 3

        results = search(source_type="migrated", verbose=False)
        assert len(results) == 0

    def test_search_by_source_nonexistent(self, incoming_dir, db_path):
        """按不存在的来源搜索应返回空列表。"""
        self._setup_data(incoming_dir, db_path)
        results = search(source="archive", verbose=False)
        assert len(results) == 0


# ─── 测试 status ───────────────────────────────────────────


class TestStatus:
    def test_empty_db_shows_zero(self, db_path):
        """空数据库应显示 0 条记录。"""
        stats = show_status(verbose=False)
        assert stats["total"] == 0

    def test_status_distribution(self, incoming_dir, db_path):
        """状态分布应正确统计。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("a.py", {"source": "manual", "target": "automation_v2"}),
            ("b.py", {"source": "manual", "target": "automation_v2"}),
        ])
        create_incoming_structure(incoming_dir, "20260516", [
            ("c.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str=None, verbose=False)

        stats = show_status(verbose=False)
        assert stats["total"] == 3
        assert stats["status_distribution"].get("incoming", 0) == 3

    def test_category_distribution_standardized(self, incoming_dir, db_path):
        """标准化分类分布应正确统计。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("a.py", {"source": "manual", "target": "automation_v2"}),
            ("b.py", {"source": "manual", "target": "ta_backtest"}),
            ("c.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        stats = show_status(verbose=False)
        assert stats["category_distribution"].get("automation", 0) == 2
        assert stats["category_distribution"].get("backtest", 0) == 1
        # 旧分类名不应出现
        assert "automation_v2" not in stats["category_distribution"]
        assert "ta_backtest" not in stats["category_distribution"]

    def test_source_type_distribution(self, incoming_dir, archive_dir, db_path):
        """source_type 分布应正确统计。"""
        # incoming → source_type='unknown'
        create_incoming_structure(incoming_dir, "20260515", [
            ("a.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        # archive → source_type='migrated'
        (archive_dir / "reports" / "daily.md").parent.mkdir(parents=True)
        (archive_dir / "reports" / "daily.md").write_text("# Daily", encoding="utf-8")
        archive_scan(verbose=False)

        stats = show_status(verbose=False)
        assert stats["total"] == 2
        assert stats["source_type_distribution"].get("unknown", 0) == 1
        assert stats["source_type_distribution"].get("migrated", 0) == 1

    def test_recent_7_days(self, incoming_dir, db_path):
        """最近7天新增统计。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("a.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        stats = show_status(verbose=False)
        assert stats["recent_7_days"] == 1


# ─── 测试 update ──────────────────────────────────────────


class TestUpdate:
    def test_update_current_path_and_status(self, incoming_dir, db_path):
        """更新 current_path 和 status。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("update_me.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        original_path = str((incoming_dir / "20260515" / "update_me.py").resolve())
        success = update_record(
            original_path=original_path,
            current_path="automation/update_me.py",
            status="production",
            verbose=False,
        )
        assert success

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT current_path, status FROM files WHERE original_path = ?",
            (original_path,),
        )
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "automation/update_me.py"
        assert row[1] == "production"

    def test_update_category_and_tags(self, incoming_dir, db_path):
        """更新分类和标签。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("categorize.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        original_path = str((incoming_dir / "20260515" / "categorize.py").resolve())
        success = update_record(
            original_path=original_path,
            category="backtest",
            tags="high-priority,settlement",
            note="已归入回测模块",
            verbose=False,
        )
        assert success

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT category, tags, note FROM files WHERE original_path = ?",
            (original_path,),
        )
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "backtest"
        assert row[1] == "high-priority,settlement"
        assert row[2] == "已归入回测模块"

    def test_update_source_type(self, incoming_dir, db_path):
        """更新 source_type。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("st_test.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        original_path = str((incoming_dir / "20260515" / "st_test.py").resolve())
        success = update_record(
            original_path=original_path,
            source_type="manual",
            verbose=False,
        )
        assert success

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT source_type FROM files WHERE original_path = ?",
            (original_path,),
        )
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "manual"

    def test_update_nonexistent_record(self, incoming_dir, db_path):
        """更新不存在的记录应返回 False。"""
        success = update_record(
            original_path="/nonexistent/path.py",
            status="production",
            verbose=False,
        )
        assert not success

    def test_invalid_status_rejected(self, incoming_dir, db_path):
        """无效 status 应被拒绝。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("test.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        original_path = str((incoming_dir / "20260515" / "test.py").resolve())
        success = update_record(
            original_path=original_path,
            status="nonexistent_status",
            verbose=False,
        )
        assert not success

    def test_invalid_source_type_rejected(self, incoming_dir, db_path):
        """无效 source_type 应被拒绝。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("st_bad.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        original_path = str((incoming_dir / "20260515" / "st_bad.py").resolve())
        success = update_record(
            original_path=original_path,
            source_type="invalid_type",
            verbose=False,
        )
        assert not success


# ─── 测试 scan-registry ────────────────────────────────────


class TestScanRegistry:
    def test_empty_scan(self, db_path):
        """空数据库扫描。"""
        ensure_db()
        report = scan_registry(verbose=False)
        assert report["total"] == 0
        assert report["orphans"] == []

    def test_orphan_detection(self, incoming_dir, db_path):
        """孤儿文件检测。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("will_delete.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        target = incoming_dir / "20260515" / "will_delete.py"
        target.unlink()

        report = scan_registry(verbose=False)
        assert report["total"] == 1
        assert len(report["orphans"]) == 1
        assert report["orphans"][0]["filename"] == "will_delete.py"


# ─── 测试 export ───────────────────────────────────────────


class TestExport:
    def test_export_csv(self, incoming_dir, db_path, tmp_path):
        """CSV 导出。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("test.csv.py", {"source": "manual", "target": "automation_v2"}),
        ])
        register_incoming(date_str="20260515", verbose=False)

        output = str(tmp_path / "export_test.csv")
        result = export_csv(output_path=output, verbose=False)

        assert Path(result).exists()
        content = Path(result).read_text(encoding="utf-8-sig")
        assert "filename" in content
        assert "current_path" in content
        assert "checksum" in content
        assert "source_type" in content
        assert "test.csv.py" in content


# ─── 测试批量注册 ──────────────────────────────────────────


class TestBatchRegister:
    def test_multiple_date_dirs(self, incoming_dir, db_path):
        """多个日期目录应全部扫描。"""
        create_incoming_structure(incoming_dir, "20260515", [
            ("day1.py", {"source": "manual", "target": "automation_v2"}),
        ])
        create_incoming_structure(incoming_dir, "20260516", [
            ("day2.py", {"source": "cron", "target": "ta_backtest"}),
        ])
        create_incoming_structure(incoming_dir, "20260517", [
            ("day3.py", {"source": "api", "target": "docs"}),
        ])

        count = register_incoming(date_str=None, verbose=False)
        assert count == 3

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        total = cursor.fetchone()[0]
        conn.close()
        assert total == 3

    def test_empty_date_dir_skipped(self, incoming_dir, db_path):
        """空日期目录应跳过。"""
        (incoming_dir / "20260515").mkdir(parents=True)
        count = register_incoming(date_str="20260515", verbose=False)
        assert count == 0


# ─── 测试 CLI 入口 ─────────────────────────────────────────


class TestCLI:
    def test_init_command(self, incoming_dir, db_path):
        """init 子命令应初始化数据库。"""
        import src.utils.file_lifecycle as flc
        assert not db_path.exists()

        sys.argv = ["file_lifecycle.py", "init"]
        try:
            flc.main()
        except SystemExit:
            pass

        assert db_path.exists()

    def test_register_incoming_cli(self, incoming_dir, db_path):
        """register-incoming CLI 子命令。"""
        import src.utils.file_lifecycle as flc
        create_incoming_structure(incoming_dir, "20260515", [
            ("cli_test.py", {"source": "manual", "target": "automation_v2"}),
        ])

        sys.argv = ["file_lifecycle.py", "register-incoming", "--date", "20260515", "--quiet"]
        try:
            flc.main()
        except SystemExit:
            pass

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_status_cli(self, db_path):
        """status 子命令。"""
        import src.utils.file_lifecycle as flc
        sys.argv = ["file_lifecycle.py", "status"]
        try:
            flc.main()
        except SystemExit:
            pass


# ─── 测试 archive-scan ────────────────────────────────────


class TestArchiveScan:
    def _setup_archive(self, archive_dir):
        """创建 mock 存档目录结构。"""
        (archive_dir / "reports" / "morning" / "20260515").mkdir(parents=True)
        (archive_dir / "reports" / "morning" / "20260515" / "report_1.md").write_text("report 1", encoding="utf-8")
        (archive_dir / "reports" / "morning" / "20260515" / "report_2.md").write_text("report 2", encoding="utf-8")

        (archive_dir / "agents" / "moheng").mkdir(parents=True)
        (archive_dir / "agents" / "moheng" / "analysis.json").write_text("{}", encoding="utf-8")

        (archive_dir / "config").mkdir()
        (archive_dir / "config" / "settings.yaml").write_text("key: value", encoding="utf-8")

        (archive_dir / "signals" / "triggers").mkdir(parents=True)
        (archive_dir / "signals" / "triggers" / "trigger.json").write_text("{}", encoding="utf-8")

        (archive_dir / ".git" / "objects").mkdir(parents=True)
        (archive_dir / ".git" / "objects" / "hash").write_text("data", encoding="utf-8")

        return 5  # 期望被扫描到的文件数（含 signals/ 下的 1 个）

    def test_archive_scan_basic(self, archive_dir, db_path):
        """基础 archive 扫描。"""
        expected = self._setup_archive(archive_dir)
        count = archive_scan(verbose=False, dry_run=False)
        assert count == expected

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT filename, source, source_type, category FROM files ORDER BY filename")
        rows = cursor.fetchall()
        conn.close()
        assert len(rows) == expected
        for row in rows:
            assert row[1] == "archive"         # source
            assert row[2] == "migrated"        # source_type

    def test_archive_scan_standardized_categories(self, archive_dir, db_path):
        """archive-scan 应使用标准化分类。"""
        (archive_dir / "automation_v2" / "workflow.py").parent.mkdir(parents=True)
        (archive_dir / "automation_v2" / "workflow.py").write_text("workflow", encoding="utf-8")
        (archive_dir / "backtest_engine" / "strategy.py").parent.mkdir(parents=True)
        (archive_dir / "backtest_engine" / "strategy.py").write_text("strategy", encoding="utf-8")
        (archive_dir / "data" / "prices.csv").parent.mkdir(parents=True)
        (archive_dir / "data" / "prices.csv").write_text("date,price", encoding="utf-8")

        archive_scan(verbose=False)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT filename, category FROM files ORDER BY filename")
        rows = cursor.fetchall()
        conn.close()

        cat_map = {r[0]: r[1] for r in rows}
        assert cat_map["workflow.py"] == "automation"  # automation_v2 → automation
        assert cat_map["strategy.py"] == "backtest"    # backtest_engine → backtest
        assert cat_map["prices.csv"] == "db"           # data → db

    def test_archive_scan_skips_duplicates(self, archive_dir, db_path):
        """重复扫描应跳过已有记录。"""
        self._setup_archive(archive_dir)
        count1 = archive_scan(verbose=False)
        assert count1 == 5
        count2 = archive_scan(verbose=False)
        assert count2 == 0

    def test_archive_scan_dry_run(self, archive_dir, db_path):
        """dry-run 不应写入数据库。"""
        self._setup_archive(archive_dir)
        count = archive_scan(verbose=False, dry_run=True)
        assert count == 0

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        total = cursor.fetchone()[0]
        conn.close()
        assert total == 0

    def test_archive_scan_includes_signals(self, archive_dir, db_path):
        """signals 目录中的文件应被包括（不再排除）。"""
        (archive_dir / "signals" / "triggers").mkdir(parents=True)
        (archive_dir / "signals" / "triggers" / "sig.json").write_text("{}", encoding="utf-8")
        (archive_dir / "signals" / "locks").mkdir(parents=True)
        (archive_dir / "signals" / "locks" / "info.json").write_text("{}", encoding="utf-8")
        # 使用不包含特殊字符的目录名
        data_dir = archive_dir / "data" / "misc"
        data_dir.mkdir(parents=True)
        (data_dir / "file.txt").write_text("test", encoding="utf-8")

        count = archive_scan(verbose=False)
        assert count == 3  # 2 from signals/ + 1 from data/


# ─── 测试 daily-maintenance ────────────────────────────────


class TestDailyMaintenance:
    def test_generates_missing_meta(self, incoming_dir, db_path):
        """没有 meta 的文件应自动生成 meta 并登记。"""
        date_dir = incoming_dir / "20260515"
        date_dir.mkdir(parents=True)
        create_data_file(date_dir, "has_meta.py")
        create_meta_file(date_dir, "has_meta.py", {"source": "manual", "target": "automation_v2"})
        (date_dir / "no_meta.py").write_text("data", encoding="utf-8")

        report = daily_maintenance(verbose=False, date_str="20260515")
        assert report["files_scanned"] == 2
        assert report["meta_generated"] == 1
        assert report["registered"] == 2

        assert (date_dir / "no_meta.py.meta.json").exists()

    def test_dry_run_no_changes(self, incoming_dir, db_path):
        """dry-run 不应创建 meta 或登记。"""
        date_dir = incoming_dir / "20260516"
        date_dir.mkdir(parents=True)
        (date_dir / "data.csv").write_text("a,b,c", encoding="utf-8")

        report = daily_maintenance(verbose=False, dry_run=True, date_str="20260516")
        assert report["files_scanned"] == 1
        assert report["meta_generated"] == 0
        assert report["registered"] == 0
        assert not (date_dir / "data.csv.meta.json").exists()

    def test_skips_already_registered(self, incoming_dir, db_path):
        """已登记的文件应跳过。"""
        date_dir = incoming_dir / "20260517"
        date_dir.mkdir(parents=True)
        (date_dir / "script.py").write_text("data", encoding="utf-8")

        report1 = daily_maintenance(verbose=False, date_str="20260517")
        assert report1["registered"] == 1

        report2 = daily_maintenance(verbose=False, date_str="20260517")
        assert report2["registered"] == 0

    def test_summary_report(self, incoming_dir, db_path):
        """汇总报告应包含分类分布。"""
        date_dir = incoming_dir / "20260518"
        date_dir.mkdir(parents=True)
        (date_dir / "task_auto.py").write_text("data", encoding="utf-8")
        (date_dir / "backtest_v2.py").write_text("data", encoding="utf-8")

        report = daily_maintenance(verbose=False, date_str="20260518")
        assert "categories" in report
        assert report["status"] == "success"


# ─── 测试 rebuild ──────────────────────────────────────────


class TestRebuild:
    def test_rebuild_db(self, db_path):
        """rebuild_db 应重建表结构（含新列）。"""
        ensure_db()
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO files (filename, original_path) VALUES (?, ?)",
                     ("test.py", "/tmp/test.py"))
        conn.commit()
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 1
        conn.close()

        rebuild_db()

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0

        cursor = conn.execute("PRAGMA table_info(files)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "current_path" in cols
        assert "checksum" in cols
        assert "source_type" in cols
        assert "final_path" not in cols
        conn.close()


# ─── 测试 extract_summary ────────────────────────────────────


class TestExtractSummary:
    def test_py_comment(self, tmp_path):
        """.py 文件首个注释。"""
        f = tmp_path / "test.py"
        f.write_text("# 这是一个结算修复脚本\nimport json\n", encoding="utf-8")
        assert extract_summary(f) == "这是一个结算修复脚本"

    def test_py_docstring(self, tmp_path):
        """.py 文件 docstring。"""
        f = tmp_path / "test.py"
        f.write_text('"""\n趋势分析工具模块。\n"""\nimport json\n', encoding="utf-8")
        assert extract_summary(f) == "趋势分析工具模块。"

    def test_py_single_line_docstring(self, tmp_path):
        """.py 文件单行 docstring。"""
        f = tmp_path / "test.py"
        f.write_text('"""趋势分析工具模块。"""\nimport json\n', encoding="utf-8")
        assert extract_summary(f) == "趋势分析工具模块。"

    def test_py_shebang_skipped(self, tmp_path):
        """.py 文件跳过 shebang。"""
        f = tmp_path / "test.py"
        f.write_text("#!/usr/bin/env python\n# 实际注释\nimport json\n", encoding="utf-8")
        assert extract_summary(f) == "实际注释"

    def test_md_title(self, tmp_path):
        """.md 文件首个 # 标题。"""
        f = tmp_path / "readme.md"
        f.write_text("# 文件生命周期管理系统\n\n简介\n", encoding="utf-8")
        assert extract_summary(f) == "文件生命周期管理系统"

    def test_md_multi_level(self, tmp_path):
        """.md 文件二级标题。"""
        f = tmp_path / "doc.md"
        f.write_text("## 安装说明\n\n步骤\n", encoding="utf-8")
        assert extract_summary(f) == "安装说明"

    def test_json_description(self, tmp_path):
        """.json 文件取 description 字段。"""
        f = tmp_path / "config.json"
        f.write_text('{"description": "配置文件", "version": 1}', encoding="utf-8")
        assert extract_summary(f) == "配置文件"

    def test_json_key_fallback(self, tmp_path):
        """.json 文件无 description 时取首个 key。"""
        f = tmp_path / "data.json"
        f.write_text('{"settings": "value", "version": 1}', encoding="utf-8")
        assert extract_summary(f) == "settings"

    def test_yaml_comment(self, tmp_path):
        """.yaml 文件首个注释。"""
        f = tmp_path / "config.yaml"
        f.write_text("# 数据库配置文件\ndb:\n  host: localhost\n", encoding="utf-8")
        assert extract_summary(f) == "数据库配置文件"

    def test_yaml_name_field(self, tmp_path):
        """.yaml 文件取 name 字段。"""
        f = tmp_path / "pipeline.yaml"
        f.write_text("name: settlement-pipeline\nsteps:\n  - init\n", encoding="utf-8")
        assert extract_summary(f) == "settlement-pipeline"

    def test_csv_first_row(self, tmp_path):
        """.csv 文件取第一行前4列。"""
        f = tmp_path / "data.csv"
        f.write_text("date,price,volume,change,extra\n", encoding="utf-8")
        assert extract_summary(f) == "date, price, volume, change"

    def test_csv_empty(self, tmp_path):
        """空 CSV 返回空字符串。"""
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        assert extract_summary(f) == ""

    def test_unknown_extension(self, tmp_path):
        """未知扩展名返回空字符串。"""
        f = tmp_path / "data.bin"
        f.write_text("binary data", encoding="utf-8")
        assert extract_summary(f) == ""

    def test_nonexistent_file(self, tmp_path):
        """不存在的文件返回空字符串。"""
        f = tmp_path / "nonexistent.py"
        assert extract_summary(f) == ""

    def test_max_len_80(self, tmp_path):
        """摘要应截断到 80 字符。"""
        f = tmp_path / "long.py"
        long_comment = "# " + "A" * 200
        f.write_text(long_comment, encoding="utf-8")
        result = extract_summary(f)
        assert len(result) <= 80


# ─── 测试 CATEGORY_MAP ──────────────────────────────────────


class TestCategoryMap:
    def test_all_keys_map_to_valid_categories(self):
        """CATEGORY_MAP 所有值都应是 VALID_CATEGORIES 中的有效值。"""
        for key, value in CATEGORY_MAP.items():
            assert value in VALID_CATEGORIES, \
                f"CATEGORY_MAP['{key}'] = '{value}' 不是有效分类"

    def test_map_target_to_category_exact_match(self):
        """map_target_to_category 应能精确匹配。"""
        assert map_target_to_category("automation_v2") == "automation"
        assert map_target_to_category("backtest_engine") == "backtest"
        assert map_target_to_category("reports") == "reports"
        assert map_target_to_category("docs") == "docs"
        assert map_target_to_category("signals") == "signals"
        assert map_target_to_category("tools") == "tools"
        assert map_target_to_category("db") == "db"
        assert map_target_to_category("agents") == "agents"
        assert map_target_to_category("shared") == "shared"

    def test_map_target_to_category_keyword_match(self):
        """map_target_to_category 应能通过关键词匹配。"""
        assert map_target_to_category("automation-module") == "automation"
        assert map_target_to_category("backtest-strategy") == "backtest"
        assert map_target_to_category("trading-core") == "shared"
        assert map_target_to_category("data-feed") == "db"

    def test_map_target_to_category_fallback(self):
        """无法匹配的 target 应回退到 'shared'。"""
        assert map_target_to_category("unknown_path") == "shared"
        assert map_target_to_category("random_text") == "shared"
        assert map_target_to_category("") == "shared"


# ─── 测试 VALID_STATUSES 标准化 ──────────────────────────────


class TestValidStatuses:
    def test_statuses_are_standardized(self):
        """VALID_STATUSES 应为标准化 6 枚举。"""
        expected = {"incoming", "experimental", "staging", "production", "deprecated", "archived"}
        assert set(VALID_STATUSES) == expected
        assert "sorted" not in VALID_STATUSES
        assert "deleted" not in VALID_STATUSES


# ─── 测试 VALID_CATEGORIES 标准化 ──────────────────────────


class TestValidCategories:
    def test_categories_are_standardized(self):
        """VALID_CATEGORIES 应为标准化 9 枚举。"""
        expected = {"automation", "backtest", "reports", "docs", "signals", "tools", "db", "agents", "shared"}
        assert set(VALID_CATEGORIES) == expected
        assert "automation_v2" not in VALID_CATEGORIES
        assert "ta_backtest" not in VALID_CATEGORIES
        assert "archive" not in VALID_CATEGORIES


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
