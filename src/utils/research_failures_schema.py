# -*- coding: utf-8 -*-
"""
research_failures_schema.py — Q9b RESEARCH_FAILURES 数据库表结构

Q9b 是 Layer Q (Transverse Governance Layer) 的全量研究失败数据库，
独立于 Q9a Q_FAILURES（正式审计失败），共同构成 Failure Registry 双层结构。

设计原则 (ADR-001, ADR-007, Expert Round 3 #5):
  - 双层隔离：Q9a = 正式审计失败（可信度治理），Q9b = 全量研究失败（长期知识积累 + Meta Research）
  - 职责分离：Q9a 由 Gate 自动写入，Q9b 由研究员人工复盘 / 元研究主动录入
  - 交叉引用：Q9b 记录的 cross_ref_q9a 字段可指向对应的 Q9a 记录
  - 机构最值钱的往往不是成功策略，而是失败模式数据库

数据结构差异（Q9b vs Q9a）:
  | 维度 | Q9a Q_FAILURES | Q9b RESEARCH_FAILURES |
  |:-----|:---------------|:-----------------------|
  | 来源 | Gate/Q层自动 | 人工复盘 + Meta Research |
  | 粒度 | 失败即可触发 | 需要根因分析的失败 |
  | 类型 | 预定义枚举 | 自由文本(failure_type_verbose) |
  | 研究人员 | 自动提取 | 主动填写 |
  | cross_ref | — | 可选引用 Q9a |
  | 输出 | 可信度治理 | 知识积累 + 复发检测 |

作者：墨萱 (moxuan)
创建时间：2026-05-19 16:20 GMT+8
"""

from __future__ import annotations

import json
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
# 常量
# ============================================================

# RESEARCH_FAILURES 数据库文件名
_RF_DB_NAME: str = "research_failures.db"

# 表名
_RF_TABLE: str = "research_failures"

# 文件结构目录
_RF_DIRS: dict[str, str] = {
    "records": "records",     # 手动复盘记录存放目录
    "index": "index",         # 索引文件存放目录
}


# ============================================================
# 记录数据结构
# ============================================================

