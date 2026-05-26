"""
legacy_signal_adapter.py — 旧系统 float/dict ↔ R1Signal 双向转换

红蓝并行阶段关键适配层：
- 蓝（新系统）→ R1Signal
- 红（旧系统）→ legacy_to_r1signal() → R1Signal → signal_diff(blue, red) → 一致性报告

红蓝信号在 R1 管线中具有相同的第一类优先级，
通过 adapter 层确保两套系统可以联调、对比、渐进迁移。

作者: 墨衡 (moheng)
创建时间: 2026-05-18 10:30 +08:00
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..models.signal_types import R1Signal, SignalDirection, SignalMethod


# ── 旧系统信号键名映射（兼容多种命名变体） ────────────────────

_KEY_ALIASES: dict[str, str] = {
    # direction
    "direction": "direction",
    "signal": "direction",
    "sig": "direction",
    "action": "direction",
    # confidence
    "confidence": "confidence",
    "conf": "confidence",
    "score": "confidence",
    "strength": "confidence",
    # price
    "price": "price",
    "entry_price": "price",
    "trigger_price": "price",
    "px": "price",
    # timestamp
    "timestamp": "timestamp",
    "time": "timestamp",
    "ts": "timestamp",
    "datetime": "timestamp",
    # regime
    "regime": "regime",
    "market_state": "regime",
    "state": "regime",
}

_LEGACY_METHOD_NAMES: dict[str, str] = {
    "reversal": "reversal",
    "grid": "grid",
    "trend": "trend",
    "momentum": "trend",
}


def _normalize_key(k: str) -> str:
    """将旧系统各种命名变体归一化为标准键名"""
    return _KEY_ALIASES.get(k.lower().strip(), k)


def _resolve_ts(ts_val: Any) -> datetime:
    """将多种时间戳格式转换为 datetime"""
    if isinstance(ts_val, datetime):
        return ts_val
    if isinstance(ts_val, (int, float)):
        # ms 级时间戳 → seconds
        if ts_val > 1_000_000_000_000:  # ms 级别
            ts_val = ts_val / 1000.0
        try:
            return datetime.fromtimestamp(ts_val)
        except (OSError, ValueError):
            return datetime.now()
    return datetime.now()


# ── 正向转换：旧系统 dict → R1Signal ────────────────────────────


def legacy_to_r1signal(
    legacy_signal: dict,
    method: Optional[str] = None,
    default_confidence: float = 0.0,
) -> R1Signal:
    """将旧系统 float dict 信号转换为 R1Signal。

    Args:
        legacy_signal: 旧系统信号 dict，支持多种键名变体：
            - {direction: 1/-1/0, confidence: 0.8, price: 100.0, timestamp: ...}
            - {action: "BUY"/"SELL"/"HOLD", score: 0.6, ...}
            - 也支持 {method, direction, confidence, price} 含 method 的格式
        method: 方法名覆盖（若未提供则从 legacy_signal 中提取，默认为 "legacy"）
        default_confidence: 当 legacy_signal 未提供 confidence 时的默认值

    Returns:
        R1Signal

    Examples:
        >>> sig = legacy_to_r1signal({"direction": 1, "confidence": 0.8, "price": 100.5, "timestamp": 1700000000000})
        >>> sig.direction
        1
        >>> sig.method
        'legacy'
    """
    # ── 归一化键名 ──
    normalized = {_normalize_key(k): v for k, v in legacy_signal.items()}

    # ── direction ──
    raw_dir = normalized.get("direction", 0)
    if isinstance(raw_dir, str):
        dir_map = {"BUY": 1, "LONG": 1, "SELL": -1, "SHORT": -1, "HOLD": 0, "": 0}
        direction = dir_map.get(raw_dir.upper(), 0)
    else:
        try:
            direction = int(raw_dir)
            if direction not in (1, -1, 0):
                direction = 0
        except (ValueError, TypeError):
            direction = 0

    # ── confidence ──
    try:
        confidence = float(normalized.get("confidence", default_confidence))
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = default_confidence

    # ── price ──
    try:
        price = float(normalized.get("price", 0.0))
    except (ValueError, TypeError):
        price = 0.0

    # ── timestamp ──
    timestamp = _resolve_ts(normalized.get("timestamp", 0))

    # ── regime ──
    regime = str(normalized.get("regime", ""))

    # ── method ──
    if method is not None:
        resolved_method = method
    else:
        raw_method = str(normalized.get("method", "legacy")).lower()
        resolved_method = _LEGACY_METHOD_NAMES.get(raw_method, "legacy")

    # ── metadata: 传入的全部原始数据 ──
    metadata = dict(legacy_signal)  # 保留原始数据供审计

    return R1Signal(
        method=resolved_method,
        direction=direction,
        confidence=confidence,
        price=price,
        timestamp=timestamp,
        regime=regime,
        metadata=metadata,
    )


# ── 反向转换：R1Signal → 旧系统 dict ────────────────────────────


def r1signal_to_legacy(signal: R1Signal) -> dict:
    """将 R1Signal 转换回旧系统 float dict 格式。

    Args:
        signal: R1Signal 实例

    Returns:
        dict: 旧系统兼容格式 {direction, confidence, price, timestamp, regime}

    Examples:
        >>> sig = R1Signal("breakout_retest", 1, 0.8, 100.0, datetime.now())
        >>> d = r1signal_to_legacy(sig)
        >>> d["direction"]
        1
    """
    return {
        "direction": signal.direction,
        "confidence": signal.confidence,
        "price": signal.price,
        "timestamp": int(signal.timestamp.timestamp() * 1000),
        "regime": signal.regime,
    }
