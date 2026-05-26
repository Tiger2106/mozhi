"""
墨枢 - SignalComparator（R1 阶段二：任务6）

红蓝信号偏差检测。

功能：
  1. compare(old_signals, new_signals) — 每 K 线对比方向、价格、置信度
  2. 偏差 >5% 告警，>10% 自动阻断

依赖:
  - src.backtest.models.signal_types — signal_diff
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.backtest.models.signal_types import R1Signal, signal_diff


@dataclass
class ComparisonRow:
    """单根 K 线对比结果"""
    index: int
    old_direction: int
    new_direction: int
    old_price: float
    new_price: float
    old_confidence: float
    new_confidence: float
    price_deviation_pct: float
    direction_match: bool
    confidence_delta: float
    verdict: str          # "match" | "minor_deviation" | "mismatch"


@dataclass
class CompareResult:
    """偏差检测结果"""
    rows: List[ComparisonRow] = field(default_factory=list)
    total_comparisons: int = 0
    matches: int = 0
    minor_deviations: int = 0
    mismatches: int = 0
    price_deviation_pct_avg: float = 0.0
    alert_triggered: bool = False
    block_triggered: bool = False
    verdict: str = "pass"     # "pass" | "warning" | "block"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_comparisons": self.total_comparisons,
            "matches": self.matches,
            "minor_deviations": self.minor_deviations,
            "mismatches": self.mismatches,
            "price_deviation_pct_avg": round(self.price_deviation_pct_avg, 2),
            "alert_triggered": self.alert_triggered,
            "block_triggered": self.block_triggered,
            "verdict": self.verdict,
            "rows": [
                {
                    "index": r.index,
                    "old_dir": r.old_direction,
                    "new_dir": r.new_direction,
                    "old_price": round(r.old_price, 4),
                    "new_price": round(r.new_price, 4),
                    "price_dev_pct": round(r.price_deviation_pct, 2),
                    "direction_match": r.direction_match,
                    "verdict": r.verdict,
                }
                for r in self.rows
            ],
        }


# ─── 对齐新旧信号到 K 线时间轴 ──────────────────────────────

def _align_signals(
    old_signals: List[dict],
    new_signals: List[R1Signal],
) -> List[Tuple[Optional[dict], Optional[R1Signal]]]:
    """按时间对齐新旧信号（近似匹配）。

    Args:
        old_signals: 旧系统信号列表
        new_signals: 新系统信号列表

    Returns:
        List[Tuple[Optional[dict], Optional[R1Signal]]]:
            按时间顺序对齐的 (old, new) 对
    """
    # 按时间戳排序
    def _get_ts(sig) -> str:
        if isinstance(sig, dict):
            return sig.get("timestamp", "")
        return str(sig.timestamp)

    sorted_old = sorted(old_signals, key=_get_ts)
    sorted_new = sorted(new_signals, key=lambda s: str(s.timestamp))

    aligned: List[Tuple[Optional[dict], Optional[R1Signal]]] = []

    # 简单配对：按索引一一配对
    max_len = max(len(sorted_old), len(sorted_new))
    for i in range(max_len):
        old = sorted_old[i] if i < len(sorted_old) else None
        new = sorted_new[i] if i < len(sorted_new) else None
        aligned.append((old, new))

    return aligned


# ─── 主对比函数 ──────────────────────────────────────────────

def compare(
    old_signals: List[dict],
    new_signals: List[R1Signal],
) -> CompareResult:
    """红蓝信号逐对比对。

    使用 signal_diff 函数比较每一对信号的差异，聚合得出总体判断。

    Args:
        old_signals: 旧系统信号列表（dict 格式）
        new_signals: 新系统信号列表（R1Signal 格式）

    Returns:
        CompareResult: 对比结果，含 verdict / alert / block 状态
    """
    aligned = _align_signals(old_signals, new_signals)

    # 构建旧信号索引（按时间戳）
    old_by_ts: Dict[str, dict] = {}
    for sig in old_signals:
        ts = sig.get("timestamp", "")
        if ts:
            old_by_ts[ts] = sig

    rows: List[ComparisonRow] = []
    alerts = 0
    blocks = 0

    for i, (old, new) in enumerate(aligned):
        if old is None or new is None:
            continue

        # 使用 signal_diff 计算偏差
        diff = signal_diff(old, new)
        verdict = diff.get("verdict", "mismatch")
        price_dev = diff.get("price_deviation", 0.0)
        conf_delta = diff.get("confidence_delta", 0.0)
        dir_match = diff.get("direction_match", False)

        row = ComparisonRow(
            index=i,
            old_direction=int(old.get("signal_verdict", 0)),
            new_direction=new.direction,
            old_price=float(old.get("price", 0)),
            new_price=float(new.price),
            old_confidence=float(old.get("confidence", 0)),
            new_confidence=float(new.confidence),
            price_deviation_pct=price_dev,
            direction_match=dir_match,
            confidence_delta=conf_delta,
            verdict=verdict,
        )
        rows.append(row)

        # 偏差判定
        if price_dev > 10.0 or not dir_match:
            blocks += 1
        elif price_dev > 5.0:
            alerts += 1

    total = len(rows)
    matches = sum(1 for r in rows if r.verdict == "match")
    minor_d = sum(1 for r in rows if r.verdict == "minor_deviation")
    mismatches = sum(1 for r in rows if r.verdict == "mismatch")

    avg_price_dev = (
        sum(r.price_deviation_pct for r in rows) / len(rows)
        if rows else 0.0
    )

    # 判定 verdict
    if blocks > 0:
        verdict = "block"
    elif alerts > 0 or mismatches > 0:
        verdict = "warning"
    else:
        verdict = "pass"

    return CompareResult(
        rows=rows,
        total_comparisons=total,
        matches=matches,
        minor_deviations=minor_d,
        mismatches=mismatches,
        price_deviation_pct_avg=avg_price_dev,
        alert_triggered=(alerts > 0),
        block_triggered=(blocks > 0),
        verdict=verdict,
    )


# ─── 便捷函数 ────────────────────────────────────────────────

def compare_result(
    old_signals: List[dict],
    new_signals: List[R1Signal],
) -> str:
    """快速对比，返回 verdict 字符串。"""
    result = compare(old_signals, new_signals)
    return result.verdict
