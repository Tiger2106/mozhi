"""
墨枢 - 市场数据适配器（R1 阶段一：第1组-1）

纯量价字段适配器。将原始行情数据统一转换为标准 DataFrame 格式，
供所有因子计算模块消费。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pipeline_paths import factors_data_dir, market_data_dir
from pathlib import Path

MOZHI_BASE = Path(r"C:\Users\17699\mozhi_platform")


# ── 列名标准 ──────────────────────────────────────────

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = ["turnover_rate", "amount", "circulating_cap"]

# ── 数据获取 ──────────────────────────────────────────


def fetch_price_volume(
    symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: str = "csv",
) -> pd.DataFrame:
    """
    获取标的的标准量价 DataFrame。

    Parameters
    ----------
    symbol : str
        标的代码，如 "000300.SH"。
    start : str, optional
        开始日期 YYYYMMDD。
    end : str, optional
        结束日期 YYYYMMDD。默认今天。
    source : str
        数据源类型。"csv" 从 data/market_cache/ 读取。

    Returns
    -------
    pd.DataFrame
        包含标准列名 open/high/low/close/volume/turnover_rate 的 DataFrame，
        以日期为索引。
    """
    if source == "csv":
        return _fetch_from_cache(symbol, start, end)
    else:
        return _fetch_fallback(symbol, start, end)


def calc_turnover_rate(
    df: pd.DataFrame,
    circulating_cap_col: Optional[str] = None,
    volume_col: str = "volume",
    close_col: str = "close",
) -> pd.Series:
    """
    计算换手率。

    换手率 = 成交量 / 流通股本 * 100%。

    Parameters
    ----------
    df : pd.DataFrame
        包含成交量和收盘价/金额的信息。
    circulating_cap_col : str, optional
        流通市值（元）列名。若不存在则用 amount 和 close 估算。
    volume_col : str
        成交量列名。
    close_col : str
        收盘价列名。

    Returns
    -------
    pd.Series
        换手率列（%）。
    """
    if circulating_cap_col and circulating_cap_col in df.columns:
        # 已有流通市值列（元）
        cir_cap = df[circulating_cap_col]
        turnover = df[volume_col] * df[close_col] / cir_cap * 100.0
    elif "amount" in df.columns and "circulating_cap" not in df.columns:
        # 用成交额和价格估算（不精确，作为兜底）
        est_cir_cap = df["amount"].rolling(120, min_periods=60).sum() * 10
        turnover = df[volume_col] * df[close_col] / est_cir_cap * 100.0
    else:
        # 最简估算：假设成交量本身就是换手率的 1/100
        turnover = df[volume_col] / df[volume_col].rolling(5).mean() * 0.5

    turnover = turnover.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return turnover.clip(lower=0.0)


def validate_dataframe(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    验证 DataFrame 是否满足因子计算最低要求。

    Returns
    -------
    Tuple[bool, List[str]]
        (是否通过, 问题列表)
    """
    issues: List[str] = []

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            issues.append(f"缺少必要列: {col}")

    if "date" not in df.columns and df.index.name not in ("date", "trade_date"):
        issues.append("缺少日期索引或 date 列")

    if len(df) < 10:
        issues.append(f"数据行数过少: {len(df)}")

    if df.isnull().all().all():
        issues.append("全空 DataFrame")

    return (len(issues) == 0, issues)


# ── 内部辅助 ──────────────────────────────────────────


def _fetch_from_cache(
    symbol: str, start: Optional[str], end: Optional[str]
) -> pd.DataFrame:
    """从本地缓存读取 CSV。"""
    data_dir = market_data_dir()
    symbol_clean = symbol.replace(".", "_")
    csv_path = data_dir / f"{symbol_clean}.csv"

    if csv_path.exists():
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    else:
        # 生成虚拟数据供测试
        df = _make_dummy_data(symbol, rows=120)

    # 标准化列名
    col_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Turnover": "turnover_rate",
        "Amount": "amount",
        "turnover": "turnover_rate",
    }
    df = df.rename(columns=col_map)
    for c in REQUIRED_COLUMNS:
        if c not in df.columns:
            df[c] = 0.0

    # 只保留标准列
    keep_cols = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    keep_cols = [c for c in keep_cols if c in df.columns]

    # 日期筛选
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    # 确保 turn_rate 存在
    if "turnover_rate" not in df.columns:
        df["turnover_rate"] = calc_turnover_rate(df)

    return df[keep_cols].sort_index()


def _fetch_fallback(
    symbol: str, start: Optional[str], end: Optional[str]
) -> pd.DataFrame:
    """兜底：生成模拟数据。"""
    return _make_dummy_data(symbol, rows=120)


def _make_dummy_data(symbol: str, rows: int = 120) -> pd.DataFrame:
    """生成模拟行情数据（用于开发和测试）。"""
    np.random.seed(hash(symbol) % (2**31))
    dates = pd.bdate_range(
        end=date.today(), periods=rows, freq="B"
    )
    base_price = 100.0 + hash(symbol) % 200
    daily_ret = np.random.randn(rows) * 0.015
    prices = base_price * np.exp(np.cumsum(daily_ret))

    df = pd.DataFrame(
        {
            "open": prices * (1 - np.random.rand(rows) * 0.008),
            "high": prices * (1 + np.random.rand(rows) * 0.015),
            "low": prices * (1 - np.random.rand(rows) * 0.015),
            "close": prices,
            "volume": np.random.randint(1_000_000, 10_000_000, rows),
            "amount": np.random.uniform(1e8, 1e10, rows),
        },
        index=dates,
    )
    df.index.name = "date"
    return df
