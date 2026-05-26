#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S005/catalyst_signal.py — 催化剂信号库框架

框架功能
--------
1. 信号注册: 预定义催化剂信号模板（QDII/跨境理财通/券商月报/港股通/AH溢价等）
2. 条件触发: 事件驱动 / 周期性 / 资金流 / 异常检测 四种触发模式
3. 置信度评估: 信号匹配时结合传导链信息计算合成置信度
4. 操作建议: 方向（long/short/neutral）+ 强度 + 时效窗口

信号类型
--------
- event      : 事件触发型（大事件公告）
- periodic   : 周期型（定期数据发布）
- flow       : 资金流型（资金流向数据）
- anomaly    : 异常检测型（偏离统计阈值）

信号工作流
----------
  注册信号模板
      ↓
  监控触发条件 (外部数据/事件)
      ↓
  匹配传导链节点 → CatalystMatch
      ↓
  合成置信度 → 操作建议
      ↓
  CatalystMatchReport

TODO:
  - 接入实时数据源（新闻/公告/资金流API）
  - 加入历史触发回测功能

作者: 墨萱 (moxuan)
创建时间: 2026-05-25 10:48 +08:00
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from src.strategies.S005.config import S005Config

logger = logging.getLogger("S005.catalyst_signal")


# ============================================================
# 催化剂信号模板数据结构
# ============================================================

@dataclass
class CatalystSignalTemplate:
    """催化剂信号模板

    定义一种催化剂信号的静态属性。
    """
    signal_id: str
    name: str
    description: str
    direction: str           # long / short / neutral / bidirectional
    default_confidence: float
    trigger_type: str        # event / periodic / flow / anomaly
    trigger_condition: str
    weight_category: str = "medium"   # high / medium / low
    required_data_sources: list[str] = field(default_factory=list)
    validity_window_days: int = 5     # 信号有效窗口

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "name": self.name,
            "description": self.description,
            "direction": self.direction,
            "default_confidence": self.default_confidence,
            "trigger_type": self.trigger_type,
            "trigger_condition": self.trigger_condition,
            "weight_category": self.weight_category,
            "required_data_sources": self.required_data_sources,
            "validity_window_days": self.validity_window_days,
        }


# ============================================================
# 催化剂匹配结果数据类型
# ============================================================

@dataclass
class CatalystMatch:
    """单次催化剂信号匹配结果

    Attributes
    ----------
    signal_id : str
        信号模板ID
    signal_name : str
        信号名称
    target_symbol : str
        匹配到的标的代码
    target_name : str
        匹配标的名
    chain_level : int
        所在BFS链层级 (1-3)
    source_seed : str
        源种子节点
    base_confidence : float
        基础置信度 (来自模板)
    chain_multiplier : float
        传导链置信度乘数
    final_confidence : float
        合成置信度
    direction : str
        操作方向
    direction_confidence : float
        方向置信度
    validity_date : str | None
        有效期
    trigger_reason : str
        触发原因说明
    matched_at : str
        匹配时间戳
    """
    signal_id: str
    signal_name: str
    target_symbol: str
    target_name: str = ""
    chain_level: int = 0
    source_seed: str = ""
    base_confidence: float = 0.0
    chain_multiplier: float = 1.0
    final_confidence: float = 0.0
    direction: str = "neutral"
    direction_confidence: float = 0.0
    validity_date: str | None = None
    trigger_reason: str = ""
    matched_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CatalystMatchReport:
    """催化剂信号匹配报告"""
    run_date: str = ""
    total_signals: int = 0
    matched_count: int = 0
    signals: list[dict] = field(default_factory=list)
    signal_summary: list[dict] = field(default_factory=list)


# ============================================================
# 催化剂信号库
# ============================================================

