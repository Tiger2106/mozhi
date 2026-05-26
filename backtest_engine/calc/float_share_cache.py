# float_share_cache.py
# 墨家投资室 - Tushare float_share 缓存模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 用途：缓存 Tushare daily_basic.float_share（流通股本，万股）
# 刷新策略：日频，T+1 刷新
# 存储：本地 SQLite 缓存 + Tushare 实时补齐
#
# 使用方式：
#   from calc.float_share_cache import FloatShareCache
#   cache = FloatShareCache()
#   float_share = cache.get(symbol='601857', date='20260522')

import sqlite3
import os
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────

# 缓存数据库路径（MOZHIHOME 指向平台根目录，回退到 mozhi_platform）
CACHE_DB_DIR = os.environ.get(
    "MOZHIHOME",
    str(Path.home() / "mozhi_platform")
)
CACHE_DB_PATH = os.path.join(CACHE_DB_DIR, "db", "float_share_cache.db")

# 缓存保留天数
CACHE_RETENTION_DAYS = 90

# Tushare 限频控制
TUSHARE_RATE_LIMIT_SLEEP = 0.6  # 每次请求间隔（秒），确保 < 100次/分钟


class FloatShareCache:
    """
    Tushare float_share 缓存模块。
    
    提供本地缓存 + 远程补齐的双层架构：
      - 本地 SQLite：key=(symbol, date) → float_share
      - 远程：Tushare daily_basic API 带限频
      - 缺失处理：N-1 天填充（同一标的最近值）
    """

    def __init__(self, db_path: str = None, auto_init: bool = True):
        self.db_path = db_path or CACHE_DB_PATH
        self._pro = None  # lazy init for tushare
        if auto_init:
            self._init_db()

    # ── 数据库初始化 ──────────────────────────────────────

    def _init_db(self):
        """确保缓存目录和数据库表存在"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS float_share_cache (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    float_share REAL,
                    total_share REAL,
                    circ_mv REAL,
                    fetched_at TEXT DEFAULT (datetime('now','localtime')),
                    PRIMARY KEY (symbol, date)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fsc_symbol_date
                ON float_share_cache(symbol, date)
            """)
            conn.commit()
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Tushare 接入 ──────────────────────────────────────

    def _get_pro(self):
        """Lazy init Tushare Pro API"""
        if self._pro is None:
            import tushare as ts
            self._pro = ts.pro_api()
        return self._pro

    def _fetch_from_tushare(self, symbol: str, date: str) -> Optional[Dict]:
        """
        从 Tushare 获取 float_share 数据。
        
        Args:
            symbol: 6位股票代码（如 '601857'）
            date: 日期字符串 'YYYYMMDD'
            
        Returns:
            {'float_share': float, 'total_share': float, 'circ_mv': float} 或 None
        """
        try:
            # Tushare 需要完整的 ts_code 格式
            ts_code = self._format_ts_code(symbol)
            pro = self._get_pro()
            df = pro.daily_basic(
                ts_code=ts_code,
                start_date=date,
                end_date=date,
                fields='ts_code,trade_date,float_share,total_share,circ_mv'
            )
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                return {
                    'float_share': float(row.get('float_share', 0) or 0),
                    'total_share': float(row.get('total_share', 0) or 0),
                    'circ_mv': float(row.get('circ_mv', 0) or 0),
                }
            time.sleep(TUSHARE_RATE_LIMIT_SLEEP)
            return None
        except Exception as e:
            logger.warning("Tushare fetch failed for %s %s: %s", symbol, date, e)
            return None

    @staticmethod
    def _format_ts_code(symbol: str) -> str:
        """格式化股票代码为 Tushare 格式"""
        symbol = symbol.strip()
        if '.' in symbol:
            return symbol  # 已经是完整格式
        # 识别交易所
        if symbol.startswith('6') or symbol.startswith('9'):
            return f"{symbol}.SH"
        elif symbol.startswith('0') or symbol.startswith('3') or symbol.startswith('2'):
            return f"{symbol}.SZ"
        elif symbol.startswith('4') or symbol.startswith('8'):
            return f"{symbol}.BJ"
        else:
            return f"{symbol}.SH"  # fallback

    # ── 核心方法 ──────────────────────────────────────────

    def get(self, symbol: str, date: str) -> Optional[float]:
        """
        获取指定标的在指定日期的 float_share（万股）。
        
        策略：
          1. 查本地缓存 → 命中返回
          2. 远程 Tushare 补齐 → 写入缓存
          3. N-1 天填充（同一标的最近值）
          4. 返回 None
          
        Args:
            symbol: 6位股票代码
            date: 日期 'YYYYMMDD'
            
        Returns:
            float_share 值（万股）或 None
        """
        # 1. 查本地缓存
        cached = self._get_cached(symbol, date)
        if cached is not None:
            return cached

        # 2. 远程补齐
        result = self._fetch_from_tushare(symbol, date)
        if result is not None:
            self._cache_result(symbol, date, result)
            return result['float_share']

        # 3. N-1 天填充
        filled = self._fill_from_nearest(symbol, date)
        if filled is not None:
            return filled

        return None

    def get_all_fields(self, symbol: str, date: str) -> Optional[Dict]:
        """获取完整字段（float_share, total_share, circ_mv）"""
        cached = self._get_cached_full(symbol, date)
        if cached:
            return cached

        result = self._fetch_from_tushare(symbol, date)
        if result is not None:
            self._cache_result(symbol, date, result)
            return result

        return None

    def batch_get(self, symbols: list, date: str) -> dict:
        """
        批量获取多个标的在同一天的 float_share。
        
        Args:
            symbols: 股票代码列表
            date: 日期
            
        Returns:
            {symbol: float_share} 字典
        """
        result = {}
        for sym in symbols:
            val = self.get(sym, date)
            if val:
                result[sym] = val
        return result

    # ── 内部方法 ──────────────────────────────────────────

    def _get_cached(self, symbol: str, date: str) -> Optional[float]:
        """查本地缓存"""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT float_share FROM float_share_cache WHERE symbol=? AND date=?",
                (symbol, date)
            )
            row = cur.fetchone()
            return row['float_share'] if row else None
        finally:
            conn.close()

    def _get_cached_full(self, symbol: str, date: str) -> Optional[Dict]:
        """查本地缓存（完整字段）"""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT float_share, total_share, circ_mv FROM float_share_cache WHERE symbol=? AND date=?",
                (symbol, date)
            )
            row = cur.fetchone()
            if row:
                return {
                    'float_share': row['float_share'],
                    'total_share': row['total_share'],
                    'circ_mv': row['circ_mv'],
                }
            return None
        finally:
            conn.close()

    def _cache_result(self, symbol: str, date: str, result: Dict):
        """将 Tushare 结果写入本地缓存"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO float_share_cache
                   (symbol, date, float_share, total_share, circ_mv, fetched_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))""",
                (symbol, date, result['float_share'],
                 result['total_share'], result['circ_mv'])
            )
            conn.commit()
        finally:
            conn.close()

    def _fill_from_nearest(self, symbol: str, date_str: str) -> Optional[float]:
        """
        N-1 填充：查找同一标的在 date 之前最近的一笔缓存。
        
        Args:
            symbol: 股票代码
            date_str: 目标日期
            
        Returns:
            最近有效 float_share 或 None
        """
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """SELECT float_share FROM float_share_cache
                   WHERE symbol=? AND date < ?
                   ORDER BY date DESC LIMIT 1""",
                (symbol, date_str)
            )
            row = cur.fetchone()
            if row:
                return row['float_share']
            return None
        finally:
            conn.close()

    def refresh(self, symbols: list, date: str = None):
        """
        强制刷新指定标的的缓存（从 Tushare 拉取）。
        
        Args:
            symbols: 股票代码列表
            date: 日期，默认当日
        """
        date = date or datetime.now().strftime("%Y%m%d")
        for sym in symbols:
            result = self._fetch_from_tushare(sym, date)
            if result:
                self._cache_result(sym, date, result)
                logger.info("Refreshed %s on %s: float_share=%.2f万股",
                           sym, date, result['float_share'])

    def cleanup(self, retention_days: int = None):
        """清理旧缓存"""
        retention_days = retention_days or CACHE_RETENTION_DAYS
        cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y%m%d")
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM float_share_cache WHERE date < ?",
                (cutoff,)
            )
            deleted = cur.rowcount
            conn.commit()
            logger.info("Cleaned %d stale float_share cache rows", deleted)
        finally:
            conn.close()
