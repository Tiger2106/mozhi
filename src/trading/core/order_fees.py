# -*- coding: utf-8 -*-
"""
order_fees.py — 费用计算统一接口
作者：墨衡 (moheng)
创建时间：2026-05-12 17:52 GMT+8

提取自 order_engine.py (V1.1-005 模块拆分)

功能：
  统一封装费用计算函数，委托给 account_manager 和 fees 模块。
  避免现有模块间费用函数的重复定义。

设计说明：
  account_manager.py 中定义了三套费用函数（calculate_commission,
  calculate_stamp_tax, calculate_frozen_amount），fees.py 定义了
  另一套（calc_commission, calc_stamp_tax, estimate_commission 等）。
  本模块作为薄委托层，按需统一导出 order_engine 使用的版本。

依赖：
  - account_manager（calculate_commission / calculate_stamp_tax / calculate_frozen_amount）
  - fees（estimate_commission - Saga 冻结预估）
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


# ============================================================
# 内部导入（兼容路径）
# ============================================================

try:
    from .account_manager import calculate_commission, calculate_stamp_tax, calculate_frozen_amount
    from .fees import estimate_commission
except ImportError:
    import os
    import sys
    _DIR = os.path.dirname(os.path.abspath(__file__))
    if _DIR not in sys.path:
        sys.path.insert(0, _DIR)
    from account_manager import calculate_commission, calculate_stamp_tax, calculate_frozen_amount
    from fees import estimate_commission
    del _DIR


# ============================================================
# 重新导出（保持 import 路径兼容）
# ============================================================

__all__ = [
    "calculate_commission",
    "calculate_stamp_tax",
    "calculate_frozen_amount",
    "estimate_commission",
    "calculate_total_fees",
]
