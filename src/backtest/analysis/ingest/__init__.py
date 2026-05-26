"""src/backtest/analysis/ingest/__init__.py

public API:
    ingest(run_id, analysis_type, ...) -> PipelineResult
    Pipeline 类
    PipelineResult 结果类型
"""

from .config import resolve_archive_root, resolve_db_path
from .model import QaCheckItem, QaReport
from .pipeline import Pipeline, PipelineResult, ingest
from .writer import Writer

__all__ = [
    "Pipeline", "PipelineResult", "ingest",
    "QaCheckItem", "QaReport",
    "archive_cleanup",
]
__version__ = "1.0.0"


def archive_cleanup(
    dry_run: bool = False,
    db_path: str | None = None,
    archive_root: str | None = None,
    verbose: bool = False,
) -> list[dict]:
    """
    清理 archive/ 目录中的 orphan 文件。

    Orphan 定义：不在 analysis_docs 表中被引用的归档文件。
    安全机制：仅检查孤立文件，不碰已有引用。
    幂等性：多次运行安全。

    Args:
        dry_run: 仅输出 orphan 列表，不实际删除
        db_path: 数据库路径（默认自动推断）
        archive_root: 归档根目录（默认自动推断）
        verbose: 详细日志输出

    Returns:
        orphan 文件列表，每项含 {path, size, action, category}
    """
    resolved_db = resolve_db_path(db_path)
    resolved_archive = resolve_archive_root(archive_root)

    writer = Writer(
        db_path=resolved_db,
        archive_root=resolved_archive,
        verbose=verbose,
    )
    return writer.archive_cleanup(dry_run=dry_run)
