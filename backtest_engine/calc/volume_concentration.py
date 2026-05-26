# volume_concentration.py
# 墨家投资室 - 量集中度计算模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 量集中度：日内成交量在时间上的集中程度。
#   指标1: HHI-like (Herfindahl-Hirschman Index)
#      HHI = SUM((vol_i / total_vol) ^ 2)
#      HHI越高 → 量集中在少数分钟
#      HHI越低 → 量均匀分布
#
#   指标2: 前N%(时间) 的成交量占比
#      例如：前25%时间的成交量占比
#      占比高 → 量集中在早盘
#
# 基于分钟级数据（Phase 4）计算。
#
# 使用方式：
#   from calc.volume_concentration import calc_hhi, calc_top_pct_concentration
#   hhi = calc_hhi(volumes=[...])

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def calc_hhi(volumes: List[float]) -> Optional[float]:
    """
    计算量集中度的 HHI 指标。
    
    HHI = SUM((vol_i / total_vol)^2)
    
    范围：
      - ~0: 完全均匀（每笔成交量一样）
      - 0.01~0.05: 正常分散
      - 0.05~0.1: 中度集中
      - >0.1: 高度集中（少数时间窗口完成大部分成交量）
    
    Args:
        volumes: 分钟级成交量列表
        
    Returns:
        HHI 值，或 None（数据不足）
    """
    if not volumes or len(volumes) < 5:
        return None

    vols = [v for v in volumes if v > 0]
    if len(vols) < 5:
        return None

    total = sum(vols)
    if total == 0:
        return 0.0

    hhi = sum((v / total) ** 2 for v in vols)
    return round(hhi, 6)


def calc_top_pct_concentration(volumes: List[float],
                                 time_pct: float = 0.25) -> Optional[float]:
    """
    计算前 time_pct% 时间的成交量占总成交量的比例。
    
    例如 time_pct=0.25: 前 25% 的时间窗口的成交量占比。
    
    Args:
        volumes: 分钟级成交量列表（按时间顺序）
        time_pct: 时间比例 [0, 1]
        
    Returns:
        成交量占比 [0, 1]，或 None
    """
    if not volumes or len(volumes) < 5:
        return None

    n = len(volumes)
    cutoff = max(1, int(n * time_pct))

    top_vol = sum(volumes[:cutoff])
    total_vol = sum(volumes)

    if total_vol == 0:
        return 0.0

    return round(top_vol / total_vol, 4)


def calc_gini_coefficient(volumes: List[float]) -> Optional[float]:
    """
    计算量集中度的基尼系数。
    
    Gini = 2 * SUM(i * v_i) / (n * SUM(v_i)) - (n + 1) / n
    
    范围：
      - 0: 完全均匀
      - 1: 完全集中
      
    Args:
        volumes: 分钟级成交量列表
        
    Returns:
        基尼系数 [0, 1]，或 None
    """
    if not volumes or len(volumes) < 5:
        return None

    vols = sorted([v for v in volumes if v > 0])
    if len(vols) < 5:
        return None

    n = len(vols)
    total = sum(vols)

    if total == 0:
        return 0.0

    # Gini = (2/n² * sum(i * v_i) / mean) - (n+1)/n 的简化形式
    # 更稳定的公式：
    sum_weighted = sum((i + 1) * v for i, v in enumerate(vols))
    gini = (2 * sum_weighted) / (n * total) - (n + 1) / n

    return round(gini, 4)


def classify_concentration(hhi: float) -> str:
    """分类量集中度"""
    if hhi > 0.1:
        return 'highly_concentrated'
    elif hhi > 0.05:
        return 'moderately_concentrated'
    elif hhi > 0.01:
        return 'normal'
    else:
        return 'uniform'


def get_concentration_label_cn(label: str) -> str:
    """中文标签"""
    labels = {
        'highly_concentrated': '高度集中（少数时间完成大部分成交）',
        'moderately_concentrated': '中度集中',
        'normal': '正常分散',
        'uniform': '均匀分布',
    }
    return labels.get(label, label)
