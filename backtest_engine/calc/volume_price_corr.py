# volume_price_corr.py
# 墨家投资室 - 量价相关系数计算模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 量价相关系数：日内分钟级成交量与价格变化的相关性。
#   正相关 → 价涨量增/价跌量缩（健康上涨）
#   负相关 → 价涨量缩/价跌量增（放量下跌→危险信号）
#   零相关 → 量价分离
#
# 基于分钟级数据（Phase 4）计算。
#
# 使用方式：
#   from calc.volume_price_corr import calc_volume_price_corr
#   corr = calc_volume_price_corr(volumes=[...], prices=[...])

import math
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def calc_volume_price_corr(volumes: List[float],
                           prices: List[float],
                           price_change_mode: str = 'bracket') -> Optional[float]:
    """
    计算量价相关系数（Pearson）。

    Args:
        volumes: 分钟级成交量列表
        prices: 分钟级价格列表（收盘价）
        price_change_mode:
            'bracket' - 用该分钟收盘与前一分钟收盘的涨跌（默认）
            'amplitude' - 用该分钟的振幅 (high - low) / open

    Returns:
        相关系数 [-1, 1]。
          > 0.3: 量价正相关（健康）
          < -0.3: 量价负相关（警惕）
          ≈ 0: 量价分离
        None: 数据不足时
    """
    if not volumes or not prices:
        return None

    n = min(len(volumes), len(prices))
    if n < 10:
        return None

    volumes = volumes[:n]
    prices = prices[:n]

    # 计算价格变化
    if price_change_mode == 'bracket':
        # 用逐分钟涨跌
        bracket = []
        for i in range(1, n):
            prev_close = prices[i - 1]
            if prev_close > 0:
                bracket.append((prices[i] - prev_close) / prev_close * 100)
            else:
                bracket.append(0.0)
        # 对应的成交量也去掉第一个（差分后少一个）
        vols = volumes[1:]
    elif price_change_mode == 'amplitude':
        logger.warning("Amplitude mode not yet supported, falling back to brackets")
        bracket = []
        for i in range(1, n):
            prev_close = prices[i - 1]
            if prev_close > 0:
                bracket.append((prices[i] - prev_close) / prev_close * 100)
            else:
                bracket.append(0.0)
        vols = volumes[1:]
    else:
        return None

    if len(vols) < 10:
        return None

    # 计算 Pearson 相关系数
    corr = _pearson(vols, bracket)
    return round(corr, 4)


def classify_correlation(corr: float) -> str:
    """
    分类量价相关性状态。

    Args:
        corr: 相关系数

    Returns:
        'strong_positive' | 'positive' | 'neutral' | 'negative' | 'strong_negative'
    """
    if corr > 0.6:
        return 'strong_positive'
    elif corr > 0.2:
        return 'positive'
    elif corr < -0.6:
        return 'strong_negative'
    elif corr < -0.2:
        return 'negative'
    else:
        return 'neutral'


def get_corr_label_cn(label: str) -> str:
    """中文标签"""
    labels = {
        'strong_positive': '量价强正相关（健康放量上涨）',
        'positive': '轻度正相关',
        'neutral': '量价分离',
        'negative': '轻度负相关',
        'strong_negative': '量价负相关（放量下跌/缩量上涨）',
    }
    return labels.get(label, label)


# ── 内部 ──────────────────────────────────────────────────


def _pearson(x: List[float], y: List[float]) -> float:
    """计算 Pearson 相关系数"""
    n = len(x)
    if n < 3:
        return 0.0

    # 过滤掉 None/NaN
    pairs = [(xi, yi) for xi, yi in zip(x, y) if xi is not None and yi is not None]
    if len(pairs) < 3:
        return 0.0

    n = len(pairs)
    x_vals = [p[0] for p in pairs]
    y_vals = [p[1] for p in pairs]

    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n

    numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in pairs)
    denom_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x_vals))
    denom_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y_vals))

    if denom_x == 0 or denom_y == 0:
        return 0.0

    return numerator / (denom_x * denom_y)
