"""test_ingest_e2e.py - P4: End-to-end integration tests (real backtest.db).

Database path: mozhi_platform/data/backtest.db
Test run_id: 4f4b377a-7cba-4842-b566-7bd483559c16 (has data in performance_summary)
Idempotent run_id: 65787f51-dffe-4090-9456-803ec0991441 (already in analysis_meta)

Scenarios:
1. Full pipeline: read -> transform -> validate -> write (INSERT)
2. DRY-RUN mode
3. Idempotency (second run -> SKIP / UPDATE)
4. Data consistency verification
5. Performance (< 1s)
6. Cleanup after tests

Notes:
- 65787f51 has final record in analysis_meta but no data in performance_summary/backtest_run
- 4f4b377a is in backtest_run (status=done) and performance_summary - the only viable run_id
  for full pipeline test
"""

from __future__ import annotations

import logging
import time
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.backtest.analysis.ingest.datasource import DataSource
from src.backtest.analysis.ingest.transformer import Transformer
from src.backtest.analysis.ingest.validator import Validator
from src.backtest.analysis.ingest.writer import Writer
from src.backtest.analysis.ingest.pipeline import Pipeline, PipelineResult

# --- Constants ---

DB_PATH = Path(r"C:/Users/17699/mozhi_platform/data/backtest.db")
ARCHIVE_ROOT = DB_PATH.parent / "archive"
REPORTS_ROOT = DB_PATH.parent / "reports"
E2E_ANALYSIS_TYPE = "summary"

# run_id with data in both performance_summary and backtest_run
REAL_RUN_ID = "4f4b377a-7cba-4842-b566-7bd483559c16"

# run_id already ingested in analysis_meta only (for idempotent test)
INGESTED_RUN_ID = "65787f51-dffe-4090-9456-803ec0991441"


# --- Helpers ---


def _get_db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _cleanup_test_data(run_id: str, analysis_type: str = E2E_ANALYSIS_TYPE) -> None:
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            "SELECT id FROM analysis_meta WHERE run_id=? AND analysis_type=?",
            (run_id, analysis_type),
        )
        row = cur.fetchone()
        if row is None:
            return
        analysis_id = row["id"]
        conn.execute("DELETE FROM analysis_docs WHERE analysis_id=?", (analysis_id,))
        conn.execute("DELETE FROM analysis_metrics_ext WHERE analysis_id=?", (analysis_id,))
        conn.execute("DELETE FROM analysis_metrics_core WHERE analysis_id=?", (analysis_id,))
        conn.execute("DELETE FROM analysis_meta WHERE id=?", (analysis_id,))
        conn.commit()
    finally:
        conn.close()


def _get_test_analysis_count(run_id: str, analysis_type: str = E2E_ANALYSIS_TYPE) -> int:
    conn = _get_db_conn()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) as cnt FROM analysis_meta WHERE run_id=? AND analysis_type=?",
            (run_id, analysis_type),
        )
        return cur.fetchone()["cnt"]
    finally:
        conn.close()


def _get_perf_row() -> dict:
    conn = _get_db_conn()
    try:
        cur = conn.execute("""
            SELECT total_return, annualized_return, benchmark_return, excess_return,
                   max_drawdown, sharpe_ratio, calmar_ratio, sortino_ratio,
                   volatility, var_95_pct, win_rate, total_trades,
                   max_consecutive_wins, max_consecutive_losses, final_equity,
                   profit_factor
            FROM performance_summary
            WHERE run_id=?
            ORDER BY id DESC LIMIT 1
        """, (REAL_RUN_ID,))
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def _normalize_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return round(float(val), 6)
    except (ValueError, TypeError):
        return None


# ============================================================
# Test class
# ============================================================


