#!/usr/bin/env python3
"""每日运维脚本 — Layer1: 机械性整理与备份 / Layer2: 状态追踪 / Layer3: 知识沉淀

墨枢平台日常维护工具，按层执行。
Layer1：定时清理、报告检查、旧报告归档、数据库备份。
Layer2：扫描 incoming/ 超期文件、knowledge 草稿、本周回测、未注册文件。
Layer3：触发 knowledge_extractor、检查知识条目衰减。

用法:
    python scripts/daily_maintenance.py                    # 全量运行
    python scripts/daily_maintenance.py --dry-run          # 预扫描不执行
    python scripts/daily_maintenance.py --layer 1          # 只执行第一层
    python scripts/daily_maintenance.py --layer 2          # 只执行第二层
    python scripts/daily_maintenance.py --layer 3          # 只执行第三层
    python scripts/daily_maintenance.py --report           # 同时生成 daily_doc_report.md
    python scripts/daily_maintenance.py --setup-cron       # 配置 02:00 定时任务（仅首次）

Author: 墨衡
Created: 2026-05-16
Version: 1.2
"""

import sys
import os
import argparse
import shutil
import json
import zipfile
import sqlite3
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path

# 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 日志 ─────────────────────────────────────────────────────
logger = logging.getLogger("daily_maintenance")
def _setup_logging():
    """初始化 FileHandler 日志，同时保留 console print 输出。"""
    if logger.handlers:
        return
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(log_dir / "daily_maintenance.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _log_and_print(msg: str, level: int = logging.INFO):
    """日志写入 + 控制台双输出。"""
    logger.log(level, msg)
    print(msg)


# ── 常量 ─────────────────────────────────────────────────────
SIGNALS_TASKS_DIR = Path.home() / "mo_zhi_sharereports" / "signals" / "tasks"
REPORTS_DIR = PROJECT_ROOT / "reports"
ARCHIVE_DIR = PROJECT_ROOT / "archive"
DATA_DIR = PROJECT_ROOT / "data"
DB_BACKUP_DIR = DATA_DIR / "db"
INCOMING_DIR = PROJECT_ROOT / "incoming"
REGISTRY_DB = PROJECT_ROOT / "registry" / "file_registry.db"
KNOWLEDGE_DB = str(PROJECT_ROOT / "data" / "knowledge.db")
BACKTEST_DB = str(PROJECT_ROOT / "data" / "knowledge.db")

RETENTION_DAYS = 7          # 信号文件保留天数
ARCHIVE_DAYS = 30           # 报告归档天数
STALE_DAYS = 3              # incoming/ 超期判定天数
DECAY_DAYS = 90             # 知识条目衰减判定天数


def cleanup_signal_files(dry_run=False):
    """删除超过 RETENTION_DAYS 天的 .done/.failed 文件。

    Args:
        dry_run: 若为 True，只扫描不删除。

    Returns:
        dict: 包含清理结果的统计信息。
    """
    if not SIGNALS_TASKS_DIR.exists():
        return {"cleaned": 0, "error": "目录不存在", "details": []}

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    cleaned = 0
    failed_clean = 0
    details = []

    for pattern in ("*.done", "*.failed"):
        for f in SIGNALS_TASKS_DIR.glob(pattern):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    details.append({
                        "file": f.name,
                        "age_days": (datetime.now() - mtime).days,
                        "action": "delete" if not dry_run else "dry-run (would delete)"
                    })
                    if not dry_run:
                        f.unlink()
                    cleaned += 1
            except Exception as e:
                failed_clean += 1
                details.append({
                    "file": f.name,
                    "error": str(e),
                    "action": "failed"
                })

    return {
        "cleaned": cleaned,
        "failed": failed_clean,
        "cutoff_days": RETENTION_DAYS,
        "details": details
    }


def check_today_report(dry_run=False):
    """检查 reports/ 下当日日报是否已生成。

    Args:
        dry_run: 仅扫描，无副作用（此函数为只读，忽略此参数）。

    Returns:
        dict: 包含检查结果。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not REPORTS_DIR.exists():
        return {"missing": True, "found": 0, "error": "reports 目录不存在"}

    found = list(REPORTS_DIR.rglob(f"*{today}*"))

    return {
        "missing": len(found) == 0,
        "found": len(found),
        "date": today,
        "files": [str(f.relative_to(REPORTS_DIR)) for f in found[:50]]
    }


def archive_old_reports(dry_run=False):
    """将超过 ARCHIVE_DAYS 天的日报按月度压缩归档。

    扫描 reports/ 下所有文件，识别修改时间超过 30 天的文件，
    按所属月份 (YYYY-MM) 分组，创建 zip 归档到 archive/ 目录。
    归档成功后删除原文件。

    Args:
        dry_run: 若为 True，只扫描不归档也不删除。

    Returns:
        dict: 包含归档结果统计。
    """
    if not REPORTS_DIR.exists():
        return {"archived_groups": 0, "error": "reports 目录不存在"}

    cutoff = datetime.now() - timedelta(days=ARCHIVE_DAYS)
    files_to_archive = {}  # { "YYYY-MM": [Path, ...] }

    for f in REPORTS_DIR.rglob("*"):
        if not f.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                month_key = mtime.strftime("%Y-%m")
                files_to_archive.setdefault(month_key, []).append(f)
        except (OSError, ValueError):
            continue

    if not files_to_archive:
        return {"archived_groups": 0, "total_files": 0}

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    archived_groups = 0
    total_files = 0
    group_details = []

    for month_key, files in sorted(files_to_archive.items()):
        archive_name = f"reports_{month_key}"
        archive_path = ARCHIVE_DIR / archive_name

        if dry_run:
            group_details.append({
                "month": month_key,
                "file_count": len(files),
                "action": "dry-run (would archive)"
            })
            archived_groups += 1
            total_files += len(files)
            continue

        try:
            zip_path = str(archive_path) + ".zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    rel_path = f.relative_to(PROJECT_ROOT)
                    zf.write(str(f), str(rel_path))

            # 删除已归档的原文件
            for f in files:
                try:
                    f.unlink()
                except OSError:
                    pass

            group_details.append({
                "month": month_key,
                "file_count": len(files),
                "archive": str(Path(zip_path).name),
                "size_kb": round(Path(zip_path).stat().st_size / 1024, 1),
                "action": "archived"
            })
            archived_groups += 1
            total_files += len(files)

        except Exception as e:
            group_details.append({
                "month": month_key,
                "file_count": len(files),
                "error": str(e),
                "action": "failed"
            })

    return {
        "archived_groups": archived_groups,
        "total_files": total_files,
        "cutoff_days": ARCHIVE_DAYS,
        "groups": group_details
    }


def backup_knowledge_db(dry_run=False):
    """热备份 knowledge.db 到 data/db/knowledge_backup_{date}.db。

    使用 KnowledgeDB 类的在线备份 API，在数据库正常运行状态下
    创建一致性备份。

    Args:
        dry_run: 若为 True，只检查不备份。

    Returns:
        dict: 包含备份路径和状态。
    """
    from backtest.pipeline.knowledge_db import KnowledgeDB

    try:
        kdb = KnowledgeDB()
        kdb.initialize()

        if dry_run:
            kdb.close()
            DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y%m%d")
            backup_path = str(DB_BACKUP_DIR / f"knowledge_backup_{today}.db")
            return {
                "backup_path": backup_path,
                "exists": Path(backup_path).exists(),
                "dry_run": True
            }

        backup_path = kdb.backup(str(DB_BACKUP_DIR))
        kdb.close()
        return {
            "backup_path": backup_path,
            "exists": Path(backup_path).exists(),
            "size_kb": round(Path(backup_path).stat().st_size / 1024, 1) if Path(backup_path).exists() else 0
        }
    except Exception as e:
        return {
            "backup_path": None,
            "error": str(e),
            "exists": False
        }


def backup_trade_engine(dry_run=False):
    """备份 trade_engine.db 到 data/db/trade_engine_backup_{date}.db。

    trade_engine.db 通常较小，使用 shutil.copy2 进行简单复制备份。

    Args:
        dry_run: 若为 True，只检查不复制。

    Returns:
        dict: 包含备份路径和状态。
    """
    db_path = DATA_DIR / "trade_engine.db"
    DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    backup_path = DB_BACKUP_DIR / f"trade_engine_backup_{today}.db"

    if not db_path.exists():
        return {
            "backup_path": str(backup_path),
            "exists": False,
            "source_missing": True
        }

    if dry_run:
        return {
            "backup_path": str(backup_path),
            "exists": backup_path.exists(),
            "source_size_kb": round(db_path.stat().st_size / 1024, 1),
            "dry_run": True
        }

    try:
        shutil.copy2(str(db_path), str(backup_path))
        return {
            "backup_path": str(backup_path),
            "exists": backup_path.exists(),
            "source_size_kb": round(db_path.stat().st_size / 1024, 1),
            "backup_size_kb": round(backup_path.stat().st_size / 1024, 1) if backup_path.exists() else 0
        }
    except Exception as e:
        return {
            "backup_path": str(backup_path),
            "error": str(e),
            "exists": False
        }


# ═══════════════════════════════════════════════════════════
# Layer 2: 状态追踪
# ═══════════════════════════════════════════════════════════

def scan_incoming(dry_run=False):
    """列出 incoming/ 中超过 STALE_DAYS 天未处理文件。

    Args:
        dry_run: 仅扫描，无副作用。

    Returns:
        dict: 包含超期文件统计列表。
    """
    if not INCOMING_DIR.exists():
        return {"stale": 0, "files": []}
    cutoff = datetime.now() - timedelta(days=STALE_DAYS)
    stale = []
    for f in sorted(INCOMING_DIR.iterdir()):
        if f.is_file():
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    stale.append({
                        "filename": f.name,
                        "age_days": (datetime.now() - mtime).days,
                        "path": str(f)
                    })
            except (OSError, ValueError):
                continue
    return {"stale": len(stale), "files": stale}


def scan_knowledge_drafts(dry_run=False):
    """扫描 knowledge_entries，列出 status='draft' 的条目。

    Args:
        dry_run: 仅扫描，无副作用。

    Returns:
        dict: 包含草稿条目统计。
    """
    try:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, symbol, strategy, insight_category, confidence, insight_summary, activated_at "
                     "FROM knowledge_entries WHERE status='draft'")
        rows = cur.fetchall()
        conn.close()
        drafts = [{
            "id": r["id"],
            "symbol": r["symbol"],
            "strategy": r["strategy"],
            "category": r["insight_category"],
            "confidence": r["confidence"],
            "summary": (r["insight_summary"][:60] + "..") if len(r.get("insight_summary", "") or "") > 60 else (r.get("insight_summary", "") or ""),
            "created_at": r["activated_at"]
        } for r in rows]
        return {"total": len(drafts), "drafts": drafts}
    except Exception as e:
        return {"total": 0, "error": str(e), "drafts": []}


def scan_recent_backtests(dry_run=False):
    """查询 knowledge.db 本周新增回测，生成摘要。

    返回按 strategy 分组的计数。

    Args:
        dry_run: 仅扫描，无副作用。

    Returns:
        dict: 包含本周回测计数。
    """
    try:
        # 计算本周一日期
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.strftime("%Y-%m-%d")

        conn = sqlite3.connect(KNOWLEDGE_DB)
        cur = conn.cursor()
        cur.execute("SELECT strategy, COUNT(*) as cnt FROM backtest_runs "
                     "WHERE created_at >= ? GROUP BY strategy ORDER BY cnt DESC", (week_start,))
        rows = cur.fetchall()
        total = sum(r[1] for r in rows)
        conn.close()
        return {
            "total": total,
            "week_start": week_start,
            "by_strategy": {r[0]: r[1] for r in rows}
        }
    except Exception as e:
        return {"total": 0, "error": str(e), "by_strategy": {}}


def check_unregistered_files(dry_run=False):
    """扫描 src/backtest/ 和 scripts/ 下新增 .py 文件，检查是否未注册到 file_registry。

    获取 file_registry 中已有的路径列表，与文件系统实际文件比对，
    找出未注册的文件。

    Args:
        dry_run: 仅扫描，无副作用。

    Returns:
        dict: 包含未注册文件列表。
    """
    try:
        # 获取 file_registry 中已有的路径列表
        conn = sqlite3.connect(str(REGISTRY_DB))
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT filename FROM files")
        registered = set(row[0] for row in cur.fetchall())
        conn.close()
    except Exception as e:
        return {"unregistered": 0, "error": f"读取 file_registry 失败: {e}", "files": []}

    # 扫描目录下的 .py 文件
    scan_dirs = [
        PROJECT_ROOT / "src" / "backtest",
        PROJECT_ROOT / "scripts"
    ]
    unregistered = []
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for f in sorted(scan_dir.rglob("*.py")):
            fname = f.name
            if fname not in registered:
                unregistered.append({
                    "filename": fname,
                    "path": str(f.relative_to(PROJECT_ROOT))
                })

    return {"unregistered": len(unregistered), "files": unregistered}


# ═══════════════════════════════════════════════════════════
# Layer 3: 知识沉淀
# ═══════════════════════════════════════════════════════════

def trigger_knowledge_extractor(dry_run=False):
    """调用 aggregate_knowledge() 从回测运行聚合并更新 knowledge_entries。

    Args:
        dry_run: 若为 True，只检查不执行。

    Returns:
        dict: 包含聚合结果。
    """
    if dry_run:
        return {"aggregated": 0, "dry_run": True}
    try:
        from backtest.pipeline.knowledge_db import KnowledgeDB
        kdb = KnowledgeDB()
        kdb.initialize()
        updated = kdb.aggregate_knowledge()
        kdb.close()
        return {"aggregated": updated}
    except Exception as e:
        return {"aggregated": -1, "error": str(e)}


def trigger_decay_check(dry_run=False):
    """检查超过 DECAY_DAYS 天未更新的知识条目，标记 degraded/deprecated。

    Args:
        dry_run: 若为 True，只检查不执行。

    Returns:
        dict: 包含衰减检查结果。
    """
    if dry_run:
        return {"decayed": 0, "dry_run": True}
    try:
        from backtest.pipeline.knowledge_db import KnowledgeDB
        kdb = KnowledgeDB()
        kdb.initialize()
        result = kdb.decay_check(max_age_days=DECAY_DAYS)
        kdb.close()
        return result
    except Exception as e:
        return {"decayed": -1, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════


def _query_weekly_backtests() -> dict:
    """查询本周 backtest_runs + performance_results 明细（限制行数）。

    Returns:
        dict: {"rows": list[dict], "total": int} — 每条包含 strategy, symbol, sharpe, max_dd, grade
    """
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    week_start = monday.strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(BACKTEST_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT r.strategy, r.symbol, p.sharpe_ratio, p.max_drawdown_pct, p.validity_grade
            FROM backtest_runs r
            LEFT JOIN performance_results p ON r.run_id = p.run_id
            WHERE r.created_at >= ?
            ORDER BY r.created_at DESC
            LIMIT 20
        """, (week_start,))
        rows = [dict(r) for r in cur.fetchall()]
        # 统计总数
        cur.execute("SELECT COUNT(*) FROM backtest_runs WHERE created_at >= ?", (week_start,))
        total = cur.fetchone()[0]
        conn.close()
        return {"rows": rows, "total": total}
    except Exception as e:
        logging.warning("_query_weekly_backtests query failed: %s", e)
        return {"rows": [], "total": 0}


