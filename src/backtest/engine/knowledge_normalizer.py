"""
mozhi_platform.src.backtest.engine.knowledge_normalizer — 知识标准化器

Phase 1a 核心产出：将不同策略的异构参数转为统一命名空间。

核心职责：
  1. 参数标准化：不同策略的同语义参数统一命名
  2. 市场状态标记：基于波动率水平的自动 regime 判定
  3. 多维标签生成：基于 method_name + params 自动打标
  4. quality_score 计算：样本数 × 回测长度 × 稳定性加权

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import logging
from typing import Any

from backtest.engine.knowledge_entry import KnowledgeEntry

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# KnowledgeNormalizer
# ──────────────────────────────────────────────────────────────────────


class KnowledgeNormalizer:
    """知识标准化器。

    将不同方法的异构参数映射到统一命名空间，
    自动生成市场状态标签、多维标签和质量评分。

    Examples:
        >>> n = KnowledgeNormalizer()
        >>> entry = KnowledgeEntry(
        ...     task_id="t1", method_name="ma_cross", symbol="601857",
        ...     completed_time="2026-01-01T00:00:00+08:00",
        ...     parameters={"period": 20, "ma_fast": 5, "ma_slow": 20},
        ... )
        >>> result = n.normalize(entry)
        >>> result.normalized_params["strategy_type"]
        'trend_following'
        >>> result.quality_score >= 0.0
        True
    """

    # 策略名称 → 策略大类映射
    STRATEGY_MAP: dict[str, str] = {
        "ma_cross": "trend_following",
        "macd": "trend_following",
        "bollinger": "mean_reversion",
        "rsi": "mean_reversion",
        "kdj": "mean_reversion",
        "bias": "mean_reversion",
        "grid": "grid",
        "reversal": "mean_reversion",
        "volume_profile": "volume_based",
        "wyckoff": "volume_based",
    }

    # 统一参数名 → (适用方法名列表, 源参数字段名)
    PARAM_MAP: dict[str, tuple[list[str], str]] = {
        "period": (["ma_cross", "bollinger", "volume_profile"], "period"),
        "fast_period": (["macd", "kdj"], "fast_period"),
        "slow_period": (["macd", "kdj"], "slow_period"),
        "spacing": (["grid"], "grid_spacing"),
        "grid_levels": (["grid"], "levels"),
        "cooling_bars": (["reversal"], "cooling_bars"),
    }

    def normalize(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        """对知识条目执行标准化。

        填充以下字段：
          - normalized_params: 策略类型 + 标准化参数
          - tags: 自动生成的标签
          - regime: 市场状态（基于 parameters 推测）
          - quality_score: 自动评分

        Args:
            entry: 待标准化的 KnowledgeEntry。

        Returns:
            KnowledgeEntry: 标准化后的条目（就地修改）。
        """
        # 1. 参数标准化
        normalized = self._normalize_params(entry.method_name, entry.parameters)
        entry.normalized_params = normalized

        # 2. 市场状态标记（基于现有数据推测）
        if not entry.regime:
            # 无外部 provider 时默认为 unknown
            entry.regime = "unknown"

        # 3. 标签生成
        entry.tags = self._generate_tags(entry)

        # 4. 质量评分
        entry.quality_score = self._compute_quality_score(entry)

        return entry

    # ─── 参数标准化 ────────────────────────────────────────────

    def _normalize_params(
        self,
        method_name: str,
        raw_params: dict[str, Any],
    ) -> dict[str, Any]:
        """将原始参数映射为标准化参数字典。

        Args:
            method_name: 方法名。
            raw_params: 原始参数快照。

        Returns:
            dict: 标准化参数字典，包含：
              - strategy_type: 策略大类
              - 各标准化字段（取决于方法类型）
              - _original_keys: 原始参数 key 列表（调试用）
        """
        strategy_type = self.STRATEGY_MAP.get(method_name, "unknown")

        result: dict[str, Any] = {
            "strategy_type": strategy_type,
            "_original_keys": list(raw_params.keys()),
        }

        # 遍历 PARAM_MAP，提取当前方法适用的字段
        for unified_name, (method_names, source_key) in self.PARAM_MAP.items():
            if method_name in method_names:
                value = raw_params.get(source_key)
                if value is not None:
                    result[unified_name] = value
                # 值不存在时不填充，不报错

        return result

    # ─── 市场状态检测 ──────────────────────────────────────────

    def _detect_regime(self, vix_level: float) -> str:
        """基于波动率水平判断市场状态。

        Args:
            vix_level: VIX 或等效波动率水平。

        Returns:
            str: bull / bear / sideways / volatile。
        """
        if vix_level > 30:
            return "volatile"
        if vix_level > 20:
            return "sideways"
        if vix_level > 12:
            return "bull"
        # vix_level <= 12
        return "bull"

    # ─── 质量评分 ──────────────────────────────────────────────

    def _compute_quality_score(self, entry: KnowledgeEntry) -> float:
        """计算知识条目的质量评分。

        评分公式：
          base = 0.5
          + data_coverage: 基于 parameters 中可能存在的周期信息
          + confidence 贡献: entry.confidence 的折半加权
          结果截断至 [0.05, 0.95]。

        质量评分与 confidence 的关系：
          - confidence: 单次回测的置信度（先验，KnowledgeBridge 计算）
          - quality_score: 结构化的质量评价（后验，含稳定性）
          - 两者独立但不冲突，Bitable 中均可展示

        Args:
            entry: 知识条目。

        Returns:
            float: [0.05, 0.95] 范围内的质量评分。
        """
        base = 0.5

        # 参数信息评分：有参数 +0.1，参数较多 +0.05
        if entry.parameters:
            base += 0.1
            if len(entry.parameters) >= 5:
                base += 0.05

        # 标签信息评分
        if entry.regime and entry.regime != "unknown":
            base += 0.05

        # confidence 折半贡献（quality_score 侧重稳定性，不全盘借用）
        base += entry.confidence * 0.3

        # 有 insight_summary 加分
        if entry.insight_summary:
            base += 0.03

        return max(0.05, min(0.95, base))

    # ─── 标签生成 ──────────────────────────────────────────────

    def _generate_tags(self, entry: KnowledgeEntry) -> list[str]:
        """根据方法名和参数自动生成多维标签。

        标签层级：
          1. 策略类型: trend / grid / mean_reversion / volume_based
          2. 技术因子: ma / macd / rsi / vwap / bollinger / volume
          3. 风格: short_term / mid_term / long_term

        Args:
            entry: 知识条目。

        Returns:
            list[str]: 标签列表（已去重）。
        """
        tags: list[str] = []
        method = entry.method_name
        params = entry.parameters

        # 1. 策略大类标签（从 STRATEGY_MAP 推断）
        strategy_type = self.STRATEGY_MAP.get(method, "unknown")
        if strategy_type != "unknown":
            # trend_following → "trend", mean_reversion → "mean_reversion"
            if strategy_type == "trend_following":
                tags.append("trend")
            elif strategy_type == "volume_based":
                tags.append("volume_based")
            else:
                tags.append(strategy_type)

        # 2. 技术因子标签（基于方法名）
        method_to_tech_tag: dict[str, str] = {
            "ma_cross": "ma",
            "macd": "macd",
            "bollinger": "bollinger",
            "rsi": "rsi",
            "kdj": "kdj",
            "bias": "bias",
            "grid": "grid",
            "reversal": "reversal",
            "volume_profile": "volume_profile",
            "wyckoff": "wyckoff",
        }
        tech_tag = method_to_tech_tag.get(method)
        if tech_tag:
            tags.append(tech_tag)

        # 3. 风格标签（基于周期参数）
        # 尝试从多个常见参数字段获取周期
        period_keys = ["period", "ma_fast", "rsi_period", "kdj_n", "bias_period", "lookback"]
        period_value = None
        for key in period_keys:
            val = params.get(key)
            if val is not None and isinstance(val, (int, float)):
                period_value = int(val)
                break

        if period_value is not None:
            if period_value <= 10:
                tags.append("short_term")
            elif period_value <= 40:
                tags.append("mid_term")
            else:
                tags.append("long_term")

        return list(set(tags))
