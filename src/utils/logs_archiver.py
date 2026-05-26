#!/usr/bin/env python3
"""
logs_archiver.py — 日志归档脚本
墨家投资室 · 墨衡 (moheng)
创建时间：2026-05-07 13:30 GMT+8
版本：v1.0
搬迁至 mozhi_platform: 2026-05-15

功能：
  1. 扫描 logs/ 下所有 .log 文件
     - 单文件 >50MB OR 文件修改日期 >7天 → 压缩到 archive/logs/YYYYMM/
  2. 清理 archive/logs/ 下超过180天的归档包（长期保留策略）

核心逻辑：
  [归档]
    1. 遍历 logs/ 下所有 .log 文件（含子目录）
    2. 过滤条件：文件大小 >50MB 或 修改时间 >7天
    3. 按文件修改时间的 YYYYMM 分组打包为 tar.gz
    4. 幂等：已归档文件已删除，不会重复处理
  [长期清理]
    1. 扫描 archive/logs/YYYYMM/ 子目录
    2. 过滤 >180天 的月份目录
    3. 整体删除过期月份目录

使用统一日志模块：phase1_core.logging_config

用法：
  python src/utils/logs_archiver.py
  python src/utils/logs_archiver.py --dry-run
  python src/utils/logs_archiver.py --skip-cleanup
  python src/utils/logs_archiver.py --cleanup-only
"""

import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phase1_core.logging_config import setup_logger, setup_root_logger
from config import SHANGHAI_TZ

# ── 配置 ──
LOGS_DIR = Path(r"C:\Users\17699\mo_zhi_sharereports\logs")
ARCHIVE_DIR = Path(r"C:\Users\17699\mo_zhi_sharereports\archive\logs")
RETENTION_DAYS = 7          # 源文件保留期（之后归档并从源目录删除）
SIZE_THRESHOLD_MB = 50       # 单文件超过此大小则归档
ARCHIVE_RETENTION_DAYS = 180  # 归档包保留期（之后从archive/logs/删除）

TZ = SHANGHAI_TZ

# ── 日志 ──
log = setup_logger("logs_archiver", "logs_archiver.log")


# =============================================
# 工具函数
# =============================================

def get_file_month(file_path: Path) -> str:
    """根据文件修改时间返回 YYYYMM 字符串"""
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=TZ)
    return mtime.strftime("%Y%m")


def should_archive_by_size(file_path: Path) -> bool:
    """判断文件是否超过大小阈值"""
    size_mb = file_path.stat().st_size / (1024 * 1024)
    return size_mb > SIZE_THRESHOLD_MB


def should_archive_by_age(file_path: Path, cutoff: datetime) -> bool:
    """判断文件修改时间是否超过保留期"""
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=TZ)
    return mtime < cutoff


def _collect_log_files(logs_dir: Path, cutoff: datetime) -> list[tuple[Path, str]]:
    """
    收集所有需要归档的 .log 文件。
    返回 [(file_path, archive_month)] 列表。
    """
    pending: list[tuple[Path, str]] = []

    for f in logs_dir.rglob("*.log"):
        if not f.is_file():
            continue

        # 跳过子目录中的 alerts/ daily/ 等特殊目录（仅处理根目录直接下的 .log）
        # 但保留子目录中的 .log（如 monitoring/ 下）
        # 判断是否为顶级 .log（不在特殊子目录中）
        relative = f.relative_to(logs_dir)
        top_level_subdirs = {"alerts", "daily", "daily_xuanzhi", "monitoring", "phase_2_2_adapter", "webhook_tests"}
        
        # 如果路径第一段是特殊子目录名，则跳过（不处理这些系统日志）
        if len(relative.parts) > 1 and relative.parts[0] in top_level_subdirs:
            log.debug(f"跳过系统日志目录: {f}")
            continue

        archive_month = get_file_month(f)

        if should_archive_by_size(f):
            log.info(f"标记归档（大小超限 {SIZE_THRESHOLD_MB}MB）: {f}")
            pending.append((f, archive_month))
        elif should_archive_by_age(f, cutoff):
            log.info(f"标记归档（超过{RETENTION_DAYS}天）: {f}")
            pending.append((f, archive_month))
        else:
            log.debug(f"跳过（未过期）: {f}")

    return pending


