"""
mozhi_platform.src.backtest.methods.manifest — 合约四件套之 MethodManifest / FACTOR_META

定义方法元信息协议常量及校验工具。

版本: v1 (Phase 1)
更新:
  - v1: 初始定稿 (B7, B14)
  - v1.1: capabilities 扩展 ai_generated + risk_metrics (墨萱 P1 修复, B13)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypeAlias


# ──────────────────────────────────────────────────────────────────────
# B7, B14: MethodManifest / FACTOR_META 协议类型定义
# ──────────────────────────────────────────────────────────────────────

MethodManifest: TypeAlias = Dict[str, Any]
"""方法元信息（Manifest）协议 — 每类方法需定义模块级常量 ``METHOD_META``。

字段说明（Convention-over-Config）:

name:
    方法唯一标识名（小写蛇形，如 "macd", "rsi_reversal"）。
version:
    语义化版本号（如 "1.0.0"）。
description:
    简短的功能描述（≤100 字）。

author (可选):
    方法作者。
created (可选):
    创建日期 ISO 格式。

capabilities:
    能力声明字典。必须包含:

    - long_only (bool): True = 仅做多，False = 可做空。
    - intraday_support (bool): True = 支持盘中信号。
    - requires_state (bool): True = 需要状态持久化。
    - ai_generated (bool, P1 扩展): True = AI 生成，需额外人工审核。
    - risk_metrics (Dict, P1 扩展): 预留风险指标声明。

default_params:
    默认参数字典。
dependencies (可选):
    依赖列表。
tags (可选):
    标签列表。
"""

METHOD_META: MethodManifest = {
    "name": "",
    "version": "",
    "capabilities": {
        "long_only": True,
        "intraday_support": False,
        "requires_state": False,
    },
    "default_params": {},
}
"""
方法元信息参考模板。
子类应覆盖此常量以声明自身元信息。
"""


# ─── 标准字段定义（供校验器 & IDE 补全参考） ────────────

MANIFEST_REQUIRED_FIELDS = {"name", "version", "capabilities", "default_params"}
"""validate_manifest 强制要求存在的顶层字段集合。"""

CAPABILITIES_REQUIRED_FIELDS = {
    "long_only",
    "intraday_support",
    "requires_state",
}
"""capabilities 必须包含的子字段集合（B12 校验用）。"""


# ──────────────────────────────────────────────────────────────────────
# B8: validate_manifest() 校验工具 （墨萱 P1）
# ──────────────────────────────────────────────────────────────────────


def validate_manifest(manifest: Dict[str, Any]) -> List[str]:
    """校验 MethodManifest 协议合规性。

    检查项:
    1. 必要顶层字段存在（name / version / capabilities / default_params）
    2. capabilities 必要子字段（long_only / intraday_support / requires_state）
    3. capabilities 子字段类型正确（bool）

    Args:
        manifest: 待校验的元信息字典。

    Returns:
        List[str]: 错误描述列表。空列表表示完全合规。

    Examples:
        >>> errors = validate_manifest({"name": "macd", "version": "1.0.0",
        ...     "capabilities": {"long_only": True, "intraday_support": False,
        ...                      "requires_state": False},
        ...     "default_params": {"fast": 12}})
        >>> errors
        []
    """
    errors: List[str] = []

    # ── 1. 顶层必要字段 ──────────────────────────────────────────
    for field in MANIFEST_REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f"缺少必要顶层字段: '{field}'")

    # ── 2. capabilities 子字段 ───────────────────────────────────
    capabilities = manifest.get("capabilities", {})
    for field in CAPABILITIES_REQUIRED_FIELDS:
        if field not in capabilities:
            errors.append(
                f"capabilities 缺少必要子字段: '{field}'"
            )
        elif not isinstance(capabilities[field], bool):
            errors.append(
                f"capabilities['{field}'] 必须为 bool 类型，"
                f"收到 {type(capabilities[field]).__name__}"
            )

    return errors


# ──────────────────────────────────────────────────────────────────────
# FACTOR_META 协议（B14）
# ──────────────────────────────────────────────────────────────────────

# FACTOR_META 是因子级的元信息字典，与 METHOD_META 结构相似但更精简。

FACTOR_META: MethodManifest = {
    "name": "",
    "version": "",
    "category": "",
    "default_params": {},
}
"""因子元信息参考模板。子类应覆盖此常量。"""

FACTOR_META_REQUIRED_FIELDS = {"name", "version", "category", "default_params"}
"""FACTOR_META 校验用的必要字段集合。"""


def validate_factor_meta(meta: Dict[str, Any]) -> List[str]:
    """校验 FACTOR_META 协议合规性。

    Args:
        meta: 待校验的因子元信息字典。

    Returns:
        List[str]: 错误描述列表。空列表表示完全合规。
    """
    errors: List[str] = []
    for field in FACTOR_META_REQUIRED_FIELDS:
        if field not in meta:
            errors.append(f"缺少必要因子元字段: '{field}'")
    return errors
