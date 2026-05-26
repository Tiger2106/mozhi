"""
cleanup_orphan_sessions.py
OpenClaw 孤儿 transcript 文件清理工具
版本：v1.0

问题背景：
  sessions.json 记录了所有有效会话，但历史 .jsonl transcript 文件
  可能不在 sessions.json 引用范围内（孤儿文件），占磁盘且拖慢 gateway 启动。

使用方式：
  # 第一步：预览（不删除任何文件）
  python cleanup_orphan_sessions.py --dry-run

  # 第二步：确认预览无误后正式清理
  python cleanup_orphan_sessions.py --delete

  # 仅清理 N 天前的孤儿文件（更保守）
  python cleanup_orphan_sessions.py --delete --older-than 7

  # 指定其他 agent 目录
  python cleanup_orphan_sessions.py --dry-run --agent xuanzhi
"""

import os
import sys
import json
import shutil
import argparse
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.config import SHANGHAI_TZ

TZ = SHANGHAI_TZ
log = logging.getLogger("cleanup_orphans")

# ─────────────────────────────────────────────
# 默认路径配置
# ─────────────────────────────────────────────

OPENCLAW_BASE   = Path(r"C:\Users\17699\.openclaw")
DEFAULT_AGENT   = "moheng"
BACKUP_SUFFIX   = ".orphan_backup"


# ─────────────────────────────────────────────
# 核心逻辑
# ─────────────────────────────────────────────

def load_referenced_ids(sessions_json_path: Path) -> set:
    """
    从 sessions.json 提取所有被引用的 session ID。
    这些 ID 对应的 .jsonl 文件是有效的，不能删除。
    """
    if not sessions_json_path.exists():
        log.error(f"sessions.json 不存在: {sessions_json_path}")
        return set()

    try:
        with open(sessions_json_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"读取 sessions.json 失败: {e}")
        return set()

    referenced = set()

    # sessions.json 格式可能是列表或字典，兼容处理
    sessions = []

    if isinstance(data, list):
        sessions = data  # 列表格式：每个元素是一个 session dict
    elif isinstance(data, dict):
        # dict 格式：key="agent:xxx:sessionId", value=session dict
        sessions = list(data.values())
    else:
        sessions = []

    for session in sessions:
        if not isinstance(session, dict):
            continue
        # 常见 ID 字段名
        for key in ["id", "session_id", "sessionId", "key", "transcript_id"]:
            sid = session.get(key)
            if sid:
                referenced.add(str(sid))
                # 也加入可能的文件名变体
                referenced.add(str(sid).replace("-", "_"))
                referenced.add(str(sid).replace("_", "-"))

        # sessionFile 字段包含完整路径
        session_file = session.get("sessionFile", "")
        if session_file:
            fname = Path(session_file).stem  # 去掉扩展名
            referenced.add(fname)
            referenced.add(fname.replace("-", "_"))
            referenced.add(fname.replace("_", "-"))

        # transcript 字段可能直接包含文件名
        transcript = session.get("transcript", session.get("transcriptFile", ""))
        if transcript:
            fname = Path(transcript).stem
            referenced.add(fname)

    log.info(f"sessions.json 中引用了 {len(referenced)} 个有效 session ID")
    return referenced


def find_orphan_files(
    sessions_dir: Path,
    referenced_ids: set,
    older_than_days: int = 0,
) -> list[Path]:
    """
    扫描 sessions 目录，找出所有孤儿 .jsonl 文件。

    参数：
        sessions_dir:    sessions 目录路径
        referenced_ids:  有效的 session ID 集合
        older_than_days: 只返回 N 天前的文件（0=不限制）
    """
    if not sessions_dir.exists():
        log.error(f"sessions 目录不存在: {sessions_dir}")
        return []

    all_jsonl = list(sessions_dir.glob("*.jsonl"))
    log.info(f"扫描到 {len(all_jsonl)} 个 .jsonl 文件")

    cutoff_ts = None
    if older_than_days > 0:
        cutoff = datetime.now(TZ) - timedelta(days=older_than_days)
        cutoff_ts = cutoff.timestamp()
        log.info(f"只处理 {older_than_days} 天前的文件（截止：{cutoff.isoformat()}）")

    orphans = []
    for f in all_jsonl:
        stem = f.stem  # 文件名去掉 .jsonl

        # 检查是否在引用集合中
        is_referenced = (
            stem in referenced_ids or
            any(stem.startswith(rid) or rid.startswith(stem) for rid in referenced_ids)
        )

        if is_referenced:
            continue

        # 检查文件年龄
        if cutoff_ts is not None:
            mtime = f.stat().st_mtime
            if mtime > cutoff_ts:
                continue  # 文件太新，跳过

        orphans.append(f)

    return orphans


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def generate_report(
    orphans: list[Path],
    referenced_ids: set,
    sessions_dir: Path,
) -> str:
    """Generate cleanup preview report"""
    total_size = sum(f.stat().st_size for f in orphans)
    all_jsonl  = list(sessions_dir.glob("*.jsonl"))
    all_size   = sum(f.stat().st_size for f in all_jsonl)

    lines = [
        "=" * 60,
        "Orphan Transcript Cleanup Report",
        f"Generated: {datetime.now(TZ).isoformat()}",
        "=" * 60,
        f"Sessions dir: {sessions_dir}",
        f"Valid session IDs: {len(referenced_ids)}",
        f"Total .jsonl files: {len(all_jsonl)} ({format_size(all_size)})",
        f"Orphan files: {len(orphans)} ({format_size(total_size)})",
        f"Reclaimable: {format_size(total_size)}",
        "",
    ]

    if orphans:
        lines.append("Orphan files (top 20):")
        for f in sorted(orphans, key=lambda x: x.stat().st_mtime)[:20]:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, TZ).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {f.name:<60} {format_size(f.stat().st_size):>10}  {mtime}")
        if len(orphans) > 20:
            lines.append(f"  ... and {len(orphans) - 20} more files")

    lines.append("=" * 60)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 清理执行
