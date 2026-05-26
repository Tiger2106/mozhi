#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S005/bfs_chain.py — BFS 三级传导链引擎

算法: BFS (广度优先搜索) 传导链

从合规评分 Top-10 种子节点出发，通过产业链关系
向外扩展三级传导：

  Level 1 — 直接受益层
    竞争对手退出 → 市场份额集中 (competitor_retreat)
    监管处罚同行业 → 合规优势企业受益 (peer_penalty)
    行业准入壁垒提升 → 存量玩家受益 (entry_barrier)

  Level 2 — 产业链协同层
    供应商传导: 合规要求向上游传递，高合规企业优先获得订单
    战略客户传导: 客户因监管压力转向合规供应商
    技术合作传导: 合规标准提升带动合作方升级

  Level 3 — 系统传导层
    IT系统改造: 金融机构合规系统升级需求
    合规咨询服务: 第三方合规审计/咨询需求
    金融IT/风控科技: 科技赋能合规管理

数据链路
---------
  ScoringPhase         → BFSNode → BFSChain → BFSChainReport
  (ComplianceScorer)     (节点)     (链路)      (报告)

TODO:
  - 接入产业链图谱数据 (知识图谱)
  - 接入S004灰色资金链路路由

作者: 墨萱 (moxuan)
创建时间: 2026-05-25 10:48 +08:00
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from src.strategies.S005.config import S005Config

logger = logging.getLogger("S005.bfs_chain")


# ============================================================
# BFS 节点与链结构
# ============================================================

@dataclass
class BFSNode:
    """BFS传导链节点

    Attributes
    ----------
    id : str
        节点唯一标识
    symbol : str
        标的代码
    name : str
        节点名
    level : int
        层级 (0=种子, 1=直接受益, 2=产业链协同, 3=系统传导)
    chain_type : str
        链类型 (direct|synergy|systemic)
    source_seed : str
        来源种子节点symbol
    parent_id : str | None
        父节点id
    compliance_score : float
        源节点合规评分 (种子才有)
    confidence : float
        传导置信度 (0-1)
    propagation_path : list[str]
        传导路径 [symbol1, symbol2, ...]
    chain_layers : int
        从种子到此节点的层级数
    """
    id: str
    symbol: str
    name: str = ""
    level: int = 0
    chain_type: str = "direct"
    source_seed: str = ""
    parent_id: str | None = None
    compliance_score: float = 0.0
    confidence: float = 1.0
    propagation_path: list[str] = field(default_factory=list)
    chain_layers: int = 0

    @property
    def chain_level_label(self) -> str:
        labels = {
            0: "种子节点",
            1: "Level 1 — 直接受益层",
            2: "Level 2 — 产业链协同层",
            3: "Level 3 — 系统传导层",
        }
        return labels.get(self.level, f"Level {self.level}")


@dataclass
class BFSChain:
    """单条传导链路"""
    root_seed: str                # 种子节点symbol
    root_score: float              # 种子合规评分
    node_ids: list[str] = field(default_factory=list)
    effective_confidence: float = 1.0
    propagation_decay: float = 0.6
    levels_achieved: int = 0


@dataclass
class BFSChainReport:
    """BFS传导链报告"""
    run_date: str = ""
    total_nodes: int = 0
    seed_count: int = 0
    level1_count: int = 0
    level2_count: int = 0
    level3_count: int = 0
    chains: list[BFSChain] = field(default_factory=list)
    nodes: list[dict] = field(default_factory=list)
    top_level1_tickers: list[dict] = field(default_factory=list)
    top_level2_tickers: list[dict] = field(default_factory=list)
    top_level3_tickers: list[dict] = field(default_factory=list)


# ============================================================
# BFS 传导链引擎
# ============================================================

