# -*- coding: utf-8 -*-
"""
gate_integration.py — Quality Gate → Q9a Q_FAILURES 自动集成

G1/G2/G3 三个门控的失败结果自动写入 Q_FAILURES 数据库。
门控失败时调用本模块的 hook 函数，无需手动记录。

映射规则：
  G1 (ExistenceValidator) FAIL  → failure_type=STATISTICAL_NOISE, discovered_by="Q1"
  G2 (Robustness) FAIL          → failure_type=PARAMETER_PEAK,   discovered_by="Q2"
  G3 (Multi-Sign) FAIL          → failure_type=HUMAN_REJECTED,   discovered_by="G3"

Design Rationale (ADR-001, ADR-007):
  - 双账本系统：Gate 是账本B（可信度审计）的执行节点
  - 研究者不记录自己的失败 → Gate 自动记录
  - 确保零遗漏：每条 Gate 失败自动映射为 Q_FAILURES 记录

作者：墨衡 (moheng)
创建时间：2026-05-19 16:16 GMT+8
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from q_failures_db import QFailuresDB, QFailureRecord, FailureType

# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")


# ============================================================
# 门控集成
# ============================================================

class GateToQ9aIntegration:
    """Quality Gate → Q9a Q_FAILURES 自动写入集成

    用法：在每个 Gate 的 "Fail" 分支调用对应的静态方法。

    Parameters
    ----------
    db_path : str | Path | None
        数据库路径，传递给 QFailuresDB
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._db = QFailuresDB(db_path)
        self._db.initialize()

    # ---------- G1: ExistenceValidator ----------

    def record_g1_failure(
        self,
        strategy_id: str,
        cause: str,
        parameter_set: dict | None = None,
        regime: str = "",
        run_id: str | None = None,
        report_id: str | None = None,
        confidence_before: float | None = None,
        human_notes: str = "",
    ) -> str:
        """G1 (ExistenceValidator) 失败时自动写入 Q_FAILURES

        Parameters
        ----------
        strategy_id : str
            失败的策略 ID
        cause : str
            失败原因描述（优先使用 ExistenceResult.fail_reasons 拼接）
        parameter_set : dict | None
            参数集（可选）
        regime : str
            市场状态（可选）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        confidence_before : float | None
            失败前的综合置信度（可选）
        human_notes : str
            人工备注（可选）

        Returns
        -------
        str
            写入的 failure_id
        """
        record = QFailureRecord(
            strategy_id=strategy_id,
            parameter_set=parameter_set or {},
            failure_type=FailureType.STATISTICAL_NOISE,
            regime=regime,
            cause=cause,
            discovered_by="Q1",
            confidence_before=confidence_before,
            confidence_after=0.0,
            run_id=run_id,
            report_id=report_id,
            human_notes=human_notes,
        )
        return self._db.insert_record(record)

    # ---------- G2: Robustness ----------

    def record_g2_failure(
        self,
        strategy_id: str,
        cause: str,
        parameter_set: dict | None = None,
        regime: str = "",
        run_id: str | None = None,
        report_id: str | None = None,
        confidence_before: float | None = None,
        human_notes: str = "",
    ) -> str:
        """G2 (Robustness) 失败时自动写入 Q_FAILURES

        Parameters
        ----------
        strategy_id : str
            失败的策略 ID
        cause : str
            失败原因描述
        parameter_set : dict | None
            参数集（可选）
        regime : str
            市场状态（可选）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        confidence_before : float | None
            失败前的综合置信度（可选）
        human_notes : str
            人工备注（可选）

        Returns
        -------
        str
            写入的 failure_id
        """
        record = QFailureRecord(
            strategy_id=strategy_id,
            parameter_set=parameter_set or {},
            failure_type=FailureType.PARAMETER_PEAK,
            regime=regime,
            cause=cause,
            discovered_by="Q2",
            confidence_before=confidence_before,
            confidence_after=0.0,
            run_id=run_id,
            report_id=report_id,
            human_notes=human_notes,
        )
        return self._db.insert_record(record)

    # ---------- G3: Multi-Sign ----------

    def record_g3_failure(
        self,
        strategy_id: str,
        cause: str,
        parameter_set: dict | None = None,
        regime: str = "",
        run_id: str | None = None,
        report_id: str | None = None,
        confidence_before: float | None = None,
        human_notes: str = "",
    ) -> str:
        """G3 (Multi-Sign) 人工复审不通过时自动写入 Q_FAILURES

        Parameters
        ----------
        strategy_id : str
            失败的策略 ID
        cause : str
            人工复审不通过的原因
        parameter_set : dict | None
            参数集（可选）
        regime : str
            市场状态（可选）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        confidence_before : float | None
            失败前的综合置信度（可选）
        human_notes : str
            人工备注，可补充复审意见

        Returns
        -------
        str
            写入的 failure_id
        """
        record = QFailureRecord(
            strategy_id=strategy_id,
            parameter_set=parameter_set or {},
            failure_type=FailureType.HUMAN_REJECTED,
            regime=regime,
            cause=cause,
            discovered_by="G3",
            confidence_before=confidence_before,
            confidence_after=0.0,
            run_id=run_id,
            report_id=report_id,
            human_notes=human_notes,
        )
        return self._db.insert_record(record)

    # ---------- 通用写入 ----------

    def record_failure(
        self,
        strategy_id: str,
        failure_type: FailureType | str,
        cause: str,
        discovered_by: str,
        parameter_set: dict | None = None,
        regime: str = "",
        run_id: str | None = None,
        report_id: str | None = None,
        confidence_before: float | None = None,
        confidence_after: float | None = None,
        human_notes: str = "",
    ) -> str:
        """通用写入：非 G1/G2/G3 的其他 Q 层验证失败

        适用于 Q3 (REGIME_BOUNDED), Q4 (CAPACITY_LIMITED),
        Q5 (TEMPORAL_DECAY), Q6 (OOS_FAILURE), Q7 (LOW_CONFIDENCE) 等。

        Parameters
        ----------
        strategy_id : str
            失败的策略 ID
        failure_type : FailureType | str
            失败类型
        cause : str
            失败原因
        discovered_by : str
            发现者，如 "Q3", "Q4", "Q5", "Q6", "Q7"
        parameter_set : dict | None
            参数集（可选）
        regime : str
            市场状态（可选）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        confidence_before : float | None
            失败前的置信度（可选）
        confidence_after : float | None
            失败后的置信度（可选）
        human_notes : str
            人工备注（可选）

        Returns
        -------
        str
            写入的 failure_id
        """
        ft = failure_type if isinstance(failure_type, FailureType) else FailureType(failure_type)
        record = QFailureRecord(
            strategy_id=strategy_id,
            parameter_set=parameter_set or {},
            failure_type=ft,
            regime=regime,
            cause=cause,
            discovered_by=discovered_by,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            run_id=run_id,
            report_id=report_id,
            human_notes=human_notes,
        )
        return self._db.insert_record(record)

    # ---------- 便捷工厂方法 ----------

    @staticmethod
    def from_existence_result(
        strategy_id: str,
        fail_reasons: list[str],
        parameter_set: dict | None = None,
        regime: str = "",
        run_id: str | None = None,
        report_id: str | None = None,
        confidence_before: float | None = None,
    ) -> tuple[str, str]:
        """从 ExistenceResult.fail_reasons 快速创建 G1 失败记录

        这是最常用的工厂方法——ExistenceValidator 失败后只需一行调用。

        Parameters
        ----------
        strategy_id : str
            策略 ID
        fail_reasons : list[str]
            ExistenceResult.fail_reasons 列表
        parameter_set : dict | None
            参数集（可选）
        regime : str
            市场状态（可选）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        confidence_before : float | None
            失败前的置信度（可选）

        Returns
        -------
        tuple[str, str]
            (failure_id, summary_string)
            summary_string 是 fail_reasons 用 "; " 拼接后的摘要，便于日志记录
        """
        cause = "; ".join(fail_reasons)
        integrator = GateToQ9aIntegration()
        fid = integrator.record_g1_failure(
            strategy_id=strategy_id,
            cause=cause,
            parameter_set=parameter_set,
            regime=regime,
            run_id=run_id,
            report_id=report_id,
            confidence_before=confidence_before,
        )
        integrator.close()
        return fid, cause

    def close(self) -> None:
        """关闭数据库连接"""
        self._db.close()

    def __enter__(self) -> "GateToQ9aIntegration":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
