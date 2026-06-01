"""
分红引擎 — 双路径调和模块
===========================
路径 A: 外部数据源优先（Eastmoney/Tushare/akShare JSON）
路径 B: adj_factor 变化检测（兜底，仅定位除息日，不精确金额）
调和规则: 外部 > adj_factor，交叉验证 WARN

作者: moheng
版本: v1.0 (引擎集成 Stage 1)
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationReport:
    """双路径调和报告"""
    symbol: str
    total_external_events: int = 0
    total_adj_detected: int = 0
    matched_events: int = 0
    external_missing_events: int = 0
    amount_mismatch_events: int = 0
    unresolved_events: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def coverage(self) -> float:
        if self.total_adj_detected == 0:
            return 1.0 if self.total_external_events == 0 else 0.0
        return self.matched_events / self.total_adj_detected


def reconcile(
    external_events: Dict[str, Dict],
    adj_events: Dict[str, Dict],
    symbol: str
) -> ReconciliationReport:
    """双路径调和主函数

    对外部数据源事件和 adj_factor 检测事件进行交叉验证：
    1. 双源匹配 → 检查金额一致性（>5% 偏差则 WARN）
    2. adj_factor 独有 → WARN（需补充外部数据）
    3. 外部数据优先级最高，金额冲突时以外部值为准

    Args:
        external_events: 外部数据源事件 dict, key=date_str, value=事件信息 dict
        adj_events: adj_factor 检测事件 dict, key=date_str, value=事件信息 dict
        symbol: 证券代码，用于报告标识

    Returns:
        ReconciliationReport: 包含覆盖率和所有差异信息的调和报告

    WARN 条件:
        - adj_factor 检测到但外部无记录 → external_missing_events 计数
        - 金额偏差 > 5% → amount_mismatch_events 计数
    """
    report = ReconciliationReport(symbol=symbol)
    report.total_external_events = len(external_events)
    report.total_adj_detected = len(adj_events)
    
    all_dates = sorted(set(list(external_events.keys()) + list(adj_events.keys())))
    
    for date_str in all_dates:
        ext = external_events.get(date_str)
        adj = adj_events.get(date_str)
        
        if ext and adj:
            # 双源都有记录 → 检查一致性
            report.matched_events += 1
            ext_dps = ext.get("cash_dividend_per_share", 0) or 0
            adj_dps = adj.get("cash_dividend_per_share", 0) or 0
            
            if ext_dps > 0 and adj_dps > 0 and abs(ext_dps - adj_dps) / max(ext_dps, adj_dps) > 0.05:
                report.amount_mismatch_events += 1
                report.warnings.append(
                    f"{date_str}: 金额不一致 — 外部{ext_dps:.4f} vs adj_factor{adj_dps:.4f} "
                    "(使用外部值)"
                )
            
        elif adj and not ext:
            # adj_factor 检测到但外部无记录 → WARN
            report.external_missing_events += 1
            event_info = {
                "date": date_str,
                "source": "adj_factor_only",
                "adj_change": 1.0 - adj.get("post_adj_factor", 1.0) / max(adj.get("pre_adj_factor", 1.0), 0.001),
                "event_type": adj.get("event_type", "unknown")
            }
            report.unresolved_events.append(event_info)
            report.warnings.append(
                f"{date_str}: adj_factor检测到除息({adj.get('event_type','')}) "
                "但外部数据无记录 — 需补充外部数据源"
            )
    
    if report.external_missing_events > 0:
        logger.warning(
            f"[双路径调和] {symbol}: {report.external_missing_events}个事件缺少外部数据"
        )
    
    if report.amount_mismatch_events > 0:
        logger.warning(
            f"[双路径调和] {symbol}: {report.amount_mismatch_events}个事件金额不一致"
        )
    
    return report