@dataclass
class ResearchFailureRecord:
    """单条 Q9b RESEARCH_FAILURES 记录

    Attributes
    ----------
    failure_id : str
        UUID 格式唯一标识 (自动生成)
    strategy_name : str
        策略名称
    researcher : str
        研究员标识，如 "moheng", "moxuan", "mochen"
    failure_type_verbose : str
        失败的详细文本描述类型，如 "TEMPORAL_DECAY",
        "STATISTICAL_INSUFFICIENCY", "REGIME_DEPENDENT",
        "PARAMETER_OVERFIT", "DATA_QUALITY_ISSUE" 等（自由文本）
    root_cause : str
        根因详细描述
    discovery_date : str
        失败发现日期 (ISO8601 日期格式, e.g. "2026-05-19")
    data_source_version : str
        发现时的数据源版本，如 "wind_v2.3.0"
    notes : str
        详细复盘笔记（Markdown 格式，可选）
    cross_ref_q9a : str | None
        关联的 Q9a Q_FAILURES 记录的 failure_id（可选，用于双层交叉引用）
    created_at : str
        记录创建时间 ISO8601 (CST +08:00, 自动填充)
    updated_at : str
        最后更新时间 ISO8601 (CST +08:00, 自动填充)
    """
    failure_id: str = ""
    strategy_name: str = ""
    researcher: str = ""
    failure_type_verbose: str = ""
    root_cause: str = ""
    discovery_date: str = ""
    data_source_version: str = ""
    notes: str = ""
    cross_ref_q9a: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now_str = _now_cst().isoformat()
        if not self.failure_id:
            self.failure_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = now_str
        if not self.updated_at:
            self.updated_at = now_str

    def to_db_tuple(self) -> tuple:
        """转换为数据库插入元组（按表字段顺序）"""
        return (
            self.failure_id,
            self.strategy_name,
            self.researcher,
            self.failure_type_verbose,
            self.root_cause,
            self.discovery_date,
            self.data_source_version,
            self.notes,
            self.cross_ref_q9a,
            self.created_at,
            self.updated_at,
        )

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "ResearchFailureRecord":
        """从数据库行对象反序列化

        Parameters
        ----------
        row : sqlite3.Row
            SQLite 行对象

        Returns
        -------
        ResearchFailureRecord
        """
        return cls(
            failure_id=row["failure_id"],
            strategy_name=row["strategy_name"],
            researcher=row["researcher"],
            failure_type_verbose=row["failure_type_verbose"],
            root_cause=row["root_cause"],
            discovery_date=row["discovery_date"],
            data_source_version=row["data_source_version"],
            notes=row["notes"] or "",
            cross_ref_q9a=row["cross_ref_q9a"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典"""
        return asdict(self)

    def to_yaml_manual(self) -> str:
        """生成适合手动复盘记录的 YAML 格式字符串"""
        lines = [
            f"failure_id: \"{self.failure_id}\"",
            f"strategy_name: \"{self.strategy_name}\"",
            f"researcher: \"{self.researcher}\"",
            f"failure_type_verbose: \"{self.failure_type_verbose}\"",
            f"root_cause: |",
            f"  {self.root_cause}",
            f"discovery_date: \"{self.discovery_date}\"",
            f"data_source_version: \"{self.data_source_version}\"",
            f"notes: |",
            f"  {self.notes.replace(chr(10), chr(10) + '  ')}",
        ]
        if self.cross_ref_q9a:
            lines.append(f"cross_ref_q9a: \"{self.cross_ref_q9a}\"")
        else:
            lines.append("cross_ref_q9a: null")
        return "\n".join(lines)


# ============================================================
# 数据库管理器
# ============================================================

class ResearchFailuresRegistry:
    """Q9b RESEARCH_FAILURES 数据库管理器

    管理研究失败记录数据库的创建、CRUD、查询和索引维护。

    存储位置：research_failures/research_failures.db
    手动记录目录：research_failures/records/
    索引目录：research_failures/index/

    Parameters
    ----------
    db_path : str | Path | None
        数据库文件路径。默认创建在 mozhi_platform/research_failures/ 下。

    Examples
    --------
    >>> registry = ResearchFailuresRegistry()
    >>> registry.initialize()
    >>> record = ResearchFailureRecord(
    ...     strategy_name="grid_601857",
    ...     researcher="moheng",
    ...     failure_type_verbose="TEMPORAL_DECAY",
    ...     root_cause="因子在趋势市中有效但震荡市中反转"
    ... )
    >>> fid = registry.insert_record(record)
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        # 自动推断项目根目录
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent / "research_failures"
            base_dir.mkdir(parents=True, exist_ok=True)
            (base_dir / "records").mkdir(parents=True, exist_ok=True)
            (base_dir / "index").mkdir(parents=True, exist_ok=True)
            self._base_dir: Path = base_dir
            self.db_path: Path = base_dir / _RF_DB_NAME
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._base_dir = self.db_path.parent

        self._conn: Optional[sqlite3.Connection] = None

    @property
    def base_dir(self) -> Path:
        """research_failures 目录路径"""
        return self._base_dir

    @property
    def records_dir(self) -> Path:
        """手动复盘记录存放目录"""
        return self._base_dir / "records"

    @property
    def index_dir(self) -> Path:
        """索引文件存放目录"""
        return self._base_dir / "index"

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
        schema = f"""
        CREATE TABLE IF NOT EXISTS {_RF_TABLE} (
            failure_id           TEXT PRIMARY KEY,
            strategy_name        TEXT NOT NULL,
            researcher           TEXT NOT NULL,
            failure_type_verbose TEXT NOT NULL,
            root_cause           TEXT NOT NULL DEFAULT '',
            discovery_date       TEXT NOT NULL DEFAULT '',
            data_source_version  TEXT NOT NULL DEFAULT '',
            notes                TEXT DEFAULT '',
            cross_ref_q9a        TEXT,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_rf_strategy_name  ON {_RF_TABLE}(strategy_name);
        CREATE INDEX IF NOT EXISTS idx_rf_researcher     ON {_RF_TABLE}(researcher);
        CREATE INDEX IF NOT EXISTS idx_rf_failure_type   ON {_RF_TABLE}(failure_type_verbose);
        CREATE INDEX IF NOT EXISTS idx_rf_discovery_date ON {_RF_TABLE}(discovery_date);
        CREATE INDEX IF NOT EXISTS idx_rf_cross_ref_q9a  ON {_RF_TABLE}(cross_ref_q9a);
        CREATE INDEX IF NOT EXISTS idx_rf_created_at     ON {_RF_TABLE}(created_at);
        """
        self.conn.executescript(schema)
        self.conn.commit()

    # ---------- CRUD ----------

    def insert_record(self, record: ResearchFailureRecord) -> str:
        """插入一条研究失败记录，返回 failure_id

        Parameters
        ----------
        record : ResearchFailureRecord
            待插入的记录

        Returns
        -------
        str
            该记录的 failure_id
        """
        sql = f"""
        INSERT INTO {_RF_TABLE} (
            failure_id, strategy_name, researcher, failure_type_verbose,
            root_cause, discovery_date, data_source_version,
            notes, cross_ref_q9a, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(sql, record.to_db_tuple())
        self.conn.commit()
        return record.failure_id

    def get_record(self, failure_id: str) -> Optional[ResearchFailureRecord]:
        """根据 failure_id 获取单条记录

        Parameters
        ----------
        failure_id : str
            失败记录唯一标识

        Returns
        -------
        ResearchFailureRecord | None
        """
        cur = self.conn.execute(
            f"SELECT * FROM {_RF_TABLE} WHERE failure_id = ?", (failure_id,)
        )
        row = cur.fetchone()
        return ResearchFailureRecord.from_db_row(row) if row else None

    def update_record(
        self,
        failure_id: str,
        *,
        strategy_name: Optional[str] = None,
        researcher: Optional[str] = None,
        failure_type_verbose: Optional[str] = None,
        root_cause: Optional[str] = None,
        discovery_date: Optional[str] = None,
        data_source_version: Optional[str] = None,
        notes: Optional[str] = None,
        cross_ref_q9a: Optional[str] = None,
    ) -> bool:
        """更新记录（仅更新提供的字段）

        Parameters
        ----------
        failure_id : str
            待更新的记录 ID
        其余字段：None 表示不更新，提供值则更新

        Returns
        -------
        bool
            是否更新成功（True = 找到并更新，False = 记录不存在）
        """
        existing = self.get_record(failure_id)
        if existing is None:
            return False

        updates: dict[str, Any] = {}
        if strategy_name is not None:
            updates["strategy_name"] = strategy_name
        if researcher is not None:
            updates["researcher"] = researcher
        if failure_type_verbose is not None:
            updates["failure_type_verbose"] = failure_type_verbose
        if root_cause is not None:
            updates["root_cause"] = root_cause
        if discovery_date is not None:
            updates["discovery_date"] = discovery_date
        if data_source_version is not None:
            updates["data_source_version"] = data_source_version
        if notes is not None:
            updates["notes"] = notes
        if cross_ref_q9a is not None:
            updates["cross_ref_q9a"] = cross_ref_q9a
        updates["updated_at"] = _now_cst().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [failure_id]
        self.conn.execute(
            f"UPDATE {_RF_TABLE} SET {set_clause} WHERE failure_id = ?", values
        )
        self.conn.commit()
        return True

    def delete_record(self, failure_id: str) -> bool:
        """删除一条记录

        Parameters
        ----------
        failure_id : str
            要删除的记录 ID

        Returns
        -------
        bool
            是否删除成功
        """
        cur = self.conn.execute(
            f"DELETE FROM {_RF_TABLE} WHERE failure_id = ?", (failure_id,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ---------- 查询 ----------

    def query(
        self,
        strategy_name: Optional[str] = None,
        researcher: Optional[str] = None,
        failure_type_verbose: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        has_cross_ref: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "discovery_date DESC, created_at DESC",
    ) -> list[ResearchFailureRecord]:
        """多条件查询研究失败记录

        Parameters
        ----------
        strategy_name : str | None
            筛选特定策略名称
        researcher : str | None
            筛选特定研究员
        failure_type_verbose : str | None
            筛选特定失败类型（模糊匹配，使用 LIKE '%...%'）
        since : str | None
            起始发现日期 (包含)
        until : str | None
            截止发现日期 (包含)
        has_cross_ref : bool | None
            True = 仅包含有 cross_ref_q9a 的，False = 仅包含无 cross_ref_q9a 的
        limit : int
            最大返回条数 (默认 100)
        offset : int
            跳过前 N 条 (用于分页)
        order_by : str
            排序规则

        Returns
        -------
        list[ResearchFailureRecord]
        """
        conditions: list[str] = []
        params: list[Any] = []

        if strategy_name is not None:
            conditions.append("strategy_name = ?")
            params.append(strategy_name)
        if researcher is not None:
            conditions.append("researcher = ?")
            params.append(researcher)
        if failure_type_verbose is not None:
            conditions.append("failure_type_verbose LIKE ?")
            params.append(f"%{failure_type_verbose}%")
        if since is not None:
            conditions.append("discovery_date >= ?")
            params.append(since)
        if until is not None:
            conditions.append("discovery_date <= ?")
            params.append(until)
        if has_cross_ref is True:
            conditions.append("cross_ref_q9a IS NOT NULL")
        elif has_cross_ref is False:
            conditions.append("cross_ref_q9a IS NULL")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM {_RF_TABLE} WHERE {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)

        cur = self.conn.execute(sql, params)
        return [ResearchFailureRecord.from_db_row(row) for row in cur.fetchall()]

    # ---------- 统计分析 ----------

    def count_by_failure_type(self) -> list[tuple[str, int]]:
        """按失败类型统计记录数

        Returns
        -------
        list[tuple[str, int]]
            [(failure_type_verbose, count), ...] 按数量降序
        """
        cur = self.conn.execute(
            f"SELECT failure_type_verbose, COUNT(*) AS cnt "
            f"FROM {_RF_TABLE} GROUP BY failure_type_verbose ORDER BY cnt DESC"
        )
        return [(row["failure_type_verbose"], row["cnt"]) for row in cur.fetchall()]

    def count_by_researcher(self) -> list[tuple[str, int]]:
        """按研究员统计记录数

        Returns
        -------
        list[tuple[str, int]]
            [(researcher, count), ...]
        """
        cur = self.conn.execute(
            f"SELECT researcher, COUNT(*) AS cnt "
            f"FROM {_RF_TABLE} GROUP BY researcher ORDER BY cnt DESC"
        )
        return [(row["researcher"], row["cnt"]) for row in cur.fetchall()]

    def count_by_strategy(self) -> list[tuple[str, int]]:
        """按策略名称统计失败次数（可识别"高失败率策略"）

        Returns
        -------
        list[tuple[str, int]]
            [(strategy_name, count), ...] 按失败次数降序
        """
        cur = self.conn.execute(
            f"SELECT strategy_name, COUNT(*) AS cnt "
            f"FROM {_RF_TABLE} GROUP BY strategy_name ORDER BY cnt DESC"
        )
        return [(row["strategy_name"], row["cnt"]) for row in cur.fetchall()]

    def get_cross_ref_counts(self) -> dict[str, Any]:
        """获取交叉引用统计（Q9b ↔ Q9a）

        Returns
        -------
        dict:
            - total: Q9b 总记录数
            - with_cross_ref: 有 cross_ref_q9a 的记录数
            - without_cross_ref: 无 cross_ref_q9a 的记录数
            - cross_ref_ratio: 交叉引用比例
        """
        total = max(self.count(), 1)
        cur_with = self.conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {_RF_TABLE} WHERE cross_ref_q9a IS NOT NULL"
        )
        with_ref = cur_with.fetchone()["cnt"]
        return {
            "total": self.count(),
            "with_cross_ref": with_ref,
            "without_cross_ref": total - with_ref,
            "cross_ref_ratio": round(with_ref / total, 4),
        }

    def count(self) -> int:
        """返回总记录数

        Returns
        -------
        int
        """
        cur = self.conn.execute(f"SELECT COUNT(*) AS cnt FROM {_RF_TABLE}")
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def batch_insert(self, records: list[ResearchFailureRecord]) -> list[str]:
        """批量插入多条记录

        Parameters
        ----------
        records : list[ResearchFailureRecord]
            待插入的记录列表

        Returns
        -------
        list[str]
            每条记录对应的 failure_id 列表
        """
        sql = f"""
        INSERT INTO {_RF_TABLE} (
            failure_id, strategy_name, researcher, failure_type_verbose,
            root_cause, discovery_date, data_source_version,
            notes, cross_ref_q9a, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        tuples = [r.to_db_tuple() for r in records]
        self.conn.executemany(sql, tuples)
        self.conn.commit()
        return [r.failure_id for r in records]

    # ---------- 索引维护 ----------

    def build_index(self) -> dict[str, Path]:
        """重新生成所有索引文件

        按 failure_type_verbose、researcher、strategy_name 生成 JSON 索引。

        Returns
        -------
        dict[str, Path]:
            {index_type: file_path}
        """
        # 按失败类型索引
        by_type = self.count_by_failure_type()
        type_index = {"type": "by_failure_type", "built_at": _now_cst().isoformat(), "entries": [
            {"failure_type": t, "count": c} for t, c in by_type
        ]}
        type_path = self.index_dir / "by_failure_type.json"
        type_path.write_text(json.dumps(type_index, ensure_ascii=False, indent=2), encoding="utf-8")

        # 按策略索引
        by_strategy = self.count_by_strategy()
        strat_index = {"type": "by_strategy", "built_at": _now_cst().isoformat(), "entries": [
            {"strategy_name": s, "count": c, "failure_ids": [
                r.failure_id for r in self.query(strategy_name=s, limit=1000)
            ]} for s, c in by_strategy
        ]}
        strat_path = self.index_dir / "by_strategy.json"
        strat_path.write_text(json.dumps(strat_index, ensure_ascii=False, indent=2), encoding="utf-8")

        # 按研究员索引
        by_researcher = self.count_by_researcher()
        res_index = {"type": "by_researcher", "built_at": _now_cst().isoformat(), "entries": [
            {"researcher": r, "count": c} for r, c in by_researcher
        ]}
        res_path = self.index_dir / "by_researcher.json"
        res_path.write_text(json.dumps(res_index, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "by_failure_type": type_path,
            "by_strategy": strat_path,
            "by_researcher": res_path,
        }

    # ---------- 生命周期 ----------

    def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "ResearchFailuresRegistry":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
