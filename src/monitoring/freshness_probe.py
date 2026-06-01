"""
freshness_probe.py — 数据新鲜度探针
Author: 墨衡 (deepseek R1)
Created: 2026-06-01T15:40:00+08:00

功能：连接目标数据库，检查各数据源的最近更新时间，
      对比阈值判断 OK / WARN / ALERT，输出 JSON 报告。

探针列表：
  - a50_daily_ohlcv：日频价量数据
  - a50_daily_basic：日频估值数据
  - a50_factor_data：计算因子
  - a50_constituents：成分股列表

交易日历感知：
  - trade_calendar_aware=True：以交易日历最后一笔交易日为参考
  - trade_calendar_aware=False：以当前系统时间为参考

使用方式：
  python -c "from src.monitoring.freshness_probe import run_freshness_check; import json; print(json.dumps(run_freshness_check(), ensure_ascii=False, indent=2))"
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .freshness_config import (
    FRESHNESS_RULES,
    A50_IC_DB,
    TRADING_CALENDAR_DB,
)

# ============================================================
# 常量
# ============================================================
TZ = timezone(timedelta(hours=8))
logger = logging.getLogger("freshness_probe")

DATE_REPORT_KEYS = [
    "last_trade_date",
    "expected_date",
    "hours_elapsed",
    "status",
]


# ============================================================
# 辅助函数
# ============================================================

def _str_to_date(s: str) -> Optional[datetime]:
    """将 YYYYMMDD 字符串转为 datetime 日期（midnight）。"""
    if not s:
        return None
    try:
        s = s.strip()
        if len(s) == 8 and s.isdigit():
            return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=TZ)
        return None
    except (ValueError, IndexError):
        return None


def get_last_trade_date(calendar_db: Path = TRADING_CALENDAR_DB) -> Optional[datetime]:
    """
    从交易日历数据库获取最后一个交易日。

    查询：SELECT MAX(cal_date) FROM trading_calendar
          WHERE market='SSE' AND is_trading=1

    Args:
        calendar_db: 交易日历数据库路径

    Returns:
        datetime（当天午夜），或 None（不可用/无记录）
    """
    if not calendar_db.exists():
        logger.warning(f"交易日历数据库不存在: {calendar_db}")
        return None

    try:
        conn = sqlite3.connect(str(calendar_db))
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(cal_date) FROM trading_calendar "
            "WHERE market='SSE' AND is_trading=1"
        )
        row = cur.fetchone()
        conn.close()

        if row and row[0]:
            dt = _str_to_date(str(row[0]))
            if dt:
                logger.info(f"最后交易日（日历）: {row[0]}")
                return dt
        logger.warning("交易日历中未找到交易日记录")
        return None
    except Exception as e:
        logger.error(f"读取交易日历失败: {e}")
        return None


def get_max_date_from_table(
    db_path: Path,
    table: str,
    date_field: str,
) -> Tuple[Optional[datetime], Optional[str]]:
    """
    从指定数据库表的指定日期字段获取最大值。

    Args:
        db_path: 数据库路径
        table: 表名
        date_field: 日期字段名

    Returns:
        (datetime, raw_string) 或 (None, None) 当不可用时
    """
    if not db_path.exists():
        return None, None

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        # 先检查表是否存在
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        if not cur.fetchone():
            conn.close()
            return None, None

        # 查询最后日期
        cur.execute(f'SELECT MAX("{date_field}") FROM "{table}"')
        row = cur.fetchone()
        conn.close()

        if row and row[0]:
            dt = _str_to_date(str(row[0]))
            return dt, str(row[0])
        return None, None
    except Exception as e:
        logger.debug(f"查询 {db_path.name}/{table}.{date_field} 失败: {e}")
        return None, None


def compute_freshness_status(
    rule: dict,
    now: datetime,
    last_trade_date_from_calendar: Optional[datetime],
) -> dict:
    """
    对单条 FRESHNESS_RULES 规则执行新鲜度判定。

    判定逻辑：
      1. 尝试主数据库表 → 主源
      2. 若不可用，尝试回退数据库表 → 回源
      3. 都不可用 → status=UNKNOWN
      4. 根据 trade_calendar_aware 选择参考日期
      5. 比较 hours_elapsed 与 warn_hours / alert_hours

    Args:
        rule: FRESHNESS_RULES 中的一条配置
        now: 当前时间
        last_trade_date_from_calendar: 从日历获取的最后交易日

    Returns:
        dict 包含 status / last_trade_date / hours_elapsed / 等
    """
    name = rule.get("source", "unknown")
    warn_h = rule["warn_hours"]
    alert_h = rule["alert_hours"]
    is_calendar_aware = rule.get("trade_calendar_aware", False)

    result = {
        "source": name,
        "type": rule.get("type", ""),
        "last_trade_date": None,
        "last_trade_date_raw": None,
        "expected_date": None,
        "expected_date_raw": None,
        "hours_elapsed": None,
        "warn_hours": warn_h,
        "alert_hours": alert_h,
        "status": "UNKNOWN",
        "detail": "",
        "fallback_used": False,
    }

    # Step 1: 获取数据表中的最后日期
    dt, raw = get_max_date_from_table(
        rule["db_path"],
        rule["table"],
        rule.get("date_field", "trade_date"),
    )

    # Step 2: 如果主源不可用，尝试回退
    if dt is None and "fallback_db_path" in rule:
        fb_db = rule["fallback_db_path"]
        fb_table = rule.get("fallback_table", rule["table"])
        fb_field = rule.get("fallback_date_field", rule.get("date_field", "trade_date"))
        fb_dt, fb_raw = get_max_date_from_table(fb_db, fb_table, fb_field)
        if fb_dt is not None:
            dt, raw = fb_dt, fb_raw
            result["fallback_used"] = True
            result["detail"] = f"使用回退源: {fb_db.name}/{fb_table}"

    # Step 3: 都没数据
    if dt is None:
        result["detail"] = "数据源不可用（数据库或表不存在）"
        return result

    result["last_trade_date"] = dt.isoformat()
    result["last_trade_date_raw"] = raw

    # Step 4: 确定参考日期
    if is_calendar_aware and last_trade_date_from_calendar is not None:
        ref_date = last_trade_date_from_calendar
        result["expected_date"] = ref_date.isoformat()
        result["expected_date_raw"] = ref_date.strftime("%Y%m%d")
    else:
        ref_date = now
        result["expected_date"] = ref_date.isoformat()
        result["expected_date_raw"] = ref_date.strftime("%Y%m%d")

    # Step 5: 如果 last_data_date >= reference_date，视为最新
    if dt >= ref_date.replace(hour=0, minute=0, second=0, microsecond=0):
        result["status"] = "OK"
        result["hours_elapsed"] = 0.0
        return result

    # Step 6: 计算 hours_elapsed（从数据最后日期 midnight 到参考日期 midnight）
    ref_midnight = ref_date.replace(hour=0, minute=0, second=0, microsecond=0)
    data_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = ref_midnight - data_midnight
    hours = delta.total_seconds() / 3600.0
    result["hours_elapsed"] = round(hours, 1)

    # Step 7: 判定
    if hours <= warn_h:
        result["status"] = "OK"
    elif hours <= alert_h:
        result["status"] = "WARN"
    else:
        result["status"] = "ALERT"

    return result


# ============================================================
# 主入口
# ============================================================

def run_freshness_check(
    rules: Optional[Dict[str, dict]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    执行新鲜度全面检查。

    Args:
        rules: 可选的自定义规则字典（默认用 FRESHNESS_RULES）
        now: 可选的自定义当前时间（默认用系统当前时间）

    Returns:
        {
            "status": "OK" | "WARN" | "ALERT" | "UNKNOWN",
            "checked_at": "ISO8601",
            "last_trade_date": "YYYYMMDD or null",
            "sources": { ... },
            "summary": { "OK": n, "WARN": n, "ALERT": n, "UNKNOWN": n }
        }
    """
    now = now or datetime.now(TZ)
    rules = rules or FRESHNESS_RULES

    # 获取日历最后交易日
    last_trade_date_from_calendar = get_last_trade_date()

    result = {
        "status": "UNKNOWN",
        "checked_at": now.isoformat(),
        "last_trade_date": (
            last_trade_date_from_calendar.strftime("%Y%m%d")
            if last_trade_date_from_calendar
            else None
        ),
        "last_trade_date_iso": (
            last_trade_date_from_calendar.isoformat()
            if last_trade_date_from_calendar
            else None
        ),
        "sources": {},
        "summary": {"OK": 0, "WARN": 0, "ALERT": 0, "UNKNOWN": 0},
    }

    for key, rule in rules.items():
        status_info = compute_freshness_status(rule, now, last_trade_date_from_calendar)
        result["sources"][key] = status_info
        s = status_info["status"]
        result["summary"][s] = result["summary"].get(s, 0) + 1

    # 整体状态：取最严重
    if result["summary"].get("ALERT", 0) > 0:
        result["status"] = "ALERT"
    elif result["summary"].get("WARN", 0) > 0:
        result["status"] = "WARN"
    elif result["summary"].get("UNKNOWN", 0) > 0:
        result["status"] = "UNKNOWN"
    else:
        result["status"] = "OK"

    return result


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    report = run_freshness_check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
