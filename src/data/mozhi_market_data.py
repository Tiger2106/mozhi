"""
mozhi_market_data.py
====================
墨衡 · 行情数据基础库
版本: v2.0 | 创建: 2026-05-16 | 修订: 2026-05-16

修订说明（v1.0 → v2.0）：
  🔴 [F1] _snapshot_sina 名称-实现不一致 → 拆为单只新浪接口 + 全量东财接口
  🔴 [F2] 全局 patch requests.get 副作用 → 改为 AkShareSession 子类，
          可选 enable_header_patch 参数，不污染宿主 requests.get
  🟡 [F3] 补充指数行情接口（benchmark_data_source.py 需求）
  🟡 [F4] 增加 Parquet 缓存层（TTL 可配置）
  🟡 [F5] 重命名歧义方法，消除"新浪/东财"与实现不一致
  🟡 [F6] _retry 补充 @wraps

依赖::
    pip install akshare baostock pandas requests pyarrow
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

# ── NO_PROXY 必须在 import requests 之前 ─────────────────────────────────────
_NO_PROXY_DOMAINS = ",".join([
    "push2his.eastmoney.com",
    "datacenter.eastmoney.com",
    "*.eastmoney.com",
    "push2.eastmoney.com",
    "quotes.sina.cn",
    "finance.sina.com.cn",
    "hq.sinajs.cn",
])
os.environ.setdefault("NO_PROXY", _NO_PROXY_DOMAINS)
os.environ.setdefault("no_proxy", _NO_PROXY_DOMAINS)

import pandas as pd      # noqa: E402
import requests          # noqa: E402

logger = logging.getLogger("mozhi.market_data")


# ══════════════════════════════════════════════════════════════════════════════
# 1. [F2] Header 注入 — AkShareSession（作用域受限，不污染全局）
# ══════════════════════════════════════════════════════════════════════════════

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}

_REFERER_MAP = {
    "eastmoney.com": "https://finance.eastmoney.com/",
    "sina.com.cn":   "https://finance.sina.com.cn/",
    "sinajs.cn":     "https://finance.sina.com.cn/",
}


def _make_referer(url: str) -> str:
    for domain, ref in _REFERER_MAP.items():
        if domain in url:
            return ref
    return "https://finance.eastmoney.com/"


class AkShareSession(requests.Session):
    """
    [F2] 仅在 AkShare 内部使用的 Session 子类，注入浏览器 Headers。
    不修改全局 requests.get，对 webhook/API 调用无副作用。
    """
    def request(self, method, url, **kwargs):  # type: ignore[override]
        headers = dict(_BROWSER_HEADERS)
        headers["Referer"] = _make_referer(url)
        headers.update(kwargs.pop("headers", {}) or {})
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


def _patch_requests_globally() -> None:
    """
    可选的全局 patch（向后兼容 v1.0，默认不启用）。
    仅当调用方明确传入 enable_header_patch=True 时使用。
    """
    if getattr(requests.get, "_mozhi_patched", False):
        return
    _orig_get = requests.get

    @wraps(_orig_get)
    def _patched(url, **kwargs):
        h = dict(_BROWSER_HEADERS)
        h["Referer"] = _make_referer(url)
        h.update(kwargs.pop("headers", {}) or {})
        kwargs["headers"] = h
        return _orig_get(url, **kwargs)

    _patched._mozhi_patched = True  # type: ignore[attr-defined]
    requests.get = _patched         # type: ignore[assignment]
    logger.warning(
        "enable_header_patch=True：已全局 patch requests.get，"
        "可能影响 webhook/API 等其他模块，仅在隔离环境中使用。"
    )


def _inject_session_to_akshare(session: AkShareSession) -> None:
    """将 AkShareSession 注入 akshare 内部 Session，替代全局 patch。"""
    try:
        import akshare.utils.func as _func  # type: ignore[import]
        if hasattr(_func, "session"):
            _func.session = session
            logger.debug("AkShareSession 注入 akshare.utils.func.session ✅")
            return
    except Exception:
        pass
    # 降级：patch requests.Session() 构造函数（范围仍小于全局 patch）
    _orig_session_cls = requests.Session

    def _session_factory(*a, **kw):
        return AkShareSession(*a, **kw)

    requests.Session = _session_factory  # type: ignore[assignment]
    logger.debug("AkShareSession 通过 requests.Session 工厂注入 ✅")


# ══════════════════════════════════════════════════════════════════════════════
# 2. 工具函数
# ══════════════════════════════════════════════════════════════════════════════

_MARKET_PREFIX = {"0": "sz", "3": "sz", "6": "sh", "4": "bj", "8": "bj"}


def _sina_code(symbol: str) -> str:
    return f"{_MARKET_PREFIX.get(symbol[0], 'sz')}{symbol}"


def _bs_code(symbol: str) -> str:
    prefix = "sh" if symbol.startswith("6") else "sz"
    return f"{prefix}.{symbol}"


# [F6] _retry 补充 @wraps
def _retry(func: Callable, times: int = 2, sleep: float = 1.0) -> Callable:
    @wraps(func)
    def wrapper(*args, **kwargs):
        last_exc: Exception = RuntimeError("未执行")
        for i in range(times):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                logger.warning(f"  {func.__name__} 第{i+1}/{times}次失败: {e}")
                if i < times - 1:
                    time.sleep(sleep)
        raise last_exc
    return wrapper


def _baostock_login():
    import baostock as bs
    if not getattr(_baostock_login, "_logged_in", False):
        result = bs.login()
        if result.error_code != "0":
            raise RuntimeError(f"baostock 登录失败: {result.error_msg}")
        _baostock_login._logged_in = True
    return bs


# ══════════════════════════════════════════════════════════════════════════════
# 3. [F4] Parquet 缓存层
# ══════════════════════════════════════════════════════════════════════════════

class _ParquetCache:
    """
    轻量 Parquet 缓存，带 TTL（分钟级）。
    文件名由查询参数 hash 确定，避免路径冲突。
    """

    def __init__(self, cache_dir: str = "data/market_cache"):
        self.root = Path(cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, **kwargs: Any) -> str:
        raw = "&".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def get(self, ttl_minutes: int, **kwargs: Any) -> Optional[pd.DataFrame]:
        path = self.root / f"{self._key(**kwargs)}.parquet"
        if not path.exists():
            return None
        age_min = (time.time() - path.stat().st_mtime) / 60
        if age_min > ttl_minutes:
            path.unlink(missing_ok=True)
            return None
        try:
            return pd.read_parquet(path)
        except Exception as e:
            logger.warning(f"缓存读取失败（忽略）: {e}")
            return None

    def set(self, df: pd.DataFrame, **kwargs: Any) -> None:
        path = self.root / f"{self._key(**kwargs)}.parquet"
        try:
            df.to_parquet(path)
        except Exception as e:
            logger.warning(f"缓存写入失败（忽略）: {e}")

    def invalidate(self, **kwargs: Any) -> None:
        path = self.root / f"{self._key(**kwargs)}.parquet"
        path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 4. 数据模型
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Snapshot:
    symbol:     str
    name:       str
    price:      float
    open:       float
    high:       float
    low:        float
    prev_close: float
    volume:     float
    amount:     float
    pct_chg:    float
    timestamp:  str


@dataclass
class CacheConfig:
    enabled:        bool  = True
    cache_dir:      str   = "data/market_cache"
    daily_ttl_min:  int   = 60      # 日线缓存 60 分钟
    minute_ttl_min: int   = 3       # 分钟线缓存 3 分钟
    index_ttl_min:  int   = 60      # 指数缓存 60 分钟


# ══════════════════════════════════════════════════════════════════════════════
# 5. 核心客户端
# ══════════════════════════════════════════════════════════════════════════════

class MarketDataClient:
    """
    A 股行情数据统一客户端 v2.0。

    数据源优先级：
      日线   → 东财(akshare) → baostock
      分钟线 → 东财(akshare) → 新浪(akshare)
      快照   → 东财全量接口过滤单只  → 新浪单只接口
      批量快照 → 东财全量接口（1次请求）
      指数   → 东财(akshare) → 新浪(akshare)    [F3 新增]
    """

    def __init__(
        self,
        retry_times:         int         = 2,
        retry_sleep:         float       = 1.0,
        request_gap:         float       = 0.5,
        cache:               CacheConfig = None,
        enable_header_patch: bool        = False,
    ):
        """
        参数
        ----
        retry_times          重试次数
        retry_sleep          重试间隔（秒）
        request_gap          请求限速（秒）
        cache                缓存配置，None 使用默认值
        enable_header_patch  True=全局 patch requests.get（⚠️ 副作用大，
                             仅在完全隔离的回测进程中使用）
                             False（默认）=仅 AkShareSession 注入，无副作用
        """
        self.retry_times = retry_times
        self.retry_sleep = retry_sleep
        self.request_gap = request_gap
        self._last_req   = 0.0
        self._cache_cfg  = cache or CacheConfig()
        self._cache      = (
            _ParquetCache(self._cache_cfg.cache_dir)
            if self._cache_cfg.enabled else None
        )

        # [F2] Header 注入策略
        if enable_header_patch:
            _patch_requests_globally()
        else:
            self._session = AkShareSession()
            _inject_session_to_akshare(self._session)

        # 延迟 import akshare（注入完成后）
        import akshare as _ak
        self._ak = _ak

    # ── 限速 ──────────────────────────────────────────────────────────────────
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_req
        if elapsed < self.request_gap:
            time.sleep(self.request_gap - elapsed)
        self._last_req = time.time()

    def _try(self, func: Callable, *args, **kwargs):
        return _retry(func, self.retry_times, self.retry_sleep)(*args, **kwargs)

    # ──────────────────────────────────────────────────────────────────────────
    # 5.1 日线
    # ──────────────────────────────────────────────────────────────────────────

    def get_daily(
        self,
        symbol: str,
        adjust: str = "qfq",
        start:  str = "2023-01-01",
        end:    str = "",
    ) -> pd.DataFrame:
        """日线 OHLCV，index=date(str)"""
        # 缓存命中
        if self._cache:
            cached = self._cache.get(
                self._cache_cfg.daily_ttl_min,
                fn="daily", symbol=symbol, adjust=adjust, start=start, end=end,
            )
            if cached is not None:
                logger.debug(f"[{symbol}] 日线缓存命中")
                return cached

        self._throttle()
        try:
            df = self._try(self._daily_eastmoney, symbol, adjust, start, end)
            logger.info(f"[{symbol}] 东财日线 {len(df)} 条")
        except Exception as e:
            logger.warning(f"[{symbol}] 东财日线失败，降级baostock: {e}")
            self._throttle()
            df = self._try(self._daily_baostock, symbol, adjust, start, end)
            logger.info(f"[{symbol}] baostock日线 {len(df)} 条")

        if self._cache:
            self._cache.set(
                df, fn="daily", symbol=symbol, adjust=adjust, start=start, end=end,
            )
        return df

    def _daily_eastmoney(
        self, symbol: str, adjust: str, start: str, end: str
    ) -> pd.DataFrame:
        end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
        df = self._ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust=adjust,
        )
        return _normalize_daily_em(df)

    def _daily_baostock(
        self, symbol: str, adjust: str, start: str, end: str
    ) -> pd.DataFrame:
        bs = _baostock_login()
        end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
        adj_flag = {"qfq": "2", "hfq": "1", "": "3"}.get(adjust, "3")
        rs = bs.query_history_k_data_plus(
            _bs_code(symbol),
            "date,open,high,low,close,volume,amount,pctChg",
            start_date=start, end_date=end,
            frequency="d", adjustflag=adj_flag,
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(
            rows, columns=["date","open","high","low","close","volume","amount","pct_chg"]
        ).set_index("date")
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    # ──────────────────────────────────────────────────────────────────────────
    # 5.2 分钟线
    # ──────────────────────────────────────────────────────────────────────────

    def get_minute(
        self,
        symbol: str,
        period: str = "5",
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """分钟线 OHLCV，index=datetime(Timestamp)，period: 1/5/15/30/60"""
        if self._cache:
            cached = self._cache.get(
                self._cache_cfg.minute_ttl_min,
                fn="minute", symbol=symbol, period=period, adjust=adjust,
            )
            if cached is not None:
                logger.debug(f"[{symbol}] 分钟线缓存命中")
                return cached

        self._throttle()
        try:
            df = self._try(self._minute_eastmoney, symbol, period, adjust)
            logger.info(f"[{symbol}] 东财{period}分钟 {len(df)} 条")
        except Exception as e:
            logger.warning(f"[{symbol}] 东财分钟线失败，降级新浪: {e}")
            self._throttle()
            df = self._try(self._minute_sina, symbol, period, adjust)
            logger.info(f"[{symbol}] 新浪{period}分钟 {len(df)} 条")

        if self._cache:
            self._cache.set(
                df, fn="minute", symbol=symbol, period=period, adjust=adjust,
            )
        return df

    def _minute_eastmoney(
        self, symbol: str, period: str, adjust: str
    ) -> pd.DataFrame:
        df = self._ak.stock_zh_a_hist_min_em(
            symbol=symbol, period=period, adjust=adjust
        )
        return _normalize_minute(df, ts_col="时间")

    def _minute_sina(
        self, symbol: str, period: str, adjust: str
    ) -> pd.DataFrame:
        df = self._ak.stock_zh_a_minute(
            symbol=_sina_code(symbol), period=period, adjust=adjust
        )
        return _normalize_minute(df, ts_col="day")

    # ──────────────────────────────────────────────────────────────────────────
    # 5.3 [F1] 实时快照 — 拆分单只与批量
    # ──────────────────────────────────────────────────────────────────────────

    def get_snapshot(self, symbol: str) -> Snapshot:
        """
        单只实时快照。
        [F1 Fix] 主路径：东财全量接口过滤单只（stock_zh_a_spot_em）。
        降级：新浪单只接口（stock_zh_a_spot("shXXXXX")）。
        """
        self._throttle()
        try:
            return self._try(self._snapshot_single_em, symbol)
        except Exception as e:
            logger.warning(f"[{symbol}] 东财全量快照失败，降级新浪单只: {e}")

        self._throttle()
        return self._try(self._snapshot_single_sina, symbol)

    def _snapshot_single_em(self, symbol: str) -> Snapshot:
        """[F1 Fix] 东财全量接口过滤单只（主路径）。
        使用 stock_zh_a_spot_em() 拉全量后过滤单行。
        降级见 _snapshot_single_sina（新浪单只接口）。
        """
        df = self._ak.stock_zh_a_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty:
            raise ValueError(f"东财全量快照未找到: {symbol}")
        return _row_to_snapshot(symbol, row.iloc[0])

    def _snapshot_single_sina(self, symbol: str) -> Snapshot:
        """[F1 Fix] 新浪单只接口降级。
        使用 stock_zh_a_spot(sina_code) 仅拉取单只数据。
        """
        code = _sina_code(symbol)
        df = self._ak.stock_zh_a_spot(code)
        code_col = "代码"
        row = df[df[code_col] == code]
        if row.empty:
            raise ValueError(f"新浪单只快照未找到: {symbol}（sina_code={code}）")
        r = row.iloc[0]
        return Snapshot(
            symbol    = symbol,
            name      = str(r.get("名称", "")),
            price     = float(r.get("最新价", 0) or 0),
            open      = float(r.get("今开", 0) or 0),
            high      = float(r.get("最高", 0) or 0),
            low       = float(r.get("最低", 0) or 0),
            prev_close= float(r.get("昨收", 0) or 0),
            volume    = float(r.get("成交量", 0) or 0),
            amount    = float(r.get("成交额", 0) or 0),
            pct_chg   = float(r.get("涨跌幅", 0) or 0),
            timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def get_snapshot_batch(
        self,
        symbols: list[str],
        gap:     float = 0.3,
    ) -> dict[str, Snapshot]:
        """
        批量实时快照。
        [F1] 东财全量接口一次拉取（1次请求），再按 symbol 过滤，
        不再循环调用单只接口。
        """
        self._throttle()
        try:
            df = self._ak.stock_zh_a_spot_em()
            result = {}
            for symbol in symbols:
                row = df[df["代码"] == symbol]
                if row.empty:
                    logger.warning(f"[{symbol}] 全量快照未找到")
                    continue
                result[symbol] = _row_to_snapshot(symbol, row.iloc[0])
            logger.info(f"批量快照：{len(result)}/{len(symbols)} 只成功")
            return result
        except Exception as e:
            logger.warning(f"东财全量快照失败，逐只降级: {e}")
            result = {}
            for symbol in symbols:
                try:
                    result[symbol] = self.get_snapshot(symbol)
                except Exception as ex:
                    logger.error(f"[{symbol}] 快照最终失败: {ex}")
                time.sleep(gap)
            return result

    @staticmethod
    def _calc_pct_chg(price: float, prev_close: float) -> float:
        if prev_close == 0:
            return 0.0
        return round((price - prev_close) / prev_close * 100, 4)

    # ──────────────────────────────────────────────────────────────────────────
    # 5.4 [F3] 指数行情（benchmark_data_source.py 需求）
    # ──────────────────────────────────────────────────────────────────────────

    # 常用指数代码映射
    INDEX_MAP = {
        "上证指数":  "000001",
        "沪深300":  "000300",
        "深证成指":  "399001",
        "创业板指":  "399006",
        "中证500":  "000905",
        "科创50":   "000688",
    }

    def get_index_daily(
        self,
        symbol: str,
        start:  str = "2023-01-01",
        end:    str = "",
    ) -> pd.DataFrame:
        """
        [F3] 指数日线行情（不复权，指数无复权概念）。

        symbol 支持：
          - 数字代码：'000300'、'399001'
          - 中文名：'沪深300'、'上证指数'（见 INDEX_MAP）

        返回
        ----
        DataFrame，index=date(str)，列：open/high/low/close/volume/amount/pct_chg
        """
        # 中文名映射
        symbol = self.INDEX_MAP.get(symbol, symbol)

        if self._cache:
            cached = self._cache.get(
                self._cache_cfg.index_ttl_min,
                fn="index", symbol=symbol, start=start, end=end,
            )
            if cached is not None:
                logger.debug(f"[{symbol}] 指数缓存命中")
                return cached

        self._throttle()
        try:
            df = self._try(self._index_eastmoney, symbol, start, end)
            logger.info(f"[指数{symbol}] 东财 {len(df)} 条")
        except Exception as e:
            logger.warning(f"[指数{symbol}] 东财失败，降级新浪: {e}")
            self._throttle()
            df = self._try(self._index_sina, symbol, start, end)
            logger.info(f"[指数{symbol}] 新浪 {len(df)} 条")

        if self._cache:
            self._cache.set(
                df, fn="index", symbol=symbol, start=start, end=end,
            )
        return df

    def _index_eastmoney(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
        df = self._ak.index_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
        )
        return _normalize_daily_em(df)

    def _index_sina(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """新浪指数日线。使用 stock_zh_index_spot_sina 获取实时快照式数据。"""
        code = _sina_code(symbol)
        df = self._ak.stock_zh_index_spot_sina()
        row = df[df["代码"] == code]
        if row.empty:
            raise ValueError(f"新浪指数快照未找到: {symbol}")
        r = row.iloc[0]
        # 将单行数据转为 DataFrame
        data = pd.DataFrame([{
            "open":     float(r.get("今开", 0) or 0),
            "high":     float(r.get("最高", 0) or 0),
            "low":      float(r.get("最低", 0) or 0),
            "close":    float(r.get("最新价", 0) or 0),
            "volume":   float(r.get("成交量", 0) or 0),
            "amount":   float(r.get("成交额", 0) or 0),
            "pct_chg":  float(r.get("涨跌幅", 0) or 0),
        }], index=[pd.Timestamp.now().strftime("%Y-%m-%d")])
        return data

    def get_index_snapshot(self, symbol: str) -> Snapshot:
        """[F3] 指数实时快照"""
        symbol = self.INDEX_MAP.get(symbol, symbol)
        self._throttle()
        df = self._try(self._ak.stock_zh_index_spot_em)
        if df is None or df.empty:
            raise RuntimeError("指数快照接口无数据")
        row = df[df["代码"] == symbol]
        if row.empty:
            raise ValueError(f"指数快照未找到: {symbol}")
        r = row.iloc[0]
        return Snapshot(
            symbol    = symbol,
            name      = str(r.get("名称", "")),
            price     = float(r.get("最新价", 0) or 0),
            open      = float(r.get("今开", 0) or 0),
            high      = float(r.get("最高", 0) or 0),
            low       = float(r.get("最低", 0) or 0),
            prev_close= float(r.get("昨收", 0) or 0),
            volume    = float(r.get("成交量", 0) or 0),
            amount    = float(r.get("成交额", 0) or 0),
            pct_chg   = float(r.get("涨跌幅", 0) or 0),
            timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 5.5 批量日线
    # ──────────────────────────────────────────────────────────────────────────

    def get_daily_batch(
        self,
        symbols: list[str],
        adjust:  str   = "qfq",
        start:   str   = "2023-01-01",
        end:     str   = "",
        gap:     float = 0.8,
    ) -> dict[str, pd.DataFrame]:
        """批量日线，返回 {symbol: DataFrame}"""
        result: dict[str, pd.DataFrame] = {}
        for i, symbol in enumerate(symbols):
            try:
                result[symbol] = self.get_daily(symbol, adjust, start, end)
            except Exception as e:
                logger.error(f"[{symbol}] 批量日线失败: {e}")
                result[symbol] = pd.DataFrame()
            if i < len(symbols) - 1:
                time.sleep(gap)
        return result


# ══════════════════════════════════════════════════════════════════════════════
# 6. [F5] 内部标准化函数（命名消除歧义）
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_daily_em(df: pd.DataFrame) -> pd.DataFrame:
    """东财日线列名标准化"""
    df = df.rename(columns={
        "日期": "date",   "开盘": "open",   "收盘": "close",
        "最高": "high",   "最低": "low",    "成交量": "volume",
        "成交额": "amount","涨跌幅": "pct_chg","换手率": "turnover",
    })
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.set_index("date")
    cols = [c for c in ["open","high","low","close","volume","amount","pct_chg"]
            if c in df.columns]
    df = df[cols]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _normalize_minute(df: pd.DataFrame, ts_col: str) -> pd.DataFrame:
    """分钟线列名标准化（东财/新浪通用）"""
    rename = {
        ts_col:   "datetime",
        "开盘": "open",  "收盘": "close", "最高": "high",
        "最低": "low",   "成交量": "volume","成交额": "amount",
        "涨跌幅": "pct_chg","换手率": "turnover",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["datetime"] = pd.to_datetime(df["datetime"])
    cols = [c for c in ["open","high","low","close","volume","amount","pct_chg"]
            if c in df.columns]
    df = df.set_index("datetime")[cols]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _row_to_snapshot(symbol: str, r: pd.Series) -> Snapshot:
    """东财全量行转 Snapshot"""
    return Snapshot(
        symbol    = symbol,
        name      = str(r.get("名称", "")),
        price     = float(r.get("最新价", 0) or 0),
        open      = float(r.get("今开", 0) or 0),
        high      = float(r.get("最高", 0) or 0),
        low       = float(r.get("最低", 0) or 0),
        prev_close= float(r.get("昨收", 0) or 0),
        volume    = float(r.get("成交量", 0) or 0),
        amount    = float(r.get("成交额", 0) or 0),
        pct_chg   = float(r.get("涨跌幅", 0) or 0),
        timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 7. 诊断工具
# ══════════════════════════════════════════════════════════════════════════════

def diagnose() -> dict:
    """网络与数据源状态诊断，返回报告字典"""
    report: dict[str, Any] = {}

    s = requests.Session()
    cfg = s.merge_environment_settings(
        "https://push2his.eastmoney.com", {}, False, None, None
    )
    report["proxy"]         = cfg["proxies"].get("https", "") or "直连"
    report["no_proxy_set"]  = bool(os.environ.get("NO_PROXY"))
    report["global_patch"]  = getattr(requests.get, "_mozhi_patched", False)
    report["session_patch"] = True  # AkShareSession 始终注入

    for name, url in [
        ("eastmoney", "https://push2his.eastmoney.com"),
        ("sina",      "https://finance.sina.com.cn"),
    ]:
        try:
            r = requests.get(url, timeout=5)
            report[f"{name}_reachable"] = r.status_code < 500
            report[f"{name}_status"]    = r.status_code
        except Exception as e:
            report[f"{name}_reachable"] = False
            report[f"{name}_error"]     = str(e)

    try:
        bs = _baostock_login()
        report["baostock_reachable"] = True
    except Exception as e:
        report["baostock_reachable"] = False
        report["baostock_error"]     = str(e)

    return report


# ══════════════════════════════════════════════════════════════════════════════
# 8. 快捷函数（代理直接调用，无需实例化）
# ══════════════════════════════════════════════════════════════════════════════

_default_client: Optional[MarketDataClient] = None


def _client() -> MarketDataClient:
    global _default_client
    if _default_client is None:
        _default_client = MarketDataClient()
    return _default_client


def get_daily(symbol: str, adjust: str = "qfq",
              start: str = "2023-01-01", end: str = "") -> pd.DataFrame:
    """快捷：日线"""
    return _client().get_daily(symbol, adjust=adjust, start=start, end=end)


def get_minute(symbol: str, period: str = "5",
               adjust: str = "qfq") -> pd.DataFrame:
    """快捷：分钟线"""
    return _client().get_minute(symbol, period=period, adjust=adjust)


def get_snapshot(symbol: str) -> Snapshot:
    """快捷：单只实时快照（新浪单只接口）"""
    return _client().get_snapshot(symbol)


def get_snapshot_batch(symbols: list[str]) -> dict[str, Snapshot]:
    """快捷：批量实时快照（东财全量接口）"""
    return _client().get_snapshot_batch(symbols)


def get_index_daily(symbol: str, start: str = "2023-01-01",
                    end: str = "") -> pd.DataFrame:
    """快捷：指数日线（支持代码或中文名）"""
    return _client().get_index_daily(symbol, start=start, end=end)


def get_index_snapshot(symbol: str) -> Snapshot:
    """快捷：指数实时快照"""
    return _client().get_index_snapshot(symbol)


def get_daily_batch(symbols: list[str], adjust: str = "qfq",
                    start: str = "2023-01-01") -> dict[str, pd.DataFrame]:
    """快捷：批量日线"""
    return _client().get_daily_batch(symbols, adjust=adjust, start=start)


# ══════════════════════════════════════════════════════════════════════════════
# 9. 自检入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("mozhi_market_data v2.0 自检")
    print("=" * 60)

    diag = diagnose()
    print(f"\n── 网络环境 ─────────────────────────────────────────")
    print(f"  代理状态        : {diag['proxy']}")
    print(f"  NO_PROXY 已设置 : {'✅' if diag['no_proxy_set'] else '❌'}")
    print(f"  全局 patch      : {'⚠️ 已启用' if diag['global_patch'] else '✅ 未启用（安全）'}")
    print(f"  Session 注入    : {'✅' if diag['session_patch'] else '❌'}")
    print(f"  东财可达        : {'✅' if diag.get('eastmoney_reachable') else '❌'}")
    print(f"  新浪可达        : {'✅' if diag.get('sina_reachable') else '❌'}")
    print(f"  baostock可达    : {'✅' if diag.get('baostock_reachable') else '❌'}")

    client = MarketDataClient(
        retry_times=2,
        request_gap=0.8,
        cache=CacheConfig(enabled=True, daily_ttl_min=60),
    )
    TARGET = "601857"

    tests = [
        ("日线",       lambda: client.get_daily(TARGET, start="2026-01-01")),
        ("5分钟线",    lambda: client.get_minute(TARGET, period="5")),
        ("单只快照",   lambda: client.get_snapshot(TARGET)),
        ("指数日线",   lambda: client.get_index_daily("沪深300", start="2026-01-01")),
        ("指数快照",   lambda: client.get_index_snapshot("沪深300")),
        ("批量快照",   lambda: client.get_snapshot_batch([TARGET, "000001"])),
    ]

    for name, fn in tests:
        print(f"\n── {name}测试 ─────────────────────────────────────────")
        try:
            result = fn()
            if isinstance(result, pd.DataFrame):
                print(result.tail(2))
                print(f"  共 {len(result)} 条")
            elif isinstance(result, Snapshot):
                print(f"  {result.name}({result.symbol}) "
                      f"价={result.price} 涨跌={result.pct_chg:+.2f}%")
            elif isinstance(result, dict):
                for sym, s in result.items():
                    print(f"  {sym}: {s.price} ({s.pct_chg:+.2f}%)")
        except Exception as e:
            print(f"  ❌ {e}")

    print("\n自检完成 ✅")