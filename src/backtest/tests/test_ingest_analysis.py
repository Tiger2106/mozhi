"""test_ingest_analysis.py — 单元测试

覆盖率:
- 每个模块的可导入性 (已完成)
- model.py: PipelineInput Pydantic 校验
- transformer.py: 字段映射 + DataSourceError
- validator.py: 各检查项
- writer.py: 幂等判定表
- pipeline.py: Pipeline.run() 测试模式
"""

from __future__ import annotations

import os
import tempfile

import pytest

from src.backtest.analysis.ingest.model import (
    AnalysisDoc,
    AnalysisMeta,
    MetricsCore,
    MetricsExt,
    PipelineInput,
    WriteResult,
    _hash_file,
    _now_iso,
)
from src.backtest.analysis.ingest.pipeline import PipelineResult


# ==================== model.py ====================


class TestModel:
    """model.py: Pydantic 模型校验"""

    def test_analysis_meta_defaults(self):
        meta = AnalysisMeta(run_id="test-run-1", analysis_type="summary")
        assert meta.author == "moheng"
        assert meta.version_schema == "1.0"
        assert meta.version_content == 1
        assert meta.version_status == "draft"

    def test_analysis_meta_insert_sql(self):
        meta = AnalysisMeta(run_id="test-run-1", analysis_type="summary")
        sql, params = meta.meta_to_insert_sql()
        assert "INSERT INTO analysis_meta" in sql
        assert len(params) == 10
        assert params[0] == "test-run-1"

    def test_metrics_core_to_insert_sql(self):
        mc = MetricsCore(run_id="test-run-1", total_return_pct=0.12, sharpe_ratio=1.5)
        sql, params = mc.to_insert_sql()
        assert "INSERT INTO analysis_metrics_core" in sql
        assert len(params) == 30

    def test_pipeline_input_dedup_metrics_core(self):
        """重复 metric_group 应抛出 ValueError"""
        mc1 = MetricsCore(run_id="r1", metric_group="daily")
        mc2 = MetricsCore(run_id="r1", metric_group="daily")
        with pytest.raises(ValueError):
            PipelineInput(
                meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
                metrics_core=[mc1, mc2],
                docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
            )

    def test_pipeline_input_dedup_docs(self):
        """重复 doc_type 应抛出 ValueError"""
        doc1 = AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")
        doc2 = AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/b.md")
        with pytest.raises(ValueError):
            PipelineInput(
                meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
                metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
                docs=[doc1, doc2],
            )

    def test_model_to_update_sql(self):
        meta = AnalysisMeta(run_id="r1", analysis_type="summary")
        sql, params = meta.meta_to_update_sql(meta_id=42)
        assert "UPDATE analysis_meta" in sql
        assert params[-1] == 42  # WHERE id = ?

    def test_now_iso_format(self):
        ts = _now_iso()
        assert "+08" in ts or "+0800" in ts
        assert "T" in ts
        assert len(ts) >= 19

    def test_hash_file(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
            f.write("hello world")
            tmp = f.name
        try:
            h = _hash_file(tmp)
            assert isinstance(h, str)
            assert len(h) == 64  # SHA256 hex
            assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        finally:
            os.unlink(tmp)

    def test_metrics_ext_to_insert_sql(self):
        me = MetricsExt(run_id="r1", metric_name="test_metric", metric_value=1.5)
        sql, params = me.to_insert_sql()
        assert "INSERT INTO analysis_metrics_ext" in sql
        assert params[3] == "test_metric"
        assert params[4] == 1.5

    def test_analysis_doc_to_insert_sql(self):
        doc = AnalysisDoc(
            run_id="r1", doc_type="summary_report", file_path="/tmp/test.md",
            content_hash="abc123", file_size_bytes=1024,
        )
        sql, params = doc.to_insert_sql()
        assert "INSERT INTO analysis_docs" in sql
        assert params[2] == "summary_report"
        assert params[5] == 1024

    def test_write_result_defaults(self):
        wr = WriteResult(status="SUCCESS", operation="INSERT")
        assert wr.rows_written == {}
        assert wr.doc_archive_results == []
        assert wr.qa_report is None

    def test_pipeline_input_validation(self):
        """最小有效输入"""
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        assert pi.meta.run_id == "r1"
        assert len(pi.metrics_core) == 1
        assert len(pi.docs) == 1
        assert pi.metrics_ext == []


# ==================== transformer.py ====================


class TestTransformer:
    """transformer.py: 字段映射"""

    def test_map_perf_to_metrics_core(self, tmp_path):
        from src.backtest.analysis.ingest.transformer import Transformer
        db = tmp_path / "test.db"
        db.write_text("")
        t = Transformer(str(db))
        perf_row = {
            "run_id": "test-run-1",
            "total_return": 0.15,
            "annualized_return": 0.12,
            "benchmark_return": 0.05,
            "excess_return": 0.07,
            "max_drawdown": -0.20,
            "sharpe_ratio": 1.5,
            "calmar_ratio": 0.75,
            "sortino_ratio": 1.2,
            "volatility": 0.25,
            "var_95_pct": -0.03,
            "win_rate": 0.55,
            "total_trades": 100,
            "winning_trades": 55,
            "losing_trades": 45,
            "max_consecutive_wins": 5,
            "max_consecutive_losses": 3,
            "final_equity": 1150000.0,
            "total_profit": 300000.0,
            "total_loss": -150000.0,
            "max_single_win": 50000.0,
            "max_single_loss": -25000.0,
        }
        mc = t._map_perf_to_metrics_core(perf_row, initial_capital=1000000.0)
        assert mc.total_return_pct == 0.15
        assert mc.sharpe_ratio == 1.5
        assert mc.max_drawdown_pct == -0.20
        assert mc.total_trades == 100
        assert mc.total_pnl == 150000.0  # final_equity - initial_capital
        assert mc.win_rate_pct == 0.55
        assert mc.profit_loss_ratio is None

    def test_transform_raises_on_none_perf(self, tmp_path):
        from src.backtest.analysis.ingest.transformer import Transformer
        from src.backtest.analysis.ingest.datasource import DataSourceError
        db = tmp_path / "test.db"
        db.write_text("")
        t = Transformer(str(db))
        with pytest.raises(DataSourceError, match="未找到 performance_summary"):
            t.transform("test-run-1", "summary", perf_row=None)

    def test_transform_with_doc_files(self, tmp_path):
        from src.backtest.analysis.ingest.transformer import Transformer
        db = tmp_path / "test.db"
        db.write_text("")
        t = Transformer(str(db))
        doc_file = tmp_path / "reports" / "summary_test-run-1.md"
        doc_file.parent.mkdir(parents=True)
        doc_file.write_text("# Summary Report")
        perf_row = {"run_id": "test-run-1", "total_return": 0.1, "final_equity": 1100000}
        pi = t.transform(
            "test-run-1", "summary",
            perf_row=perf_row,
            doc_files=[{
                "doc_type": "summary_report",
                "file_path": str(doc_file),
                "content_hash": "",
                "file_size_bytes": 0,
            }],
            initial_capital=1000000.0,
        )
        assert pi.meta.analysis_type == "summary"
        assert len(pi.metrics_core) == 1
        assert pi.metrics_core[0].total_return_pct == 0.1
        assert len(pi.docs) == 1
        assert pi.docs[0].doc_type == "summary_report"

    def test_to_float_and_int(self):
        from src.backtest.analysis.ingest.transformer import _to_float, _to_int
        assert _to_float("0.15") == 0.15
        assert _to_float(None) is None
        assert _to_float("abc") is None
        assert _to_int("100") == 100
        assert _to_int(None) is None


# ==================== validator.py ====================


class TestValidator:
    """validator.py: 校验逻辑"""

    def test_check_run_id_exists_missing(self, tmp_path):
        from src.backtest.analysis.ingest.validator import Validator
        import sqlite3
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE backtest_run (id TEXT, run_name TEXT, status TEXT)")
        conn.commit()
        conn.close()
        v = Validator(str(db))
        cr = v._check_run_id_exists("nonexistent-id")
        assert not cr.passed
        assert cr.level == "ERROR"

    def test_check_run_id_exists_ok(self, tmp_path):
        from src.backtest.analysis.ingest.validator import Validator
        import sqlite3
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE backtest_run (id TEXT, run_name TEXT, status TEXT)")
        conn.execute("INSERT INTO backtest_run VALUES ('run-1', 'test', 'done')")
        conn.commit()
        conn.close()
        v = Validator(str(db))
        cr = v._check_run_id_exists("run-1")
        assert cr.passed
        assert cr.level == "PASS"

    def test_check_not_null_empty(self, tmp_path):
        from src.backtest.analysis.ingest.validator import Validator
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        v = Validator(str(db))
        # 构造合法 Pydantic 实例后修改字段为空
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        pi.meta.run_id = ""  # type: ignore[assignment]
        pi.metrics_core = []  # type: ignore[assignment]
        pi.docs = []  # type: ignore[assignment]
        cr = v._check_not_null(pi)
        assert not cr.passed
        assert cr.level == "ERROR"

    def test_check_enum_invalid_type(self, tmp_path):
        from src.backtest.analysis.ingest.validator import Validator
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        v = Validator(str(db))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        pi.meta.analysis_type = "invalid_type"  # type: ignore[assignment]
        cr = v._check_enum_values(pi)
        assert not cr.passed
        assert cr.level == "ERROR"

    def test_validate_passes_valid_input(self, tmp_path):
        from src.backtest.analysis.ingest.validator import Validator
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        import sqlite3
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE backtest_run (id TEXT, run_name TEXT, status TEXT)")
        conn.execute("INSERT INTO backtest_run VALUES ('run-1', 'test', 'done')")
        conn.commit()
        conn.close()
        v = Validator(str(db))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="run-1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="run-1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="run-1", doc_type="summary_report", file_path=str(tmp_path / "exists.md"))],
        )
        vr = v.validate(pi)
        assert vr.passed  # WARN level, not ERROR

    def test_check_docs_exist_missing(self, tmp_path):
        from src.backtest.analysis.ingest.validator import Validator
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        v = Validator(str(db))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/nonexistent_report.md")],
        )
        cr = v._check_docs_exist(pi)
        assert not cr.passed
        assert cr.level == "WARN"


