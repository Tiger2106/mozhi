# -*- coding: utf-8 -*-
"""
q8_failure_attribution.py — Q8 Failure Attribution Engine 失败归因引擎

分析 Q_FAILURES 数据库中记录的策略失败数据，按 failure_type 分类统计
复发频率，识别"重复失败模式"（相同 failure_type 复发 ≥2 次的策略）。

功能：
  1. 失败类型排行：各类失败出现的总次数和占比
  2. 复发检测：同一策略同一失败类型是否反复出现
  3. 策略失败画像：特定策略的失败模式分布
  4. 按市场状态聚合：不同市场状态下的失败模式差异
  5. 归因分析：组合 Q9a + 按门控/Q模块归因

作者：墨衡 (moheng)
创建时间：2026-05-19 16:22 GMT+8
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from q_failures_db import QFailuresDB, QFailureRecord, FailureType

# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class FailureTypeDistribution:
    """失败类型整体分布"""
    total_records: int
    by_type: dict[str, int]                # failure_type → count
    by_type_pct: dict[str, float]          # failure_type → percentage
    top_n: list[tuple[str, int, float]]    # [(type, count, %), ...]
    discovery_breakdown: dict[str, int]    # discovered_by → count


@dataclass
class RecurrencePattern:
    """单个复发模式"""
    strategy_id: str
    failure_type: str
    recurrence_count: int                  # 复发次数（总出现次数）
    first_seen: str
    last_seen: str
    gap_days: int                          # 首次到最后一次的天数
    average_interval_days: float           # 平均复发间隔
    records: list[QFailureRecord]          # 所有相关记录


@dataclass
class StrategyFailureSummary:
    """单策略的失败摘要"""
    strategy_id: str
    total_failures: int
    failure_types: dict[str, int]
    failure_types_pct: dict[str, float]
    recurrence_count: int                  # 复发类型数
    recurrence_types: list[str]
    gate_failures: int
    validator_failures: int


@dataclass
class FailureAttributionReport:
    """完整的归因报告"""
    generated_at: str
    total_records: int
    distribution: FailureTypeDistribution
    recurrence_patterns: list[RecurrencePattern]
    strategy_summaries: list[StrategyFailureSummary]
    top_recurrent_strategies: list[tuple[str, int]]     # (strategy_id, recurrence_count)
    top_recurrent_types: list[tuple[str, int]]           # (failure_type, recurrence_count)


# ============================================================
# 归因引擎
# ============================================================

class FailureAttributionEngine:
    """Q8 失败归因引擎

    分析 Q_FAILURES 数据库中的失败记录，提供多维度聚合分析。

    Parameters
    ----------
    db_path : str | Path | None
        数据库路径，传递给 QFailuresDB。若为 None 使用默认路径。
    """

    # 复发判定阈值
    DEFAULT_RECURRENCE_THRESHOLD = 2       # 同一类型出现 ≥ 2 次算复发
    DEFAULT_RECURRENCE_GAP_DAYS = 1        # 最小间隔天数（同一天内的多条记录不算）

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._db = QFailuresDB(db_path)
        self._db.initialize()

    @property
    def db(self) -> QFailuresDB:
        return self._db

    # ----- 失败类型分布 -----

    def compute_distribution(self) -> FailureTypeDistribution:
        """计算失败类型的整体分布

        返回各 failure_type 的出现频率、占比以及按发现者（Gate/Validator）的分解。

        Returns
        -------
        FailureTypeDistribution
        """
        records = self._db.query(limit=100000)
        total = len(records)

        by_type: dict[str, int] = {}
        by_discovery: dict[str, int] = {}

        for r in records:
            ft = r.failure_type.value if isinstance(r.failure_type, FailureType) else str(r.failure_type)
            by_type[ft] = by_type.get(ft, 0) + 1
            by_discovery[r.discovered_by] = by_discovery.get(r.discovered_by, 0) + 1

        sorted_types = sorted(by_type.items(), key=lambda x: -x[1])
        top_n = [
            (ft, cnt, round(cnt / total * 100, 2) if total > 0 else 0.0)
            for ft, cnt in sorted_types
        ]

        by_type_pct = {
            ft: round(cnt / total * 100, 2) if total > 0 else 0.0
            for ft, cnt in by_type.items()
        }

        return FailureTypeDistribution(
            total_records=total,
            by_type=by_type,
            by_type_pct=by_type_pct,
            top_n=top_n[:10],   # Top 10
            discovery_breakdown=by_discovery,
        )

    # ----- 复发检测 -----

    def detect_recurrence(
        self,
        min_occurrences: int = 2,
        min_gap_days: int = 1,
    ) -> list[RecurrencePattern]:
        """检测全库中的失败复发模式

        识别 "重复失败模式"：相同 strategy_id + 相同 failure_type 出现 ≥ min_occurrences 次。

        Parameters
        ----------
        min_occurrences : int
            至少出现多少次才算复发（默认 2）
        min_gap_days : int
            最小间隔天数（默认 1；同一天的多条记录不视为复发）

        Returns
        -------
        list[RecurrencePattern]
            所有检测到的复发模式，按 recurrence_count 降序
        """
        records = self._db.query(limit=100000)
        if len(records) < min_occurrences:
            return []

        # 按 (strategy_id, failure_type) 分组
        grouped: dict[tuple[str, str], list[QFailureRecord]] = {}
        for r in records:
            ft = r.failure_type.value if isinstance(r.failure_type, FailureType) else str(r.failure_type)
            key = (r.strategy_id, ft)
            grouped.setdefault(key, []).append(r)

        patterns: list[RecurrencePattern] = []
        for (sid, ft), recs in grouped.items():
            if len(recs) < min_occurrences:
                continue

            # 按时间排序
            sorted_recs = sorted(recs, key=lambda x: x.timestamp)
            first = sorted_recs[0]
            last = sorted_recs[-1]

            try:
                first_dt = datetime.fromisoformat(first.timestamp)
                last_dt = datetime.fromisoformat(last.timestamp)
            except (ValueError, TypeError):
                # 时间戳解析失败时跳过
                continue

            gap_days = (last_dt - first_dt).days

            # 计算平均间隔
            if len(sorted_recs) >= 2:
                intervals: list[float] = []
                for i in range(1, len(sorted_recs)):
                    try:
                        prev_dt = datetime.fromisoformat(sorted_recs[i - 1].timestamp)
                        curr_dt = datetime.fromisoformat(sorted_recs[i].timestamp)
                        intervals.append((curr_dt - prev_dt).days)
                    except (ValueError, TypeError):
                        pass
                avg_interval = sum(intervals) / len(intervals) if intervals else 0.0
            else:
                avg_interval = 0.0

            if gap_days >= min_gap_days:
                patterns.append(RecurrencePattern(
                    strategy_id=sid,
                    failure_type=ft,
                    recurrence_count=len(sorted_recs),
                    first_seen=first.timestamp,
                    last_seen=last.timestamp,
                    gap_days=gap_days,
                    average_interval_days=round(avg_interval, 1),
                    records=sorted_recs,
                ))

        # 按复发次数降序
        patterns.sort(key=lambda p: -p.recurrence_count)
        return patterns

    # ----- 策略失败画像 -----

    def strategy_summary(self, strategy_id: str) -> Optional[StrategyFailureSummary]:
        """查询特定策略的失败画像

        Parameters
        ----------
        strategy_id : str
            策略名称/ID

        Returns
        -------
        StrategyFailureSummary | None
            失败画像，无记录时返回 None
        """
        records = self._db.query(strategy_id=strategy_id)
        if not records:
            return None

        total = len(records)
        by_type: dict[str, int] = {}
        gate_failures = 0
        validator_failures = 0

        for r in records:
            ft = r.failure_type.value if isinstance(r.failure_type, FailureType) else str(r.failure_type)
            by_type[ft] = by_type.get(ft, 0) + 1

            if r.discovered_by.startswith("G"):
                gate_failures += 1
            else:
                validator_failures += 1

        by_type_pct = {
            ft: round(cnt / total * 100, 2)
            for ft, cnt in by_type.items()
        }

        # 复发类型
        recurrence_types = [
            ft for ft, cnt in by_type.items()
            if cnt >= self.DEFAULT_RECURRENCE_THRESHOLD
        ]

        return StrategyFailureSummary(
            strategy_id=strategy_id,
            total_failures=total,
            failure_types=by_type,
            failure_types_pct=by_type_pct,
            recurrence_count=len(recurrence_types),
            recurrence_types=recurrence_types,
            gate_failures=gate_failures,
            validator_failures=validator_failures,
        )

    # ----- 全库聚合报告 -----

    def generate_report(self) -> FailureAttributionReport:
        """生成完整的归因分析报告

        综合分布统计、复发检测和策略画像，生成单一报告对象。

        Returns
        -------
        FailureAttributionReport
        """
        distribution = self.compute_distribution()
        recurrence_patterns = self.detect_recurrence()

        # 对所有有记录的策略生成画像
        all_records = self._db.query(limit=100000)
        strategy_ids = sorted(set(r.strategy_id for r in all_records))

        summaries: list[StrategyFailureSummary] = []
        for sid in strategy_ids:
            summary = self.strategy_summary(sid)
            if summary is not None:
                summaries.append(summary)

        # 按复发类型聚合
        recurrence_by_type: dict[str, int] = {}
        for pat in recurrence_patterns:
            recurrence_by_type[pat.failure_type] = recurrence_by_type.get(pat.failure_type, 0) + 1

        sorted_recur_types = sorted(recurrence_by_type.items(), key=lambda x: -x[1])

        # 按策略复发数聚合
        recurrence_by_strategy: dict[str, int] = {}
        for pat in recurrence_patterns:
            recurrence_by_strategy[pat.strategy_id] = recurrence_by_strategy.get(pat.strategy_id, 0) + 1

        sorted_recur_strats = sorted(recurrence_by_strategy.items(), key=lambda x: -x[1])

        return FailureAttributionReport(
            generated_at=datetime.now(_TZ_CST).isoformat(),
            total_records=distribution.total_records,
            distribution=distribution,
            recurrence_patterns=recurrence_patterns,
            strategy_summaries=summaries,
            top_recurrent_strategies=sorted_recur_strats[:10],
            top_recurrent_types=sorted_recur_types[:10],
        )

    # ----- 导出 -----

    def export_report(self, output_path: str | Path) -> str:
        """归因报告导出为 JSON 文件

        Parameters
        ----------
        output_path : str | Path
            JSON 输出路径

        Returns
        -------
        str
            输出文件路径
        """
        report = self.generate_report()
        data = asdict(report)
        # 展开记录为可分字典
        data["recurrence_patterns"] = [
            {
                "strategy_id": p.strategy_id,
                "failure_type": p.failure_type,
                "recurrence_count": p.recurrence_count,
                "first_seen": p.first_seen,
                "last_seen": p.last_seen,
                "gap_days": p.gap_days,
                "average_interval_days": p.average_interval_days,
                "records": [r.to_dict() for r in p.records],
            }
            for p in report.recurrence_patterns
        ]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(output_path)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "FailureAttributionEngine":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
