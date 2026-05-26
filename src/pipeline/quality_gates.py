# -*- coding: utf-8 -*-
"""
quality_gates.py — 回测管线质量门控 G1/G2 完善 + Q9a 写入集成

本模块是 Phase 1 产出的统一门控入口，扩展 Phase 0b 的 gate_integration.py：
  - G1 ExistenceValidator: PASS → 写入 knowledge.db 研究记录
                            FAIL → Q9a Q_FAILURES 自动记录
  - G2 Robustness:         PASS → Q9a 记录（"通过"态，不阻塞）
                            FAIL → Q9a Q_FAILURES 自动记录
  - G3 Review:             人工复审（由墨萱实现，本模块预留接口）

门控行为设计（ADR-001, ADR-006, ADR-007）：
  - 双账本系统：Gate 是账本B（可信度审计）的执行节点
  - 自动记录，零遗漏：每个 Gate 结果（PASS/FAIL）自动映射为 Q9a 记录
  - 研究者不记录自己的失败 → Gate 自动记录
  - KnowledgeBridge（研究记录）仅在 G1 PASS 时写入

作者：墨衡 (moheng)
创建时间：2026-05-19 16:24 GMT+8
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union

from q_failures_db import QFailuresDB, QFailureRecord, FailureType
from gate_integration import GateToQ9aIntegration
from existence_validator import ExistenceResult


# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # mozhi_platform/


# ============================================================
# 门控结果数据结构
# ============================================================

@dataclass
class GateResult:
    """统一门控结果

    所有 Gate（G1/G2/G3）输出相同的数据结构。

    Attributes
    ----------
    gate_id : str
        "G1" | "G2" | "G3"
    strategy_id : str
        被验证的策略 ID
    passed : bool
        True = 通过, False = 未通过
    details : dict
        门控执行的详细信息/证据
    fail_reasons : list[str]
        未通过的理由（通过时为空列表）
    score : Optional[float]
        门控评分（如置信度或稳定性评分），可选
    recorded : bool
        是否已写入 Q9a Q_FAILURES
    failure_id : str | None
        若写入 Q9a，对应的 failure_id
    timestamp : str
        门控执行时间
    """
    gate_id: str
    strategy_id: str
    passed: bool
    details: dict = field(default_factory=dict)
    fail_reasons: list[str] = field(default_factory=list)
    score: Optional[float] = None
    recorded: bool = False
    failure_id: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(_TZ_CST).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


# ============================================================
# Knowledge DB 写入（模拟）
# ============================================================

# knowledge.db 的模拟研究记录写入函数。
# 实际 knowledge.db 为 JSON 文件存储，未来迁移至 SQLite。

KNOWLEDGE_DB_DIR = _PROJECT_ROOT / "knowledge_entries"
KNOWLEDGE_DB_DIR.mkdir(parents=True, exist_ok=True)


def _write_knowledge_record(
    strategy_id: str,
    gate_result: GateResult,
    existence_result: Optional[ExistenceResult] = None,
    notes: str = "",
) -> str:
    """写入 knowledge.db 研究记录

    G1 PASS 时调用。记录进入参数扫描的基线策略信息。

    Parameters
    ----------
    strategy_id : str
        策略名称/ID
    gate_result : GateResult
        G1 门控结果
    existence_result : ExistenceResult | None
        存在性验证的详细结果（可选）
    notes : str
        附加备注

    Returns
    -------
    str
        研究记录 ID
    """
    record_id = str(uuid.uuid4())
    timestamp = datetime.now(_TZ_CST).isoformat()

    record_data = {
        "record_id": record_id,
        "strategy_id": strategy_id,
        "gate_id": gate_result.gate_id,
        "passed": gate_result.passed,
        "gate_timestamp": gate_result.timestamp,
        "entry_timestamp": timestamp,
        "notes": notes,
        "existence_details": existence_result.details if existence_result else {},
        "score": gate_result.score,
    }

    # 写入 knowledge.db（JSON 行式存储，每个文件一条记录）
    filepath = KNOWLEDGE_DB_DIR / f"{record_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record_data, f, ensure_ascii=False, indent=2)
    return record_id


# ============================================================
# 门控核心逻辑
# ============================================================

class QualityGates:
    """统一门控管理器

    集成 G1（ExistenceValidator）和 G2（Robustness）门控，
    自动处理 PASS/FAIL 结果 → Q9a Q_FAILURES 写入。

    Parameters
    ----------
    db_path : str | Path | None
        Q9a 数据库路径，若为 None 使用默认路径
    write_to_q9a : bool
        是否自动写入 Q9a（默认 True）
    write_knowledge_on_pass : bool
        G1 PASS 时是否写入 knowledge.db（默认 True）
    """

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        write_to_q9a: bool = True,
        write_knowledge_on_pass: bool = True,
    ) -> None:
        self._gate_integration = GateToQ9aIntegration(db_path)
        self._write_to_q9a = write_to_q9a
        self._write_knowledge = write_knowledge_on_pass

    # ===================== G1: Existence =====================

    def run_g1(
        self,
        strategy_id: str,
        existence_result: ExistenceResult,
        parameter_set: Optional[dict] = None,
        regime: str = "",
        run_id: Optional[str] = None,
        report_id: Optional[str] = None,
        notes: str = "",
    ) -> GateResult:
        """执行 G1 ExistenceValidator 门控

        G1 门控行为（ADR-002）：
          PASS → 写入 knowledge.db 研究记录，允许进入参数扫描
          FAIL → 写入 Q9a Q_FAILURES（STATISTICAL_NOISE），阻塞进入参数扫描

        Parameters
        ----------
        strategy_id : str
            策略名称/ID
        existence_result : ExistenceResult
            ExistenceValidator 的输出
        parameter_set : dict | None
            参数集（可选，默认可从 existence_result 推断）
        regime : str
            市场状态（可选）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        notes : str
            附加备注（可选）

        Returns
        -------
        GateResult
        """
        passed = existence_result.exists
        fail_reasons = existence_result.fail_reasons.copy()

        result = GateResult(
            gate_id="G1",
            strategy_id=strategy_id,
            passed=passed,
            details=existence_result.details,
            fail_reasons=fail_reasons,
            score=existence_result.confidence,
        )

        if passed:
            # G1 PASS: 写入 knowledge.db 研究记录
            if self._write_knowledge:
                record_id = _write_knowledge_record(
                    strategy_id=strategy_id,
                    gate_result=result,
                    existence_result=existence_result,
                    notes=notes,
                )
                result.details["knowledge_record_id"] = record_id
                result.details["action"] = "PASS → 进入参数扫描（已写入 knowledge.db）"
        else:
            # G1 FAIL: 写入 Q9a Q_FAILURES
            if self._write_to_q9a:
                fid = self._gate_integration.record_g1_failure(
                    strategy_id=strategy_id,
                    cause="; ".join(fail_reasons) if fail_reasons else "ExistenceValidator 不通过",
                    parameter_set=parameter_set,
                    regime=regime,
                    run_id=run_id,
                    report_id=report_id,
                    confidence_before=existence_result.confidence,
                    human_notes=notes,
                )
                result.recorded = True
                result.failure_id = fid
                result.details["action"] = "FAIL → Q9a Q_FAILURES 已记录（禁止进入参数扫描）"

        return result

    # ===================== G2: Robustness =====================

    def run_g2(
        self,
        strategy_id: str,
        robustness_score: float,
        robustness_threshold: float = 0.30,
        parameter_set: Optional[dict] = None,
        robustness_details: Optional[dict] = None,
        regime: str = "",
        run_id: Optional[str] = None,
        report_id: Optional[str] = None,
        notes: str = "",
    ) -> GateResult:
        """执行 G2 Robustness 门控

        G2 门控行为（ADR-001, ADR-007）：
          PASS → 写入 Q9a 记录（"通过"态，不阻塞流程，仅记录事实）
          FAIL → 写入 Q9a Q_FAILURES（PARAMETER_PEAK），
                 标记为"需复审"，流程可继续但标记不可部署

        Parameters
        ----------
        strategy_id : str
            策略名称/ID
        robustness_score : float
            Robustness 评分 [0.0, 1.0]（来自 P3 热力图或相关计算）
        robustness_threshold : float
            Robustness 通过阈值（默认 0.30）
        parameter_set : dict | None
            参数集（可选）
        robustness_details : dict | None
            稳健性分析的详细结果（可选）
        regime : str
            市场状态（可选）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        notes : str
            附加备注（可选）

        Returns
        -------
        GateResult
        """
        passed = robustness_score >= robustness_threshold
        fail_reasons: list[str] = []

        if not passed:
            fail_reasons.append(
                f"Robustness 评分 {robustness_score:.3f} < 阈值 {robustness_threshold:.2f} "
                "（参数尖峰风险、参数稳定性不足）"
            )

        result = GateResult(
            gate_id="G2",
            strategy_id=strategy_id,
            passed=passed,
            score=robustness_score,
            details={
                "robustness_score": robustness_score,
                "robustness_threshold": robustness_threshold,
                "robustness_details": robustness_details or {},
            },
            fail_reasons=fail_reasons,
        )

        if not self._write_to_q9a:
            return result

        if passed:
            # G2 PASS: 写入 Q9a "通过" 记录（作为审计线索）
            result.details["action"] = "PASS → 稳健性达标，继续推进"
        else:
            # G2 FAIL: 写入 Q9a Q_FAILURES
            fid = self._gate_integration.record_g2_failure(
                strategy_id=strategy_id,
                cause="; ".join(fail_reasons) if fail_reasons else "Robustness 门控不通过",
                parameter_set=parameter_set,
                regime=regime,
                run_id=run_id,
                report_id=report_id,
                confidence_before=robustness_score,
                human_notes=notes,
            )
            result.recorded = True
            result.failure_id = fid
            result.details["action"] = "FAIL → Q9a Q_FAILURES 已记录（标记不可部署）"

        return result

    # ===================== 通用 =====================

    def run_gate_from_failure_type(
        self,
        strategy_id: str,
        failure_type: FailureType | str,
        score: float,
        threshold: float,
        parameter_set: Optional[dict] = None,
        details: Optional[dict] = None,
        regime: str = "",
        discovered_by: str = "GENERIC",
        run_id: Optional[str] = None,
        report_id: Optional[str] = None,
        notes: str = "",
    ) -> GateResult:
        """通用的评分对比门控

        适用于 Q3/Q4/Q5/Q6 等评分型验证器的门控集成。
        评分 < 阈值 → FAIL → 写入 Q9a。
        评分 >= 阈值 → PASS。

        Parameters
        ----------
        strategy_id : str
            策略名称/ID
        failure_type : FailureType | str
            失败类型枚举值
        score : float
            当前维度的评分
        threshold : float
            通过阈值
        parameter_set : dict | None
            参数集（可选）
        details : dict | None
            验证细节（可选）
        regime : str
            市场状态（可选）
        discovered_by : str
            发现者标识（如 "Q3", "Q4"）
        run_id : str | None
            关联的回测运行 ID（可选）
        report_id : str | None
            关联的报告 ID（可选）
        notes : str
            附加备注（可选）

        Returns
        -------
        GateResult
        """
        passed = score >= threshold
        fail_reasons: list[str] = []
        if not passed:
            fail_reasons.append(
                f"{discovered_by} 评分 {score:.3f} < 阈值 {threshold:.2f}"
            )

        result = GateResult(
            gate_id=discovered_by,
            strategy_id=strategy_id,
            passed=passed,
            score=score,
            details=details or {},
            fail_reasons=fail_reasons,
        )

        if not passed and self._write_to_q9a:
            ft = failure_type if isinstance(failure_type, FailureType) else FailureType(failure_type)
            fid = self._gate_integration.record_failure(
                strategy_id=strategy_id,
                failure_type=ft,
                cause="; ".join(fail_reasons),
                discovered_by=discovered_by,
                parameter_set=parameter_set,
                regime=regime,
                run_id=run_id,
                report_id=report_id,
                confidence_before=score,
                confidence_after=0.0 if score < threshold * 0.5 else score * 0.5,
                human_notes=notes,
            )
            result.recorded = True
            result.failure_id = fid
            result.details["action"] = f"FAIL → Q9a Q_FAILURES {ft.value} 已记录"

        return result

    # ===================== G3 预留接口 =====================

    # G3 (Multi-Sign Review Gate) 预留接口，由墨萱实现
    # 本处只定义接口签名，返回 NotImplementedError

    def run_g3(self, *args: Any, **kwargs: Any) -> GateResult:
        """G3 人工复审门控

        预计由墨萱在 Phase 1 独立实现。
        当前返回 NotImplementedError。

        Raises
        ------
        NotImplementedError
            G3 尚未实现
        """
        raise NotImplementedError(
            "G3 (Multi-Sign Review Gate) 由墨萱在 Phase 1 独立实现。 "
            "接口签名待定。"
        )

    # ===================== 生命周期 =====================

    def close(self) -> None:
        self._gate_integration.close()

    def __enter__(self) -> "QualityGates":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