def _query_knowledge_status() -> dict:
    """查询 knowledge_entries 各状态计数。

    Returns:
        dict: {active, draft, degraded, deprecated}
    """
    counts = {"active": 0, "draft": 0, "degraded": 0, "deprecated": 0}
    try:
        conn = sqlite3.connect(BACKTEST_DB)
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM knowledge_entries GROUP BY status")
        for status, cnt in cur.fetchall():
            counts[status] = cnt
        conn.close()
    except Exception as e:
        logging.warning("_query_knowledge_status query failed: %s", e)
        return {"error": str(e)}
    return counts


def generate_report(results: dict, output_dir=None, dry_run=False) -> str:
    """根据运维结果生成 daily_doc_report.md。

    Args:
        results: 运维各层结果汇总 JSON
        output_dir: 输出目录（默认 PROJECT_ROOT/reports/daily/）
        dry_run: 若为 True，只打印内容不写入文件

    Returns:
        报告文件路径或 "DRY_RUN"
    """
    if output_dir is None:
        output_dir = str(PROJECT_ROOT / "reports" / "daily")
    out_dir = Path(output_dir)

    today = datetime.now().strftime("%Y-%m-%d")
    report_path = out_dir / f"daily_doc_report_{today}.md"

    # ── 提取各层结果 ──
    backtests = results.get("backtests", {})
    drafts = results.get("drafts", {})
    incoming = results.get("incoming", {})
    decay = results.get("decay", {})
    kb_backup = results.get("knowledge_backup", {})
    eng_backup = results.get("engine_backup", {})

    # ── 今日摘要计数 ──
    new_backtest_count = backtests.get("total", 0)
    by_strategy = backtests.get("by_strategy", {})
    grid_cnt = by_strategy.get("grid", 0)
    trend_cnt = by_strategy.get("trend", 0)
    reversal_cnt = by_strategy.get("reversal", 0)

    new_draft_count = drafts.get("total", 0)
    stale_count = incoming.get("stale", 0)

    decay_count = 0
    if isinstance(decay, dict):
        decay_count = decay.get("decayed", decay.get("total", 0))

    kb_status = "✅" if kb_backup.get("exists") or kb_backup.get("dry_run") else "❌"
    eng_status = "✅" if eng_backup.get("exists") or eng_backup.get("dry_run") else "❌"
    backup_ok = (kb_status == "✅" and eng_status == "✅")

    # ── 本周回测明细 ──
    bt_result = _query_weekly_backtests()
    weekly_bt = bt_result["rows"]
    bt_total = bt_result["total"]

    # ── 知识库状态 ──
    ks = _query_knowledge_status()

    # ── 构建报告 ──
    lines = []

    lines.append(f"# 文档管理日报 · {today[:10]} 02:00")
    lines.append("")

    # ── 今日摘要 ──
    lines.append("## 今日摘要")
    bt_detail_parts = []
    if grid_cnt:
        bt_detail_parts.append(f"grid x{grid_cnt}")
    if trend_cnt:
        bt_detail_parts.append(f"trend x{trend_cnt}")
    if reversal_cnt:
        bt_detail_parts.append(f"reversal x{reversal_cnt}")
    bt_detail = ", ".join(bt_detail_parts) if bt_detail_parts else "-"
    lines.append(f"- 新增回测记录: {new_backtest_count} 条（{bt_detail}）")
    lines.append(f"- 新增知识草稿: {new_draft_count} 条")
    lines.append(f"- 待处理文件: {stale_count} 个（incoming/ 超3天未处理）")
    lines.append(f"- 知识库衰减: {decay_count} 条")
    lines.append(f"- 备份状态: {'✅ 正常' if backup_ok else '❌ 异常'}")
    lines.append("")

    # ── 待处理事项 ──
    lines.append("## 待处理事项")
    has_pending = False
    for f in incoming.get("files", []):
        lines.append(f"- 📁 `{f['filename']}` — 已停留 {f['age_days']} 天")
        has_pending = True
    for d in drafts.get("drafts", []):
        lines.append(f"- 📝 `{d.get('summary', '?')[:40]}` — {d.get('strategy', '?')} / {d.get('symbol', '?')}「草稿」")
        has_pending = True
    if not has_pending:
        lines.append("  无待处理事项")
    lines.append("")

    # ── 本周回测汇总 ──
    lines.append("## 本周回测汇总")
    lines.append("| 策略 | 标的 | 夏普 | 最大回撤 | 评级 |")
    lines.append("|:----|:----|:----:|:-------:|:----:|")
    if weekly_bt:
        for row in weekly_bt:
            strategy = row.get("strategy", "-")
            symbol = row.get("symbol", "-")
            sharpe = row.get("sharpe_ratio", 0)
            max_dd = row.get("max_drawdown_pct", 0)
            grade = row.get("validity_grade", "-")
            lines.append(f"| {strategy} | {symbol} | {sharpe} | {max_dd}% | {grade} |")
    else:
        lines.append("| — | — | — | — | — |")
    # 末尾提示省略行
    if bt_total > len(weekly_bt):
        lines.append(f"> 共 {bt_total} 条记录，仅显示前 {len(weekly_bt)} 条。")
    elif bt_total > 0:
        lines.append(f"> 共 {bt_total} 条记录。")
    lines.append("")

    # ── 知识库状态 ──
    lines.append("## 知识库状态")
    lines.append(f"- 活跃条目: {ks['active']} 条")
    lines.append(f"- 草稿条目: {ks['draft']} 条")
    lines.append(f"- 已衰减: {ks['degraded']} 条")
    lines.append(f"- 已废弃: {ks['deprecated']} 条")
    lines.append("")

    # ── 备份状态 ──
    lines.append("## 备份状态")
    lines.append(f"- knowledge.db: {kb_status}")
    lines.append(f"- trade_engine.db: {eng_status}")

    text = "\n".join(lines)

    if dry_run:
        # 控制台输出时替换 emoji 为 ASCII（避免 Windows GBK 编码错误）
        ascii_text = text.replace('✅', '[OK]').replace('❌', '[FAIL]')
        print(ascii_text)
        return "DRY_RUN"

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")

    return str(report_path)


