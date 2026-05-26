# -*- coding: utf-8 -*-
"""
q9a_failure_registry.py — Q9a Q_FAILURES 查询引擎与聚合统计

基于 QFailuresDB 提供高层次查询接口：
  - 按 failure_type / strategy_id / regime / 时间范围检索
  - 聚合统计：Top-N 失败类型、最近失败趋势
  - 复发检测：同一策略+同一失败类型是否重复出现

作为 "可信度审计账本 (账本B)" 的查询入口，供 Layer Q 报告、定期复盘使用。

作者：墨衡 (moheng)
创建时间：2026-05-19 16:16 GMT+8
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
# 聚合结果数据结构
# ============================================================

@dataclass
class FailureTypeStats:
    """按失败类型的聚合统计"""
    failure_type: str
    count: int
    percentage: float          # 占总记录数的百分比
    latest_timestamp: str      # 最近一次出现时间
    strategies: list[str]      # 涉及哪些策略


@dataclass
class StrategyFailureProfile:
    """单策略的失败全景"""
    strategy_id: str
    total_failures: int
    by_type: dict[str, int]    # failure_type → count
    by_regime: dict[str, int]  # regime → count
    by_gate: dict[str, int]    # discovered_by → count
    latest_failure: Optional[str]  # 最近失败时间
    has_recurring: bool         # 是否有复发记录
    recurring_types: list[str]  # 复发类型列表


@dataclass
class TrendPoint:
    """趋势数据点（用于折线图）"""
    date_bucket: str            # 日期桶（如 "2026-05-19"）
    count: int
    by_type: dict[str, int]    # 该桶内各类型计数


@dataclass
class TrendReport:
    """趋势分析报告"""
    total_records: int
    date_from: str
    date_to: str
    bucket_size_days: int
    points: list[TrendPoint]
    trend_direction: str        # "up" | "down" | "stable" | "insufficient_data"
    top_failure_types: list[FailureTypeStats]


@dataclass
class RecurrenceDetection:
    """复发检测结果"""
    strategy_id: str
    failure_type: str
    occurrences: int            # 出现次数
    first_seen: str
    last_seen: str
    gap_days: int              # 首次到最后一次间隔天数
    records: list[QFailureRecord]


# ============================================================
# 查询引擎
# ============================================================

class Q9aFailureRegistry:
    """Q9a Q_FAILURES 查询引擎

    提供对 QFailuresDB 的高层次查询与聚合分析能力。

    Parameters
    ----------
    db_path : str | Path | None
        数据库路径，传递给 QFailuresDB
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._db = QFailuresDB(db_path)
        self._db.initialize()

    # ----- 基础查询 -----

    def list_failures(
        self,
        failure_type: Optional[FailureType | str] = None,
        strategy_id: Optional[str] = None,
        regime: Optional[str] = None,
        discovered_by: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[QFailureRecord]:
        """多条件检索失败记录

        Parameters
        ----------
        failure_type : FailureType | str | None
            筛选特定失败类型
        strategy_id : str | None
            筛选特定策略
        regime : str | None
            筛选特定市场状态
        discovered_by : str | None
            筛选特定发现者
        since : str | None
            起始时间 (ISO8601)
        until : str | None
            截止时间 (ISO8601)
        limit : int
            最大返回条数 (默认 100)
        offset : int
            分页偏移

        Returns
        -------
        list[QFailureRecord]
            符合条件的记录列表
        """
        return self._db.query(
            failure_type=failure_type,
            strategy_id=strategy_id,
            regime=regime,
            discovered_by=discovered_by,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    def get_by_strategy(self, strategy_id: str, limit: int = 100) -> list[QFailureRecord]:
        """查询特定策略的所有失败记录

        Parameters
        ----------
        strategy_id : str
            策略名称/ID
        limit : int
            最大返回条数 (默认 100)

        Returns
        -------
        list[QFailureRecord]
            按时间倒序排列的记录
        """
        return self._db.query(strategy_id=strategy_id, limit=limit)

    def get_by_failure_type(self, failure_type: FailureType | str, limit: int = 100) -> list[QFailureRecord]:
        """查询特定失败类型的所有记录

        Parameters
        ----------
        failure_type : FailureType | str
            失败类型
        limit : int
            最大返回条数 (默认 100)

        Returns
        -------
        list[QFailureRecord]
            按时间倒序排列的记录
        """
        return self._db.query(failure_type=failure_type, limit=limit)

    # ----- 聚合统计 -----

    def top_failure_types(self, top_n: int = 5) -> list[FailureTypeStats]:
        """返回出现频率最高的失败类型 Top-N

        Parameters
        ----------
        top_n : int
            返回前 N 个类型 (默认 5)

        Returns
        -------
        list[FailureTypeStats]
            按计数降序排列的统计结果
        """
        total = self._db.count()
        cur = self._db.conn.execute("""
            SELECT
                failure_type,
                COUNT(*) AS cnt,
                MAX(timestamp) AS latest,
                GROUP_CONCAT(DISTINCT strategy_id) AS strategies
            FROM q_failures
            GROUP BY failure_type
            ORDER BY cnt DESC
            LIMIT ?
        """, (top_n,))

        results: list[FailureTypeStats] = []
        for row in cur.fetchall():
            pct = (row["cnt"] / total * 100) if total > 0 else 0.0
            results.append(FailureTypeStats(
                failure_type=row["failure_type"],
                count=row["cnt"],
                percentage=round(pct, 2),
                latest_timestamp=row["latest"],
                strategies=row["strategies"].split(",") if row["strategies"] else [],
            ))
        return results

    def strategy_profile(self, strategy_id: str) -> Optional[StrategyFailureProfile]:
        """查询特定策略的失败全景

        Parameters
        ----------
        strategy_id : str
            策略名称/ID

        Returns
        -------
        StrategyFailureProfile | None
            策略失败画像，若该策略无失败记录则返回 None
        """
        records = self._db.query(strategy_id=strategy_id)
        if not records:
            return None

        by_type: dict[str, int] = {}
        by_regime: dict[str, int] = {}
        by_gate: dict[str, int] = {}
        latest: Optional[str] = None

        for r in records:
            ft = r.failure_type.value if isinstance(r.failure_type, FailureType) else str(r.failure_type)
            by_type[ft] = by_type.get(ft, 0) + 1
            rg = r.regime or "unknown"
            by_regime[rg] = by_regime.get(rg, 0) + 1
            by_gate[r.discovered_by] = by_gate.get(r.discovered_by, 0) + 1
            if latest is None or r.timestamp > latest:
                latest = r.timestamp

        # 复发检测
        recurring_types = [
            ft for ft, cnt in by_type.items()
            if cnt >= 2
        ]

        return StrategyFailureProfile(
            strategy_id=strategy_id,
            total_failures=len(records),
            by_type=by_type,
            by_regime=by_regime,
            by_gate=by_gate,
            latest_failure=latest,
            has_recurring=len(recurring_types) > 0,
            recurring_types=recurring_types,
        )

    def trend_analysis(
        self,
        days: int = 30,
        bucket_size_days: int = 7,
    ) -> TrendReport:
        """时间序列趋势分析

        将指定天数内的失败记录按时间桶分组，计算每桶内的计数和类型分布，
        并评估整体趋势方向。

        Parameters
        ----------
        days : int
            回顾天数 (默认 30)
        bucket_size_days : int
            每个时间桶的天数 (默认 7)

        Returns
        -------
        TrendReport
            趋势分析报告
        """
        now = datetime.now(_TZ_CST)
        since = (now - timedelta(days=days)).isoformat()
        records = self._db.query(since=since)

        n_buckets = max(days // bucket_size_days, 1)
        buckets: list[dict[str, Any]] = []
        for i in range(n_buckets):
            bucket_end = now - timedelta(days=i * bucket_size_days)
            bucket_start = now - timedelta(days=(i + 1) * bucket_size_days)
            buckets.append({
                "start": bucket_start.isoformat(),
                "end": bucket_end.isoformat(),
                "date": bucket_end.strftime("%Y-%m-%d"),
                "count": 0,
                "by_type": {},
            })

        for r in records:
            try:
                r_ts = datetime.fromisoformat(r.timestamp)
            except (ValueError, TypeError):
                continue
            for b in buckets:
                b_start = datetime.fromisoformat(b["start"])
                b_end = datetime.fromisoformat(b["end"])
                if b_start <= r_ts < b_end:
                    b["count"] += 1
                    ft = r.failure_type.value if isinstance(r.failure_type, FailureType) else str(r.failure_type)
                    b["by_type"][ft] = b["by_type"].get(ft, 0) + 1
                    break

        # 倒序（旧→新）
        buckets.reverse()
        points = [
            TrendPoint(date_bucket=b["date"], count=b["count"], by_type=b["by_type"])
            for b in buckets
        ]

        counts = [p.count for p in points if p.count > 0]

        # 趋势方向判定
        if len(counts) < 2:
            direction = "insufficient_data"
        else:
            first_half = counts[:len(counts)//2]
            second_half = counts[len(counts)//2:]
            avg_first = sum(first_half) / len(first_half) if first_half else 0
            avg_second = sum(second_half) / len(second_half) if second_half else 0
            ratio = avg_second / avg_first if avg_first > 0 else 999
            if ratio > 1.3:
                direction = "up"
            elif ratio < 0.7:
                direction = "down"
            else:
                direction = "stable"

        # Top-N 失败类型（总览维度）
        total_count = sum(r["count"] for r in buckets)
        if total_count > 0:
            type_agg: dict[str, int] = {}
            for b in buckets:
                for ft, cnt in b["by_type"].items():
                    type_agg[ft] = type_agg.get(ft, 0) + cnt

            sorted_types = sorted(type_agg.items(), key=lambda x: -x[1])
            top_types = [
                FailureTypeStats(
                    failure_type=ft,
                    count=cnt,
                    percentage=round(cnt / total_count * 100, 2),
                    latest_timestamp="",
                    strategies=[],
                )
                for ft, cnt in sorted_types[:5]
            ]
        else:
            top_types = []

        return TrendReport(
            total_records=sum(r["count"] for r in buckets),
            date_from=buckets[0]["start"] if buckets else since,
            date_to=buckets[-1]["end"] if buckets else now.isoformat(),
            bucket_size_days=bucket_size_days,
            points=points,
            trend_direction=direction,
            top_failure_types=top_types,
        )

    def detect_recurrence(
        self,
        strategy_id: str,
        min_gap_days: int = 30,
    ) -> list[RecurrenceDetection]:
        """检测特定策略的失败复发模式

        相同 strategy_id + 相同 failure_type 在相隔 >= min_gap_days 后再次出现 = 复发。

        Parameters
        ----------
        strategy_id : str
            要检测的策略
        min_gap_days : int
            最小间隔天数才算复发 (默认 30)

        Returns
        -------
        list[RecurrenceDetection]
            复发检测结果，每个复发类型一条
        """
        records = self._db.query(strategy_id=strategy_id)
        if len(records) < 2:
            return []

        # 按 failure_type 分组
        by_type: dict[str, list[QFailureRecord]] = {}
        for r in records:
            ft = r.failure_type.value if isinstance(r.failure_type, FailureType) else str(r.failure_type)
            by_type.setdefault(ft, []).append(r)

        results: list[RecurrenceDetection] = []
        for ft, recs in by_type.items():
            if len(recs) < 2:
                continue
            # 按时间排序
            sorted_recs = sorted(recs, key=lambda x: x.timestamp)
            first = sorted_recs[0]
            last = sorted_recs[-1]
            try:
                first_dt = datetime.fromisoformat(first.timestamp)
                last_dt = datetime.fromisoformat(last.timestamp)
                gap_days = (last_dt - first_dt).days
            except (ValueError, TypeError):
                gap_days = 0

            if gap_days >= min_gap_days:
                results.append(RecurrenceDetection(
                    strategy_id=strategy_id,
                    failure_type=ft,
                    occurrences=len(sorted_recs),
                    first_seen=first.timestamp,
                    last_seen=last.timestamp,
                    gap_days=gap_days,
                    records=sorted_recs,
                ))

        return results

    def export_to_json(self, output_path: str | Path) -> None:
        """导出全量失败记录到 JSON 文件

        Parameters
        ----------
        output_path : str | Path
            JSON 输出路径
        """
        records = self._db.query(limit=100000)
        data = {
            "export_time": datetime.now(_TZ_CST).isoformat(),
            "total_records": len(records),
            "records": [r.to_dict() for r in records],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def close(self) -> None:
        """关闭数据库连接"""
        self._db.close()

    def __enter__(self) -> "Q9aFailureRegistry":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
