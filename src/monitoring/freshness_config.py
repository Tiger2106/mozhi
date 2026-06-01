"""
freshness_config.py — 数据新鲜度探针配置
Author: 墨衡
Created: 2026-06-01T15:40:00+08:00

阈值经玄知签字确认（§4.1 数据新鲜度阈值表）
"""

from pathlib import Path

# ============================================================
# 项目根路径（自动检测从 src/monitoring → mo_zhi_sharereports）
# ============================================================
REPORTS_BASE = Path(__file__).resolve().parents[2]  # mo_zhi_sharereports

# ============================================================
# 数据库路径
# ============================================================
A50_IC_DB = REPORTS_BASE / "reports" / "a50_ic" / "a50_ic.db"
TRADING_CALENDAR_DB = REPORTS_BASE / "db" / "trading_calendar.db"
MARKET_DATA_DB = REPORTS_BASE / "market_data.db"
FACTOR_REPOSITORY_DB = REPORTS_BASE / "factor_repository.db"

# ============================================================
# 日期阈值配置（玄知签字确认）
# ============================================================
FRESHNESS_RULES = {
    "a50_daily_ohlcv": {
        "source": "a50_ic.db/a50_daily_ohlcv",
        "type": "daily_prices",
        "warn_hours": 24,
        "alert_hours": 48,
        "trade_calendar_aware": True,       # 跳过非交易日
        "db_path": A50_IC_DB,
        "table": "a50_daily_ohlcv",
        "date_field": "trade_date",
        # 回退：如果 a50_ic.db 不可用，尝试 market_data.db/stock_daily
        "fallback_db_path": MARKET_DATA_DB,
        "fallback_table": "stock_daily",
    },
    "a50_daily_basic": {
        "source": "a50_ic.db/a50_daily_basic",
        "type": "daily_fundamentals",
        "warn_hours": 24,
        "alert_hours": 48,
        "trade_calendar_aware": True,
        "db_path": A50_IC_DB,
        "table": "a50_daily_basic",
        "date_field": "trade_date",
        "fallback_db_path": MARKET_DATA_DB,
        "fallback_table": "stock_daily",
    },
    "a50_factor_data": {
        "source": "a50_ic.db/factor_values",
        "type": "calculated_factors",
        "warn_hours": 24,
        "alert_hours": 48,
        "trade_calendar_aware": True,
        "db_path": A50_IC_DB,
        "table": "factor_values",
        "date_field": "trade_date",
        "fallback_db_path": FACTOR_REPOSITORY_DB,
        "fallback_table": "daily_factors",
        "fallback_date_field": "date",
    },
    "a50_constituents": {
        "source": "a50_ic.db/a50_constituents",
        "type": "constituent_list",
        "warn_hours": 168,          # 7天
        "alert_hours": 336,         # 14天
        "trade_calendar_aware": False,
        "db_path": A50_IC_DB,
        "table": "a50_constituents",
        "date_field": "update_date",
    },
}
