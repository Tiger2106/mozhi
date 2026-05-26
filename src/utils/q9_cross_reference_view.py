# -*- coding: utf-8 -*-
"""
q9_cross_reference_view.py — Q9b ↔ Q9a 交叉引用查询

连接 Q9a Q_FAILURES（正式审计失败）与 Q9b RESEARCH_FAILURES（全量研究失败），
提供完整的双层 Failure Registry 交叉分析能力。

能力概述：
  1. 给定 strategy_id/strategy_name，查出该策略两个数据库中的重叠/独立失败
  2. 统计 Q9a 被 Q9b 独立发现的比例（"双重覆盖率"）
  3. 筛选：按 failure_type / 时间范围 / 研究阶段
  4. 两种关联模式：
     - 显式关联：利用 Q9b 的 cross_ref_q9a 字段指向 Q9a failure_id
     - 隐式关联：利用 strategy_id == strategy_name + 类型/时间近似匹配

作者：墨萱 (moxuan)
创建时间：2026-05-19 16:38 GMT+8
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from src.utils.q_failures_db import (
    QFailuresDB,
    QFailureRecord,
    FailureType,
)
from src.utils.research_failures_schema import (
    ResearchFailuresRegistry,
    ResearchFailureRecord,
)


# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")


def _now_cst() -> datetime:
    return datetime.now(_TZ_CST)


# ============================================================
# 数据类型
# ============================================================


@dataclass
@dataclass
class CoverageStats:
    """覆盖度统计数据

    Attributes
    ----------
    explicit_matches : int
        通过 Q9b.cross_ref_q9a 显式关联的匹配数
    implicit_matches : int
        通过策略名+类型/时间隐式匹配的数
    q9a_total_in_strategy : int
        该策略在 Q9a 中的总失败记录数
    q9a_covered_count : int
        该策略中 Q9a 记录被 Q9b 独立发现的计数
    q9b_total_in_strategy : int
        该策略在 Q9b 中的总失败记录数
    """
    explicit_matches: int = 0
    implicit_matches: int = 0
    q9a_total_in_strategy: int = 0
    q9a_covered_count: int = 0
    q9b_total_in_strategy: int = 0

    @property
    def q9a_coverage_ratio(self) -> float:
        """Q9a 被 Q9b 覆盖的比例（双重覆盖率）

        分母为零时返回 0.0
        """
        if self.q9a_total_in_strategy == 0:
            return 0.0
        return self.q9a_covered_count / self.q9a_total_in_strategy


@dataclass
class MatchedPair:
    """一条 Q9a ↔ Q9b 匹配对

    Attributes
    ----------
    q9a_record : QFailureRecord
        Q9a 正式审计失败记录
    q9b_record : ResearchFailureRecord
        Q9b 研究失败记录
    match_type : str
        关联类型："explicit" (显式 cross_ref 关联) |
                      "implicit" (隐式策略+类型/时间匹配)
    match_score : float
        匹配可信度 [0.0, 1.0]，1.0 = 显式匹配
    notes : str
        匹配备注
    """
    q9a_record: QFailureRecord
    q9b_record: ResearchFailureRecord
    match_type: str = "explicit"
    match_score: float = 1.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "q9a": self.q9a_record.to_dict(),
            "q9b": self.q9b_record.to_dict(),
            "match_type": self.match_type,
            "match_score": self.match_score,
            "notes": self.notes,
        }


@dataclass
class CrossReferenceResult:
    """一次交叉引用查询的完整结果

    Attributes
    ----------
    strategy_id : str
        被查询的策略 ID / 策略名称
    matched_records : list[MatchedPair]
        两个数据库中都存在的匹配对列表
    q9a_only : list[QFailureRecord]
        仅出现在 Q9a 中的失败记录
    q9b_only : list[ResearchFailureRecord]
        仅出现在 Q9b 中的失败记录
    coverage_stats : CoverageStats
        覆盖度统计数据
    query_filters : dict
        本次查询使用的筛选条件（便于追溯）
    queried_at : str
        查询时间 ISO8601 (CST)
    """
    strategy_id: str
    matched_records: list[MatchedPair] = field(default_factory=list)
    q9a_only: list[QFailureRecord] = field(default_factory=list)
    q9b_only: list[ResearchFailureRecord] = field(default_factory=list)
    coverage_stats: CoverageStats = field(default_factory=CoverageStats)
    query_filters: dict = field(default_factory=dict)
    queried_at: str = ""

    def __post_init__(self) -> None:
        if not self.queried_at:
            self.queried_at = _now_cst().isoformat()

    @property
    def total_q9a(self) -> int:
        """Q9a 总记录数（包含匹配的 + 仅 Q9a 的）"""
        return len(self.matched_records) + len(self.q9a_only)

    @property
    def total_q9b(self) -> int:
        """Q9b 总记录数（包含匹配的 + 仅 Q9b 的）"""
        return len(self.matched_records) + len(self.q9b_only)

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典"""
        return {
            "strategy_id": self.strategy_id,
            "matched_records": [pair.to_dict() for pair in self.matched_records],
            "q9a_only": [r.to_dict() for r in self.q9a_only],
            "q9b_only": [r.to_dict() for r in self.q9b_only],
            "coverage_stats": asdict(self.coverage_stats),
            "query_filters": self.query_filters,
            "queried_at": self.queried_at,
            "total_q9a": self.total_q9a,
            "total_q9b": self.total_q9b,
        }

    def summary_text(self) -> str:
        """生成人类可读的摘要文本"""
        s = self.coverage_stats
        lines = [
            f"=== Q9b ↔ Q9a 交叉引用查询 ===",
            f"策略: {self.strategy_id}",
            f"",
            f"Q9a 正式审计失败: {self.total_q9a} 条",
            f"Q9b 研究失败记录: {self.total_q9b} 条",
            f"",
            f"--- 双重覆盖 ---",
            f"两库都有记录: {len(self.matched_records)} 条",
            f"仅 Q9a 独有: {len(self.q9a_only)} 条",
            f"仅 Q9b 独有: {len(self.q9b_only)} 条",
            f"",
            f"--- 覆盖统计 ---",
            f"显式关联 (cross_ref): {s.explicit_matches} 条",
            f"隐式关联 (策略名+类型匹配): {s.implicit_matches} 条",
            f"Q9a→Q9b 双重覆盖率: {s.q9a_coverage_ratio:.1%}",
            f"  (Q9a 中有 {s.q9a_covered_count}/{s.q9a_total_in_strategy} 条被 Q9b 独立发现)",
            f"",
        ]
        if self.query_filters:
            lines.append("--- 筛选条件 ---")
            for k, v in self.query_filters.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

