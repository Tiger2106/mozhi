# data_pipeline.py — 数据管线（日频因子计算）
# 墨家投资室 回测管线模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.2 (P1 数据入口统一：使用 data_source.fetch_daily())
#
# 本管线基于日频数据（通过 data_source 统一接口获取）计算：
#   - FloatShareCache：流通股本缓存（Tushare）
#   - TurnoverRate：换手率
#   - VolumeRatio：量比（N=20/60）
#   - VWAPChannel：VWAP ± nσ 通道
#
# 数据来源：统一走 data_source.fetch_daily()（P1 数据入口统一）

import logging
from typing import Optional, Dict, Any, List

from ..calc.float_share_cache import FloatShareCache
from ..calc.turnover_rate import calc_turnover_rate
from ..calc.volume_ratio import calc_volume_ratio, calc_ma_volume
from ..calc.vwap_channel import VWAPChannel

logger = logging.getLogger(__name__)


class DataPipeline:
    """
    数据管线：基于日频数据的因子计算。
    
    使用方式：
        pipeline = DataPipeline()
        result = pipeline.run(symbol='601857', date='20260522')
    """

    def __init__(self, db_path: str = None):
        # db_path 保留兼容（pipeline_orchestrator 传入），已不再使用
        # 数据通过 data_source 统一获取
        self._float_cache = FloatShareCache()
        self._vwap = VWAPChannel()

    # ── 主入口 ──────────────────────────────────────────

    def run(self, symbol: str, date: str) -> Dict[str, Any]:
        """
        对该标的/日期运行所有日频因子计算。

        Args:
            symbol: 6位股票代码
            date: 日期 'YYYYMMDD'

        Returns:
            包含所有计算结果的 dict，结构见 _assemble_result
        """
        row = self._fetch_daily(symbol, date)
        if row is None:
            logger.warning("DataPipeline: no daily data for %s on %s", symbol, date)
            return self._empty_result(symbol, date)

        results = {}

        # 1. FloatShare（流通股本）
        results['float_share'] = self._calc_float_share(symbol, date)

        # 2. 换手率
        results['turnover_rate'] = self._calc_turnover_rate(row, results.get('float_share'))

        # 3. 量比
        results['volume_ratio_20'] = self._calc_volume_ratio(symbol, date, window=20)
        results['volume_ratio_60'] = self._calc_volume_ratio(symbol, date, window=60)

        # 4. VWAP 通道
        results['vwap_channel'] = self._calc_vwap_channel(symbol, date)

        return self._assemble_result(symbol, date, row, results)

    # ── 数据读取 ────────────────────────────────────────

    def _fetch_daily(self, symbol: str, date: str) -> Optional[Dict]:
        """从 data_source 统一接口读取一行日频数据"""
        from datetime import datetime, timedelta
        from src.backtest.data_source import AkshareDataSource

        ds = AkshareDataSource()
        dt = datetime.strptime(date, '%Y%m%d')
        start_dt = dt - timedelta(days=5)
        end_dt = dt + timedelta(days=1)
        start_date = start_dt.strftime('%Y%m%d')
        end_date = end_dt.strftime('%Y%m%d')

        df = ds.fetch_daily(symbol=symbol, start_date=start_date, end_date=end_date, adjust="qfq")
        if df is None or df.empty:
            return None

        # 找到目标日期所在行
        for _, row in df.iterrows():
            d = row['date']
            if hasattr(d, 'strftime'):
                d = d.strftime('%Y%m%d')
            if str(d) == date:
                return {
                    'code': symbol,
                    'date': date,
                    'open': row.get('open'),
                    'high': row.get('high'),
                    'low': row.get('low'),
                    'close': row.get('close'),
                    'volume': row.get('volume'),
                    'amount': row.get('amount'),
                }
        return None

    # ── 各因子计算 ──────────────────────────────────────

    def _calc_float_share(self, symbol: str, date: str) -> Optional[float]:
        """流通股本（万股）"""
        try:
            return self._float_cache.get(symbol, date)
        except Exception as e:
            logger.warning("FloatShare calc failed for %s %s: %s", symbol, date, e)
            return None

    def _calc_turnover_rate(self, row: Dict, float_share: Optional[float]) -> Optional[float]:
        """换手率"""
        if float_share is None or float_share <= 0:
            return None
        amount = row.get('amount') or 0
        close = row.get('close') or 0
        if amount <= 0 or close <= 0:
            return None
        try:
            return calc_turnover_rate(amount=amount, float_share=float_share, price=close)
        except Exception as e:
            logger.warning("TurnoverRate calc failed: %s", e)
            return None

    def _calc_volume_ratio(self, symbol: str, date: str, window: int = 20) -> Optional[float]:
        """量比 = 当日成交量 / N日均量（使用 data_source 统一接口）"""
        from datetime import datetime, timedelta
        from src.backtest.data_source import AkshareDataSource

        try:
            ds = AkshareDataSource()
            dt = datetime.strptime(date, '%Y%m%d')
            start_dt = dt - timedelta(days=window * 2 + 10)
            start_date = start_dt.strftime('%Y%m%d')

            df = ds.fetch_daily(symbol=symbol, start_date=start_date, end_date=date, adjust="qfq")
            if df is None or df.empty:
                return None

            df = df.sort_values('date', ascending=True)

            # 当日成交量
            target_idx = None
            for i, row in df.iterrows():
                d = row['date']
                if hasattr(d, 'strftime'):
                    d = d.strftime('%Y%m%d')
                if str(d) == date:
                    target_idx = i
                    break

            if target_idx is None:
                return None

            current_vol = float(df.loc[target_idx, 'volume'])
            if current_vol <= 0:
                return None

            # 前 N 天成交量（不含目标日期）
            before = df.loc[:target_idx].iloc[:-1]
            volumes = [float(v) for v in before['volume'].tail(window) if v and v > 0]

            ma_vol = calc_ma_volume(volumes, window=window)
            if ma_vol is None or ma_vol == 0:
                return None

            return calc_volume_ratio(current_vol, ma_vol)
        except Exception as e:
            logger.warning("VolumeRatio calc failed for %s %s: %s", symbol, date, e)
            return None

    def _calc_vwap_channel(self, symbol: str, date: str) -> Optional[Dict]:
        """VWAP 通道"""
        try:
            return self._vwap.calc(symbol, date)
        except Exception as e:
            logger.warning("VWAPChannel calc failed for %s %s: %s", symbol, date, e)
            return None

    # ── 结果组装 ────────────────────────────────────────

    def _assemble_result(self, symbol: str, date: str,
                         row: Dict, results: Dict) -> Dict[str, Any]:
        """组装为统一格式"""
        return {
            'symbol': symbol,
            'date': date,
            'pipeline': 'data',
            'close': row.get('close'),
            'volume': row.get('volume'),
            'amount': row.get('amount'),
            'factors': {
                'float_share': results.get('float_share'),
                'turnover_rate': results.get('turnover_rate'),
                'volume_ratio_20': results.get('volume_ratio_20'),
                'volume_ratio_60': results.get('volume_ratio_60'),
                'vwap_channel': results.get('vwap_channel'),
            },
        }

    def _empty_result(self, symbol: str, date: str) -> Dict[str, Any]:
        return {
            'symbol': symbol,
            'date': date,
            'pipeline': 'data',
            'error': f'No daily data for {symbol} on {date}',
            'close': None,
            'volume': None,
            'amount': None,
            'factors': {},
        }
