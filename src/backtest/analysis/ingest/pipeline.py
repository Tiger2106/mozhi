"""pipeline.py — Pipeline 协调器 / 四阶段管道主入口

P0 MVP: Pipeline.run() 完整流程（10步骤+错误处理+事务）
P1: 归档实现
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .config import find_project_root, resolve_archive_root, resolve_db_path
from .datasource import DataSource, DataSourceError
from .model import PipelineInput, WriteResult, _now_iso
from .transformer import Transformer, TransformError
from .validator import ValidationError, ValidationResult, Validator
from .writer import WriteError, Writer


# ——— 结果类型 ———


class PipelineResult(dict):
    """管道执行结果 (TypedDict 风格)"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setdefault("status", "ERROR")
        self.setdefault("run_id", "")
        self.setdefault("analysis_type", "")
        self.setdefault("operation", "")
        self.setdefault("analysis_meta_id", None)
        self.setdefault("rows_written", {})
        self.setdefault("qa_report", None)
        self.setdefault("total_duration_ms", 0.0)
        self.setdefault("error", None)
        self.setdefault("warnings", [])

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def to_json(self) -> str:
        return json.dumps(self, ensure_ascii=False, default=str)

    @staticmethod
    def from_error(run_id: str, analysis_type: str, error: str, dur_ms: float = 0.0):
        return PipelineResult(
            status="ERROR",
            run_id=run_id,
            analysis_type=analysis_type,
            error=error,
            total_duration_ms=dur_ms,
        )


class PipelineError(Exception):
    """Pipeline 基类异常"""

    def __init__(
        self, message: str, level: str = "ERROR", phase: str = "", details: dict | None = None
    ):
        super().__init__(message)
        self.level = level
        self.phase = phase
        self.details = details or {}


# ——— Logger 设置 ———


def setup_logger(log_dir: str | Path = "logs", verbose: bool = False) -> logging.Logger:
    """JSON Lines 格式日志配置"""
    import sys
    from logging.handlers import RotatingFileHandler

    log_dir = Path(log_dir)
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger("ingest_analysis")
    logger.setLevel(logging.DEBUG)

    # 避免重复添加
    if logger.handlers:
        return logger

    # JSON Lines 文件 Handler
    file_handler = RotatingFileHandler(
        log_dir / "ingest_analysis.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)

    class JsonFormatter(logging.Formatter):
        def format(self, record):
            log_obj = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S+08:00"),
                "level": record.levelname,
                "component": getattr(record, "component", "ingest"),
                "message": record.getMessage(),
            }
            for key in (
                "run_id", "action", "duration_ms", "phase", "table",
                "rows", "check_name", "detail", "sql", "data", "traceback",
                "status", "existing_status", "result",
            ):
                val = getattr(record, key, None)
                if val is not None:
                    log_obj[key] = val
            return json.dumps(log_obj, ensure_ascii=False)

    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


# ——— Pipeline 协调器 ———


