"""
test_incoming_meta.py — incoming_meta 单元测试

作者: moheng
创建时间: 2026-05-15
"""

import json
import sys
from pathlib import Path

# 确保能从 src/utils 导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils import incoming_meta


def _make_file(dir_path: Path, name: str, content: str = "test") -> Path:
    """在指定目录下创建测试文件。"""
    path = dir_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _redirect_incoming_base(monkeypatch, tmp_path):
    """
    将 INCOMING_BASE 重定向到 tmp_path 的父目录，
    使得 scan_directory(date_str=tmp_path.name) 映射到 tmp_path。
    """
    monkeypatch.setattr(incoming_meta, "INCOMING_BASE", tmp_path.parent)


class TestIsMetaFile:
    """测试 is_meta_file 判断逻辑。"""

    def test_meta_file_identified(self):
        assert incoming_meta.is_meta_file("foo.py.meta.json") is True
        assert incoming_meta.is_meta_file("data.csv.meta.json") is True

    def test_regular_file_not_meta(self):
        assert incoming_meta.is_meta_file("foo.py") is False
        assert incoming_meta.is_meta_file("data.csv") is False
        assert incoming_meta.is_meta_file("meta.json") is False


class TestHasMetaFile:
    """测试 has_meta_file 检测逻辑。"""

    def test_meta_exists_returns_true(self, tmp_path):
        _make_file(tmp_path, "data.csv")
        _make_file(tmp_path, "data.csv.meta.json", '{"status": "incoming"}')
        assert incoming_meta.has_meta_file(tmp_path, "data.csv") is True

    def test_meta_missing_returns_false(self, tmp_path):
        _make_file(tmp_path, "data.csv")
        assert incoming_meta.has_meta_file(tmp_path, "data.csv") is False

    def test_meta_file_itself_returns_true(self, tmp_path):
        assert incoming_meta.has_meta_file(tmp_path, "data.csv.meta.json") is True


class TestGenerateMeta:
    """测试 generate_meta 函数。"""

    def test_generates_default_meta(self, tmp_path):
        f = _make_file(tmp_path, "fix_settlement.py")
        result = incoming_meta.generate_meta(f)
        assert result is not None
        assert result.exists()
        assert result.name == "fix_settlement.py.meta.json"

        with open(result, encoding="utf-8") as fp:
            meta = json.load(fp)
        assert meta["source"] == "unknown"
        assert meta["status"] == "incoming"
        assert meta["target"] == "unassigned"
        assert meta["owner"] == "unassigned"
        assert meta["description"] == ""
        assert "created_at" in meta
        assert "20" in meta["created_at"]

    def test_skips_meta_files(self, tmp_path):
        _make_file(tmp_path, "data.csv.meta.json", '{"status": "incoming"}')
        meta_path = tmp_path / "data.csv.meta.json"
        result = incoming_meta.generate_meta(meta_path)
        assert result is None

    def test_skip_existing_without_overwrite(self, tmp_path):
        f = _make_file(tmp_path, "data.csv")
        r1 = incoming_meta.generate_meta(f)
        assert r1 is not None
        r2 = incoming_meta.generate_meta(f)
        assert r2 is None

    def test_overwrite_existing(self, tmp_path):
        f = _make_file(tmp_path, "data.csv")
        incoming_meta.generate_meta(f)
        result = incoming_meta.generate_meta(f, overwrite=True)
        assert result is not None


class TestScanDirectory:
    """测试 scan_directory 函数（需 monkeypatch INCOMING_BASE）。"""

    def test_scans_empty_directory(self, tmp_path, monkeypatch):
        _redirect_incoming_base(monkeypatch, tmp_path)
        results = incoming_meta.scan_directory(
            date_str=tmp_path.name, verbose=False
        )
        assert results == []

    def test_generates_meta_for_all_data_files(self, tmp_path, monkeypatch):
        _redirect_incoming_base(monkeypatch, tmp_path)
        _make_file(tmp_path, "fix_settlement.py")
        _make_file(tmp_path, "trade_log.csv")
        _make_file(tmp_path, "config.yaml")

        results = incoming_meta.scan_directory(
            date_str=tmp_path.name, verbose=False
        )
        assert len(results) == 3
        for r in results:
            assert r.exists()

    def test_skips_existing_meta(self, tmp_path, monkeypatch):
        _redirect_incoming_base(monkeypatch, tmp_path)
        _make_file(tmp_path, "file_a.py")
        _make_file(tmp_path, "file_a.py.meta.json", '{"status": "incoming"}')
        _make_file(tmp_path, "file_b.py")

        results = incoming_meta.scan_directory(
            date_str=tmp_path.name, verbose=False
        )
        assert len(results) == 1
        assert results[0].name == "file_b.py.meta.json"

    def test_skips_meta_files_themselves(self, tmp_path, monkeypatch):
        _redirect_incoming_base(monkeypatch, tmp_path)
        _make_file(tmp_path, "foo.py.meta.json", '{"status": "incoming"}')
        _make_file(tmp_path, "bar.py.meta.json", '{"status": "incoming"}')

        results = incoming_meta.scan_directory(
            date_str=tmp_path.name, verbose=False
        )
        assert results == []

    def test_mixed_files_respects_all_rules(self, tmp_path, monkeypatch):
        _redirect_incoming_base(monkeypatch, tmp_path)
        _make_file(tmp_path, "data.csv")
        _make_file(tmp_path, "data.csv.meta.json", '{"status": "incoming"}')
        _make_file(tmp_path, "script.py.meta.json", '{"status": "incoming"}')
        _make_file(tmp_path, "new_script.py")
        _make_file(tmp_path, "log.txt")

        results = incoming_meta.scan_directory(
            date_str=tmp_path.name, verbose=False
        )
        assert len(results) == 2
        names = {r.name for r in results}
        assert "new_script.py.meta.json" in names
        assert "log.txt.meta.json" in names

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        results = incoming_meta.scan_directory(date_str="99999999", verbose=False)
        assert results == []


class TestDefaultMeta:
    """测试默认元数据生成。"""

    def test_default_meta_has_all_fields(self):
        meta = incoming_meta.default_meta()
        assert "created_at" in meta
        assert "source" in meta
        assert "status" in meta
        assert "target" in meta
        assert "owner" in meta
        assert "description" in meta

    def test_created_at_is_formatted_correctly(self):
        meta = incoming_meta.default_meta()
        created = meta["created_at"]
        assert len(created) == 16  # "YYYY-MM-DD HH:MM"
        assert created[4] == "-"
        assert created[7] == "-"
        assert created[10] == " "
        assert created[13] == ":"


class TestDailyScan:
    """测试 daily_scan 入口函数。"""

    def test_daily_scan_called(self, tmp_path, monkeypatch):
        monkeypatch.setattr(incoming_meta, "INCOMING_BASE", tmp_path)
        today = incoming_meta.datetime.now().strftime("%Y%m%d")
        (tmp_path / today).mkdir(exist_ok=True)
        results = incoming_meta.daily_scan()
        assert results is not None
        assert isinstance(results, list)


class TestGetIncomingPath:
    """测试 get_incoming_path。"""

    def test_default_is_today(self):
        path = incoming_meta.get_incoming_path()
        today = incoming_meta.datetime.now().strftime("%Y%m%d")
        assert path.name == today

    def test_specific_date(self):
        path = incoming_meta.get_incoming_path("20260515")
        assert path.name == "20260515"
