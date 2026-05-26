#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S005/config.py — 合规受益链策略配置

包含所有默认参数、权重、路径等配置常量。
所有路径通过 src.config 模块自动解析。

作者: 墨萱 (moxuan)
创建时间: 2026-05-25 10:48 +08:00
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================
# 合规评分五维度权重 (必须凑足 1.00)
# ============================================================

DEFAULT_WEIGHTS: dict[str, float] = {
    "inner_control": 0.25,   # 内控合规投入
    "governance": 0.20,      # 治理结构评分
    "history": 0.20,         # 历史合规记录
    "grey_overlap": 0.20,    # 灰色关联度 (S004联动)
    "transparency": 0.15,    # 信息透明度
}


# ============================================================
# BFS 传导链配置
# ============================================================

BFS_DEFAULT_CONFIG: dict[str, Any] = {
    "top_n_seeds": 10,               # Top-N 种子节点数
    "max_level1_per_seed": 5,         # 每种子 Level-1 最大数
    "max_level2_per_level1": 3,       # 每 Level-1 节点 Level-2 最大数
    "max_level3_per_level2": 3,       # 每 Level-2 节点 Level-3 最大数
    "min_score_threshold": 70.0,      # 种子最小合规评分阈值
    "propagation_decay": 0.6,         # 每级传导置信度衰减系数
    "chain_types": ["direct", "synergy", "systemic"],
    "chain_type_labels": {
        "direct": "Level 1 — 直接受益层",
        "synergy": "Level 2 — 产业链协同层",
        "systemic": "Level 3 — 系统传导层",
    },
}


# ============================================================
# 催化剂信号配置
# ============================================================

CATALYST_SIGNALS_DEFAULT: list[dict[str, Any]] = [
    {
        "signal_id": "QDII_QUOTA",
        "name": "QDII新额度发放",
        "description": "外汇管理局发放新的QDII额度→跨境投资能力提升",
        "direction": "long",       # long / short / neutral
        "default_confidence": 0.4,
        "trigger_type": "event",
        "trigger_condition": "外管局公告新QDII额度",
    },
    {
        "signal_id": "CROSS_BORDER_WECHAT",
        "name": "跨境理财通扩容",
        "description": "粤港澳大湾区跨境理财通试点扩容→北向资金流入增加",
        "direction": "long",
        "default_confidence": 0.3,
        "trigger_type": "event",
        "trigger_condition": "监管机构公告扩容方案",
    },
    {
        "signal_id": "BROKER_MONTHLY",
        "name": "券商月度经营数据",
        "description": "头部券商月报营收/净利润超预期→行业景气上行",
        "direction": "long",
        "default_confidence": 0.25,
        "trigger_type": "periodic",
        "trigger_condition": "每月10日前券商月报披露",
    },
    {
        "signal_id": "SOUTHBOUND_FLOW",
        "name": "港股通资金净流入",
        "description": "南向资金连续净流入→港股活跃度提升",
        "direction": "long",
        "default_confidence": 0.35,
        "trigger_type": "flow",
        "trigger_condition": "南向资金单日净流入>50亿且连续3日",
    },
    {
        "signal_id": "AH_PREMIUM",
        "name": "AH溢价率异常",
        "description": "AH溢价率偏离均值→套利/回归机会",
        "direction": "bidirectional",
        "default_confidence": 0.3,
        "trigger_type": "anomaly",
        "trigger_condition": "AH溢价率>130或<110",
    },
    {
        "signal_id": "REGULATION_ACTION",
        "name": "监管处罚事件",
        "description": "重大行政处罚→合规优胜企业受益",
        "direction": "long",
        "default_confidence": 0.45,
        "trigger_type": "event",
        "trigger_condition": "证监会/交易所重大处罚公告涉及同行业",
    },
    {
        "signal_id": "COMPLIANCE_POLICY",
        "name": "合规新规出台",
        "description": "新合规要求出台→合规成本行业分化",
        "direction": "long",
        "default_confidence": 0.4,
        "trigger_type": "event",
        "trigger_condition": "国务院/央行/证监会新规发布",
    },
]


# ============================================================
# 输出路径
# ============================================================

# 注意: 实际路径在 S005Config 中通过 src.config.PROJECT_ROOT 动态解析
DEFAULT_OUTPUT_DIR = "reports/S005"


# ============================================================
# Mismatch Heatmap 输出配置 (S002 格式对齐 v1.0)
# ============================================================
# 墨衡 2026-05-25 发布的 S002 三线统一格式规范:
# -
#   时间轴：统一日频，按交易日对齐
#   标的池：A50核心池 + 拓展池两级
#   数据粒度：标的-日期-渠道三维
#   输出元组：{date, symbol, channel_type, value}
# -
# 墨萱线输出：
#   mismatch_heatmap_{date}.json
#   内容格式: {date, symbol, channel_pair, mismatch_intensity, z_score}
#   channel_pair 取值与墨衡 channel_type 枚举一致
#
# 对齐完成日期: 2026-05-25
# ============================================================