def main():
    parser = argparse.ArgumentParser(description="墨枢每日运维脚本")
    parser.add_argument("--dry-run", action="store_true", help="预扫描不执行")
    parser.add_argument("--layer", type=int, choices=[1, 2, 3], default=None,
                        help="只执行指定层（省略则全量运行）")
    parser.add_argument("--report", action="store_true", help="生成 daily_doc_report.md")
    parser.add_argument("--setup-cron", action="store_true", help="配置 02:00 定时任务（仅首次）")
    args = parser.parse_args()

    # 单独处理 --setup-cron
    if args.setup_cron:
        setup_cron()
        return {}

    _setup_logging()
    results = {}

    # Layer1 — 机械性整理与备份
    if args.layer in [None, 1]:
        _log_and_print("[Layer 1] 机械性整理开始...")
        _log_and_print(f"[Layer 1] dry_run={args.dry_run}")

        try:
            results["cleanup"] = cleanup_signal_files(args.dry_run)
            c = results["cleanup"]
            _log_and_print(f"  cleanup: cleaned={c.get('cleaned', '?')}, failed={c.get('failed', 0)}{' (dry-run)' if args.dry_run else ''}")
        except Exception as e:
            results["cleanup"] = {"error": str(e)}
            _log_and_print(f"  cleanup: FAILED — {e}", logging.ERROR)

        try:
            results["report_check"] = check_today_report(args.dry_run)
            rc = results["report_check"]
            _log_and_print(f"  report_check: missing={rc.get('missing')}, found={rc.get('found', 0)}")
        except Exception as e:
            results["report_check"] = {"error": str(e)}
            _log_and_print(f"  report_check: FAILED — {e}", logging.ERROR)

        try:
            results["archive"] = archive_old_reports(args.dry_run)
            a = results["archive"]
            _log_and_print(f"  archive: groups={a.get('archived_groups', 0)}, files={a.get('total_files', 0)}{' (dry-run)' if args.dry_run else ''}")
        except Exception as e:
            results["archive"] = {"error": str(e)}
            _log_and_print(f"  archive: FAILED — {e}", logging.ERROR)

        try:
            results["knowledge_backup"] = backup_knowledge_db(args.dry_run)
            kb = results["knowledge_backup"]
            _log_and_print(f"  knowledge_backup: path={kb.get('backup_path', 'N/A')}, exists={kb.get('exists', False)}{' (dry-run)' if kb.get('dry_run') else ''}")
        except Exception as e:
            results["knowledge_backup"] = {"error": str(e)}
            _log_and_print(f"  knowledge_backup: FAILED — {e}", logging.ERROR)

        try:
            results["engine_backup"] = backup_trade_engine(args.dry_run)
            eb = results["engine_backup"]
            _log_and_print(f"  engine_backup: path={eb.get('backup_path', 'N/A')}, exists={eb.get('exists', False)}{' (dry-run)' if eb.get('dry_run') else ''}")
        except Exception as e:
            results["engine_backup"] = {"error": str(e)}
            _log_and_print(f"  engine_backup: FAILED — {e}", logging.ERROR)

        _log_and_print("[Layer 1] 整理完成。")

    # Layer2 — 状态追踪
    if args.layer in [None, 2]:
        _log_and_print("[Layer 2] 状态追踪开始...")

        try:
            results["incoming"] = scan_incoming(args.dry_run)
            inc = results["incoming"]
            _log_and_print(f"  incoming: stale={inc.get('stale', 0)}")
        except Exception as e:
            results["incoming"] = {"error": str(e)}
            _log_and_print(f"  incoming: FAILED — {e}", logging.ERROR)

        try:
            results["drafts"] = scan_knowledge_drafts(args.dry_run)
            dr = results["drafts"]
            _log_and_print(f"  drafts: total={dr.get('total', 0)}")
        except Exception as e:
            results["drafts"] = {"error": str(e)}
            _log_and_print(f"  drafts: FAILED — {e}", logging.ERROR)

        try:
            results["backtests"] = scan_recent_backtests(args.dry_run)
            bt = results["backtests"]
            _log_and_print(f"  backtests: total={bt.get('total', 0)}, week_start={bt.get('week_start', '?')}")
        except Exception as e:
            results["backtests"] = {"error": str(e)}
            _log_and_print(f"  backtests: FAILED — {e}", logging.ERROR)

        try:
            results["unregistered"] = check_unregistered_files(args.dry_run)
            ur = results["unregistered"]
            _log_and_print(f"  unregistered: count={ur.get('unregistered', 0)}")
        except Exception as e:
            results["unregistered"] = {"error": str(e)}
            _log_and_print(f"  unregistered: FAILED — {e}", logging.ERROR)

        _log_and_print("[Layer 2] 状态追踪完成。")

    # Layer3 — 知识沉淀
    if args.layer in [None, 3]:
        _log_and_print("[Layer 3] 知识沉淀开始...")

        try:
            results["aggregate"] = trigger_knowledge_extractor(args.dry_run)
            ag = results["aggregate"]
            _log_and_print(f"  aggregate: aggregated={ag.get('aggregated', '?')}{' (dry-run)' if ag.get('dry_run') else ''}")
        except Exception as e:
            results["aggregate"] = {"error": str(e)}
            _log_and_print(f"  aggregate: FAILED — {e}", logging.ERROR)

        try:
            results["decay"] = trigger_decay_check(args.dry_run)
            dc = results["decay"]
            _log_and_print(f"  decay: decayed={dc.get('decayed', '?')}{' (dry-run)' if dc.get('dry_run') else ''}")
        except Exception as e:
            results["decay"] = {"error": str(e)}
            _log_and_print(f"  decay: FAILED — {e}", logging.ERROR)

        _log_and_print("[Layer 3] 知识沉淀完成。")

    # 生成报告
    if args.report:
        try:
            output_dir = str(PROJECT_ROOT / "reports" / "daily")
            report_path = generate_report(results, output_dir=output_dir, dry_run=args.dry_run)
            results["_report"] = {"report_path": report_path}
            _log_and_print(f"report: {report_path}")
        except Exception as e:
            results["_report"] = {"error": str(e)}
            _log_and_print(f"report: FAILED — {e}", logging.ERROR)

    output = json.dumps(results, indent=2, ensure_ascii=False)
    _log_and_print(output)

    # 写入结果到文件供其他进程读取（dry-run 模式不写入）
    if not args.dry_run:
        output_path = PROJECT_ROOT / "logs" / f"daily_maintenance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        _log_and_print(f"[done] 结果已写入: {output_path}")

    return results


