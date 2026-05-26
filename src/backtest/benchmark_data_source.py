"""
墨枢 - BenchmarkProvider 接入 akshare 数据桥接模块

提供两个高阶注册函数，将 AkshareDataSource 获取的行情数据
注入 BenchmarkProvider，替代内置迷你数据集。

用法::

    from backtest.benchmark_data_source import register_stock_from_akshare, register_index_from_akshare
    from backtest.benchmark import BenchmarkProvider

    provider = BenchmarkProvider()

    # 注册个股
    idx = register_stock_from_akshare(provider, "601857", "中国石油",
                                       start_date="20250101", end_date="20250515")

    # 注册指数
    idx = register_index_from_akshare(provider, "csi300",
                                       start_date="20250101", end_date="20250515")
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from backtest.benchmark import BenchmarkProvider, BenchmarkIndex
from backtest.data_source import AkshareDataSource

# ── 指数代码映射 ──────────────────────────────────────────────

_INDEX_SYMBOL_MAP = {
    "csi300": "sh000300",
    "shanghai": "sh000001",
}

_INDEX_NAME_MAP = {
    "csi300": "沪深300",
    "shanghai": "上证指数",
}

_INDEX_CODE_MAP = {
    "csi300": "000300.SH",
    "shanghai": "000001.SH",
}

# ── 列名映射（akshare 中文 → 统一英文）───────────────────────

_COLUMN_MAP_INDEX = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}


# ═══════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════


def register_stock_from_akshare(
    provider: BenchmarkProvider,
    symbol: str,
    name: str,
    start_date: str,
    end_date: str,
    ds: Optional[AkshareDataSource] = None,
) -> BenchmarkIndex:
    """用 AkshareDataSource 获取股票行情并注册为基准。

    Args:
        provider: BenchmarkProvider 实例，调用其 register() 方法注册数据。
        symbol: 股票代码，如 "601857"（传给 AkshareDataSource.fetch_daily）。
        name: 注册的显示名称（用作 register() 的 key 和 name 参数）。
        start_date: 起始日期 "YYYYMMDD"。
        end_date: 结束日期 "YYYYMMDD"。
        ds: AkshareDataSource 实例。若未提供，自动创建默认实例。

    Returns:
        注册后的 BenchmarkIndex 对象。
    """
    if ds is None:
        ds = AkshareDataSource()

    df = ds.fetch_daily(symbol, start_date, end_date)

    if df is None or df.empty:
        raise ValueError(
            f"无法从 akshare 获取 {symbol} 的行情数据 "
            f"（{start_date} ~ {end_date}）"
        )

    # 提取 (date_str, close) 格式
    data = _extract_close_data(df)
    return provider.register(key=name, name=name, code=symbol, data=data)


def register_index_from_akshare(
    provider: BenchmarkProvider,
    index_name: str,
    start_date: str,
    end_date: str,
    ds: Optional[AkshareDataSource] = None,
) -> BenchmarkIndex:
    """用 akshare 获取指数行情（上证综指/沪深300）并注册为基准。

    支持的 index_name: "csi300", "shanghai"。
    对应 akshare 接口: stock_zh_index_daily(symbol="sh000300") 和 "sh000001"。
    列映射同 AkshareDataSource 格式（date/open/high/low/close/volume/amount）。

    Args:
        provider: BenchmarkProvider 实例。
        index_name: 指数名称，支持 "csi300" 或 "shanghai"。
        start_date: 起始日期 "YYYYMMDD"。
        end_date: 结束日期 "YYYYMMDD"。
        ds: 未使用，保留参数以保持接口一致性。

    Returns:
        注册后的 BenchmarkIndex 对象。

    Raises:
        ValueError: index_name 不支持或数据获取失败时抛出。
    """
    if index_name not in _INDEX_SYMBOL_MAP:
        raise ValueError(
            f"不支持的指数名称: {index_name!r}。"
            f"支持: {list(_INDEX_SYMBOL_MAP.keys())}"
        )

    akshare_symbol = _INDEX_SYMBOL_MAP[index_name]
    display_name = _INDEX_NAME_MAP[index_name]
    code = _INDEX_CODE_MAP[index_name]

    # 延迟导入 akshare
    import akshare as ak

    raw = ak.stock_zh_index_daily(symbol=akshare_symbol)
    if raw is None or raw.empty:
        raise ValueError(f"无法获取指数行情 {akshare_symbol}")

    # 列映射
    df = raw.rename(columns=_COLUMN_MAP_INDEX)
    df = df[[col for col in _COLUMN_MAP_INDEX.values() if col in df.columns]]

    # 日期列转换
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])

    # 按日期范围过滤
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

    if df.empty:
        raise ValueError(
            f"指数 {index_name}({akshare_symbol}) 在 "
            f"{start_date} ~ {end_date} 范围内无数据"
        )

    data = _extract_close_data(df)
    return provider.register(key=index_name, name=display_name, code=code, data=data)


# ═══════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════


def _extract_close_data(df: pd.DataFrame) -> list:
    """从 DataFrame 提取 (date_str, close) 列表。

    Args:
        df: 包含 date 和 close 列的 DataFrame。

    Returns:
        [(date_str, close_float), ...]，按日期升序排列。
    """
    # 确保 date 列存在
    if "date" not in df.columns:
        raise ValueError("DataFrame 缺少 'date' 列")
    if "close" not in df.columns:
        raise ValueError("DataFrame 缺少 'close' 列")

    result = sorted(
        (
            row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime")
            else str(row["date"]),
            float(row["close"]),
        )
        for _, row in df.iterrows()
    )
    return result


def _calc_kpis(df: pd.DataFrame, total_return: float, trading_days: int) -> dict:
    """计算买入持有策略的 KPI 指标。

    Args:
        df: 包含 'close' 列的 DataFrame，已按日期升序排列。
        total_return: 累计收益率（小数，如 0.1081）。
        trading_days: 交易日数。

    Returns:
        包含 annualized_return_pct / max_drawdown_pct / max_drawdown_duration
        / win_rate / calmar_ratio / trading_days 的字典。

    Raises:
        ValueError: trading_days 小于等于 0 时抛出。
    """
    if trading_days <= 0:
        raise ValueError("trading_days 必须大于 0")

    # 年化收益率（按持仓天数）: (1 + total_return) ^ (365 / trading_days) - 1
    annualized_return_pct = round(
        ((1 + total_return) ** (365 / trading_days) - 1) * 100, 2
    )

    # 最大回撤 & 持续天数（基于每日收盘价的滚动净值序列）
    closes = df["close"].values
    peak = closes[0]
    max_drawdown = 0.0
    max_drawdown_duration = 0
    current_drawdown_days = 0

    for close in closes:
        if close >= peak:
            peak = close
            current_drawdown_days = 0
        else:
            drawdown = (close - peak) / peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown
            current_drawdown_days += 1
            if current_drawdown_days > max_drawdown_duration:
                max_drawdown_duration = current_drawdown_days

    max_drawdown_pct = round(max_drawdown * 100, 2)

    # 日胜率：上涨交易日占全部交易日（不含首日）的比例
    price_changes = df["close"].diff()
    win_days = int((price_changes > 0).sum())
    valid_days = max(trading_days - 1, 1)
    win_rate = round(win_days / valid_days, 2)

    # Calmar 比率：年化收益 / 最大回撤绝对值
    if abs(max_drawdown_pct) > 1e-10:
        calmar_ratio = round(annualized_return_pct / abs(max_drawdown_pct), 2)
    else:
        calmar_ratio = 0.0

    return {
        "annualized_return_pct": annualized_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "max_drawdown_duration": max_drawdown_duration,
        "win_rate": win_rate,
        "calmar_ratio": calmar_ratio,
        "trading_days": trading_days,
    }


def calc_buy_hold_return(
    symbol: str,
    name: str,
    start_date: str,
    end_date: str,
    ds: Optional[AkshareDataSource] = None,
) -> dict:
    """计算买入持有收益率（前复权价格）。

    使用 AkshareDataSource.fetch_daily() 获取前复权日线数据。
    如果起/止日不是交易日，自动取最近一个交易日。
    数据不足 30 个交易日时抛出 ValueError。

    Args:
        symbol: 股票代码如 "601857"。
        name: 展示名称如 "中国石油"。
        start_date: 起始日期 "YYYYMMDD"。
        end_date: 结束日期 "YYYYMMDD"。
        ds: 可选数据源实例（不传则新建）。

    Returns:
        包含起止价格和收益率的字典。

    Raises:
        ValueError: 数据为空或不足 30 个交易日时抛出。
    """
    if ds is None:
        ds = AkshareDataSource()

    # 获取前复权数据（adjust="qfq" 为 AkshareDataSource.fetch_daily 的默认值）
    df = ds.fetch_daily(symbol, start_date, end_date, adjust="qfq")

    if df is None or df.empty:
        raise ValueError(
            f"无法获取 {symbol} 的行情数据（{start_date} ~ {end_date}）"
        )

    # 验证至少 30 个交易日
    if len(df) < 30:
        raise ValueError(
            f"{symbol} 在 {start_date} ~ {end_date} 范围内"
            f"仅 {len(df)} 个交易日，不足 30 个"
        )

    # 按日期升序排列
    df = df.sort_values("date").reset_index(drop=True)

    # 取实际起止日期（自动对齐最近交易日）
    start_row = df.iloc[0]
    end_row = df.iloc[-1]
    actual_start_date = (
        start_row["date"].strftime("%Y-%m-%d")
        if hasattr(start_row["date"], "strftime")
        else str(start_row["date"])
    )
    actual_end_date = (
        end_row["date"].strftime("%Y-%m-%d")
        if hasattr(end_row["date"], "strftime")
        else str(end_row["date"])
    )

    start_close = float(start_row["close"])
    end_close = float(end_row["close"])

    # 累计收益率 = (end_close - start_close) / start_close
    total_return = (end_close - start_close) / start_close if start_close != 0 else 0.0
    total_return_pct = round(total_return * 100, 2)
    total_return = round(total_return, 4)

    trading_days = len(df)
    kpis = _calc_kpis(df, total_return, trading_days)

    return {
        "symbol": symbol,
        "name": name,
        "start_date": actual_start_date,
        "end_date": actual_end_date,
        "start_close": start_close,
        "end_close": end_close,
        "total_return_pct": total_return_pct,
        "total_return": total_return,
        **kpis,
    }
