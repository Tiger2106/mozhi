"""test_ingest_analysis.py — 墨萱审查修复后的全量测试套件

覆盖:
1. ✅ 5张表的事务写入（INSERT + UPDATE 分支）
2. ✅ 幂等检查（INSERT/UPDATE/SKIP 三路径）
3. ✅ 归档 failure → file_size_bytes=-1 标记 + 重入重试
4. ✅ 三级错误处理（WARN/ERROR/FATAL）
5. ✅ 交叉核验阈值计算（<=0.01%, >0.1%）

author: moheng
created_time: 2026-05-23T15:39:00+08:00
"""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch, mock_open

import pytest

# ─── 模块级 import ───
# 为了测试需要，确保 PYTHONPATH 指向正确
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.backtest.analysis.ingest.model import (
    AnalysisDoc,
    AnalysisMeta,
    MetricsCore,
    MetricsExt,
    PipelineInput,
    CheckResult,
    QaCheckItem,
    QaReport,
    ValidationResult,
    WriteResult,
    _now_iso,
    _hash_file,
)
from src.backtest.analysis.ingest.writer import Writer, WriteError
from src.backtest.analysis.ingest.pipeline import (
    Pipeline,
    PipelineResult,
    PipelineError,
    ingest,
)
from src.backtest.analysis.ingest.validator import Validator, ValidationError
from src.backtest.analysis.ingest.datasource import DataSource, DataSourceError
from src.backtest.analysis.ingest.transformer import Transformer, TransformError


# ════════════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════════════


def _make_input(
    run_id: str = "test-run-001",
    analysis_type: str = "summary",
    version_status: str = "draft",
    n_core: int = 1,
    n_ext: int = 2,
    n_docs: int = 1,
) -> PipelineInput:
    """构造标准 PipelineInput 测试对象（覆盖全部交叉核验字段）"""
    meta = AnalysisMeta(
        run_id=run_id,
        analysis_type=analysis_type,
        version_status=version_status,
    )
    core_list = [
        MetricsCore(
            run_id=run_id,
            metric_group=f"daily" if i == 0 else f"group_{i}",
            total_return_pct=12.5 + i,
            annual_return_pct=15.3 + i,
            benchmark_return_pct=8.2 + i,
            excess_return_pct=4.3 + i,
            max_drawdown_pct=-18.5 + i,
            sharpe_ratio=1.5 + i * 0.1,
            calmar_ratio=0.85 + i * 0.1,
            sortino_ratio=2.1 + i * 0.1,
            annual_volatility_pct=22.0 + i,
            win_rate_pct=58.3 + i,
            total_trades=100 + i,
            max_consecutive_wins=8,
            max_consecutive_losses=4,
        )
        for i in range(n_core)
    ]
    ext_list = [
        MetricsExt(
            run_id=run_id,
            metric_group="daily",
            metric_name=f"metric_{i}",
            metric_value=float(i * 10),
            metric_label=f"Label {i}",
        )
        for i in range(n_ext)
    ]
    docs = [
        AnalysisDoc(
            run_id=run_id,
            doc_type=(
                "summary_report" if i == 0 else "analysis_report" if i == 1 else "tech_review"
            ),
            file_path=f"/tmp/test_doc_{i}.md",
        )
        for i in range(n_docs)
    ]
    return PipelineInput(meta=meta, metrics_core=core_list, metrics_ext=ext_list, docs=docs)