MISMATCH_HEATMAP_CONFIG: dict[str, Any] = {
    "filename_template": "mismatch_heatmap_{date}.json",
    "version": "1.0",
    "schema": "S002_mismatch_heatmap_v1.0",
    "fields": {
        "date": "String, ISO-8601 日期, 如 '2026-05-25'",
        "symbol": "String, 标的代码, 如 '601398.SH'",
        "channel_pair": "String, 渠道对枚举, 与墨衡 channel_type 一致",
        "mismatch_intensity": "Float, 错配强度 0-100, 基于合规评分偏离基准的程度",
        "z_score": "Float, 标准化 Z-Score, 偏离均值多少个标准差",
    },
    "notes": {
        "aligned_with": "S002_v1_format_20260525",
        "compliant": True,
    },
}

# ============================================================
# S004 接口配置 (Phase1 交付占位 → 5/29 激活)
# ============================================================
# S004 (灰色资金链路由) 接口信息:
# -
#   Phase1 责任人: 墨衡 (5/29 交付路由拓扑+三层打标)
#   Phase2 责任人: 玄知 (接通知后启动渠道变形跟踪)
# -
# 接口格式 (6字段):
#   {route_id, supply_label, demand_label, route_topology, flow_volume, compliance_flag}
# -
# compliance_flag 取值: "compliant" / "grey" / "black"
#
# S005 读取字段:
#   compliance_flag → 映射为合规评分 (compliant=100, grey=40, black=0)
#
# 预期路径:
#   S004 Phase1 输出到 reports/S004/grey_routes_{date}.json
# ============================================================

S004_INTERFACE_CONFIG: dict[str, Any] = {
    "endpoint_type": "file",
    "expected_output_dir": "reports/S004",
    "filename_pattern": "grey_routes_{date}.json",
    "fields": ["route_id", "supply_label", "demand_label", "route_topology", "flow_volume", "compliance_flag"],
    "s005_read_field": "compliance_flag",
    "compliance_mapping": {
        "compliant": 100,
        "grey": 40,
        "black": 0,
    },
    "fallback_on_missing": {
        "mode": "use_latest_available",
        "default_score": 60.0,
        "default_source": "placeholder",
    },
}


# ============================================================
# S005Config 数据类
# ============================================================

@dataclass
class S005Config:
    """S005 合规受益链策略配置"""

    # ── 合规评分权重 ──
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # ── BFS 传导链配置 ──
    bfs_config: dict[str, Any] = field(default_factory=lambda: dict(BFS_DEFAULT_CONFIG))

    # ── 催化剂信号配置 ──
    catalyst_signals: list[dict[str, Any]] = field(
        default_factory=lambda: list(CATALYST_SIGNALS_DEFAULT)
    )

    # ── 输出路径 ──
    output_dir: str = DEFAULT_OUTPUT_DIR

    # ── S004 接口配置 (Phase1 5/29 激活) ──
    s004_grey_overlap_endpoint: str = "reports/S004/grey_routes_{date}.json"
    s004_compliance_mapping: dict[str, float] = field(
        default_factory=lambda: dict(S004_INTERFACE_CONFIG["compliance_mapping"])
    )

    # ── S002 格式对齐 (墨衡 5/25 发布规范) ──
    s002_format_version: str = "v1.0"  # 格式对齐完成日期: 2026-05-25

    # ── 调试与日志 ──
    verbose: bool = False
    dry_run: bool = False

    # ── 派生属性 ──
    @property
    def OUTPUT_DIR(self) -> Path:
        from src.config import PROJECT_ROOT
        return PROJECT_ROOT / self.output_dir

    @property
    def weights_summary(self) -> str:
        parts = [f"{k}={v*100:.0f}%" for k, v in self.weights.items()]
        return " | ".join(parts)

    def validate(self) -> list[str]:
        """验证配置完整性，返回警告列表"""
        warnings: list[str] = []

        # 权重检查
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.001:
            warnings.append(f"权重和不等于1.00 → {total:.4f}")

        required_keys = [
            "inner_control", "governance", "history",
            "grey_overlap", "transparency",
        ]
        for k in required_keys:
            if k not in self.weights:
                warnings.append(f"缺少权重维度: {k}")

        # BFS配置检查
        bfs = self.bfs_config
        if bfs.get("top_n_seeds", 0) <= 0:
            warnings.append("top_n_seeds 必须 > 0")
        if bfs.get("propagation_decay", 1.0) <= 0 or bfs.get("propagation_decay", 0.0) > 1.0:
            warnings.append("propagation_decay 必须在 (0, 1] 范围内")

        return warnings


# ── 默认实例 ──────────────────────────────────────────

default_config = S005Config()
