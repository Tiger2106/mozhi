"""
管线前置健康检查：数据新鲜度探针
Author: 墨衡 (deepseek R1)
Created: 2026-06-01T15:47+08:00

用途：在早报管线启动时执行数据新鲜度检查，仅记录不阻断。
      如有 WARN/ALERT 的记录，写入管线报告中供后续步骤使用。

使用方式：
  from src.morning_pipeline.steps.preflight_freshness import run_freshness_preflight
  result = run_freshness_preflight(reports_dir="reports/freshness")
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from src.monitoring.freshness_probe import run_freshness_check

TZ = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)

# 默认 reports/freshness 目录（相对于项目根）
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports" / "freshness"


def run_freshness_preflight(reports_dir: Optional[str] = None) -> dict:
    """
    执行新鲜度检查，返回结果。WARN/ALERT 会记录警告日志。
    检查结果写入 reports/freshness/{日期}_freshness.json。

    此函数是**非阻塞**的 — 只记录不阻断管线执行。
    即便数据延迟 1–2 天，旧数据仍然可用，检查仅用于报告和预警。

    Args:
        reports_dir: 输出目录路径（字符串）。默认使用 reports/freshness/。

    Returns:
        dict: freshness_probe.run_freshness_check() 的完整返回结果。
              包含 sources 详细信息和 summary 汇总统计。
    """
    result = run_freshness_check()
    summary = result.get("summary", {})
    status = result.get("status", "UNKNOWN")

    # 日志记录
    if summary.get("ALERT", 0) > 0:
        logger.warning(
            "Freshness ALERT: %d source(s) stale — %s",
            summary["ALERT"],
            _describe_stale_sources(result, "ALERT"),
        )
    elif summary.get("WARN", 0) > 0:
        logger.warning(
            "Freshness WARN: %d source(s) stale — %s",
            summary["WARN"],
            _describe_stale_sources(result, "WARN"),
        )
    else:
        total = (
            summary.get("OK", 0) + summary.get("WARN", 0)
            + summary.get("ALERT", 0) + summary.get("UNKNOWN", 0)
        )
        logger.info("Freshness OK: all %d sources fresh", total)

    # 写入状态文件
    _write_freshness_report(result, reports_dir)

    return result


def _describe_stale_sources(result: dict, status_filter: str) -> str:
    """返回状态为 status_filter 的源名称列表（逗号分隔）。"""
    stale = []
    for key, info in result.get("sources", {}).items():
        if info.get("status") == status_filter:
            stale.append(key)
    return ", ".join(stale) if stale else "(none)"


def _write_freshness_report(result: dict, reports_dir: Optional[str] = None) -> str:
    """
    将新鲜度检查结果写入文件。

    Args:
        result: run_freshness_check() 的返回结果
        reports_dir: 输出目录路径（字符串或 None）

    Returns:
        str: 写入的文件路径
    """
    target_dir = Path(reports_dir) if reports_dir else DEFAULT_REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(TZ)
    date_str = now.strftime("%Y%m%d")
    file_path = target_dir / f"{date_str}_freshness.json"

    # 补充元数据字段
    report = dict(result)
    report["_meta"] = {
        "generated_by": "preflight_freshness",
        "generated_at": now.isoformat(),
        "file_version": "1.0",
    }

    file_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Freshness report written: %s", file_path)
    return str(file_path)


def get_freshness_summary_line(result: dict) -> str:
    """
    生成一行摘要文本，供早报元数据使用。

    返回格式示例：
      "数据新鲜度: OK (4/4)"
      "数据新鲜度: WARN (3/4 OK, 1 延迟)"
      "数据新鲜度: ALERT (2/4 OK, 2 延迟)"

    Args:
        result: run_freshness_check() 的返回结果

    Returns:
        str: 一行摘要
    """
    summary = result.get("summary", {})
    status = result.get("status", "UNKNOWN")
    total = sum(summary.get(s, 0) for s in ["OK", "WARN", "ALERT", "UNKNOWN"])
    ok_count = summary.get("OK", 0)

    if status == "OK":
        return f"数据新鲜度: OK ({ok_count}/{total})"
    elif status == "WARN":
        stale = summary.get("WARN", 0)
        return f"数据新鲜度: WARN ({ok_count}/{total} OK, {stale} 延迟)"
    elif status == "ALERT":
        stale = summary.get("ALERT", 0)
        return f"数据新鲜度: ALERT ({ok_count}/{total} OK, {stale} 严重延迟)"
    else:
        unknown = summary.get("UNKNOWN", 0)
        return f"数据新鲜度: UNKNOWN ({ok_count}/{total} OK, {unknown} 不可用)"


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    result = run_freshness_preflight()
    print("\n=== 摘要 ===")
    print(get_freshness_summary_line(result))
    print(f"状态: {result.get('status', '?')}")
    print(f"源总数: {len(result.get('sources', {}))}")