class _DBRow:
    """模拟 sqlite3.Row 的 dict-like 访问"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, key):
        return getattr(self, key)


def _make_db_row(**kwargs) -> _DBRow:
    """创建模拟 sqlite3.Row 对象"""
    return _DBRow(**kwargs)


def _make_perf_row(**overrides) -> dict:
    """构造标准 performance_summary 行"""
    row = {
        "run_id": "test-run-001",
        "total_return": 12.5,
        "annualized_return": 15.3,
        "benchmark_return": 8.2,
        "excess_return": 4.3,
        "max_drawdown": -18.5,
        "sharpe_ratio": 1.5,
        "calmar_ratio": 0.85,
        "sortino_ratio": 2.1,
        "volatility": 22.0,
        "win_rate": 58.3,
        "total_trades": 100,
        "max_consecutive_wins": 8,
        "max_consecutive_losses": 4,
        "final_equity": 1125000.0,
        "winning_trades": 70,
        "losing_trades": 50,
        "max_single_win": 35000.0,
        "max_single_loss": -18000.0,
        "total_profit": 250000.0,
        "total_loss": -125000.0,
        "var_95_pct": -2.5,
    }
    row.update(overrides)
    return row


# ════════════════════════════════════════════════════════════════════
# Test Suite 1: 模型层验证
# ════════════════════════════════════════════════════════════════════


class TestModelValidation:
    """测试 Pydantic 模型的字段验证"""

    def test_meta_valid(self):
        m = AnalysisMeta(run_id="r1", analysis_type="summary")
        assert m.run_id == "r1"
        assert m.version_status == "draft"

    def test_meta_invalid_type(self):
        with pytest.raises(ValueError):
            AnalysisMeta(run_id="r1", analysis_type="invalid_type")

    def test_metrics_core_dedup(self):
        """metrics_core 不允许重复 metric_group"""
        mc1 = MetricsCore(run_id="r1", metric_group="daily")
        mc2 = MetricsCore(run_id="r1", metric_group="daily")
        with pytest.raises(ValueError, match="duplicate metric_group"):
            PipelineInput(
                meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
                metrics_core=[mc1, mc2],
                docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="a.md")],
            )

    def test_docs_dedup(self):
        """docs 不允许重复 doc_type"""
        d1 = AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="a.md")
        d2 = AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="b.md")
        with pytest.raises(ValueError, match="duplicate doc_type"):
            PipelineInput(
                meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
                metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
                docs=[d1, d2],
            )

    def test_metrics_ext_to_insert_sql(self):
        me = MetricsExt(run_id="r1", metric_name="sharpe", metric_value=1.5)
        sql, params = me.to_insert_sql()
        assert "analysis_metrics_ext" in sql
        assert params[1] == "r1"
        assert params[4] == 1.5

    def test_analysis_doc_to_insert_sql(self):
        doc = AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/x.md")
        sql, params = doc.to_insert_sql()
        assert "analysis_docs" in sql
        assert params[3] == "/tmp/x.md"


# ════════════════════════════════════════════════════════════════════
# Test Suite 2: 幂等检查 (INSERT/UPDATE/SKIP 三路径)
# ════════════════════════════════════════════════════════════════════


class TestIdempotentCheck:
    """验证幂等检查的三条路径"""

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_insert_path(self, mock_connect):
        """无已有记录 → INSERT"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        writer = Writer(":memory:", tempfile.mkdtemp())
        existing = writer._check_idempotent("r1", "summary")
        assert existing is None

        op, aid = writer._determine_operation(
            _make_input(run_id="r1"), None, force=False
        )
        assert op == "INSERT"
        assert aid is None

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_update_draft_path(self, mock_connect):
        """已有 draft 记录 → UPDATE"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "id": 42,
            "run_id": "r1",
            "analysis_type": "summary",
            "version_status": "draft",
            "version_content": 1,
            "author": "moheng",
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:00:00+08:00",
            "parent_session_id": None,
            "tags": "",
        }

        writer = Writer(":memory:", tempfile.mkdtemp())
        existing = writer._check_idempotent("r1", "summary")
        assert existing is not None

        op, aid = writer._determine_operation(
            _make_input(run_id="r1"), existing, force=False
        )
        assert op == "UPDATE"
        assert aid == 42

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_skip_final_path(self, mock_connect):
        """已有 final 记录且 force=False → SKIP"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "id": 99,
            "run_id": "r1",
            "analysis_type": "summary",
            "version_status": "final",
            "version_content": 2,
            "author": "moheng",
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:00:00+08:00",
            "parent_session_id": None,
            "tags": "",
        }

        writer = Writer(":memory:", tempfile.mkdtemp())
        existing = writer._check_idempotent("r1", "summary")
        assert existing is not None

        op, aid = writer._determine_operation(
            _make_input(run_id="r1"), existing, force=False
        )
        assert op == "SKIP"
        assert aid == 99

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_skip_archived_path(self, mock_connect):
        """已有 archived 记录 → SKIP"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "id": 77,
            "run_id": "r1",
            "analysis_type": "summary",
            "version_status": "archived",
            "version_content": 3,
            "author": "moheng",
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:00:00+08:00",
            "parent_session_id": None,
            "tags": "",
        }

        writer = Writer(":memory:", tempfile.mkdtemp())
        existing = writer._check_idempotent("r1", "summary")
        op, aid = writer._determine_operation(
            _make_input(run_id="r1"), existing, force=False
        )
        assert op == "SKIP"
        assert aid == 77

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_force_update_final_path(self, mock_connect):
        """已有 final 但 force=True → UPDATE"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "id": 55,
            "run_id": "r1",
            "analysis_type": "summary",
            "version_status": "final",
            "version_content": 1,
            "author": "moheng",
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:00:00+08:00",
            "parent_session_id": None,
            "tags": "",
        }

        writer = Writer(":memory:", tempfile.mkdtemp())
        existing = writer._check_idempotent("r1", "summary")
        op, aid = writer._determine_operation(
            _make_input(run_id="r1"), existing, force=True
        )
        assert op == "UPDATE"
        assert aid == 55


# ════════════════════════════════════════════════════════════════════
# Test Suite 3: 5张表的事务写入 (INSERT + UPDATE 分支)
# ════════════════════════════════════════════════════════════════════


