# -*- coding: utf-8 -*-
"""
q_failures_db.py — Q9a Q_FAILURES 数据库基础设施

Q9a 是 Layer Q (Transverse Governance Layer) 的正式审计失败数据库，
记录所有 Quality Gate (G1/G2/G3) 和 Q层验证器 (Q1~Q8) 发现的审计失败。
作为"可信度审计账本 (账本B)"的核心存储组件。

失败记录与 KnowledgeBridge（知识桥）形成镜像互补：
  - KnowledgeBridge: 记录"什么成功"
  - Q_FAILURES:    记录"什么失败"

设计原则：
  - 严格模式（STRICT）确保数据完整性
  - failure_type 为受限枚举，不允许非法值
  - 写入后自动 timezone-aware 时间戳
  - 与 trade_engine.db 通过 run_id 交叉引用

作者：墨衡 (moheng)
创建时间：2026-05-19 16:15 GMT+8
"""

from __future__ import annotations

import enum
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")


def _now_cst() -> datetime:
    """返回当前 CST (+08:00) 时间"""
    return datetime.now(_TZ_CST)


# ============================================================
# failure_type 枚举
# ============================================================

class FailureType(str, enum.Enum):
    """失败类型枚举 —— 与 Q9 各层门控一一对应"""
    STATISTICAL_NOISE  = "STATISTICAL_NOISE"   # Q1: 统计噪声（交易太少/信噪比过低）
    PARAMETER_PEAK     = "PARAMETER_PEAK"      # Q2: 参数尖峰（最优参数孤立）
    REGIME_BOUNDED     = "REGIME_BOUNDED"      # Q3: 仅单一市场状态有效
    CAPACITY_LIMITED   = "CAPACITY_LIMITED"    # Q4: 资金容量不足
    TEMPORAL_DECAY     = "TEMPORAL_DECAY"      # Q5: 时间漂移（前期赚钱后期亏）
    OOS_FAILURE        = "OOS_FAILURE"         # Q6: 样本外全面失效
    LOW_CONFIDENCE     = "LOW_CONFIDENCE"      # Q7: 综合置信度不足
    HUMAN_REJECTED     = "HUMAN_REJECTED"      # G3: 人工复审不通过
    EDGE_CASE          = "EDGE_CASE"           # 兜底: 待人工分析

    @classmethod
    def from_gate(cls, gate_name: str) -> "FailureType":
        """从门控名称映射到失败类型

        Parameters
        ----------
        gate_name : str
            门控名称，如 "G1", "G2", "G3"

        Returns
        -------
        FailureType
            对应的失败类型枚举值

        Raises
        ------
        ValueError
            无法识别的门控名称
        """
        mapping = {
            "G1": cls.STATISTICAL_NOISE,
            "G2": cls.PARAMETER_PEAK,
            "G3": cls.HUMAN_REJECTED,
        }
        if gate_name not in mapping:
            raise ValueError(f"无法识别的门控名称: {gate_name}，支持: {list(mapping.keys())}")
        return mapping[gate_name]


# ============================================================
# 记录数据结构
# ============================================================