@dataclass
class CrossReferenceFilters:
    """交叉引用查询筛选条件

    Parameters
    ----------
    failure_type : str | FailureType | None
        筛选特定 Q9a failure_type。若为 str，自动转为 FailureType。
        若为 "*" 或 None，不按此筛选。
    failure_type_verbose_pattern : str | None
        筛选 Q9b failure_type_verbose 关键词（LIKE '%...%' 匹配）
    time_start : str | None
        起始时间 (ISO8601)，同时约束 Q9a.timestamp 和 Q9b.discovery_date/created_at
    time_end : str | None
        截止时间 (ISO8601)
    research_phase : str | None
        研究阶段标记（可在 Q9b.notes 或 Q9a.human_notes 中标记，如 "phase1", "exploration"）
    min_confidence : float | None
        最低 confidence_before 阈值（仅对 Q9a 有 confidence_before 的记录有效）
    """
    failure_type: Optional[str | FailureType] = None
    failure_type_verbose_pattern: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    research_phase: Optional[str] = None
    min_confidence: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(d.get("failure_type"), FailureType):
            d["failure_type"] = d["failure_type"].value
        # 过滤掉 None 值
        return {k: v for k, v in d.items() if v is not None}


# ============================================================
# 控制器：单一管理两个数据库连接
# ============================================================