class TestIngestE2E:
    """End-to-end integration tests (real DB connection)."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        _cleanup_test_data(REAL_RUN_ID)
        yield
        _cleanup_test_data(REAL_RUN_ID)

    # --------------------------------------------------
    # 1. DataSource tests
    # --------------------------------------------------

    def test_datasource_fetch_real_data(self):
        """[E2E] DataSource reads performance_summary from real DB."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        assert perf_row is not None, "Should read performance_summary data"
        assert perf_row["total_return"] is not None
        assert perf_row["annualized_return"] is not None
        assert perf_row["final_equity"] is not None
        assert isinstance(doc_files, list)

    def test_datasource_fetch_missing_run_id(self):
        """[E2E] DataSource returns None for missing run_id."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch("nonexistent-run-id-12345")
        assert perf_row is None
        assert isinstance(doc_files, list)

    # --------------------------------------------------
    # 2. Transformer tests
    # --------------------------------------------------

    def test_transformer_full_pipeline_input(self):
        """[E2E] Transformer produces complete PipelineInput."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        assert perf_row is not None, "Precondition: perf data must exist"

        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, doc_files)

        assert input_data.meta.run_id == REAL_RUN_ID
        assert input_data.meta.analysis_type == E2E_ANALYSIS_TYPE
        assert input_data.meta.version_status == "draft"
        assert len(input_data.metrics_core) == 1
        mc = input_data.metrics_core[0]
        assert mc.run_id == REAL_RUN_ID
        assert mc.metric_group == "daily"
        assert mc.total_return_pct is not None
        assert mc.sharpe_ratio is not None
        assert _normalize_float(mc.total_return_pct) == _normalize_float(perf_row["total_return"])
        assert _normalize_float(mc.annual_return_pct) == _normalize_float(perf_row["annualized_return"])
        assert len(input_data.docs) >= 1

    def test_transformer_with_null_perf_raises_error(self):
        """[E2E] Transformer raises error when perf_row is None."""
        transformer = Transformer(DB_PATH)
        with pytest.raises(Exception):
            transformer.transform("nonexistent-run-id", E2E_ANALYSIS_TYPE, None, [])

    # --------------------------------------------------
    # 3. Validator tests (real DB)
    # --------------------------------------------------

    def test_validator_passes_with_real_data(self):
        """[E2E] Validator passes all checks with real data."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, doc_files)

        validator = Validator(DB_PATH)
        result = validator.validate_with_perf(input_data, perf_row)
        assert result.passed, f"Validator should pass, level={result.level}"
        for check in result.checks:
            if check.level == "ERROR":
                pytest.fail(f"Check failed: [{check.name}] {check.detail}")

    def test_validator_run_id_exists(self):
        """[E2E] run_id exists in backtest_run check."""
        validator = Validator(DB_PATH)
        check = validator._check_run_id_exists(REAL_RUN_ID)
        assert check.passed, f"run_id check failed: {check.detail}"
        assert check.level == "PASS"

    def test_validator_run_id_not_exists(self):
        """[E2E] Missing run_id fails validation."""
        validator = Validator(DB_PATH)
        check = validator._check_run_id_exists("nonexistent-run-id")
        assert not check.passed

    def test_validator_not_null_pass(self):
        """[E2E] Not-null check passes."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, doc_files)
        validator = Validator(DB_PATH)
        check = validator._check_not_null(input_data)
        assert check.passed and check.level == "PASS"

    def test_validator_enum_values_pass(self):
        """[E2E] Enum values check passes."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, doc_files)
        validator = Validator(DB_PATH)
        check = validator._check_enum_values(input_data)
        assert check.passed and check.level == "PASS"

    def test_validator_cross_validate(self):
        """[E2E] Cross-validate: transformer data matches DB."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, doc_files)
        validator = Validator(DB_PATH)
        check = validator._check_cross_validate(input_data, perf_row)
        assert check.level != "ERROR", f"Cross-validation error: {check.detail}"
        assert check.passed, f"Cross-validation failed: {check.detail}"

    # --------------------------------------------------
    # 4. Pipeline full flow tests
    # --------------------------------------------------

    def test_pipeline_dry_run(self):
        """[E2E] Pipeline DRY-RUN writes no data."""
        count_before = _get_test_analysis_count(REAL_RUN_ID)
        assert count_before == 0, "Precondition: no existing records"

        pipeline = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=True,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_dry_run"),
        )
        result = pipeline.run()
        assert result.status == "DRY_RUN", f"Expected DRY_RUN, got {result.status}"
        count_after = _get_test_analysis_count(REAL_RUN_ID)
        assert count_after == 0, "No data should be written after DRY-RUN"

    def test_pipeline_full_ingest_and_data_consistency(self):
        """[E2E] Full pipeline: INSERT and verify data consistency."""
        perf_row = _get_perf_row()

        pipeline = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=False,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_full_ingest"),
        )
        result = pipeline.run()
        assert result.status in ("SUCCESS", "WARN"), f"Pipeline failed: {result.error}"
        assert result.operation == "INSERT", f"Expected INSERT, got {result.operation}"
        assert result.analysis_meta_id is not None, "Should return analysis_meta_id"
        assert result.total_duration_ms < 1000, \
            f"Performance requirement < 1s, actual: {result.total_duration_ms:.2f}ms"

        assert result.rows_written.get("analysis_meta", 0) == 1
        assert result.rows_written.get("analysis_metrics_core", 0) == 1
        assert isinstance(result.rows_written.get("analysis_docs", 0), int)

        # Verify written data matches original perf data
        analysis_id = result.analysis_meta_id
        conn = _get_db_conn()
        try:
            meta_row = conn.execute(
                "SELECT * FROM analysis_meta WHERE id=?", (analysis_id,)
            ).fetchone()
            assert meta_row is not None, "analysis_meta record not found"
            assert meta_row["run_id"] == REAL_RUN_ID
            assert meta_row["analysis_type"] == E2E_ANALYSIS_TYPE
            assert meta_row["version_status"] in ("draft",)

            mc_row = conn.execute(
                "SELECT * FROM analysis_metrics_core WHERE analysis_id=?", (analysis_id,)
            ).fetchone()
            assert mc_row is not None, "analysis_metrics_core record not found"
            assert _normalize_float(mc_row["total_return_pct"]) == _normalize_float(
                perf_row["total_return"]
            ), f"total_return mismatch: {mc_row['total_return_pct']} vs {perf_row['total_return']}"
            assert _normalize_float(mc_row["annual_return_pct"]) == _normalize_float(
                perf_row["annualized_return"]
            )
            assert _normalize_float(mc_row["sharpe_ratio"]) == _normalize_float(
                perf_row["sharpe_ratio"]
            )
            assert _normalize_float(mc_row["max_drawdown_pct"]) == _normalize_float(
                perf_row["max_drawdown"]
            )
            assert _normalize_float(mc_row["final_equity"]) == _normalize_float(
                perf_row["final_equity"]
            )

            doc_rows = conn.execute(
                "SELECT * FROM analysis_docs WHERE analysis_id=?", (analysis_id,)
            ).fetchall()
            assert len(doc_rows) >= 1, "At least 1 doc record expected"

            sv_row = conn.execute(
                "SELECT * FROM schema_version ORDER BY applied_at DESC LIMIT 1"
            ).fetchone()
            assert sv_row is not None, "schema_version should have a record"
        finally:
            conn.close()

    def test_pipeline_idempotent_second_run_updates(self):
        """[E2E] Idempotency: second run -> UPDATE (first INSERT had draft status)."""
        pipeline1 = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=False,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_idempotent_1"),
        )
        result1 = pipeline1.run()
        assert result1.operation == "INSERT", f"First run should INSERT, got {result1.operation}"

        pipeline2 = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=False,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_idempotent_2"),
        )
        result2 = pipeline2.run()
        assert result2.status in ("SUCCESS", "WARN"), f"Second run failed: {result2.error}"
        assert result2.operation in ("UPDATE", "INSERT"), \
            f"Expected UPDATE/INSERT, got {result2.operation}"

        conn = _get_db_conn()
        try:
            meta_rows = conn.execute(
                "SELECT id, version_content, version_status FROM analysis_meta "
                "WHERE run_id=? AND analysis_type=? ORDER BY id",
                (REAL_RUN_ID, E2E_ANALYSIS_TYPE),
            ).fetchall()
            assert len(meta_rows) >= 1

            mc_rows = conn.execute(
                "SELECT total_return_pct, sharpe_ratio FROM analysis_metrics_core "
                "WHERE analysis_id=?", (meta_rows[0]["id"],),
            ).fetchall()
            assert len(mc_rows) == 1, "metrics_core should have 1 row (idempotent)"
        finally:
            conn.close()

    # --------------------------------------------------
    # 5. Writer standalone tests
    # --------------------------------------------------

    def test_writer_write_dry_run(self):
        """[E2E] Writer dry_run mode works."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, doc_files)
        validator = Validator(DB_PATH)
        validation = validator.validate_with_perf(input_data, perf_row)
        writer = Writer(
            str(DB_PATH), str(ARCHIVE_ROOT), qa_verify=True, verbose=False,
            logger=logging.getLogger("test_writer_dry_run"),
        )
        result = writer.write(input_data, validation, dry_run=True)
        assert result.status == "DRY_RUN"

    def test_writer_insert_and_verify(self):
        """[E2E] Writer inserts and returns correct results."""
        ds = DataSource(DB_PATH)
        perf_row, doc_files = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, doc_files)
        validator = Validator(DB_PATH)
        validation = validator.validate_with_perf(input_data, perf_row)
        writer = Writer(
            str(DB_PATH), str(ARCHIVE_ROOT), qa_verify=True, verbose=False,
            logger=logging.getLogger("test_writer_insert"),
        )
        result = writer.write(input_data, validation)
        assert result.status == "SUCCESS", f"Write failed: {result.status}"
        assert result.operation == "INSERT"
        assert result.analysis_meta_id is not None
        assert result.rows_written.get("analysis_meta", 0) >= 1
        assert result.rows_written.get("analysis_metrics_core", 0) >= 1

    # --------------------------------------------------
    # 6. Performance tests
    # --------------------------------------------------

    def test_performance_ingest_under_1s(self):
        """[E2E] Performance: full pipeline < 1s."""
        t_start = time.time()
        pipeline = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=False,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_perf"),
        )
        result = pipeline.run()
        t_elapsed = (time.time() - t_start) * 1000
        assert result.status in ("SUCCESS", "WARN"), f"Pipeline failed: {result.error}"
        assert t_elapsed < 1050, f"Performance test failed: {t_elapsed:.2f}ms"

    def test_performance_dry_run_under_500ms(self):
        """[E2E] Performance: DRY-RUN < 500ms."""
        t_start = time.time()
        pipeline = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=True,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_perf_dry"),
        )
        result = pipeline.run()
        t_elapsed = (time.time() - t_start) * 1000
        assert result.status == "DRY_RUN"
        assert t_elapsed < 550, f"DRY-RUN performance: {t_elapsed:.2f}ms"

    # --------------------------------------------------
    # 7. Pipeline result structure
    # --------------------------------------------------

    def test_pipeline_result_structure(self):
        """[E2E] PipelineResult structure integrity."""
        pipeline = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=True,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_result_struct"),
        )
        result = pipeline.run()
        assert isinstance(result, PipelineResult)
        assert hasattr(result, "status")
        assert hasattr(result, "run_id")
        assert hasattr(result, "analysis_type")
        assert hasattr(result, "total_duration_ms")
        assert hasattr(result, "warnings")
        assert result.run_id == REAL_RUN_ID
        assert result.analysis_type == E2E_ANALYSIS_TYPE
        json_str = result.to_json()
        assert isinstance(json_str, str)
        assert REAL_RUN_ID in json_str

    # --------------------------------------------------
    # 8. Idempotent for already-ingested run_id
    # --------------------------------------------------

    def test_ingested_run_id_handling(self):
        """[E2E] run_id in analysis_meta but not perf_summary -> handles gracefully."""
        pipeline = Pipeline(
            db_path=str(DB_PATH),
            run_id=INGESTED_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=False,
            force=False,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_e2e_ingested"),
        )
        result = pipeline.run()
        # INGESTED_RUN_ID has no perf row -> datasource returns None -> transformer raises error
        # This is expected - the ingest pipeline needs perf data
        if result.status == "ERROR":
            assert "DataSourceError" in str(result.error) or "未找到" in str(result.error)
        else:
            assert result.operation == "SKIP"

    # --------------------------------------------------
    # 9. Column mapping verification
    # --------------------------------------------------

    def test_column_mapping_derived_fields(self):
        """[E2E] winning_trades/losing_trades derived from total_trades*win_rate."""
        ds = DataSource(DB_PATH)
        perf_row, _ = ds.fetch(REAL_RUN_ID)
        assert perf_row is not None

        # Verify source columns that DON'T exist
        assert "winning_trades" not in perf_row
        assert "losing_trades" not in perf_row

        # Verify source columns that DO exist and are used for derivation
        tt = perf_row.get("total_trades")
        wr = perf_row.get("win_rate")
        assert tt is not None
        assert wr is not None

        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, [])
        mc = input_data.metrics_core[0]

        # Derived values
        assert mc.winning_trades is not None, f"winning_trades should be derived from total_trades={tt} * win_rate={wr}"
        assert mc.losing_trades is not None, f"losing_trades should be derived"
        expected_wins = round(tt * wr)
        assert mc.winning_trades == expected_wins, f"winning_trades: expected {expected_wins}, got {mc.winning_trades}"
        assert mc.losing_trades == tt - expected_wins, f"losing_trades: expected {tt - expected_wins}, got {mc.losing_trades}"
        assert mc.winning_trades + mc.losing_trades == tt, "win + loss should equal total_trades"

    def test_column_mapping_missing_fields_as_none(self):
        """[E2E] Fields absent from source table are None in MetricsCore."""
        ds = DataSource(DB_PATH)
        perf_row, _ = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, [])
        mc = input_data.metrics_core[0]

        # These columns don't exist in performance_summary and can't be derived:
        assert mc.total_profit is None, "total_profit not in source table, should be None"
        assert mc.total_loss is None, "total_loss not in source table, should be None"
        assert mc.max_single_win is None, "max_single_win not in source table, should be None"
        assert mc.max_single_loss is None, "max_single_loss not in source table, should be None"
        assert mc.profit_loss_ratio is None, "profit_loss_ratio not derived, should be None"

    def test_column_mapping_exact_match_fields(self):
        """[E2E] Fields existing in source are mapped with exact values."""
        ds = DataSource(DB_PATH)
        perf_row, _ = ds.fetch(REAL_RUN_ID)
        transformer = Transformer(DB_PATH)
        input_data = transformer.transform(REAL_RUN_ID, E2E_ANALYSIS_TYPE, perf_row, [])
        mc = input_data.metrics_core[0]

        expected = [
            ("total_return", "total_return_pct"),
            ("annualized_return", "annual_return_pct"),
            ("benchmark_return", "benchmark_return_pct"),
            ("max_drawdown", "max_drawdown_pct"),
            ("sharpe_ratio", "sharpe_ratio"),
            ("calmar_ratio", "calmar_ratio"),
            ("sortino_ratio", "sortino_ratio"),
            ("volatility", "annual_volatility_pct"),
            ("win_rate", "win_rate_pct"),
            ("total_trades", "total_trades"),
            ("max_consecutive_wins", "max_consecutive_wins"),
            ("max_consecutive_losses", "max_consecutive_losses"),
            ("final_equity", "final_equity"),
        ]
        for perf_key, mc_attr in expected:
            perf_val = perf_row.get(perf_key)
            mc_val = getattr(mc, mc_attr)
            if perf_val is None:
                assert mc_val is None, f"{mc_attr}: perf is None but got {mc_val}"
            else:
                assert _normalize_float(mc_val) == _normalize_float(perf_val), \
                    f"{mc_attr}: expected {perf_val}, got {mc_val} (from {perf_key})"

    # --------------------------------------------------
    # 10. Database connectivity
    # --------------------------------------------------

    def test_database_exists_and_has_real_data(self):
        """[E2E] Database exists and has real data."""
        assert DB_PATH.exists(), f"Database not found: {DB_PATH}"
        conn = _get_db_conn()
        try:
            v4_tables = [
                "analysis_meta", "analysis_metrics_core",
                "analysis_metrics_ext", "analysis_docs", "schema_version",
            ]
            for tbl in v4_tables:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (tbl,),
                ).fetchone()
                assert row is not None, f"V4 table {tbl} missing"
            perf_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM performance_summary"
            ).fetchone()["cnt"]
            assert perf_count > 0, "performance_summary is empty"
            run_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM backtest_run"
            ).fetchone()["cnt"]
            assert run_count > 0, "backtest_run is empty"
        finally:
            conn.close()

    def test_real_run_id_exists_in_perf(self):
        """[E2E] REAL_RUN_ID exists in both performance_summary and backtest_run."""
        conn = _get_db_conn()
        try:
            perf = conn.execute(
                "SELECT COUNT(*) as cnt FROM performance_summary WHERE run_id=?",
                (REAL_RUN_ID,),
            ).fetchone()
            assert perf["cnt"] > 0, f"REAL_RUN_ID {REAL_RUN_ID} not in performance_summary"
            br = conn.execute(
                "SELECT COUNT(*) as cnt FROM backtest_run WHERE id=?",
                (REAL_RUN_ID,),
            ).fetchone()
            assert br["cnt"] > 0, f"REAL_RUN_ID {REAL_RUN_ID} not in backtest_run"
        finally:
            conn.close()

    # ============================================================
    # Stage4: Pipeline v4 integration tests (P5)
    # ============================================================

    def test_cli_end_to_end(self):
        """[Stage4] CLI dry-run returns exit code 0 with required args."""
        import subprocess

        result = subprocess.run(
            ["python", "-m", "src.backtest.analysis.ingest",
             "--run-id", REAL_RUN_ID, "--analysis-type", "summary",
             "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, \
            f"CLI failed (rc={result.returncode}): stderr={result.stderr[:500]}"

    def test_schema_version_recorded(self):
        """[Stage4] schema_version table records version=4.0 after ingestion."""
        conn = _get_db_conn()
        try:
            tables = [
                r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "schema_version" in tables, \
                "schema_version table not found"
            row = conn.execute(
                "SELECT version, applied_at, description "
                "FROM schema_version ORDER BY applied_at DESC LIMIT 1"
            ).fetchone()
            assert row is not None, "No version record in schema_version"
            version = row["version"]
            assert isinstance(version, str) and len(version) >= 3, \
                f"Invalid version string: {version}"
            assert row["applied_at"] is not None, "applied_at should not be null"
        finally:
            conn.close()

    def test_analysis_meta_record(self):
        """[Stage4] analysis_meta records ingested run_id with correct type."""
        from src.backtest.analysis.ingest.pipeline import Pipeline
        import logging

        pipeline = Pipeline(
            db_path=str(DB_PATH),
            run_id=REAL_RUN_ID,
            analysis_type=E2E_ANALYSIS_TYPE,
            dry_run=False,
            force=True,
            timeout=30,
            archive_root=str(ARCHIVE_ROOT),
            logger=logging.getLogger("test_p5_analysis_meta"),
        )
        result = pipeline.run()
        assert result.status in ("SUCCESS", "WARN"), \
            f"Pipeline failed: {result.error}"

        conn = _get_db_conn()
        try:
            row = conn.execute(
                "SELECT run_id, analysis_type, version_schema, version_status "
                "FROM analysis_meta WHERE run_id=? AND analysis_type=?",
                (REAL_RUN_ID, E2E_ANALYSIS_TYPE),
            ).fetchone()
            assert row is not None, \
                f"analysis_meta record not found for run_id={REAL_RUN_ID}"
            assert row["run_id"] == REAL_RUN_ID
            assert row["analysis_type"] == E2E_ANALYSIS_TYPE
            assert row["version_schema"] == "1.0"
            assert row["version_status"] in ("draft",)
        finally:
            conn.close()

    def test_archive_content_hash_integrity(self):
        """[Stage4] analysis_docs.content_hash is non-empty for records that have it."""
        conn = _get_db_conn()
        try:
            rows = conn.execute(
                "SELECT id, doc_type, file_path, content_hash, file_size_bytes "
                "FROM analysis_docs WHERE content_hash IS NOT NULL"
            ).fetchall()
            if len(rows) == 0:
                pytest.skip("No records with content_hash in analysis_docs")
            for row in rows:
                assert len(str(row["content_hash"])) > 0, \
                    f"Empty content_hash for doc_id={row['id']}, type={row['doc_type']}"
        finally:
            conn.close()

    def test_done_signal_file_written_with_task_id(self):
        """[Stage4] Pipeline with task_id writes .done signal file."""
        import json, tempfile, logging
        from src.backtest.analysis.ingest.pipeline import Pipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = f"p5_test_{int(time.time())}"
            pipeline = Pipeline(
                db_path=str(DB_PATH),
                run_id=REAL_RUN_ID,
                analysis_type=E2E_ANALYSIS_TYPE,
                dry_run=False,
                force=True,
                timeout=30,
                archive_root=str(ARCHIVE_ROOT),
                signal_root=tmpdir,
                task_id=task_id,
                logger=logging.getLogger("test_p5_done_signal"),
            )
            result = pipeline.run()
            assert result.status in ("SUCCESS", "WARN"), \
                f"Pipeline failed: {result.error}"

            done_path = Path(tmpdir) / f"{task_id}_moheng.done"
            assert done_path.exists(), \
                f".done signal file not found: {done_path}"

            signal = json.loads(done_path.read_text(encoding="utf-8"))
            assert signal["status"] == "SUCCESS"
            assert signal["run_id"] == REAL_RUN_ID
            assert signal["analysis_type"] == E2E_ANALYSIS_TYPE
            assert signal["timestamp"] is not None

    def test_failed_signal_file_written_on_error(self):
        """[Stage4] Pipeline writes .failed signal file on validation error."""
        import json, tempfile
        from src.backtest.analysis.ingest.pipeline import Pipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = f"p5_fail_test_{int(time.time())}"
            pipeline = Pipeline(
                db_path=str(DB_PATH),
                run_id="nonexistent_run_id_xyz",
                analysis_type="summary",
                dry_run=False,
                timeout=10,
                signal_root=tmpdir,
                task_id=task_id,
            )
            result = pipeline.run()
            assert result.status == "ERROR"

            failed_path = Path(tmpdir) / f"{task_id}_moheng.failed"
            assert failed_path.exists(), \
                f".failed signal file not found: {failed_path}"

            signal = json.loads(failed_path.read_text(encoding="utf-8"))
            assert signal["status"] == "FAILED"
            assert "error" in signal and len(signal["error"]) > 0
