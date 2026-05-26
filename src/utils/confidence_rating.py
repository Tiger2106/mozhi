# -*- coding: utf-8 -*-
"""
confidence_rating.py — 研究置信度评分标准化

定义 ResearchConfidence 枚举体系 (A/B/C/D/F) 和评分聚合逻辑。
将各个 Q 层验证器的输出（ExistenceValidator、Regime Validator、Robustness 等）
映射到统一的标准化置信度评级。

评级体系：
  A (高置信):  0.80 ≤ R ≤ 1.00   全维度验证通过，无瓶颈
  B (中高置信): 0.65 ≤ R < 0.80   大部分维度通过，存在轻微不足
  C (中置信):   0.50 ≤ R < 0.65   存在明显过拟合风险
  D (低置信):   0.30 ≤ R < 0.50   多个维度不通过，需要复审
  F (极低置信): 0.00 ≤ R < 0.30   严重的统计或逻辑缺陷

Design Rationale (ADR-001, ADR-006):
  - 双账本系统：评级属于账本B（可信度审计），独立于账本A（收益指标）
  - 研究者不能给自己盖章 → 评级由 Q7 ConfidenceScoreAggregator 统一输出
  - A/B/C/D/F 评级与复合 R 值一起提供，避免评分标尺的随意性

作者：墨衡 (moheng)
创建时间：2026-05-19 16:17 GMT+8
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional

from q_failures_db import FailureType
from existence_validator import ExistenceResult


# ============================================================
# 枚举定义
# ============================================================

class ResearchConfidence(enum.Enum):
    """研究置信度评级 (A/B/C/D/F)

    遵循严格单调递减的顺序，F < D < C < B < A。
    用于比较运算符 __lt__, __le__, __gt__, __ge__。

    Examples
    --------
    >>> ResearchConfidence.A > ResearchConfidence.C
    True
    >>> ResearchConfidence.F < ResearchConfidence.D
    True
    """
    A = "A"   # 高置信 — 80%+
    B = "B"   # 中高置信 — 65%+
    C = "C"   # 中置信 — 50%+（存在明显过拟合风险）
    D = "D"   # 低置信 — 30%+（需要复审）
    F = "F"   # 极低置信 — <30%

    def __lt__(self, other: "ResearchConfidence") -> bool:
        order = ["F", "D", "C", "B", "A"]
        return order.index(self.value) < order.index(other.value)

    def __le__(self, other: "ResearchConfidence") -> bool:
        return self == other or self < other

    def __gt__(self, other: "ResearchConfidence") -> bool:
        return not self <= other

    def __ge__(self, other: "ResearchConfidence") -> bool:
        return not self < other

    @property
    def description(self) -> str:
        """返回中文描述"""
        descriptions = {
            "A": "高置信度 — 全维度验证通过，无瓶颈",
            "B": "中高置信度 — 大部分维度通过，存在轻微不足",
            "C": "中置信度 — 存在明显过拟合风险",
            "D": "低置信度 — 多个维度不通过，需要复审",
            "F": "极低置信度 — 严重统计或逻辑缺陷，不适合上线",
        }
        return descriptions[self.value]

    @classmethod
    def from_composite_r(cls, r_value: float) -> "ResearchConfidence":
        """从复合 R 值映射到评级

        Parameters
        ----------
        r_value : float
            复合 R 值，范围 [0.0, 1.0]

        Returns
        -------
        ResearchConfidence
            对应的评级
        """
        if r_value >= 0.80:
            return cls.A
        elif r_value >= 0.65:
            return cls.B
        elif r_value >= 0.50:
            return cls.C
        elif r_value >= 0.30:
            return cls.D
        else:
            return cls.F


# ============================================================
# 评级结果数据类
# ============================================================

@dataclass
class RatingResult:
    """完整的评级结果

    包含复合 R 值、等级评级、瓶颈维度列表、各维度评分明细。
    用作 Q7 ConfidenceScoreAggregator 的标准输出格式。

    Attributes
    ----------
    composite_r : float
        复合 R 值 [0.0, 1.0]
    rating : ResearchConfidence
        标准评级 A/B/C/D/F
    bottleneck_dimensions : list[str]
        瓶颈维度列表（评分最低的维度），如 ["Regime Consistency", "Robustness"]
    dimension_scores : dict[str, float]
        各维度评分明细，如 {"Existence": 0.85, "Robustness": 0.32, ...}
    hard_gate_failed : bool
        是否存在硬门禁未通过（如 C1 最小交易数不足）
    fail_reasons : list[str]
        所有失败原因列表
    """
    composite_r: float
    rating: ResearchConfidence
    bottleneck_dimensions: list[str] = field(default_factory=list)
    dimension_scores: dict[str, float] = field(default_factory=dict)
    hard_gate_failed: bool = False
    fail_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典"""
        return {
            "composite_r": self.composite_r,
            "rating": self.rating.value,
            "rating_description": self.rating.description,
            "bottleneck_dimensions": self.bottleneck_dimensions,
            "dimension_scores": self.dimension_scores,
            "hard_gate_failed": self.hard_gate_failed,
            "fail_reasons": self.fail_reasons,
        }

    @property
    def is_passable(self) -> bool:
        """是否可通过门禁

        Returns
        -------
        bool
            True 表示评级为 C 及以上（非 D 和 F）
        """
        return self.rating >= ResearchConfidence.C and not self.hard_gate_failed

    @property
    def bottleneck_summary(self) -> str:
        """瓶颈摘要（一句话）

        Returns
        -------
        str
            如 "瓶颈: Robustness (0.32) + Regime Consistency (0.12)"
        """
        if not self.bottleneck_dimensions or not self.dimension_scores:
            return "无显著瓶颈"
        parts = []
        for dim in self.bottleneck_dimensions[:3]:
            score = self.dimension_scores.get(dim, 0.0)
            parts.append(f"{dim} ({score:.2f})")
        return f"瓶颈: {' + '.join(parts)}"