class BFSChainEngine:
    """BFS三级传导链引擎

    从合规评分Top-10种子节点出发，BFS扩展至三级传导链。
    每级传导置信度按衰减系数递减，低于阈值则剪枝。
    """

    def __init__(self, config: Optional[S005Config] = None):
        self.config = config or S005Config()
        self._node_counter: int = 0

    # ── 构建传导链 ──────────────────────────────────────

    def build_chain(
        self,
        compliance_scores: Any,
        run_date: date | None = None,
    ) -> BFSChainReport:
        """BFS构建完整传导链

        Parameters
        ----------
        compliance_scores : ComplianceReport
            合规评分报告（来自 ComplianceScorer）
        run_date : date | None

        Returns
        -------
        BFSChainReport
        """
        run_date = run_date or date.today()
        self._node_counter = 0

        bfs_config = self.config.bfs_config
        top_n = bfs_config.get("top_n_seeds", 10)
        threshold = bfs_config.get("min_score_threshold", 70.0)
        decay = bfs_config.get("propagation_decay", 0.6)

        # ── 提取种子节点 ──
        seeds = self._extract_seeds(compliance_scores, top_n, threshold)
        if not seeds:
            logger.warning("无合规评分≥阈值的种子节点，BFS跳过")
            return BFSChainReport(run_date=run_date.isoformat())

        logger.info(f"种子节点数: {len(seeds)} (Top-{top_n}, 阈值≥{threshold})")

        # ── BFS遍历 ──
        all_nodes: dict[str, BFSNode] = {}
        chains: list[BFSChain] = []
        visited: set[str] = set()

        for seed in seeds:
            chain = BFSChain(
                root_seed=seed["symbol"],
                root_score=seed["total_score"],
                propagation_decay=decay,
            )
            self._bfs_from_seed(
                seed=seed,
                chain=chain,
                all_nodes=all_nodes,
                visited=visited,
                bfs_config=bfs_config,
            )
            chain.effective_confidence = decay ** min(3, chain.levels_achieved)
            chains.append(chain)

        # ── 构建报告 ──
        report = self._build_report(run_date, all_nodes, chains)
        logger.info(
            f"BFS完成: {report.total_nodes} 节点 | "
            f"种子{report.seed_count} → "
            f"Level1 {report.level1_count} → "
            f"Level2 {report.level2_count} → "
            f"Level3 {report.level3_count}"
        )
        return report

    # ── BFS 核心算法 ── ────────────────────────────────

    def _bfs_from_seed(
        self,
        seed: dict[str, Any],
        chain: BFSChain,
        all_nodes: dict[str, BFSNode],
        visited: set[str],
        bfs_config: dict[str, Any],
    ) -> None:
        """从单个种子出发BFS扩展

        BFS队列: (symbol, level, path, confidence)
        """
        decay = bfs_config.get("propagation_decay", 0.6)
        max_l1 = bfs_config.get("max_level1_per_seed", 5)
        max_l2 = bfs_config.get("max_level2_per_level1", 3)
        max_l3 = bfs_config.get("max_level3_per_level2", 3)

        symbol = seed["symbol"]
        if symbol in visited:
            return

        # ── 创建种子节点 ──
        seed_node = self._make_node(
            symbol=symbol,
            name=symbol,
            level=0,
            chain_type="seed",
            source_seed=symbol,
            compliance_score=seed["total_score"],
            confidence=1.0,
            propagation_path=[symbol],
            chain_layers=0,
        )
        all_nodes[seed_node.id] = seed_node
        visited.add(symbol)
        chain.node_ids.append(seed_node.id)

        # ── BFS队列 ──
        queue = deque()
        queue.append((symbol, 1, [symbol], 1.0))

        level_counts = {1: 0, 2: 0, 3: 0}

        while queue:
            current_symbol, level, path, confidence = queue.popleft()

            if level > 3:
                continue

            # 获取当前层级最大扩展数
            max_expand = {1: max_l1, 2: max_l2, 3: max_l3}.get(level, 1)

            if level_counts[level] >= max_expand:
                continue

            # ── 获取邻接节点（模拟/外部数据）──
            neighbors = self._get_neighbors(
                current_symbol, level, bfs_config
            )

            for neighbor in neighbors:
                neighbor_symbol = neighbor["symbol"]

                # 去重
                if neighbor_symbol in visited:
                    continue

                visited.add(neighbor_symbol)
                level_counts[level] += 1

                new_path = path + [neighbor_symbol]
                new_confidence = confidence * decay

                # 链类型
                chain_type = {1: "direct", 2: "synergy", 3: "systemic"}.get(level, "unknown")

                # 创建节点
                node = self._make_node(
                    symbol=neighbor_symbol,
                    name=neighbor.get("name", neighbor_symbol),
                    level=level,
                    chain_type=chain_type,
                    source_seed=symbol,
                    parent_id=f"bfs_{current_symbol}_{level - 1}",
                    compliance_score=seed.get("total_score", 0),
                    confidence=new_confidence,
                    propagation_path=new_path,
                    chain_layers=level,
                )
                all_nodes[node.id] = node
                chain.node_ids.append(node.id)
                chain.levels_achieved = max(chain.levels_achieved, level)

                # BFS继续扩展下一级
                queue.append((neighbor_symbol, level + 1, new_path, new_confidence))

                # 已达该层最大数，不再扩展
                if level_counts[level] >= max_expand:
                    break

        # 更新种子节点的链信息
        seed_node.propagation_path = [symbol]  # type: ignore[possibly-undefined]

    # ── 邻接节点获取 ─────────────────────────────────────

    def _get_neighbors(
        self,
        symbol: str,
        level: int,
        bfs_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """获取某节点的邻接标的

        Parameters
        ----------
        symbol : str
        level : int
            传到的层级 (1=直接受益, 2=产业链协同, 3=系统传导)
        bfs_config : dict

        Returns
        -------
        list[dict]
            [{"symbol": "...", "name": "..."}, ...]

        TODO: 接入产业链知识图谱数据源
        """
        if level == 1:
            return self._mock_level1_neighbors(symbol)
        elif level == 2:
            return self._mock_level2_neighbors(symbol)
        elif level == 3:
            return self._mock_level3_neighbors(symbol)
        return []

    # ── 模拟邻接数据（各层级） ──────────────────────────

    def _mock_level1_neighbors(self, symbol: str) -> list[dict]:
        """模拟 Level 1 — 直接受益层

        类型: 同行业竞争对手、替代品提供方
        逻辑: 竞争对手退出/受罚 → 市场份额向合规优势企业集中
        """
        # 同行业映射
        peer_map = {
            "601398.SH": [  # 工商银行 → 其他银行
                {"symbol": "601939.SH", "name": "建设银行"},
                {"symbol": "601288.SH", "name": "农业银行"},
                {"symbol": "600036.SH", "name": "招商银行"},
                {"symbol": "601166.SH", "name": "兴业银行"},
            ],
            "600030.SH": [  # 中信证券 → 其他券商
                {"symbol": "601688.SH", "name": "华泰证券"},
                {"symbol": "600837.SH", "name": "海通证券"},
                {"symbol": "601211.SH", "name": "国泰君安"},
            ],
            "601318.SH": [  # 中国平安 → 保险/金控
                {"symbol": "601601.SH", "name": "中国太保"},
                {"symbol": "601628.SH", "name": "中国人寿"},
            ],
        }
        return peer_map.get(symbol, [
            {"symbol": f"MOCK_L1_{symbol.replace('.', '_')}_1", "name": f"同业竞争者({symbol})"},
            {"symbol": f"MOCK_L1_{symbol.replace('.', '_')}_2", "name": f"替代品提供商({symbol})"},
        ])

    def _mock_level2_neighbors(self, symbol: str) -> list[dict]:
        """模拟 Level 2 — 产业链协同层

        类型: 核心供应商、战略客户、技术合作伙伴
        逻辑: 上游供应商因合规传导受益、下游客户转向高合规供应商
        """
        client_map = {
            "601398.SH": [  # 银行的上游: IT服务商、战略客户
                {"symbol": "600570.SH", "name": "恒生电子(金融IT)"},
                {"symbol": "002410.SZ", "name": "广联达(银行软件)"},
                {"symbol": "600588.SH", "name": "用友网络(企业服务)"},
            ],
            "600030.SH": [  # 券商的上游
                {"symbol": "600570.SH", "name": "恒生电子(券商IT)"},
                {"symbol": "600271.SH", "name": "航天信息(金融科技)"},
            ],
        }
        return client_map.get(symbol, [
            {"symbol": f"MOCK_L2_{symbol.replace('.', '_')}_1", "name": f"供应商链({symbol})"},
            {"symbol": f"MOCK_L2_{symbol.replace('.', '_')}_2", "name": f"战略客户({symbol})"},
            {"symbol": f"MOCK_L2_{symbol.replace('.', '_')}_3", "name": f"合作伙伴({symbol})"},
        ])

    def _mock_level3_neighbors(self, symbol: str) -> list[dict]:
        """模拟 Level 3 — 系统传导层

        类型: 金融IT改造、合规咨询、风控科技
        逻辑: 监管趋严 → 金融机构合规投入增加 → 相关服务商受益
        """
        # 系统级受益标的
        systemic_map = {
            "600570.SH": [
                {"symbol": "600570.SH", "name": "恒生电子(合规IT系统)"},
            ],
            "default": [
                {"symbol": "002439.SZ", "name": "启明星辰(安全合规)"},
                {"symbol": "300454.SZ", "name": "深信服(安全服务)"},
                {"symbol": "688111.SH", "name": "金山办公(文档合规)"},
            ],
        }
        result = systemic_map.get(symbol, systemic_map["default"])
        return result[:3]  # 最多3个

    # ── 辅助方法 ────────────────────────────────────────

    def _make_node(
        self,
        symbol: str,
        name: str,
        level: int,
        chain_type: str,
        source_seed: str,
        compliance_score: float,
        confidence: float,
        propagation_path: list[str],
        chain_layers: int,
        parent_id: str | None = None,
    ) -> BFSNode:
        """创建 BFS 节点"""
        self._node_counter += 1
        return BFSNode(
            id=f"bfs_{self._node_counter:04d}",
            symbol=symbol,
            name=name,
            level=level,
            chain_type=chain_type,
            source_seed=source_seed,
            parent_id=parent_id,
            compliance_score=compliance_score,
            confidence=round(confidence, 4),
            propagation_path=propagation_path,
            chain_layers=chain_layers,
        )

    def _extract_seeds(
        self,
        compliance_scores: Any,
        top_n: int,
        threshold: float,
    ) -> list[dict[str, Any]]:
        """从合规评分报告中提取种子节点

        筛选: 综合评分 ≥ threshold, 取 Top-N
        """
        # 支持 ComplianceReport 对象和 dict
        if hasattr(compliance_scores, "top_scores"):
            top_scores = compliance_scores.top_scores
        elif isinstance(compliance_scores, dict):
            top_scores = compliance_scores.get("top_scores", [])
        else:
            top_scores = []

        seeds = [s for s in top_scores if s.get("total_score", 0) >= threshold]
        return seeds[:top_n]

    def _build_report(
        self,
        run_date: date,
        all_nodes: dict[str, BFSNode],
        chains: list[BFSChain],
    ) -> BFSChainReport:
        """构建 BFSChainReport"""
        nodes_list = sorted(all_nodes.values(), key=lambda n: (n.level, n.symbol))

        level_counts = {1: 0, 2: 0, 3: 0}
        for node in nodes_list:
            if node.level in level_counts:
                level_counts[node.level] += 1

        # 按层级构建摘要
        def extract_tickers(level: int) -> list[dict]:
            return [
                {
                    "symbol": n.symbol,
                    "name": n.name,
                    "confidence": n.confidence,
                    "path": "→".join(n.propagation_path),
                }
                for n in nodes_list if n.level == level
            ]

        return BFSChainReport(
            run_date=run_date.isoformat(),
            total_nodes=len(all_nodes),
            seed_count=sum(1 for n in nodes_list if n.level == 0),
            level1_count=level_counts[1],
            level2_count=level_counts[2],
            level3_count=level_counts[3],
            chains=chains,
            nodes=[
                {
                    "id": n.id,
                    "symbol": n.symbol,
                    "name": n.name,
                    "level": n.level,
                    "chain_type": n.chain_type,
                    "confidence": n.confidence,
                    "path": "→".join(n.propagation_path),
                    "source_seed": n.source_seed,
                }
                for n in nodes_list
            ],
            top_level1_tickers=extract_tickers(1),
            top_level2_tickers=extract_tickers(2),
            top_level3_tickers=extract_tickers(3),
        )


# ── 测试入口 ──────────────────────────────────────────

def demo() -> None:
    """演示 BFS 传导链构建"""
    from src.strategies.S005.compliance_scorer import ComplianceScorer

    scorer = ComplianceScorer()
    report = scorer.score_all()

    engine = BFSChainEngine()
    bfs_report = engine.build_chain(report)

    print("=" * 60)
    print("S005 BFS 传导链演示")
    print("=" * 60)
    print(f"运行日期: {bfs_report.run_date}")
    print(f"总节点数: {bfs_report.total_nodes}")
    print(f"种子节点: {bfs_report.seed_count}")
    print(f"Level 1 (直接受益): {bfs_report.level1_count}")
    print(f"Level 2 (产业链协同): {bfs_report.level2_count}")
    print(f"Level 3 (系统传导): {bfs_report.level3_count}")
    print(f"\n传导链数: {len(bfs_report.chains)}")

    print(f"\nLevel 1 标的 (直接受益):")
    for t in bfs_report.top_level1_tickers[:5]:
        print(f"  {t['symbol']:<18} 置信度:{t['confidence']:.3f}  {t['name']}")

    print(f"\nLevel 2 标的 (产业链协同):")
    for t in bfs_report.top_level2_tickers[:5]:
        print(f"  {t['symbol']:<18} 置信度:{t['confidence']:.3f}  {t['name']}")

    print(f"\nLevel 3 标的 (系统传导):")
    for t in bfs_report.top_level3_tickers[:5]:
        print(f"  {t['symbol']:<18} 置信度:{t['confidence']:.3f}  {t['name']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