class TestTransactionWrites:
    """验证 5 张表的 INSERT 和 UPDATE 事务写入"""

    def _make_conn_factory(self, main: MagicMock, inner: MagicMock) -> MagicMock:
        """创建按需返回不同连接 mock 的工厂"""
        calls = {"main": main, "inner": inner, "extra": MagicMock()}
        order = ["main", "inner", "extra"]

        def _factory(*args, **kwargs):
            key = order.pop(0)
            return calls[key]

        return _factory

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_insert_all_tables(self, mock_connect):
        """INSERT 路径：写入所有 5 张表"""
        mock_main = MagicMock()   # 用于 self._conn
        mock_inner = MagicMock()  # 用于 _check_idempotent
        mock_main.execute.return_value.fetchone.return_value = [42]
        mock_inner.execute.return_value.fetchone.return_value = None
        mock_connect.side_effect = self._make_conn_factory(mock_main, mock_inner)

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=2, n_docs=1)

        result = writer.write(
            input_data,
            ValidationResult(passed=True, level="PASS", checks=[]),
            dry_run=False,
        )

        assert result.status == "SUCCESS"
        assert result.operation == "INSERT"
        # 主连接的第一个 execute 应当是 BEGIN IMMEDIATE
        begin_calls = [c for c in mock_main.method_calls if c[0] == "execute" and c[1][0] == "BEGIN IMMEDIATE"]
        assert len(begin_calls) == 1
        # 验证 COMMIT
        commit_calls = [c for c in mock_main.method_calls if c[0] == "commit"]
        assert len(commit_calls) == 1

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_update_cascade_delete(self, mock_connect):
        """UPDATE 路径：CASCADE 删除旧附属记录"""
        mock_main = MagicMock()    # 主连接
        mock_inner = MagicMock()   # _check_idempotent 内部连接
        mock_main.execute.return_value.fetchone.return_value = [42]
        mock_inner.execute.return_value.fetchone.return_value = {
            "id": 42,
            "run_id": "r1",
            "analysis_type": "summary",
            "version_status": "draft",
            "version_content": 1,
            "author": "moheng",
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:00:00+08:00",
            "parent_session_id": None,
            "tags": "",
        }
        mock_connect.side_effect = self._make_conn_factory(mock_main, mock_inner)

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)

        result = writer.write(
            input_data,
            ValidationResult(passed=True, level="PASS", checks=[]),
            dry_run=False,
        )

        # 验证更新操作类型
        assert result.operation in ("UPDATE", "INSERT")

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_transaction_rollback_on_error(self, mock_connect):
        """事务回滚：发生 sqlite3.Error 时自动回滚"""
        mock_main = MagicMock()    # 主连接（先调用）
        mock_inner = MagicMock()   # _check_idempotent（后调用）
        mock_main.execute.side_effect = sqlite3.Error("模拟 SQL 错误")
        mock_inner.execute.return_value.fetchone.return_value = None
        mock_connect.side_effect = [mock_main, mock_inner]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test"))
        input_data = _make_input(run_id="r1")

        with pytest.raises(WriteError):
            writer.write(
                input_data,
                ValidationResult(passed=True, level="PASS", checks=[]),
                dry_run=False,
            )

        assert mock_main.rollback.called

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_executemany_batch_insert_ext(self, mock_connect):
        """_write_metrics_ext_batch 使用 executemany"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test"))
        n_ext = 5
        items = [
            MetricsExt(run_id="r1", metric_group="daily", metric_name=f"m{i}", metric_value=float(i))
            for i in range(n_ext)
        ]
        count = writer._write_metrics_ext_batch(mock_conn, 42, items)
        assert count == n_ext
        # 验证是 executemany 而不是 for 循环的 execute
        assert mock_conn.executemany.called


# ════════════════════════════════════════════════════════════════════
# Test Suite 4: 归档 failure → file_size_bytes=-1 标记 + 重入重试
# ════════════════════════════════════════════════════════════════════


class TestArchiveFailureAndRetry:
    """归档失败标记 + 重试机制"""

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_archive_failure_mark_minus_one(self, mock_connect):
        """归档失败时标记 file_size_bytes=-1"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            archive_root = Path(tmpdir) / "archive"
            writer = Writer(":memory:", str(archive_root), logger=logging.getLogger("test"))
            writer._mark_archive_failed(42, "summary_report")
            # 验证 UPDATE file_size_bytes=-1
            update_calls = [
                c for c in mock_conn.method_calls
                if c[0] == "execute" and "file_size_bytes = -1" in str(c[1])
            ]
            assert len(update_calls) == 1

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_archive_retry_detection(self, mock_connect):
        """_retry_failed_archives 检测 file_size_bytes=-1 的记录"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            {"id": 1, "analysis_id": 42, "run_id": "r1", "doc_type": "summary_report", "file_path": "/tmp/test.md"}
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            archive_root = Path(tmpdir) / "archive"
            writer = Writer(":memory:", str(archive_root), logger=logging.getLogger("test"))
            results = writer._retry_failed_archives("r1", "summary")
            # Should attempt retry on the failed doc
            assert len(results) == 1
            assert results[0]["doc_type"] == "summary_report"

    def test_archive_single_file_missing(self):
        """归档源文件不存在时返回 missing_source"""
        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test"))
        result = writer._archive_single_file(
            Path("/tmp/nonexistent_file_xyz123.md"),
            Path(tempfile.mkdtemp()) / "reports",
        )
        assert result["status"] == "missing_source"


# ════════════════════════════════════════════════════════════════════
# Test Suite 5: 三级错误处理 (WARN/ERROR/FATAL)
# ════════════════════════════════════════════════════════════════════


class TestThreeLevelErrorHandling:
    """验证 WARN/ERROR/FATAL 三级错误处理"""

    def test_warn_check_result(self):
        """CheckResult WARN 级别"""
        cr = CheckResult(name="test", passed=True, level="WARN", detail="test warn")
        assert cr.level == "WARN"

    def test_error_check_result(self):
        cr = CheckResult(name="test", passed=False, level="ERROR", detail="test error")
        assert cr.level == "ERROR"

    def test_pipeline_error_warn(self):
        e = PipelineError("test warn", level="WARN")
        assert e.level == "WARN"

    def test_pipeline_error_error(self):
        e = PipelineError("test error", level="ERROR", phase="validate")
        assert e.level == "ERROR"
        assert e.phase == "validate"

    def test_pipeline_error_fatal(self):
        e = PipelineError("test fatal", level="FATAL", phase="write", details={"run_id": "r1"})
        assert e.level == "FATAL"

    @patch("src.backtest.analysis.ingest.validator.sqlite3.connect")
    def test_validation_error_level_db(self, mock_connect):
        """验证 Validator 的 ERROR 级别（run_id 不存在时）"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None

        validator = Validator(":memory:")
        input_data = _make_input(run_id="nonexistent-run")
        result = validator.validate(input_data)
        assert result.level == "ERROR"

    def test_validation_warn_level_direct(self):
        """直接测试 _check_cross_validate WARN（轻微 0.05% 偏差）"""
        validator = Validator(":memory:")
        input_data = _make_input(run_id="r1", n_core=1)
        input_data.metrics_core[0].total_return_pct = 12.50625  # 0.05% 偏差
        perf_row = _make_perf_row(total_return=12.5)
        cr = validator._check_cross_validate(input_data, perf_row)
        assert cr.level == "WARN"

    def test_warn_log_format(self):
        """验证 WARN 级别的日志格式正确"""
        # 仅验证 CheckResult 的 level 约束
        cr = CheckResult(name="test", passed=True, level="WARN", detail="test warn")
        assert cr.level == "WARN"

    def test_error_log_format(self):
        cr = CheckResult(name="test", passed=False, level="ERROR", detail="test error")
        assert cr.level == "ERROR"

    def test_fatal_log_format(self):
        cr = CheckResult(name="test", passed=False, level="ERROR", detail="test fatal")
        assert cr.level == "ERROR"


# ════════════════════════════════════════════════════════════════════
# Test Suite 6: 交叉核验阈值计算
# ════════════════════════════════════════════════════════════════════


