# volume_skewness.py
# 墨家投资室 - 量偏度计算模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 量偏度：日内成交量分布的偏度（Skewness）。
#   - 正偏度 → 成交量集中在尾盘（尾市放量）
#   - 负偏度 → 成交量集中在早盘（开盘集中成交）
#   - 零偏度 → 成交量均匀分布
#
# 基于分钟级数据（Phase 4）计算。
#
# 使用方式：
#   from calc.volume_skewness import calc_volume_skewness
#   skew = calc_volume_skewness(volumes=[5000, 6000, ..., 4000])

import math
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def calc_volume_skewness(volumes: List[float]) -> Optional[float]:
    """
    计算量偏度（Fisher-Pearson 标准化三阶矩）。
    
    Args:
        volumes: 日内按时间顺序排列的成交量列表（分钟级）
        
    Returns:
        偏度值。范围通常 [-3, 3]。
          > 0.5: 尾盘集中
          < -0.5: 早盘集中
          ≈ 0: 均匀分布
        None: 数据不足时
    """
    if not volumes or len(volumes) < 8:
        return None

    # 过滤掉零值
    vols = [v for v in volumes if v > 0]
    if len(vols) < 8:
        return None

    n = len(vols)
    mean = sum(vols) / n

    if mean == 0:
        return 0.0

    # 方差
    variance = sum((v - mean) ** 2 for v in vols) / (n - 1)
    if variance == 0:
        return 0.0

    std = math.sqrt(variance)

    # 三阶矩
    skewness = sum((v - mean) ** 3 for v in vols) / ((n - 1) * (std ** 3))

    # 小样本修正 (n < 50)
    if n < 50:
        adjust = math.sqrt(n * (n - 1)) / (n - 2)
        skewness *= adjust

    return round(skewness, 4)


def calc_volume_skewness_from_minute(minute_data: List[dict],
                                       vol_key: str = 'volume',
                                       normalize: bool = True) -> Optional[float]:
    """
    从分钟级数据计算量偏度。

    Args:
        minute_data: 分钟级数据列表，按时间升序
        vol_key: 成交量字段名
        normalize: 是否按日总成交量归一化（消除量级差异）

    Returns:
        偏度值
    """
    volumes = [float(r.get(vol_key, 0)) for r in minute_data]

    if normalize and sum(volumes) > 0:
        total = sum(volumes)
        volumes = [v / total for v in volumes]

    return calc_volume_skewness(volumes)


def classify_skewness(skewness: float) -> str:
    """
    分类量偏度状态。

    Args:
        skewness: 偏度值

    Returns:
        'early_concentrated' | 'slightly_early' | 'uniform' | 'slightly_late' | 'late_concentrated'
    """
    if skewness > 2.0:
        return 'late_concentrated'
    elif skewness > 0.5:
        return 'slightly_late'
    elif skewness < -2.0:
        return 'early_concentrated'
    elif skewness < -0.5:
        return 'slightly_early'
    else:
        return 'uniform'


def get_skewness_label_cn(label: str) -> str:
    """中文标签"""
    labels = {
        'early_concentrated': '早盘集中放量',
        'slightly_early': '早盘偏多',
        'uniform': '量能均匀',
        'slightly_late': '尾盘偏多',
        'late_concentrated': '尾盘集中放量',
    }
    return labels.get(label, label)
