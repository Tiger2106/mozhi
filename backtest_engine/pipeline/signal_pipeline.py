# signal_pipeline.py — 信号管线（分钟级因子计算）
# 墨家投资室 回测管线模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 本管线基于 stock_minute 表（分钟级数据）计算：
#   - VolumeSkewness：量偏度
#   - VolumePriceCorr：量价相关系数
#   - VolumeConcentration：量集中度（HHI / Gini）
#
# 依赖：stock_minute 表（由 collector/minute_collector.py 采集）
# 前置条件：若 stock_minute 无数据则所有因子返回 None（不阻断回测）

import logging
import sqlite3
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from ..calc.volume_skewness import (
    calc_volume_skewness_from_minute,
    classify_skewness,
)
from ..calc.volume_price_corr import (
    calc_volume_price_corr,
    classify_correlation,
)
from ..calc.volume_concentration import (
    calc_hhi,
    calc_gini_coefficient,
    classify_concentration,
)

logger = logging.getLogger(__name__)


class SignalPipeline:
    """
    信号管线：基于分钟级数据的因子计算。
    
    使用方式：
        pipeline = SignalPipeline()
        result = pipeline.run(symbol='601857', date='20260522')
    """

    def __init__(self, db_path: str = None):  # DB_UNIFY_0525
        # DB_UNIFY_0525: stock_minute 隶属行情数据，源改为 market_data.db
        self.db_path = db_path or os.path.join(
            os.environ.get("MOZHIHOME", str(Path.home() / "mozhi_platform")),
            "data", "market", "market_data.db"
        )
        # old: ...data/analysis.db  # DB_UNIFY_0525

    # ── 主入口 ──────────────────────────────────────────

    def run(self, symbol: str, date: str,
            freq: str = '5min') -> Dict[str, Any]:
        """
        对该标的/日期运行所有分钟级因子计算。

        Args:
            symbol: 6位股票代码
            date: 日期 'YYYYMMDD'
            freq: 分钟频率（默认 '5min'）

        Returns:
            包含所有计算结果 + 分类标签的 dict
        """
        minute_data = self._fetch_minute(symbol, date, freq)
        if not minute_data:
            logger.info("SignalPipeline: no minute data for %s on %s", symbol, date)
            return self._empty_result(symbol, date, 'no minute data')

        volumes = [r['volume'] for r in minute_data if r.get('volume', 0) > 0]
        prices = [r['close'] for r in minute_data if r.get('close', 0) > 0]

        if len(volumes) < 8:
            return self._empty_result(symbol, date, 'insufficient minute records')

        results = {
            'record_count': len(minute_data),
            'valid_volume_count': len(volumes),
        }

        # 1. 量偏度
        results['volume_skewness'] = self._calc_skewness(volumes)
        # 2. 量价相关系数
        results['volume_price_corr'] = self._calc_price_corr(volumes, prices)
        # 3. 量集中度
        results['volume_concentration'] = self._calc_concentration(volumes)

        return {
            'symbol': symbol,
            'date': date,
            'pipeline': 'signal',
            'freq': freq,
            'factors': results,
            'minute_record_count': len(minute_data),
        }

    # ── 数据读取 ────────────────────────────────────────

    def _fetch_minute(self, symbol: str, date: str,
                      freq: str = '5min') -> List[Dict]:
        """从 stock_minute 表读取分钟级数据（按时间升序）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """SELECT minute, open, high, low, close, volume, amount
                   FROM stock_minute
                   WHERE code=? AND date=? AND freq=?
                   ORDER BY minute ASC""",
                (symbol, date, freq)
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("Fetch minute data failed: %s", e)
            return []
        finally:
            conn.close()

    # ── 各因子计算 ──────────────────────────────────────

    def _calc_skewness(self, volumes: List[float]) -> Optional[Dict]:
        """量偏度 + 分类"""
        try:
            skew = calc_volume_skewness_from_minute(
                [{'volume': v} for v in volumes],
                vol_key='volume',
                normalize=True
            )
            if skew is not None:
                return {
                    'value': skew,
                    'label_en': classify_skewness(skew),
                    'label_cn': {
                        'early_concentrated': '早盘集中放量',
                        'slightly_early': '早盘偏多',
                        'uniform': '量能均匀',
                        'slightly_late': '尾盘偏多',
                        'late_concentrated': '尾盘集中放量',
                    }.get(classify_skewness(skew), 'unknown'),
                }
            return None
        except Exception as e:
            logger.warning("Skewness calc failed: %s", e)
            return None

    def _calc_price_corr(self, volumes: List[float],
                         prices: List[float]) -> Optional[Dict]:
        """量价相关系数 + 分类"""
        try:
            # 对齐长度（相关系数内部会做一次差分，少一个点）
            n = min(len(volumes), len(prices))
            corr = calc_volume_price_corr(volumes[:n], prices[:n])
            if corr is not None:
                return {
                    'value': corr,
                    'label_en': classify_correlation(corr),
                    'label_cn': {
                        'strong_positive': '量价强正相关（健康放量上涨）',
                        'positive': '轻度正相关',
                        'neutral': '量价分离',
                        'negative': '轻度负相关',
                        'strong_negative': '量价负相关（放量下跌/缩量上涨）',
                    }.get(classify_correlation(corr), 'unknown'),
                }
            return None
        except Exception as e:
            logger.warning("Price correlation calc failed: %s", e)
            return None

    def _calc_concentration(self, volumes: List[float]) -> Optional[Dict]:
        """量集中度（HHI + Gini）"""
        try:
            hhi = calc_hhi(volumes)
            gini = calc_gini_coefficient(volumes)
            classification = classify_concentration(hhi) if hhi is not None else None
            return {
                'hhi': hhi,
                'gini': gini,
                'classification_en': classification,
                'classification_cn': {
                    'highly_concentrated': '高度集中',
                    'moderately_concentrated': '中度集中',
                    'normal': '正常分散',
                    'uniform': '均匀分布',
                }.get(classification, 'unknown') if classification else 'unknown',
            }
        except Exception as e:
            logger.warning("Concentration calc failed: %s", e)
            return None

    # ── 结果组装 ────────────────────────────────────────

    def _empty_result(self, symbol: str, date: str,
                      reason: str) -> Dict[str, Any]:
        return {
            'symbol': symbol,
            'date': date,
            'pipeline': 'signal',
            'error': reason,
            'factors': {},
            'minute_record_count': 0,
        }
