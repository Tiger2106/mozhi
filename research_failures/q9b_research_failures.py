# -*- coding: utf-8 -*-
"""
q9b_research_failures.py — Q9b RESEARCH_FAILURES 写入/查询模块

Q9b 是 Layer Q (Transverse Governance Layer) 的**全量研究失败数据库**。
记录所有研究过程中产生的失败——包括但不限于人工复盘发现的失败、
元研究（Meta Research）发现的模式性失败等。

与 Q9a Q_FAILURES 的职责分离：
  Q9a (正式审计)    ← G1/G2/G3 门控自动记录，可信度治理用途
  Q9b (全量研究)    ← 人工复盘/元研究/实验记录，知识积累用途

数据结构说明（独立于 Q9a）：
  - 独立的数据结构 ResearchFailureRecord（非 QFailureRecord）
  - 独立的枚举 ResearchFailureType（扩展 Q9a 的 FailureType）
  - 独立的存储路径（research_failures/records/）
  - 通过 strategy_id + failure_id 交叉引用 Q9a

新增枚举类型（Q9b 专有）：
  VETO_FAILURE       — Owner 否决（策略方向性否决）
  DATA_ISSUE         — 数据问题（数据质量/偏差/幸存者偏差等）
  METHODOLOGY_BIAS   — 方法论偏见（前视偏差/过拟合认知等）

作者：墨衡 (moheng)
创建时间：2026-05-19 16:26 GMT+8
"""

from __future__ import annotations

import enum
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")
_RESEARCH_FAILURES_ROOT = Path(__file__).resolve().parent  # research_failures/


# ============================================================
# 枚举类型
# ============================================================

class ResearchFailureType(str, enum.Enum):
    """Q9b 研究失败类型枚举

    扩展自 Q9a 的 FailureType，新增 3 个研究专有类型：
      VETO_FAILURE       — Owner 否决
      DATA_ISSUE         — 数据问题（数据质量、幸存者偏差等）
      METHODOLOGY_BIAS   — 方法论偏见（前视偏差、过拟合认知等）

    保留与 Q9a 的交叉引用能力（通过 strategy_id + failure_id）。
    """

    # ---- Q9a 继承类型（正式审计失败） ----
    STATISTICAL_NOISE  = "STATISTICAL_NOISE"
    PARAMETER_PEAK     = "PARAMETER_PEAK"
    REGIME_BOUNDED     = "REGIME_BOUNDED"
    CAPACITY_LIMITED   = "CAPACITY_LIMITED"
    TEMPORAL_DECAY     = "TEMPORAL_DECAY"
    OOS_FAILURE        = "OOS_FAILURE"
    LOW_CONFIDENCE     = "LOW_CONFIDENCE"
    HUMAN_REJECTED     = "HUMAN_REJECTED"

    # ---- Q9b 新增类型（研究专有） ----
    VETO_FAILURE       = "VETO_FAILURE"         # Owner 否决
    DATA_ISSUE         = "DATA_ISSUE"           # 数据问题
    METHODOLOGY_BIAS   = "METHODOLOGY_BIAS"     # 方法论偏见
    EDGE_CASE          = "EDGE_CASE"            # 兜底


# ============================================================
# 严重级别
# ============================================================

class FailureSeverity(str, enum.Enum):
    """失败严重级别"""
    CRITICAL = "CRITICAL"    # 致命缺陷，策略不可用
    MAJOR    = "MAJOR"       # 重大缺陷，需修复后重审
    MINOR    = "MINOR"       # 轻微缺陷，可接受但需记录
    INFO     = "INFO"        # 信息性记录，非缺陷


# ============================================================
# 数据持久化路径
# ============================================================

RECORDS_DIR = _RESEARCH_FAILURES_ROOT / "records"
AGGREGATIONS_DIR = _RESEARCH_FAILURES_ROOT / "aggregations"
INDEX_FILE = _RESEARCH_FAILURES_ROOT / "index.json"

