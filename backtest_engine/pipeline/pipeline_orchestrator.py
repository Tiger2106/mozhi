# pipeline_orchestrator.py — 管线编排器
# 墨家投资室 回测管线模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# PipelineOrchestrator 将 DataPipeline 和 SignalPipeline 串联为一条完整管线，
# 供回测引擎（data_ingestion → pipeline → signal output）调用。
#
# 执行流程：
#   1. 数据管线（日频因子）— 依赖 stock_daily 表
#   2. 信号管线（分钟级因子）— 依赖 stock_minute 表（可选，无数据不阻断）
#   3. 结果合并 → 统一 dict 输出
#
# 使用方式：
#   from pipeline import run_pipeline
#   result = run_pipeline(symbol='601857', date='20260522')

import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from .data_pipeline import DataPipeline
from .signal_pipeline import SignalPipeline

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    管线编排器。
    
    统一调度两条管线，合并结果，提供错误隔离。
    """

    def __init__(self, db_path: str = None):  # DB_UNIFY_0525
        """
        DB_UNIFY_0525: 拆分 db_path 为 market_data_db（行情）和 pipeline_cache_db（缓存）。
        老路径 data/analysis.db 不再使用。
        """
        self.market_data_db = db_path or os.path.join(
            os.environ.get("MOZHIHOME", str(Path.home() / "mozhi_platform")),
            "data", "market", "market_data.db"
        )
        self.pipeline_cache_db = os.path.join(
            os.environ.get("MOZHIHOME", str(Path.home() / "mozhi_platform")),
            "data", "pipeline_cache.db"
        )
        # old: self.db_path = db_path or ...data/analysis.db  # DB_UNIFY_0525
        self.data_pipeline = DataPipeline(db_path=self.market_data_db)
        self.signal_pipeline = SignalPipeline(db_path=self.market_data_db)

    # ── 全管线运行 ──────────────────────────────────────

    def run_full(self, symbol: str, date: str,
                 include_signal: bool = True,
                 minute_freq: str = '5min') -> Dict[str, Any]:
        """
        运行完整管线（数据管线 + 信号管线）。

        Args:
            symbol: 6位股票代码
            date: 日期 'YYYYMMDD'
            include_signal: 是否包含信号管线（分钟级因子）
            minute_freq: 分钟频率

        Returns:
            {
                'symbol': '601857',
                'date': '20260522',
                'pipeline': 'full',
                'data_pipeline': {...},    # DataPipeline 结果
                'signal_pipeline': {...},   # SignalPipeline 结果（或 None）
                'factors_summary': {...},   # 平铺的因子摘要
                'error': None | str,
            }
        """
        result = {
            'symbol': symbol,
            'date': date,
            'pipeline': 'full',
            'data_pipeline': None,
            'signal_pipeline': None,
            'factors_summary': {},
            'error': None,
        }

        # Step 1: 数据管线
        try:
            data_result = self.data_pipeline.run(symbol, date)
            result['data_pipeline'] = data_result
            if data_result.get('error'):
                logger.warning("DataPipeline issue: %s", data_result['error'])
        except Exception as e:
            logger.error("DataPipeline failed: %s", e)
            result['error'] = f"DataPipeline: {e}"
            return result

        # Step 2: 信号管线（可选，不阻断）
        if include_signal:
            try:
                signal_result = self.signal_pipeline.run(symbol, date, freq=minute_freq)
                result['signal_pipeline'] = signal_result
                if signal_result.get('error'):
                    logger.info("SignalPipeline skipped: %s", signal_result['error'])
            except Exception as e:
                logger.warning("SignalPipeline failed, continuing: %s", e)
                result['signal_pipeline'] = {
                    'symbol': symbol, 'date': date,
                    'pipeline': 'signal', 'error': str(e),
                    'factors': {}, 'minute_record_count': 0,
                }

        # Step 3: 合并因子摘要
        result['factors_summary'] = self._build_factors_summary(result)

        return result

    @staticmethod
    def _build_factors_summary(result: Dict) -> Dict[str, Any]:
        """从两条管线结果中提取平铺的因子摘要"""
        summary = {}

        dp = result.get('data_pipeline', {}) or {}
        if dp.get('factors'):
            f = dp['factors']
            summary['float_share'] = f.get('float_share')
            summary['turnover_rate'] = f.get('turnover_rate')
            summary['volume_ratio_ma20'] = f.get('volume_ratio_20')
            summary['volume_ratio_ma60'] = f.get('volume_ratio_60')
            vwap = f.get('vwap_channel')
            if vwap:
                summary['vwap'] = vwap.get('vwap')
                summary['vwap_upper'] = vwap.get('upper')
                summary['vwap_lower'] = vwap.get('lower')
                summary['vwap_std'] = vwap.get('std')
                summary['close_vs_vwap_pct'] = vwap.get('close_vs_vwap_pct')
                summary['close_above_upper'] = vwap.get('close_above_upper')
                summary['close_below_lower'] = vwap.get('close_below_lower')

        sp = result.get('signal_pipeline', {}) or {}
        if sp.get('factors'):
            f = sp['factors']
            skew = f.get('volume_skewness')
            if skew:
                summary['volume_skewness'] = skew.get('value')
                summary['volume_skewness_label'] = skew.get('label_cn')
            corr = f.get('volume_price_corr')
            if corr:
                summary['volume_price_corr'] = corr.get('value')
                summary['volume_price_corr_label'] = corr.get('label_cn')
            conc = f.get('volume_concentration')
            if conc:
                summary['volume_concentration_hhi'] = conc.get('hhi')
                summary['volume_concentration_gini'] = conc.get('gini')
                summary['volume_concentration_label'] = conc.get('classification_cn')

        return summary


# ── 快捷函数 ────────────────────────────────────────────

_orchestrator: Optional[PipelineOrchestrator] = None


def get_orchestrator(db_path: str = None) -> PipelineOrchestrator:
    """获取（或创建）全局编排器实例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator(db_path=db_path)
    return _orchestrator


def run_pipeline(symbol: str, date: str,
                 include_signal: bool = True,
                 minute_freq: str = '5min',
                 db_path: str = None) -> Dict[str, Any]:
    """
    快捷入口：一键运行完整管线。

    Args:
        symbol: 6位股票代码（如 '601857'）
        date: 日期 'YYYYMMDD'
        include_signal: 是否包含分钟级信号因子
        minute_freq: 分钟频率

    Returns:
        管线运行结果 dict（含 data_pipeline / signal_pipeline / factors_summary）
    """
    orch = get_orchestrator(db_path=db_path)
    return orch.run_full(symbol, date,
                         include_signal=include_signal,
                         minute_freq=minute_freq)
