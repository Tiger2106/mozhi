# -*- coding: utf-8 -*-
"""
q7_rating_aggregator.py — Q7 Rating Aggregator 置信度聚合评级

聚合 Q1/Q2/Q3/Q4/Q5/Q6 六个维度的验证结果为单一标准化评级（A/B/C/D/F）。
支持两类聚合模式：
  ① 加权平均 (weighted_mean) — 各维度按权重加权调和平均
  ② 最低分否决 (lowest_veto) — 最低分维度决定最终评级（短板效应）

定位：
  Layer Q — Transverse Governance Layer（横向治理层）
  Q7 Rating Aggregator — 置信度聚合输出层

设计说明：
  - 基于 confidence_rating.py 的 ResearchConfidence 评级体系
  - Q1~Q6 各维度的评分范围均为 [0.0, 1.0]
  - 聚合逻辑在 ConfidenceAggregator 基础上扩展，支持两种模式
  - 每个维度可附带 fail_reason，聚合时汇总
  - 输出 RatingResult（复用 confidence_rating.py 的 RatingResult 类型）

数据输入方式：
  ① 直接传入维度评分字典（最常用）
  ② 指定文件路径自动读取（从 JSON/MD 文件提取评分）
  ③ 用于 Q-Gate 流水线的自动聚合

作者：墨衡 (moheng)
创建时间：2026-05-19 17:13 GMT+8
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

try:
    from src.utils.confidence_rating import (
        ResearchConfidence,
        RatingResult,
        ConfidenceAggregator,
   )
except ImportError:
    # fallback when running from within src/utils/
    from confidence_rating import (
        ResearchConfidence,
        RatingResult,
        ConfidenceAggregator,
    )


# ============================================================
# 时区
# ============================================================

_TZ_CST = timezone(timedelta(hours=8), "CST")


# ============================================================
# 常量
# ============================================================

# Q1~Q6 维度默认权重（与 ConfidenceAggregator.DEFAULT_WEIGHTS 对齐）
_DEFAULT_Q_WEIGHTS: dict[str, float] = {
    "Existence":       0.20,  # Q1: 存在性验证
    "Robustness":      0.20,  # Q2: 参数稳健性
    "Regime":          0.15,  # Q3: 市场状态适配
    "Capacity":        0.15,  # Q4: 资金容量
    "Temporal":        0.15,  # Q5: 时间稳定性
    "OOS":             0.15,  # Q6: 样本外存活
}

# 聚合模式
AGGREGATION_MODE_WEIGHTED: str = "weighted_mean"    # 加权平均（默认）
AGGREGATION_MODE_VETO: str = "lowest_veto"           # 最低分否决


# ============================================================
# 聚合结果数据类
# ============================================================

@dataclass
class QAggregationResult:
    """Q1~Q6 聚合评级完整结果

    包含聚合评级、各维度评分、瓶颈分析、聚合模式详情。

    Attributes
    ----------
    aggregate_result : RatingResult
        聚合后的评级结果（复用 confidence_rating.py 的 RatingResult）
    mode : str
        使用的聚合模式（weighted_mean / lowest_veto）
    dimension_statuses : dict[str, str]
        各维度验证状态（"PASS" / "WARN" / "FAIL"）
    dimension_fail_reasons : dict[str, str]
        各维度的失败原因
    overall_verdict : str
        整体判决（"PASS" / "WARN" / "FAIL"）
    hard_gate_failed : bool
        是否存在硬门禁未通过
    aggregation_time : str
        聚合时间戳
    """
    aggregate_result: RatingResult
    mode: str
    dimension_statuses: dict[str, str]
    dimension_fail_reasons: dict[str, str]
    overall_verdict: str
    hard_gate_failed: bool
    aggregation_time: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_result": self.aggregate_result.to_dict(),
            "mode": self.mode,
            "dimension_statuses": self.dimension_statuses,
            "dimension_fail_reasons": self.dimension_fail_reasons,
            "overall_verdict": self.overall_verdict,
            "hard_gate_failed": self.hard_gate_failed,
            "aggregation_time": self.aggregation_time,
        }

    @property
    def summary_line(self) -> str:
        """一句话摘要"""
        r = self.aggregate_result
        return (
            f"评级 {r.rating.value} (复合R={r.composite_r:.2f}) | "
            f"判决 {self.overall_verdict} | "
            f"瓶颈: {r.bottleneck_summary}"
        )


# ============================================================
# Q7 聚合器
# ============================================================

class Q7RatingAggregator:
    """Q7 置信度聚合评级器

    聚合 Q1~Q6 六个维度的验证结果，输出统一的置信度评级。

    两类聚合模式：
      weighted_mean — 加权调和平均（默认），各维度评分以权重合并
      lowest_veto  — 最低分否决，最低的维度评分决定最终评级

    Design notes:
      - weighted_mean 使用 ConfidenceAggregator.aggregate() 的加权调和平均
      - lowest_veto 在加权调和平均基础上，将结果限制为 ≤ 最低分
      - 硬门禁（Q1 存在性不通过）始终导致 F 评级
    """

    def __init__(
        self,
        weights: Optional[dict[str, float]] = None,
        mode: str = AGGREGATION_MODE_WEIGHTED,
        veto_threshold: float = 0.30,
    ):
        """
        Parameters
        ----------
        weights : dict[str, float] | None
            各维度权重，若为 None 则使用默认权重。
            权重无需归一化，计算时会自动归一化。
        mode : str
            聚合模式。可选 "weighted_mean" | "lowest_veto"
        veto_threshold : float
            否决阈值。当最低分维度评分 < 此值时，才会触发否决降级。
            默认 0.30（对应 D 评级）。
        """
        self._weights = weights or dict(_DEFAULT_Q_WEIGHTS)
        self._mode = mode
        self._veto_threshold = veto_threshold
        self._inner_aggregator = ConfidenceAggregator(weights=self._weights)

    # ---- 属性 ----

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in (AGGREGATION_MODE_WEIGHTED, AGGREGATION_MODE_VETO):
            raise ValueError(f"不支持的聚合模式: {value}（可选: {AGGREGATION_MODE_WEIGHTED}, {AGGREGATION_MODE_VETO}）")
        self._mode = value

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    # ---- 核心聚合 ----

    def aggregate(
        self,
        dimension_scores: dict[str, float],
        dimension_statuses: Optional[dict[str, str]] = None,
        dimension_fail_reasons: Optional[dict[str, str]] = None,
        hard_gate_failed: bool = False,
        fail_reasons: Optional[list[str]] = None,
    ) -> QAggregationResult:
        """聚合 Q1~Q6 维度评分为单一评级

        Parameters
        ----------
        dimension_scores : dict[str, float]
            各维度评分，key 为维度名称，value 为 [0.0, 1.0] 的评分。
            可包含任何子集，建议包含：Existence, Robustness, Regime,
            Capacity, Temporal, OOS。
        dimension_statuses : dict[str, str] | None
            各维度的验证状态（"PASS" / "WARN" / "FAIL"）。可选。
        dimension_fail_reasons : dict[str, str] | None
            各维度的失败原因。可选。
        hard_gate_failed : bool
            是否存在 C1 硬门禁未通过（默认 False）
        fail_reasons : list[str] | None
            全局失败原因列表（可选）

        Returns
        -------
        QAggregationResult
        """
        dim_statuses = dimension_statuses or {}
        dim_fail_reasons = dimension_fail_reasons or {}
        all_fail_reasons = list(fail_reasons or [])

        # ── 第1步：加权调和平均 ──
        inner_result = self._inner_aggregator.aggregate(
            dimension_scores=dimension_scores,
            hard_gate_failed=hard_gate_failed,
            fail_reasons=all_fail_reasons,
        )

        composite_r = inner_result.composite_r

        # ── 第2步：最低分否决模式 ──
        if self._mode == AGGREGATION_MODE_VETO:
            if dimension_scores:
                lowest_score = min(dimension_scores.values())
                lowest_dim = min(dimension_scores, key=dimension_scores.get)

                if lowest_score < self._veto_threshold:
                    # 触发否决：复合 R 被压制到 ≤ 最低分
                    vetoed_r = min(composite_r, lowest_score)
                    if vetoed_r < composite_r:
                        all_fail_reasons.append(
                            f"最低分否决 (模式: lowest_veto): "
                            f"维度 '{lowest_dim}' 评分 {lowest_score:.2f} "
                            f"< 阈值 {self._veto_threshold}，复合 R 从 "
                            f"{composite_r:.2f} 降至 {vetoed_r:.2f}"
                        )
                    composite_r = vetoed_r

        # ── 第3步：重新映射评级 ──
        rating = ResearchConfidence.from_composite_r(composite_r)
        rating = ResearchConfidence.F if hard_gate_failed else rating

        # ── 第4步：瓶颈维度判定 ──
        sorted_dims = sorted(
            dimension_scores.items(),
            key=lambda x: x[1],
        )
        bottleneck_count = min(3, len(sorted_dims))
        bottleneck_dimensions = [
            dim for dim, score in sorted_dims[:bottleneck_count]
            if score < 0.65  # 低于 B 级阈值才算瓶颈
        ]

        # ── 第5步：整体判决 ──
        overall_verdict = self._determine_verdict(
            rating=rating,
            hard_gate_failed=hard_gate_failed,
            dimension_scores=dimension_scores,
            dimension_statuses=dim_statuses,
        )

        aggregate_result = RatingResult(
            composite_r=round(composite_r, 4),
            rating=rating,
            bottleneck_dimensions=bottleneck_dimensions,
            dimension_scores=dimension_scores,
            hard_gate_failed=hard_gate_failed,
            fail_reasons=all_fail_reasons,
        )

        return QAggregationResult(
            aggregate_result=aggregate_result,
            mode=self._mode,
            dimension_statuses=dim_statuses,
            dimension_fail_reasons=dim_fail_reasons,
            overall_verdict=overall_verdict,
            hard_gate_failed=hard_gate_failed,
            aggregation_time=datetime.now(_TZ_CST).isoformat(),
        )

    # ---- 辅助方法 ----

    @staticmethod
    def _determine_verdict(
        rating: ResearchConfidence,
        hard_gate_failed: bool,
        dimension_scores: dict[str, float],
        dimension_statuses: dict[str, str],
    ) -> str:
        """判定整体判决"""
        if hard_gate_failed or rating == ResearchConfidence.F:
            return "FAIL"

        if rating == ResearchConfidence.D:
            return "FAIL"

        if rating == ResearchConfidence.C:
            # C 评级可以 pass，但检查是否有 WARN 维度
            has_warn = "WARN" in dimension_statuses.values()
            return "WARN" if has_warn else "PASS"

        # A 或 B 评级
        has_fail = "FAIL" in dimension_statuses.values()
        has_warn = "WARN" in dimension_statuses.values()
        if has_fail:
            return "WARN"
        if has_warn:
            return "PASS"  # 轻微警告不影响 A/B 评级
        return "PASS"

    # ---- 便捷方法 ----

    def aggregate_from_dicts(
        self,
        inputs: list[dict[str, Any]],
        score_key: str = "score",
        name_key: str = "name",
        status_key: str = "status",
        fail_reason_key: str = "fail_reason",
        hard_gate_key: str = "hard_gate_failed",
    ) -> QAggregationResult:
        """从字典列表聚合

        Parameters
        ----------
        inputs : list[dict]
            各维度结果字典列表
        score_key : str
            评分字段名
        name_key : str
            维度名字段名
        status_key : str
            状态字段名
        fail_reason_key : str
            失败原因字段名
        hard_gate_key : str
            硬门禁字段名

        Returns
        -------
        QAggregationResult
        """
        dimension_scores: dict[str, float] = {}
        dimension_statuses: dict[str, str] = {}
        dimension_fail_reasons: dict[str, str] = {}
        hard_gate_failed = False
        global_fail_reasons: list[str] = []

        for inp in inputs:
            name = inp.get(name_key, "unknown")
            score = inp.get(score_key, 0.0)
            dim_status = inp.get(status_key, "PASS")
            fail_reason = inp.get(fail_reason_key, "")
            hg = inp.get(hard_gate_key, False)

            dimension_scores[name] = float(score)
            dimension_statuses[name] = dim_status
            if fail_reason:
                dimension_fail_reasons[name] = fail_reason
                global_fail_reasons.append(fail_reason)
            if hg:
                hard_gate_failed = True

        return self.aggregate(
            dimension_scores=dimension_scores,
            dimension_statuses=dimension_statuses,
            dimension_fail_reasons=dimension_fail_reasons,
            hard_gate_failed=hard_gate_failed,
            fail_reasons=global_fail_reasons,
        )


# ============================================================
# 便捷函数（单次聚合）
# ============================================================

def aggregate_ratings(
    dimension_scores: dict[str, float],
    mode: str = AGGREGATION_MODE_WEIGHTED,
    veto_threshold: float = 0.30,
    hard_gate_failed: bool = False,
) -> QAggregationResult:
    """单次聚合 Q1~Q6 评级

    Parameters
    ----------
    dimension_scores : dict[str, float]
        各维度评分
    mode : str
        聚合模式
    veto_threshold : float
        否决阈值（lowest_veto 模式使用）
    hard_gate_failed : bool
        是否存在硬门禁未通过

    Returns
    -------
    QAggregationResult
    """
    aggregator = Q7RatingAggregator(mode=mode, veto_threshold=veto_threshold)
    return aggregator.aggregate(
        dimension_scores=dimension_scores,
        hard_gate_failed=hard_gate_failed,
    )


def aggregate_from_files(
    result_files: dict[str, str],
    *,
    mode: str = AGGREGATION_MODE_WEIGHTED,
    veto_threshold: float = 0.30,
    hard_gate_failed: bool = False,
) -> QAggregationResult:
    """从 JSON 结果文件聚合评分

    读取指定路径的 JSON 文件，提取 "confidence" 或 "score" 字段作为维度评分。

    Parameters
    ----------
    result_files : dict[str, str]
        key=维度名称, value=JSON 文件路径
    mode : str
        聚合模式
    veto_threshold : float
        否决阈值
    hard_gate_failed : bool
        是否存在硬门禁未通过

    Returns
    -------
    QAggregationResult
    """
    dimension_scores: dict[str, float] = {}
    dimension_statuses: dict[str, str] = {}

    for dim_name, filepath in result_files.items():
        if not os.path.exists(filepath):
            dimension_scores[dim_name] = 0.0
            dimension_statuses[dim_name] = "FAIL"
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 尝试提取 confidence/score/exists 字段
            score = data.get("confidence", data.get("score", data.get("exists", 0)))
            if isinstance(score, bool):
                score = 1.0 if score else 0.0
            score = float(score) if score is not None else 0.0
            score = max(0.0, min(1.0, score))

            dimension_scores[dim_name] = score
            dimension_statuses[dim_name] = "PASS" if score >= 0.50 else "WARN"

        except (json.JSONDecodeError, IOError, ValueError) as e:
            dimension_scores[dim_name] = 0.0
            dimension_statuses[dim_name] = "FAIL"

    aggregator = Q7RatingAggregator(mode=mode, veto_threshold=veto_threshold)
    return aggregator.aggregate(
        dimension_scores=dimension_scores,
        dimension_statuses=dimension_statuses,
        hard_gate_failed=hard_gate_failed,
    )


# ============================================================
# 报告格式化
# ============================================================

def format_aggregation_report(result: QAggregationResult) -> str:
    """将聚合结果格式化为完整报告文本

    Parameters
    ----------
    result : QAggregationResult

    Returns
    -------
    str
        格式化的报告文本
    """
    agg = result.aggregate_result
    lines: list[str] = [
        "=" * 60,
        "  Q7 置信度聚合评级报告",
        "=" * 60,
        f"  聚合时间:      {result.aggregation_time}",
        f"  聚合模式:      {result.mode}",
        f"  整体判决:      {result.overall_verdict}",
        f"  复合 R 值:     {agg.composite_r:.4f}",
        f"  评级等级:      {agg.rating.value} — {agg.rating.description}",
        f"  硬门禁:        {'⛔ 未通过' if agg.hard_gate_failed else '✅ 通过'}",
        f"  瓶颈维度:      {agg.bottleneck_summary}",
        "=" * 60,
        "  各维度评分:",
        f"  {'维度':<15} | {'评分':>8} | {'状态':>6} | {'瓶颈':>6}",
        "  " + "-" * 38,
    ]

    for dim_name in sorted(agg.dimension_scores.keys()):
        score = agg.dimension_scores[dim_name]
        status = result.dimension_statuses.get(dim_name, "N/A")
        is_bottleneck = dim_name in agg.bottleneck_dimensions
        bottleneck_mark = "⚠️" if is_bottleneck else ""
        lines.append(
            f"  {dim_name:<15} | {score:>8.2f} | {status:>6} | {bottleneck_mark:>6}"
        )

    if agg.fail_reasons:
        lines.extend([
            "=" * 60,
            "  失败原因:",
        ])
        for reason in agg.fail_reasons:
            lines.append(f"    • {reason}")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_aggregation_summary(result: QAggregationResult) -> str:
    """快速摘要（一行级）"""
    return result.summary_line


# ============================================================
# 批处理：来自 Q-Gate Pipeline
# ============================================================

def aggregate_pipeline(
    q_results: dict[str, Any],
    dimension_name_map: Optional[dict[str, str]] = None,
    mode: str = AGGREGATION_MODE_WEIGHTED,
    veto_threshold: float = 0.30,
) -> QAggregationResult:
    """从 Q-Gate Pipeline 输出聚合

    Parameters
    ----------
    q_results : dict[str, Any]
        key = Q 层标识（如 "q1"），value = 验证结果对象或字典
        支持的对象类型：ExistenceResult, RegimeValidationResult, CapacityResult,
        TemporalStabilityResult, RobustnessResult, OOSResult
    dimension_name_map : dict[str, str] | None
        Q 标识到维度名称的映射，默认按约定推断
    mode : str
        聚合模式
    veto_threshold : float
        否决阈值

    Returns
    -------
    QAggregationResult
    """
    DEFAULT_NAME_MAP: dict[str, str] = {
        "q1": "Existence",
        "q2": "Robustness",
        "q3": "Regime",
        "q4": "Capacity",
        "q5": "Temporal",
        "q6": "OOS",
    }
    name_map = dimension_name_map or DEFAULT_NAME_MAP

    dimension_scores: dict[str, float] = {}
    dimension_statuses: dict[str, str] = {}
    dimension_fail_reasons: dict[str, str] = {}
    hard_gate_failed = False
    global_fail_reasons: list[str] = []

    for q_key, result in q_results.items():
        dim_name = name_map.get(q_key, q_key)

        # 提取评分
        score = _extract_score(result)
        dimension_scores[dim_name] = score

        # 提取状态
        if isinstance(result, dict):
            status = result.get("status", result.get("exists", True))
            if isinstance(status, bool):
                status_str = "PASS" if status else "FAIL"
            else:
                status_str = str(status) if status else "PASS"
        else:
            # 使用 dataclass 对象
            passed = getattr(result, "passed", getattr(result, "is_stable", getattr(result, "is_capacity_ok", getattr(result, "is_oos_valid", getattr(result, "is_robust", getattr(result, "exists", None))))))
            if passed is None:
                status_str = "PASS"
            else:
                status_str = "PASS" if passed else "FAIL"

        dimension_statuses[dim_name] = status_str

        # 提取失败原因
        fail_reason = None
        if isinstance(result, dict):
            fail_reason = result.get("fail_reason", result.get("fail_reasons", None))
        else:
            fail_reason = getattr(result, "fail_reason", getattr(result, "fail_reasons", None))

        if fail_reason:
            if isinstance(fail_reason, list):
                reason_text = "; ".join(str(r) for r in fail_reason)
            else:
                reason_text = str(fail_reason)
            dimension_fail_reasons[dim_name] = reason_text
            global_fail_reasons.append(reason_text)

        # 硬门禁
        if isinstance(result, dict):
            hg = result.get("hard_gate_failed", result.get("exists", True))
            if isinstance(hg, bool) and not hg:
                hard_gate_failed = True
        else:
            exists = getattr(result, "exists", True)
            if hasattr(result, "exists") and not exists:
                hard_gate_failed = True

    aggregator = Q7RatingAggregator(mode=mode, veto_threshold=veto_threshold)
    return aggregator.aggregate(
        dimension_scores=dimension_scores,
        dimension_statuses=dimension_statuses,
        dimension_fail_reasons=dimension_fail_reasons,
        hard_gate_failed=hard_gate_failed,
        fail_reasons=global_fail_reasons,
    )


def _extract_score(result: Any) -> float:
    """从验证结果对象提取评分 [0, 1]"""
    if isinstance(result, dict):
        return float(result.get("confidence", result.get("score", 0.0)))
    # dataclass 对象
    return float(getattr(result, "confidence", getattr(result, "score", 0.0)))


# ============================================================
# 快速 PASS/FAIL 判定（门禁）
# ============================================================

def rating_passes(
    dimension_scores: dict[str, float],
    mode: str = AGGREGATION_MODE_WEIGHTED,
    min_rating: ResearchConfidence = ResearchConfidence.C,
) -> bool:
    """快速判断 Q1~Q6 聚合评级是否通过门禁

    Parameters
    ----------
    dimension_scores : dict[str, float]
        各维度评分
    mode : str
        聚合模式
    min_rating : ResearchConfidence
        最低通过的评级（默认 C）

    Returns
    -------
    bool
    """
    result = aggregate_ratings(dimension_scores, mode=mode)
    return result.aggregate_result.rating >= min_rating
