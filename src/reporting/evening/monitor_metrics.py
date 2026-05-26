# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
monitor_metrics.py — Phase1a 信号轮询监控指标

提供外部查询接口（可用于 cron 健康巡检、仪表盘集成），
以及指标历史快照写入功能。

指标来源：
  - Phase1aSignalPoller.get_metrics() 的实时快照
  - 写入 metrics/{date}/ 目录的历史数据

作者：墨衡 (moheng)
创建时间：2026-05-12 19:47 GMT+8
任务：P0-MX-001-Phase1b
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from utils.time_utils import now_iso, now_str, today

logger = logging.getLogger("paper_trade.monitor_metrics")

TZ_CST = SHANGHAI_TZ

# 配置
METRICS_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\reports"

# 文件路径
METRICS_BASE_DIR = os.path.join(
    r"C:\Users\17699\mo_zhi_sharereports",
    "signals", "reports", "metrics"
)

# ============================================================
# 快照写入
# ============================================================

def write_metrics_snapshot(stats: dict) -> str:
    """将轮询统计快照写入历史文件。

    路径: signals/reports/metrics/{date}/poller_snapshot_{seq}.json

    Args:
        stats: Phase1aSignalPoller.get_metrics() 返回的统计 dict

    Returns:
        写入的文件路径（str）
    """
    date_str = today().strftime("%Y%m%d")
    seq = int(datetime.now(TZ_CST).timestamp())
    dir_path = os.path.join(METRICS_BASE_DIR, date_str)
    os.makedirs(dir_path, exist_ok=True)

    snapshot = {
        "type": "poller_metrics_snapshot",
        "timestamp": now_iso(),
        "seq": seq,
        "metrics": {
            "scanned": stats.get("scanned", 0),
            "processed": stats.get("processed", 0),
            "skipped": stats.get("skipped", 0),
            "failed": stats.get("failed", 0),
            "risk_blocked": stats.get("risk_blocked", 0),
            "total": stats.get("total", 0),
            "warmup_skip": stats.get("warmup_skip", False),
            "non_trading_day": stats.get("non_trading_day", False),
            "cooling_active": stats.get("cooling_active", False),
        },
        # 只保留最近的详情（防止文件过大）
        "details_count": len(stats.get("details", [])),
        "details": stats.get("details", []),
    }

    filepath = os.path.join(dir_path, f"poller_snapshot_{seq}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    logger.info(f"[MonitorMetrics] 指标快照写入: {filepath}")
    return filepath

# ============================================================
# 最新快照查询
# ============================================================

def read_latest_metrics(date_str: Optional[str] = None) -> Optional[dict]:
    """读取指定日期最新的指标快照。

    Args:
        date_str: 日期字符串 YYYYMMDD（默认当天）

    Returns:
        最新的指标快照 dict，无快照则返回 None
    """
    date_str = date_str or today().strftime("%Y%m%d")
    dir_path = os.path.join(METRICS_BASE_DIR, date_str)
    if not os.path.isdir(dir_path):
        return None

    snapshots = sorted([
        f for f in os.listdir(dir_path)
        if f.startswith("poller_snapshot_") and f.endswith(".json")
    ])
    if not snapshots:
        return None

    latest_file = os.path.join(dir_path, snapshots[-1])
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[MonitorMetrics] 读取快照失败 {latest_file}: {e}")
        return None

# ============================================================
# 日汇总
# ============================================================

def get_daily_summary(date_str: Optional[str] = None) -> dict:
    """计算指定日期的累计指标汇总。

    Args:
        date_str: 日期 YYYYMMDD（默认当天）

    Returns:
        {
            "total_scanned": int,
            "total_processed": int,
            "total_skipped": int,
            "total_failed": int,
            "total_risk_blocked": int,
            "snapshot_count": int,
            "date": str,
        }
    """
    date_str = date_str or today().strftime("%Y%m%d")
    dir_path = os.path.join(METRICS_BASE_DIR, date_str)

    if not os.path.isdir(dir_path):
        return {
            "date": date_str,
            "snapshot_count": 0,
            "total_scanned": 0,
            "total_processed": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "total_risk_blocked": 0,
        }

    snapshots = sorted([
        f for f in os.listdir(dir_path)
        if f.startswith("poller_snapshot_") and f.endswith(".json")
    ])

    total_scanned = 0
    total_processed = 0
    total_skipped = 0
    total_failed = 0
    total_risk_blocked = 0

    for fname in snapshots:
        try:
            with open(os.path.join(dir_path, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            m = data.get("metrics", {})
            total_scanned += m.get("scanned", 0)
            total_processed += m.get("processed", 0)
            total_skipped += m.get("skipped", 0)
            total_failed += m.get("failed", 0)
            total_risk_blocked += m.get("risk_blocked", 0)
        except (json.JSONDecodeError, IOError):
            continue

    return {
        "date": date_str,
        "snapshot_count": len(snapshots),
        "total_scanned": total_scanned,
        "total_processed": total_processed,
        "total_skipped": total_skipped,
        "total_failed": total_failed,
        "total_risk_blocked": total_risk_blocked,
    }

# ============================================================
# 健康状态检查
# ============================================================

def health_check(date_str: Optional[str] = None) -> dict:
    """Phase1a 轮询器健康检查。

    检查项：
    - 是否有最新快照（< 10分钟）
    - 最近 5 次是否持续失败

    Returns:
        {
            "status": "OK" | "WARN" | "FAIL",
            "latest_snapshot_age_seconds": int | None,
            "consecutive_failures": int,
            "checks": dict,
        }
    """
    date_str = date_str or today().strftime("%Y%m%d")
    now_ts = datetime.now(TZ_CST).timestamp()

    result = {
        "status": "OK",
        "date": date_str,
        "latest_snapshot_age_seconds": None,
        "consecutive_failures": 0,
        "checks": {},
    }

    latest = read_latest_metrics(date_str)
    if latest is None:
        result["status"] = "WARN"
        result["checks"]["has_snapshot"] = False
        return result

    snapshot_ts = datetime.fromisoformat(latest.get("timestamp", "")).timestamp()
    age = int(now_ts - snapshot_ts)
    result["latest_snapshot_age_seconds"] = age
    result["checks"]["has_snapshot"] = True

    # 快照太旧（>10分钟）告警
    if age > 600:
        result["status"] = "WARN"
        result["checks"]["snapshot_age"] = f"{age}s (超过600s阈值)"

    # 检查最近5次快照的失败数
    dir_path = os.path.join(METRICS_BASE_DIR, date_str)
    if os.path.isdir(dir_path):
        snapshots = sorted([
            f for f in os.listdir(dir_path)
            if f.startswith("poller_snapshot_") and f.endswith(".json")
        ])
        recent = snapshots[-5:] if len(snapshots) >= 5 else snapshots
        failures = 0
        for fname in recent:
            try:
                with open(os.path.join(dir_path, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                failures += data.get("metrics", {}).get("failed", 0)
            except (json.JSONDecodeError, IOError):
                continue
        result["consecutive_failures"] = failures
        if failures >= 5:
            result["status"] = "WARN"
            result["checks"]["recent_failures"] = f"{failures} (>=5次阈值)"

    return result

# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    action = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if action == "summary":
        result = get_daily_summary()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif action == "health":
        result = health_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif action == "latest":
        result = read_latest_metrics()
        print(json.dumps(result, ensure_ascii=False, indent=2) if result else "null")
    else:
        print(f"Usage: {sys.argv[0]} [summary|health|latest]")
