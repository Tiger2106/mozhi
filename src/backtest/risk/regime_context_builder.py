"""
mozhi_platform.src.backtest.risk.regime_context_builder — RegimeContextBuilder

市场上下文构建器：打通 Regime + AnchoredVWAP + Volume Profile + KnowledgeBridge，
输出综合信号供 RiskPipeline 的信号融合流水线使用。

功能：
  - 从 RegimeAnalyzer 获取市场状态
  - 从 AnchoredVWAPFactor 获取通道偏离度及评分
  - 从 Volume Profile 获取价值区信息
  - 从 KnowledgeBridge 获取历史知识信号
  - 加权融合为统一的 CompositeSignal

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.regime.regime_analyzer import RegimeAnalyzer, RegimeWindowResult
from backtest.factors.volume.anchored_vwap import (
    AnchorConfig,
    calc_anchored_vwap,
    calc_anchored_vwap_score,
)
from backtest.factors.volume.volume_profile_factor import calc_volume_profile, calc_lvn
from backtest.engine.knowledge_bridge import KnowledgeBridge

logger = logging.getLogger(__name__)


# ─── 输出类型 ──────────────────────────────────────────────


@dataclass
class RegimeContextSignal:
    """RegimeContextBuilder 的综合信号输出"""
    composite_score: float
    """综合评分 [-1, 1]，正=看涨，负=看空。"""

    action: str
    """操作建议: BUY / SELL / HOLD / REDUCE"""

    confidence: float
    """置信度 [0, 1]"""

    regime: str
    """当前市场状态"""

    regime_confidence: float = 0.0
    """状态判定的置信度"""

    vwap_deviation: float = 0.0
    """VWAP 标准化偏离度"""

    vwap_band_position: float = 0.0
    """VWAP 通道位置 [-2, 2]"""

    volume_profile_poc: float = 0.0
    """Volume Profile 控制点价格"""

    volume_profile_vah: float = 0.0
    """Volume Profile 价值区上界"""

    volume_profile_val: float = 0.0
    """Volume Profile 价值区下界"""

    lvn_count: int = 0
    """Low Volume Node 数量"""

    knowledge_signal: float = 0.0
    """KnowledgeBridge 信号得分"""

    reasoning: str = ""
    """分析推理摘要"""

    weights: Dict[str, float] = field(default_factory=dict)
    """各分量权重"""


# ─── 信号分量权重配置 ──────────────────────────────────────


DEFAULT_WEIGHTS: Dict[str, float] = {
    "regime": 0.40,
    "vwap": 0.25,
    "volume_profile": 0.20,
    "knowledge": 0.15,
}


# ─── RegimeContextBuilder ─────────────────────────────────────


class RegimeContextBuilder:
    """市场上下文构建器。

    整合多个信号源（Regime + AnchoredVWAP + Volume Profile + KnowledgeBridge），
    输出加权融合后的综合信号。

    配置方式（按优先级）：
      1. 构造函数 weights 参数（自定义）
      2. 类默认权重 DEFAULT_WEIGHTS

    Examples:
        >>> builder = RegimeContextBuilder(regime_analyzer=analyzer)
        >>> signal = builder.build_signal(df_ohlcv)
        >>> signal.composite_score
        0.45
        >>> signal.action
        'BUY'
    """

    def __init__(
        self,
        regime_analyzer: Optional[RegimeAnalyzer] = None,
        knowledge_bridge: Optional[KnowledgeBridge] = None,
        anchor_config: Optional[AnchorConfig] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.regime_analyzer = regime_analyzer or RegimeAnalyzer()
        self.knowledge_bridge = knowledge_bridge
        self.anchor_config = anchor_config or AnchorConfig(type="first_bar")
        self.weights = weights or dict(DEFAULT_WEIGHTS)

        # 标准化权重
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def build_signal(
        self,
        df_ohlcv: pd.DataFrame,
        symbol: str = "",
        regime_series: Optional[pd.Series] = None,
    ) -> RegimeContextSignal:
        """构建综合信号。

        Args:
            df_ohlcv: OHLCV DataFrame。
            symbol: 标的代码（可选）。
            regime_series: 市场状态序列（可选，传给 AnchoredVWAP）。

        Returns:
            RegimeContextSignal: 综合信号输出。
        """
        if df_ohlcv.empty or len(df_ohlcv) < 10:
            return self._empty_signal("数据不足")

        # ── 1. Regime 分析 ────────────────────────────────────
        window_result = self.regime_analyzer.analyze_window(
            df_ohlcv, lookback=min(60, len(df_ohlcv))
        )
        current = self.regime_analyzer.get_current_regime()
        regime = current.get("regime", "UNKNOWN")
        regime_conf = current.get("confidence", 0.0)

        regime_score = self._regime_to_score(regime, window_result)

        # ── 2. AnchoredVWAP ──────────────────────────────────
        vwap_result = calc_anchored_vwap_score(
            df_ohlcv,
            config=self.anchor_config,
            regime_series=regime_series,
        )
        vwap_score = vwap_result.get("score", 0.0)
        vwap_dev = vwap_result.get("vwap_deviation", 0.0)
        band_pos = vwap_result.get("band_position", 0.0)

        # ── 3. Volume Profile ────────────────────────────────
        vp = calc_volume_profile(df_ohlcv)
        lvns = calc_lvn(df_ohlcv)

        # 价格相对价值区的位置：高于 VAH → 看空（超买），低于 VAL → 看多（超卖）
        close_price = df_ohlcv["close"].iloc[-1]
        vp_score = self._volume_profile_to_score(close_price, vp)

        # ── 4. KnowledgeBridge ───────────────────────────────
        kb_score = self._get_knowledge_signal(symbol, regime)

        # ── 5. 加权融合 ──────────────────────────────────────
        composite = (
            self.weights.get("regime", 0.4) * regime_score
            + self.weights.get("vwap", 0.25) * vwap_score
            + self.weights.get("volume_profile", 0.20) * vp_score
            + self.weights.get("knowledge", 0.15) * kb_score
        )

        # 置信度：各分量置信度的加权平均
        confidence = (
            self.weights.get("regime", 0.4) * regime_conf
            + self.weights.get("vwap", 0.25) * min(abs(vwap_score) * 1.5, 1.0)
            + self.weights.get("volume_profile", 0.20) * 0.5  # VP 默认中等置信度
            + self.weights.get("knowledge", 0.15) * min(abs(kb_score), 1.0)
        )
        confidence = max(0.0, min(1.0, confidence))

        # 方向判定
        action = self._score_to_action(composite, confidence)

        # 推理
        reasoning = (
            f"Regime={regime}({regime_conf:.2f}), "
            f"VWAP_dev={vwap_dev:.2f}σ, "
            f"VP_pos={vp.get('value_area_pct', 0):.0f}%, "
            f"KB={kb_score:.2f}"
        )

        return RegimeContextSignal(
            composite_score=round(composite, 4),
            action=action,
            confidence=round(confidence, 4),
            regime=regime,
            regime_confidence=round(regime_conf, 4),
            vwap_deviation=round(vwap_dev, 4),
            vwap_band_position=round(band_pos, 4),
            volume_profile_poc=vp.get("poc", 0.0),
            volume_profile_vah=vp.get("vah", 0.0),
            volume_profile_val=vp.get("val", 0.0),
            lvn_count=len(lvns),
            knowledge_signal=round(kb_score, 4),
            reasoning=reasoning,
            weights=dict(self.weights),
        )

    def _regime_to_score(self, regime: str, window: RegimeWindowResult) -> float:
        """市场状态 → 评分 [-1, 1]"""
        score_map: Dict[str, float] = {
            "UPTREND": 0.8,
            "BREAKOUT": 0.6,
            "RANGE": 0.0,
            "DOWNTREND": -0.8,
            "CLIMAX": -0.3,
            "UNKNOWN": 0.0,
        }
        base = score_map.get(regime, 0.0)
        # 稳定性修正：状态越稳定，得分越可靠
        stability = window.stability
        if stability < 0.3:
            base *= 0.5  # 高波动期，信号减半
        return base

    def _volume_profile_to_score(
        self,
        close_price: float,
        vp: Dict[str, float],
    ) -> float:
        """Volume Profile → 评分 [-1, 1]"""
        vah = vp.get("vah", 0.0)
        val = vp.get("val", 0.0)
        poc = vp.get("poc", 0.0)

        if vah <= 0 or val <= 0 or vah == val:
            return 0.0

        # 价格在价值区内 → 中性
        if val <= close_price <= vah:
            # 靠近 POC → 更中性；靠近边界 → 有方向信号
            mid = (vah + val) / 2.0
            half_range = (vah - val) / 2.0 if vah > val else 1.0
            # 在中间 50% 区域 → 接近 0
            if abs(close_price - mid) / half_range < 0.5:
                return 0.0
            # 靠近 VAH（上边界）→ 轻度看空
            if close_price > mid:
                return -0.2
            # 靠近 VAL（下边界）→ 轻度看多
            return 0.2

        # 价格高于 VAH → 超买，看空
        if close_price > vah:
            overshoot = (close_price - vah) / (vah - val + 1e-10)
            return -min(0.5, overshoot * 0.3)

        # 价格低于 VAL → 超卖，看多
        if close_price < val:
            undershoot = (val - close_price) / (vah - val + 1e-10)
            return min(0.5, undershoot * 0.3)

        return 0.0

    def _get_knowledge_signal(self, symbol: str, regime: str) -> float:
        """从 KnowledgeBridge 获取历史信号。

        当前为轻度集成：若 KnowledgeBridge 有历史数据时提供信号。
        无知识库时返回 0.0。
        """
        if self.knowledge_bridge is None:
            return 0.0

        # 查询最近的知识条目的历史性能
        try:
            entries = self.knowledge_bridge.list_v1_entries()
            if not entries:
                return 0.0

            # 找最近 5 条 symbol 相关的条目
            relevant = [
                e for e in entries
                if e.symbol == symbol and e.confidence > 0.3
            ][-5:]

            if not relevant:
                return 0.0

            # 平均置信度作为信号强度
            avg_conf = np.mean([e.confidence for e in relevant])

            # 当前 regime 下的历史胜率
            win_counts = sum(
                1 for e in relevant
                if e.metadata.get("win_rate", 0.5) > 0.5
            )
            win_ratio = win_counts / len(relevant)

            # 综合 KB 信号
            return float(np.clip(avg_conf * win_ratio * 2 - 0.5, -0.5, 0.5))

        except Exception as e:
            logger.debug("KnowledgeBridge 查询失败: %s", e)
            return 0.0

    def _score_to_action(self, score: float, confidence: float) -> str:
        """综合评分 → 操作建议"""
        if confidence < 0.2:
            return "HOLD"

        if score >= 0.5:
            return "BUY"
        elif score >= 0.15:
            return "BUY"  # 轻度看多，仍可买入但注意仓位
        elif score <= -0.5:
            return "SELL"
        elif score <= -0.15:
            return "REDUCE"
        else:
            return "HOLD"

    def _empty_signal(self, reason: str = "") -> RegimeContextSignal:
        """无数据时的默认信号"""
        return RegimeContextSignal(
            composite_score=0.0,
            action="HOLD",
            confidence=0.0,
            regime="UNKNOWN",
            reasoning=f"未生成信号: {reason}" if reason else "未生成信号",
            weights=dict(self.weights),
        )

    def get_sub_scores(self, df_ohlcv: pd.DataFrame) -> Dict[str, float]:
        """返回各分量得分（调试/分析用）。"""
        window = self.regime_analyzer.analyze_window(
            df_ohlcv, lookback=min(60, len(df_ohlcv))
        )
        current = self.regime_analyzer.get_current_regime()
        regime = current.get("regime", "UNKNOWN")

        vwap_s = calc_anchored_vwap_score(df_ohlcv, config=self.anchor_config)

        vp = calc_volume_profile(df_ohlcv)
        close_price = df_ohlcv["close"].iloc[-1]
        vp_s = self._volume_profile_to_score(close_price, vp)

        return {
            "regime": self._regime_to_score(regime, window),
            "vwap": vwap_s.get("score", 0.0),
            "volume_profile": vp_s,
            "knowledge": self._get_knowledge_signal("", regime),
        }