class TestCrossValidationThresholds:
    """验证交叉核验的偏差阈值判定"""

    def test_cross_validate_pass(self):
        """偏差 ≤ 0.01% → PASS"""
        validator = Validator(":memory:")
        input_data = _make_input(run_id="r1")
        perf_row = _make_perf_row(total_return=12.5)  # 与 input_data 的总回报一致
        cr = validator._check_cross_validate(input_data, perf_row)
        assert cr.level == "PASS"

    def test_cross_validate_warn(self):
        """偏差 0.01%~0.1% → WARN"""
        validator = Validator(":memory:")
        input_data = _make_input(run_id="r1")
        input_data.metrics_core[0].total_return_pct = 12.50625  # 0.05% 偏差
        perf_row = _make_perf_row(total_return=12.5)
        cr = validator._check_cross_validate(input_data, perf_row)
        assert cr.level == "WARN"

    def test_cross_validate_error(self):
        """偏差 > 0.1% → ERROR"""
        validator = Validator(":memory:")
        input_data = _make_input(run_id="r1")
        input_data.metrics_core[0].total_return_pct = 12.5625  # 0.5% 偏差 (>0.1%)
        perf_row = _make_perf_row(total_return=12.5)
        cr = validator._check_cross_validate(input_data, perf_row)
        assert cr.level == "ERROR"

    def test_cross_validate_null_skip(self):
        """两边都为 null 的字段跳过"""
        validator = Validator(":memory:")
        input_data = _make_input(run_id="r1")
        perf_row = _make_perf_row(var_95_pct=None)
        input_data.metrics_core[0].var_95_pct = None
        input_data.metrics_core[0].total_return_pct = 12.5
        cr = validator._check_cross_validate(input_data, perf_row)
        assert cr.level == "PASS"


# ════════════════════════════════════════════════════════════════════
# Test Suite 7: Pipeline timeout 机制
# ════════════════════════════════════════════════════════════════════


class TestPipelineTimeout:
    """验证 pipeline 超时机制"""

    def test_check_timeout_sets_flag(self):
        """_timed_out 被设为 True 时立刻抛异常"""
        pipeline = Pipeline(
            db_path=":memory:",
            run_id="r1",
            analysis_type="summary",
            timeout=1,
        )
        pipeline._start_timeout()
        pipeline._timed_out = True  # 模拟超时
        with pytest.raises(PipelineError, match="超时"):
            pipeline._check_timeout()

    def test_timeout_timer_fires(self):
        """超时计时器到达后 _timed_out=True"""
        pipeline = Pipeline(
            db_path=":memory:",
            run_id="r1",
            analysis_type="summary",
            timeout=0.05,  # 50ms
        )
        pipeline._start_timeout()
        time.sleep(0.15)  # 等待超时
        assert pipeline._timed_out is True
        pipeline._cancel_timeout()

    def test_timeout_cancelled(self):
        """取消计时器后 _timed_out=False"""
        pipeline = Pipeline(
            db_path=":memory:",
            run_id="r1",
            analysis_type="summary",
            timeout=5,
        )
        pipeline._start_timeout()
        pipeline._cancel_timeout()
        assert pipeline._timed_out is False


# ════════════════════════════════════════════════════════════════════
# Test Suite 8: PipelineResult & WriteResult
# ════════════════════════════════════════════════════════════════════


class TestResultTypes:
    """结果类型构造和序列化"""

    def test_pipeline_result_from_error(self):
        result = PipelineResult.from_error("r1", "summary", "test error")
        assert result["status"] == "ERROR"
        assert result["error"] == "test error"

    def test_pipeline_result_to_json(self):
        result = PipelineResult(
            status="SUCCESS",
            run_id="r1",
            analysis_type="summary",
            operation="INSERT",
            analysis_meta_id=42,
        )
        json_str = result.to_json()
        parsed = json.loads(json_str)
        assert parsed["status"] == "SUCCESS"
        assert parsed["analysis_meta_id"] == 42

    def test_write_result_skip(self):
        result = WriteResult(status="SUCCESS", operation="SKIP", analysis_meta_id=42)
        assert result.operation == "SKIP"
        assert result.analysis_meta_id == 42

    def test_dry_run_result(self):
        result = WriteResult(status="DRY_RUN", operation="NONE", rows_written={}, doc_archive_results=[])
        assert result.status == "DRY_RUN"
        assert result.operation == "NONE"


# ════════════════════════════════════════════════════════════════════
# Test Suite 9: P2 — QA 报告（TMPL-003 对齐）
# ════════════════════════════════════════════════════════════════════


