# -*- coding: utf-8 -*-
"""
price_utils.py — 行情价格获取与滑点计算工具
作者：墨衡 (moheng)
创建时间：2026-05-12 17:53 GMT+8

提取自 order_engine.py (V1.1-005 模块拆分)

功能：
1. get_current_price() — 从信号文件/信号队列获取当前参考价格
2. apply_slippage() — 对指定价格应用滑点调整
3. apply_slippage_if_needed() — 条件性应用滑点（确认成交时）

设计说明：
  get_current_price 逻辑原本内联在 confirm_fill 方法的调用端
  （调用者自行确定 fill_price），这里提供统一的参考价格获取入口。

依赖：无（纯数值计算）
"""

import logging
import os
import json
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# 滑点计算
# ============================================================


def apply_slippage(base_price: float, slippage_rate: float, direction: str = "buy") -> float:
    """对参考价格应用滑点调整。

    滑点方向：
      - buy（买入）：价格上浮（不利方向） → base_price × (1 + slippage_rate)
      - sell（卖出）：价格下浮（不利方向） → base_price × (1 - slippage_rate)

    参数：
        base_price — 参考价格（如信号建议价）
        slippage_rate — 滑点率（如 0.001 = 千1，0.0 = 无滑点）
        direction — "buy"（买入）或 "sell"（卖出）

    返回：
        应用滑点后的价格（四舍五入到小数点后2位）
    """
    if slippage_rate <= 0.0:
        return round(base_price, 2)

    if direction == "buy":
        return round(base_price * (1.0 + slippage_rate), 2)
    else:
        return round(base_price * (1.0 - slippage_rate), 2)


def apply_slippage_if_needed(base_price: float, fill_price: Optional[float],
                              slippage_rate: float, direction: str = "buy") -> float:
    """条件性应用滑点：如果未提供 fill_price，则从 base_price 计算含滑点价格。

    这是 confirm_fill 中滑点处理逻辑的提取：
      - 若提供了 fill_price，直接使用（调用者已自行确定）
      - 若未提供，则从 base_price + slippage 计算

    参数：
        base_price — 参考价格（原始订单价格）
        fill_price — 外部指定的成交价（None 表示自动应用滑点）
        slippage_rate — 滑点率
        direction — 滑点方向（"buy" / "sell"）

    返回：
        最终成交价
    """
    if fill_price is not None:
        return fill_price
    return apply_slippage(base_price, slippage_rate, direction)


# ============================================================
# 参考价格获取
# ============================================================


def get_current_price(symbol: str, signals_dir: Optional[str] = None) -> Optional[float]:
    """从最近的信号文件获取指定品种的当前参考价格。

    遍历 signals_dir 下最新的信号 JSON，提取指定 symbol 的价格。

    参数：
        symbol — 品种代码（如 "600519.SH"）
        signals_dir — 信号目录路径（默认使用 moheng 信号目录）

    返回：
        价格（float），未找到则返回 None
    """
    if signals_dir is None:
        signals_dir = r"C:\Users\17699\mo_zhi_sharereports\signals\moheng"

    if not os.path.isdir(signals_dir):
        logger.warning(f"[PriceUtils] 信号目录不存在: {signals_dir}")
        return None

    try:
        # 列出所有 JSON 文件，按修改时间排序取最新的
        json_files = [
            os.path.join(signals_dir, f)
            for f in os.listdir(signals_dir)
            if f.endswith(".json") and os.path.isfile(os.path.join(signals_dir, f))
        ]
        if not json_files:
            return None

        latest = max(json_files, key=os.path.getmtime)

        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 尝试多种路径提取价格
        # 格式1: {"symbol": "...", "suggested_price": ...}
        if isinstance(data, dict):
            if data.get("symbol") == symbol and "suggested_price" in data:
                return float(data["suggested_price"])

            # 格式2: 嵌套在 signals 或 results 字段
            for key in ("signals", "results", "data", "items"):
                items = data.get(key, [])
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and item.get("symbol") == symbol:
                            for price_key in ("suggested_price", "price", "fill_price"):
                                if price_key in item:
                                    return float(item[price_key])

        logger.debug(f"[PriceUtils] 在 {latest} 中未找到 {symbol} 的价格")
        return None

    except Exception as e:
        logger.warning(f"[PriceUtils] 读取信号文件失败: {e}")
        return None