# ═══════════════════════════════════════════════════════════
# Cron 集成
# ═══════════════════════════════════════════════════════════

CRON_SCHEDULER_CONFIG = PROJECT_ROOT / "config" / "scheduler.json"


def setup_cron():
    """配置 02:00 cron 定时任务（仅首次）。

    写入 config/scheduler.json 记录定时任务配置。
    """
    config_dir = CRON_SCHEDULER_CONFIG.parent
    config_dir.mkdir(parents=True, exist_ok=True)

    if CRON_SCHEDULER_CONFIG.exists():
        existing = json.loads(CRON_SCHEDULER_CONFIG.read_text(encoding="utf-8"))
        if "daily_maintenance_cron" in existing:
            _log_and_print("[setup-cron] 定时任务已存在，跳过配置。")
            _log_and_print(f"[setup-cron] 当前配置: {json.dumps(existing['daily_maintenance_cron'], indent=2, ensure_ascii=False)}")
            return False

    cron_config = {
        "daily_maintenance_cron": {
            "schedule": "02:00",
            "command": "python scripts/daily_maintenance.py --report",
            "description": "每日 02:00 执行完整运维并生成日报",
            "enabled": True,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "modified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    }

    existing = {}
    if CRON_SCHEDULER_CONFIG.exists():
        existing = json.loads(CRON_SCHEDULER_CONFIG.read_text(encoding="utf-8"))
    existing.update(cron_config)

    CRON_SCHEDULER_CONFIG.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    _log_and_print("[setup-cron] 定时任务配置已写入 config/scheduler.json")
    _log_and_print(f"[setup-cron] 计划: 每日 {cron_config['daily_maintenance_cron']['schedule']} 运行")
    _log_and_print("")
    _log_and_print("=" * 60)
    _log_and_print("  重要提示：手动执行确认")
    _log_and_print("=" * 60)
    _log_and_print(f"  请手动执行以下命令确认脚本运行正常：")
    _log_and_print(f"    cd {PROJECT_ROOT}")
    _log_and_print(f"    python scripts/daily_maintenance.py --dry-run --report")
    _log_and_print("")
    _log_and_print("  然后设置系统定时任务：")
    _log_and_print("    Windows: 使用任务计划程序，触发器设为每日 02:00")
    _log_and_print(f"    程序: python")
    _log_and_print(f"    参数: scripts/daily_maintenance.py --report")
    _log_and_print(f"    起始位置: {PROJECT_ROOT}")
    _log_and_print("=" * 60)
    return True


if __name__ == "__main__":
    main()