# ============================================================
# 评分聚合逻辑
# ============================================================

class ConfidenceAggregator:
    """置信度评分聚合器（Q7 原型）

    汇聚各 Q 层验证器的输出，计算复合 R 值和评级。

    Design notes:
      - 复合 R = weighted harmonic mean（加权调和平均），
        确保任一维度过低都会显著压低总分（模拟短板效应）。
      - 硬门禁 (hard_gate) 不通过时，复合 R 被限制 ≤ 0.30 (F 评级)。
      - 瓶颈维度 = 评分最低的 1~3 个维度。
    """

    # 默认权重分布（6 维评分 → 复合 R）
    DEFAULT_WEIGHTS: dict[str, float] = {
        "Existence":       0.20,  # Q1: 存在性验证
        "Robustness":      0.20,  # Q2: 参数稳健性
        "Regime":          0.15,  # Q3: 市场状态适配
        "Capacity":        0.15,  # Q4: 资金容量
        "Temporal":        0.15,  # Q5: 时间稳定性
        "OOS":             0.15,  # Q6: 样本外存活
    }

    def __init__(self, weights: Optional[dict[str, float]] = None) -> None:
        """
        Parameters
        ----------
        weights : dict[str, float] | None
            各维度权重，若为 None 则使用 DEFAULT_WEIGHTS。
            权重无需归一化，计算时会自动归一化。
        """
        self._weights = weights or dict(self.DEFAULT_WEIGHTS)

    def aggregate(
        self,
        dimension_scores: dict[str, float],
        hard_gate_failed: bool = False,
        fail_reasons: list[str] | None = None,
    ) -> RatingResult:
        """计算复合 R 值和评级

        使用加权调和平均 (weighted harmonic mean) 聚合各维度评分。

        Parameters
        ----------
        dimension_scores : dict[str, float]
            各维度评分，key 为维度名称，value 为 [0.0, 1.0] 的评分。
            至少需包含 Existence 维度。
        hard_gate_failed : bool
            是否存在 C1 硬门禁未通过（默认 False）
        fail_reasons : list[str] | None
            失败原因列表（可选）

        Returns
        -------
        RatingResult

        Raises
        ------
        ValueError
            dimension_scores 为空或不包含 Existence 维度
        """
        if not dimension_scores:
            raise ValueError("dimension_scores 为空，无法聚合评分")

        # 硬门禁：若存在 C1 硬门禁未通过，复合 R ≤ 0.30
        if hard_gate_failed:
            r_value = min(dimension_scores.get("Existence", 0.0), 0.30)
            rating = ResearchConfidence.F
        else:
            # 加权调和平均
            numerator = 0.0
            denominator = 0.0
            valid_scores: list[tuple[str, float, float]] = []

            total_weight = sum(self._weights.values())
            if total_weight <= 0:
                raise ValueError("权重总和必须 > 0")

            for dim, score in dimension_scores.items():
                w = self._weights.get(dim, 0.0) / total_weight
                if score > 0:
                    numerator += w
                    denominator += w / score
                    valid_scores.append((dim, score, w))
                # score = 0 时该维度权重不参与平均数计算（避免除零）

            if denominator > 0:
                r_value = numerator / denominator
            else:
                # 所有维度都为 0
                r_value = 0.0

            # 限制范围
            r_value = max(0.0, min(1.0, r_value))
            rating = ResearchConfidence.from_composite_r(r_value)

        # 瓶颈维度：评分最低的维度
        sorted_dims = sorted(
            dimension_scores.items(),
            key=lambda x: x[1],
        )
        bottleneck_count = min(3, len(sorted_dims))
        bottleneck_dimensions = [
            dim for dim, score in sorted_dims[:bottleneck_count]
            if score < 0.65  # 低于 B 级阈值才算瓶颈
        ]

        return RatingResult(
            composite_r=round(r_value, 4),
            rating=rating,
            bottleneck_dimensions=bottleneck_dimensions,
            dimension_scores=dimension_scores,
            hard_gate_failed=hard_gate_failed,
            fail_reasons=fail_reasons or [],
        )

    def from_existence_result(self, er: ExistenceResult) -> float:
        """从 ExistenceResult 计算存在性置信度（评分）

        将 ExistenceResult.confidence 直接映射为 Existence 维度的评分。
        若 ExistenceResult.exists == False，标记 hard_gate_failed。

        Parameters
        ----------
        er : ExistenceResult
            ExistenceValidator 的输出

        Returns
        -------
        float
            Existence 维度的评分 [0.0, 1.0]
        """
        return er.confidence

    @staticmethod
    def existence_to_rating(er: ExistenceResult) -> RatingResult:
        """将 ExistenceValidator 输出映射到完整评级

        这是从 Phase 0a 输出到 Phase 0b 评级的直接桥梁。
        当仅存在性验证可用时（Phase 0a MVP），使用此方法
        为策略提供初步的置信度评级。

        Parameters
        ----------
        er : ExistenceResult

        Returns
        -------
        RatingResult
            仅基于 Existence 维度的评级
        """
        aggregator = ConfidenceAggregator()
        return aggregator.aggregate(
            dimension_scores={"Existence": er.confidence},
            hard_gate_failed=not er.exists,
            fail_reasons=er.fail_reasons,
        )


