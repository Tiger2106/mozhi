"""
假突破分类器
基于规则引擎的假突破实时识别与历史模式分析。
不使用ML，基于多维度加权评分。

Author: 墨衡 (generated)
"""

from typing import List, Dict, Optional, Union
import numpy as np


# 标签映射：综合得分 -> 5档标签
LABEL_MAP = [
    (0.85, 'REAL'),
    (0.65, 'PROBABLY_REAL'),
    (0.45, 'UNCERTAIN'),
    (0.25, 'PROBABLY_FAKE'),
    (0.0, 'FAKE'),
]


class FakeBreakoutClassifier:
    """
    假突破分类器。基于5维规则引擎评分：
    - volume_support (30%)：成交量支撑
    - trend_alignment (25%)：趋势方向一致性
    - momentum_quality (20%)：动量质量
    - support_resistance (15%)：支撑/阻力位
    - volatility_context (10%)：波动率背景
    """

    DEFAULT_RULES = {
        'volume_support': 0.30,
        'trend_alignment': 0.25,
        'momentum_quality': 0.20,
        'support_resistance': 0.15,
        'volatility_context': 0.10,
    }

    def __init__(self, rules: Optional[Dict[str, float]] = None):
        self.rules = rules or self.DEFAULT_RULES.copy()
        # 归一化权重
        total = sum(self.rules.values())
        if total > 0:
            for k in self.rules:
                self.rules[k] /= total

    # ─── 各维度评分 ─────────────────────

    def _score_volume_support(self, event: dict, ctx: dict) -> float:
        """成交量支撑评分。
        volume_ratio = 当日成交量 / 20日均量
        映射：<0.5 -> 0, 0.5~1.0 -> 0~0.6, 1.0~2.0 -> 0.6~1.0, >2.0 -> 1.0
        """
        vr = event.get('volume_ratio', ctx.get('volume_ratio', 0))
        if vr <= 0:
            return 0.0
        if vr < 0.5:
            return 0.0
        if vr < 1.0:
            return (vr - 0.5) / 0.5 * 0.6
        if vr < 2.0:
            return 0.6 + (vr - 1.0) / 1.0 * 0.4
        return 1.0

    def _score_trend_alignment(self, event: dict, ctx: dict) -> float:
        """趋势对齐评分。
        突破方向 vs 均线趋势：同向则高分，反向则低分。
        """
        direction = event.get('direction', event.get('breakout_direction', ''))
        ma_trend = ctx.get('ma_trend', ctx.get('trend', 0))
        if isinstance(ma_trend, str):
            ma_trend = 1 if 'UP' in ma_trend.upper() else -1
        dir_val = 1 if 'UP' in str(direction).upper() else -1
        alignment = dir_val * float(ma_trend)
        return max(0, min(1, 0.5 + alignment * 0.5))

    def _score_momentum_quality(self, event: dict, ctx: dict) -> float:
        """动量质量评分。
        突破前N日斜率：对称映射到[0,1]范围。
        """
        mom = event.get('momentum', ctx.get('momentum_slope', 0))
        if isinstance(mom, str):
            mom = float(mom)
        return min(1, max(0, 0.5 + float(mom) * 10))

    def _score_support_resistance(self, event: dict, ctx: dict) -> float:
        """支撑/阻力距离评分。
        突破价离关键位的距离百分比。越远越可信。
        """
        price = event.get('price', event.get('breakout_price', 0))
        nearest_level = ctx.get('nearest_support', ctx.get('support_level', 0))
        if price <= 0 or nearest_level <= 0:
            return 0.5  # 中性
        dist = abs(float(price) - float(nearest_level)) / float(price)
        return min(1, dist * 5)

    def _score_volatility_context(self, event: dict, ctx: dict) -> float:
        """波动率背景评分。
        倒U形：中等波动率（20%-60%百分位）最可靠。
        """
        vol_pct = ctx.get('volatility_percentile', ctx.get('vol_pct', 0.3))
        if vol_pct < 0.2:
            return vol_pct / 0.2 * 0.6
        if vol_pct < 0.6:
            return 0.6 + (vol_pct - 0.2) / 0.4 * 0.4
        return max(0, 1 - (vol_pct - 0.6) / 0.4)

    # ─── 主分类接口 ─────────────────────

    def classify(self, breakout_event: dict,
                 market_context: Optional[dict] = None) -> Dict:
        """对单个突破事件进行真假分类。
        返回 {composite_score, label, dimension_scores, weights}
        """
        ctx = market_context or {}
        scores = {
            'volume_support': self._score_volume_support(breakout_event, ctx),
            'trend_alignment': self._score_trend_alignment(breakout_event, ctx),
            'momentum_quality': self._score_momentum_quality(breakout_event, ctx),
            'support_resistance': self._score_support_resistance(breakout_event, ctx),
            'volatility_context': self._score_volatility_context(breakout_event, ctx),
        }
        composite = sum(scores[k] * self.rules[k] for k in self.rules)
        label = self._to_label(composite)
        return {
            'composite_score': round(composite, 4),
            'label': label,
            'dimension_scores': scores,
            'weights': self.rules.copy(),
        }

    def batch_classify(self, events: List[dict],
                       context: Optional[Dict] = None) -> List[Dict]:
        """批量分类"""
        return [self.classify(e, context) for e in events]

    def analyze_failure_patterns(self, breakout_db: List[dict]) -> Dict:
        """分析历史假突破的各维度特征区分度。
        
        breakout_db: [{is_fake: bool, volume_ratio, momentum, ..., actual_outcome}]
        """
        real = []
        fake = []
        for b in breakout_db:
            is_fake = b.get('is_fake', b.get('actual_outcome', None))
            if is_fake is True:
                fake.append(b)
            elif is_fake is False:
                real.append(b)

        def avg_vals(records, keys):
            if not records:
                return {}
            result = {}
            for k in keys:
                vals = [r.get(k, 0) for r in records if isinstance(r.get(k), (int, float))]
                result[k] = float(np.mean(vals)) if vals else 0
            return result

        keys = ['volume_ratio', 'momentum', 'vwap_deviation', 'strength_score']
        return {
            'total_events': len(breakout_db),
            'real_count': len(real),
            'fake_count': len(fake),
            'real_avg': avg_vals(real, keys),
            'fake_avg': avg_vals(fake, keys),
            'discrimination': {
                k: abs(avg_vals(real, keys).get(k, 0) - avg_vals(fake, keys).get(k, 0))
                for k in keys
            }
        }

    def _to_label(self, score: float) -> str:
        """将综合得分映射到5档标签"""
        for threshold, label in LABEL_MAP:
            if score >= threshold:
                return label
        return 'FAKE'