# ==================== writer.py ====================


class TestWriter:
    """writer.py: 幂等判定表"""

    def test_determine_operation_insert(self, tmp_path):
        from src.backtest.analysis.ingest.writer import Writer
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        w = Writer(str(db), str(tmp_path / "archive"))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        op, _ = w._determine_operation(pi, existing=None, force=False)
        assert op == "INSERT"

    def test_determine_operation_update_draft(self, tmp_path):
        from src.backtest.analysis.ingest.writer import Writer
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        w = Writer(str(db), str(tmp_path / "archive"))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        existing = {"id": 1, "version_status": "draft", "version_content": 1}
        op, aid = w._determine_operation(pi, existing=existing, force=False)
        assert op == "UPDATE"
        assert aid == 1

    def test_determine_operation_skip_final(self, tmp_path):
        from src.backtest.analysis.ingest.writer import Writer
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        w = Writer(str(db), str(tmp_path / "archive"))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        existing = {"id": 2, "version_status": "final", "version_content": 1}
        op, aid = w._determine_operation(pi, existing=existing, force=False)
        assert op == "SKIP"
        assert aid == 2

    def test_determine_operation_force_final(self, tmp_path):
        from src.backtest.analysis.ingest.writer import Writer
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        w = Writer(str(db), str(tmp_path / "archive"))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        existing = {"id": 3, "version_status": "final", "version_content": 1}
        op, aid = w._determine_operation(pi, existing=existing, force=True)
        assert op == "UPDATE"
        assert aid == 3

    def test_determine_operation_skip_archived(self, tmp_path):
        from src.backtest.analysis.ingest.writer import Writer
        from src.backtest.analysis.ingest.model import PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc
        db = tmp_path / "test.db"
        db.write_text("")
        w = Writer(str(db), str(tmp_path / "archive"))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        existing = {"id": 4, "version_status": "archived", "version_content": 1}
        op, aid = w._determine_operation(pi, existing=existing, force=True)
        assert op == "SKIP"
        assert aid == 4

    def test_dry_run_returns_immediately(self, tmp_path):
        from src.backtest.analysis.ingest.writer import Writer
        from src.backtest.analysis.ingest.model import (
            PipelineInput, AnalysisMeta, MetricsCore, AnalysisDoc, ValidationResult,
        )
        db = tmp_path / "test.db"
        db.write_text("")
        w = Writer(str(db), str(tmp_path / "archive"))
        pi = PipelineInput(
            meta=AnalysisMeta(run_id="r1", analysis_type="summary"),
            metrics_core=[MetricsCore(run_id="r1", metric_group="daily")],
            docs=[AnalysisDoc(run_id="r1", doc_type="summary_report", file_path="/tmp/a.md")],
        )
        vr = ValidationResult(passed=True, level="PASS", checks=[])
        wr = w.write(pi, vr, dry_run=True)
        assert wr.status == "DRY_RUN"
        assert wr.operation == "NONE"


