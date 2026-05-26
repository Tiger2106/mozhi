# vwap_channel.py
# 墨家投资室 - VWAP ± nσ 通道计算模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 说明：
#   VWAP = SUM(price × volume) / SUM(volume)
#   σ = 滚动窗口样本标准差
#   通道：上轨 = VWAP + n×σ, 下轨 = VWAP - n×σ
#
# 使用方式：
#   from calc.vwap_channel import VWAPChannel
#   channel = VWAPChannel()
#   result = channel.calc(symbol='601857', date='20260522')

from typing import Optional, Dict, List, Tuple
import math
import logging
import sqlite3
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class VWAPChannel:
    """
    VWAP ± nσ 通道计算。
    
    VWAP 使用日频数据估算：
      VWAP ≈ amount / volume  (日成交均价)
    
    注意：精确 VWAP 需分钟级数据，此处用日均价近似。
    若已有分钟级数据，可在 Phase 4 完成后升级为精确计算。

    数据来源：统一使用 data_source.fetch_daily()（P1 数据入口统一）
    """

    DEFAULT_N = 2          # 默认 ±2σ
    DEFAULT_WINDOW = 20    # 默认滚动窗口 20 天

    def __init__(self, db_path: str = None):
        # 兼容旧参数，已不再使用；数据通过 data_source 统一获取
        self.db_path = db_path

    # ── 核心计算 ──────────────────────────────────────────

    def calc_avg_trade_price(self, amount: float, volume: float) -> Optional[float]:
        """
        计算日均成交价格（VWAP 近似值）。
        
        avg_trade_price = amount / volume
        
        Args:
            amount: 成交金额（元）
            volume: 成交量（股）
            
        Returns:
            日均价（元/股），或 None
        """
        if volume is None or volume <= 0 or amount is None or amount <= 0:
            return None
        return amount / volume

    def calc(self, symbol: str, date: str,
             n: float = None, window: int = None) -> Optional[Dict]:
        """
        计算指定标的/日期的 VWAP 通道。

        Args:
            symbol: 6位股票代码
            date: 目标日期 'YYYYMMDD'
            n: σ 倍数，默认 2
            window: 滚动窗口大小，默认 20

        Returns:
            {
                'vwap': float,          # 当日 VWAP（均价）
                'std': float,           # 窗口期 VWAP 标准差
                'upper': float,         # VWAP + n×σ
                'lower': float,         # VWAP - n×σ
                'n': float,
                'window': int,
                'mid': float,           # = VWAP
                'close_vs_vwap_pct': float,  # 收盘价偏离 VWAP 百分比
                'close_above_upper': bool,   # 收盘价 > 上轨
                'close_below_lower': bool,   # 收盘价 < 下轨
            }
            数据不足时返回 None
        """
        n = n or self.DEFAULT_N
        window = window or self.DEFAULT_WINDOW

        # 获取窗口数据（包含目标日期在内共 window 天）
        data = self._fetch_window(symbol, date, window)
        if not data or len(data) < 3:
            logger.warning("Insufficient data for %s around %s", symbol, date)
            return None

        # 计算每日 VWAP（均价）
        vwaps = []
        vwap_today = None
        for row in data:
            vol = row['volume']
            amt = row['amount']
            avg = self.calc_avg_trade_price(amt, vol)
            if avg is not None:
                vwaps.append(avg)
                if row['date'] == date:
                    vwap_today = avg

        if vwap_today is None or len(vwaps) < 3:
            return None

        # 计算 σ
        std = self._calc_std(vwaps)

        # 通道
        upper = vwap_today + n * std
        lower = vwap_today - n * std
        lower = max(lower, 0)  # 下轨不为负

        # 收盘价信息
        close_price = data[0]['close']  # date 是第一行（按时间降序，第一行即最新）

        # 偏离度
        close_vs_vwap = (close_price - vwap_today) / vwap_today * 100 if vwap_today != 0 else 0

        return {
            'vwap': round(vwap_today, 4),
            'std': round(std, 4),
            'upper': round(upper, 4),
            'lower': round(lower, 4),
            'mid': round(vwap_today, 4),
            'n': n,
            'window': len(vwaps),
            'close': close_price,
            'close_vs_vwap_pct': round(close_vs_vwap, 2),
            'close_above_upper': close_price > upper,
            'close_below_lower': close_price < lower,
        }

    def batch_calc(self, symbols: List[str], date: str,
                   n: float = None, window: int = None) -> Dict[str, Optional[Dict]]:
        """批量计算"""
        result = {}
        for sym in symbols:
            result[sym] = self.calc(sym, date, n=n, window=window)
        return result

    # ── 内部方法 ──────────────────────────────────────────

    def _fetch_window(self, symbol: str, date: str, window: int) -> List[Dict]:
        """
        获取窗口期数据（包含 date 在内共 window 天）。
        按日期降序排列，最新数据在前。

        数据来源：data_source.fetch_daily()（P1 统一入口）
        """
        from datetime import datetime, timedelta
        from src.backtest.data_source import AkshareDataSource

        ds = AkshareDataSource()

        # 向前推算起始日期，确保覆盖足够交易日
        dt = datetime.strptime(date, '%Y%m%d')
        start_dt = dt - timedelta(days=window * 2 + 10)
        start_date = start_dt.strftime('%Y%m%d')

        df = ds.fetch_daily(symbol=symbol, start_date=start_date, end_date=date, adjust="qfq")
        if df is None or df.empty:
            return []

        # 按日期降序，筛选有效行
        df = df.sort_values('date', ascending=False)
        result = []
        for _, row in df.iterrows():
            vol = row.get('volume', 0) or 0
            amt = row.get('amount', 0) or 0
            if vol > 0 and amt > 0:
                date_str = row['date']
                if hasattr(date_str, 'strftime'):
                    date_str = date_str.strftime('%Y%m%d')
                result.append({
                    'date': str(date_str),
                    'open': row.get('open'),
                    'high': row.get('high'),
                    'low': row.get('low'),
                    'close': row.get('close'),
                    'volume': vol,
                    'amount': amt,
                })
            if len(result) >= window:
                break
        return result[:window]

    @staticmethod
    def _calc_std(values: List[float]) -> float:
        """计算样本标准差（分母 N-1）"""
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        return math.sqrt(variance)


