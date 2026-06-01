"""
DataBridge — 统一数据入口模块

为共振系统提供 A50 / 上证 ETF 等标的的 OHLCV 行情数据获取。
实现本地 CSV 缓存策略，避免重复 API 调用。

主接口:
    fetch_ohlcv(ticker, start_date, end_date, force_refresh=False)
        → pd.DataFrame(columns=[date, open, high, low, close, volume])

数据源（按优先级）:
  1. CSV 缓存（data/bridge_cache/）
  2. akshare stock_zh_a_hist（个股）
  3. akshare stock_zh_index_daily（指数）

依赖:
    - akshare（行情数据源）
    - pandas（数据处理与返回格式）
    - src.resonance.constants（配置常量）

Author: moheng
Created: 2026-05-29T09:57:00+08:00
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

from src.resonance.constants import MIN_REQUIRED_HISTORY_DAYS

logger = logging.getLogger("resonance.data_bridge")


# ══════════════════════════════════════════════════════════
# 项目根路径解析（与 lookback_buffer.py 一致）
# ══════════════════════════════════════════════════════════


def _resolve_project_root() -> Path:
    """从模块位置向上查找项目根目录。

    Search strategy:
        1. 从 __file__ 所在目录 src/resonance/ 向上查找
        2. 找到包含 .git 目录的 src/ 父目录
        3. 回退：src/resonance/ 上两级即为项目根

    Returns:
        项目根目录的绝对路径。
    """
    module_dir = Path(__file__).resolve().parent  # src/resonance/
    for parent in [module_dir, *module_dir.parents]:
        if parent.name == "src" and (parent.parent / ".git").is_dir():
            return parent.parent
    return module_dir.parent.parent  # fallback: <project_root>/


_PROJECT_ROOT = _resolve_project_root()

# ══════════════════════════════════════════════════════════
# 路径与常量
# ══════════════════════════════════════════════════════════

CACHE_DIR = _PROJECT_ROOT / "data" / "bridge_cache"
"""CSV 缓存目录。缓存文件以 {safe_ticker}_{start_date}_{end_date}.csv 命名。"""

MAX_RETRIES: int = 2
"""网络请求最大重试次数。"""

RETRY_DELAY_SECONDS: float = 1.0
"""重试间隔秒数。"""

COLUMN_MAP_STOCK: dict = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
}
"""东方财富 akshare stock_zh_a_hist 中文列名 → 标准英文列名映射。"""

REQUIRED_COLUMNS: List[str] = ["open", "high", "low", "close", "volume"]
"""返回 DataFrame 必须包含的 OHLCV 列。"""

STOCK_SUFFIXES: tuple = (".SH", ".SZ", ".BJ")
"""A 股个股后缀集合。指数代码通常为 6 位纯数字后缀 .SH（如 000300.SH）。"""


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════


def _is_index_ticker(ticker: str) -> bool:
    """判断 ticker 是否为指数代码。

    A 股指数代码特征：6 位纯数字，不以 6/0(深市)/3 开头，
    但 000/001/399 开头的典型指数代码。

    简单规则：
      - 代码以 "0" 或 "1" 或 "8" 开头 → 指数
      - 否则 → 个股

    Args:
        ticker: 标的代码，如 "601857.SH" 或 "000300.SH"。

    Returns:
        True 如果 ticker 是指数代码。
    """
    code = ticker.split(".")[0]
    return code.startswith("0") or code.startswith("1") or code.startswith("8")


def _safe_ticker(ticker: str) -> str:
    """将 ticker 转换为安全的文件名片段。

    替换 . / \\ 等特殊字符，防止路径穿越攻击。

    Args:
        ticker: 原始标的代码。

    Returns:
        安全的文件名片段。
    """
    return ticker.replace(".", "_").replace("/", "_").replace("\\", "_")


def _cache_path(ticker: str, start_date: str, end_date: str) -> Path:
    """计算缓存文件路径。

    Args:
        ticker: 标的代码。
        start_date: 起始日期 YYYYMMDD。
        end_date: 结束日期 YYYYMMDD。

    Returns:
        缓存文件的 Path 对象。
    """
    safe = _safe_ticker(ticker)
    return CACHE_DIR / f"{safe}_{start_date}_{end_date}.csv"


# ══════════════════════════════════════════════════════════
# 缓存操作
# ══════════════════════════════════════════════════════════


def _ensure_cache_dir() -> None:
    """确保缓存目录存在。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _read_cache(cache_file: Path) -> Optional[pd.DataFrame]:
    """从 CSV 缓存文件读取数据。

    自动解析 date 列为 datetime 类型。

    Args:
        cache_file: 缓存文件路径。

    Returns:
        如果缓存存在且有效，返回 DataFrame；否则返回 None。
    """
    if not cache_file.exists():
        return None
    try:
        df = pd.read_csv(cache_file, parse_dates=["date"])
        if df.empty:
            return None
        # 确保标准列存在
        required = ["date"] + REQUIRED_COLUMNS
        for col in required:
            if col not in df.columns:
                return None
        return df
    except Exception as exc:
        logger.warning("读取缓存失败 %s: %s", cache_file, exc)
        return None