@dataclass
class QFailureRecord:
    """单条 Q_FAILURES 失败记录

    Attributes
    ----------
    failure_id : str
        UUID 格式唯一标识 (自动生成)
    strategy_id : str
        策略名称/ID
    parameter_set : dict
        失败时的参数集（JSON 序列化）
    failure_type : FailureType
        失败类型枚举
    regime : str
        发生失败时的市场状态（如 OSCILLATION_LOWVOL/TREND_UP/…）
    cause : str
        根因描述（优先使用 Q8 输出的 TopSuggestion，也可人工补充）
    discovered_by : str
        由哪个验证器/门控发现，如 "Q1", "G2", "G3"
    confidence_before : float | None
        失败发生前的置信度（可选），范围 [0.0, 1.0]
    confidence_after : float | None
        失败发生后的置信度（可选），范围 [0.0, 1.0]
    timestamp : str
        记录时间 ISO8601 字符串 (CST +08:00, 自动填充)
    run_id : str | None
        关联的回测运行 ID（与 trade_engine.db 交叉引用）
    report_id : str | None
        关联的审计报告 ID
    human_notes : str
        人工复盘补充说明（可选，默认空字符串）
    """
    failure_id: str = ""
    strategy_id: str = ""
    parameter_set: dict = field(default_factory=dict)
    failure_type: FailureType = FailureType.EDGE_CASE
    regime: str = ""
    cause: str = ""
    discovered_by: str = ""
    confidence_before: Optional[float] = None
    confidence_after: Optional[float] = None
    timestamp: str = ""
    run_id: Optional[str] = None
    report_id: Optional[str] = None
    human_notes: str = ""

    def __post_init__(self) -> None:
        """自动填充默认值"""
        if not self.failure_id:
            self.failure_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = _now_cst().isoformat()

    def to_db_tuple(self) -> tuple:
        """转换为数据库插入元组（按表字段顺序）"""
        return (
            self.failure_id,
            self.strategy_id,
            json.dumps(self.parameter_set, ensure_ascii=False),
            self.failure_type.value,
            self.regime,
            self.cause,
            self.discovered_by,
            self.confidence_before,
            self.confidence_after,
            self.timestamp,
            self.run_id,
            self.report_id,
            self.human_notes,
        )

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "QFailureRecord":
        """从数据库行对象反序列化为 QFailureRecord

        Parameters
        ----------
        row : sqlite3.Row
            SQLite 行对象（支持 dict-like 的 [] 访问）

        Returns
        -------
        QFailureRecord
        """
        return cls(
            failure_id=row["failure_id"],
            strategy_id=row["strategy_id"],
            parameter_set=json.loads(row["parameter_set"]) if row["parameter_set"] else {},
            failure_type=FailureType(row["failure_type"]),
            regime=row["regime"] or "",
            cause=row["cause"] or "",
            discovered_by=row["discovered_by"] or "",
            confidence_before=row["confidence_before"],
            confidence_after=row["confidence_after"],
            timestamp=row["timestamp"],
            run_id=row["run_id"],
            report_id=row["report_id"],
            human_notes=row["human_notes"] or "",
        )

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典"""
        d = asdict(self)
        d["failure_type"] = self.failure_type.value
        return d


# ============================================================
# 数据库管理器
# ============================================================

class QFailuresDB:
    """Q9a Q_FAILURES 数据库管理器

    管理 SQLite 数据库的创建、连接、CRUD 操作。
    数据库文件默认存储在 q_failures/ 目录下。

    Parameters
    ----------
    db_path : str | Path | None
        数据库文件路径。默认创建在 mozhi_platform/q_failures/q_failures.db。

    Examples
    --------
    >>> db = QFailuresDB()
    >>> db.initialize()
    >>> db.insert_record(QFailureRecord(strategy_id="grid_601857", ...))
    """

    DEFAULT_DB_RELATIVE = "q_failures" / Path("q_failures.db")
    DEFAULT_DB_NAME = "q_failures.db"

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        # 自动推断项目根目录
        if db_path is None:
            default_dir = Path(__file__).resolve().parent.parent.parent / "q_failures"
            default_dir.mkdir(parents=True, exist_ok=True)
            self.db_path: Path = default_dir / self.DEFAULT_DB_NAME
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        """惰性获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def initialize(self) -> None:
        """创建或确认数据库表结构存在"""
        schema = """
        CREATE TABLE IF NOT EXISTS q_failures (
            failure_id         TEXT PRIMARY KEY,
            strategy_id        TEXT NOT NULL,
            parameter_set      TEXT NOT NULL DEFAULT '{}',
            failure_type       TEXT NOT NULL
                               CHECK (failure_type IN (
                                   'STATISTICAL_NOISE',
                                   'PARAMETER_PEAK',
                                   'REGIME_BOUNDED',
                                   'CAPACITY_LIMITED',
                                   'TEMPORAL_DECAY',
                                   'OOS_FAILURE',
                                   'LOW_CONFIDENCE',
                                   'HUMAN_REJECTED',
                                   'EDGE_CASE'
                               )),
            regime             TEXT,
            cause              TEXT,
            discovered_by      TEXT NOT NULL,
            confidence_before  REAL,
            confidence_after   REAL,
            timestamp          TEXT NOT NULL,
            run_id             TEXT,
            report_id          TEXT,
            human_notes        TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_qf_failure_type  ON q_failures(failure_type);
        CREATE INDEX IF NOT EXISTS idx_qf_strategy_id   ON q_failures(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_qf_regime        ON q_failures(regime);
        CREATE INDEX IF NOT EXISTS idx_qf_timestamp     ON q_failures(timestamp);
        CREATE INDEX IF NOT EXISTS idx_qf_discovered_by ON q_failures(discovered_by);
        CREATE INDEX IF NOT EXISTS idx_qf_run_id        ON q_failures(run_id);
        """
        self.conn.executescript(schema)
        self.conn.commit()

    def insert_record(self, record: QFailureRecord) -> str:
        """插入一条失败记录，返回 failure_id

        Parameters
        ----------
        record : QFailureRecord
            待插入的失败记录

        Returns
        -------
        str
            该记录的唯一 failure_id
        """
        sql = """
        INSERT INTO q_failures (
            failure_id, strategy_id, parameter_set, failure_type,
            regime, cause, discovered_by,
            confidence_before, confidence_after,
            timestamp, run_id, report_id, human_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(sql, record.to_db_tuple())
        self.conn.commit()
        return record.failure_id

    def batch_insert(self, records: list[QFailureRecord]) -> list[str]:
        """批量插入多条失败记录

        Parameters
        ----------
        records : list[QFailureRecord]
            待插入的记录列表

        Returns
        -------
        list[str]
            每条记录对应的 failure_id 列表
        """
        sql = """
        INSERT INTO q_failures (
            failure_id, strategy_id, parameter_set, failure_type,
            regime, cause, discovered_by,
            confidence_before, confidence_after,
            timestamp, run_id, report_id, human_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        tuples = [r.to_db_tuple() for r in records]
        self.conn.executemany(sql, tuples)
        self.conn.commit()
        return [r.failure_id for r in records]

    def get_record(self, failure_id: str) -> Optional[QFailureRecord]:
        """根据 failure_id 获取单条记录

        Parameters
        ----------
        failure_id : str
            失败记录唯一标识

        Returns
        -------
        QFailureRecord | None
            找到的记录，或 None
        """
        cur = self.conn.execute(
            "SELECT * FROM q_failures WHERE failure_id = ?", (failure_id,)
        )
        row = cur.fetchone()
        return QFailureRecord.from_db_row(row) if row else None

    def query(
        self,
        failure_type: Optional[FailureType | str] = None,
        strategy_id: Optional[str] = None,
        regime: Optional[str] = None,
        discovered_by: Optional[str] = None,
        run_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "timestamp DESC",
    ) -> list[QFailureRecord]:
        """多条件查询失败记录

        Parameters
        ----------
        failure_type : FailureType | str | None
            筛选特定失败类型
        strategy_id : str | None
            筛选特定策略
        regime : str | None
            筛选特定市场状态
        discovered_by : str | None
            筛选特定发现者（如 "Q1", "G2"）
        run_id : str | None
            筛选关联的回测运行 ID
        since : str | None
            起始时间 (ISO8601, 包含)
        until : str | None
            截止时间 (ISO8601, 包含)
        limit : int
            最大返回条数 (默认 100)
        offset : int
            跳过前 N 条 (用于分页)
        order_by : str
            排序规则 (默认 timestamp DESC)

        Returns
        -------
        list[QFailureRecord]
            符合条件的记录列表
        """
        conditions: list[str] = []
        params: list[Any] = []

        if failure_type is not None:
            ft = failure_type.value if isinstance(failure_type, FailureType) else failure_type
            conditions.append("failure_type = ?")
            params.append(ft)
        if strategy_id is not None:
            conditions.append("strategy_id = ?")
            params.append(strategy_id)
        if regime is not None:
            conditions.append("regime = ?")
            params.append(regime)
        if discovered_by is not None:
            conditions.append("discovered_by = ?")
            params.append(discovered_by)
        if run_id is not None:
            conditions.append("run_id = ?")
            params.append(run_id)
        if since is not None:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            conditions.append("timestamp <= ?")
            params.append(until)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM q_failures WHERE {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)

        cur = self.conn.execute(sql, params)
        return [QFailureRecord.from_db_row(row) for row in cur.fetchall()]

    def count(self) -> int:
        """返回总记录数

        Returns
        -------
        int
            数据库中的失败记录总数
        """
        cur = self.conn.execute("SELECT COUNT(*) AS cnt FROM q_failures")
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "QFailuresDB":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