# ── P2 字段清洗辅助 ──────────────────────────────────────


def audit_p2_fields(symbol: str = None, db_path: str = None) -> Dict:
    """
    P2 字段审计：检查 amount/volume 是否异常。
    
    检查项：
      1. amount/volume = 0
      2. amount/volume NULL
      3. avg_trade_price 极端值（>10000 或 <0.01）
    """
    db_path = db_path or os.path.join(
        os.environ.get("MOZHIHOME", str(Path.home() / "mozhi_platform")),
        "data", "analysis.db"
    )
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    where_clause = "WHERE code=?" if symbol else ""

    results = {}
    checks = [
        ("total_rows", f"SELECT COUNT(*) FROM stock_daily {where_clause}"),
        ("zero_volume", f"SELECT COUNT(*) FROM stock_daily WHERE (volume IS NULL OR volume=0) {where_clause}".replace("WHERE ", "AND ") if where_clause else f"SELECT COUNT(*) FROM stock_daily WHERE volume IS NULL OR volume=0"),
        ("zero_amount", f"SELECT COUNT(*) FROM stock_daily WHERE (amount IS NULL OR amount=0) {where_clause}".replace("WHERE ", "AND ") if where_clause else f"SELECT COUNT(*) FROM stock_daily WHERE amount IS NULL OR amount=0"),
    ]

    for name, query in checks:
        if symbol and "AND " in query:
            query = query + f" AND code='{symbol}'"
        elif symbol:
            query = query.replace("WHERE code=?", f"WHERE code='{symbol}'")
        cur.execute(query)
        results[name] = cur.fetchone()[0]

    conn.close()
    return results