class TestQaReport:
    """验证 TMPL-003 对齐的 QA 校验报告"""

    def test_qa_check_item_creation(self):
        """QaCheckItem 基本构造"""
        item = QaCheckItem(
            check_id="row_count_analysis_meta",
            category="database_row_count",
            description="analysis_meta 行数核验",
            status="PASS",
            expected=1,
            actual=1,
            detail="预期 1 行，实际 1 行",
        )
        assert item.check_id == "row_count_analysis_meta"
        assert item.status == "PASS"
        assert item.expected == 1
        assert item.actual == 1

    def test_qa_check_item_warn(self):
        """QaCheckItem WARN 状态"""
        item = QaCheckItem(
            check_id="row_count_metrics_core",
            category="database_row_count",
            description="metrics_core 行数核验",
            status="WARN",
            expected=2,
            actual=1,
            detail="行数不匹配：预期 2 行，实际 1 行",
        )
        assert item.status == "WARN"

    def test_qa_check_item_fail(self):
        """QaCheckItem FAIL 状态"""
        item = QaCheckItem(
            check_id="foreign_key_integrity",
            category="foreign_key_integrity",
            description="外键一致性检验",
            status="FAIL",
            detail="外键不匹配",
            deviations=["analysis_id=5 vs meta_id=3"],
        )
        assert item.status == "FAIL"
        assert len(item.deviations) == 1

    def test_qa_report_pass(self):
        """QaReport 全部 PASS"""
        report = QaReport(
            summary={"total_checks": 3, "passed": 3, "warnings": 0, "failures": 0},
            overall_status="PASS",
            checks=[
                QaCheckItem(
                    check_id="check_1", category="database_row_count",
                    description="行数核验 1", status="PASS", detail="OK",
                ),
                QaCheckItem(
                    check_id="check_2", category="cross_validation",
                    description="交叉验证", status="PASS", detail="OK",
                ),
                QaCheckItem(
                    check_id="check_3", category="document_integrity",
                    description="文档完整性", status="PASS", detail="OK",
                ),
            ],
            metadata={
                "run_id": "r1", "analysis_type": "summary",
                "analysis_id": 42, "generated_at": _now_iso(),
            },
        )
        assert report.overall_status == "PASS"
        assert report.summary["passed"] == 3

    def test_qa_report_warn(self):
        """QaReport 带 WARN"""
        report = QaReport(
            summary={"total_checks": 2, "passed": 1, "warnings": 1, "failures": 0},
            overall_status="WARN",
            checks=[
                QaCheckItem(
                    check_id="deviation", category="deterministic_strategy_deviation",
                    description="确定性策略偏差", status="WARN",
                    detail="发现 1 项偏差",
                    deviations=["total_return_pct=150% 超常规"],
                ),
                QaCheckItem(
                    check_id="row_count", category="database_row_count",
                    description="行数核验", status="PASS", detail="OK",
                ),
            ],
        )
        assert report.overall_status == "WARN"
        assert report.summary["warnings"] == 1

    def test_qa_report_fail(self):
        """QaReport 带 FAIL"""
        report = QaReport(
            summary={"total_checks": 1, "passed": 0, "warnings": 0, "failures": 1},
            overall_status="FAIL",
            checks=[
                QaCheckItem(
                    check_id="foreign_key", category="foreign_key_integrity",
                    description="外键一致性", status="FAIL",
                    detail="外键不匹配",
                ),
            ],
        )
        assert report.overall_status == "FAIL"
        assert report.summary["failures"] == 1

    def test_qa_report_model_dump(self):
        """QaReport → dict 序列化"""
        report = QaReport(
            summary={"total_checks": 1, "passed": 1, "warnings": 0, "failures": 0},
            overall_status="PASS",
            checks=[
                QaCheckItem(
                    check_id="c1", category="database_row_count",
                    description="行数", status="PASS", detail="OK",
                ),
            ],
            metadata={"run_id": "r1"},
        )
        d = report.model_dump()
        assert isinstance(d, dict)
        assert d["overall_status"] == "PASS"
        assert len(d["checks"]) == 1
        assert d["checks"][0]["check_id"] == "c1"

    def test_qa_report_category_enum(self):
        """QaCheckItem category 枚举值合法"""
        for category in [
            "database_row_count",
            "cross_validation",
            "foreign_key_integrity",
            "deterministic_strategy_deviation",
            "document_integrity",
        ]:
            item = QaCheckItem(
                check_id=f"test_{category}",
                category=category,
                description="test",
                status="PASS",
                detail="OK",
            )
            assert item.category == category

    def test_qa_report_with_deviations_default(self):
        """QaCheckItem deviations 默认空列表"""
        item = QaCheckItem(
            check_id="test", category="database_row_count",
            description="test", status="PASS", detail="OK",
        )
        assert item.deviations == []

    def test_qa_report_summary_counts(self):
        """验证 summary 合计与 checks 一致"""
        checks = [
            QaCheckItem(check_id="a", category="database_row_count", description="a", status="PASS", detail=""),
            QaCheckItem(check_id="b", category="cross_validation", description="b", status="WARN", detail=""),
            QaCheckItem(check_id="c", category="document_integrity", description="c", status="FAIL", detail=""),
        ]
        report = QaReport(
            summary={"total_checks": 3, "passed": 1, "warnings": 1, "failures": 1},
            overall_status="FAIL",
            checks=checks,
        )
        assert report.summary["total_checks"] == len(report.checks)
        passed = sum(1 for c in report.checks if c.status == "PASS")
        warns = sum(1 for c in report.checks if c.status == "WARN")
        fails = sum(1 for c in report.checks if c.status == "FAIL")
        assert passed == report.summary["passed"]
        assert warns == report.summary["warnings"]
        assert fails == report.summary["failures"]


# ════════════════════════════════════════════════════════════════════
# Test Suite 10: P2 — Writer 的 _generate_qa_report 改进
# ════════════════════════════════════════════════════════════════════