# ─────────────────────────────────────────────

def delete_orphans(
    orphans: list[Path],
    backup: bool = True,
    backup_dir: Path = None,
) -> dict:
    """
    删除孤儿文件。

    参数：
        orphans:    孤儿文件列表
        backup:     是否先备份再删除（默认 True）
        backup_dir: 备份目录（None=同目录下创建 _orphan_backup 子目录）

    返回：
        {"deleted": int, "failed": int, "backed_up": int, "errors": list}
    """
    result = {"deleted": 0, "failed": 0, "backed_up": 0, "errors": []}

    if backup and backup_dir is None and orphans:
        backup_dir = orphans[0].parent / "_orphan_backup"
        backup_dir.mkdir(exist_ok=True)
        log.info(f"备份目录：{backup_dir}")

    for f in orphans:
        try:
            if backup and backup_dir:
                dest = backup_dir / f.name
                shutil.move(str(f), str(dest))
                result["backed_up"] += 1
                result["deleted"] += 1
                log.debug(f"已移动到备份: {f.name}")
            else:
                f.unlink()
                result["deleted"] += 1
                log.debug(f"已删除: {f.name}")
        except Exception as e:
            result["failed"] += 1
            result["errors"].append(f"{f.name}: {e}")
            log.warning(f"删除失败 {f.name}: {e}")

    return result


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="清理 OpenClaw 孤儿 transcript (.jsonl) 文件"
    )
    parser.add_argument(
        "--agent", default=DEFAULT_AGENT,
        help=f"Agent 名称（默认: {DEFAULT_AGENT}）"
    )
    parser.add_argument(
        "--sessions-dir", default=None,
        help="sessions 目录路径（默认自动推断）"
    )
    parser.add_argument(
        "--sessions-json", default=None,
        help="sessions.json 路径（默认自动推断）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：只显示将被删除的文件，不实际删除"
    )
    parser.add_argument(
        "--delete", action="store_true",
        help="正式删除孤儿文件（先备份到 _orphan_backup 子目录）"
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="删除时不备份（危险，配合 --delete 使用）"
    )
    parser.add_argument(
        "--older-than", type=int, default=0, metavar="DAYS",
        help="只处理 N 天前的孤儿文件（0=全部）"
    )
    parser.add_argument(
        "--report-file", default=None,
        help="将报告写入指定文件"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="显示详细日志"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Windows GBK console: force UTF-8 for print
    import io
    import sys
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


    # ── 推断路径 ──────────────────────────────
    agent_base   = OPENCLAW_BASE / "agents" / args.agent
    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else agent_base / "sessions"
    sessions_json = Path(args.sessions_json) if args.sessions_json else sessions_dir / "sessions.json"

    log.info(f"Agent: {args.agent}")
    log.info(f"Sessions 目录: {sessions_dir}")
    log.info(f"Sessions JSON: {sessions_json}")

    if not args.dry_run and not args.delete:
        print('Please specify mode:')
        print('  Preview: --dry-run')
        print('  Delete:  --delete')
        sys.exit(1)

    # ── 加载有效 session ID ───────────────────
    referenced_ids = load_referenced_ids(sessions_json)

    # ── 扫描孤儿文件 ──────────────────────────
    orphans = find_orphan_files(
        sessions_dir=sessions_dir,
        referenced_ids=referenced_ids,
        older_than_days=args.older_than,
    )

    # ── 生成报告 ──────────────────────────────
    report = generate_report(orphans, referenced_ids, sessions_dir)
    print(report)

    if args.report_file:
        with open(args.report_file, "w", encoding="utf-8") as f:
            f.write(report)
        log.info(f"报告已写入: {args.report_file}")

    if not orphans:
        print('No orphan files found, nothing to clean')
        return

    # ── 执行清理 ──────────────────────────────
    if args.dry_run:
        print(f'\n[DRY-RUN] Will delete {len(orphans)} orphan files')
        print('Confirm and run: python cleanup_orphan_sessions.py --delete')
        return

    if args.delete:
        backup = not args.no_backup
        if backup:
            print(f'\n[DELETE] Moving {len(orphans)} orphan files to _orphan_backup')
        else:
            print(f'\n[DELETE - NO BACKUP] Permanently deleting {len(orphans)} orphan files')
            confirm = input('Confirm? Type YES to continue: ').strip()
            if confirm != 'YES':
                print('Cancelled')
                return

        result = delete_orphans(
            orphans=orphans,
            backup=backup,
        )

        print(f'\nCleanup complete:')
        print(f'  OK: {result["deleted"]}')
        if result['backed_up']:
            print(f'  Backed up: {result["backed_up"]} (to _orphan_backup/)')
        if result['failed']:
            print(f'  Failed: {result["failed"]}')
            for err in result['errors'][:10]:
                print(f'    {err}')


if __name__ == "__main__":
    main()