def _build_tar_for_month(
    archive_month: str,
    files: list[Path],
    arc_prefix: str,
) -> Path:
    """构建月度 tar.gz 文件，返回文件路径"""
    archive_subdir = ARCHIVE_DIR / archive_month
    archive_subdir.mkdir(parents=True, exist_ok=True)

    tar_name = f"logs_{archive_month}.tar.gz"
    tar_path = archive_subdir / tar_name

    # 创建临时 tar.gz，避免写入一半崩坏
    fd, tmp_path_str = tempfile.mkstemp(
        suffix=".tar.gz",
        prefix=f"logs_{archive_month}_",
        dir=str(archive_subdir),
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        with tarfile.open(str(tmp_path), "w:gz") as tar:
            for f in files:
                # 保留相对路径作为 arcname
                rel = f.relative_to(LOGS_DIR)
                tar.add(str(f), arcname=f"{arc_prefix}/{rel.as_posix()}")

        if tar_path.exists():
            tar_path.unlink()
        shutil.move(str(tmp_path), str(tar_path))
        log.info(f"归档包已更新: {tar_path} ({len(files)} 个文件)")
        return tar_path
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def cleanup_old_archives(dry_run: bool = False) -> int:
    """
    清理 archive/logs/ 下超过 ARCHIVE_RETENTION_DAYS 的归档包。

    Args:
        dry_run: 如为 True 仅输出日志，不执行实际删除。

    Returns:
        删除的归档包数量（dry_run 时为待删除数量）。
    """
    if not ARCHIVE_DIR.exists():
        log.info(f"存档目录不存在: {ARCHIVE_DIR}")
        return 0

    cutoff = datetime.now(TZ) - timedelta(days=ARCHIVE_RETENTION_DAYS)
    cutoff_month = cutoff.strftime("%Y%m")
    log.info(
        f"清理旧归档，保留期={ARCHIVE_RETENTION_DAYS}天，"
        f"截止月份={cutoff_month}"
    )

    deleted_count = 0

    for month_dir in sorted(ARCHIVE_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        month_str = month_dir.name

        if len(month_str) != 6 or not month_str.isdigit():
            continue

        if month_str >= cutoff_month:
            continue

        if dry_run:
            for f in month_dir.iterdir():
                log.info(f"[DRY RUN] 将删除: {f}")
                deleted_count += 1
            log.info(f"[DRY RUN] 将删除空目录: {month_dir}")
            continue

        try:
            file_count_before = len(list(month_dir.iterdir()))
            shutil.rmtree(month_dir)
            log.info(f"已删除过期归档: {month_dir}（含 {file_count_before} 个文件）")
            deleted_count += file_count_before
        except Exception as e:
            log.error(f"删除归档月份目录失败: {month_dir} ({e})")

    if deleted_count == 0:
        log.info("没有需要清理的过期归档")
    return deleted_count


# =============================================
# 核心归档逻辑
# =============================================

def run_archive(dry_run: bool = False) -> int:
    """
    主归档逻辑。

    参数：
      dry_run: 如为 True，仅输出将要归档的文件，不执行实际归档操作。

    返回：
      归档的文件数量。
    """
    cutoff = datetime.now(TZ) - timedelta(days=RETENTION_DAYS)
    log.info(
        f"开始日志归档，保留期={RETENTION_DAYS}天，"
        f"截止日期={cutoff.strftime('%Y-%m-%d')}，"
        f"大小阈值={SIZE_THRESHOLD_MB}MB"
    )

    pending = _collect_log_files(LOGS_DIR, cutoff)

    if not pending:
        log.info("没有需要归档的日志文件")
        return 0

    # 按月份分组
    groups: dict[str, list[Path]] = {}
    for file_path, archive_month in pending:
        if archive_month not in groups:
            groups[archive_month] = []
        groups[archive_month].append(file_path)

    total_files = 0

    for archive_month, files in sorted(groups.items()):
        if dry_run:
            for f in files:
                size_mb = f.stat().st_size / (1024 * 1024)
                log.info(f"[DRY RUN] 将归档: {f} ({size_mb:.1f}MB)")
            log.info(f"[DRY RUN] 将打包: logs_{archive_month}.tar.gz ({len(files)} 个文件)")
            total_files += len(files)
            continue

        # 实际归档
        try:
            tar_path = _build_tar_for_month(archive_month, files, "logs")

            # 删除源文件
            for f in files:
                try:
                    f.unlink()
                    log.info(f"已删除源文件: {f}")
                except Exception as e:
                    log.error(f"删除源文件失败: {f} ({e})")

            total_files += len(files)
        except Exception as e:
            log.error(f"归档失败: {archive_month} ({e})", exc_info=True)
            continue

    # 清理空目录（logs/ 下可能产生的空子目录）
    for d in LOGS_DIR.iterdir():
        if d.is_dir():
            try:
                if not any(d.iterdir()):
                    d.rmdir()
                    log.info(f"删除空目录: {d}")
            except (PermissionError, OSError):
                pass

    log.info(f"日志归档完成，共归档 {total_files} 个文件")
    return total_files


# =============================================
# __main__ 入口
# =============================================

def parse_args():
    """简单参数解析"""
    import sys

    args = {
        "dry_run": False,
        "skip_cleanup": False,
        "cleanup_only": False,
    }

    for arg in sys.argv[1:]:
        if arg in ("--dry-run", "-n", "--dryrun"):
            args["dry_run"] = True
        if arg in ("--skip-cleanup",):
            args["skip_cleanup"] = True
        if arg in ("--cleanup-only",):
            args["cleanup_only"] = True
        if arg in ("--help", "-h"):
            print("用法: python src/utils/logs_archiver.py [--dry-run] [--skip-cleanup] [--cleanup-only] [--help]")
            print()
            print("  归档 logs/ 下超过7天或单文件超过50MB的 .log 文件")
            print("  自动清理 archive/logs/ 下超过180天的过期归档包")
            print()
            print("  选项：")
            print("    --dry-run, -n          仅扫描，不执行实际归档或清理操作")
            print("    --skip-cleanup         跳过过期归档包清理步骤")
            print("    --cleanup-only         仅执行过期归档包清理，跳过源文件归档")
            print("    --help, -h             显示此帮助")
            sys.exit(0)

    return args


if __name__ == "__main__":
    args = parse_args()

    setup_root_logger(log_file="automation.log")
    log.info("=" * 60)
    log.info("logs_archiver 启动")

    try:
        if args.get("cleanup_only"):
            deleted = cleanup_old_archives(dry_run=args.get("dry_run", False))
            if args.get("dry_run"):
                print(f"\n[DRY RUN] 共 {deleted} 个归档包待清理")
            else:
                print(f"\n清理完成：共删除 {deleted} 个归档包")
                print(f"日志：{Path(__file__).parent / 'logs' / 'logs_archiver.log'}")
        else:
            count = run_archive(dry_run=args.get("dry_run", False))

            if not args.get("skip_cleanup", False):
                deleted = cleanup_old_archives(dry_run=args.get("dry_run", False))
                if deleted > 0:
                    log.info(f"已清理过期归档: {deleted} 个归档包")
            else:
                log.info("跳过过期归档清理（--skip-cleanup）")

            if args.get("dry_run"):
                print(f"\n[DRY RUN] 共 {count} 个日志文件待归档")
                print("使用不带 --dry-run 参数执行以实际归档。")
            else:
                print(f"\n归档完成：共归档 {count} 个日志文件")
                print(f"日志：{Path(__file__).parent / 'logs' / 'logs_archiver.log'}")
    except Exception as e:
        log.critical(f"归档异常终止: {e}", exc_info=True)
        print(f"\n错误：归档异常终止，详见日志。\n{e}")
        raise

    log.info("logs_archiver 正常结束")
    log.info("=" * 60)
