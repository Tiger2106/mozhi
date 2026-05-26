"""__main__.py — CLI 入口

使用方式:
    python -m src.backtest.analysis.ingest --run-id <UUID> --analysis-type summary

参数:
    --run-id         回测运行 UUID (必填)
    --analysis-type  分析类型 (必填, 枚举: summary/deep_analysis/tech_review/validation/resolution)
    --dry-run        试运行模式
    --qa-verify      输出 QA 校验报告
    --force          强制覆盖已有 final 记录
    --timeout        管道超时秒数 (默认: 65)
    --verbose        详细日志输出
    --db-path        数据库路径 (默认: 搜索 pyproject.toml -> data/backtest.db)
    --archive-root   归档根目录 (默认: 搜索 pyproject.toml -> archive/)
    --archive-cleanup 清理 orphan 归档文件
    --task-id        任务 ID (用于写入 .done/.failed 信号文件)
"""

from __future__ import annotations

import argparse
import json
import sys

from .pipeline import ingest as _ingest
from .writer import Writer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ingest_analysis: 回测分析数据入库管道"
    )
    parser.add_argument(
        "--run-id", required=True, help="回测运行 UUID"
    )
    parser.add_argument(
        "--analysis-type", required=True,
        choices=["summary", "deep_analysis", "tech_review", "validation", "resolution"],
        help="分析类型",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="试运行模式: 只校验不写入"
    )
    parser.add_argument(
        "--qa-verify", action="store_true", help="输出 QA 校验报告 (JSON)"
    )
    parser.add_argument(
        "--force", action="store_true", help="强制覆盖已存在 final 记录"
    )
    parser.add_argument(
        "--timeout", type=int, default=65, help="管道超时秒数 (default: 65)"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="详细日志输出"
    )
    parser.add_argument(
        "--archive-cleanup", action="store_true", help="清理 orphan 归档文件"
    )
    parser.add_argument(
        "--db-path", default=None, help="数据库路径 (默认: data/backtest.db)"
    )
    parser.add_argument(
        "--archive-root", default=None, help="归档根目录 (默认: archive/)"
    )
    parser.add_argument(
        "--task-id", default="", help="任务 ID (用于写入 .done/.failed 信号文件)"
    )

    args = parser.parse_args()

    # 归档清理模式
    if args.archive_cleanup:
        from .config import resolve_archive_root, resolve_db_path

        db_path = resolve_db_path(args.db_path)
        archive_root = resolve_archive_root(args.archive_root)
        writer = Writer(db_path, archive_root, verbose=args.verbose)
        try:
            result = writer.archive_cleanup(dry_run=args.dry_run)
            output = {
                "status": "SUCCESS",
                "orphan_count": len(result),
                "dry_run": args.dry_run,
                "orphan_files": result,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            sys.exit(0)
        except Exception as e:
            import traceback
            output = {
                "status": "ERROR",
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            sys.exit(1)

    # 正常管道
    result = _ingest(
        run_id=args.run_id,
        analysis_type=args.analysis_type,
        dry_run=args.dry_run,
        qa_verify=args.qa_verify,
        force=args.force,
        timeout=args.timeout,
        verbose=args.verbose,
        db_path=args.db_path,
        archive_root=args.archive_root,
        task_id=args.task_id,
    )

    print(json.dumps(dict(result), ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if result.get("status") in ("SUCCESS", "WARN", "DRY_RUN") else 1)


if __name__ == "__main__":
    main()
