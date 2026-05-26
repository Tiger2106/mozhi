"""
S004 Phase2: 渠道变形跟踪模块
玄知 | 2026-05-25
Phase2 v1

基于 Jaccard(节点集) + 图编辑距离综合评分，监测已知渠道的模式变异。
"""

import json
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
import math


@dataclass
class ChannelSnapshot:
    """渠道快照——某个时点渠道的完整拓扑结构"""
    channel_id: str
    date: str                          # YYYY-MM-DD
    node_set: Set[str]                 # 渠道涉及的所有法人/账户/服务商节点
    edge_list: List[Tuple[str, str]]   # 有向边列表 [("节点A","节点B"), ...]
    layer_structure: List[str]         # 层级结构描述
    attributes: Dict[str, float]       # 关键属性（交易频率、穿透度等）


@dataclass
class DeformationScore:
    """渠道变形评分"""
    channel_id: str
    base_date: str                     # 基准快照日期
    compare_date: str                  # 对比快照日期
    jaccard_similarity: float          # Jaccard相似度 [0,1]
    graph_edit_distance: float         # 图编辑距离（归一化）[0,1]
    composite_score: float             # 综合变形评分 [0,1]
    deformation_type: Optional[str]    # 变形类型：壳公司变更|嵌套结构变化|账户替换|新渠道出现
    flagged: bool                      # 是否触发警报