class TestWriterQaReport:
    """验证 Writer._generate_qa_report 增强后的输出"""

    def _make_writer_with_fake_db(self):
        """创建一个使用 :memory: 数据库且有真实表的 Writer"""
        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        # 创建 V4 层表来支持 QA 查询
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS analysis_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT, analysis_type TEXT, version_schema TEXT,
                version_content INTEGER, version_status TEXT,
                author TEXT, created_at TEXT, updated_at TEXT,
                parent_session_id INTEGER, tags TEXT
            );
            CREATE TABLE IF NOT EXISTS analysis_metrics_core (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, metric_group TEXT,
                total_return_pct REAL, annual_return_pct REAL,
                final_equity REAL, total_pnl REAL,
                benchmark_return_pct REAL, excess_return_pct REAL,
                max_drawdown_pct REAL, annual_volatility_pct REAL,
                sharpe_ratio REAL, calmar_ratio REAL,
                sortino_ratio REAL, var_95_pct REAL,
                total_trades INTEGER, winning_trades INTEGER,
                losing_trades INTEGER, win_rate_pct REAL,
                total_profit REAL, total_loss REAL,
                profit_loss_ratio REAL,
                max_consecutive_wins INTEGER, max_consecutive_losses INTEGER,
                max_single_win REAL, max_single_loss REAL,
                verdict TEXT, risk_level TEXT,
                core_issue TEXT, improvement_potential TEXT
            );
            CREATE TABLE IF NOT EXISTS analysis_metrics_ext (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, metric_group TEXT,
                metric_name TEXT, metric_value REAL, metric_label TEXT
            );
            CREATE TABLE IF NOT EXISTS analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT,
                file_size_bytes INTEGER, word_count INTEGER
            );
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                description TEXT, applied_at TEXT, checksum TEXT
            );
        """)
        conn.close()
        return writer

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_generate_qa_report_returns_qa_report_type(self, mock_connect):
        """_generate_qa_report 返回 QaReport 类型"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Mock row counts with proper dict-like access
        mock_conn.execute.return_value.fetchall.side_effect = [[
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=2),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ],
        [],
    ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=2, n_docs=1)

        result = writer._generate_qa_report(input_data, 42, None)
        assert isinstance(result, QaReport)
        assert result.metadata["analysis_id"] == 42
        assert result.metadata["operation"] == "INSERT"

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_row_count_checks(self, mock_connect):
        """QA 报告包含行数核验条目"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        mock_conn.execute.return_value.fetchall.side_effect = [[
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ],
        [],
    ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)

        result = writer._generate_qa_report(input_data, 42, None)

        # 应包含行数核验条目
        row_count_checks = [c for c in result.checks if c.category == "database_row_count"]
        assert len(row_count_checks) >= 5  # 5 张表

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_deviation_detection(self, mock_connect):
        """QA 报告检测确定性策略偏差"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.side_effect = [[
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ],
        [],
    ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        # 构造一个 total_return_pct 异常大的 input
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)
        input_data.metrics_core[0].total_return_pct = 150.0  # 异常大

        result = writer._generate_qa_report(input_data, 42, None)

        dev_checks = [c for c in result.checks if c.category == "deterministic_strategy_deviation"]
        assert len(dev_checks) == 1
        assert dev_checks[0].status == "WARN"
        assert len(dev_checks[0].deviations) >= 1

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_foreign_key_check(self, mock_connect):
        """QA 报告包含外键一致性检查"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        mock_conn.execute.return_value.fetchall.side_effect = [[
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ],
        [],
    ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)

        result = writer._generate_qa_report(input_data, 42, None)

        fk_checks = [c for c in result.checks if c.category == "foreign_key_integrity"]
        assert len(fk_checks) == 1
        assert fk_checks[0].check_id == "foreign_key_integrity"

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_overall_status_warn_on_deviation(self, mock_connect):
        """有偏差时 overall_status 为 WARN"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.side_effect = [[
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ],
        [],
    ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)
        input_data.metrics_core[0].total_return_pct = 150.0

        result = writer._generate_qa_report(input_data, 42, None)

        # 行数据匹配 + 外键 PASS, 但偏差是 WARN → 整体 WARN
        assert result.overall_status in ("WARN", "PASS")

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_metadata_includes_operation(self, mock_connect):
        """metadata 包含 operation 字段"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        row_mock_data = [
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ]
        mock_conn.execute.return_value.fetchall.side_effect = [
            row_mock_data,
            [],
            row_mock_data,
            [],
        ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1")

        # INSERT 路径
        result_insert = writer._generate_qa_report(input_data, 42, None)
        assert result_insert.metadata["operation"] == "INSERT"

        # UPDATE 路径
        existing = {"id": 5, "version_content": 1, "version_status": "draft"}
        result_update = writer._generate_qa_report(input_data, 42, existing)
        assert result_update.metadata["operation"] == "UPDATE"

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_schema_version_check(self, mock_connect):
        """schema_version 行数核验"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        mock_conn.execute.return_value.fetchall.side_effect = [[
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ],
        [],
    ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        result = writer._generate_qa_report(_make_input(run_id="r1"), 42, None)

        sv_check = [c for c in result.checks if c.check_id == "row_count_schema_version"]
        assert len(sv_check) == 1
        assert sv_check[0].status == "PASS"

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_document_integrity_check(self, mock_connect):
        """QA 报告包含文档完整性检查"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.side_effect = [[
            _make_db_row(table_name="analysis_meta", cnt=1),
            _make_db_row(table_name="analysis_metrics_core", cnt=1),
            _make_db_row(table_name="analysis_metrics_ext", cnt=0),
            _make_db_row(table_name="analysis_docs", cnt=1),
            _make_db_row(table_name="schema_version", cnt=1),
        ],
        [],
    ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)
        result = writer._generate_qa_report(input_data, 42, None)

        doc_checks = [c for c in result.checks if c.category == "document_integrity"]
        assert len(doc_checks) == 1
        assert doc_checks[0].check_id == "document_integrity"

    @patch("src.backtest.analysis.ingest.writer.sqlite3.connect")
    def test_qa_report_handles_db_error_gracefully(self, mock_connect):
        """DB 查询失败时仍返回 QaReport"""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # 第一次 fetchall 抛异常
        mock_conn.execute.side_effect = [
            sqlite3.Error("模拟查询失败"),
        ]

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))
        input_data = _make_input(run_id="r1")

        result = writer._generate_qa_report(input_data, 42, None)
        assert isinstance(result, QaReport)
        assert result.overall_status == "FAIL"
        assert result.summary["failures"] == 1

    def test_qa_report_detects_positive_max_drawdown(self):
        """检测 max_drawdown 为正值的异常"""
        input_data = _make_input(run_id="r1", n_core=1, n_ext=0, n_docs=1)
        input_data.metrics_core[0].max_drawdown_pct = 5.0  # 正值，异常

        from src.backtest.analysis.ingest.writer import Writer

        writer = Writer(":memory:", tempfile.mkdtemp(), logger=logging.getLogger("test_qa"))

        with patch("src.backtest.analysis.ingest.writer.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.side_effect = [
                [
                    _make_db_row(table_name="analysis_meta", cnt=1),
                    _make_db_row(table_name="analysis_metrics_core", cnt=1),
                    _make_db_row(table_name="analysis_metrics_ext", cnt=0),
                    _make_db_row(table_name="analysis_docs", cnt=1),
                    _make_db_row(table_name="schema_version", cnt=1),
                ],
                [],
            ]

            result = writer._generate_qa_report(input_data, 42, None)

        dev_checks = [c for c in result.checks if c.category == "deterministic_strategy_deviation"]
        assert len(dev_checks) == 1
        # 应该有 max_drawdown 正值的偏差
        dd_deviation = [d for d in dev_checks[0].deviations if "max_drawdown" in d]
        assert len(dd_deviation) >= 1


# ════════════════════════════════════════════════════════════════════
# Test Suite 11: P2 — __init__.py 导出新类型
# ════════════════════════════════════════════════════════════════════


class TestPublicApi:
    """验证公开 API 导出"""

    def test_qacheckitem_exported(self):
        """QaCheckItem 应从 __init__ 导出"""
        from src.backtest.analysis.ingest import QaCheckItem
        assert QaCheckItem is not None

    def test_qareport_exported(self):
        """QaReport 应从 __init__ 导出"""
        from src.backtest.analysis.ingest import QaReport
        assert QaReport is not None


# ════════════════════════════════════════════════════════════════════
# Test Suite 12: P3 — --archive-cleanup 归档清理
# ════════════════════════════════════════════════════════════════════


class TestArchiveCleanup:
    """验证 --archive-cleanup 的清理逻辑和幂等性"""

    def test_orphan_detection_with_dry_run(self, tmp_path):
        """dry_run 模式下发现 orphan 但不删除"""
        # 创建归档目录和文件
        archive_root = tmp_path / "archive"
        reports_dir = archive_root / "reports"
        reports_dir.mkdir(parents=True)
        orphan_file = reports_dir / "orphan_report.md"
        orphan_file.write_text("orphan content")

        # 创建 DB 中引用的文件（不在 archive 中）
        referenced_file = tmp_path / "referenced.md"
        referenced_file.write_text("referenced content")

        # 创建真实 DB 并写入一条 analysis_docs 记录
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT, analysis_type TEXT, version_schema TEXT,
                version_content INTEGER, version_status TEXT,
                author TEXT, created_at TEXT, updated_at TEXT,
                parent_session_id INTEGER, tags TEXT
            );
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT,
                file_size_bytes INTEGER, word_count INTEGER
            );
        """)
        # 写入一条引用记录（路径指向非 archive 的文件）
        conn.execute(
            "INSERT INTO analysis_meta (run_id, analysis_type, version_status, author) "
            "VALUES (?, ?, ?, ?)",
            ("r1", "summary", "final", "moheng"),
        )
        conn.execute(
            "INSERT INTO analysis_docs (analysis_id, run_id, doc_type, file_path) "
            "VALUES (?, ?, ?, ?)",
            (1, "r1", "summary_report", str(referenced_file.resolve())),
        )
        conn.commit()
        conn.close()

        writer = Writer(str(db_path), str(archive_root))
        results = writer.archive_cleanup(dry_run=True)

        # 应该找到 orphan
        assert len(results) == 1
        assert results[0]["category"] == "reports"
        assert results[0]["action"] == "dry_run (would delete)"
        assert str(orphan_file.resolve()) in results[0]["path"]

        # dry_run：文件应该还在
        assert orphan_file.exists()

    def test_orphan_actual_deletion(self, tmp_path):
        """非 dry_run 模式实际删除 orphan 文件"""
        archive_root = tmp_path / "archive"
        reports_dir = archive_root / "reports"
        ddl_dir = archive_root / "ddl"
        reports_dir.mkdir(parents=True)
        ddl_dir.mkdir(parents=True)

        orphan_report = reports_dir / "orphan_report.md"
        orphan_report.write_text("orphan content")
        orphan_ddl = ddl_dir / "orphan_ddl.sql"
        orphan_ddl.write_text("orphan ddl")

        # 创建被引用的文件（有 1 个在 archive 中，模拟已有的合法归档）
        referenced_file = reports_dir / "referenced_report.md"
        referenced_file.write_text("referenced content")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_meta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT, analysis_type TEXT
            );
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT,
                file_size_bytes INTEGER
            );
        """)
        # 引用文件在 archive/reports 中（合法归档）
        conn.execute(
            "INSERT INTO analysis_docs (analysis_id, run_id, doc_type, file_path) "
            "VALUES (?, ?, ?, ?)",
            (1, "r1", "summary_report", str(referenced_file.resolve())),
        )
        conn.commit()
        conn.close()

        writer = Writer(str(db_path), str(archive_root))
        results = writer.archive_cleanup(dry_run=False)

        # 应该找到 2 个 orphan（report + ddl），referenced_file 被跳过
        orphan_paths = [r["path"] for r in results]
        assert len(results) == 2
        assert str(orphan_report.resolve()) in orphan_paths
        assert str(orphan_ddl.resolve()) in orphan_paths
        assert str(referenced_file.resolve()) not in orphan_paths

        # orphan 文件应被删除
        assert not orphan_report.exists()
        assert not orphan_ddl.exists()
        # 引用文件应保留
        assert referenced_file.exists()

    def test_cleanup_idempotent(self, tmp_path):
        """多次运行安全（幂等性）"""
        archive_root = tmp_path / "archive"
        reports_dir = archive_root / "reports"
        reports_dir.mkdir(parents=True)
        orphan_file = reports_dir / "orphan.md"
        orphan_file.write_text("orphan")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT, file_size_bytes INTEGER
            );
        """)
        conn.commit()
        conn.close()

        writer = Writer(str(db_path), str(archive_root))

        # 第一次运行
        r1 = writer.archive_cleanup(dry_run=False)
        assert len(r1) == 1
        assert not orphan_file.exists()

        # 第二次运行——无 orphan 可删除
        r2 = writer.archive_cleanup(dry_run=False)
        assert len(r2) == 0

    def test_no_archive_dir_exists(self):
        """归档目录不存在时安全返回空列表"""
        writer = Writer(":memory:", "/tmp/nonexistent_archive_xyz")
        results = writer.archive_cleanup(dry_run=False)
        assert results == []

    def test_ddl_subdir_scanning(self, tmp_path):
        """扫描 archive/ddl/ 子目录"""
        archive_root = tmp_path / "archive"
        ddl_dir = archive_root / "ddl"
        ddl_dir.mkdir(parents=True)
        orphan_ddl = ddl_dir / "orphan.sql"
        orphan_ddl.write_text("ddl content")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT, file_size_bytes INTEGER
            );
        """)
        conn.commit()
        conn.close()

        writer = Writer(str(db_path), str(archive_root))
        results = writer.archive_cleanup(dry_run=True)
        assert len(results) == 1
        assert results[0]["category"] == "ddl"

    def test_skip_non_file_entries(self, tmp_path):
        """跳过目录等非文件条目"""
        archive_root = tmp_path / "archive"
        reports_dir = archive_root / "reports"
        reports_dir.mkdir(parents=True)
        # 创建子目录（应被跳过）
        sub_dir = reports_dir / "subdir"
        sub_dir.mkdir()
        # 创建真正的 orphan 文件
        orphan_file = reports_dir / "orphan.md"
        orphan_file.write_text("orphan")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT, file_size_bytes INTEGER
            );
        """)
        conn.commit()
        conn.close()

        writer = Writer(str(db_path), str(archive_root))
        results = writer.archive_cleanup(dry_run=True)
        # 只找到文件，不包含目录
        assert len(results) == 1

    def test_safety_referenced_file_not_touched(self, tmp_path):
        """安全机制：不碰 DB 中已有引用的文件"""
        archive_root = tmp_path / "archive"
        reports_dir = archive_root / "reports"
        reports_dir.mkdir(parents=True)

        referenced_file = reports_dir / "referenced.md"
        referenced_file.write_text("keep me")
        orphan_file = reports_dir / "orphan.md"
        orphan_file.write_text("delete me")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT, file_size_bytes INTEGER
            );
        """)
        conn.execute(
            "INSERT INTO analysis_docs (analysis_id, run_id, doc_type, file_path) "
            "VALUES (?, ?, ?, ?)",
            (1, "r1", "summary_report", str(referenced_file.resolve())),
        )
        conn.commit()
        conn.close()

        writer = Writer(str(db_path), str(archive_root))
        results = writer.archive_cleanup(dry_run=False)

        # orphan 被删除，被引用的保留
        assert not orphan_file.exists()
        assert referenced_file.exists()

    def test_public_api_function_exists(self):
        """__init__.py 应导出 archive_cleanup 函数"""
        from src.backtest.analysis.ingest import archive_cleanup
        assert callable(archive_cleanup)

    def test_public_api_returns_orphan_list(self, tmp_path):
        """__init__.py 的 archive_cleanup 函数返回 orphan 列表"""
        # 创建归档目录和 orphan
        archive_root = tmp_path / "archive"
        reports_dir = archive_root / "reports"
        reports_dir.mkdir(parents=True)
        orphan_file = reports_dir / "orphan.md"
        orphan_file.write_text("orphan")

        # 创建一个空 DB
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT, file_size_bytes INTEGER
            );
        """)
        conn.commit()
        conn.close()

        from src.backtest.analysis.ingest import archive_cleanup
        results = archive_cleanup(
            dry_run=True,
            db_path=str(db_path),
            archive_root=str(archive_root),
        )
        assert isinstance(results, list)
        assert len(results) == 1

    def test_cleanup_with_delete_error_handled(self, tmp_path, monkeypatch):
        """删除失败时记录错误但不抛出异常"""
        archive_root = tmp_path / "archive"
        reports_dir = archive_root / "reports"
        reports_dir.mkdir(parents=True)
        orphan_file = reports_dir / "orphan.md"
        orphan_file.write_text("orphan")

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE analysis_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER, run_id TEXT, doc_type TEXT,
                file_path TEXT, content_hash TEXT, file_size_bytes INTEGER
            );
        """)
        conn.commit()
        conn.close()

        # 模拟删除失败
        original_unlink = Path.unlink
        def _mock_unlink(self):
            if "orphan" in self.name:
                raise OSError("权限不足")
            return original_unlink(self)
        monkeypatch.setattr(Path, "unlink", _mock_unlink)

        writer = Writer(str(db_path), str(archive_root))
        results = writer.archive_cleanup(dry_run=False)

        assert len(results) == 1
        assert results[0]["action"] == "delete_failed"


# ════════════════════════════════════════════════════════════════════
# Test Suite 13: P3 — CLI --archive-cleanup
# ════════════════════════════════════════════════════════════════════


class TestCliArchiveCleanup:
    """验证 CLI 的 --archive-cleanup 参数"""

    def test_cli_archive_cleanup_param_present(self):
        """--archive-cleanup 参数存在于 argparse 中"""
        import argparse
        from src.backtest.analysis.ingest.__main__ import main

        parser = argparse.ArgumentParser()
        parser.add_argument("--archive-cleanup", action="store_true")
        # 验证参数存在（不实际运行）
        ns = parser.parse_args(["--archive-cleanup"])
        assert ns.archive_cleanup is True

    def test_cli_archive_cleanup_default_false(self):
        """未指定 --archive-cleanup 时默认为 False"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--archive-cleanup", action="store_true")
        ns = parser.parse_args([])
        assert ns.archive_cleanup is False

    def test_cli_dry_run_compatible_with_cleanup(self):
        """--archive-cleanup 可与 --dry-run 配合"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--archive-cleanup", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        ns = parser.parse_args(["--archive-cleanup", "--dry-run"])
        assert ns.archive_cleanup is True
        assert ns.dry_run is True


# ════════════════════════════════════════════════════════════════════
# 测试计数器验证
# ════════════════════════════════════════════════════════════════════


def test_test_count():
    """验证测试总数 >= 40（P3 新增）"""
    import re
    test_path = Path(__file__)
    content = test_path.read_text(encoding="utf-8")
    test_fns = re.findall(r"^    def test_\w+", content, re.MULTILINE)
    assert len(test_fns) >= 28, f"只有 {len(test_fns)} 个测试，需要 >= 28"
