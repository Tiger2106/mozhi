"""
incoming_meta.py — 文件准入元数据系统

扫描 incoming/YYYYMMDD/ 目录，为没有 .meta.json 的数据文件自动生成元数据。

作者: moheng
创建时间: 2026-05-15
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 默认元数据策略
DEFAULT_META = {
    "created_at": None,  # 动态填充当前时间
    "source": "unknown",
    "status": "incoming",
    "target": "unassigned",
    "owner": "unassigned",
    "description": "",
}

# 墨枢项目根目录自动探测
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # mozhi_platform/
INCOMING_BASE = PROJECT_ROOT / "incoming"

TIMEZONE = "+08:00"


def now_str() -> str:
    """返回带时区的当前时间字符串（YYYY-MM-DD HH:MM）。"""
    return datetime.now().strftime(f"%Y-%m-%d %H:%M")


def default_meta() -> dict:
    """生成带当前时间戳的默认元数据字典。"""
    meta = dict(DEFAULT_META)
    meta["created_at"] = now_str()
    return meta


def get_incoming_path(date_str: Optional[str] = None) -> Path:
    """
    获取 incoming 下的日期目录路径。

    参数:
        date_str: YYYYMMDD 格式日期字符串，None 则取当天。

    返回:
        Path 对象。
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    return INCOMING_BASE / date_str


def is_meta_file(filename: str) -> bool:
    """判断是否为 .meta.json 文件。"""
    return filename.endswith(".meta.json")


def has_meta_file(dir_path: Path, filename: str) -> bool:
    """检查某个文件是否已有对应的 .meta.json。"""
    if is_meta_file(filename):
        return True  # meta 文件自身跳过
    meta_path = dir_path / f"{filename}.meta.json"
    return meta_path.exists()


def read_meta_input(prompt: str, default: str = "") -> str:
    """交互式读取用户输入，提供默认值。"""
    if default:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "
    value = input(display).strip()
    return value if value else default


def interactive_meta(filename: str) -> dict:
    """通过命令行交互补全元数据。"""
    meta = default_meta()
    print(f"\n--- 为 {filename} 输入元数据 ---")
    meta["source"] = read_meta_input("来源 (source)", "unknown")
    meta["target"] = read_meta_input("目标模块 (target)", "unassigned")
    meta["owner"] = read_meta_input("负责人 (owner)", "unassigned")
    meta["description"] = read_meta_input("描述 (description)", "")
    return meta


def generate_meta(
    file_path: Path,
    interactive: bool = False,
    overwrite: bool = False,
) -> Optional[Path]:
    """
    为指定文件生成 .meta.json。

    参数:
        file_path: 数据文件的路径。
        interactive: 是否使用交互式输入补全元数据。
        overwrite: 如果 .meta.json 已存在，是否覆盖。

    返回:
        .meta.json 路径（成功时），None（跳过/失败时）。
    """
    parent = file_path.parent
    filename = file_path.name

    # 跳过 meta 文件自身
    if is_meta_file(filename):
        return None

    meta_path = parent / f"{filename}.meta.json"

    # 检查是否已存在
    if meta_path.exists() and not overwrite:
        return None

    # 生成元数据
    if interactive:
        meta = interactive_meta(filename)
    else:
        meta = default_meta()

    # 写入
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta_path
    except OSError as e:
        print(f"ERROR: 写入 {meta_path} 失败: {e}", file=sys.stderr)
        return None