class DeformationTracker:
    """
    渠道变形跟踪引擎
    算法：Jaccard(节点集系数) + 图编辑距离加权综合评分
    """

    # 警报阈值
    JACCARD_ALERT_THRESHOLD = 0.6      # Jaccard < 0.6 触发变形警报
    GRAPH_EDIT_ALERT_THRESHOLD = 0.5   # 图编辑距离 > 0.5 触发变形警报
    COMPOSITE_ALERT_THRESHOLD = 0.55   # 综合评分 > 0.55 触发警报

    # Jaccard vs 图编辑距离的权重
    W_JACCARD = 0.4
    W_GRAPH = 0.6

    def __init__(self, gray_list_path: Optional[str] = None):
        self._gray_list: Dict[str, ChannelSnapshot] = {}  # channel_id -> 最新快照
        self._history: List[Dict] = []                     # 变形检测历史
        self._gray_list_path = gray_list_path
        if gray_list_path:
            self._load_gray_list()

    def _load_gray_list(self):
        """从文件加载灰名单渠道表"""
        try:
            with open(self._gray_list_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data:
                snap = ChannelSnapshot(
                    channel_id=entry["channel_id"],
                    date=entry["date"],
                    node_set=set(entry["node_set"]),
                    edge_list=[tuple(e) for e in entry.get("edge_list", [])],
                    layer_structure=entry.get("layer_structure", []),
                    attributes=entry.get("attributes", {})
                )
                self._gray_list[entry["channel_id"]] = snap
        except (FileNotFoundError, json.JSONDecodeError):
            self._gray_list = {}

    def save_gray_list(self, path: Optional[str] = None):
        """保存灰名单渠道表至文件"""
        save_path = path or self._gray_list_path
        if not save_path:
            return
        data = []
        for cid, snap in self._gray_list.items():
            data.append({
                "channel_id": cid,
                "date": snap.date,
                "node_set": list(snap.node_set),
                "edge_list": snap.edge_list,
                "layer_structure": snap.layer_structure,
                "attributes": snap.attributes
            })
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ─── Jaccard 节点集相似度 ─────────────────────────────────

    def _jaccard_similarity(self, set_a: Set[str], set_b: Set[str]) -> float:
        """计算两个节点集的Jaccard相似度"""
        intersection = set_a & set_b
        union = set_a | set_b
        if not union:
            return 1.0  # 两个空集视为完全一致
        return len(intersection) / len(union)

    # ─── 图编辑距离（简化版） ───────────────────────────────

    def _graph_edit_distance_normalized(
        self,
        edges_a: List[Tuple[str, str]],
        edges_b: List[Tuple[str, str]]
    ) -> float:
        """
        计算归一化图编辑距离
        使用边集对称差 / 边集总大小 作为近似
        """
        set_a = set(edges_a)
        set_b = set(edges_b)
        symmetric_diff = len(set_a ^ set_b)
        total = len(set_a | set_b)
        if total == 0:
            return 0.0
        return symmetric_diff / total

    # ─── 变形类型判定 ───────────────────────────────────────

    def _classify_deformation(
        self,
        old_snap: ChannelSnapshot,
        new_snap: ChannelSnapshot,
        jaccard: float,
        ged: float
    ) -> str:
        """判定变形类型"""
        # 检查是否有新节点类型
        new_nodes = new_snap.node_set - old_snap.node_set
        removed_nodes = old_snap.node_set - new_snap.node_set

        # 壳公司变更：节点大量替换但层级结构相似
        if jaccard < 0.5 and len(new_nodes) > 0 and len(removed_nodes) > 0:
            structure_similar = (
                len(old_snap.layer_structure) == len(new_snap.layer_structure)
            )
            if structure_similar:
                return "壳公司变更"

        # 嵌套结构变化：Jaccard尚可但边关系变化大
        if jaccard >= 0.5 and ged > 0.5:
            return "嵌套结构变化"

        # 账户替换：少量节点替换，结构基本不变
        if jaccard >= 0.6 and ged <= 0.4 and (len(new_nodes) > 0 or len(removed_nodes) > 0):
            return "账户替换"

        # 新渠道出现：全新节点集
        if jaccard < 0.3 and len(new_nodes) / max(len(new_snap.node_set), 1) > 0.7:
            return "新渠道出现"

        return "结构微调" if jaccard < self.JACCARD_ALERT_THRESHOLD else None

    # ─── 主检测方法 ─────────────────────────────────────────

    def detect_deformation(
        self,
        old_snapshot: ChannelSnapshot,
        new_snapshot: ChannelSnapshot
    ) -> DeformationScore:
        """
        对单个渠道的两个时间点快照进行变形检测
        返回综合变形评分及警报标记
        """
        # Jaccard相似度
        jaccard = self._jaccard_similarity(old_snapshot.node_set, new_snapshot.node_set)

        # 图编辑距离
        ged = self._graph_edit_distance_normalized(old_snapshot.edge_list, new_snapshot.edge_list)

        # 综合评分（加权和，越高变形越严重）
        composite = self.W_JACCARD * (1 - jaccard) + self.W_GRAPH * ged

        # 判定类型
        dtype = self._classify_deformation(old_snapshot, new_snapshot, jaccard, ged)

        # 是否触发警报
        flagged = (
            jaccard < self.JACCARD_ALERT_THRESHOLD
            or ged > self.GRAPH_EDIT_ALERT_THRESHOLD
            or composite > self.COMPOSITE_ALERT_THRESHOLD
        )

        return DeformationScore(
            channel_id=old_snapshot.channel_id,
            base_date=old_snapshot.date,
            compare_date=new_snapshot.date,
            jaccard_similarity=round(jaccard, 4),
            graph_edit_distance=round(ged, 4),
            composite_score=round(composite, 4),
            deformation_type=dtype,
            flagged=flagged
        )

    def batch_detect(
        self,
        snapshots: Dict[str, ChannelSnapshot]
    ) -> List[DeformationScore]:
        """
        批量检测：将新快照与灰名单基准对比
        返回所有变形检测结果（含警报标记）
        """
        results = []

        for channel_id, new_snap in snapshots.items():
            if channel_id in self._gray_list:
                old_snap = self._gray_list[channel_id]
                score = self.detect_deformation(old_snap, new_snap)
                results.append(score)

        return results

    def update_gray_list(
        self,
        new_snapshots: Dict[str, ChannelSnapshot],
        auto_downgrade: bool = True
    ) -> List[DeformationScore]:
        """
        更新灰名单渠道表
        1. 对已存在的渠道运行变形检测
        2. 更新快照至最新
        3. 新增渠道自动加入灰名单
        """
        alerts = []

        for channel_id, new_snap in new_snapshots.items():
            if channel_id in self._gray_list:
                # 变形检测
                score = self.detect_deformation(self._gray_list[channel_id], new_snap)
                alerts.append(score)

            # 更新快照
            self._gray_list[channel_id] = new_snap

        return alerts

    def generate_alert_report(
        self,
        alerts: List[DeformationScore],
        min_severity: str = "WARN"
    ) -> Dict:
        """
        生成渠道变形警报报告
        min_severity: "CRITICAL" | "WARN" | "INFO"
        """
        critical = [a for a in alerts if a.flagged and a.composite_score >= 0.7]
        warning = [a for a in alerts if a.flagged and 0.55 <= a.composite_score < 0.7]
        info = [a for a in alerts if a.flagged and a.composite_score < 0.55]

        return {
            "module": "S004",
            "component": "deformation_tracker",
            "generated_at": datetime.now().isoformat(),
            "alert_summary": {
                "critical": len(critical),
                "warning": len(warning),
                "info": len(info),
                "total_flagged": len([a for a in alerts if a.flagged]),
                "total_monitored": len(self._gray_list)
            },
            "critical_alerts": [
                {
                    "channel_id": a.channel_id,
                    "composite_score": a.composite_score,
                    "deformation_type": a.deformation_type,
                    "jaccard_similarity": a.jaccard_similarity,
                    "graph_edit_distance": a.graph_edit_distance,
                    "base_date": a.base_date,
                    "compare_date": a.compare_date
                }
                for a in critical
            ],
            "warning_alerts": [
                {
                    "channel_id": a.channel_id,
                    "composite_score": a.composite_score,
                    "deformation_type": a.deformation_type
                }
                for a in warning
            ],
            "info_alerts": [
                {
                    "channel_id": a.channel_id,
                    "composite_score": a.composite_score
                }
                for a in info
            ]
        }

    def to_json(self, output_path: str) -> str:
        """序列化灰名单变形检测状态至JSON文件"""
        from pathlib import Path
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        output = {
            "meta": {
                "author": "xuanzhi",
                "date": str(date.today()),
                "module": "S004_Phase2_DeformationTracker",
                "version": "v1",
                "status": "READY"
            },
            "gray_list_channels": list(self._gray_list.keys()),
            "gray_list_count": len(self._gray_list),
            "detection_history_count": len(self._history)
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # 写入验证
        with open(path, "r", encoding="utf-8") as f:
            validated = json.load(f)
            assert validated["meta"]["status"] == "READY", "写入验证失败"

        return str(path)
