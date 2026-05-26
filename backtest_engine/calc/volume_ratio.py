# volume_ratio.py
# 墨家投资室 - 量比（Volume Ratio）计算模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 公式：volume_ratio(t) = vol(t) / MA(vol, N)
#   - vol(t)：当日成交量（股）
#   - MA(vol, N)：过去 N 日均量
#   - N 默认值：20（月均） / 60（季均）
#
# 使用方式：
#   from calc.volume_ratio import calc_volume_ratio
#   vr = calc_volume_ratio(current_vol=95413273, ma20_vol=80000000)

from typing import Optional, Union, List, Dict
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def calc_volume_ratio(
    current_vol: float,
    ma_vol: float,
) -> float:
    """
    计算单日量比。

    Args:
        current_vol: 当日成交量（股）
        ma_vol: N 日均量（股）

    Returns:
        量比值。预期范围：
          - volume_ratio > 1.5 → 放量显著
          - volume_ratio [0.8, 1.5] → 量能正常
          - volume_ratio < 0.5 → 缩量显著
          - volume_ratio = 0 → 无成交

    Raises:
        ValueError: 输入参数无效时抛出
    """
    _validate_inputs(current_vol, ma_vol)

    if ma_vol == 0:
        return 0.0

    return current_vol / ma_vol


def calc_volume_ratio_multi_ma(
    current_vol: float,
    ma_values: Dict[str, float],
) -> Dict[str, float]:
    """
    计算多个 N 值的量比。

    Args:
        current_vol: 当日成交量（股）
        ma_values: {窗口名称: 均量}，如 {'ma20': 80000000, 'ma60': 75000000}

    Returns:
        {窗口名称: 量比值} 字典
    """
    result = {}
    for win_name, ma_vol in ma_values.items():
        try:
            result[win_name] = calc_volume_ratio(current_vol, ma_vol)
        except ValueError as e:
            logger.warning("MA window %s: %s", win_name, e)
            result[win_name] = None
    return result


def calc_ma_volume(
    volumes: List[float],
    window: int = 20,
    min_periods: int = None,
) -> Optional[float]:
    """
    计算 N 日均量（Simple Moving Average）。

    Args:
        volumes: 成交量列表（按日期正序），最新数据在最后
        window: 移动窗口大小
        min_periods: 最少有效周期，默认 window

    Returns:
        均量值，若有效数据不足则返回 None
    """
    min_periods = min_periods or window

    if len(volumes) < min_periods:
        return None

    recent = volumes[-window:]
    valid = [v for v in recent if v is not None and v > 0]
    if len(valid) < min_periods:
        return None

    return sum(valid) / len(valid)


# ── 数据校验 ──────────────────────────────────────────────


def _validate_inputs(current_vol: float, ma_vol: float):
    """输入有效性检查"""
    if current_vol is None or ma_vol is None:
        raise ValueError("current_vol 和 ma_vol 均不能为 None")
    if current_vol < 0:
        raise ValueError(f"current_vol 不能为负数: {current_vol}")
    if ma_vol < 0:
        raise ValueError(f"ma_vol 不能为负数: {ma_vol}")


# ── 快速函数：从数据库读数据计算 ──────────────────────────


def calc_volume_ratio_from_db(symbol: str, date: str, window: int = 20, db_path: str = None):
    """
    从 data_source 统一接口读取数据计算 volume_ratio。

    Args:
        symbol: 股票代码
        date: 目标日期 'YYYYMMDD'
        window: 均量周期
        db_path: 兼容旧参数，已不再使用

    Returns:
        {'volume_ratio': float, 'ma_vol': float, 'current_vol': float} 或 None
    """
    from datetime import datetime, timedelta
    from src.backtest.data_source import AkshareDataSource

    ds = AkshareDataSource()

    # 向前推算起始日期
    dt = datetime.strptime(date, '%Y%m%d')
    start_dt = dt - timedelta(days=window * 2 + 10)
    start_date = start_dt.strftime('%Y%m%d')

    df = ds.fetch_daily(symbol=symbol, start_date=start_date, end_date=date, adjust="qfq")
    if df is None or df.empty:
        logger.warning("No data for %s around %s", symbol, date)
        return None

    # 按日期升序排列
    df = df.sort_values('date', ascending=True)

    # 找到目标日期
    target_idx = None
    for i, row in df.iterrows():
        d = row['date']
        if hasattr(d, 'strftime'):
            d = d.strftime('%Y%m%d')
        if str(d) == date:
            target_idx = i
            break

    if target_idx is None:
        logger.warning("No data for %s on %s", symbol, date)
        return None

    current_vol = float(df.loc[target_idx, 'volume'])
    if current_vol <= 0:
        logger.warning("Zero volume for %s on %s", symbol, date)
        return None

    # 前 N 天的成交量（不含目标日期本身）
    before = df.loc[:target_idx].iloc[:-1]
    volumes = [float(v) for v in before['volume'].tail(window) if v and v > 0]

    ma_vol = calc_ma_volume(volumes, window=window)
    if ma_vol is None:
        logger.warning("Insufficient volume data for %s before %s", symbol, date)
        return None

    vr = calc_volume_ratio(current_vol, ma_vol)
    return {
        'volume_ratio': vr,
        'ma_vol': ma_vol,
        'current_vol': current_vol,
    }
