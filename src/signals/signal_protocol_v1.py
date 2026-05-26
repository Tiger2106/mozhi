"""
Signal Protocol v1 — 墨枢研究↔交易信号交换协议

Core 8 字段 + extras 扩展字典。
JSON 双向序列化，V-01~V-13 验证规则，extras 64KB 上限。

author: 墨衡
created_time: 2026-05-20
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Literal, Optional

from .logger import (
    get_logger,
    log_extras_debug_warning,
    log_serialization_error,
    log_deserialization_error,
    log_extras_redline_warning,
)

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

CURRENT_PROTOCOL_VERSION = "1.0"
SUPPORTED_MAJOR_VERSIONS = {1}

EXTRAS_MAX_BYTES = 64 * 1024       # 64KB
DEBUG_KEY_MAX_COUNT = 3
EXTRAS_KEY_MAX_LENGTH = 128

VALID_DIRECTIONS = ("BUY", "SELL", "HOLD")
VALID_HORIZONS = ("short", "mid", "long")
VALID_SIGNAL_TYPES = ("trend", "reversal", "grid")

# UUID v4 正则
UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
# ISO 8601 含时区偏移
TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"
)
# SemVer MAJOR.MINOR
PROTOCOL_VERSION_RE = re.compile(r"^\d+\.\d+$")

# Core 字段名集合（用于 V-10 未知字段检测）
CORE_FIELD_NAMES = frozenset({
    "signal_id", "symbol", "direction", "confidence",
    "horizon", "signal_type", "timestamp", "protocol_version",
    "extras",
})

# V-13 例外键前缀（6类）
EXCEPTION_KEY_PREFIXES = (
    "ml.trial_",
    "debug.",
    "bridge.",
    "compliance.",
    "trace.",
    "strategy.",
)


# ═══════════════════════════════════════════════════════════
# 异常定义
# ═══════════════════════════════════════════════════════════

class SchemaValidationError(ValueError):
    """信号 Schema 验证失败异常 (V-01 ~ V-13)"""
    pass


class SignalSerializeError(Exception):
    """序列化/反序列化过程错误"""
    pass


# ═══════════════════════════════════════════════════════════
# Signal 数据类
# ═══════════════════════════════════════════════════════════

@dataclass
class Signal:
    """
    Signal Protocol v1 核心数据类

    Core 字段（冻结，8个）:
        signal_id, symbol, direction, confidence,
        horizon, signal_type, timestamp, protocol_version

    Extension（开放）:
        extras — 可扩展字典

    __post_init__ 自动运行 validate()
    """

    # ── Core（冻结） ──
    signal_id: str
    symbol: str
    direction: Literal["BUY", "SELL", "HOLD"]
    confidence: float                    # 0.0 ~ 1.0, 精度 4 位
    horizon: str                         # "short" | "mid" | "long"
    signal_type: str                     # "trend" | "reversal" | "grid"
    timestamp: datetime
    protocol_version: str                # "MAJOR.MINOR"

    # ── Extension（开放） ──
    extras: dict = field(default_factory=dict)

    # ── 内部状态（反序列化时保留） ──
    _original_data: dict = field(default_factory=dict, repr=False, compare=False)
    _ignored_fields: list = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self):
        """构造后自动验证"""
        # 精度归一化
        self.confidence = round(float(self.confidence), 4)
        self.validate()

    # ── 验证 ─────────────────────────────────────────────

    def validate(self) -> None:
        """
        运行 V-01 ~ V-09, V-12 验证

        异常抛出: SchemaValidationError（验证失败时）
        """
        # V-01: signal_id UUID v4 格式
        if not UUID_V4_RE.match(str(self.signal_id)):
            raise SchemaValidationError(
                f"V-01 FAILED: signal_id not UUID v4: {self.signal_id}"
            )

        # V-02: symbol 非空、字符串、≤10 字符
        if not isinstance(self.symbol, str) or not self.symbol or len(self.symbol) > 10:
            raise SchemaValidationError(
                f"V-02 FAILED: invalid symbol: '{self.symbol}'"
            )

        # V-03: direction 合法性
        if self.direction not in VALID_DIRECTIONS:
            raise SchemaValidationError(
                f"V-03 FAILED: invalid direction: {self.direction}"
            )

        # V-04: confidence 范围 [0.0, 1.0]
        if not isinstance(self.confidence, (int, float)) or not (0.0 <= self.confidence <= 1.0):
            raise SchemaValidationError(
                f"V-04 FAILED: confidence out of range [0.0, 1.0]: {self.confidence}"
            )

        # V-05: horizon 合法性
        if self.horizon not in VALID_HORIZONS:
            raise SchemaValidationError(
                f"V-05 FAILED: invalid horizon: {self.horizon}"
            )

        # V-06: signal_type 合法性
        if self.signal_type not in VALID_SIGNAL_TYPES:
            raise SchemaValidationError(
                f"V-06 FAILED: invalid signal_type: {self.signal_type}"
            )

        # V-07: timestamp 必须含时区
        if not hasattr(self.timestamp, "tzinfo") or self.timestamp.tzinfo is None:
            raise SchemaValidationError(
                "V-07 FAILED: timestamp must include timezone offset"
            )

        # V-08: protocol_version 格式 SemVer MAJOR.MINOR
        if not PROTOCOL_VERSION_RE.match(str(self.protocol_version)):
            raise SchemaValidationError(
                f"V-08 FAILED: invalid protocol_version: {self.protocol_version}"
            )

        # V-09: 8 个 Core 字段完备性 — 由 dataclass 的 __init__ 隐式保证

        # V-12: extras 类型
        if not isinstance(self.extras, dict):
            raise SchemaValidationError(
                "V-12 FAILED: extras must be a dict"
            )

    # ── extras 大小检查 ─────────────────────────────────

    def check_extras_size(self) -> bool:
        """
        检查 extras JSON 序列化后是否 ≤ 64KB

        Returns:
            True 表示未超限
        """
        extras_json = json.dumps(self.extras, ensure_ascii=False, separators=(",", ":"))
        return len(extras_json.encode("utf-8")) <= EXTRAS_MAX_BYTES

    # ── Direction + Confidence 联合解码 ─────────────────

    def decode_direction_confidence(self) -> dict:
        """
        Direction + Confidence 联合解码

        返回字典包含:
            direction, confidence, strength, position_weight, description

        §1.3 映射表:
            BUY  0.8~1.0 → strong_buy    (仓位 ≥ 0.6)
            BUY  0.5~0.8 → weak_buy      (仓位 0.3~0.6)
            BUY  0.0~0.5 → tentative_buy (仓位 ≤ 0.3)
            SELL 0.8~1.0 → strong_sell   (仓位 ≥ 0.6)
            SELL 0.5~0.8 → weak_sell     (仓位 0.3~0.6)
            SELL 0.0~0.5 → tentative_sell(仓位 ≤ 0.3)
            HOLD 0.5~1.0 → strong_hold   (N/A)
            HOLD 0.0~0.5 → weak_hold     (N/A)
        """
        c = self.confidence
        d = self.direction

        table = {
            ("BUY", True):   ("strong_buy",       "≥ 0.6",   "强买入信号"),
            ("BUY", None):   ("weak_buy",         "0.3 ~ 0.6", "温和看多"),
            ("BUY", False):  ("tentative_buy",    "≤ 0.3",   "试探性买入，仅供观察"),
            ("SELL", True):  ("strong_sell",      "≥ 0.6",   "强卖出信号"),
            ("SELL", None):  ("weak_sell",        "0.3 ~ 0.6", "温和看空"),
            ("SELL", False): ("tentative_sell",   "≤ 0.3",   "试探性卖出，仅供观察"),
            ("HOLD", True):  ("strong_hold",      "N/A",     "强烈建议持仓"),
            ("HOLD", False): ("weak_hold",        "N/A",     "建议观望"),
        }

        if c >= 0.8:
            key = True
        elif c >= 0.5:
            key = None
        else:
            key = False

        strength, pos_weight, desc = table[(d, key)]

        return {
            "direction": d,
            "confidence": c,
            "strength": strength,
            "position_weight": pos_weight,
            "description": desc,
        }


# ═══════════════════════════════════════════════════════════
# 内部工具函数
# ═══════════════════════════════════════════════════════════

def _is_exception_key(key: str) -> bool:
    """检查 key 是否属于 6 类例外前缀"""
    return key.startswith(EXCEPTION_KEY_PREFIXES)


def _check_redlines(
    extras: dict,
    strict: bool = False,
    signal_id: str = "N/A",
) -> list:
    """
    V-13 extras 禁止域检查

    检查 4 类红线:

    1. RED_CORE_SUBSTITUTE — Core 替补声明
       检测逻辑: key 中包含 core field 名称且不在例外列表中
    2. RED_BINARY_LARGEOBJECT — 二进制大数据
       检测逻辑: 超长 base64-like 字符串 / 超 10KB 的 list/dict
    3. RED_SENSITIVE_INFO — 敏感信息
       检测逻辑: key 匹配敏感 pattern（password, token, api_key 等）
    4. RED_CIRCULAR_REF — 循环引用
       检测逻辑: value 是 UUID v4 格式字符串

    Args:
        extras: 待检查的 extras 字典
        strict: 严格模式下发现红线直接抛出 SchemaValidationError
        signal_id: 信号 ID（用于日志）

    Returns:
        宽松模式下返回警告列表（每个元素为 dict）

    Raises:
        SchemaValidationError: strict=True 且发现红线时
    """
    if not isinstance(extras, dict):
        return []

    warnings = []

    for key, value in extras.items():
        key_str = str(key) if isinstance(key, str) else ""

        # ── 红线1: Core 替补声明 ──
        core_field_names = [
            "direction", "symbol", "confidence", "horizon",
            "signal_type", "timestamp", "protocol_version", "signal_id",
        ]
        if not _is_exception_key(key_str):
            key_lower = key_str.lower().replace("-", "_").replace(".", "_")
            for cf in core_field_names:
                if cf in key_lower:
                    warnings.append({
                        "type": "RED_CORE_SUBSTITUTE",
                        "key": key_str,
                        "detail": f"key references core field '{cf}'",
                    })
                    break

        # ── 红线2: 二进制大数据 ──
        if isinstance(value, str) and len(value) > 500:
            # base64-like 检测（前 100 字符全为 base64 字符集）
            head = value[:100]
            if re.match(r"^[A-Za-z0-9+/=]+$", head):
                warnings.append({
                    "type": "RED_BINARY_LARGEOBJECT",
                    "key": key_str,
                    "detail": f"key contains base64-like data ({len(value)} chars)",
                })

        if isinstance(value, (list, dict)):
            serialized_size = len(
                json.dumps(value, ensure_ascii=False).encode("utf-8")
            )
            if serialized_size > 10 * 1024:  # 10KB
                if not _is_exception_key(key_str):
                    warnings.append({
                        "type": "RED_BINARY_LARGEOBJECT",
                        "key": key_str,
                        "detail": f"key serialized size {serialized_size} bytes exceeds 10KB",
                    })

        # ── 红线3: 敏感信息 ──
        sensitive_patterns = [
            "password", "secret", "token", "apikey", "api_key", "api-key",
            "account", "trader_id", "traderid", "user_id", "userid",
            "private", "credential", "auth", "passwd",
            "credit_card", "phone", "email",
        ]
        if key_str:
            kl = key_str.lower().replace("-", "_").replace(".", "_")
            for sp in sensitive_patterns:
                if sp in kl:
                    warnings.append({
                        "type": "RED_SENSITIVE_INFO",
                        "key": key_str,
                        "detail": f"key contains sensitive pattern '{sp}'",
                    })
                    break

        # ── 红线4: 循环引用（value 为 UUID 格式） ──
        if isinstance(value, str) and UUID_V4_RE.match(value):
            warnings.append({
                "type": "RED_CIRCULAR_REF",
                "key": key_str,
                "detail": "value is a UUID v4 string (possible circular reference)",
            })

        # ── extras key 长度超限 ──
        if key_str and len(key_str) > EXTRAS_KEY_MAX_LENGTH and not _is_exception_key(key_str):
            warnings.append({
                "type": "RED_KEY_LENGTH",
                "key": key_str,
                "detail": f"key length {len(key_str)} exceeds {EXTRAS_KEY_MAX_LENGTH}",
            })

    # 严格模式：红线即拒绝
    if strict and warnings:
        raise SchemaValidationError(
            f"V-13 STRICT FAILED: {len(warnings)} red-line violation(s): "
            + " | ".join(f"[{w['type']}] {w['key']}: {w['detail']}" for w in warnings)
        )

    return warnings


def _check_debug_keys(extras: dict, signal_id: str) -> None:
    """
    检查 debug.* key 数量是否超限并记录预警

    Args:
        extras: extras 字典
        signal_id: 信号 ID
    """
    debug_keys = [k for k in extras if isinstance(k, str) and k.startswith("debug.")]
    if len(debug_keys) > DEBUG_KEY_MAX_COUNT:
        log_extras_debug_warning(signal_id, debug_keys)


def _serialize_timestamp(dt: datetime) -> str:
    """
    序列化 datetime → ISO 8601 字符串

    强制使用 +08:00 时区。

    Args:
        dt: 带时区的 datetime

    Returns:
        ISO 8601 格式字符串，如 '2026-05-20T10:30:00+08:00'
    """
    tz_east8 = timezone(timedelta(hours=8))
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz_east8)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    # Python 的 %z 输出 +0800，需要插入冒号
    if len(s) == 24:  # YYYY-MM-DDTHH:MM:SS+HHMM
        s = s[:22] + ":" + s[22:]
    return s


def _deserialize_timestamp(s: str) -> datetime:
    """
    从 ISO 8601 字符串反序列化为 datetime

    Args:
        s: ISO 8601 字符串，如 '2026-05-20T10:30:00+08:00'

    Returns:
        带时区的 datetime 对象

    Raises:
        SchemaValidationError: 无法解析或缺少时区
    """
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError) as e:
        raise SchemaValidationError(
            f"V-07 FAILED: cannot parse timestamp '{s}': {e}"
        )

    if dt.tzinfo is None:
        raise SchemaValidationError(
            f"V-07 FAILED: timestamp lacks timezone offset: {s}"
        )

    return dt


def generate_signal_id() -> str:
    """
    生成 UUID v4 作为 signal_id

    Returns:
        UUID v4 字符串，如 '550e8400-e29b-41d4-a716-446655440000'
    """
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════
# 序列化 / 反序列化
# ═══════════════════════════════════════════════════════════

def serialize_to_json(signal: Signal, pretty: bool = False) -> str:
    """
    将 Signal 序列化为 JSON 字符串

    执行验证链: V-01~V-09, V-12, V-13（宽松）, extras 大小检查

    Args:
        signal: Signal 对象
        pretty: True 输出 2 空格缩进（开发用）；False 压缩输出（生产用）

    Returns:
        JSON 字符串

    Raises:
        SignalSerializeError: 序列化失败
    """
    try:
        # ── V-13 宽松模式红线检查 ──
        redline_warnings = _check_redlines(
            signal.extras, strict=False, signal_id=signal.signal_id
        )
        for w in redline_warnings:
            log_extras_redline_warning(
                signal.signal_id, w["type"], w["key"], w["detail"]
            )

        # ── debug.* key 超限预警 ──
        _check_debug_keys(signal.extras, signal.signal_id)

        # ── extras 大小检查 ──
        if not signal.check_extras_size():
            raise SignalSerializeError(
                f"extras exceeds {EXTRAS_MAX_BYTES} byte size limit"
            )

        # ── 构建输出字典 ──
        data = {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "confidence": round(signal.confidence, 4),
            "horizon": signal.horizon,
            "signal_type": signal.signal_type,
            "timestamp": _serialize_timestamp(signal.timestamp),
            "protocol_version": signal.protocol_version,
            "extras": signal.extras if signal.extras else {},
        }

        indent = 2 if pretty else None
        return json.dumps(data, ensure_ascii=False, indent=indent)

    except SchemaValidationError as e:
        log_serialization_error(signal.signal_id, str(e))
        raise SignalSerializeError(str(e)) from e
    except SignalSerializeError:
        raise
    except Exception as e:
        log_serialization_error(signal.signal_id, str(e))
        raise SignalSerializeError(f"serialization failed: {e}") from e


def deserialize_from_json(json_str: str, strict_v13: bool = False) -> Signal:
    """
    从 JSON 字符串反序列化为 Signal 对象

    执行验证链: V-01~V-13

    Args:
        json_str: JSON 字符串
        strict_v13: 是否使用严格模式进行 V-13 红线检查

    Returns:
        Signal 对象

    Raises:
        SchemaValidationError: schema 验证失败
        SignalSerializeError: 反序列化过程失败（如 JSON 语法错误）
    """
    # ── JSON 解析 ──
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        log_deserialization_error("json", str(e))
        raise SignalSerializeError(f"JSON parse error: {e}")

    if not isinstance(data, dict):
        raise SignalSerializeError("JSON root must be an object")

    # ── V-09: 必需字段完备性 ──
    required = [
        "signal_id", "symbol", "direction", "confidence",
        "horizon", "signal_type", "timestamp", "protocol_version",
    ]
    missing = [f for f in required if f not in data]
    if missing:
        raise SchemaValidationError(f"V-09 FAILED: missing required fields: {missing}")

    # ── V-10: 未知字段检测 ──
    unknown_fields = [k for k in data if k not in CORE_FIELD_NAMES]
    if unknown_fields:
        logger.info(
            "V-10: unknown fields ignored: %s", unknown_fields,
            extra={"unknown_fields": unknown_fields},
        )

    # ── V-12: extras 类型 / 空 extras 提升 ──
    raw_extras = data.get("extras")
    if raw_extras is None or "extras" not in data:
        extras = {}
    elif not isinstance(raw_extras, dict):
        raise SchemaValidationError("V-12 FAILED: extras must be a dict")
    else:
        extras = raw_extras

    # ── V-13 extras 禁止域检查 ──
    redline_warnings = _check_redlines(
        extras, strict=strict_v13, signal_id=data.get("signal_id", "N/A")
    )
    for w in redline_warnings:
        log_extras_redline_warning(
            data.get("signal_id", "N/A"), w["type"], w["key"], w["detail"]
        )

    # ── debug.* key 超限预警 ──
    sid = data.get("signal_id", "N/A")
    _check_debug_keys(extras, sid)

    # ── extras 64KB 大小校验 ──
    extras_json = json.dumps(extras, ensure_ascii=False, separators=(",", ":"))
    if len(extras_json.encode("utf-8")) > EXTRAS_MAX_BYTES:
        raise SignalSerializeError(
            f"deserialization failed: extras exceeds {EXTRAS_MAX_BYTES} byte limit"
        )

    # ── 解析 timestamp ──
    timestamp = _deserialize_timestamp(data["timestamp"])

    # ── 创建 Signal 对象（__post_init__ 内自动验证 V-01~V-09） ──
    signal = Signal(
        signal_id=data["signal_id"],
        symbol=data["symbol"],
        direction=data["direction"],
        confidence=float(data.get("confidence", 0.0)),
        horizon=data["horizon"],
        signal_type=data["signal_type"],
        timestamp=timestamp,
        protocol_version=data["protocol_version"],
        extras=extras,
        _original_data=data,
        _ignored_fields=unknown_fields,
    )

    return signal


# ═══════════════════════════════════════════════════════════
# 辅助验证函数
# ═══════════════════════════════════════════════════════════

def validate_roundtrip(signal: Signal) -> bool:
    """
    验证 Signal 的 JSON 往返一致性

    Signal → serialize → JSON → deserialize → Signal
    所有 Core 字段必须等值。

    Args:
        signal: 原始 Signal 对象

    Returns:
        True 往返一致；False 存在偏差
    """
    json_str = serialize_to_json(signal)
    restored = deserialize_from_json(json_str)

    return (
        signal.signal_id == restored.signal_id
        and signal.symbol == restored.symbol
        and signal.direction == restored.direction
        and abs(signal.confidence - restored.confidence) < 0.0001
        and signal.horizon == restored.horizon
        and signal.signal_type == restored.signal_type
        and signal.protocol_version == restored.protocol_version
        and signal.extras == restored.extras
    )


def validate_signal_version(
    signal_version: str,
    consumer_version: str,
) -> dict:
    """
    验证信号版本与 Consumer 版本的兼容性

    返回字典:
        compatible: bool   — 是否兼容
        strategy: str      — "A" 字段忽略 / "B" 版本降级 / "C" 拒绝
        detail: str        — 说明

    Args:
        signal_version: 信号的 protocol_version（如 "1.0", "2.0"）
        consumer_version: Consumer 支持的协议版本

    Returns:
        兼容性判定结果字典
    """
    try:
        sig_parts = [int(x) for x in str(signal_version).split(".")]
        con_parts = [int(x) for x in str(consumer_version).split(".")]
        sig_major, sig_minor = sig_parts[0], sig_parts[1]
        con_major, con_minor = con_parts[0], con_parts[1]
    except (ValueError, IndexError, AttributeError):
        return {
            "compatible": False,
            "strategy": "C",
            "detail": (
                f"cannot parse versions: "
                f"signal={signal_version}, consumer={consumer_version}"
            ),
        }

    if con_major == sig_major:
        # 同 MAJOR — 正常消费
        if con_minor >= sig_minor:
            return {
                "compatible": True,
                "strategy": "A",
                "detail": "正常消费 (同版本或更新)",
            }
        else:
            return {
                "compatible": True,
                "strategy": "A",
                "detail": (
                    f"降级消费: consumer v{consumer_version} < signal v{signal_version}"
                ),
            }
    elif con_major > sig_major:
        # Consumer 版本 MAJOR 更高 — 向前兼容
        return {
            "compatible": True,
            "strategy": "B",
            "detail": (
                f"版本降级: consumer v{consumer_version} > signal v{signal_version}"
            ),
        }
    else:
        # Consumer 版本 MAJOR 更低 — 拒绝
        return {
            "compatible": False,
            "strategy": "C",
            "detail": (
                f"版本不匹配: consumer v{consumer_version}, signal v{signal_version}"
            ),
        }
