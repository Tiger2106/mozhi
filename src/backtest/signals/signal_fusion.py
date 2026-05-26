"""
墨枢 - SignalFusionEngine 多因子信号融合引擎（R1 阶段三：任务1）

功能：
  - 接收多个 FactorSignal（来自 FactorRegistry.compute_all 的因子输出）
  - 按融合规则输出 CompositeSignal
  - 支持可配置权重

融合规则：
  1. 同方向因子加权平均
  2. 反方向因子互相抵消（score 求和取符号）
  3. 极低置信度（score 绝对值 < 0.3）信号过滤
  4. confidence = 加权后的净 score 绝对值（映射到 0~1）

依赖:
  - src.backtest.models.signal_types — FactorSignal, CompositeSignal, MarketRegime, SignalAction, SignalConfidence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from src.backtest.models.signal_types import (
    CompositeSignal,
    FactorSignal,
    MarketRegime,
    SignalAction,
    SignalConfidence,
)


@dataclass
class FusionConfig:
    """融合引擎配置参数"""
    confidence_threshold: float = 0.3       # 低置信度过滤阈值
    default_weights: Dict[str, float] = field(default_factory=dict)  # 因子权重（空=等权）
    regime_override: bool = True            # 是否使用 regime 状态修正信号
    regime_penalty_flat: float = 0.0        # 横盘状态下信号折扣
    regime_penalty_climax: float = 0.3      # 高潮状态下信号折扣


class SignalFusionEngine:
    """多因子信号融合引擎。

    接收 FactorRegistry 产出的多个 FactorSignal，按照可配置的融合规则
    输出统一的 CompositeSignal。
    """

    def __init__(self, config: Optional[FusionConfig] = None):
        self.config = config or FusionConfig()

    def fuse(
        self,
        signals: List[FactorSignal],
        regime: Optional[MarketRegime] = None,
    ) -> CompositeSignal:
        """融合多个因子信号为 CompositeSignal。

        Args:
            signals: FactorSignal 列表（来自 FactorRegistry 的因子评分）
            regime: 当前市场状态（可选，用于信号修正）

        Returns:
            CompositeSignal: 融合后的输出信号
        """
        if not signals:
            return self._empty_composite_signal()

        symbol = signals[0].symbol
        timestamp = signals[0].timestamp

        # ── 1. 极低置信度过滤 ────────────────────────────────
        valid_signals = [
            s for s in signals
            if abs(s.score) >= self.config.confidence_threshold
        ]

        if not valid_signals:
            return CompositeSignal(
                symbol=symbol,
                timestamp=timestamp,
                action=SignalAction.HOLD,
                confidence=SignalConfidence.LOW,
                composite_score=0.0,
                regime=regime or MarketRegime.UNKNOWN,
                sub_signals=signals.copy(),
                reasoning="所有因子信号置信度低于阈值，无有效信号",
            )

        # ── 2. 权重构建 ──────────────────────────────────────
        # 构建权重字典：因子名 → 权重
        weights = self._build_weights(valid_signals)

        # ── 3. 融合计算 ──────────────────────────────────────
        total_weight = 0.0
        weighted_sum = 0.0
        long_weight = 0.0    # 多头方向权重和
        short_weight = 0.0   # 空头方向权重和

        for s in valid_signals:
            w = weights.get(s.factor_name, 1.0)
            weighted_sum += s.score * w
            total_weight += w

            if s.score > 0:
                long_weight += w
            elif s.score < 0:
                short_weight += w

        if total_weight == 0:
            return self._empty_composite_signal(symbol, timestamp, regime, valid_signals)

        net_score = weighted_sum / total_weight

        # ── 4. 计算置信度（净 score 绝对值映射到 0~1） ──────
        confidence_value = min(abs(net_score), 1.0)

        # 修正：多空力量差异体现一致性
        if long_weight > 0 and short_weight > 0:
            conflict_ratio = min(long_weight, short_weight) / max(long_weight, short_weight)
            # 冲突越大，置信度越低
            confidence_value *= (1.0 - conflict_ratio * 0.5)

        # ── 5. 状态修正 ──────────────────────────────────────
        if regime is not None and self.config.regime_override:
            if regime == MarketRegime.RANGE:
                net_score *= (1.0 - self.config.regime_penalty_flat)
            elif regime in (MarketRegime.CLIMAX, MarketRegime.UNKNOWN):
                net_score *= (1.0 - self.config.regime_penalty_climax)

        # ── 6. 确定 action 和 confidence 枚举 ──────────────────
        action, conf_enum = self._determine_action(net_score, confidence_value)

        # ── 7. 信号有效性统计 ────────────────────────────────
        factor_details = []
        for s in signals:
            factor_details.append(
                f"{s.factor_name}:score={s.score:.3f}"
            )

        reasoning = (
            f"融合 {len(valid_signals)}/{len(signals)} 个有效因子信号，"
            f"加权净评分={net_score:.4f}，置信度={confidence_value:.4f}，"
            f"市场状态={regime.value if regime else 'N/A'}"
        )

        return CompositeSignal(
            symbol=symbol,
            timestamp=timestamp,
            action=action,
            confidence=conf_enum,
            composite_score=round(net_score, 4),
            regime=regime or MarketRegime.UNKNOWN,
            sub_signals=signals.copy(),
            reasoning=reasoning,
        )

    def _build_weights(self, signals: List[FactorSignal]) -> Dict[str, float]:
        """构建因子权重映射。

        优先返回用户配置的权重，未配置的因子等权处理。
        """
        if self.config.default_weights:
            weights = {}
            for s in signals:
                if s.factor_name in self.config.default_weights:
                    weights[s.factor_name] = self.config.default_weights[s.factor_name]
                else:
                    weights[s.factor_name] = 1.0
            return weights
        # 等权：所有因子权重为 1.0
        return {s.factor_name: 1.0 for s in signals}

    def _determine_action(
        self,
        net_score: float,
        confidence_value: float,
    ) -> tuple[SignalAction, SignalConfidence]:
        """根据净评分和置信度确定操作类型和置信度级别。"""
        # 置信度映射
        if confidence_value >= 0.7:
            conf_enum = SignalConfidence.HIGH
        elif confidence_value >= 0.4:
            conf_enum = SignalConfidence.MEDIUM
        else:
            conf_enum = SignalConfidence.LOW

        # 方向判定（加入置信度门槛，低置信度建议 HOLD）
        if abs(net_score) < 0.1 or confidence_value < 0.2:
            return SignalAction.HOLD, conf_enum

        if net_score > 0:
            return SignalAction.BUY, conf_enum
        else:
            return SignalAction.SELL, conf_enum

    def _empty_composite_signal(
        self,
        symbol: str = "",
        timestamp: str = "",
        regime: Optional[MarketRegime] = None,
        sub_signals: Optional[List[FactorSignal]] = None,
    ) -> CompositeSignal:
        """无信号时的默认输出。"""
        return CompositeSignal(
            symbol=symbol,
            timestamp=timestamp,
            action=SignalAction.HOLD,
            confidence=SignalConfidence.LOW,
            composite_score=0.0,
            regime=regime or MarketRegime.UNKNOWN,
            sub_signals=sub_signals or [],
            reasoning="无输入信号，默认 HOLD",
        )