# ==================== pipeline.py ====================


class TestPipeline:
    """pipeline.py: Pipeline.run() 测试模式"""

    def test_pipeline_result_defaults(self):
        pr = PipelineResult(status="SUCCESS", run_id="r1", analysis_type="summary")
        assert pr["status"] == "SUCCESS"
        assert pr["warnings"] == []
        assert pr["total_duration_ms"] == 0.0

    def test_pipeline_result_from_error(self):
        pr = PipelineResult.from_error("r1", "summary", "test error", 100.0)
        assert pr["status"] == "ERROR"
        assert pr["error"] == "test error"
        assert pr["total_duration_ms"] == 100.0

    def test_ingest_api_exists(self):
        from src.backtest.analysis.ingest import ingest
        assert callable(ingest)

    def test_pipeline_constructor(self, tmp_path):
        """Pipeline 构造测试"""
        from src.backtest.analysis.ingest.pipeline import Pipeline
        db = tmp_path / "test.db"
        db.write_text("")
        p = Pipeline(
            db_path=str(db),
            run_id="test-run-1",
            analysis_type="summary",
            dry_run=True,
        )
        assert p.run_id == "test-run-1"
        assert p.dry_run
        assert p.timeout == 65

    def test_setup_logger(self, tmp_path):
        from src.backtest.analysis.ingest.pipeline import setup_logger
        log_dir = tmp_path / "logs"
        logger = setup_logger(str(log_dir), verbose=True)
        assert logger is not None
        assert (log_dir / "ingest_analysis.log").parent.exists()

    def test_pipeline_run_no_db(self, tmp_path):
        """DB 不存在时应返回 ERROR 而非崩溃"""
        from src.backtest.analysis.ingest.pipeline import Pipeline
        p = Pipeline(
            db_path=str(tmp_path / "nonexistent" / "backtest.db"),
            run_id="test-run-1",
            analysis_type="summary",
            dry_run=False,
            timeout=5,
        )
        result = p.run()
        assert result["status"] == "ERROR"
        assert result["error"] is not None


# ==================== config.py ====================


class TestConfig:
    """config.py: 路径推断"""

    def test_find_project_root(self):
        from src.backtest.analysis.ingest.config import find_project_root
        root = find_project_root()
        assert root.exists()
        assert (root / "pyproject.toml").exists()

    def test_resolve_db_path_default(self):
        from src.backtest.analysis.ingest.config import resolve_db_path
        dp = resolve_db_path(None)
        assert dp.endswith("backtest.db")

    def test_resolve_db_path_explicit(self):
        from src.backtest.analysis.ingest.config import resolve_db_path
        dp = resolve_db_path("/custom/path.db")
        assert dp == "/custom/path.db"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