class CatalystSignalLibrary:
    """催化剂信号库 — 信号注册、触发检测、匹配评估"""

    def __init__(self, config: Optional[S005Config] = None):
        self.config = config or S005Config()
        self._templates: dict[str, CatalystSignalTemplate] = {}
        self._register_defaults()

    # ── 信号注册 ────────────────────────────────────────

    def _register_defaults(self) -> None:
        """注册默认催化剂信号模板"""
        for signal_conf in self.config.catalyst_signals:
            template = CatalystSignalTemplate(
                signal_id=signal_conf["signal_id"],
                name=signal_conf["name"],
                description=signal_conf.get("description", ""),
                direction=signal_conf.get("direction", "neutral"),
                default_confidence=signal_conf.get("default_confidence", 0.3),
                trigger_type=signal_conf.get("trigger_type", "event"),
                trigger_condition=signal_conf.get("trigger_condition", ""),
                weight_category=signal_conf.get("weight_category", "medium"),
                required_data_sources=signal_conf.get("required_data_sources", []),
                validity_window_days=signal_conf.get("validity_window_days", 5),
            )
            self._templates[template.signal_id] = template

    def register_signal(self, template: CatalystSignalTemplate) -> None:
        """注册自定义信号模板"""
        self._templates[template.signal_id] = template
        logger.info(f"注册催化剂信号: {template.signal_id} — {template.name}")

    def list_signals(self) -> list[dict[str, Any]]:
        """列出所有注册信号"""
        return [t.to_dict() for t in self._templates.values()]

    def get_signal(self, signal_id: str) -> CatalystSignalTemplate | None:
        """获取单个信号模板"""
        return self._templates.get(signal_id)

    # ── 匹配 ────────────────────────────────────────────

    def match_all(
        self,
        run_date: date | None = None,
        bfs_report: Any = None,
    ) -> CatalystMatchReport:
        """对所有已注册信号进行触发匹配

        当前为模拟匹配：检查BFS传导链中各节点是否
        与催化剂信号存在关联关系。

        实际实现需对接：
          - 新闻/公告实时推送
          - 资金流数据（港股通）
          - 监管公告（处罚/新规）
          - 券商月报数据
          - AH溢价数据
          - QDII额度公告
        """
        run_date = run_date or date.today()
        matches: list[CatalystMatch] = []

        # 没有BFS传导链 → 无匹配
        if bfs_report is None:
            logger.info("无BFS传导链数据，催化剂匹配跳过")
            return CatalystMatchReport(run_date=run_date.isoformat())

        # 提取各级标的
        level_tickers = self._extract_bfs_tickers(bfs_report)

        for signal_id, template in self._templates.items():
            # 对每个信号检查传导链中是否有匹配标
            signal_matches = self._check_signal_match(
                template=template,
                bfs_tickers=level_tickers,
                run_date=run_date,
            )
            matches.extend(signal_matches)

        return self._build_report(run_date, matches)

    def _check_signal_match(
        self,
        template: CatalystSignalTemplate,
        bfs_tickers: dict[int, list[dict]],
        run_date: date,
    ) -> list[CatalystMatch]:
        """检查单个信号在传导链中的匹配

        模拟实现：按信号类型随机匹配 Level 1 和 Level 2 节点。
        实际应依赖外部触发条件判断。
        """
        matches: list[CatalystMatch] = []
        signal_id = template.signal_id

        # 检查各层级标的（仅匹配Level1和Level2的实际标的，不匹配mock标的）
        for level in [1, 2]:
            tickers = bfs_tickers.get(level, [])

            # 根据信号类型确定匹配条件
            match_indices = self._get_mock_match_indices(signal_id, tickers)

            for idx in match_indices:
                ticker = tickers[idx]
                symbol = ticker.get("symbol", "")

                # 只匹配真实标的（非mock）
                if symbol.startswith("MOCK_"):
                    continue

                base_confidence = template.default_confidence
                # Level 1 信号更强，Level 2 衰减
                level_multiplier = 1.0 if level == 1 else 0.6
                chain_multiplier = ticker.get("confidence", 0.6)

                final_confidence = min(1.0, base_confidence * level_multiplier * chain_multiplier)

                validity = (run_date + timedelta(days=template.validity_window_days)).isoformat()

                match = CatalystMatch(
                    signal_id=signal_id,
                    signal_name=template.name,
                    target_symbol=symbol,
                    target_name=ticker.get("name", symbol),
                    chain_level=level,
                    source_seed=ticker.get("source_seed", ""),
                    base_confidence=base_confidence,
                    chain_multiplier=round(chain_multiplier, 4),
                    final_confidence=round(final_confidence, 4),
                    direction=template.direction if template.direction != "bidirectional"
                    else self._infer_direction(symbol),
                    direction_confidence=round(final_confidence * 0.8, 4),
                    validity_date=validity,
                    trigger_reason=self._get_trigger_reason(template, level, symbol),
                    matched_at=datetime.now().isoformat(),
                )
                matches.append(match)

        return matches

    def _extract_bfs_tickers(
        self, bfs_report: Any
    ) -> dict[int, list[dict]]:
        """从 BFSChainReport 提取各层级标的"""
        tickers: dict[int, list[dict]] = {1: [], 2: [], 3: []}

        if hasattr(bfs_report, "top_level1_tickers"):
            tickers[1] = bfs_report.top_level1_tickers
            tickers[2] = bfs_report.top_level2_tickers
            tickers[3] = bfs_report.top_level3_tickers
        elif isinstance(bfs_report, dict):
            tickers[1] = bfs_report.get("top_level1_tickers", [])
            tickers[2] = bfs_report.get("top_level2_tickers", [])
            tickers[3] = bfs_report.get("top_level3_tickers", [])

        return tickers

    # ── 辅助方法 ────────────────────────────────────────

    def _get_mock_match_indices(
        self,
        signal_id: str,
        tickers: list[dict],
    ) -> list[int]:
        """模拟匹配索引（后续替换为实际匹配逻辑）

        优先匹配真实标的（非MOCK_开头），
        每个信号至少匹配1个节点。
        """
        import hashlib

        if not tickers:
            return []

        # 分离真实标的和MOCK标的
        real_indices = [i for i, t in enumerate(tickers)
                        if not t.get("symbol", "").startswith("MOCK_")]
        mock_indices = [i for i, t in enumerate(tickers)
                        if t.get("symbol", "").startswith("MOCK_")]

        signal_seed = sum(ord(c) for c in signal_id)

        # 优先匹配真实标的
        if real_indices:
            count = min(len(real_indices), 1 + (signal_seed % min(3, len(real_indices))))
            indices = [real_indices[(signal_seed + i) % len(real_indices)]
                       for i in range(count)]
        elif mock_indices:
            count = min(len(mock_indices), 1 + (signal_seed % 2))
            indices = [mock_indices[(signal_seed + i) % len(mock_indices)]
                       for i in range(count)]
        else:
            return []

        return list(set(indices))

    def _infer_direction(self, symbol: str) -> str:
        """双向信号的方向推断"""
        import hashlib
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        return "long" if (seed % 3) < 2 else "short"

    @staticmethod
    def _get_trigger_reason(
        template: CatalystSignalTemplate,
        level: int,
        symbol: str,
    ) -> str:
        """生成信号触发原因说明"""
        level_label = {1: "直接受益层", 2: "产业链协同层", 3: "系统传导层"}.get(level, f"Level{level}")
        return (
            f"{template.name} 触发条件: {template.trigger_condition} | "
            f"传导层级: {level_label} | 匹配标的: {symbol}"
        )

    def _build_report(
        self,
        run_date: date,
        matches: list[CatalystMatch],
    ) -> CatalystMatchReport:
        """构建匹配报告"""
        signal_list = sorted(
            [m for m in matches],
            key=lambda m: m.final_confidence,
            reverse=True,
        )

        signals = [
            {
                "signal_id": m.signal_id,
                "signal_name": m.signal_name,
                "target_symbol": m.target_symbol,
                "target_name": m.target_name,
                "chain_level": m.chain_level,
                "source_seed": m.source_seed,
                "base_confidence": m.base_confidence,
                "chain_multiplier": m.chain_multiplier,
                "final_confidence": m.final_confidence,
                "direction": m.direction,
                "direction_confidence": m.direction_confidence,
                "validity_date": m.validity_date,
                "trigger_reason": m.trigger_reason,
            }
            for m in signal_list
        ]

        # 按信号类型汇总
        signal_summary = self._build_summary(matches)

        return CatalystMatchReport(
            run_date=run_date.isoformat(),
            total_signals=len(self._templates),
            matched_count=len(signals),
            signals=signals,
            signal_summary=signal_summary,
        )

    @staticmethod
    def _build_summary(matches: list[CatalystMatch]) -> list[dict]:
        """按信号ID汇总"""
        from collections import Counter

        signal_counts: dict[str, dict] = {}
        for m in matches:
            if m.signal_id not in signal_counts:
                signal_counts[m.signal_id] = {
                    "signal_id": m.signal_id,
                    "signal_name": m.signal_name,
                    "match_count": 0,
                    "avg_confidence": 0.0,
                    "directions": Counter(),
                }
            sc = signal_counts[m.signal_id]
            sc["match_count"] += 1
            sc["avg_confidence"] += m.final_confidence
            sc["directions"][m.direction] += 1

        return [
            {
                "signal_id": sc["signal_id"],
                "signal_name": sc["signal_name"],
                "match_count": sc["match_count"],
                "avg_confidence": round(sc["avg_confidence"] / sc["match_count"], 4),
                "direction_distribution": dict(sc["directions"]),
            }
            for sc in signal_counts.values()
        ]


