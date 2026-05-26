"""
墨枢信号系统日志底座 (Signal Protocol v1)

功能:
- extras debug.* key 超限预警
- 序列化/反序列化错误记录
- V-13 extras 红线违规记录
- 版本不匹配事件记录

author: 墨衡
created_time: 2026-05-20
"""

import logging
import sys
from typing import Any, Optional

# ── 常量 ──────────────────────────────────────────────────
SIGNAL_LOGGER_NAME = "mozhi.signals"
DEBUG_KEY_MAX_COUNT = 3

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


# ── 日志器初始化 ──────────────────────────────────────────

_signal_logger: logging.Logger = None  # type: ignore


def _ensure_logger() -> logging.Logger:
    """确保信号日志器已初始化（单例模式）"""
    global _signal_logger
    if _signal_logger is None:
        logger = logging.getLogger(SIGNAL_LOGGER_NAME)
        logger.setLevel(logging.DEBUG)

        # 控制台 handler
        if not logger.handlers:
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.INFO)
            ch.setFormatter(logging.Formatter(LOG_FORMAT))
            logger.addHandler(ch)

        _signal_logger = logger
    return _signal_logger


def get_logger(name: str = SIGNAL_LOGGER_NAME) -> logging.Logger:
    """
    获取信号系统日志器

    Args:
        name: 日志器名称（默认使用信号系统统一名称）

    Returns:
        已配置的 logging.Logger 实例
    """
    _ensure_logger()
    return logging.getLogger(name)


# ── 专用日志函数 ─────────────────────────────────────────


def log_extras_debug_warning(
    signal_id: str,
    debug_keys: list[str],
) -> None:
    """
    extras debug.* key 超限预警

    当 extras 中 debug.* 前缀的 key 数量超过 DEBUG_KEY_MAX_COUNT 时调用。

    Args:
        signal_id: 信号 ID
        debug_keys: 超限的 debug.* key 列表
    """
    logger = _ensure_logger()
    logger.warning(
        "extras debug.* key count exceeds limit: %d > %d. keys=%s",
        len(debug_keys),
        DEBUG_KEY_MAX_COUNT,
        debug_keys,
        extra={
            "event": "debug_key_overlimit",
            "signal_id": signal_id,
            "debug_keys": debug_keys,
            "limit": DEBUG_KEY_MAX_COUNT,
        },
    )


def log_serialization_error(
    signal_id: str,
    error: str,
    detail: Optional[str] = None,
) -> None:
    """
    记录序列化错误

    Args:
        signal_id: 信号 ID（如果序列化前已分配）
        error: 错误描述
        detail: 详细上下文信息（可选）
    """
    logger = _ensure_logger()
    logger.error(
        "Signal serialization failed [%s]: %s",
        signal_id,
        error,
        extra={
            "event": "serialization_error",
            "signal_id": signal_id,
            "error": error,
            "detail": detail or "",
        },
    )


def log_deserialization_error(
    source: str,
    error: str,
    detail: Optional[str] = None,
) -> None:
    """
    记录反序列化错误

    Args:
        source: 数据来源描述（如文件名、消息队列 topic）
        error: 错误描述
        detail: 详细上下文信息（可选）
    """
    logger = _ensure_logger()
    logger.error(
        "Signal deserialization failed [source=%s]: %s",
        source,
        error,
        extra={
            "event": "deserialization_error",
            "source": source,
            "error": error,
            "detail": detail or "",
        },
    )


def log_extras_redline_warning(
    signal_id: str,
    redline_type: str,
    key: str,
    detail: str,
) -> None:
    """
    记录 extras 红线违规警告 (V-13)

    Args:
        signal_id: 信号 ID
        redline_type: 红线类型（RED_CORE_SUBSTITUTE / RED_BINARY_LARGEOBJECT /
                       RED_SENSITIVE_INFO / RED_CIRCULAR_REF）
        key: 违规的 extras key
        detail: 违规详情
    """
    logger = _ensure_logger()
    logger.warning(
        "V-13 red-line violation [%s]: key='%s' — %s",
        redline_type,
        key,
        detail,
        extra={
            "event": "extras_redline",
            "signal_id": signal_id,
            "redline_type": redline_type,
            "key": key,
            "detail": detail,
        },
    )


def log_version_mismatch(
    signal_id: str,
    signal_version: str,
    consumer_version: str,
    action: str,
) -> None:
    """
    记录版本不匹配事件

    Args:
        signal_id: 信号 ID
        signal_version: 信号的 protocol_version
        consumer_version: Consumer 支持的协议版本
        action: 处理动作（策略 A/B/C 或其他）
    """
    logger = _ensure_logger()
    logger.warning(
        "Version mismatch: signal v%s, consumer v%s, action=%s",
        signal_version,
        consumer_version,
        action,
        extra={
            "event": "version_mismatch",
            "signal_id": signal_id,
            "signal_version": signal_version,
            "consumer_version": consumer_version,
            "action": action,
        },
    )