def scan_directory(
    date_str: Optional[str] = None,
    interactive: bool = False,
    overwrite: bool = False,
    verbose: bool = True,
) -> list[Path]:
    """
    扫描 incoming 目录下的日期文件夹，为缺少 .meta.json 的文件生成元数据。

    参数:
        date_str: YYYYMMDD 格式日期，None 则当天。
        interactive: 交互式补全元数据。
        overwrite: 覆盖已有 .meta.json。
        verbose: 输出详细信息。

    返回:
        生成的 .meta.json 路径列表。
    """
    incoming_path = get_incoming_path(date_str)
    date_display = date_str or datetime.now().strftime("%Y%m%d")

    if not incoming_path.exists():
        if verbose:
            print(f"[SKIP] 目录不存在: {incoming_path}")
        return []

    if verbose:
        print(f"[SCAN] 扫描: {incoming_path}")

    generated: list[Path] = []
    skipped = 0
    meta_skipped = 0

    for entry in sorted(incoming_path.iterdir()):
        if not entry.is_file():
            continue

        filename = entry.name

        # 跳过 .meta.json 自身
        if is_meta_file(filename):
            meta_skipped += 1
            continue

        # 检查是否已有 meta
        if has_meta_file(incoming_path, filename) and not overwrite:
            skipped += 1
            if verbose:
                print(f"  [SKIP] 已有 meta: {filename}")
            continue

        # 生成 meta
        result = generate_meta(entry, interactive=interactive, overwrite=overwrite)
        if result:
            generated.append(result)
            if verbose:
                print(f"  [META] 已生成: {result.name}")

    if verbose:
        total = len(list(incoming_path.iterdir()))
        print(f"\n[SUMMARY] 目录: {date_display} | "
              f"总计: {total} 文件 | "
              f"已生成: {len(generated)} | "
              f"跳过(已有 meta): {skipped} | "
              f"跳过(meta文件): {meta_skipped}")

    return generated


def daily_scan(verbose: bool = False) -> list[Path]:
    """
    每日扫描任务：为当天 incoming 目录生成所有缺失的 .meta.json。
    用于 cron 定时调用。

    返回:
        生成的 .meta.json 路径列表。
    """
    return scan_directory(verbose=verbose)


def main():
    parser = argparse.ArgumentParser(
        description="incoming_meta — 文件准入元数据系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用示例:\n"
            "  python incoming_meta.py                     # 扫描当天目录\n"
            "  python incoming_meta.py --date 20260515     # 扫描指定日期\n"
            "  python incoming_meta.py --interactive       # 交互式补全\n"
            "  python incoming_meta.py --overwrite         # 覆盖已有 meta\n"
            "  python incoming_meta.py --quiet             # 静默模式\n"
            "  python incoming_meta.py --dry-run           # 试运行（不写入）\n"
        ),
    )
    parser.add_argument(
        "--date", "-d",
        type=str,
        default=None,
        help="日期目录 (YYYYMMDD)，默认当天",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="交互式输入元数据",
    )
    parser.add_argument(
        "--overwrite", "-o",
        action="store_true",
        help="覆盖已有 .meta.json",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="静默模式",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="仅列出会处理哪些文件，不实际写入",
    )

    args = parser.parse_args()
    verbose = not args.quiet

    if args.dry_run:
        incoming_path = get_incoming_path(args.date)
        if not incoming_path.exists():
            print(f"[DRY-RUN] 目录不存在: {incoming_path}")
            sys.exit(0)

        print(f"[DRY-RUN] 扫描: {incoming_path}")
        for entry in sorted(incoming_path.iterdir()):
            if not entry.is_file():
                continue
            filename = entry.name
            if is_meta_file(filename):
                print(f"  [SKIP] meta文件: {filename}")
                continue
            if has_meta_file(incoming_path, filename):
                print(f"  [SKIP] 已有 meta: {filename}")
                continue
            print(f"  [WOULD] 生成: {filename}.meta.json")
        sys.exit(0)

    results = scan_directory(
        date_str=args.date,
        interactive=args.interactive,
        overwrite=args.overwrite,
        verbose=verbose,
    )

    if verbose:
        if results:
            print(f"\n[DONE] 共生成 {len(results)} 个元数据文件。")
        else:
            print("\n[DONE] 无需生成新的元数据文件。")


if __name__ == "__main__":
    main()