class Q9CrossReference:
    """Q9b ↔ Q9a 交叉引用查询控制器

    同时持有 Q9a QFailuresDB 和 Q9b ResearchFailuresRegistry 的数据库连接，
    提供跨库查询、匹配、统计功能。

    Parameters
    ----------
    db_q9a : QFailuresDB | None
        Q9a 数据库实例。默认创建。
    db_q9b : ResearchFailuresRegistry | None
        Q9b 数据库实例。默认创建。

    Examples
    --------
    >>> ref = Q9CrossReference()
    >>> result = ref.query_by_strategy("grid_601857")
    >>> print(result.summary_text())
    """

    def __init__(
        self,
        db_q9a: Optional[QFailuresDB] = None,
        db_q9b: Optional[ResearchFailuresRegistry] = None,
    ) -> None:
        self._q9a: QFailuresDB = db_q9a or QFailuresDB()
        self._q9b: ResearchFailuresRegistry = db_q9b or ResearchFailuresRegistry()

        # 确保表结构存在
        self._q9a.initialize()
        self._q9b.initialize()

    # ----------
    # 核心策略级查询
    # ----------

    def query_by_strategy(
        self,
        strategy_id: str,
        filters: Optional[CrossReferenceFilters] = None,
        implicit_match: bool = True,
    ) -> CrossReferenceResult:
        """给定 strategy_id，查询该策略在 Q9a 和 Q9b 中的交叉引用

        查询流程：
        1. 分别获取该策略在 Q9a 和 Q9b 的所有记录
        2. 通过显式关联（cross_ref_q9a == failure_id）建立匹配对
        3. 若 implicit_match=True，再尝试隐式关联
        4. 统计覆盖度

        Parameters
        ----------
        strategy_id : str
            策略 ID（对应 Q9a.strategy_id 和 Q9b.strategy_name）
        filters : CrossReferenceFilters | None
            可选筛选条件
        implicit_match : bool
            是否启用隐式匹配（默认 True）

        Returns
        -------
        CrossReferenceResult
            包含匹配对、独有记录、覆盖统计的完整结果
        """
        filters = filters or CrossReferenceFilters()
        # 展开 FailureType（若传入 str）
        ft_filter: Optional[str] = None
        ft_enum: Optional[FailureType] = None
        if filters.failure_type is not None:
            if isinstance(filters.failure_type, FailureType):
                ft_enum = filters.failure_type
                ft_filter = ft_enum.value
            else:
                ft_filter = filters.failure_type
                try:
                    ft_enum = FailureType(ft_filter)
                except ValueError:
                    pass  # 非枚举值，仅用原始字符串筛选

        # ── 获取 Q9a 记录 ──
        q9a_records = self._q9a.query(
            strategy_id=strategy_id,
            failure_type=ft_enum,
            since=filters.time_start,
            until=filters.time_end,
            limit=10000,
        )
        # 额外 confidence 筛选
        if filters.min_confidence is not None:
            q9a_records = [
                r for r in q9a_records
                if r.confidence_before is not None
                and r.confidence_before >= filters.min_confidence
            ]

        # ── 获取 Q9b 记录 ──
        q9b_records = self._q9b.query(
            strategy_name=strategy_id,
            failure_type_verbose=filters.failure_type_verbose_pattern,
            limit=10000,
        )
        # 按时间筛选 Q9b（用 discovery_date 或 created_at）
        if filters.time_start or filters.time_end:
            filtered_q9b: list[ResearchFailureRecord] = []
            for r in q9b_records:
                dt = r.discovery_date or r.created_at[:10]
                if filters.time_start and dt < filters.time_start:
                    continue
                if filters.time_end and dt > filters.time_end:
                    continue
                filtered_q9b.append(r)
            q9b_records = filtered_q9b

        # 按 research_phase 筛选（在 notes 中标记）
        if filters.research_phase:
            keyword = filters.research_phase.lower()
            q9a_records = [
                r for r in q9a_records
                if keyword in r.human_notes.lower()
            ]
            q9b_records = [
                r for r in q9b_records
                if keyword in r.notes.lower()
            ]

        # ── 构建索引（便于匹配）──
        q9a_by_id: dict[str, QFailureRecord] = {r.failure_id: r for r in q9a_records}
        q9b_by_id: dict[str, ResearchFailureRecord] = {r.failure_id: r for r in q9b_records}

        # ── Phase 1: 显式匹配（cross_ref_q9a -> Q9a.failure_id）──
        matched_pairs: list[MatchedPair] = []
        matched_q9a_ids: set[str] = set()
        matched_q9b_ids: set[str] = set()

        for q9b_rec in q9b_records:
            if q9b_rec.cross_ref_q9a and q9b_rec.cross_ref_q9a in q9a_by_id:
                q9a_rec = q9a_by_id[q9b_rec.cross_ref_q9a]
                matched_pairs.append(MatchedPair(
                    q9a_record=q9a_rec,
                    q9b_record=q9b_rec,
                    match_type="explicit",
                    match_score=1.0,
                    notes=f"显式关联: Q9b.cross_ref_q9a = {q9b_rec.cross_ref_q9a}",
                ))
                matched_q9a_ids.add(q9a_rec.failure_id)
                matched_q9b_ids.add(q9b_rec.failure_id)

        # ── Phase 2: 隐式匹配（可选）──
        if implicit_match:
            implicit_pairs = self._match_implicit(
                q9a_records, q9b_records,
                matched_q9a_ids, matched_q9b_ids,
            )
            matched_pairs.extend(implicit_pairs)
            for pair in implicit_pairs:
                matched_q9a_ids.add(pair.q9a_record.failure_id)
                matched_q9b_ids.add(pair.q9b_record.failure_id)

        # ── 分离出「仅 Q9a」和「仅 Q9b」的记录 ──
        q9a_only = [r for r in q9a_records if r.failure_id not in matched_q9a_ids]
        q9b_only = [r for r in q9b_records if r.failure_id not in matched_q9b_ids]

        # ── 统计 ──
        explicit_count = sum(1 for p in matched_pairs if p.match_type == "explicit")
        implicit_count = sum(1 for p in matched_pairs if p.match_type == "implicit")
        coverage_stats = CoverageStats(
            explicit_matches=explicit_count,
            implicit_matches=implicit_count,
            q9a_total_in_strategy=len(q9a_records),
            q9a_covered_count=len(matched_q9a_ids),
            q9b_total_in_strategy=len(q9b_records),
        )

        return CrossReferenceResult(
            strategy_id=strategy_id,
            matched_records=matched_pairs,
            q9a_only=q9a_only,
            q9b_only=q9b_only,
            coverage_stats=coverage_stats,
            query_filters=filters.to_dict(),
        )

    # ----------
    # 隐式匹配
    # ----------

    def _match_implicit(
        self,
        q9a_records: list[QFailureRecord],
        q9b_records: list[ResearchFailureRecord],
        already_matched_q9a: set[str],
        already_matched_q9b: set[str],
    ) -> list[MatchedPair]:
        """隐式匹配：通过 failure_type 和时间的近似度匹配

        匹配逻辑（按优先级）：
        1. 名称相似度：Q9b.failure_type_verbose 与 Q9a.FailureType 枚举值匹配
        2. 时间近似：发现日期与 Q9a.timestamp 在同一天 ±N 天内
        3. 综合评分：类型匹配 + 时间接近度 → match_score

        Parameters
        ----------
        q9a_records : list[QFailureRecord]
            待匹配的 Q9a 记录
        q9b_records : list[ResearchFailureRecord]
            待匹配的 Q9b 记录
        already_matched_q9a : set[str]
            已显式匹配的 Q9a failure_id 集合
        already_matched_q9b : set[str]
            已显式匹配的 Q9b failure_id 集合
        """
        pairs: list[MatchedPair] = []

        # 类型映射：Q9a 枚举值 → 常见的 Q9b.failure_type_verbose 变体
        type_mappings: dict[str, list[str]] = {
            "STATISTICAL_NOISE": [
                "STATISTICAL_NOISE", "STATISTICAL_INSUFFICIENCY",
                "NOISE", "STATISTICAL", "INSUFFICIENT_DATA",
            ],
            "PARAMETER_PEAK": [
                "PARAMETER_PEAK", "PARAMETER_OVERFIT",
                "PEAK", "OVERFIT", "PARAMETER_SENSITIVITY",
            ],
            "REGIME_BOUNDED": [
                "REGIME_BOUNDED", "REGIME_DEPENDENT",
                "REGIME", "MARKET_STATE", "STATE_DEPENDENT",
            ],
            "CAPACITY_LIMITED": [
                "CAPACITY_LIMITED", "CAPACITY", "SIZE_LIMITED",
                "LIQUIDITY", "CAPACITY_CONSTRAINT",
            ],
            "TEMPORAL_DECAY": [
                "TEMPORAL_DECAY", "TEMPORAL", "DECAY",
                "TIME_DECAY", "PERFORMANCE_DECAY",
            ],
            "OOS_FAILURE": [
                "OOS_FAILURE", "OUT_OF_SAMPLE", "OOS",
                "SAMPLE_OUT", "OOS_DEGRADATION",
            ],
            "LOW_CONFIDENCE": [
                "LOW_CONFIDENCE", "CONFIDENCE", "CONFIDENCE_LOW",
                "UNCERTAINTY", "WEAK_SIGNAL",
            ],
            "HUMAN_REJECTED": [
                "HUMAN_REJECTED", "REJECTED", "HUMAN",
                "MANUAL_REJECT", "EXPERT_REJECT",
            ],
            "EDGE_CASE": [
                "EDGE_CASE", "EDGE_CASE", "ANOMALY",
                "UNKNOWN", "OTHER",
            ],
        }

        # 剩余的 Q9a/Q9b（未匹配）
        unmatched_q9a = [r for r in q9a_records if r.failure_id not in already_matched_q9a]
        unmatched_q9b = [r for r in q9b_records if r.failure_id not in already_matched_q9b]

        for q9a_rec in unmatched_q9a:
            ft_value = q9a_rec.failure_type.value
            ft_aliases = type_mappings.get(ft_value, [ft_value])
            # 去日期前缀（仅比较 YYYY-MM-DD）
            q9a_date = q9a_rec.timestamp[:10]

            for q9b_rec in unmatched_q9b:
                if q9b_rec.failure_id in already_matched_q9b:
                    continue

                # 类型得分
                q9b_type_upper = q9b_rec.failure_type_verbose.upper().strip()
                type_score = 0.0
                if q9b_type_upper == ft_value:
                    type_score = 1.0
                else:
                    for alias in ft_aliases:
                        if alias in q9b_type_upper or q9b_type_upper in alias:
                            type_score = 0.7
                            break

                # 时间得分（同一天 = 1.0，±3天 = 0.5，更远 = 0.2）
                q9b_date = q9b_rec.discovery_date or q9b_rec.created_at[:10]
                time_score = 0.0
                if q9b_date and q9a_date:
                    try:
                        d_q9a = datetime.strptime(q9a_date, "%Y-%m-%d").date()
                        d_q9b = datetime.strptime(q9b_date[:10], "%Y-%m-%d").date()
                        diff_days = abs((d_q9b - d_q9a).days)
                        if diff_days == 0:
                            time_score = 1.0
                        elif diff_days <= 3:
                            time_score = 0.5
                        elif diff_days <= 14:
                            time_score = 0.2
                    except (ValueError, IndexError):
                        time_score = 0.0
                elif q9b_rec.cross_ref_q9a:
                    # 如果有跨库引用（即便临时指向不同 Q9a），也给基础分
                    time_score = 0.1

                # 综合评分（类型权重 0.6 + 时间权重 0.4）
                combined = type_score * 0.6 + time_score * 0.4

                # 只有得分 > 0.5 才认为匹配
                if combined > 0.5:
                    notes_parts = []
                    if type_score > 0:
                        notes_parts.append(f"类型匹配(score={type_score:.1f})")
                    if time_score > 0:
                        notes_parts.append(f"时间近似(diff_days)")
                    pairs.append(MatchedPair(
                        q9a_record=q9a_rec,
                        q9b_record=q9b_rec,
                        match_type="implicit",
                        match_score=round(combined, 3),
                        notes=f"隐式匹配: {'; '.join(notes_parts)}",
                    ))
                    already_matched_q9b.add(q9b_rec.failure_id)
                    break  # 一个 Q9a 最多配一个 Q9b

        return pairs

    # ----------
    # 批量策略查询
    # ----------

    def query_multiple_strategies(
        self,
        strategy_ids: list[str],
        filters: Optional[CrossReferenceFilters] = None,
        implicit_match: bool = True,
    ) -> dict[str, CrossReferenceResult]:
        """批量查询多个策略的交叉引用

        Parameters
        ----------
        strategy_ids : list[str]
            策略 ID 列表
        filters : CrossReferenceFilters | None
            筛选条件（所有策略共用）
        implicit_match : bool
            是否启用隐式匹配

        Returns
        -------
        dict[str, CrossReferenceResult]
            {strategy_id: CrossReferenceResult}
        """
        return {
            sid: self.query_by_strategy(sid, filters, implicit_match)
            for sid in strategy_ids
        }

    # ----------
    # 全量覆盖度报告
    # ----------

    def full_coverage_report(
        self,
        filters: Optional[CrossReferenceFilters] = None,
        implicit_match: bool = True,
        min_records: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """生成全量双层覆盖度报告（按策略汇总）

        用于回答：
        - 哪些策略的双重覆盖率高（Q9a 被 Q9b 深度验证）？
        - 哪些策略的 Q9a 记录基本未被 Q9b 关注（覆盖盲区）？

        Parameters
        ----------
        filters : CrossReferenceFilters | None
            筛选条件
        implicit_match : bool
            是否启用隐式匹配
        min_records : int
            策略最低 Q9a 记录数（过滤掉记录太少不具统计意义的策略）
        limit : int
            最多返回几个策略

        Returns
        -------
        dict:
            - report_time: str
            - strategies: list[dict] — 按 q9a_coverage_ratio 降序排列
            - overall_stats: dict — 全局汇总统计
        """
        filters = filters or CrossReferenceFilters()

        # 获取有 Q9a 记录的所有策略
        strategies_q9a: dict[str, int] = {}
        cur = self._q9a.conn.execute(
            "SELECT strategy_id, COUNT(*) AS cnt FROM q_failures GROUP BY strategy_id"
        )
        for row in cur.fetchall():
            sid = row["strategy_id"]
            cnt = row["cnt"]
            if cnt >= min_records:
                strategies_q9a[sid] = cnt

        # 获取有 Q9b 记录的所有策略
        strategies_q9b: dict[str, int] = {}
        cur = self._q9b.conn.execute(
            "SELECT strategy_name, COUNT(*) AS cnt FROM research_failures GROUP BY strategy_name"
        )
        for row in cur.fetchall():
            sid = row["strategy_name"]
            cnt = row["cnt"]
            strategies_q9b[sid] = cnt

        # 取并集（有限制）
        all_sids = list(set(list(strategies_q9a.keys()) + list(strategies_q9b.keys())))
        all_sids.sort()
        all_sids = all_sids[:limit]

        strategy_reports: list[dict] = []
        for sid in all_sids:
            result = self.query_by_strategy(sid, filters, implicit_match)
            strategy_reports.append({
                "strategy_id": sid,
                "q9a_count": result.total_q9a,
                "q9b_count": result.total_q9b,
                "matched_count": len(result.matched_records),
                "explicit_matches": result.coverage_stats.explicit_matches,
                "implicit_matches": result.coverage_stats.implicit_matches,
                "q9a_coverage_ratio": result.coverage_stats.q9a_coverage_ratio,
                "q9a_covered_count": result.coverage_stats.q9a_covered_count,
            })

        # 排序：双重覆盖率高的在前
        strategy_reports.sort(key=lambda x: (-x["q9a_coverage_ratio"], -x["q9a_count"]))

        # 全局统计
        total_strategies = len(strategy_reports)
        total_q9a = sum(r["q9a_count"] for r in strategy_reports)
        total_matched = sum(r["matched_count"] for r in strategy_reports)
        total_coverage = total_matched / total_q9a if total_q9a > 0 else 0.0
        covered_strategies = sum(1 for r in strategy_reports if r["matched_count"] > 0)

        return {
            "report_time": _now_cst().isoformat(),
            "strategies": strategy_reports,
            "overall_stats": {
                "total_strategies": total_strategies,
                "total_q9a_records": total_q9a,
                "total_matched_pairs": total_matched,
                "overall_q9a_coverage_ratio": round(total_coverage, 4),
                "strategies_with_overlap": covered_strategies,
                "strategies_without_overlap": total_strategies - covered_strategies,
                "filter": filters.to_dict(),
            },
        }

    # ----------
    # 调试/自检
    # ----------

    def check_integrity(self) -> dict[str, Any]:
        """检查双层数据库的引用完整性

        验证：
        - Q9b.cross_ref_q9a 指向的 Q9a failure_id 是否存在
        - 孤立的 cross_ref

        Returns
        -------
        dict:
            - total_cross_ref: int — Q9b 中有 cross_ref 的记录数
            - valid_cross_ref: int — 指向存在的 Q9a 记录数
            - orphaned_cross_ref: int — 指向不存在 Q9a 的记录数
            - orphaned_list: list[dict] — 孤立引用详情
        """
        q9b_with_ref = self._q9b.query(has_cross_ref=True, limit=10000)

        valid = 0
        orphaned: list[dict] = []

        for rec in q9b_with_ref:
            if rec.cross_ref_q9a:
                q9a_rec = self._q9a.get_record(rec.cross_ref_q9a)
                if q9a_rec:
                    valid += 1
                else:
                    orphaned.append({
                        "q9b_failure_id": rec.failure_id,
                        "q9b_strategy": rec.strategy_name,
                        "cross_ref_target": rec.cross_ref_q9a,
                        "status": "ORPHANED",
                    })

        return {
            "total_cross_ref": len(q9b_with_ref),
            "valid_cross_ref": valid,
            "orphaned_cross_ref": len(orphaned),
            "orphaned_list": orphaned,
            "check_time": _now_cst().isoformat(),
        }

    # ----------
    # 生命周期
    # ----------

    def close(self) -> None:
        """关闭两个数据库连接"""
        self._q9a.close()
        self._q9b.close()

    def __enter__(self) -> "Q9CrossReference":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