for _d in [RECORDS_DIR, AGGREGATIONS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


# ============================================================
# 数据结构（独立于 Q9a）
# ============================================================

@dataclass
class ResearchFailureRecord:
    """Q9b 研究失败记录

    独立于 Q9a QFailureRecord 的数据结构。

    通过 strategy_id + failure_id 与 Q9a 交叉引用：
      若该研究失败同时也导致正式审计失败，则在 q9a_failure_id 中记录
      Q9a 的 failure_id。

    Attributes
    ----------
    failure_id : str
        UUID 格式唯一标识（自动生成）
    strategy_id : str
        策略名称/ID
    context : str
        失败场景描述（在什么情况下发生的失败）
    failure_type : ResearchFailureType
        失败类型枚举
    severity : FailureSeverity
        严重级别（默认 MAJOR）
    discovered_by : str
        发现者（如 "MOZHEN", "MOHAN", "OWNER", "META_ANALYSIS"）
    root_cause : str
        根因分析
    impact_description : str
        对研究结果的影响描述
    q9a_failure_id : str | None
        关联的 Q9a failure_id（可选，用于交叉引用）
    regime : str
        发生时的市场状态（可选）
    parameter_set : dict
        相关参数集（可选）
    evidence_paths : list[str]
        证据文件路径列表（可选，支持引用分析报告/图表）
    created_at : str
        创建时间 ISO8601 (CST)
    updated_at : str
        最后更新 ISO8601 (CST)
    resolved : bool
        是否已解决（默认 False）
    resolution_notes : str
        解决方案/备注（可选）
    tags : list[str]
        标签列表（如 ["过拟合", "数据偏差", "前视偏差"]）
    """
    failure_id: str = ""
    strategy_id: str = ""
    context: str = ""
    failure_type: ResearchFailureType = ResearchFailureType.EDGE_CASE
    severity: FailureSeverity = FailureSeverity.MAJOR
    discovered_by: str = ""
    root_cause: str = ""
    impact_description: str = ""
    q9a_failure_id: Optional[str] = None
    regime: str = ""
    parameter_set: dict = field(default_factory=dict)
    evidence_paths: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    resolved: bool = False
    resolution_notes: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        now = datetime.now(_TZ_CST).isoformat()
        if not self.failure_id:
            self.failure_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典"""
        d = asdict(self)
        d["failure_type"] = self.failure_type.value
        d["severity"] = self.severity.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchFailureRecord":
        """从字典反序列化"""
        ft = data.get("failure_type", "EDGE_CASE")
        sev = data.get("severity", "MAJOR")
        return cls(
            failure_id=data.get("failure_id", ""),
            strategy_id=data.get("strategy_id", ""),
            context=data.get("context", ""),
            failure_type=ResearchFailureType(ft),
            severity=FailureSeverity(sev),
            discovered_by=data.get("discovered_by", ""),
            root_cause=data.get("root_cause", ""),
            impact_description=data.get("impact_description", ""),
            q9a_failure_id=data.get("q9a_failure_id"),
            regime=data.get("regime", ""),
            parameter_set=data.get("parameter_set", {}),
            evidence_paths=data.get("evidence_paths", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            resolved=data.get("resolved", False),
            resolution_notes=data.get("resolution_notes", ""),
            tags=data.get("tags", []),
        )


# ============================================================
# 索引管理器
# ============================================================

def _load_index() -> dict[str, list[str]]:
    """加载索引文件

    索引格式：{strategy_id: [failure_id, ...]}

    Returns
    -------
    dict[str, list[str]]
    """
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_index(index: dict[str, list[str]]) -> None:
    """保存索引文件"""
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ============================================================
# 写入/查询接口
# ============================================================

class ResearchFailuresDB:
    """Q9b RESEARCH_FAILURES 管理器

    提供对研究失败记录的写入、查询、聚合分析。
    数据存储为独立 JSON 文件，不依赖 Q9a 的 SQLite 数据库。

    Parameters
    ----------
    root_path : str | Path | None
        根目录，默认 research_failures/
    """

    def __init__(self, root_path: Optional[str | Path] = None) -> None:
        self._root = Path(root_path) if root_path else _RESEARCH_FAILURES_ROOT
        self._records_dir = self._root / "records"
        self._agg_dir = self._root / "aggregations"
        self._records_dir.mkdir(parents=True, exist_ok=True)
        self._agg_dir.mkdir(parents=True, exist_ok=True)

    # ===================== 写入 =====================

    def insert(self, record: ResearchFailureRecord) -> str:
        """写入一条研究失败记录

        Parameters
        ----------
        record : ResearchFailureRecord
            待写入的记录

        Returns
        -------
        str
            failure_id
        """
        # 保存记录文件
        filepath = self._records_dir / f"{record.failure_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)

        # 更新索引
        index = _load_index()
        index.setdefault(record.strategy_id, []).append(record.failure_id)
        _save_index(index)

        return record.failure_id

    def batch_insert(self, records: list[ResearchFailureRecord]) -> list[str]:
        """批量写入

        Parameters
        ----------
        records : list[ResearchFailureRecord]

        Returns
        -------
        list[str]
            failure_id 列表
        """
        ids: list[str] = []
        index = _load_index()

        for record in records:
            filepath = self._records_dir / f"{record.failure_id}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
            index.setdefault(record.strategy_id, []).append(record.failure_id)
            ids.append(record.failure_id)

        _save_index(index)
        return ids

    # ===================== 查询 =====================

    def get(self, failure_id: str) -> Optional[ResearchFailureRecord]:
        """按 failure_id 查询单条记录

        Parameters
        ----------
        failure_id : str

        Returns
        -------
        ResearchFailureRecord | None
        """
        filepath = self._records_dir / f"{failure_id}.json"
        if not filepath.exists():
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return ResearchFailureRecord.from_dict(json.load(f))
        except (json.JSONDecodeError, IOError):
            return None

    def get_by_strategy(self, strategy_id: str) -> list[ResearchFailureRecord]:
        """查询特定策略的所有研究失败记录

        Parameters
        ----------
        strategy_id : str

        Returns
        -------
        list[ResearchFailureRecord]
        """
        index = _load_index()
        failure_ids = index.get(strategy_id, [])
        results: list[ResearchFailureRecord] = []
        for fid in failure_ids:
            record = self.get(fid)
            if record:
                results.append(record)
        return results

    def get_by_type(self, failure_type: ResearchFailureType | str) -> list[ResearchFailureRecord]:
        """按失败类型查询

        Parameters
        ----------
        failure_type : ResearchFailureType | str

        Returns
        -------
        list[ResearchFailureRecord]
        """
        ft = failure_type.value if isinstance(failure_type, ResearchFailureType) else failure_type
        return self.query(failure_type=ft)

    def get_by_severity(self, severity: FailureSeverity | str) -> list[ResearchFailureRecord]:
        """按严重级别查询

        Parameters
        ----------
        severity : FailureSeverity | str

        Returns
        -------
        list[ResearchFailureRecord]
        """
        sev = severity.value if isinstance(severity, FailureSeverity) else severity
        return self.query(severity=sev)

    def get_by_q9a_ref(self, q9a_failure_id: str) -> Optional[ResearchFailureRecord]:
        """通过 Q9a failure_id 查询关联的研究失败记录

        Parameters
        ----------
        q9a_failure_id : str

        Returns
        -------
        ResearchFailureRecord | None
        """
        for p in self._records_dir.iterdir():
            if p.suffix != ".json":
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("q9a_failure_id") == q9a_failure_id:
                    return ResearchFailureRecord.from_dict(data)
            except (json.JSONDecodeError, IOError):
                continue
        return None

    def query(
        self,
        strategy_id: Optional[str] = None,
        failure_type: Optional[str] = None,
        severity: Optional[str] = None,
        discovered_by: Optional[str] = None,
        resolved: Optional[bool] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> list[ResearchFailureRecord]:
        """多条件查询

        Parameters
        ----------
        strategy_id : str | None
            筛选策略
        failure_type : str | None
            筛选类型
        severity : str | None
            筛选严重级别
        discovered_by : str | None
            筛选发现者
        resolved : bool | None
            筛选已解决/未解决
        tag : str | None
            筛选标签
        limit : int
            最大返回条数（默认 100）

        Returns
        -------
        list[ResearchFailureRecord]
        """
        results: list[ResearchFailureRecord] = []
        for p in self._records_dir.iterdir():
            if p.suffix != ".json":
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            # 筛选
            if strategy_id and data.get("strategy_id") != strategy_id:
                continue
            if failure_type and data.get("failure_type") != failure_type:
                continue
            if severity and data.get("severity") != severity:
                continue
            if discovered_by and data.get("discovered_by") != discovered_by:
                continue
            if resolved is not None and data.get("resolved") != resolved:
                continue
            if tag and tag not in data.get("tags", []):
                continue

            results.append(ResearchFailureRecord.from_dict(data))
            if len(results) >= limit:
                break

        # 按创建时间降序
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    # ===================== 更新 =====================

    def update_resolution(
        self,
        failure_id: str,
        resolution_notes: str,
        resolved: bool = True,
    ) -> bool:
        """更新记录的解决状态和备注

        Parameters
        ----------
        failure_id : str
            记录 ID
        resolution_notes : str
            解决方案说明
        resolved : bool
            是否已解决（默认 True）

        Returns
        -------
        bool
            是否成功
        """
        record = self.get(failure_id)
        if not record:
            return False

        record.resolved = resolved
        record.resolution_notes = resolution_notes
        record.updated_at = datetime.now(_TZ_CST).isoformat()

        filepath = self._records_dir / f"{failure_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
        return True

    # ===================== 统计 =====================

    def count_by_type(self) -> dict[str, int]:
        """按失败类型统计记录数

        Returns
        -------
        dict[str, int]
            如 {"DATA_ISSUE": 5, "PARAMETER_PEAK": 3}
        """
        counts: dict[str, int] = {}
        for p in self._records_dir.iterdir():
            if p.suffix != ".json":
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ft = data.get("failure_type", "EDGE_CASE")
                counts[ft] = counts.get(ft, 0) + 1
            except (json.JSONDecodeError, IOError):
                continue
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def count_by_severity(self) -> dict[str, int]:
        """按严重级别统计"""
        counts: dict[str, int] = {}
        for p in self._records_dir.iterdir():
            if p.suffix != ".json":
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sev = data.get("severity", "MAJOR")
                counts[sev] = counts.get(sev, 0) + 1
            except (json.JSONDecodeError, IOError):
                continue
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def count_unresolved(self) -> int:
        """未解决的记录数"""
        count = 0
        for p in self._records_dir.iterdir():
            if p.suffix != ".json":
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not data.get("resolved", False):
                    count += 1
            except (json.JSONDecodeError, IOError):
                continue
        return count

    def total_count(self) -> int:
        """总记录数"""
        return len([p for p in self._records_dir.iterdir() if p.suffix == ".json"])

    # ===================== 交叉引用查询 =====================

    def find_cross_references(self, strategy_id: str) -> dict[str, Any]:
        """查找指定策略在 Q9a 和 Q9b 中的交叉引用

        返回策略在同一策略下的 Q9a 正式审计失败和 Q9b 研究失败的关联信息。

        Parameters
        ----------
        strategy_id : str

        Returns
        -------
        dict[str, Any]
            包含 q9a_ids, q9b_ids, 以及关联的失败类型
        """
        from q_failures_db import QFailuresDB

        # Q9a 查询
        q9a_db = QFailuresDB()
        q9a_db.initialize()
        q9a_records = q9a_db.query(strategy_id=strategy_id)
        q9a_ids = [r.failure_id for r in q9a_records]
        q9a_by_type: dict[str, int] = {}
        for r in q9a_records:
            ft = r.failure_type.value if isinstance(r.failure_type, FailureType) else str(r.failure_type)
            q9a_by_type[ft] = q9a_by_type.get(ft, 0) + 1
        q9a_db.close()

        # Q9b 查询
        q9b_records = self.get_by_strategy(strategy_id)
        q9b_ids = [r.failure_id for r in q9b_records]

        # 通过 q9a_failure_id 关联的 Q9b 记录
        linked_q9b = [r for r in q9b_records if r.q9a_failure_id in q9a_ids]

        # 按类型交叉统计
        q9b_by_type: dict[str, int] = {}
        for r in q9b_records:
            ft = r.failure_type.value if isinstance(r.failure_type, ResearchFailureType) else str(r.failure_type)
            q9b_by_type[ft] = q9b_by_type.get(ft, 0) + 1

        # 交集类型：同时在 Q9a 和 Q9b 中出现的失败类型
        common_types = set(q9a_by_type.keys()) & set(q9b_by_type.keys())

        return {
            "strategy_id": strategy_id,
            "q9a_count": len(q9a_ids),
            "q9b_count": len(q9b_ids),
            "linked_count": len(linked_q9b),
            "q9a_by_type": q9a_by_type,
            "q9b_by_type": q9b_by_type,
            "common_failure_types": sorted(common_types),
        }

    # ===================== 导出 =====================

    def export(self, output_path: str | Path) -> str:
        """导出全量记录到 JSON 文件

        Parameters
        ----------
        output_path : str | Path
            JSON 输出路径

        Returns
        -------
        str
            输出文件路径
        """
        all_records = self.query(limit=10000)
        data = {
            "export_time": datetime.now(_TZ_CST).isoformat(),
            "total_records": len(all_records),
            "records": [r.to_dict() for r in all_records],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(output_path)


# ============================================================
# 便利工厂
# ============================================================

def create_research_record(
    strategy_id: str,
    context: str,
    failure_type: ResearchFailureType | str,
    discovered_by: str = "MOZHEN",
    severity: FailureSeverity | str = FailureSeverity.MAJOR,
    root_cause: str = "",
    impact_description: str = "",
    q9a_failure_id: Optional[str] = None,
    regime: str = "",
    tags: Optional[list[str]] = None,
) -> ResearchFailureRecord:
    """便捷创建一条研究失败记录

    Parameters
    ----------
    strategy_id : str
    context : str
    failure_type : ResearchFailureType | str
    discovered_by : str
    severity : FailureSeverity | str
    root_cause : str
    impact_description : str
    q9a_failure_id : str | None
    regime : str
    tags : list[str] | None

    Returns
    -------
    ResearchFailureRecord
    """
    ft = failure_type if isinstance(failure_type, ResearchFailureType) else ResearchFailureType(failure_type)
    sev = severity if isinstance(severity, FailureSeverity) else FailureSeverity(severity)
    return ResearchFailureRecord(
        strategy_id=strategy_id,
        context=context,
        failure_type=ft,
        severity=sev,
        discovered_by=discovered_by,
        root_cause=root_cause,
        impact_description=impact_description,
        q9a_failure_id=q9a_failure_id,
        regime=regime,
        tags=tags or [],
    )


def extract_type_stats(stats: dict[str, int], total: int) -> list[tuple[str, int, float]]:
    """从计数 dict 生成排序后的 (类型, 计数, 百分比) 列表

    Parameters
    ----------
    stats : dict[str, int]
    total : int

    Returns
    -------
    list[tuple[str, int, float]]
    """
    sorted_items = sorted(stats.items(), key=lambda x: -x[1])
    return [
        (ft, cnt, round(cnt / total * 100, 2) if total > 0 else 0.0)
        for ft, cnt in sorted_items
    ]