# ── 测试入口 ──────────────────────────────────────────

def demo() -> None:
    """演示催化剂信号匹配"""
    from src.strategies.S005.compliance_scorer import ComplianceScorer
    from src.strategies.S005.bfs_chain import BFSChainEngine

    scorer = ComplianceScorer()
    compliance_report = scorer.score_all()

    engine = BFSChainEngine()
    bfs_report = engine.build_chain(compliance_report)

    lib = CatalystSignalLibrary()
    match_report = lib.match_all(bfs_report=bfs_report)

    print("=" * 60)
    print("S005 催化剂信号匹配演示")
    print("=" * 60)
    print(f"运行日期: {match_report.run_date}")
    print(f"注册信号数: {match_report.total_signals}")
    print(f"匹配成功数: {match_report.matched_count}")

    print(f"\n信号匹配明细:")
    print(f"{'信号ID':<20} {'标的':<15} {'层级':<6} {'置信度':<10} {'方向':<8}")
    print("-" * 62)
    for s in match_report.signals[:10]:
        print(f"{s['signal_id']:<20} "
              f"{s['target_symbol']:<15} "
              f"L{s['chain_level']:<5} "
              f"{s['final_confidence']:<10.3f} "
              f"{s['direction']:<8}")

    print(f"\n信号汇总:")
    for sm in match_report.signal_summary:
        print(f"  {sm['signal_name']:<18} {sm['match_count']}次匹配 "
              f"avg置信度:{sm['avg_confidence']:.3f} "
              f"方向:{sm['direction_distribution']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
