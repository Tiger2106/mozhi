"""
墨枢 - AkshareDataSource
A股历史行情数据源，封装 akshare 接口。

用法::

    from .data_source import AkshareDataSource, get_backtest_results, get_stock_prices

    ds = AkshareDataSource()
    df = ds.fetch_daily("601857", "20250101", "20250515")

    # DAO 层方法（操作 analysis.db）
    results = get_backtest_results(code="601857", start_date="20260101", end_date="20260514")
    prices  = get_stock_prices(code="601857", start_date="20260101", end_date="20260514")
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# ── 网络环境适配 ──────────────────────────────────────────────
# NO_PROXY bypass：企业网络环境无法直连部分 API
os.environ.setdefault("NO_PROXY", "*")

# ── 新浪日线 fallback ───────────────────────────────────────
# symbol 前缀映射：纯代码 → akshare 新浪接口所需格式
_SINA_PREFIX = {"0": "sz", "3": "sz", "6": "sh", "4": "bj", "8": "bj"}


def _to_sina_symbol(symbol: str) -> str:
    """601857.SH -> sh601857, 000001.SZ -> sz000001"""
    code = symbol.split(".")[0]
    prefix = _SINA_PREFIX.get(code[0], "sz")
    return f"{prefix}{code}"


# 新浪日线返回的列名（英文）
_SINA_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


class AkshareDataSource:
    """A股历史行情数据源，封装 akshare 接口"""

    def __init__(
        self,
        max_retries: int = 1,
        retry_delay: float = 1.0,
        cache_dir: Optional[str] = None,
        cache_ttl_hours: float = 24.0,
    ):
        """
        Args:
            max_retries: 网络异常时最大重试次数（默认1次）
            retry_delay: 重试间隔秒数（默认1秒）
            cache_dir: 缓存目录路径，默认自动计算到项目根目录下的 backtest_data_cache
            cache_ttl_hours: 缓存过期时间（小时），默认24小时
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cache_ttl_hours = cache_ttl_hours

        if cache_dir is not None:
            self._cache_dir = Path(cache_dir)
        else:
            # 从当前文件路径推算项目根目录:
            #   data_source.py → backtest → src → mozhi_platform/
            script_dir = Path(__file__).resolve().parent  # src/backtest/
            project_root = script_dir.parent.parent  # mozhi_platform/
            self._cache_dir = project_root / "backtest_data_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # 检测是否可用 parquet 引擎
        self._parquet_ok = self._check_parquet()

    @staticmethod
    def _check_parquet() -> bool:
        """检查当前环境是否可用 parquet 格式"""
        try:
            pd.DataFrame().to_parquet()
            return True
        except ImportError:
            return False

    def _cache_filename(self, symbol: str, start_date: str, end_date: str, adjust: str) -> str:
        """生成缓存文件名，对 symbol 做防注入处理"""
        safe_symbol = symbol.replace(".", "_").replace("/", "_").replace("\\", "_")
        return f"{safe_symbol}_{start_date}_{end_date}_{adjust}.parquet"

    def _cache_path(self, symbol: str, start_date: str, end_date: str, adjust: str) -> Path:
        return self._cache_dir / self._cache_filename(symbol, start_date, end_date, adjust)

    def _cache_valid(self, cache_path: Path) -> bool:
        """检查缓存文件是否存在且未过期"""
        if not cache_path.exists():
            return False
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - mtime) < timedelta(hours=self.cache_ttl_hours)

    def _read_cache(self, cache_path: Path) -> Optional[pd.DataFrame]:
        """从缓存读取 DataFrame"""
        try:
            return pd.read_parquet(cache_path)
        except ImportError:
            # 无 parquet 引擎，回退到 pickle
            return pd.read_pickle(cache_path)
        except Exception:
            return None

    def _write_cache(self, df: pd.DataFrame, cache_path: Path) -> None:
        """将 DataFrame 写入缓存（原子写入 + 自动创建目录）"""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".tmp")
        try:
            df.to_parquet(tmp_path)
        except ImportError:
            df.to_pickle(tmp_path)
        # 原子替换
        os.replace(str(tmp_path), str(cache_path))

    def fetch_daily(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """获取日线数据（带本地缓存）

        Args:
            symbol: 股票代码, 如 "601857"
            start_date: 起始日期 "YYYYMMDD"
            end_date: 结束日期 "YYYYMMDD"
            adjust: 复权类型, "qfq"=前复权, "hfq"=后复权, ""=不复权

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount

        Raises:
            ConnectionError: 网络异常且重试耗尽后抛出
            ValueError: 参数校验失败时抛出
        """
        # 参数校验
        if not symbol or not symbol.strip():
            raise ValueError("symbol 不能为空")
        if not start_date or len(start_date) != 8 or not start_date.isdigit():
            raise ValueError(f"start_date 格式异常: {start_date}")
        if not end_date or len(end_date) != 8 or not end_date.isdigit():
            raise ValueError(f"end_date 格式异常: {end_date}")

        # ---- 缓存快路径 ----
        cache_path = self._cache_path(symbol, start_date, end_date, adjust)
        if self._cache_valid(cache_path):
            cached = self._read_cache(cache_path)
            if cached is not None and not cached.empty:
                return cached

        # ---- 列名映射：akshare 中文列名 → 统一英文列名 ----
        column_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }

        # ---- 带重试的请求 + 新浪 fallback ----
        last_exc = None
        used_sina = False
        for attempt in range(self.max_retries + 1):
            try:
                # 延迟导入 akshare，避免冷启动加载耗时
                import akshare as ak

                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
            except Exception as e:
                last_exc = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                    continue
                # 东方财富重试耗尽 → 新浪 fallback（一次，不重复重试）
                try:
                    import akshare as ak

                    sina_symbol = _to_sina_symbol(symbol)
                    df = ak.stock_zh_a_daily(
                        symbol=sina_symbol,
                        start_date=start_date,
                        end_date=end_date,
                        adjust=adjust,
                    )
                    used_sina = True
                except Exception as e2:
                    raise ConnectionError(
                        f"获取 {symbol} 日线数据失败（东财+新浪均失败）: {e2}"
                    ) from e2
            break

        # ---- 空结果处理 ----
        if df is None or df.empty:
            expected_cols = (
                _SINA_COLUMNS if used_sina else list(column_map.values())
            )
            return pd.DataFrame(columns=expected_cols)

        # ---- 列名统一 ----
        if used_sina:
            # 新浪接口返回英文列名，直接筛选
            df = df[[col for col in _SINA_COLUMNS if col in df.columns]]
        else:
            # 东方财富接口返回中文列名，统一映射
            df = df.rename(columns=column_map)
            df = df[[col for col in column_map.values() if col in df.columns]]

        # ---- 日期列转为 datetime ----
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # ---- 写入缓存 ----
        self._write_cache(df, cache_path)

        return df


