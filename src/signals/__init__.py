# 墨枢信号系统
# author: 墨衡
# created_time: 2026-05-20

from .signal_protocol_v1 import (
    Signal,
    SchemaValidationError,
    SignalSerializeError,
    serialize_to_json,
    deserialize_from_json,
    validate_roundtrip,
    validate_signal_version,
    generate_signal_id,
    CURRENT_PROTOCOL_VERSION,
)

__all__ = [
    "Signal",
    "SchemaValidationError",
    "SignalSerializeError",
    "serialize_to_json",
    "deserialize_from_json",
    "validate_roundtrip",
    "validate_signal_version",
    "generate_signal_id",
    "CURRENT_PROTOCOL_VERSION",
]
