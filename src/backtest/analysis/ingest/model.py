"""model.py — Pydantic 数据模型定义

P0 MVP: 完整 Pydantic 模型（含 _now_iso）
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ——— 辅助函数 ———

def _now_iso() -> str:
    """返回 ISO8601 +08:00 时间戳"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S%z")


def _hash_file(path: str | Path) -> str:
    """SHA256 文件哈希"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ——— Type Literals ———

ANALYSIS_TYPES = Literal[
    "summary", "deep_analysis", "tech_review", "validation", "resolution"
]
METRIC_GROUPS = Literal["daily", "weekly", "param_sweep", "factor_ic"]
DOC_TYPES = Literal[
    "summary_report", "analysis_report", "tech_review", "validation", "resolution"
]
VERSION_STATUSES = Literal["draft", "reviewed", "final", "archived"]
RISK_LEVELS = Literal["low", "mid", "high"]


# ——— Pydantic 模型 ———


class AnalysisMeta(BaseModel):
    """analysis_meta 表写入模型"""

    run_id: str = Field(..., min_length=1)
    analysis_type: ANALYSIS_TYPES
    author: str = "moheng"
    version_schema: str = "1.0"
    version_content: int = 1
    version_status: VERSION_STATUSES = "draft"
    parent_session_id: int | None = None
    tags: list[str] = Field(default_factory=list)

    def meta_to_insert_sql(self) -> tuple[str, list[Any]]:
        """生成 INSERT 语句和参数"""
        sql = """INSERT INTO analysis_meta
            (run_id, parent_session_id, tags, version_schema, version_content,
             version_status, author, analysis_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        now = _now_iso()
        params = [
            self.run_id,
            self.parent_session_id,
            ",".join(self.tags) if self.tags else "",
            self.version_schema,
            self.version_content,
            self.version_status,
            self.author,
            self.analysis_type,
            now,
            now,
        ]
        return sql, params

    def meta_to_update_sql(self, meta_id: int) -> tuple[str, list[Any]]:
        """生成 UPDATE 语句和参数（幂等 draft/final → reviewed）"""
        sql = """UPDATE analysis_meta
            SET version_content = version_content + 1,
                version_status = ?,
                tags = ?,
                author = ?,
                updated_at = ?
            WHERE id = ?"""
        now = _now_iso()
        params = [
            self.version_status,
            ",".join(self.tags) if self.tags else "",
            self.author,
            now,
            meta_id,
        ]
        return sql, params


class MetricsCore(BaseModel):
    """analysis_metrics_core 表写入模型"""

    analysis_id: int | None = None  # 写入前未知
    run_id: str
    metric_group: METRIC_GROUPS = "daily"
    total_return_pct: float | None = None
    annual_return_pct: float | None = None
    final_equity: float | None = None
    total_pnl: float | None = None
    benchmark_return_pct: float | None = None
    excess_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    annual_volatility_pct: float | None = None
    sharpe_ratio: float | None = None
    calmar_ratio: float | None = None
    sortino_ratio: float | None = None
    var_95_pct: float | None = None
    total_trades: int | None = None
    winning_trades: int | None = None
    losing_trades: int | None = None
    win_rate_pct: float | None = None
    total_profit: float | None = None
    total_loss: float | None = None
    profit_loss_ratio: float | None = None
    max_consecutive_wins: int | None = None
    max_consecutive_losses: int | None = None
    max_single_win: float | None = None
    max_single_loss: float | None = None
    verdict: str | None = None
    risk_level: RISK_LEVELS | None = None
    core_issue: str | None = None
    improvement_potential: str | None = None

    def to_insert_sql(self) -> tuple[str, list[Any]]:
        """生成 INSERT 语句和参数"""
        sql = """INSERT INTO analysis_metrics_core (
            analysis_id, run_id, metric_group,
            total_return_pct, annual_return_pct, final_equity, total_pnl,
            benchmark_return_pct, excess_return_pct,
            max_drawdown_pct, annual_volatility_pct,
            sharpe_ratio, calmar_ratio, sortino_ratio, var_95_pct,
            total_trades, winning_trades, losing_trades, win_rate_pct,
            total_profit, total_loss, profit_loss_ratio,
            max_consecutive_wins, max_consecutive_losses,
            max_single_win, max_single_loss,
            verdict, risk_level, core_issue, improvement_potential
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        params = [
            self.analysis_id,
            self.run_id,
            self.metric_group,
            self.total_return_pct,
            self.annual_return_pct,
            self.final_equity,
            self.total_pnl,
            self.benchmark_return_pct,
            self.excess_return_pct,
            self.max_drawdown_pct,
            self.annual_volatility_pct,
            self.sharpe_ratio,
            self.calmar_ratio,
            self.sortino_ratio,
            self.var_95_pct,
            self.total_trades,
            self.winning_trades,
            self.losing_trades,
            self.win_rate_pct,
            self.total_profit,
            self.total_loss,
            self.profit_loss_ratio,
            self.max_consecutive_wins,
            self.max_consecutive_losses,
            self.max_single_win,
            self.max_single_loss,
            self.verdict,
            self.risk_level,
            self.core_issue,
            self.improvement_potential,
        ]
        return sql, params


class MetricsExt(BaseModel):
    """analysis_metrics_ext 表写入模型"""

    analysis_id: int | None = None
    run_id: str
    metric_group: str | None = None
    metric_name: str
    metric_value: float
    metric_label: str | None = None

    def to_insert_sql(self) -> tuple[str, list[Any]]:
        sql = """INSERT INTO analysis_metrics_ext (
            analysis_id, run_id, metric_group, metric_name, metric_value, metric_label
        ) VALUES (?, ?, ?, ?, ?, ?)"""
        params = [
            self.analysis_id,
            self.run_id,
            self.metric_group,
            self.metric_name,
            self.metric_value,
            self.metric_label,
        ]
        return sql, params


class AnalysisDoc(BaseModel):
    """analysis_docs 表写入模型"""

    analysis_id: int | None = None
    run_id: str
    doc_type: DOC_TYPES
    file_path: str = Field(..., min_length=1)
    content_hash: str | None = None
    file_size_bytes: int = 0
    word_count: int | None = None

    def to_insert_sql(self) -> tuple[str, list[Any]]:
        sql = """INSERT INTO analysis_docs (
            analysis_id, run_id, doc_type, file_path,
            content_hash, file_size_bytes, word_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?)"""
        params = [
            self.analysis_id,
            self.run_id,
            self.doc_type,
            self.file_path,
            self.content_hash,
            self.file_size_bytes,
            self.word_count,
        ]
        return sql, params


class PipelineInput(BaseModel):
    """管道输入 —— 所有阶段共享的上下文"""

    meta: AnalysisMeta
    metrics_core: list[MetricsCore] = Field(..., min_length=1, max_length=5)
    metrics_ext: list[MetricsExt] = Field(default_factory=list)
    docs: list[AnalysisDoc] = Field(..., min_length=1, max_length=6)

    @field_validator("metrics_core")
    @classmethod
    def check_metrics_core_dedup(cls, v: list[MetricsCore]) -> list[MetricsCore]:
        groups = [m.metric_group for m in v]
        if len(groups) != len(set(groups)):
            raise ValueError("metrics_core: duplicate metric_group")
        return v

    @field_validator("docs")
    @classmethod
    def check_docs_dedup(cls, v: list[AnalysisDoc]) -> list[AnalysisDoc]:
        types = [d.doc_type for d in v]
        if len(types) != len(set(types)):
            raise ValueError("docs: duplicate doc_type")
        return v


# ——— 结果模型 ———


class CheckResult(BaseModel):
    """单条检查结果"""

    name: str
    passed: bool
    level: Literal["PASS", "WARN", "ERROR"]
    detail: str
    value: Any = None
    expected: Any = None


class ValidationResult(BaseModel):
    """Validator 综合结果"""

    passed: bool
    level: Literal["PASS", "WARN", "ERROR"]
    checks: list[CheckResult]


class QaCheckItem(BaseModel):
    """QA 检查条目（TMPL-003 对齐）"""

    check_id: str
    category: Literal[
        "database_row_count",
        "cross_validation",
        "foreign_key_integrity",
        "deterministic_strategy_deviation",
        "document_integrity",
    ]
    description: str
    status: Literal["PASS", "WARN", "FAIL"]
    expected: Any = None
    actual: Any = None
    detail: str = ""
    deviations: list[str] = Field(default_factory=list)


class QaReport(BaseModel):
    """QA 校验报告（TMPL-003 对齐）"""

    summary: dict[str, int]  # {"total_checks", "passed", "warnings", "failures"}
    overall_status: Literal["PASS", "WARN", "FAIL"]
    checks: list[QaCheckItem]
    metadata: dict[str, Any] = Field(default_factory=dict)


class WriteResult(BaseModel):
    """Writer 写入结果"""

    status: str  # "SUCCESS" | "WARN" | "ERROR"
    operation: str  # "INSERT" | "UPDATE" | "SKIP"
    analysis_meta_id: int | None = None
    rows_written: dict[str, int] = Field(default_factory=dict)
    doc_archive_results: list[dict] = Field(default_factory=list)
    qa_report: QaReport | None = None

    model_config = {"extra": "allow"}
