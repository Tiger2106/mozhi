"""
墨枢 - 标准信号类型定义（R1）

为因子产出的信号提供统一类型系统，
供因子仓库和下游策略引擎消费。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SignalAction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


class SignalConfidence(Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class SignalDirection(Enum):
    LONG = 1
    SHORT = -1
    FLAT = 0


class SignalMethod(Enum):
    BREAKOUT_RETEST = "breakout_retest"
    CONTINUATION = "continuation"
    VOLUME_PRICE_EXPANSION = "volume_price_expansion"
    REVERSAL = "reversal"
    TREND = "trend"
    GRID = "grid"
    COMPOSITE = "composite"


class MarketRegime(Enum):
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    RANGE = "RANGE"
    BREAKOUT = "BREAKOUT"
    CLIMAX = "CLIMAX"
    UNKNOWN = "UNKNOWN"


# ── R1Signal — 评审会决议标准信号类型（REVIEW_FIX #1） ──

@dataclass
class R1Signal:
    """统一信号数据类型（R1 评审会决议标准，用于红蓝并行比较）。"""
    method: str                          # 信号来源（reversal / breakout_retest / ...）
    direction: int                       # 1=多, -1=空, 0=无信号
    confidence: float                    # 0~1 置信度
    price: float                         # 触发价格
    timestamp: datetime = field(default_factory=datetime.now)
    regime: str = ""                     # 触发时的市场状态
    metadata: dict = field(default_factory=dict)  # 因子评分、附加数据

    def __post_init__(self) -> None:
        assert self.direction in (-1, 0, 1), f"R1Signal.direction must be -1/0/1, got {self.direction}"
        assert 0.0 <= self.confidence <= 1.0, f"R1Signal.confidence must be 0~1, got {self.confidence}"

    def to_legacy_dict(self) -> dict:
        """转换为旧系统兼容的 dict 格式。"""
        return {
            "signal_verdict": self.direction,
            "confidence": self.confidence,
            "price": self.price,
            "method": self.method,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp,
        }


def signal_diff(old: dict, new: R1Signal) -> dict:
    """比较旧系统信号与新系统 R1Signal（红蓝并行偏差比较）。

    比较维度：
    - direction_match: bool — 方向是否一致
    - price_deviation: float — 触发价格偏差百分比
    - timing_deviation: int — 信号触发时间偏差（K线数）
    - confidence_delta: float — 置信度差异
    - verdict: str — "match" / "minor_deviation" / "mismatch"
    """
    direction_match = (old.get("signal_verdict", 0) == new.direction)
    old_price = old.get("price", 0) or 1e-10
    price_deviation = abs(new.price - old_price) / old_price * 100 if old_price else 0
    old_confidence = old.get("confidence", 0)
    confidence_delta = new.confidence - float(old_confidence)

    if direction_match and price_deviation < 0.5:
        verdict = "match"
    elif direction_match and price_deviation < 5.0:
        verdict = "minor_deviation"
    else:
        verdict = "mismatch"

    return {
        "direction_match": direction_match,
        "price_deviation": round(price_deviation, 2),
        "timing_deviation": 0,
        "confidence_delta": round(confidence_delta, 2),
        "verdict": verdict,
    }


# ── FactorSignal / CompositeSignal — 因子级输出（用于阶段二信号融合） ──

@dataclass
class FactorSignal:
    """单个因子的输出信号。"""
    symbol: str
    timestamp: str  # ISO8601
    factor_name: str
    action: SignalAction
    confidence: SignalConfidence
    score: float  # [-1, 1]
    suggested_price: Optional[float] = None
    position_ratio: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_r1signal(self) -> R1Signal:
        direction = 1 if self.action in (SignalAction.BUY, SignalAction.CLOSE) else (-1 if self.action == SignalAction.SELL else 0)
        return R1Signal(
            method=self.factor_name,
            direction=direction,
            confidence=abs(self.score),
            price=self.suggested_price or 0.0,
            metadata=self.metadata,
        )


@dataclass
class CompositeSignal:
    """多因子融合后的最终信号。"""
    symbol: str
    timestamp: str
    action: SignalAction
    confidence: SignalConfidence
    composite_score: float
    regime: MarketRegime
    sub_signals: List[FactorSignal] = field(default_factory=list)
    reasoning: str = ""

    def to_r1signal(self) -> R1Signal:
        direction = 1 if self.action in (SignalAction.BUY, SignalAction.CLOSE) else (-1 if self.action == SignalAction.SELL else 0)
        conf_map = {SignalConfidence.HIGH: 0.9, SignalConfidence.MEDIUM: 0.6, SignalConfidence.LOW: 0.3}
        return R1Signal(
            method="composite",
            direction=direction,
            confidence=conf_map.get(self.confidence, 0.5),
            price=0.0,
            regime=self.regime.value,
            metadata={"composite_score": self.composite_score, "sub_signals": len(self.sub_signals)},
        )