class Pipeline:
    """四阶段管道协调器"""

    def __init__(
        self,
        db_path: str | Path,
        run_id: str,
        analysis_type: str,
        dry_run: bool = False,
        qa_verify: bool = False,
        force: bool = False,
        timeout: int = 65,
        verbose: bool = False,
        archive_root: str | Path | None = None,
        signal_root: str | Path | None = None,
        task_id: str = "",
        logger: logging.Logger | None = None,
    ):
        self.db_path = Path(db_path)
        self.run_id = run_id
        self.analysis_type = analysis_type
        self.dry_run = dry_run
        self.qa_verify = qa_verify
        self.force = force
        self.timeout = timeout
        self.verbose = verbose
        self.archive_root = (
            Path(archive_root) if archive_root else Path(resolve_archive_root())
        )
        self.signal_root = signal_root
        self.task_id = task_id
        self._logger = logger or setup_logger(verbose=verbose)

        # 阶段模块（延迟初始化）
        self._datasource: DataSource | None = None
        self._transformer: Transformer | None = None
        self._validator: Validator | None = None
        self._writer: Writer | None = None

        # 运行时状态
        self._start_time: float = 0.0
        self._timeout_timer: threading.Timer | None = None
        self._timed_out = False

    def _check_timeout(self) -> None:
        """检查超时标志，超时后立即中断"""
        if self._timed_out:
            dur = (time.time() - self._start_time) * 1000
            raise PipelineError(
                f"管道执行超时 (>{self.timeout}s)",
                level="ERROR",
                phase="timeout",
                details={"run_id": self.run_id, "duration_ms": round(dur, 2)},
            )

    def run(self) -> PipelineResult:
        """
        执行完整管道，返回结构化结果。

        10步骤流程:
        1. INIT
        2. DATA SOURCE PHASE
        3. TRANSFORM PHASE
        4. VALIDATE PHASE
        5. DRY-RUN
        6. IDEMPOTENT CHECK
        7. WRITE PHASE
        8. ARCHIVE PHASE
        9. QA-VERIFY
        10. COMPLETION
        """
        warnings: list[str] = []
        self._start_time = time.time()

        # 超时保护
        self._start_timeout()

        try:
            # ——— Step 1: INIT ———
            self._logger.info(
                "[START] ingest pipeline",
                extra={
                    "component": "pipeline",
                    "action": "start",
                    "run_id": self.run_id,
                    "analysis_type": self.analysis_type,
                },
            )

            self._datasource = DataSource(self.db_path)
            self._transformer = Transformer(self.db_path)
            self._validator = Validator(self.db_path)
            self._writer = Writer(
                str(self.db_path),
                str(self.archive_root),
                qa_verify=self.qa_verify,
                verbose=self.verbose,
                logger=self._logger,
                signal_root=str(self.signal_root) if self.signal_root else None,
            )

            # ——— Step 2: DATA SOURCE PHASE ———
            self._check_timeout()
            t0 = time.time()
            self._logger.info(
                "[START] data source phase",
                extra={
                    "component": "datasource",
                    "action": "start",
                    "run_id": self.run_id,
                },
            )
            perf_row, doc_files = self._datasource.fetch(self.run_id)
            t1 = time.time()
            self._logger.info(
                f"[END] data source phase: found {1 if perf_row else 0} perf row, "
                f"{len(doc_files)} doc files",
                extra={
                    "component": "datasource",
                    "action": "end",
                    "duration_ms": round((t1 - t0) * 1000, 2),
                },
            )

            # ——— Step 3: TRANSFORM PHASE ———
            self._check_timeout()
            t0 = time.time()
            self._logger.info(
                "[START] transform phase",
                extra={
                    "component": "transformer",
                    "action": "start",
                    "run_id": self.run_id,
                },
            )
            input_data = self._transformer.transform(
                self.run_id,
                self.analysis_type,
                perf_row=perf_row,
                doc_files=doc_files,
            )
            t1 = time.time()
            self._logger.info(
                "[END] transform phase: validated PipelineInput ready",
                extra={
                    "component": "transformer",
                    "action": "end",
                    "duration_ms": round((t1 - t0) * 1000, 2),
                },
            )

            # ——— Step 4: VALIDATE PHASE ———
            self._check_timeout()
            t0 = time.time()
            self._logger.info(
                "[START] validate phase",
                extra={
                    "component": "validator",
                    "action": "start",
                    "run_id": self.run_id,
                },
            )
            validation = self._validator.validate_with_perf(input_data, perf_row)
            t1 = time.time()
            n_pass = sum(1 for c in validation.checks if c.level == "PASS")
            n_warn = sum(1 for c in validation.checks if c.level == "WARN")
            n_err = sum(1 for c in validation.checks if c.level == "ERROR")
            self._logger.info(
                f"[END] validate phase: {len(validation.checks)} checks "
                f"({n_pass} PASS, {n_warn} WARN, {n_err} ERROR)",
                extra={
                    "component": "validator",
                    "action": "end",
                    "duration_ms": round((t1 - t0) * 1000, 2),
                },
            )

            # 收集警告
            for check in validation.checks:
                if check.level == "WARN":
                    warnings.append(f"[{check.name}] {check.detail}")
                if check.level == "ERROR":
                    warnings.append(f"[ERROR:{check.name}] {check.detail}")

            # ERROR 等级 → 失败
            if validation.level == "ERROR":
                error_detail = next(
                    (c.detail for c in validation.checks if c.level == "ERROR"),
                    "validate phase failed",
                )
                raise ValidationError(
                    error_detail,
                    details={"run_id": self.run_id, "checks": [
                        c.model_dump() for c in validation.checks if c.level == "ERROR"
                    ]},
                )

            # ——— Step 5: DRY-RUN ———
            self._check_timeout()
            if self.dry_run:
                dur = (time.time() - self._start_time) * 1000
                self._logger.info(
                    "[DRY-RUN] completed",
                    extra={
                        "component": "pipeline",
                        "action": "dry_run",
                        "duration_ms": round(dur, 2),
                    },
                )
                return PipelineResult(
                    status="DRY_RUN",
                    run_id=self.run_id,
                    analysis_type=self.analysis_type,
                    total_duration_ms=round(dur, 2),
                    warnings=warnings,
                )

            # ——— Step 6+7+8: WRITE PHASE + ARCHIVE ———
            self._check_timeout()
            t0 = time.time()
            write_result = self._writer.write(
                input_data, validation, force=self.force, dry_run=False
            )
            t1 = time.time()

            # 归档重试（file_size_bytes==-1 的情况）
            if write_result.operation == "UPDATE":
                retry_results = self._writer._retry_failed_archives(
                    self.run_id, self.analysis_type
                )
                for rr in retry_results:
                    if rr.get("status") == "copied":
                        warnings.append(
                            f"[ARCHIVE_RETRY] 归档重试成功: {rr.get('doc_type')}"
                        )

            # ——— Step 9: QA 报告已在 writer 内部生成 ———

            # ——— Step 10: COMPLETION ———
            dur = (time.time() - self._start_time) * 1000

            # .done 信号
            self._writer.write_done_signal(self.run_id, self.analysis_type, self.task_id)

            status = "SUCCESS"
            if warnings:
                status = "WARN"

            self._logger.info(
                f"[END] pipeline completed: status={status} "
                f"operation={write_result.operation}",
                extra={
                    "component": "pipeline",
                    "action": "end",
                    "total_duration_ms": round(dur, 2),
                    "run_id": self.run_id,
                    "analysis_type": self.analysis_type,
                    "status": status,
                },
            )

            return PipelineResult(
                status=status,
                run_id=self.run_id,
                analysis_type=self.analysis_type,
                operation=write_result.operation,
                analysis_meta_id=write_result.analysis_meta_id,
                rows_written=write_result.rows_written,
                qa_report=write_result.qa_report.model_dump() if write_result.qa_report else None,
                total_duration_ms=round(dur, 2),
                warnings=warnings,
            )

        except (DataSourceError, TransformError, ValidationError, WriteError) as e:
            import traceback
            dur = (time.time() - self._start_time) * 1000
            error_msg = f"[{type(e).__name__}] {str(e)}"
            trace = traceback.format_exc()
            extra = {
                "component": "pipeline",
                "action": "fail",
                "total_duration_ms": round(dur, 2),
                "run_id": self.run_id,
                "traceback": trace,
            }
            # 附加 SQL 和参数（如适用）
            if hasattr(e, "details") and isinstance(e.details, dict):
                for k in ("sql", "params", "sql_error"):
                    if k in e.details:
                        extra[k] = e.details[k]
            self._logger.error(
                f"[ERROR] pipeline failed: {error_msg} | sql={extra.get('sql','N/A')} "
                f"params={extra.get('params','N/A')} | traceback={trace[:500]}",
                extra=extra,
            )
            # .failed 信号
            if self._writer:
                self._writer.write_failed_signal(
                    self.run_id, self.analysis_type, error_msg, self.task_id
                )
            return PipelineResult.from_error(
                self.run_id, self.analysis_type, error_msg, dur
            )

        except Exception as e:
            import traceback
            dur = (time.time() - self._start_time) * 1000
            error_msg = f"[FATAL] {type(e).__name__}: {str(e)}"
            trace = traceback.format_exc()
            extra = {
                "component": "pipeline",
                "action": "fatal",
                "total_duration_ms": round(dur, 2),
                "traceback": trace,
            }
            self._logger.error(
                f"[FATAL] {error_msg} | traceback={trace[:500]}",
                extra=extra,
            )
            return PipelineResult.from_error(
                self.run_id, self.analysis_type, error_msg, dur
            )

        finally:
            self._cancel_timeout()

    # ——— 超时保护 ———

    def _start_timeout(self) -> None:
        if self.timeout <= 0:
            return

        def _on_timeout():
            self._timed_out = True
            self._logger.error(
                f"[TIMEOUT] pipeline exceeded {self.timeout}s",
                extra={"component": "pipeline"},
            )

        self._timeout_timer = threading.Timer(self.timeout, _on_timeout)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

    def _cancel_timeout(self) -> None:
        if self._timeout_timer:
            self._timeout_timer.cancel()
            self._timeout_timer = None


# ——— public API 便捷函数 ———


def ingest(
    run_id: str,
    analysis_type: str,
    dry_run: bool = False,
    qa_verify: bool = False,
    force: bool = False,
    timeout: int = 65,
    verbose: bool = False,
    db_path: str | None = None,
    archive_root: str | None = None,
    signal_root: str | None = None,
    task_id: str = "",
) -> PipelineResult:
    """便捷入口函数, 自动推断默认路径"""
    resolved_db = resolve_db_path(db_path)
    resolved_archive = resolve_archive_root(archive_root)
    logger = setup_logger(verbose=verbose)

    pipeline = Pipeline(
        db_path=resolved_db,
        run_id=run_id,
        analysis_type=analysis_type,
        dry_run=dry_run,
        qa_verify=qa_verify,
        force=force,
        timeout=timeout,
        verbose=verbose,
        archive_root=resolved_archive,
        signal_root=signal_root,
        task_id=task_id,
        logger=logger,
    )
    return pipeline.run()
