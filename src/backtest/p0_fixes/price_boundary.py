"""
墨枢 - p0_fixes.price_boundary
涨跌停常量和边界计算函数（从原引擎 import 的桥接模块）

P1 流水线增量代码路径。
所有实现位于 backtest_engine/sim_layer/price_boundary.py，
本模块作为 import 桥接供新引擎使用。

author: moheng
created_time: 2026-05-28T12:00+08:00
"""
from __future__ import annotations

# 从原引擎导入所有符号
from backtest_engine.sim_layer.price_boundary import (
    MarketType,
    LIMIT_UP_RATIO,
    LIMIT_DOWN_RATIO,
    calc_price_boundary,
    check_limit_trade,
    get_market_type,
    enrich_bar_with_boundary,
    is_st_stock,
)

__all__ = [
    "MarketType",
    "LIMIT_UP_RATIO",
    "LIMIT_DOWN_RATIO",
    "calc_price_boundary",
    "check_limit_trade",
    "get_market_type",
    "enrich_bar_with_boundary",
    "is_st_stock",
]