# ═══════════════════════════════════════════════════════════════
# DAO 层方法 — 操作 analysis.db（不绕过，提供统一查询入口）
# ═══════════════════════════════════════════════════════════════


def _get_analysis_db() -> Path:
    """获取 analysis.db 路径（用于 backtest_results 等非行情数据）"""
    from src.config import ANALYSIS_DB
    return ANALYSIS_DB


def _get_market_data_db() -> Path:
    """获取 market_data.db 路径（用于 stock_daily 行情数据）"""
    from src.config import MARKET_DATA_DB
    return MARKET_DATA_DB


def get_backtest_results(
    code: str,
    start_date: str,
    end_date: str,
) -> List[Dict[str, Any]]:
    """从 analysis.db 的 backtest_results 表读取回测记录。

    Args:
        code: 股票代码，如 "601857"
        start_date: 起始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD

    Returns:
        回测记录列表，每条包含 id, strategy_name, start_date, end_date,
        total_return, sharpe_ratio, total_trades, parameters 等字段
    """
    db_path = _get_analysis_db()
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 优先按 code 字段查询（P6 迁移后存在）
        cur = conn.execute(
            """
            SELECT * FROM backtest_results
            WHERE (code = ? OR strategy_name LIKE ?)
              AND start_date >= ?
              AND end_date <= ?
            ORDER BY created_at DESC
            """,
            (code, f"%{code}%", start_date, end_date),
        )
        rows = [dict(r) for r in cur.fetchall()]

        # 无结果且 strategy_name LIKE 含 code 时降级为全量
        if not rows:
            cur = conn.execute(
                """
                SELECT * FROM backtest_results
                WHERE start_date >= ? AND end_date <= ?
                ORDER BY created_at DESC
                """,
                (start_date, end_date),
            )
            rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()


def get_stock_prices(
    code: str,
    start_date: str,
    end_date: str,
) -> List[float]:
    """从 market_data.db 的 stock_daily 表读取指定标的的收盘价序列。

    Args:
        code: 股票代码，如 "601857"
        start_date: 起始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD

    Returns:
        收盘价列表，按日期升序排列
    """
    db_path = _get_market_data_db()
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """
            SELECT close FROM stock_daily
            WHERE code = ? AND date >= ? AND date <= ?
            ORDER BY date ASC
            """,
            (code, start_date, end_date),
        )
        return [float(r[0]) for r in cur.fetchall() if r[0] is not None]
    finally:
        conn.close()