# ============================================================
# FailureType ↔ 评级映射
# ============================================================

def failure_type_to_impact(failure_type: FailureType) -> tuple[float, str]:
    """失败类型 → 复合 R 影响幅度 + 描述

    不同的失败类型对复合 R 的影响权重不同。
    用于 Q9a Q_FAILURES 记录中的置信度变化评估。

    Parameters
    ----------
    failure_type : FailureType
        失败类型枚举

    Returns
    -------
    tuple[float, str]
        (impact_factor, description)
        impact_factor 范围 [0.0, 1.0]：1.0 表示完全归零，0.3 表示轻微影响
    """
    impact_map = {
        FailureType.STATISTICAL_NOISE:  (1.0, "统计噪声 → 复合 R 归零 (F)"),
        FailureType.PARAMETER_PEAK:     (0.6, "参数尖峰 → 复合 R 降至 D 级"),
        FailureType.REGIME_BOUNDED:     (0.5, "单一市场状态有效 → 复合 R 降至 D/C 边缘"),
        FailureType.CAPACITY_LIMITED:   (0.4, "资金容量不足 → 复合 R 降一档"),
        FailureType.TEMPORAL_DECAY:     (0.5, "时间漂移 → 复合 R 降至 C 以下"),
        FailureType.OOS_FAILURE:        (0.8, "样本外失效 → 复合 R 降至 D/F"),
        FailureType.LOW_CONFIDENCE:     (0.3, "综合置信度不足 → 复核"),
        FailureType.HUMAN_REJECTED:     (0.9, "人工复审不通过 → 复合 R 几乎归零"),
        FailureType.EDGE_CASE:          (0.5, "未分类异常 → 需人工判定"),
    }
    return impact_map.get(failure_type, (0.5, "未识别的失败类型"))
