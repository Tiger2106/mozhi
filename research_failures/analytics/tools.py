# -*- coding: utf-8 -*-
"""
analytics/tools.py — Q9b Meta Research 分析工具

提供研究失败记录的全量数据分析功能，包括：
  1. 按月份/季度统计 failure_type 分布
  2. 复发检测：同 strategy_id + 同 failure_type 相隔 ≥30d 视为复发
  3. 兼容 q9b_research_failures.py 的 ResearchFailuresRegistry

设计说明：
  - 数据源：research_failures/records/ 目录下的 JSON 文件
  - 引用 ResearchFailuresDB（即 ResearchFailuresRegistry）
  - 所有时间操作基于 CST (+08:00)
  - 输出标准化的 dict 数据结构，可序列化为 JSON

作者：墨衡 (moheng)
创建时间：2026-05-19 16:37 GMT+8
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from q9b_research_failures import (
    ResearchFailuresDB,
    ResearchFailureRecord,
    ResearchFailureType,
    FailureSeverity,
)


# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")
_RECORDS_DIR = Path(__file__).resolve().parent.parent / "records"


# ============================================================
# 分布统计
# ============================================================

def _split_date_key(date_str: str) -> tuple[int, int, int]:
    """从 ISO8601 日期字符串中提取 (年, 月, 日)

    可能格式：
      "2026-05-19T16:30:00+08:00"
      "2026-05-19"
      "2026-05-19T08:00:00"

    Returns
    -------
    tuple[int, int, int]
        格式化为 (year, month, day)，如果解析失败则返回 (0, 0, 0)
    """
    try:
        dt = datetime.fromisoformat(date_str)
        return (dt.year, dt.month, dt.day)
    except (ValueError, TypeError):
        pass
    # 尝试只取前 10 字符
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (dt.year, dt.month, dt.day)
    except (ValueError, TypeError):
        return (0, 0, 0)


def _month_key(year: int, month: int) -> str:
    """生成月份键值，如 '2026-05'"""
    return f"{year:04d}-{month:02d}"


def _quarter_key(year: int, month: int) -> str:
    """生成季度键值，如 '2026-Q2'"""
    q = (month - 1) // 3 + 1
    return f"{year:04d}-Q{q}"


def get_failure_type_distribution(
    registry: ResearchFailuresDB,
    *,
    period: str = "month",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    strategy_id: Optional[str] = None,
) -> dict[str, Any]:
    """按月份或季度统计 failure_type 分布

    对 ResearchFailuresRegistry 中的所有记录按时间窗口分组，
    统计每个窗口内各 failure_type 的出现频次。

    Parameters
    ----------
    registry : ResearchFailuresDB
        Q9b 研究失败数据库实例
    period : str
        时间粒度：'month' 按月统计，'quarter' 按季度统计
    start_date : str | None
        起始日期（ISO8601，可选，默认不限）
    end_date : str | None
        截止日期（ISO8601，可选，默认不限）
    strategy_id : str | None
        策略 ID 筛选（可选）

    Returns
    -------
    dict[str, Any]
        格式：
        {
            "period": "month" | "quarter",
            "total_records": int,
            "time_range": {"start": str, "end": str},
            "distribution": {
                "2026-05": {
                    "DATA_ISSUE": 3,
                    "PARAMETER_PEAK": 1,
                    ...
                },
                ...
            },
            "type_totals": {
                "DATA_ISSUE": 5,
                ...
            },
            "top_type": str,
            "generated_at": str (ISO8601)
        }
    """
    all_records = registry.query(limit=10000)

    # 时间范围过滤
    if start_date:
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=_TZ_CST)
    else:
        start_dt = None
    if end_date:
        end_dt = datetime.fromisoformat(end_date).replace(tzinfo=_TZ_CST)
    else:
        end_dt = None

    # 按 strategy 筛选
    if strategy_id:
        all_records = [r for r in all_records if r.strategy_id == strategy_id]

    # 时间范围推断
    actual_start: Optional[str] = None
    actual_end: Optional[str] = None

    # 按时间粒度分组统计
    distribution: dict[str, dict[str, int]] = {}
    type_totals: dict[str, int] = defaultdict(int)

    for record in all_records:
        year, month, day = _split_date_key(record.created_at)
        if year == 0:
            continue

        # 时间过滤
        if start_dt:
            try:
                rec_dt = datetime.fromisoformat(record.created_at)
                if rec_dt < start_dt:
                    continue
            except (ValueError, TypeError):
                pass
        if end_dt:
            try:
                rec_dt = datetime.fromisoformat(record.created_at)
                if rec_dt > end_dt:
                    continue
            except (ValueError, TypeError):
                pass

        # 更新时间范围
        if actual_start is None or record.created_at < actual_start:
            actual_start = record.created_at
        if actual_end is None or record.created_at > actual_end:
            actual_end = record.created_at

        # 按粒度构建键值
        if period == "quarter":
            key = _quarter_key(year, month)
        else:
            key = _month_key(year, month)

        ft = record.failure_type.value if isinstance(record.failure_type, ResearchFailureType) else str(record.failure_type)

        if key not in distribution:
            distribution[key] = {}
        distribution[key][ft] = distribution[key].get(ft, 0) + 1
        type_totals[ft] += 1

    # 对 distribution 内部按键值排序
    sorted_distribution = dict(sorted(distribution.items()))

    # 找出最多的类型
    top_type = max(type_totals, key=type_totals.get) if type_totals else ""

    return {
        "period": period,
        "total_records": len(all_records),
        "time_range": {
            "start": actual_start or "",
            "end": actual_end or "",
        },
        "distribution": sorted_distribution,
        "type_totals": dict(sorted(type_totals.items(), key=lambda x: -x[1])),
        "top_type": top_type,
        "generated_at": datetime.now(_TZ_CST).isoformat(),
    }


def get_severity_distribution(
    registry: ResearchFailuresDB,
) -> dict[str, int]:
    """按严重级别统计记录分布

    Parameters
    ----------
    registry : ResearchFailuresDB

    Returns
    -------
    dict[str, int]
        如 {"MAJOR": 10, "CRITICAL": 3, "MINOR": 2, "INFO": 1}
    """
    return registry.count_by_severity()


# ============================================================
# 复发检测
# ============================================================

@dataclass
class RecurrenceRecord:
    """单次复发事件记录

    Attributes
    ----------
    strategy_id : str
    failure_type : str
    first_occurrence_id : str
        首次记录的 failure_id
    first_occurrence_at : str
        首次记录时间
    recurrence_id : str
        复发记录的 failure_id
    recurrence_at : str
        复发记录时间
    gap_days : int
        两次记录时间间隔（天）
    severity : str
        复发记录的严重级别
    """
    strategy_id: str
    failure_type: str
    first_occurrence_id: str
    first_occurrence_at: str
    recurrence_id: str
    recurrence_at: str
    gap_days: int
    severity: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecurrenceResult:
    """复发检测结果

    Attributes
    ----------
    total_recurrences : int
        复发事件总数
    recurrence_rate : float
        复发率（复发的策略-类型对数 / 总策略-类型对数）
    recurrences : list[RecurrenceRecord]
        复发事件详情列表
    high_risk_strategies : list[str]
        高频复发策略列表（≥3 次复发）
    high_risk_types : list[str]
        高频复发类型列表（最易复发的 3 个类型）
    generated_at : str
    """
    total_recurrences: int
    recurrence_rate: float
    recurrences: list[RecurrenceRecord]
    high_risk_strategies: list[str]
    high_risk_types: list[str]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_recurrences": self.total_recurrences,
            "recurrence_rate": round(self.recurrence_rate, 4),
            "recurrences": [r.to_dict() for r in self.recurrences],
            "high_risk_strategies": self.high_risk_strategies,
            "high_risk_types": self.high_risk_types,
            "generated_at": self.generated_at,
        }


def detect_recurrences(
    registry: ResearchFailuresDB,
    *,
    min_gap_days: int = 30,
    strategy_id: Optional[str] = None,
    failure_type: Optional[str] = None,
) -> RecurrenceResult:
    """检测研究失败的复发模式

    复发定义：同一 strategy_id + 同一 failure_type，
    两次记录时间间隔 >= min_gap_days 天（默认 30 天）。

    Parameters
    ----------
    registry : ResearchFailuresDB
        Q9b 数据库实例
    min_gap_days : int
        最小间隔天数（默认 30）。间隔 ≥ 此值视为复发。
    strategy_id : str | None
        策略筛选（可选）
    failure_type : str | None
        类型筛选（可选）

    Returns
    -------
    RecurrenceResult
    """
    all_records = registry.query(limit=10000)

    # 筛选
    if strategy_id:
        all_records = [r for r in all_records if r.strategy_id == strategy_id]
    if failure_type:
        target_ft = failure_type
        all_records = [
            r for r in all_records
            if (r.failure_type.value if isinstance(r.failure_type, ResearchFailureType) else str(r.failure_type)) == target_ft
        ]

    # 按 (strategy_id, failure_type) 分组，按时间排序
    groups: dict[tuple[str, str], list[ResearchFailureRecord]] = defaultdict(list)
    for record in all_records:
        ft = record.failure_type.value if isinstance(record.failure_type, ResearchFailureType) else str(record.failure_type)
        groups[(record.strategy_id, ft)].append(record)

    # 对每个组内的记录按时间排序，检测复发
    recurrences: list[RecurrenceRecord] = []
    strategy_recurrence_count: dict[str, int] = defaultdict(int)
    type_recurrence_count: dict[str, int] = defaultdict(int)

    for (sid, ft), records in groups.items():
        # 按 created_at 排序（字符串排序 ISO8601 兼容）
        sorted_records = sorted(
            records,
            key=lambda r: r.created_at,
        )

        for i in range(len(sorted_records) - 1):
            first = sorted_records[i]
            second = sorted_records[i + 1]

            # 计算时间间隔（天）
            try:
                t1 = datetime.fromisoformat(first.created_at)
                t2 = datetime.fromisoformat(second.created_at)
                gap_seconds = (t2 - t1).total_seconds()
                gap_days = int(gap_seconds // 86400)
            except (ValueError, TypeError):
                continue

            if gap_days >= min_gap_days:
                recurrences.append(RecurrenceRecord(
                    strategy_id=sid,
                    failure_type=ft,
                    first_occurrence_id=first.failure_id,
                    first_occurrence_at=first.created_at,
                    recurrence_id=second.failure_id,
                    recurrence_at=second.created_at,
                    gap_days=gap_days,
                    severity=second.severity.value if isinstance(second.severity, FailureSeverity) else str(second.severity),
                ))
                strategy_recurrence_count[sid] += 1
                type_recurrence_count[ft] += 1

    # 排序：按 gap_days 降序（最近复发的排前）
    recurrences.sort(key=lambda r: r.gap_days, reverse=True)

    # 高复发策略（≥3 次）
    high_risk_strategies = sorted(
        [sid for sid, cnt in strategy_recurrence_count.items() if cnt >= 3],
    )

    # 高复发类型（最易复发的 3 个）
    sorted_types = sorted(type_recurrence_count.items(), key=lambda x: -x[1])
    high_risk_types = [ft for ft, _ in sorted_types[:3]]

    # 复发率
    total_groups = len(groups)
    recurrence_rate = len(recurrences) / total_groups if total_groups > 0 else 0.0

    return RecurrenceResult(
        total_recurrences=len(recurrences),
        recurrence_rate=recurrence_rate,
        recurrences=recurrences,
        high_risk_strategies=high_risk_strategies,
        high_risk_types=high_risk_types,
        generated_at=datetime.now(_TZ_CST).isoformat(),
    )


# ============================================================
# 综合分析报告
# ============================================================

@dataclass
class ResearchAnalyticsReport:
    """研究失败综合分析报告

    Attributes
    ----------
    registry_stats : dict
        注册表基本统计
    monthly_distribution : dict
        月度分布统计
    severity_distribution : dict
        严重级别分布
    recurrence_result : dict
        复发检测结果
    findings : list[str]
        关键发现列表（自然语言总结）
    generated_at : str
    """
    registry_stats: dict[str, Any]
    monthly_distribution: dict[str, Any]
    severity_distribution: dict[str, Any]
    recurrence_result: dict[str, Any]
    findings: list[str]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        """导出为 Markdown 格式报告"""
        lines: list[str] = [
            "# Q9b 研究失败分析报告",
            "",
            f"生成时间：{self.generated_at}",
            "",
            "---",
            "",
            "## 注册表基本统计",
            "",
            f"- 总记录数：{self.registry_stats.get('total', 0)}",
            f"- 策略覆盖数：{self.registry_stats.get('strategies', 0)}",
            f"- 未解决记录数：{self.registry_stats.get('unresolved', 0)}",
            "",
            "## 月度分布",
            "",
        ]
        dist = self.monthly_distribution.get("distribution", {})
        if dist:
            lines.append("| 月份 | 各类型分布 | 合计 |")
            lines.append("|------|-----------|------|")
            for month_key, types in sorted(dist.items()):
                total = sum(types.values())
                type_str = ", ".join(f"{ft}: {cnt}" for ft, cnt in sorted(types.items(), key=lambda x: -x[1]))
                lines.append(f"| {month_key} | {type_str} | {total} |")
        lines.append("")
        lines.append("## 严重级别分布")
        lines.append("")
        sev_dist = self.severity_distribution
        if sev_dist:
            total_sev = sum(sev_dist.values()) or 1
            lines.append("| 严重级别 | 计数 | 占比 |")
            lines.append("|----------|------|------|")
            for sev, cnt in sorted(sev_dist.items(), key=lambda x: -x[1]):
                pct = cnt / total_sev * 100
                lines.append(f"| {sev} | {cnt} | {pct:.1f}% |")
        lines.append("")
        lines.append("## 复发检测")
        lines.append("")
        rec = self.recurrence_result
        lines.append(f"- 复发事件总数：{rec.get('total_recurrences', 0)}")
        lines.append(f"- 总体复发率：{rec.get('recurrence_rate', 0):.1%}")
        lines.append(f"- 高复发策略（≥3次）：{', '.join(rec.get('high_risk_strategies', [])) or '无'}")
        lines.append(f"- 最易复发类型 TOP3：{', '.join(rec.get('high_risk_types', [])) or '无'}")
        lines.append("")
        lines.append("## 关键发现")
        lines.append("")
        for finding in self.findings:
            lines.append(f"- {finding}")
        lines.append("")
        lines.append("---")
        lines.append(f"_报告由 analytics/tools.py 自动生成于 {self.generated_at}_")
        return "\n".join(lines)


def generate_analytics_report(
    registry: ResearchFailuresDB,
) -> ResearchAnalyticsReport:
    """生成综合研究失败分析报告

    一次性聚合：月度分布、严重级别分布、复发检测。

    Parameters
    ----------
    registry : ResearchFailuresDB

    Returns
    -------
    ResearchAnalyticsReport
    """
    # 注册表基本统计
    registry_stats = {
        "total": registry.total_count(),
        "unresolved": registry.count_unresolved(),
        "strategies": len(set(
            r.strategy_id for r in registry.query(limit=10000)
        )),
    }

    # 月度分布（默认月粒度）
    monthly = get_failure_type_distribution(registry, period="month")

    # 严重级别分布
    severity = registry.count_by_severity()

    # 复发检测
    recurrences = detect_recurrences(registry)

    # 关键发现（自动生成总结）
    findings: list[str] = []

    # 总体规模
    if registry_stats["total"] == 0:
        findings.append("研究失败记录为空，暂无可分析数据。")
    else:
        findings.append(f"共 {registry_stats['total']} 条失败记录，覆盖 {registry_stats['strategies']} 个策略。")

    # 月度趋势
    dist = monthly.get("distribution", {})
    if dist:
        months = list(dist.keys())
        if len(months) >= 2:
            first = dist[months[0]]
            last = dist[months[-1]]
            first_total = sum(first.values())
            last_total = sum(last.values())
            if first_total > 0 and last_total > 0:
                trend = (last_total - first_total) / first_total
                direction = "上升" if trend > 0.05 else ("下降" if trend < -0.05 else "稳定")
                findings.append(f"失败记录趋势{direction}：从 {months[0]} ({first_total}条) 到 {months[-1]} ({last_total}条)。")

    # 复发情况
    if recurrences.total_recurrences > 0:
        findings.append(
            f"检测到 {recurrences.total_recurrences} 次复发事件，"
            f"复发率 {recurrences.recurrence_rate:.1%}。"
        )
        if recurrences.high_risk_strategies:
            findings.append(
                f"高复发策略：{', '.join(recurrences.high_risk_strategies)}"
                f"（建议重点审查这些策略的修复方案有效性）。"
            )
        if recurrences.high_risk_types:
            findings.append(
                f"最易复发的失败类型：{', '.join(recurrences.high_risk_types)}"
                f"（建议深究根因，检查修复是否触及本质）。"
            )
    else:
        findings.append("未检测到超过 30 天间隔的复发事件。")

    # 严重级别
    critical = severity.get("CRITICAL", 0)
    major = severity.get("MAJOR", 0)
    if critical > 0:
        findings.append(f"存在 {critical} 条致命（CRITICAL）记录，需要优先处理。")
    if major > 0:
        findings.append(f"存在 {major} 条重大（MAJOR）记录，建议分配资源解决。")

    # 未解决
    unresolved = registry_stats["unresolved"]
    if unresolved > 0:
        findings.append(f"有 {unresolved} 条记录未解决，占总记录的 {unresolved / max(registry_stats['total'], 1):.0%}。")

    return ResearchAnalyticsReport(
        registry_stats=registry_stats,
        monthly_distribution=monthly,
        severity_distribution=severity,
        recurrence_result=recurrences.to_dict(),
        findings=findings,
        generated_at=datetime.now(_TZ_CST).isoformat(),
    )


# ============================================================
# CLI 入口
# ============================================================

def main() -> None:
    """CLI 入口：生成研究失败分析报告并输出为 Markdown"""
    registry = ResearchFailuresDB()
    report = generate_analytics_report(registry)

    output_dir = Path(__file__).resolve().parent.parent / "analytics"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "analytics_report.md"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())

    print(f"分析报告已生成：{output_path}")
    print(f"总记录数：{report.registry_stats['total']}")
    print(f"复发事件数：{report.recurrence_result['total_recurrences']}")
    print(f"关键发现数：{len(report.findings)}")


if __name__ == "__main__":
    main()