def _write_cache(df: pd.DataFrame, cache_file: Path) -> None:
    """原子写入 CSV 缓存文件。

    使用临时文件 + os.replace 确保写入原子性，
    避免其他进程读取到不完整文件。

    Args:
        df: 要缓存的数据。
        cache_file: 目标缓存文件路径。
    """
    _ensure_cache_dir()
    tmp_path = cache_file.with_suffix(".tmp")
    try:
        df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        os.replace(str(tmp_path), str(cache_file))
    except Exception as exc:
        logger.warning("写入缓存失败 %s: %s", cache_file, exc)
        # 清理可能残留的临时文件
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════
# 数据获取（akshare 封装）
# ══════════════════════════════════════════════════════════


def _fetch_from_akshare_stock(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """使用 akshare stock_zh_a_hist 接口获取个股日线数据。

    自动重试 MAX_RETRIES 次，列名从中文映射为标准英文。

    Args:
        ticker: 个股代码，如 "601857.SH"。
        start_date: 起始日期 YYYYMMDD。
        end_date: 结束日期 YYYYMMDD。

    Returns:
        标准列名的 OHLCV DataFrame（日期升序）。

    Raises:
        ConnectionError: 重试耗尽后仍无法获取数据。
    """
    symbol = ticker.split(".")[0]

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            import akshare as ak  # noqa: PLC0415

            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df = df.rename(columns=COLUMN_MAP_STOCK)
                available = [c for c in COLUMN_MAP_STOCK.values() if c in df.columns]
                df = df[available]
                df["date"] = pd.to_datetime(df["date"])
                return df.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            logger.warning(
                "stock_zh_a_hist 第 %d 次尝试失败 [%s]: %s",
                attempt, ticker, exc,
            )
            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                raise ConnectionError(
                    f"获取 {ticker} 日线数据失败（重试 {MAX_RETRIES} 次后）: {exc}"
                ) from exc

    return pd.DataFrame(columns=["date"] + REQUIRED_COLUMNS)


def _fetch_from_akshare_index(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """使用 akshare stock_zh_index_daily 接口获取指数日线数据。

    指数成交量单位为"手"。返回的数据会自动按日期范围过滤。

    Args:
        ticker: 指数代码，如 "000300.SH"。
        start_date: 起始日期 YYYYMMDD。
        end_date: 结束日期 YYYYMMDD。

    Returns:
        标准列名的 OHLCV DataFrame（日期升序）。

    Raises:
        ConnectionError: 重试耗尽后仍无法获取数据。
    """
    symbol = ticker.split(".")[0]
    akshare_symbol = f"sh{symbol}" if ticker.endswith(".SH") else f"sz{symbol}"

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            import akshare as ak  # noqa: PLC0415

            df = ak.stock_zh_index_daily(symbol=akshare_symbol)
            if df is not None and not df.empty:
                # stock_zh_index_daily 返回列名: date, open, high, low, close, volume
                df["date"] = pd.to_datetime(df["date"])
                mask = (df["date"] >= pd.Timestamp(start_date)) & (
                    df["date"] <= pd.Timestamp(end_date)
                )
                df = df[mask].copy()
                # 确保标准列存在
                for col in REQUIRED_COLUMNS:
                    if col not in df.columns:
                        df[col] = 0.0
                available = ["date"] + [c for c in REQUIRED_COLUMNS if c in df.columns]
                return df[available].sort_values("date").reset_index(drop=True)
        except Exception as exc:
            logger.warning(
                "stock_zh_index_daily 第 %d 次尝试失败 [%s]: %s",
                attempt, ticker, exc,
            )
            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                raise ConnectionError(
                    f"获取指数 {ticker} 日线数据失败（重试 {MAX_RETRIES} 次后）: {exc}"
                ) from exc

    return pd.DataFrame(columns=["date"] + REQUIRED_COLUMNS)


# ══════════════════════════════════════════════════════════
# 数据校验
# ══════════════════════════════════════════════════════════


class DataInsufficientError(ValueError):
    """数据量不足以支持共振系统运行。

    当获取的 OHLCV 数据行数少于 MIN_REQUIRED_HISTORY_DAYS 时抛出。
    """

    def __init__(  # noqa: D107
        self,
        ticker: str,
        actual_days: int,
        required_days: int = MIN_REQUIRED_HISTORY_DAYS,
    ) -> None:
        self.ticker = ticker
        self.actual_days = actual_days
        self.required_days = required_days
        super().__init__(
            f"{ticker}: 实际 {actual_days} 日 < 要求 {required_days} 日 ("
            f"MIN_REQUIRED_HISTORY_DAYS={required_days})"
        )


def _validate_data(df: pd.DataFrame, ticker: str) -> None:
    """校验 OHLCV 数据是否满足共振系统最低要求。

    校验项:
        1. DataFrame 不为空
        2. 行数 >= MIN_REQUIRED_HISTORY_DAYS (40)
        3. 必需列 (open/high/low/close/volume) 均存在
        4. 非全空值列（仅警告）

    Args:
        df: 待校验的 OHLCV DataFrame。
        ticker: 标的代码（用于错误信息）。

    Raises:
        DataInsufficientError: 数据量不足。
        ValueError: 缺少必需列。
    """
    if df.empty:
        raise DataInsufficientError(ticker, 0)

    if len(df) < MIN_REQUIRED_HISTORY_DAYS:
        raise DataInsufficientError(ticker, len(df))

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: 缺少必需列 {missing}")

    # 全空值列警告（不阻断）
    for col in REQUIRED_COLUMNS:
        if df[col].isna().all():
            logger.warning("%s: 列 '%s' 全为空值", ticker, col)


# ══════════════════════════════════════════════════════════
# 主接口：fetch_ohlcv
# ══════════════════════════════════════════════════════════


def fetch_ohlcv(
    ticker: str,
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """统一数据入口：获取指定标的的 OHLCV 日线数据。

    优先从本地 CSV 缓存读取；缓存缺失或 ``force_refresh=True``
    时通过 akshare 实时拉取，拉取成功后自动写入缓存。

    Args:
        ticker: 标的代码。
            - 个股格式: ``"601857.SH"``, ``"600519.SH"``
            - 指数格式: ``"000300.SH"``, ``"000016.SH"``
        start_date: 起始日期，YYYYMMDD 格式。
            例如 ``"20250501"`` 表示 2025-05-01。
        end_date: 结束日期，YYYYMMDD 格式。
            例如 ``"20260528"`` 表示 2026-05-28。
        force_refresh: 是否强制刷新缓存。
            - ``True`` —  忽略缓存，重新拉取并更新缓存
            - ``False`` — 优先使用已存在的缓存（默认）

    Returns:
        :class:`pd.DataFrame`:
            - 行: 交易日，按日期升序排列
            - 列: ``date``, ``open``, ``high``, ``low``, ``close``, ``volume``
            - ``date`` 列为 :class:`pd.Timestamp` 类型

    Raises:
        ValueError: 参数格式校验失败。
        DataInsufficientError: 数据量少于 ``MIN_REQUIRED_HISTORY_DAYS`` (40)。
        ConnectionError: 网络错误且所有重试均已耗尽。

    Example:
        >>> df = fetch_ohlcv("601857.SH", "20250501", "20260528")
        >>> df.columns.tolist()
        ['date', 'open', 'high', 'low', 'close', 'volume']
        >>> len(df) >= 40
        True
    """
    # ── 参数校验 ────────────────
    if not ticker or not ticker.strip():
        raise ValueError("ticker 不能为空")
    if not start_date or len(start_date) != 8 or not start_date.isdigit():
        raise ValueError(f"start_date 格式异常: {start_date} (期望 YYYYMMDD)")
    if not end_date or len(end_date) != 8 or not end_date.isdigit():
        raise ValueError(f"end_date 格式异常: {end_date} (期望 YYYYMMDD)")
    if start_date > end_date:
        raise ValueError(
            f"start_date ({start_date}) 晚于 end_date ({end_date})"
        )

    # ── 缓存快路径 ──────────────
    cache_file = _cache_path(ticker, start_date, end_date)
    if not force_refresh:
        cached = _read_cache(cache_file)
        if cached is not None:
            logger.info("缓存命中: %s [%s ~ %s]", ticker, start_date, end_date)
            return cached

    # ── 实时拉取 ────────────────
    logger.info(
        "拉取实时数据: %s [%s ~ %s] (force_refresh=%s)",
        ticker, start_date, end_date, force_refresh,
    )

    if _is_index_ticker(ticker):
        df = _fetch_from_akshare_index(ticker, start_date, end_date)
    else:
        df = _fetch_from_akshare_stock(ticker, start_date, end_date)

    # 空结果 → 返回空 DataFrame（避免校验阻断）
    if df.empty:
        logger.warning("%s: 返回空 DataFrame [%s ~ %s]", ticker, start_date, end_date)
        return pd.DataFrame(columns=["date"] + REQUIRED_COLUMNS)

    # ── 数据量校验 ──────────────
    _validate_data(df, ticker)

    # ── 异步写入缓存（失败不影响数据返回） ──
    try:
        _write_cache(df, cache_file)
    except Exception as exc:
        logger.warning("缓存写入失败（不影响返回数据）: %s", exc)

    return df


# ══════════════════════════════════════════════════════════
# 辅助接口
# ══════════════════════════════════════════════════════════


def clear_cache(ticker: Optional[str] = None) -> int:
    """清除 DataBridge CSV 缓存。

    Args:
        ticker: 可选，指定清除某个标的的缓存。
            为 ``None`` 时清空全部缓存。

    Returns:
        被清除的文件数量。
    """
    if not CACHE_DIR.exists():
        return 0

    removed = 0
    if ticker is not None:
        prefix = _safe_ticker(ticker)
        for f in CACHE_DIR.iterdir():
            if f.suffix == ".csv" and f.stem.startswith(prefix):
                f.unlink(missing_ok=True)
                removed += 1
    else:
        for f in CACHE_DIR.iterdir():
            if f.suffix == ".csv":
                f.unlink(missing_ok=True)
                removed += 1
    logger.info("清除缓存 %d 个文件 (ticker=%s)", removed, ticker or "ALL")
    return removed


def list_cached_tickers() -> List[str]:
    """列出缓存中已有的标的代码。

    遍历 ``data/bridge_cache/`` 目录，从文件名中提取 ticker。

    Returns:
        有缓存数据的标的代码列表（去重、排序）。
    """
    if not CACHE_DIR.exists():
        return []
    tickers: set = set()
    for f in CACHE_DIR.iterdir():
        if f.suffix == ".csv":
            parts = f.stem.split("_")
            if len(parts) >= 3:  # safe_ticker_start_end.csv
                raw = parts[0] + "." + parts[1]
                tickers.add(raw)
    return sorted(tickers)
