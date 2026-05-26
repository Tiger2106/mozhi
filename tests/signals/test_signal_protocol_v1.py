"""
测试桩 — Signal Protocol v1

覆盖:
  TC-01 ~ TC-05（§4.4 兼容性测试用例）
  边界测试（空extras、版本不匹配、未知键）
  V-13 extras 红线检查
  Direction + Confidence 联合解码
  兼容性测试套件骨架

author: 墨衡
created_time: 2026-05-20
"""

import json
import pytest
from datetime import datetime, timezone, timedelta

from src.signals.signal_protocol_v1 import (
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


# ═══════════════════════════════════════════════════════════
# 测试夹具
# ═══════════════════════════════════════════════════════════

def make_signal(**overrides) -> Signal:
    """
    生成一个有效的标准 Signal 对象
    可传任意 override 参数覆盖默认字段值。
    """
    params = {
        "signal_id": "550e8400-e29b-41d4-a716-446655440000",
        "symbol": "601857",
        "direction": "BUY",
        "confidence": 0.8250,
        "horizon": "short",
        "signal_type": "trend",
        "timestamp": datetime(2026, 5, 20, 10, 30, 0, tzinfo=timezone(timedelta(hours=8))),
        "protocol_version": "1.0",
        "extras": {"factor.pe_ratio": 8.5},
    }
    params.update(overrides)
    return Signal(**params)


def make_json(**overrides) -> str:
    """
    生成一个有效的标准 Signal JSON 字符串
    可传任意 override 参数覆盖默认字段值。
    """
    data = {
        "signal_id": "550e8400-e29b-41d4-a716-446655440000",
        "symbol": "601857",
        "direction": "BUY",
        "confidence": 0.8250,
        "horizon": "short",
        "signal_type": "trend",
        "timestamp": "2026-05-20T10:30:00+08:00",
        "protocol_version": "1.0",
        "extras": {"factor.pe_ratio": 8.5},
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# TC-01: 同版本正常消费
# ═══════════════════════════════════════════════════════════

class TestTC01_SameVersionConsume:
    """
    场景: Consumer v1.0 消费 protocol_version='1.0' 的信号
    """

    def test_core_fields_correctly_parsed(self):
        """✅ 通过 V-01~V-09 且 8 个 Core 字段全部正确解析"""
        signal = make_signal()
        assert signal.signal_id == "550e8400-e29b-41d4-a716-446655440000"
        assert signal.symbol == "601857"
        assert signal.direction == "BUY"
        assert signal.confidence == 0.8250
        assert signal.horizon == "short"
        assert signal.signal_type == "trend"
        assert signal.protocol_version == "1.0"
        assert signal.timestamp.tzinfo is not None

    def test_validation_passes(self):
        """✅ 显式调用 validate() 无异常"""
        signal = make_signal()
        signal.validate()  # 不应抛出

    def test_extras_preserved(self):
        """✅ extras 保留为 dict"""
        signal = make_signal()
        assert isinstance(signal.extras, dict)
        assert signal.extras["factor.pe_ratio"] == 8.5

    def test_empty_extras_allowed(self):
        """✅ extras 可以为空 dict"""
        signal = make_signal(extras={})
        assert signal.extras == {}

    def test_json_roundtrip(self):
        """✅ JSON 往返一致"""
        signal = make_signal()
        assert validate_roundtrip(signal)

    def test_json_roundtrip_empty_extras(self):
        """✅ 空 extras 往返一致"""
        signal = make_signal(extras={})
        json_str = serialize_to_json(signal)
        restored = deserialize_from_json(json_str)
        assert restored.extras == {}
        assert restored.symbol == signal.symbol


# ═══════════════════════════════════════════════════════════
# TC-02: 跨 MAJOR 版本拒绝
# ═══════════════════════════════════════════════════════════

class TestTC02_MajorVersionRejection:
    """
    场景: Consumer v1.0 收到 protocol_version='2.0' 的信号
    """

    def test_version_mismatch_detected(self):
        """✅ validate_signal_version 返回不兼容"""
        result = validate_signal_version("2.0", "1.0")
        assert result["compatible"] is False
        assert result["strategy"] == "C"

    def test_v20_deserializes_but_flagged(self):
        """✅ v2.0 信号可反序列化（额外字段被忽略），但版本校验拒绝"""
        json_str = make_json(protocol_version="2.0", risk_level="high")
        signal = deserialize_from_json(json_str)
        assert signal.protocol_version == "2.0"

        result = validate_signal_version(signal.protocol_version, "1.0")
        assert result["compatible"] is False

    def test_v10_signal_not_blocked(self):
        """✅ 同批次 v1.0 信号正常"""
        signal = make_signal()
        json_str = serialize_to_json(signal)
        restored = deserialize_from_json(json_str)
        assert restored.protocol_version == "1.0"


# ═══════════════════════════════════════════════════════════
# TC-03: 同 MAJOR 内未知 extras 键
# ═══════════════════════════════════════════════════════════

class TestTC03_UnknownExtrasKeys:
    """
    场景: Consumer v1.0 收到版本 '1.0'，但 extras 中包含未知键
    """

    def test_core_fields_unaffected(self):
        """✅ 未知 extras 键不影响 Core 字段解析"""
        signal = make_signal(extras={
            "ml.ensemble_weight": 0.65,
            "unknown_vendor_feature": "some_value",
        })
        assert signal.symbol == "601857"
        assert signal.direction == "BUY"
        assert signal.confidence == 0.8250

    def test_extras_fully_preserved(self):
        """✅ extras 字典原样保留，不丢失数据"""
        extras = {
            "ml.ensemble_weight": 0.65,
            "unknown_vendor_feature": "some_value",
        }
        signal = make_signal(extras=extras)
        assert signal.extras == extras

    def test_unknown_extras_roundtrip(self):
        """✅ 含未知 extras 的 JSON 往返一致"""
        signal = make_signal(extras={
            "ml.ensemble_weight": 0.65,
            "unknown_vendor_feature": "some_value",
        })
        assert validate_roundtrip(signal)


# ═══════════════════════════════════════════════════════════
# TC-04: 空字段边界
# ═══════════════════════════════════════════════════════════

class TestTC04_EmptyFieldBoundary:
    """
    场景: Consumer v1.0 收到 extras 缺失的信号
    """

    def test_missing_extras_filled(self):
        """✅ 反序列化时 extras 自动填为 {}"""
        json_str = json.dumps({
            "signal_id": "550e8400-e29b-41d4-a716-446655440000",
            "symbol": "601857",
            "direction": "BUY",
            "confidence": 0.82,
            "horizon": "short",
            "signal_type": "trend",
            "timestamp": "2026-05-20T10:30:00+08:00",
            "protocol_version": "1.0",
        })
        signal = deserialize_from_json(json_str)
        assert signal.extras == {}

    def test_null_extras_filled(self):
        """✅ extras 为 null 时自动填为 {}"""
        json_str = make_json(extras=None)
        signal = deserialize_from_json(json_str)
        assert signal.extras == {}

    def test_empty_symbol_rejected(self):
        """❌ 空字符串 symbol 应当拒绝"""
        with pytest.raises(SchemaValidationError, match="V-02"):
            make_signal(symbol="")

    def test_zero_confidence_allowed(self):
        """✅ confidence=0.0 是合法值"""
        signal = make_signal(confidence=0.0)
        assert signal.confidence == 0.0

    def test_negative_confidence_rejected(self):
        """❌ 负 confidence 应当拒绝"""
        with pytest.raises(SchemaValidationError, match="V-04"):
            make_signal(confidence=-0.1)

    def test_over_one_confidence_rejected(self):
        """❌ >1.0 的 confidence 应当拒绝"""
        with pytest.raises(SchemaValidationError, match="V-04"):
            make_signal(confidence=1.1)

    def test_naive_timestamp_rejected(self):
        """❌ 不含时区的 timestamp 拒绝"""
        with pytest.raises(SchemaValidationError, match="V-07"):
            make_signal(timestamp=datetime(2026, 5, 20, 10, 30, 0))


# ═══════════════════════════════════════════════════════════
# TC-05: MINOR 版本降级（future-ready）
# ═══════════════════════════════════════════════════════════

class TestTC05_MinorVersionDegradation:
    """
    场景: Consumer v1.0 收到 protocol_version='1.1' 的信号
    """

    def test_unknown_fields_ignored(self):
        """✅ 忽略 extra_field，正常解析 8 个 Core 字段"""
        data = dict(
            signal_id="550e8400-e29b-41d4-a716-446655440000",
            symbol="601857",
            direction="BUY",
            confidence=0.82,
            horizon="short",
            signal_type="trend",
            timestamp="2026-05-20T10:30:00+08:00",
            protocol_version="1.1",
            extras={},
            extra_field="some_value",
        )
        json_str = json.dumps(data)
        signal = deserialize_from_json(json_str)
        assert signal.symbol == "601857"
        assert signal.direction == "BUY"
        assert signal.protocol_version == "1.1"

    def test_extras_normal_with_v11(self):
        """✅ extras 正常解析"""
        json_str = json.dumps({
            "signal_id": "550e8400-e29b-41d4-a716-446655440000",
            "symbol": "601857",
            "direction": "BUY",
            "confidence": 0.82,
            "horizon": "short",
            "signal_type": "trend",
            "timestamp": "2026-05-20T10:30:00+08:00",
            "protocol_version": "1.1",
            "extras": {"ml.ensemble_weight": 0.65},
        })
        signal = deserialize_from_json(json_str)
        assert signal.extras["ml.ensemble_weight"] == 0.65
        assert signal.protocol_version == "1.1"

    def test_version_check_returns_strategy_A(self):
        """✅ 版本校验返回策略 A（字段忽略）"""
        result = validate_signal_version("1.1", "1.0")
        assert result["compatible"] is True
        assert result["strategy"] == "A"


# ═══════════════════════════════════════════════════════════
# 边界测试
# ═══════════════════════════════════════════════════════════

class TestBoundaryExtras:
    """extras 边界测试"""

    def test_generated_signal_id_format(self):
        """自动生成 UUID v4"""
        sid = generate_signal_id()
        assert len(sid) == 36
        assert sid.count("-") == 4

    def test_auto_signal_id_roundtrip(self):
        """自动生成 signal_id 的信号可往返"""
        signal = make_signal(signal_id=generate_signal_id())
        assert validate_roundtrip(signal)

    def test_long_symbol_rejected(self):
        """超过 10 字符的 symbol 拒绝"""
        with pytest.raises(SchemaValidationError, match="V-02"):
            make_signal(symbol="12345678901")

    def test_confidence_precision_4(self):
        """confidence 精度保留 4 位"""
        signal = make_signal(confidence=0.82501)
        assert signal.confidence == 0.8250

    def test_extras_none_rejected(self):
        """extras=None 被拒绝"""
        with pytest.raises(SchemaValidationError, match="V-12"):
            make_signal(extras=None)

    def test_protocol_version_no_patch(self):
        """protocol_version 不能有 PATCH 段"""
        with pytest.raises(SchemaValidationError, match="V-08"):
            make_signal(protocol_version="1.0.0")

    def test_protocol_version_no_v_prefix(self):
        """protocol_version 不能有 v 前缀"""
        with pytest.raises(SchemaValidationError, match="V-08"):
            make_signal(protocol_version="v1.0")

    def test_protocol_version_single_number(self):
        """protocol_version 不能只有 MAJOR"""
        with pytest.raises(SchemaValidationError, match="V-08"):
            make_signal(protocol_version="1")

    def test_empty_extras_roundtrip(self):
        """空 extras 往返一致（V-12 自动提升）"""
        signal = make_signal(extras={})
        json_str = serialize_to_json(signal)
        restored = deserialize_from_json(json_str)
        assert restored.extras == {}


# ═══════════════════════════════════════════════════════════
# V-13 extras 红线检查
# ═══════════════════════════════════════════════════════════

class TestV13_ExtrasRedlineCheck:
    """V-13 extras 禁止域检查"""

    def test_core_substitute_redline(self):
        """红线1: Core 替补声明 → 宽松模式告警但不拒绝"""
        signal = make_signal(extras={"custom_direction": "BUY"})
        json_str = serialize_to_json(signal)
        assert "custom_direction" in json_str

    def test_sensitive_info_redline(self):
        """红线3: 敏感信息 → 宽松模式告警但不拒绝"""
        signal = make_signal(extras={"trader_id": "trader_001"})
        json_str = serialize_to_json(signal)
        assert "trader_id" in json_str

    def test_exception_keys_allowed(self):
        """6 类例外键被允许"""
        signal = make_signal(extras={
            "debug.test_key": "temp_value",
            "bridge.exchange_data": "some_data",
            "trace.span_id": "abc123",
        })
        assert validate_roundtrip(signal)

    def test_multi_exception_keys_roundtrip(self):
        """多例外键可往返"""
        signal = make_signal(extras={
            "strategy.version": "1.2.3",
            "compliance.approver": "moheng",
        })
        assert validate_roundtrip(signal)


# ═══════════════════════════════════════════════════════════
# Direction + Confidence 联合解码
# ═══════════════════════════════════════════════════════════

class TestDirectionConfidenceDecode:
    """Direction + Confidence 联合解码"""

    def test_strong_buy(self):
        decoded = make_signal(direction="BUY", confidence=0.9).decode_direction_confidence()
        assert decoded["strength"] == "strong_buy"
        assert decoded["position_weight"] == "≥ 0.6"

    def test_weak_buy(self):
        decoded = make_signal(direction="BUY", confidence=0.6).decode_direction_confidence()
        assert decoded["strength"] == "weak_buy"

    def test_tentative_buy(self):
        decoded = make_signal(direction="BUY", confidence=0.3).decode_direction_confidence()
        assert decoded["strength"] == "tentative_buy"
        assert decoded["position_weight"] == "≤ 0.3"

    def test_strong_sell(self):
        decoded = make_signal(direction="SELL", confidence=0.85).decode_direction_confidence()
        assert decoded["strength"] == "strong_sell"

    def test_weak_sell(self):
        decoded = make_signal(direction="SELL", confidence=0.6).decode_direction_confidence()
        assert decoded["strength"] == "weak_sell"

    def test_tentative_sell(self):
        decoded = make_signal(direction="SELL", confidence=0.2).decode_direction_confidence()
        assert decoded["strength"] == "tentative_sell"

    def test_strong_hold(self):
        decoded = make_signal(direction="HOLD", confidence=0.9).decode_direction_confidence()
        assert decoded["strength"] == "strong_hold"
        assert decoded["position_weight"] == "N/A"

    def test_weak_hold(self):
        decoded = make_signal(direction="HOLD", confidence=0.3).decode_direction_confidence()
        assert decoded["strength"] == "weak_hold"


# ═══════════════════════════════════════════════════════════
# 兼容性测试套件骨架
# ═══════════════════════════════════════════════════════════

class TestCompatibilitySuite:
    """
    兼容性测试套件（骨架）

    覆盖 §4.1 版本兼容矩阵、§4.2 字段兼容规则、§4.3 降级策略

    本套件为验收备查，与 TC-01~TC-05 组成完整兼容性验证。
    """

    def test_strategy_A_field_ignore(self):
        """策略A: 字段忽略（Consumer ≥ 信号的 MAJOR 且 < 信号的 MINOR）"""
        result = validate_signal_version("1.1", "1.0")
        assert result["strategy"] == "A"
        assert result["compatible"] is True

    def test_strategy_A_exact_match(self):
        """策略A: 精确匹配"""
        result = validate_signal_version("1.0", "1.0")
        assert result["strategy"] == "A"
        assert result["compatible"] is True

    def test_strategy_B_version_degradation(self):
        """策略B: 版本降级（Consumer MAJOR > 信号 MAJOR）"""
        result = validate_signal_version("1.0", "2.0")
        assert result["strategy"] == "B"
        assert result["compatible"] is True

    def test_strategy_C_rejection(self):
        """策略C: 信号拒绝（Consumer MAJOR < 信号 MAJOR）"""
        result = validate_signal_version("2.0", "1.0")
        assert result["strategy"] == "C"
        assert result["compatible"] is False

    def test_unknown_versions_graceful(self):
        """无法解析的版本号优雅降级"""
        result = validate_signal_version("a.b", "1.0")
        assert result["compatible"] is False
        assert result["strategy"] == "C"


# ═══════════════════════════════════════════════════════════
# 序列化/反序列化异常测试
# ═══════════════════════════════════════════════════════════

class TestSerializationErrors:
    """序列化/反序列化错误路径"""

    def test_invalid_json(self):
        """非法 JSON 字符串"""
        with pytest.raises(SignalSerializeError, match="JSON parse error"):
            deserialize_from_json("{invalid}")

    def test_json_not_object(self):
        """JSON 根不是对象"""
        with pytest.raises(SignalSerializeError, match="must be an object"):
            deserialize_from_json("[1, 2, 3]")

    def test_missing_required_fields(self):
        """缺少必需字段"""
        with pytest.raises(SchemaValidationError, match="V-09"):
            deserialize_from_json(json.dumps({"symbol": "601857"}))

    def test_extras_oversize_rejected_on_serialize(self):
        """extras 超过 64KB 序列化时拒绝"""
        signal = make_signal(extras={"data": "hello-world-" * 8000})
        with pytest.raises(SignalSerializeError, match="extras"):
            serialize_to_json(signal)

    def test_extras_oversize_deserialized_rejected(self):
        """反序列化时 extras 超过 64KB 拒绝"""
        oversized = json.dumps({
            "signal_id": "550e8400-e29b-41d4-a716-446655440000",
            "symbol": "601857",
            "direction": "BUY",
            "confidence": 0.82,
            "horizon": "short",
            "signal_type": "trend",
            "timestamp": "2026-05-20T10:30:00+08:00",
            "protocol_version": "1.0",
            "extras": {"data": "hello-world-" * 8000},
        })
        with pytest.raises(SignalSerializeError, match="extras"):
            deserialize_from_json(oversized)
