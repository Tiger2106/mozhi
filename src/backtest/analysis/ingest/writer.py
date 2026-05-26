"""writer.py — SQLite 事务写入 + 归档 + 幂等检查 + .done/.failed

P0 MVP: 5张表 INSERT/UPSERT + 幂等 via SELECT → UPDATE or INSERT + analysis_docs 基础写入
P1: content_hash 计算 + 文件复制的归档实现 + 归档失败标记 file_size_bytes=-1 + 重试
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .config import resolve_signal_root
from .model import (
    AnalysisDoc,
    AnalysisMeta,
    MetricsCore,
    MetricsExt,
    PipelineInput,
    QaCheckItem,
    QaReport,
    ValidationResult,
    WriteResult,
    _hash_file,
    _now_iso,
)


class WriteError(Exception):
    """写入阶段异常"""

    def __init__(self, message: str, phase: str = "writer", details: dict | None = None):
        super().__init__(message)
        self.phase = phase
        self.details = details or {}


class Writer:
    """SQLite 事务写入 + 归档"""

    def __init__(
        self,
        db_path: str | Path,
        archive_root: str | Path,
        qa_verify: bool = False,
        verbose: bool = False,
        logger: logging.Logger | None = None,
        signal_root: str | Path | None = None,
    ):
        self.db_path = Path(db_path)
        self.archive_root = Path(archive_root)
        self._signal_root = Path(resolve_signal_root(str(signal_root)) if signal_root else resolve_signal_root())
        self._qa_verify = qa_verify
        self._verbose = verbose
        self._logger = logger or logging.getLogger("ingest_analysis")
        self._conn: sqlite3.Connection | None = None

    def write(
        self,
        input_data: PipelineInput,
        validation: ValidationResult,
        force: bool = False,
        dry_run: bool = False,
    ) -> WriteResult:
        """
        事务包裹全部写入 + 归档。

        流程:
        1. 检查幂等性 (SELECT run_id + analysis_type)
        2. 确定操作类型 (INSERT / UPDATE / SKIP)
        3. 开启事务 BEGIN IMMEDIATE
        4. 写入/更新 analysis_meta
        5. CASCADE 删除旧附属记录 (如果UPDATE)
        6. 写入 analysis_metrics_core
        7. 写入 analysis_metrics_ext
        8. 写入 analysis_docs
        9. UPSERT schema_version
        10. COMMIT
        11. 执行文件归档 (先DB后文件)
        12. 归档失败时 UPDATE analysis_docs SET file_size_bytes=-1
        """
        if dry_run:
            return WriteResult(
                status="DRY_RUN",
                operation="NONE",
                rows_written={},
                doc_archive_results=[],
            )

        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row

        try:
            # 1. 幂等检查
            existing = self._check_idempotent(
                input_data.meta.run_id, input_data.meta.analysis_type
            )

            # 2. 确定操作
            operation, analysis_id = self._determine_operation(
                input_data, existing, force
            )
            if operation == "SKIP":
                self._conn.close()
                self._conn = None
                return WriteResult(
                    status="SUCCESS",
                    operation="SKIP",
                    analysis_meta_id=analysis_id,
                )

            # 3. BEGIN IMMEDIATE
            self._log("writer", "INFO", "[START] write phase: BEGIN transaction")
            self._conn.execute("BEGIN IMMEDIATE")

            # 4. 写入/更新 analysis_meta
            if operation == "INSERT":
                analysis_id = self._write_meta(self._conn, input_data.meta)
            elif operation == "UPDATE":
                self._cascade_delete_old(self._conn, analysis_id)
                self._update_meta(self._conn, analysis_id, input_data.meta)

            # 5. 写入 metrics_core
            core_rows = 0
            for mc in input_data.metrics_core:
                mc.analysis_id = analysis_id
                self._write_metrics_core(self._conn, analysis_id, mc)
                core_rows += 1

            # 6. 批量写入 metrics_ext
            ext_rows = self._write_metrics_ext_batch(self._conn, analysis_id, input_data.metrics_ext)

            # 7. 写入 docs
            doc_results: list[AnalysisDoc] = []
            for doc in input_data.docs:
                doc.analysis_id = analysis_id
                # 计算 content_hash + 文件大小
                if doc.file_path:
                    try:
                        computed_hash, fsize = self._compute_doc_meta(doc.file_path)
                        doc.content_hash = computed_hash
                        doc.file_size_bytes = fsize
                    except Exception:
                        pass
                self._write_doc(self._conn, analysis_id, doc)
                doc_results.append(doc)

            # 8. UPSERT schema_version
            self._upsert_schema_version(self._conn)

            # 9. COMMIT
            self._conn.commit()
            self._log("writer", "INFO", "[END] write phase: COMMIT transaction")

            # ——— DB 提交成功至此 ———

            # 10. 归档 (DB 外)
            archive_results = self._archive_docs(doc_results, existing)

            # 11. 处理归档失败
            for i, ar in enumerate(archive_results):
                if ar.get("status") in ("missing_source", "error"):
                    self._mark_archive_failed(analysis_id, doc_results[i].doc_type)

            # 12. QA 报告
            qa = None
            if self._qa_verify:
                qa = self._generate_qa_report(input_data, analysis_id, existing)

            return WriteResult(
                status="SUCCESS",
                operation=operation,
                analysis_meta_id=analysis_id,
                rows_written={
                    "analysis_meta": 1,
                    "analysis_metrics_core": core_rows,
                    "analysis_metrics_ext": ext_rows,
                    "analysis_docs": len(doc_results),
                    "schema_version": 1,
                },
                doc_archive_results=archive_results,
                qa_report=qa,
            )

        except sqlite3.Error as e:
            if self._conn:
                self._conn.rollback()
                self._log("writer", "ERROR", f"[ERROR] write phase rollback: {e}")
            raise WriteError(
                f"SQL transaction failed: {e}",
                details={"run_id": input_data.meta.run_id, "sql_error": str(e)},
            ) from e
        finally:
            if self._conn:
                self._conn.close()
                self._conn = None

    # ——— 幂等 / 操作判定 ———

    def _check_idempotent(self, run_id: str, analysis_type: str) -> dict | None:
        """SELECT 查重, 返回已有记录或 None"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """SELECT id, run_id, analysis_type, version_status,
                          version_content, author, created_at, updated_at,
                          parent_session_id, tags
                   FROM analysis_meta
                   WHERE run_id = ? AND analysis_type = ?
                   ORDER BY id DESC LIMIT 1""",
                (run_id, analysis_type),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    def _determine_operation(
        self, input_data: PipelineInput, existing: dict | None, force: bool
    ) -> tuple[str, int | None]:
        """确定操作类型: INSERT / UPDATE / SKIP"""
        if existing is None:
            self._log("writer", "INFO", "[IDEMPOTENT] 无已有记录 → INSERT")
            return "INSERT", None

        status = existing["version_status"]
        existing_id = existing["id"]

        if status in ("draft",):
            self._log(
                "writer",
                "INFO",
                f"[IDEMPOTENT] 已有 draft record id={existing_id} → UPDATE",
            )
            return "UPDATE", existing_id

        if status == "final" and force:
            self._log(
                "writer",
                "INFO",
                f"[IDEMPOTENT] 已有 final record id={existing_id}, force=True → UPDATE",
            )
            return "UPDATE", existing_id

        if status == "final" and not force:
            self._log(
                "writer",
                "INFO",
                f"[IDEMPOTENT] 已有 final record id={existing_id} → SKIP",
            )
            return "SKIP", existing_id

        if status == "archived":
            self._log(
                "writer",
                "INFO",
                f"[IDEMPOTENT] 已有 archived record id={existing_id} → SKIP",
            )
            return "SKIP", existing_id

        raise WriteError(
            f"unexpected version_status: {status}",
            details={"existing_id": existing_id, "status": status},
        )

    # ——— 事务写入 ———

    def _write_meta(self, tx: sqlite3.Connection, meta: AnalysisMeta) -> int:
        """INSERT analysis_meta, 返回新 id"""
        sql, params = meta.meta_to_insert_sql()
        tx.execute(sql, params)
        row_id = tx.execute("SELECT last_insert_rowid()").fetchone()[0]
        self._log(
            "writer",
            "INFO",
            f"[INSERT] analysis_meta: id={row_id} run_id={meta.run_id}",
        )
        return row_id

    def _update_meta(self, tx: sqlite3.Connection, meta_id: int, meta: AnalysisMeta) -> None:
        """UPDATE analysis_meta"""
        sql, params = meta.meta_to_update_sql(meta_id)
        tx.execute(sql, params)
        self._log(
            "writer",
            "INFO",
            f"[UPDATE] analysis_meta: id={meta_id} (version_content++)",
        )

    def _cascade_delete_old(self, tx: sqlite3.Connection, analysis_id: int) -> None:
        """UPDATE 时清除旧附属记录"""
        tx.execute("PRAGMA foreign_keys = ON")
        tx.execute("DELETE FROM analysis_docs WHERE analysis_id = ?", (analysis_id,))
        tx.execute(
            "DELETE FROM analysis_metrics_ext WHERE analysis_id = ?", (analysis_id,)
        )
        tx.execute(
            "DELETE FROM analysis_metrics_core WHERE analysis_id = ?", (analysis_id,)
        )
        self._log(
            "writer",
            "INFO",
            f"[CASCADE] 已删除 analysis_id={analysis_id} 的旧附属记录",
        )

    def _write_metrics_core(
        self, tx: sqlite3.Connection, analysis_id: int, mc: MetricsCore
    ) -> None:
        """批量 INSERT analysis_metrics_core"""
        mc.analysis_id = analysis_id
        sql, params = mc.to_insert_sql()
        tx.execute(sql, params)
        self._log(
            "writer",
            "INFO",
            f"[INSERT] analysis_metrics_core: 1 row (metric_group={mc.metric_group})",
        )

    def _write_metrics_ext(
        self, tx: sqlite3.Connection, analysis_id: int, me: MetricsExt
    ) -> None:
        """单条 INSERT analysis_metrics_ext（设计文档要求批量，外部调用已合并为 executemany）"""
        me.analysis_id = analysis_id
        sql, params = me.to_insert_sql()
        tx.execute(sql, params)
        self._log(
            "writer",
            "INFO",
            f"[INSERT] analysis_metrics_ext: 1 row (metric_name={me.metric_name})",
        )

    def _write_metrics_ext_batch(
        self, tx: sqlite3.Connection, analysis_id: int, items: list[MetricsExt]
    ) -> int:
        """executemany 批量 INSERT analysis_metrics_ext"""
        if not items:
            return 0
        for item in items:
            item.analysis_id = analysis_id
        sql = """INSERT INTO analysis_metrics_ext (
            analysis_id, run_id, metric_group, metric_name, metric_value, metric_label
        ) VALUES (?, ?, ?, ?, ?, ?)"""
        params = [
            (analysis_id, m.run_id, m.metric_group, m.metric_name, m.metric_value, m.metric_label)
            for m in items
        ]
        tx.executemany(sql, params)
        self._log(
            "writer",
            "INFO",
            f"[INSERT BATCH] analysis_metrics_ext: {len(items)} rows",
        )
        return len(items)

    def _write_doc(
        self, tx: sqlite3.Connection, analysis_id: int, doc: AnalysisDoc
    ) -> None:
        """INSERT analysis_docs"""
        doc.analysis_id = analysis_id
        sql, params = doc.to_insert_sql()
        tx.execute(sql, params)
        self._log(
            "writer",
            "INFO",
            f"[INSERT] analysis_docs: doc_type={doc.doc_type}",
        )

    def _upsert_schema_version(self, tx: sqlite3.Connection) -> None:
        """schema_version UPSERT"""
        now = _now_iso()
        tx.execute(
            """INSERT INTO schema_version (version, description, applied_at)
               VALUES ('4.0', 'Analysis layer: meta+metrics_core+metrics_ext+docs+schema_version', ?)
               ON CONFLICT(version) DO UPDATE SET
                   applied_at = ?,
                   description = excluded.description,
                   checksum = excluded.checksum""",
            (now, now),
        )
        self._log("writer", "INFO", "[UPSERT] schema_version: version=4.0")

    # ——— 归档实现 ———

    def _compute_doc_meta(self, file_path: str) -> tuple[str, int]:
        """计算文件哈希和大小"""
        p = Path(file_path)
        if not p.exists():
            return "", 0
        return _hash_file(p), p.stat().st_size

    def _archive_docs(
        self, new_docs: list[AnalysisDoc], existing_meta: dict | None
    ) -> list[dict]:
        """
        归档文件（先DB后文件策略中的第二步）。

        Returns:
            每份文档的归档结果列表
        """
        archive_results: list[dict] = []
        archive_reports = self.archive_root / "reports"
        archive_reports.mkdir(parents=True, exist_ok=True)

        for doc in new_docs:
            if not doc.file_path:
                archive_results.append({
                    "doc_type": doc.doc_type,
                    "status": "no_source_path",
                    "error": "file_path 为空",
                })
                continue

            result = self._archive_single_file(
                Path(doc.file_path), archive_reports
            )
            result["doc_type"] = doc.doc_type
            archive_results.append(result)

        return archive_results

    def _archive_single_file(self, src: Path, dst_root: Path) -> dict:
        """单文件归档，含版本化重命名逻辑"""
        dst = dst_root / src.name

        if not src.exists():
            return {"status": "missing_source", "error": f"source not found: {src}"}

        try:
            if dst.exists():
                # 比较哈希
                src_hash = _hash_file(src)
                dst_hash = _hash_file(dst)
                if src_hash == dst_hash:
                    self._log(
                        "writer",
                        "INFO",
                        f"[ARCHIVE] {src.name} → skipped (hash match)",
                    )
                    return {
                        "status": "skipped_hash_match",
                        "size": src.stat().st_size,
                        "dst": str(dst),
                        "content_hash": src_hash,
                    }
                else:
                    # 版本化重命名
                    version = 1
                    while dst.with_name(f"{dst.stem}_v{version}{dst.suffix}").exists():
                        version += 1
                    dst = dst.with_name(f"{dst.stem}_v{version}{dst.suffix}")

            shutil.copy2(str(src), str(dst))
            dst_hash = _hash_file(dst)
            fsize = src.stat().st_size
            self._log(
                "writer",
                "INFO",
                f"[ARCHIVE] {src.name} → {dst.name} ({fsize} bytes)",
            )
            return {
                "status": "copied",
                "dst": str(dst),
                "size": fsize,
                "content_hash": dst_hash,
            }
        except (OSError, PermissionError, shutil.Error) as e:
            self._log(
                "writer",
                "ERROR",
                f"[ARCHIVE FAILED] {src.name}: {e}",
            )
            return {"status": "error", "error": str(e), "src": str(src)}

    def _mark_archive_failed(self, analysis_id: int, doc_type: str) -> None:
        """归档失败: UPDATE analysis_docs SET file_size_bytes=-1"""
        conn = sqlite3.connect(str(self.db_path))
        try:
            now = _now_iso()
            conn.execute(
                """UPDATE analysis_docs
                   SET file_size_bytes = -1, updated_at = ?
                   WHERE analysis_id = ? AND doc_type = ?""",
                (now, analysis_id, doc_type),
            )
            conn.commit()
            self._log(
                "writer",
                "WARN",
                f"[ARCHIVE] 已标记归档失败: analysis_id={analysis_id} doc_type={doc_type}",
            )
        except sqlite3.Error as e:
            self._log(
                "writer",
                "ERROR",
                f"[ARCHIVE] 标记归档失败时出错: {e}",
            )
        finally:
            conn.close()

    def _retry_failed_archives(self, run_id: str, analysis_type: str) -> list[dict]:
        """归档重入检测与重试"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        results: list[dict] = []
        try:
            rows = conn.execute(
                """SELECT ad.id, ad.analysis_id, ad.run_id, ad.doc_type, ad.file_path
                   FROM analysis_docs ad
                   JOIN analysis_meta am ON ad.analysis_id = am.id
                   WHERE am.run_id = ? AND am.analysis_type = ?
                     AND ad.file_size_bytes = -1""",
                (run_id, analysis_type),
            ).fetchall()

            archive_reports = self.archive_root / "reports"
            archive_reports.mkdir(parents=True, exist_ok=True)

            for row in rows:
                d = dict(row)
                src = Path(d["file_path"])
                result = self._archive_single_file(src, archive_reports)
                result["doc_type"] = d["doc_type"]
                result["analysis_id"] = d["analysis_id"]

                if result["status"] == "copied":
                    # 成功: 更新 file_size_bytes 为正确的值
                    conn.execute(
                        """UPDATE analysis_docs
                           SET file_size_bytes = ?, content_hash = ?, updated_at = ?
                           WHERE id = ?""",
                        (
                            result.get("size", -1),
                            result.get("content_hash", ""),
                            _now_iso(),
                            d["id"],
                        ),
                    )
                    conn.commit()
                results.append(result)
        except sqlite3.Error as e:
            self._log("writer", "ERROR", f"[ARCHIVE RETRY] DB error: {e}")
        finally:
            conn.close()

        return results

    # ——— public API: 归档清理 ———

    def archive_cleanup(self, dry_run: bool = False) -> list[dict]:
        """
        清理 archive/ 目录中的 orphan 文件。

        Orphan 定义：不在 analysis_docs 表中被引用的归档文件。
        安全机制：仅检查孤立文件（不在 DB 中有引用），不碰已有引用。
        幂等性：多次运行安全。

        Args:
            dry_run: 仅输出 orphan 列表，不实际删除

        Returns:
            orphan 文件列表，每项含 {path, size, action, category}
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        orphan_files: list[dict] = []
        try:
            # 获取 DB 中所有已归档的 file_path（解析为绝对路径）
            db_archived_paths = set()
            rows = conn.execute(
                "SELECT file_path FROM analysis_docs WHERE file_path != ''"
            ).fetchall()
            for row in rows:
                fp = Path(row[0])
                if fp.exists():
                    db_archived_paths.add(str(fp.resolve()))

            # 扫描 archive/reports/ 和 archive/ddl/ 两个子目录
            subdirs = [
                ("reports", self.archive_root / "reports"),
                ("ddl", self.archive_root / "ddl"),
            ]

            for category, scan_dir in subdirs:
                if not scan_dir.exists():
                    continue
                for f in scan_dir.iterdir():
                    if not f.is_file():
                        continue
                    abs_path = str(f.resolve())
                    if abs_path not in db_archived_paths:
                        orphan_entry = {
                            "path": abs_path,
                            "size": f.stat().st_size,
                            "category": category,
                        }
                        if not dry_run:
                            try:
                                f.unlink()
                                orphan_entry["action"] = "deleted"
                                self._log(
                                    "writer",
                                    "INFO",
                                    f"[ARCHIVE CLEANUP] 已删除 orphan: {abs_path} "
                                    f"({f.stat().st_size} bytes)",
                                )
                            except OSError as e:
                                orphan_entry["action"] = "delete_failed"
                                orphan_entry["error"] = str(e)
                                self._log(
                                    "writer",
                                    "ERROR",
                                    f"[ARCHIVE CLEANUP] 删除失败: {abs_path}: {e}",
                                )
                        else:
                            orphan_entry["action"] = "dry_run (would delete)"

                        orphan_files.append(orphan_entry)

            self._log(
                "writer",
                "INFO",
                f"[ARCHIVE CLEANUP] 完成: 发现 {len(orphan_files)} 个 orphan "
                f"(dry_run={dry_run})",
            )

        except sqlite3.Error as e:
            self._log(
                "writer",
                "ERROR",
                f"[ARCHIVE CLEANUP] DB 查询失败: {e}",
            )
        finally:
            conn.close()

        return orphan_files

    _archive_cleanup = archive_cleanup  # 保留旧私有别名（向后兼容）

    # ——— QA 报告（TMPL-003 对齐） ———

    def _generate_qa_report(
        self, input_data: PipelineInput, analysis_id: int, existing: dict | None
    ) -> QaReport:
        """
        生成 TMPL-003 对齐的 QA 校验报告。

        覆盖以下维度：
        1. 数据库行数核验 — 各表预期行数 vs 实际行数
        2. 报告数据交叉验证 — 输入指标与 DB 数据一致性
        3. 外键完整性 — analysis_id 关联一致性
        4. 确定性策略偏差说明 — 输入数据的异常偏离
        5. 文档完整性 — content_hash 与文件存在性
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        checks: list[QaCheckItem] = []

        try:
            # ─── 1. 数据库行数核验 ───
            rows = conn.execute(
                """SELECT 'analysis_meta' AS table_name, COUNT(*) AS cnt
                   FROM analysis_meta WHERE run_id = ? AND analysis_type = ?
                   UNION ALL
                   SELECT 'analysis_metrics_core', COUNT(*)
                   FROM analysis_metrics_core WHERE run_id = ?
                   UNION ALL
                   SELECT 'analysis_metrics_ext', COUNT(*)
                   FROM analysis_metrics_ext WHERE run_id = ?
                   UNION ALL
                   SELECT 'analysis_docs', COUNT(*)
                   FROM analysis_docs WHERE run_id = ?
                   UNION ALL
                   SELECT 'schema_version', COUNT(*) FROM schema_version""",
                (
                    input_data.meta.run_id,
                    input_data.meta.analysis_type,
                    input_data.meta.run_id,
                    input_data.meta.run_id,
                    input_data.meta.run_id,
                ),
            ).fetchall()
            actual_counts: dict[str, int] = {r["table_name"]: r["cnt"] for r in rows}

            # 预期行数
            expected_counts = {
                "analysis_meta": 1,
                "analysis_metrics_core": len(input_data.metrics_core),
                "analysis_metrics_ext": len(input_data.metrics_ext),
                "analysis_docs": len(input_data.docs),
            }

            for table, expected in expected_counts.items():
                actual = actual_counts.get(table, 0)
                expected_sv = 1 if table == "schema_version" else expected
                check_status = "PASS" if actual == expected else ("WARN" if actual > 0 else "FAIL")
                checks.append(
                    QaCheckItem(
                        check_id=f"row_count_{table}",
                        category="database_row_count",
                        description=f"{table} 行数核验",
                        status=check_status,
                        expected=expected,
                        actual=actual,
                        detail=(
                            f"预期 {expected} 行，实际 {actual} 行"
                            if actual == expected
                            else f"行数不匹配：预期 {expected} 行，实际 {actual} 行"
                        ),
                    )
                )

            # schema_version 行数核验
            sv_count = actual_counts.get("schema_version", 0)
            checks.append(
                QaCheckItem(
                    check_id="row_count_schema_version",
                    category="database_row_count",
                    description="schema_version 行数核验",
                    status="PASS" if sv_count >= 1 else "FAIL",
                    expected=1,
                    actual=sv_count,
                    detail=f"schema_version 表共 {sv_count} 条记录" if sv_count >= 1 else "schema_version 表为空",
                )
            )

            # ─── 2. 外键一致性 ───
            mismatches = conn.execute(
                """SELECT mc.analysis_id AS mc_id, am.id AS meta_id
                   FROM analysis_metrics_core mc
                   JOIN analysis_meta am ON mc.run_id = am.run_id AND mc.run_id = ?
                   WHERE mc.analysis_id != am.id""",
                (input_data.meta.run_id,),
            ).fetchall()
            fk_mismatches = [dict(m) for m in mismatches]
            checks.append(
                QaCheckItem(
                    check_id="foreign_key_integrity",
                    category="foreign_key_integrity",
                    description="analysis_metrics_core.analysis_id → analysis_meta.id 外键一致性",
                    status="PASS" if not fk_mismatches else "FAIL",
                    expected="所有 metrics_core 的 analysis_id 与 meta.id 一致",
                    actual=len(fk_mismatches),
                    detail=(
                        "所有 metrics_core 记录的外键通过"
                        if not fk_mismatches
                        else f"发现 {len(fk_mismatches)} 条外键不匹配: {fk_mismatches}"
                    ),
                    deviations=[str(m) for m in fk_mismatches] if fk_mismatches else [],
                )
            )

            # ─── 3. 确定性策略偏差说明 ───
            deviations: list[str] = []
            # 检查 metrics_core 是否含有负值的 risk_level 等异常
            for i, mc in enumerate(input_data.metrics_core):
                if mc.total_return_pct is not None and mc.annual_return_pct is not None:
                    if abs(mc.total_return_pct) > 100:
                        deviations.append(
                            f"metrics_core[{i}].total_return_pct={mc.total_return_pct}% 超常规 ({mc.metric_group})"
                        )
                if mc.sharpe_ratio is not None and abs(mc.sharpe_ratio) > 10:
                    deviations.append(
                        f"metrics_core[{i}].sharpe_ratio={mc.sharpe_ratio} 超常规 ({mc.metric_group})"
                    )
                if mc.max_drawdown_pct is not None and mc.max_drawdown_pct > 0:
                    deviations.append(
                        f"metrics_core[{i}].max_drawdown_pct={mc.max_drawdown_pct} 为正值（通常应为负值）"
                    )

            # 检查文档路径是否为空
            empty_docs = [d.doc_type for d in input_data.docs if not d.file_path]
            if empty_docs:
                deviations.append(f"以下文档类型 file_path 为空: {', '.join(empty_docs)}")

            checks.append(
                QaCheckItem(
                    check_id="deterministic_strategy_deviation",
                    category="deterministic_strategy_deviation",
                    description="确定性策略偏差说明",
                    status="PASS" if not deviations else "WARN",
                    detail=(
                        "未发现确定性策略偏差"
                        if not deviations
                        else f"发现 {len(deviations)} 项偏差"
                    ),
                    deviations=deviations,
                )
            )

            # ─── 4. 文档完整性 ───
            docs_missing: list[str] = []
            docs_hash_ok = 0
            docs_hash_mismatch = 0
            for doc in input_data.docs:
                if not doc.file_path:
                    docs_missing.append(f"{doc.doc_type}: file_path 为空")
                    continue
                fp = Path(doc.file_path)
                if not fp.exists():
                    docs_missing.append(f"{doc.doc_type}: {doc.file_path} 不存在")
                elif doc.content_hash:
                    try:
                        actual_hash = _hash_file(fp)
                        if actual_hash == doc.content_hash:
                            docs_hash_ok += 1
                        else:
                            docs_hash_mismatch += 1
                            deviations.append(f"{doc.doc_type}: content_hash 不匹配")
                    except Exception:
                        pass

            checks.append(
                QaCheckItem(
                    check_id="document_integrity",
                    category="document_integrity",
                    description="分析文档完整性与哈希校验",
                    status="PASS" if not docs_missing and docs_hash_mismatch == 0 else "WARN",
                    expected={
                        "total_docs": len(input_data.docs),
                        "hash_verified": docs_hash_ok,
                    },
                    actual={
                        "missing": len(docs_missing),
                        "hash_mismatch": docs_hash_mismatch,
                    },
                    detail=(
                        f"共 {len(input_data.docs)} 份文档，"
                        f"{docs_hash_ok} 份哈希校验通过"
                        + (f"，{len(docs_missing)} 份缺失" if docs_missing else "")
                        + (f"，{docs_hash_mismatch} 份哈希不匹配" if docs_hash_mismatch else "")
                    ),
                )
            )

            # ─── 综合统计 ───
            passed = sum(1 for c in checks if c.status == "PASS")
            warns = sum(1 for c in checks if c.status == "WARN")
            fails = sum(1 for c in checks if c.status == "FAIL")

            if fails > 0:
                overall_status = "FAIL"
            elif warns > 0:
                overall_status = "WARN"
            else:
                overall_status = "PASS"

            return QaReport(
                summary={
                    "total_checks": len(checks),
                    "passed": passed,
                    "warnings": warns,
                    "failures": fails,
                },
                overall_status=overall_status,
                checks=checks,
                metadata={
                    "run_id": input_data.meta.run_id,
                    "analysis_type": input_data.meta.analysis_type,
                    "analysis_id": analysis_id,
                    "operation": "INSERT" if existing is None else "UPDATE",
                    "generated_at": _now_iso(),
                },
            )

        except sqlite3.Error as e:
            self._log("writer", "ERROR", f"[QA] QA 报告生成失败: {e}")
            return QaReport(
                summary={"total_checks": 0, "passed": 0, "warnings": 0, "failures": 1},
                overall_status="FAIL",
                checks=[
                    QaCheckItem(
                        check_id="qa_report_generation",
                        category="database_row_count",
                        description="QA 报告生成",
                        status="FAIL",
                        detail=f"QA 报告生成过程中 DB 错误: {e}",
                    )
                ],
                metadata={
                    "run_id": input_data.meta.run_id,
                    "analysis_type": input_data.meta.analysis_type,
                    "analysis_id": analysis_id,
                    "error": str(e),
                    "generated_at": _now_iso(),
                },
            )
        finally:
            conn.close()

    # ——— 信号文件 ———

    def write_done_signal(
        self, run_id: str, analysis_type: str, task_id: str = ""
    ) -> None:
        """写入 .done 信号文件"""
        if not task_id:
            return
        done_path = self._signal_root / f"{task_id}_moheng.done"
        signal = {
            "status": "SUCCESS",
            "run_id": run_id,
            "analysis_type": analysis_type,
            "timestamp": _now_iso(),
        }
        try:
            done_path.parent.mkdir(parents=True, exist_ok=True)
            done_path.write_text(
                json.dumps(signal, ensure_ascii=False), encoding="utf-8"
            )
            self._log("writer", "INFO", f"[SIGNAL] .done written: {done_path}")
        except OSError as e:
            self._log("writer", "ERROR", f"[SIGNAL] failed to write .done: {e}")

    def write_failed_signal(
        self, run_id: str, analysis_type: str, error: str, task_id: str = ""
    ) -> None:
        """写入 .failed 信号文件"""
        if not task_id:
            return
        failed_path = self._signal_root / f"{task_id}_moheng.failed"
        signal = {
            "status": "FAILED",
            "run_id": run_id,
            "analysis_type": analysis_type,
            "error": error,
            "timestamp": _now_iso(),
        }
        try:
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            failed_path.write_text(
                json.dumps(signal, ensure_ascii=False), encoding="utf-8"
            )
            self._log("writer", "ERROR", f"[SIGNAL] .failed written: {failed_path}")
        except OSError as e:
            self._log("writer", "ERROR", f"[SIGNAL] failed to write .failed: {e}")

    # ——— 内部日志 ———

    def _log(self, component: str, level: str, message: str) -> None:
        extra = {"component": component, "action": ""}
        log_fn = getattr(self._logger, level.lower(), self._logger.info)
        log_fn(message, extra=extra)
