# -*- coding: utf-8 -*-
"""
trade_calendar.py — 交易日历模块（P0-MX-001-Phase1e）

判断给定日期是否为A股交易日。
MVP粗略版：排除周末 + 国假硬编码列表，后续可升级为akshare API。

作者：墨衡 (moheng)
创建时间：2026-05-12 20:18 GMT+8
任务：P0-MX-001-Phase1e
"""

from datetime import date, timedelta
from typing import Optional

# ============================================================
# 国假日历（2026年粗略版）
# 来源：国务院放假安排，不含调休上班日
# ============================================================

_HOLIDAYS = frozenset({
    # ── 元旦（1月1日-2日）──
    "2026-01-01",
    "2026-01-02",
    # ── 春节（2月15日-21日）──
    "2026-02-15", "2026-02-16", "2026-02-17",
    "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21",
    # ── 清明（4月4日-6日）──
    "2026-04-04", "2026-04-05", "2026-04-06",
    # ── 劳动节（5月1日-5日）──
    "2026-05-01", "2026-05-02", "2026-05-03",
    "2026-05-04", "2026-05-05",
    # ── 端午节（6月25日-27日）──
    "2026-06-25", "2026-06-26", "2026-06-27",
    # ── 中秋+国庆（9月27日-10月8日）──
    "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
})


# ============================================================
# 公开接口
# ============================================================

def is_trading_day(dt: Optional[date] = None) -> bool:
    """判断给定日期是否为A股交易日。

    规则：
    - 周六、周日 → False
    - 元旦、春节、清明、劳动、端午、中秋、国庆 → False
    - 其余 → True

    Args:
        dt: 待判断的日期，None 表示今日

    Returns:
        True 若为交易日
    """
    dt = dt or date.today()
    # 周末 → False
    if dt.weekday() >= 5:
        return False
    # 国假 → False
    return dt.isoformat() not in _HOLIDAYS


def next_trading_day(dt: Optional[date] = None) -> str:
    """返回下一个交易日 YYYY-MM-DD。

    Args:
        dt: 基准日期，None 表示今日

    Returns:
        下一个交易日的 ISO 格式字符串
    """
    dt = dt or date.today()
    d = dt + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d.isoformat()


def previous_trading_day(dt: Optional[date] = None) -> str:
    """返回上一个交易日 YYYY-MM-DD。

    Args:
        dt: 基准日期，None 表示今日

    Returns:
        上一个交易日的 ISO 格式字符串
    """
    dt = dt or date.today()
    d = dt - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d.isoformat()
