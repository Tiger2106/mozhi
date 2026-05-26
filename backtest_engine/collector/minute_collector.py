# minute_collector.py
# 墨家投资室 - 分钟级数据采集模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 数据源：AKShare stock_zh_a_minute
# 频率：1min / 5min / 15min / 30min / 60min
# 存储：analysis.db → stock_minute 表
#
# 使用方式：
#   from collector.minute_collector import MinuteCollector
#   mc = MinuteCollector()
#   mc.collect_single('601857', '20260522')

import sqlite3
import os
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

# 默认数据库路径
DEFAULT_DB = os.path.join(
    os.environ.get("MOZHIHOME", str(Path.home() / "mozhi_platform")),
    "data", "analysis.db"
)

# AKShare 股票前缀映射
_PREFIX_MAP = {
    '6': 'sh', '9': 'sh',
    '0': 'sz', '3': 'sz', '2': 'sz',
    '4': 'bj', '8': 'bj',
}


class MinuteCollector:
    """
    分钟级数据采集器。
    
    使用 AKShare 获取 A 股分钟级 K 线数据。
    AKShare stock_zh_a_minute 返回最近 ~5 个交易日数据.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DEFAULT_DB
        self._init_db()

    # ── 数据库初始化 ──────────────────────────────────────

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_minute (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    date TEXT NOT NULL,
                    minute TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    amount REAL,
                    freq TEXT DEFAULT '5min',
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    UNIQUE(code, date, minute, freq)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sm_cdf
                ON stock_minute(code, date, freq)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sm_date
                ON stock_minute(date)
            """)
            conn.commit()
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ── 股票代码转换 ──────────────────────────────────────

    @staticmethod
    def to_akshare_symbol(symbol: str) -> str:
        """将 6 位代码转为 AKShare 格式（如 601857 → sh601857）"""
        symbol = symbol.strip().split('.')[0]
        prefix = _PREFIX_MAP.get(symbol[0], 'sh')
        return f"{prefix}{symbol}"

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """标准化为 6 位纯代码"""
        return symbol.strip().split('.')[0]

    # ── 核心采集 ──────────────────────────────────────────

    def collect_single(self, symbol: str, date: str,
                       freq: str = '5min',
                       save_to_db: bool = True) -> Optional[List[Dict]]:
        """
        采集单只股票的分钟级数据。

        Args:
            symbol: 6位股票代码（如 '601857'）
            date: 交易日 'YYYYMMDD'
            freq: 频率（'1min'/'5min'/[15|30|60]min）
            save_to_db: 是否写入数据库

        Returns:
            分钟级数据列表，或 None（失败时）
        """
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare not installed")
            return None

        ak_symbol = self.to_akshare_symbol(symbol)
        code = self.normalize_symbol(symbol)

        # AKShare period mapping
        period_map = {
            '1min': '1', '5min': '5', '15min': '15',
            '30min': '30', '60min': '60',
        }
        period = period_map.get(freq, '5')

        try:
            df = ak.stock_zh_a_minute(symbol=ak_symbol, period=period)
        except Exception as e:
            logger.error("AKShare fetch failed for %s: %s", ak_symbol, e)
            return None

        if df is None or len(df) == 0:
            logger.warning("No data returned for %s", ak_symbol)
            return None

        # 解析日期行 → minute
        records = []
        for _, row in df.iterrows():
            day_str = str(row['day'])
            # day format: '2026-05-22 14:50:00'
            try:
                dt = datetime.strptime(day_str, '%Y-%m-%d %H:%M:%S')
                rec_date = dt.strftime('%Y%m%d')
                hhmm = dt.strftime('%H:%M')
            except ValueError:
                logger.warning("Cannot parse datetime: %s", day_str)
                continue

            # 只保留目标日期的数据
            if rec_date != date:
                continue

            records.append({
                'code': code,
                'date': date,
                'minute': hhmm,
                'freq': freq,
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'close': float(row.get('close', 0)),
                'volume': int(row.get('volume', 0)),
                'amount': float(row.get('amount', 0)),
            })

        if not records:
            logger.info("No records for %s on %s (possibly non-trading day)", symbol, date)
            return []

        if save_to_db:
            self._save_batch(records)

        logger.info("Collected %d minute records for %s on %s (freq=%s)",
                    len(records), symbol, date, freq)
        return records

    def collect_batch(self, symbols: List[str], date: str,
                      freq: str = '5min') -> Dict[str, int]:
        """
        采集多只股票的分钟级数据。

        Args:
            symbols: 股票代码列表
            date: 交易日
            freq: 频率

        Returns:
            {symbol: record_count} 字典
        """
        result = {}
        for sym in symbols:
            records = self.collect_single(sym, date, freq=freq, save_to_db=True)
            result[sym] = len(records) if records else 0
            time.sleep(0.5)  # AKShare 限频保护
        return result

    # ── 存储 ──────────────────────────────────────────────

    def _save_batch(self, records: List[Dict]):
        """批量写入分钟级数据"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            for rec in records:
                cursor.execute(
                    """INSERT OR REPLACE INTO stock_minute
                       (code, date, minute, freq, open, high, low,
                        close, volume, amount, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               datetime('now','localtime'))""",
                    (rec['code'], rec['date'], rec['minute'], rec['freq'],
                     rec['open'], rec['high'], rec['low'],
                     rec['close'], rec['volume'], rec['amount'])
                )
            conn.commit()
        finally:
            conn.close()

    # ── 查询 ──────────────────────────────────────────────

    def query_minute(self, symbol: str, date: str,
                     freq: str = '5min') -> List[Dict]:
        """查询数据库中的分钟级数据"""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """SELECT * FROM stock_minute
                   WHERE code=? AND date=? AND freq=?
                   ORDER BY minute""",
                (symbol, date, freq)
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def count_minute_records(self, date: str = None) -> int:
        """统计分钟数据量"""
        conn = self._get_conn()
        try:
            if date:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM stock_minute WHERE date=?",
                    (date,)
                )
            else:
                cur = conn.execute("SELECT COUNT(*) FROM stock_minute")
            return cur.fetchone()[0]
        finally:
            conn.close()
