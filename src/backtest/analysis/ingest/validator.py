"""validator.py — 数据校验 + 交叉核验

P0 MVP: 前置/空值/枚举/交叉核验/文档存在/幂等性检查
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

from .model import CheckResult, PipelineInput, ValidationResult


class ValidationError(Exception):
    """校验阶段异常"""

    def __init__(self, message: str, phase: str = "validator", details: dict | None = None):
        super().__init__(message)
        self.phase = phase
        self.details = details or {}


class Validator:
    """数据校验 + 交叉核验"""

    # 交叉核验的偏差阈值
    CROSS_VALIDATE_THRESHOLD_WARN = 0.0001  # 0.01%
    CROSS_VALIDATE_THRESHOLD_ERROR = 0.001  # 0.1%

    # 需要交叉核验的字段映射: (perf_key, input_attr)
    CROSS_FIELDS = [
        ("total_return", "total_return_pct"),
        ("annualized_return", "annual_return_pct"),
        ("benchmark_return", "benchmark_return_pct"),
        ("excess_return", "excess_return_pct"),
        ("max_drawdown", "max_drawdown_pct"),
        ("sharpe_ratio", "sharpe_ratio"),
        ("calmar_ratio", "calmar_ratio"),
        ("sortino_ratio", "sortino_ratio"),
        ("volatility", "annual_volatility_pct"),
        ("win_rate", "win_rate_pct"),
        ("total_trades", "total_trades"),
        ("max_consecutive_wins", "max_consecutive_wins"),
        ("max_consecutive_losses", "max_consecutive_losses"),
    ]

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def validate(self, input_data: PipelineInput) -> ValidationResult:
        """
        执行所有校验项目，每条检查独立评分。

        返回 ValidationResult，包含所有检查结果。
        """
        checks: list[CheckResult] = []

        # 1. 前置: run_id 在 backtest_run 中存在且 status='done'
        checks.append(self._check_run_id_exists(input_data.meta.run_id))

        # 2. 必填字段非空
        checks.append(self._check_not_null(input_data))

        # 3. 枚举值合法性
        checks.append(self._check_enum_values(input_data))

        # 4. 文档存在
        checks.append(self._check_docs_exist(input_data))

        # 5. 幂等性检查（仅检查存在性，不阻断）
        checks.append(self._check_idempotent(input_data.meta.run_id, input_data.meta.analysis_type))

        # 综合判定
        has_errors = any(c.level == "ERROR" for c in checks)
        has_warns = any(c.level == "WARN" for c in checks)

        if has_errors:
            level = "ERROR"
            passed = False
        elif has_warns:
            level = "WARN"
            passed = True
        else:
            level = "PASS"
            passed = True

        return ValidationResult(passed=passed, level=level, checks=checks)

    def validate_with_perf(
        self, input_data: PipelineInput, perf_row: dict | None
    ) -> ValidationResult:
        """执行全部校验（含交叉核验）"""
        result = self.validate(input_data)
        if perf_row is not None:
            cr = self._check_cross_validate(input_data, perf_row)
            result.checks.append(cr)
            # 重新判定
            has_errors = any(c.level == "ERROR" for c in result.checks)
            has_warns = any(c.level == "WARN" for c in result.checks)
            if has_errors:
                result.level = "ERROR"
                result.passed = False
            elif has_warns:
                result.level = "WARN"
                result.passed = True
        return result

    # ——— 内部检查方法 ———

    def _check_run_id_exists(self, run_id: str) -> CheckResult:
        """前置校验: run_id 在 backtest_run 中存在且 status='done'"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(
                    "SELECT id, run_name, status FROM backtest_run WHERE id = ?",
                    (run_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return CheckResult(
                        name="run_id_exists",
                        passed=False,
                        level="ERROR",
                        detail=f"run_id {run_id} 在 backtest_run 中不存在",
                        value=run_id,
                        expected="exists and status='done'",
                    )
                if row["status"] != "done":
                    return CheckResult(
                        name="run_id_exists",
                        passed=False,
                        level="ERROR",
                        detail=f"run_id {run_id} 的 status='{row['status']}'，需要 'done'",
                        value=row["status"],
                        expected="done",
                    )
                return CheckResult(
                    name="run_id_exists",
                    passed=True,
                    level="PASS",
                    detail=f"run_id {run_id} 存在且状态 done",
                )
            finally:
                conn.close()
        except sqlite3.Error as e:
            return CheckResult(
                name="run_id_exists",
                passed=False,
                level="ERROR",
                detail=f"DB 查询失败: {e}",
                value=run_id,
            )

    def _check_not_null(self, input_data: PipelineInput) -> CheckResult:
        """前置校验: 必填字段非空"""
        issues: list[str] = []
        if not input_data.meta.run_id:
            issues.append("meta.run_id 为空")
        if not input_data.meta.analysis_type:
            issues.append("meta.analysis_type 为空")
        if not input_data.meta.version_status:
            issues.append("meta.version_status 为空")
        if not input_data.metrics_core:
            issues.append("metrics_core 为空")
        if not input_data.docs:
            issues.append("docs 为空")

        if issues:
            return CheckResult(
                name="not_null",
                passed=False,
                level="ERROR",
                detail="; ".join(issues),
                value=input_data.model_dump(),
                expected="所有必填字段非空",
            )
        return CheckResult(
            name="not_null",
            passed=True,
            level="PASS",
            detail="所有必填字段非空",
        )

    def _check_enum_values(self, input_data: PipelineInput) -> CheckResult:
        """校验: analysis_type 枚举值合法"""
        valid_types = {"summary", "deep_analysis", "tech_review", "validation", "resolution"}
        valid_statuses = {"draft", "reviewed", "final", "archived"}

        issues: list[str] = []
        if input_data.meta.analysis_type not in valid_types:
            issues.append(
                f"analysis_type={input_data.meta.analysis_type} 不在有效枚举中"
            )
        if input_data.meta.version_status not in valid_statuses:
            issues.append(
                f"version_status={input_data.meta.version_status} 不在有效枚举中"
            )

        if issues:
            return CheckResult(
                name="enum_values",
                passed=False,
                level="ERROR",
                detail="; ".join(issues),
                value=input_data.meta.analysis_type,
                expected=f"之一: {valid_types}",
            )
        return CheckResult(
            name="enum_values",
            passed=True,
            level="PASS",
            detail="枚举值均合法",
        )

    def _check_cross_validate(
        self, input_data: PipelineInput, perf_row: dict
    ) -> CheckResult:
        """
        校验: 输入指标 vs performance_summary 交叉核验

        - 偏差 ≤ 0.01% → PASS
        - 偏差 0.01% ~ 0.1% → WARN
        - 偏差 > 0.1% → ERROR
        """
        deviations: list[str] = []
        max_deviation = 0.0
        worst_field = ""

        if not input_data.metrics_core:
            return CheckResult(
                name="cross_validate",
                passed=False,
                level="WARN",
                detail="metrics_core 为空，跳过交叉核验",
            )

        mc = input_data.metrics_core[0]

        for perf_key, attr_name in self.CROSS_FIELDS:
            perf_val = perf_row.get(perf_key)
            input_val = getattr(mc, attr_name, None)

            if perf_val is None and input_val is None:
                continue
            if perf_val is None or input_val is None:
                deviations.append(
                    f"{attr_name}: perf={perf_val} vs input={input_val} (一边为 null)"
                )
                continue

            # 计算相对偏差
            try:
                ref = abs(float(perf_val)) if float(perf_val) != 0 else 1.0
                deviation = abs(float(input_val) - float(perf_val)) / ref
            except (ValueError, TypeError, ZeroDivisionError):
                deviations.append(f"{attr_name}: 无法计算偏差")
                continue

            if deviation > max_deviation:
                max_deviation = deviation
                worst_field = attr_name

            if deviation > self.CROSS_VALIDATE_THRESHOLD_ERROR:
                deviations.append(
                    f"{attr_name}: input={input_val} vs DB={perf_val}, "
                    f"deviation={deviation*100:.4f}%"
                )
            elif deviation > self.CROSS_VALIDATE_THRESHOLD_WARN:
                deviations.append(
                    f"{attr_name}: input={input_val} vs DB={perf_val}, "
                    f"deviation={deviation*100:.4f}%"
                )

        if not deviations:
            return CheckResult(
                name="cross_validate",
                passed=True,
                level="PASS",
                detail="所有字段交叉核验通过",
            )

        # 判定最严重的偏差
        if max_deviation > self.CROSS_VALIDATE_THRESHOLD_ERROR:
            return CheckResult(
                name="cross_validate",
                passed=False,
                level="ERROR",
                detail=f"交叉核验严重偏差: {worst_field} deviation={max_deviation*100:.4f}% "
                       f"({' | '.join(deviations[:3])})",
                value=max_deviation,
                expected=f"≤ {self.CROSS_VALIDATE_THRESHOLD_ERROR*100}%",
            )
        else:
            return CheckResult(
                name="cross_validate",
                passed=True,
                level="WARN",
                detail=f"交叉核验轻微偏差: {worst_field} deviation={max_deviation*100:.4f}% "
                       f"({' | '.join(deviations[:3])})",
                value=max_deviation,
                expected=f"≤ {self.CROSS_VALIDATE_THRESHOLD_WARN*100}%",
            )

    def _check_docs_exist(self, input_data: PipelineInput) -> CheckResult:
        """校验: analysis_docs.file_path 对应文件存在于磁盘"""
        missing: list[str] = []
        for doc in input_data.docs:
            if not doc.file_path:
                continue
            p = Path(doc.file_path)
            if not p.exists():
                missing.append(f"{doc.doc_type}: {doc.file_path}")

        if missing:
            return CheckResult(
                name="docs_exist",
                passed=False,
                level="WARN",
                detail=f"以下文档文件不存在: {'; '.join(missing)}",
                value=missing,
                expected="所有文档文件路径有效",
            )
        return CheckResult(
            name="docs_exist",
            passed=True,
            level="PASS",
            detail="所有文档文件存在于磁盘",
        )

    def _check_idempotent(self, run_id: str, analysis_type: str) -> CheckResult:
        """幂等性检查 — 返回已存在记录的状态"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(
                    """SELECT id, version_status, version_content
                       FROM analysis_meta
                       WHERE run_id = ? AND analysis_type = ?
                       ORDER BY id DESC LIMIT 1""",
                    (run_id, analysis_type),
                )
                row = cur.fetchone()
                if row is None:
                    return CheckResult(
                        name="idempotent",
                        passed=True,
                        level="PASS",
                        detail=f"run_id={run_id} analysis_type={analysis_type}: 无已有记录，将 INSERT",
                        value=None,
                    )
                return CheckResult(
                    name="idempotent",
                    passed=True,
                    level="PASS" if row["version_status"] == "draft" else "WARN",
                    detail=f"已有记录 id={row['id']} status={row['version_status']} "
                           f"content={row['version_content']}",
                    value=dict(row),
                )
            finally:
                conn.close()
        except sqlite3.Error as e:
            return CheckResult(
                name="idempotent",
                passed=False,
                level="WARN",
                detail=f"幂等检查 DB 查询失败: {e}",
            )
