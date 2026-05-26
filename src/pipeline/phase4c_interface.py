# -*- coding: utf-8 -*-
"""
phase4c_interface.py — Phase 4c 策略接入 Q 层验证管线的集成接口

Phase 4c 未来策略（六层结构重构后的统一策略系统）通过本模块接入
现有的 Q 层验证管线（Q1~Q8）和 Quality Gates（G1/G2/G3）。

本模块充当适配层 (Adapter Layer)：
  - Phase 4c 的输出（strategy_params dict）→ 转换为 Transaction 记录
  - Transaction 记录 → 送入 ExistenceValidator / Q3 / Q5 等验证器
  - 验证结果 → 返回统一的 ValidationReport

集成协议定义（与 Phase 4c 执行计划对齐）：
  Phase4cInterface
    ├── submit_for_validation(strategy_params) → task_id
    ├── get_validation_status(task_id) → ValidationStatus
    ├── get_validation_report(task_id) → dict
    └── submit_batch(strategy_params_list) → list[task_id]

设计原则：
  - 非侵入式：不修改现有 Q 层验证器的代码
  - 标准化输出：所有验证结果统一为 ValidationReport 格式
  - 可追溯：每个验证任务有唯一 task_id，支持异步查询
  - 幂等：相同参数重复提交返回相同的 task_id

作者：墨衡 (moheng)
创建时间：2026-05-19 16:46 GMT+8
"""

from __future__ import annotations

import enum
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ..utils.existence_validator import (
    TradeRecord as ExistenceTradeRecord,
    validate_existence,
    ExistenceResult,
)
from ..utils.q3_regime_validator import (
    RegimeTradeRecord,
    validate_regime_consistency,
    RegimeValidationResult,
    map_regime_name,
)
from ..utils.q5_temporal_validator import (
    validate_temporal_stability,
    TemporalStabilityResult,
)

# ============================================================
# 日志与常量
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger("phase4c_interface")


# ============================================================
# Phase 4c 管线配置
# ============================================================

PIPELINE_CONFIG: dict[str, dict[str, Any]] = {
    "default": {
        "validators": ["G1", "Q3", "Q5"],
        "description": "默认验证管线：存在性 + Regime + 时间稳定性",
        "priority": "P0",
    },
    "full": {
        "validators": ["G1", "Q3", "Q5"],  # Q2/Q4/Q6 标记为待实现
        "description": "完整验证管线（G1 + Q3 + Q5，Q2/Q4/Q6 待实现）",
        "priority": "P0",
    },
    "quick": {
        "validators": ["G1"],
        "description": "快速验证管线：仅 G1 Existence Gate",
        "priority": "P0",
    },
    "regime": {
        "validators": ["G1", "Q3"],
        "description": "Regime 验证管线：G1 + Q3",
        "priority": "P1",
    },
}

# 待实现验证器的占位说明
_PENDING_VALIDATORS: dict[str, str] = {
    "Q2": "RobustnessSurface — 参数地形分析 (标记: P0, 工时: 2.0天)",
    "Q4": "CapacityValidator — 资金容量评估 (标记: P0, 工时: 1.0天)",
    "Q6": "OOS Survival — 样本外生存率 (标记: P1, 工时: 1.5天)",
}


# ============================================================
# 验证状态枚举
# ============================================================

class ValidationStatus(str, enum.Enum):
    """验证任务的完整生命周期状态"""
    PENDING    = "PENDING"       # 已提交，等待执行
    RUNNING    = "RUNNING"       # 正在执行验证
    COMPLETED  = "COMPLETED"     # 验证完成
    FAILED     = "FAILED"        # 验证执行失败（非验证不通过，而是执行过程出错）
    STALE      = "STALE"         # 超时未完成（保护机制）

    @classmethod
    def active_states(cls) -> set["ValidationStatus"]:
        """返回 '尚未完成' 的状态集合"""
        return {cls.PENDING, cls.RUNNING}

    @classmethod
    def terminal_states(cls) -> set["ValidationStatus"]:
        """返回 '已完成/已结束' 的状态集合"""
        return {cls.COMPLETED, cls.FAILED, cls.STALE}


# ============================================================
# 验证结果数据结构
# ============================================================

@dataclass
class ValidationReport:
    """单次验证的完整报告

    Attributes
    ----------
    task_id : str
        验证任务唯一标识
    strategy_params : dict
        被验证的策略参数
    status : ValidationStatus
        验证状态
    existence_result : ExistenceResult | None
        G1 存在性验证结果
    regime_result : RegimeValidationResult | None
        Q3 Regime 验证结果
    temporal_result : TemporalStabilityResult | None
        Q5 时间稳定性验证结果
    overall_passed : bool
        综合判定通过（所有被执行的验证均通过）
    fail_reasons : list[str]
        综合失败原因汇总
    gates_triggered : list[str]
        触发了哪些门控（"G1", "Q3", "Q5" 等）
    error_message : str
        执行错误信息（仅 status=FAILED 时）
    created_at : str
        创建时间
    completed_at : str | None
        完成时间
    """
    task_id: str
    strategy_params: dict
    status: ValidationStatus = ValidationStatus.PENDING
    existence_result: Optional[ExistenceResult] = None
    regime_result: Optional[RegimeValidationResult] = None
    temporal_result: Optional[TemporalStabilityResult] = None
    overall_passed: bool = False
    fail_reasons: list[str] = field(default_factory=list)
    gates_triggered: list[str] = field(default_factory=list)
    error_message: str = ""
    created_at: str = ""
    completed_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(_TZ_CST).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 序列化的字典"""
        d = asdict(self)
        # 复杂对象转为 dict
        if self.existence_result:
            d["existence_result"] = {
                "exists": self.existence_result.exists,
                "confidence": self.existence_result.confidence,
                "fail_reasons": self.existence_result.fail_reasons,
                "details": self.existence_result.details,
            }
        if self.regime_result:
            d["regime_result"] = {
                "passed": self.regime_result.passed,
                "positive_regime_count": self.regime_result.positive_regime_count,
                "total_regimes_observed": self.regime_result.total_regimes_observed,
                "dominant_regime": self.regime_result.dominant_regime,
                "dominant_share_pct": self.regime_result.dominant_share_pct,
                "fail_reason": self.regime_result.fail_reason,
            }
        if self.temporal_result:
            d["temporal_result"] = self.temporal_result.to_dict()
        return d


# ============================================================
# 策略参数 → 交易记录的转换器
# ============================================================

class StrategyParamsConverter:
    """Phase 4c 策略参数到验证器输入记录的转换器

    Phase 4c 的每个未来策略都以 dict 形式提交参数配置。
    本转换器解析 dict，生成 TradeRecord / RegimeTradeRecord 等
    验证器可接受的输入格式。
    """

    # Phase 4c 策略参数的标准字段名映射
    FIELD_MAP: dict[str, str] = {
        # 字段名 → 含义
        "strategy_id": "策略ID",
        "symbol": "交易标的",
        "method": "策略方法 (grid/trend/reversal/factor)",
        "params": "策略参数 dict",
        "trades": "历史交易记录 (list[dict])",
        "market_regime": "市场状态标签",
        "pnl_data": "逐日收益数据",
        "ic_data": "因子IC序列 (P7 格式)",
        "backtest_days": "回测天数",
        "date_from": "回测起始日",
        "date_to": "回测截止日",
    }

    @classmethod
    def to_existence_trades(
        cls, strategy_params: dict,
    ) -> list[ExistenceTradeRecord]:
        """将策略参数转换为存在性验证器的 TradeRecord 列表

        支持两种输入模式:
          1. 已有交易记录: strategy_params["trades"] 包含逐笔交易
          2. 仅有汇总数据: 从 pnl_data 生成单笔近似
          3. 因子 IC 模式: strategy_params["ic_data"] 为 IC 序列

        Parameters
        ----------
        strategy_params : dict
            Phase 4c 策略参数

        Returns
        -------
        list[ExistenceTradeRecord]
        """
        trades_param = strategy_params.get("trades")
        if trades_param and isinstance(trades_param, list) and len(trades_param) > 0:
            # 模式1: 已有逐笔交易
            records: list[ExistenceTradeRecord] = []
            for t in trades_param:
                pnl = t.get("pnl_pct") or t.get("pnl") or t.get("return", 0.0)
                records.append(ExistenceTradeRecord(
                    date=t.get("date", datetime.now(_TZ_CST).isoformat()),
                    pnl_pct=pnl,
                    regime=strategy_params.get("market_regime", "UNKNOWN"),
                ))
            return records

        pnl_data = strategy_params.get("pnl_data")
        if pnl_data and isinstance(pnl_data, list) and len(pnl_data) > 0:
            # 模式2: 逐日收益数据 → 按周聚合成伪交易
            weekly_pnls = cls._aggregate_pnl_to_trades(pnl_data)
            return [
                ExistenceTradeRecord(date=d, pnl_pct=p, regime=strategy_params.get("market_regime", "UNKNOWN"))
                for d, p in weekly_pnls
            ]

        ic_data = strategy_params.get("ic_data")
        if ic_data and isinstance(ic_data, list) and len(ic_data) > 0:
            # 模式3: 因子IC序列
            return [
                ExistenceTradeRecord(
                    date=item.get("date", datetime.now(_TZ_CST).isoformat()),
                    pnl_pct=item.get("ic", 0.0),
                    regime=strategy_params.get("market_regime", "UNKNOWN"),
                )
                for item in ic_data
            ]

        # 若无任何数据，返回空列表
        return []

    @classmethod
    def to_regime_trades(
        cls, strategy_params: dict,
    ) -> list[RegimeTradeRecord]:
        """将策略参数转换为 Regime 验证器的交易记录

        Parameters
        ----------
        strategy_params : dict

        Returns
        -------
        list[RegimeTradeRecord]
        """
        trades_param = strategy_params.get("trades")
        if trades_param and isinstance(trades_param, list):
            records: list[RegimeTradeRecord] = []
            for t in trades_param:
                records.append(RegimeTradeRecord(
                    date=t.get("date", datetime.now(_TZ_CST).isoformat()),
                    pnl_pct=t.get("pnl_pct", t.get("pnl", t.get("return", 0.0))),
                    regime=t.get("regime", strategy_params.get("market_regime", "UNKNOWN")),
                ))
            return records

        perf_by_regime = strategy_params.get("perf_by_regime")
        if perf_by_regime and isinstance(perf_by_regime, dict):
            return [
                RegimeTradeRecord(
                    date=datetime.now(_TZ_CST).isoformat(),
                    pnl_pct=pnl,
                    regime=regime,
                )
                for regime, pnl in perf_by_regime.items()
            ]

        return []

    @classmethod
    def to_temporal_trades(
        cls, strategy_params: dict,
    ) -> list[ExistenceTradeRecord]:
        """将策略参数转换为时间稳定性验证器的输入

        复用 to_existence_trades 的逻辑（两者使用相同的 TradeRecord 结构）

        Parameters
        ----------
        strategy_params : dict

        Returns
        -------
        list[ExistenceTradeRecord]
        """
        return cls.to_existence_trades(strategy_params)

    @staticmethod
    def _aggregate_pnl_to_trades(
        pnl_data: list[dict],
        aggregation_period: int = 5,
    ) -> list[tuple[str, float]]:
        """将逐日收益聚合成伪交易（每周一条）

        Parameters
        ----------
        pnl_data : list[dict]
            逐日收益列表，每项含 "date" 和 "pnl_pct" 字段
        aggregation_period : int
            聚合天数（默认 5 = 一周）

        Returns
        -------
        list[tuple[str, float]]
            (日期字符串, 聚合收益)
        """
        result: list[tuple[str, float]] = []
        batch: list[float] = []
        batch_date: str = ""

        for item in pnl_data:
            pnl = item.get("pnl_pct", item.get("pnl", item.get("return", 0.0)))
            date = item.get("date", "")

            batch.append(pnl)
            if not batch_date:
                batch_date = date

            if len(batch) >= aggregation_period:
                result.append((batch_date, sum(batch)))
                batch = []
                batch_date = ""

        # 余数
        if batch:
            result.append((batch_date or datetime.now(_TZ_CST).isoformat(), sum(batch)))

        return result

    @staticmethod
    def validate_input(strategy_params: dict) -> list[str]:
        """验证策略参数的完整性

        检查必填字段是否存在、数据格式是否正确。

        Parameters
        ----------
        strategy_params : dict

        Returns
        -------
        list[str]
            缺失/异常字段列表（空列表=验证通过）
        """
        issues: list[str] = []

        if not isinstance(strategy_params, dict):
            return ["输入非 dict 类型"]

        sid = strategy_params.get("strategy_id")
        if not sid:
            issues.append("缺少 strategy_id")

        method = strategy_params.get("method")
        if method and method not in ("grid", "trend", "reversal", "factor", "unknown"):
            issues.append(f"不支持的策略方法: {method}")

        trades = strategy_params.get("trades", [])
        pnl_data = strategy_params.get("pnl_data", [])
        ic_data = strategy_params.get("ic_data", [])
        perf_by_regime = strategy_params.get("perf_by_regime", {})

        has_data = bool(trades) or bool(pnl_data) or bool(ic_data) or bool(perf_by_regime)
        if not has_data:
            issues.append("无任何收益/交易/IC 数据——验证将基于空数据集进行")

        return issues


# ============================================================
# Phase 4c 集成接口
# ============================================================

class Phase4cInterface:
    """Phase 4c 接入 Q 层验证管线的统一接口

    接受 Phase 4c 的未来策略参数，自动转换并执行
    核心验证器 (ExistenceValidator / Q3 / Q5)，
    返回标准化验证报告。

    支持同步和异步（轮询）两种调用模式。

    Parameters
    ----------
    auto_run : bool
        提交后是否立即执行验证（默认 True）。
        False 时需手动调用 run_validation()。
    use_adaptive_thresholds : bool
        是否使用自适应阈值（默认 True）
    results_dir : str | Path | None
        验证报告存储目录（默认 memo_validation_reports/）
    """

    def __init__(
        self,
        auto_run: bool = True,
        use_adaptive_thresholds: bool = True,
        results_dir: Optional[str | Path] = None,
        pipeline_name: str = "default",
    ) -> None:
        self._auto_run = auto_run
        self._use_adaptive = use_adaptive_thresholds
        self._pipeline_name = pipeline_name
        self._lock = threading.Lock()

        if results_dir:
            self._results_dir = Path(results_dir)
        else:
            self._results_dir = _PROJECT_ROOT / "memo_validation_reports"
        self._results_dir.mkdir(parents=True, exist_ok=True)

        # 内存中的任务状态缓存
        self._tasks: dict[str, ValidationReport] = {}
        self._task_status: dict[str, ValidationStatus] = {}

        # 过期保护
        self._stale_threshold_seconds: int = 3600  # 1 小时

    # ==================== 核心接口 ====================

    def submit_for_validation(self, strategy_params: dict) -> str:
        """提交策略参数进行验证

        参数验证后，根据 auto_run 设置决定是否立即执行。
        返回唯一的 task_id，可用于后续状态查询。

        Parameters
        ----------
        strategy_params : dict
            Phase 4c 策略参数。标准字段：
            - strategy_id: str (必填)
            - method: str ("grid"/"trend"/"reversal"/"factor")
            - symbol: str (标的代码)
            - trades: list[dict] (逐笔交易记录，可选)
            - pnl_data: list[dict] (逐日收益，可选)
            - ic_data: list[dict] (因子IC序列，可选)
            - perf_by_regime: dict[str, float] (按Regime聚合收益，可选)
            - market_regime: str (市场状态，可选)
            - params: dict (策略参数详情，可选)

        Returns
        -------
        str
            唯一的 task_id

        Raises
        ------
        ValueError
            参数验证不通过
        """
        # 参数完整性检查
        issues = StrategyParamsConverter.validate_input(strategy_params)
        critical_issues = [i for i in issues if "无任何" not in i]

        if critical_issues:
            error_msg = "; ".join(critical_issues)
            raise ValueError(f"参数验证失败: {error_msg}")

        # 生成 task_id
        task_id = str(uuid.uuid4())

        report = ValidationReport(
            task_id=task_id,
            strategy_params=dict(strategy_params),
            status=ValidationStatus.PENDING,
        )

        with self._lock:
            self._tasks[task_id] = report
            self._task_status[task_id] = ValidationStatus.PENDING

        # 持久化初始状态
        self._persist_report(report)

        if self._auto_run:
            # 立即执行
            self.run_validation(task_id)

        return task_id

    def get_validation_status(self, task_id: str) -> ValidationStatus:
        """查询验证任务的当前状态

        Parameters
        ----------
        task_id : str
            submit_for_validation 返回的任务 ID

        Returns
        -------
        ValidationStatus
            当前状态。若 task_id 不存在返回 None。
        """
        with self._lock:
            # 检查过期
            self._check_stale(task_id)

            report = self._tasks.get(task_id)
            if report is None:
                # 尝试从磁盘恢复
                report = self._recover_report(task_id)
                if report:
                    self._tasks[task_id] = report
                    self._task_status[task_id] = report.status
                    return report.status
                # 真的不存在
                raise KeyError(f"task_id 不存在: {task_id}")

            return report.status

    def get_validation_report(self, task_id: str) -> dict[str, Any]:
        """获取验证任务的完整报告

        Parameters
        ----------
        task_id : str

        Returns
        -------
        dict
            验证报告的 dict 格式

        Raises
        ------
        KeyError
            task_id 不存在
        ValueError
            验证尚未完成
        """
        with self._lock:
            self._check_stale(task_id)

            report = self._tasks.get(task_id)
            if report is None:
                report = self._recover_report(task_id)
                if report:
                    self._tasks[task_id] = report
                    self._task_status[task_id] = report.status
                else:
                    raise KeyError(f"task_id 不存在: {task_id}")

            if report.status in ValidationStatus.active_states():
                raise ValueError(f"验证尚未完成 (当前状态: {report.status.value})")

            return report.to_dict()

    # ==================== 执行引擎 ====================

    def run_validation(self, task_id: str) -> ValidationReport:
        """执行单次验证任务（同步）

        执行流程:
          1. 状态 → RUNNING
          2. 参数转换 → 验证器输入
          3. 运行 ExistenceValidator (G1)
          4. 运行 Q3 Regime Validator
          5. 运行 Q5 Temporal Validator
          6. 综合判定 → 写入报告
          7. 状态 → COMPLETED (或 FAILED)

        Parameters
        ----------
        task_id : str

        Returns
        -------
        ValidationReport
        """
        with self._lock:
            report = self._tasks.get(task_id)
            if report is None:
                raise KeyError(f"task_id 不存在: {task_id}")

            report.status = ValidationStatus.RUNNING
            self._task_status[task_id] = ValidationStatus.RUNNING
            self._persist_report(report)

        # 释放锁后执行（避免长时间持有锁）
        try:
            params = report.strategy_params
            method = params.get("method", "unknown")
            strategy_id = params.get("strategy_id", "unknown")
            time_span_years = self._compute_time_span_years(params)
            n_records_est = self._estimate_record_count(params)
            fail_reasons: list[str] = []
            gates: list[str] = []

            # ---- Step 1: ExistenceValidator ----
            existence_trades = StrategyParamsConverter.to_existence_trades(params)
            if existence_trades:
                # 自适应阈值
                c1_threshold, c5_threshold = self._get_adaptive_thresholds(
                    method, time_span_years, n_records_est,
                )

                existence_result = validate_existence(
                    existence_trades,
                    c1_min_trades=c1_threshold,
                    c2_min_regimes=max(1, int(time_span_years / 1.5) + 1) if self._use_adaptive else 2,
                    c4_max_share=min(0.40, 0.40 * (len(existence_trades) / 30) ** 0.5) if self._use_adaptive and len(existence_trades) < 30 else 0.40,
                    c5_min_density=c5_threshold,
                )
                gates.append("G1")

                with self._lock:
                    report.existence_result = existence_result
                    if not existence_result.exists:
                        fail_reasons.extend(existence_result.fail_reasons)
            else:
                existence_result = None
                logger.warning("task %s: 无交易记录，跳过 ExistenceValidator", task_id)
                fail_reasons.append("无交易记录——存在性验证无法执行")

            # ---- Step 2: Q3 Regime Validator ----
            regime_trades = StrategyParamsConverter.to_regime_trades(params)
            if regime_trades:
                min_positive = self._get_regime_threshold(time_span_years)
                regime_result = validate_regime_consistency(
                    regime_trades,
                    min_positive_regimes=min_positive,
                )
                gates.append("Q3")

                with self._lock:
                    report.regime_result = regime_result
                    if not regime_result.passed:
                        fail_reasons.append(regime_result.fail_reason or "Regime 验证不通过")
            else:
                regime_result = None
                logger.warning("task %s: 无 Regime 数据，跳过 Q3", task_id)

            # ---- Step 3: Q5 Temporal Validator ----
            temporal_trades = StrategyParamsConverter.to_temporal_trades(params)
            if temporal_trades:
                n_temporal = len(temporal_trades)
                if n_temporal >= 8 or (not self._use_adaptive):
                    temporal_result = validate_temporal_stability(
                        temporal_trades,
                        direction_threshold=0.02 if self._use_adaptive else 0.01,
                    )
                    gates.append("Q5")

                    with self._lock:
                        report.temporal_result = temporal_result
                        if not temporal_result.is_stable:
                            fail_reasons.append(temporal_result.fail_reason or "时间稳定性验证不通过")
                else:
                    temporal_result = None
                    logger.info(
                        "task %s: 时间稳定性验证跳过 (记录数 %d < 8)",
                        task_id, n_temporal,
                    )
            else:
                temporal_result = None
                logger.warning("task %s: 无时间序列数据，跳过 Q5", task_id)

            # ---- 综合判定 ----
            overall_pass = len(fail_reasons) == 0

            with self._lock:
                report.status = ValidationStatus.COMPLETED
                report.overall_passed = overall_pass
                report.fail_reasons = fail_reasons
                report.gates_triggered = gates
                report.completed_at = datetime.now(_TZ_CST).isoformat()
                self._task_status[task_id] = ValidationStatus.COMPLETED
                self._persist_report(report)

            return report

        except Exception as exc:
            logger.exception("task %s 验证执行异常", task_id)

            with self._lock:
                report.status = ValidationStatus.FAILED
                report.overall_passed = False
                report.error_message = str(exc)
                report.completed_at = datetime.now(_TZ_CST).isoformat()
                self._task_status[task_id] = ValidationStatus.FAILED
                self._persist_report(report)

            return report

    def submit_batch(
        self, strategy_params_list: list[dict],
    ) -> list[str]:
        """批量提交多个策略进行验证

        Parameters
        ----------
        strategy_params_list : list[dict]
            多个策略参数列表

        Returns
        -------
        list[str]
            每个策略对应的 task_id 列表（保持输入顺序）
        """
        task_ids: list[str] = []
        errors: list[tuple[int, str]] = []

        for idx, params in enumerate(strategy_params_list):
            try:
                tid = self.submit_for_validation(params)
                task_ids.append(tid)
            except ValueError as exc:
                errors.append((idx, str(exc)))
                task_ids.append("")

        if errors:
            error_detail = "; ".join(
                f"序号 {i}: {msg}" for i, msg in errors
            )
            logger.warning("批量提交中有 %d 个失败: %s", len(errors), error_detail)

        return task_ids

    # ==================== 持久化 ====================

    def _persist_report(self, report: ValidationReport) -> None:
        """将验证报告持久化到 JSON 文件"""
        try:
            filepath = self._results_dir / f"{report.task_id}.json"
            filepath.write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("持久化失败 task %s: %s", report.task_id, exc)

    def _recover_report(self, task_id: str) -> Optional[ValidationReport]:
        """从磁盘恢复报告

        Parameters
        ----------
        task_id : str

        Returns
        -------
        ValidationReport | None
        """
        filepath = self._results_dir / f"{task_id}.json"
        if not filepath.exists():
            return None
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            # 重建对象（简化反序列化）
            report = ValidationReport(
                task_id=data["task_id"],
                strategy_params=data.get("strategy_params", {}),
                status=ValidationStatus(data.get("status", "PENDING")),
                overall_passed=data.get("overall_passed", False),
                fail_reasons=data.get("fail_reasons", []),
                gates_triggered=data.get("gates_triggered", []),
                error_message=data.get("error_message", ""),
                created_at=data.get("created_at", ""),
                completed_at=data.get("completed_at"),
            )
            return report
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("恢复报告失败 task %s: %s", task_id, exc)
            return None

    # ==================== 内部工具方法 ====================

    def _compute_time_span_years(self, params: dict) -> float:
        """计算策略回测的时间跨度（年）

        Parameters
        ----------
        params : dict

        Returns
        -------
        float
            时间跨度（年）
        """
        # 优先从字段读取
        days = params.get("backtest_days")
        if days:
            return days / 365.25

        trades = params.get("trades", [])
        if len(trades) >= 2:
            dates = sorted(t.get("date", "") for t in trades if t.get("date"))
            if len(dates) >= 2:
                try:
                    d1 = datetime.fromisoformat(dates[0])
                    d2 = datetime.fromisoformat(dates[-1])
                    return (d2 - d1).days / 365.25
                except (ValueError, TypeError):
                    pass

        pnl_data = params.get("pnl_data", [])
        if len(pnl_data) >= 2:
            dates = sorted(
                d.get("date", "") for d in pnl_data if d.get("date")
            )
            if len(dates) >= 2:
                try:
                    d1 = datetime.fromisoformat(dates[0])
                    d2 = datetime.fromisoformat(dates[-1])
                    return (d2 - d1).days / 365.25
                except (ValueError, TypeError):
                    pass

        # 有 date_from / date_to
        date_from = params.get("date_from")
        date_to = params.get("date_to")
        if date_from and date_to:
            try:
                d1 = datetime.fromisoformat(date_from)
                d2 = datetime.fromisoformat(date_to)
                return (d2 - d1).days / 365.25
            except (ValueError, TypeError):
                pass

        return 0.5  # 默认 0.5 年

    def _estimate_record_count(self, params: dict) -> int:
        """估算记录数"""
        trades = params.get("trades", [])
        pnl_data = params.get("pnl_data", [])
        ic_data = params.get("ic_data", [])
        return max(len(trades), len(pnl_data), len(ic_data))

    def _get_adaptive_thresholds(
        self, method: str, years: float, n_records: int,
    ) -> tuple[int, float]:
        """计算自适应的 C1 和 C5 阈值

        根据策略类型、时间跨度和记录数动态调整。

        Parameters
        ----------
        method : str
            策略方法
        years : float
            回测年数
        n_records : int
            记录数

        Returns
        -------
        tuple[int, float]
            (c1_min_trades, c5_min_density)
        """
        if not self._use_adaptive:
            return (30, 12.0)

        # C1 自适应
        if years < 1.0:
            c1 = max(10, int(30 * years))
        else:
            c1 = 30

        # C5 按策略类型
        method_lower = method.lower()
        if method_lower == "grid":
            c5 = 2.0
        elif method_lower == "trend":
            c5 = 6.0
        elif method_lower == "reversal":
            c5 = 4.0
        elif method_lower == "factor":
            c5 = 250.0 if n_records > 100 else 12.0
        else:
            c5 = 12.0

        return (c1, c5)

    def _get_regime_threshold(self, years: float) -> int:
        """计算自适应的 Q3 最小正收益状态数

        Parameters
        ----------
        years : float
            回测年数

        Returns
        -------
        int
        """
        if not self._use_adaptive:
            return 2
        if years < 1.0:
            return 1
        if years < 3.0:
            return 2
        return 3

    def _check_stale(self, task_id: str) -> None:
        """检查任务是否超时"""
        report = self._tasks.get(task_id)
        if report is None:
            return

        if report.status not in ValidationStatus.active_states():
            return

        try:
            created = datetime.fromisoformat(report.created_at)
            elapsed = (datetime.now(_TZ_CST) - created).total_seconds()
            if elapsed > self._stale_threshold_seconds:
                report.status = ValidationStatus.STALE
                report.error_message = (
                    f"超时 {elapsed:.0f}秒 > 阈值 {self._stale_threshold_seconds}秒"
                )
                self._task_status[task_id] = ValidationStatus.STALE
                self._persist_report(report)
        except (ValueError, TypeError):
            pass

    # ==================== 管理工具 ====================

    def list_tasks(
        self,
        status_filter: Optional[ValidationStatus] = None,
    ) -> list[dict[str, Any]]:
        """列出所有已知任务

        Parameters
        ----------
        status_filter : ValidationStatus | None
            按状态筛选

        Returns
        -------
        list[dict]
        """
        with self._lock:
            results: list[dict[str, Any]] = []
            for tid, report in self._tasks.items():
                if status_filter and report.status != status_filter:
                    continue
                results.append({
                    "task_id": tid,
                    "status": report.status.value,
                    "strategy_id": report.strategy_params.get("strategy_id", "unknown"),
                    "created_at": report.created_at,
                    "completed_at": report.completed_at,
                    "overall_passed": report.overall_passed,
                    "n_fail_reasons": len(report.fail_reasons),
                })
            return sorted(results, key=lambda r: r["created_at"], reverse=True)

    def cleanup_stale(self, max_age_hours: int = 24) -> int:
        """清理过期的已完成任务记录

        Parameters
        ----------
        max_age_hours : int
            保留已完成记录的最大小时数

        Returns
        -------
        int
            清理的任务数
        """
        now = datetime.now(_TZ_CST)
        cutoff = now - timedelta(hours=max_age_hours)
        cleaned = 0

        with self._lock:
            stale_task_ids: list[str] = []
            for tid, report in list(self._tasks.items()):
                if report.status in ValidationStatus.terminal_states():
                    try:
                        completed = datetime.fromisoformat(
                            report.completed_at or report.created_at,
                        )
                        if completed < cutoff:
                            stale_task_ids.append(tid)
                    except (ValueError, TypeError):
                        continue

            for tid in stale_task_ids:
                del self._tasks[tid]
                self._task_status.pop(tid, None)
                # 删除磁盘文件
                fpath = self._results_dir / f"{tid}.json"
                if fpath.exists():
                    fpath.unlink(missing_ok=True)
                cleaned += 1

        return cleaned

    # ==================== Phase 4c 管线增强 ====================

    @staticmethod
    def supports_pipeline(pipeline_name: str) -> bool:
        """检查指定管线名称是否受支持"""
        return pipeline_name in PIPELINE_CONFIG

    @staticmethod
    def list_pipelines() -> dict[str, dict[str, Any]]:
        """列出所有可用管线及其配置"""
        return PIPELINE_CONFIG

    @staticmethod
    def pending_validators() -> dict[str, str]:
        """返回待实现的验证器列表（含工时估算）"""
        return dict(_PENDING_VALIDATORS)

    def get_active_pipeline(self) -> list[str]:
        """获取当前激活的验证器列表"""
        cfg = PIPELINE_CONFIG.get(self._pipeline_name, PIPELINE_CONFIG["default"])
        return list(cfg["validators"])

    @staticmethod
    def compute_q_rating(
        report: ValidationReport,
    ) -> dict[str, Any]:
        """计算 Q 综合评级（Q7 Rating Aggregator 前置版）

        基于 G1/Q3/Q5 验证结果的预设评级规则：
        - PASS all → A
        - G1 PASS, Q3/Q5 mixed → B
        - G1 WARN, rest mixed → C
        - G1 FAIL but Q3/Q5 OK → D
        - G1 FAIL and any Q3/Q5 FAIL → F

        Parameters
        ----------
        report : ValidationReport

        Returns
        -------
        dict
            {"rating": "A"~"F", "bottleneck": str, "bottleneck_validator": str}
        """
        g1_pass = bool(report.existence_result and report.existence_result.exists)
        q3_pass = bool(report.regime_result and report.regime_result.passed)
        q5_pass = bool(report.temporal_result and report.temporal_result.is_stable)

        if g1_pass and q3_pass and q5_pass:
            return {"rating": "A", "bottleneck": "无", "bottleneck_validator": ""}
        if g1_pass and (q3_pass or q5_pass):
            return {"rating": "B", "bottleneck": "Q3 或 Q5 轻度问题", "bottleneck_validator": "Q3" if not q3_pass else "Q5"}
        if report.existence_result and not report.existence_result.exists:
            if q3_pass or q5_pass:
                return {"rating": "C", "bottleneck": "G1 存在性验证", "bottleneck_validator": "G1"}
            return {"rating": "D", "bottleneck": "G1 + Q3/Q5", "bottleneck_validator": "G1"}
        return {"rating": "F", "bottleneck": "至少一个验证器 FAIL", "bottleneck_validator": "G1"}

    def generate_q_report(self, task_id: str) -> dict[str, Any]:
        """生成 Q 层完整评级报告（含评级 + 瓶颈分析 + 改进建议）

        Parameters
        ----------
        task_id : str

        Returns
        -------
        dict
        """
        report = self.get_validation_report(task_id)
        rating_info = self.compute_q_rating(
            ValidationReport(
                task_id=task_id,
                strategy_params=report.get("strategy_params", {}),
                status=ValidationStatus.COMPLETED,
                existence_result=report.get("existence_result", None),
                regime_result=report.get("regime_result", None),
                temporal_result=report.get("temporal_result", None),
                overall_passed=report.get("overall_passed", False),
            )
        )

        return {
            "task_id": task_id,
            "rating": rating_info["rating"],
            "bottleneck": rating_info["bottleneck"],
            "bottleneck_validator": rating_info["bottleneck_validator"],
            "overall_passed": report.get("overall_passed", False),
            "fail_reasons": report.get("fail_reasons", []),
            "gates_triggered": report.get("gates_triggered", []),
            "pipeline": self._pipeline_name,
            "generated_at": datetime.now(_TZ_CST).isoformat(),
        }

    def close(self) -> None:
        """关闭接口，释放资源"""
        self._tasks.clear()
        self._task_status.clear()

    def __enter__(self) -> "Phase4cInterface":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ============================================================
# 使用示例
# ============================================================

# 示例：网格策略验证
_GRID_EXAMPLE = {
    "strategy_id": "grid_601857_n5_fixed",
    "method": "grid",
    "symbol": "601857",
    "trades": [
        {"date": "2026-01-22", "pnl_pct": -0.001, "regime": "TREND_UP"},
        {"date": "2026-03-04", "pnl_pct": 0.055, "regime": "TREND_UP"},
    ],
    "market_regime": "TREND_UP",
    "backtest_days": 84,
    "params": {
        "n_levels": 5,
        "grid_type": "arithmetic",
        "cooldown_bars": 1,
        "position_mode": "fixed",
        "stop_loss": 0.0,
    },
}

# 示例：因子策略验证
_FACTOR_EXAMPLE = {
    "strategy_id": "factor_5factor_601857",
    "method": "factor",
    "symbol": "601857",
    "ic_data": [
        {"date": "2020-01-02", "ic": 0.032},
        {"date": "2020-01-03", "ic": -0.015},
    ],
    "perf_by_regime": {
        "TREND_UP": 5.2,
        "TREND_DOWN": -1.3,
        "SIDEWAYS": 3.8,
    },
    "backtest_days": 1540,
    "params": {
        "factors": ["TrendQuality", "VWAP_dev", "Volume_ratio", "ATR_ratio", "OBV_change"],
    },
}


def demo() -> None:
    """演示 Phase 4c 接口的典型使用流程"""
    import sys
    pipeline = "full" if "--pipeline" in sys.argv else "default"
    interface = Phase4cInterface(
        auto_run=True,
        use_adaptive_thresholds=True,
        pipeline_name=pipeline,
    )

    print(f"=" * 60)
    print(f"Phase 4c 验证管线演示")
    print(f"管线段: {pipeline} — {', '.join(interface.get_active_pipeline())}")
    print(f"可用管线: {', '.join(interface.list_pipelines().keys())}")
    print(f"=" * 60)

    # 1. 提交网格策略
    print("\n📤 提交网格策略...")
    grid_task_id = interface.submit_for_validation(_GRID_EXAMPLE)
    print(f"  task_id: {grid_task_id}")

    # 2. 查询状态
    status = interface.get_validation_status(grid_task_id)
    print(f"  状态: {status.value}")

    # 3. 获取报告 + Q 评级
    if status == ValidationStatus.COMPLETED:
        report = interface.get_validation_report(grid_task_id)
        q_rating = interface.compute_q_rating(
            ValidationReport(
                task_id=grid_task_id,
                strategy_params=report.get("strategy_params", {}),
                status=ValidationStatus.COMPLETED,
                existence_result=report.get("existence_result", None),
                regime_result=report.get("regime_result", None),
                temporal_result=report.get("temporal_result", None),
                overall_passed=report.get("overall_passed", False),
            )
        )
        print(f"\n📊 验证结果:")
        print(f"  综合通过: {'✅' if report['overall_passed'] else '❌'} {report['overall_passed']}")
        print(f"  Q 评级: {q_rating['rating']}")
        print(f"  瓶颈: {q_rating['bottleneck']}")
        if report["fail_reasons"]:
            print(f"  失败原因:")
            for r in report["fail_reasons"]:
                print(f"    - {r}")

    # 4. 批量提交
    print("\n📦 批量提交网格 + 因子策略...")
    task_ids = interface.submit_batch([_GRID_EXAMPLE, _FACTOR_EXAMPLE])
    print(f"  提交 {len(task_ids)} 个任务")

    # 5. 列出所有任务
    tasks = interface.list_tasks()
    print(f"\n📋 任务列表 ({len(tasks)} 个):")
    for t in tasks[:5]:
        print(f"  {t['task_id'][:12]}... | {t['status']:<12} | {t['strategy_id']:<25} | PASS={t['overall_passed']}")

    # 6. 待实现验证器
    pending = interface.pending_validators()
    print(f"\n⏳ 待实现验证器:")
    for vname, vdesc in pending.items():
        print(f"  {vname}: {vdesc}")

    interface.close()
    print(f"\n{'=' * 60}")
    print("✅ 管线演示完成")


def run_pipeline_cli() -> None:
    """CLI 入口：直接运行验证管线并输出 JSON 报告"""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Phase 4c 验证管线 CLI",
    )
    parser.add_argument("--pipeline", choices=list(PIPELINE_CONFIG.keys()), default="default",
                        help="验证管线名称")
    parser.add_argument("--params", required=True,
                        help="策略参数 JSON 文件路径")
    parser.add_argument("--output", default="",
                        help="输出报告 JSON 路径")
    parser.add_argument("--list-pipelines", action="store_true",
                        help="列出可用管线")

    args = parser.parse_args()

    if args.list_pipelines:
        print("可用管线:")
        for name, cfg in PIPELINE_CONFIG.items():
            print(f"  {name:<12} {cfg['validators']}  — {cfg['description']}")
        pending = _PENDING_VALIDATORS
        if pending:
            print(f"\n待实现验证器:")
            for vname, vdesc in pending.items():
                print(f"  {vname}: {vdesc}")
        return

    # 读取策略参数
    params_path = Path(args.params)
    if not params_path.exists():
        print(f"❌ 参数文件不存在: {params_path}")
        sys.exit(1)

    try:
        strategy_params = json.loads(params_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"❌ JSON 解析失败: {exc}")
        sys.exit(1)

    # 运行验证
    interface = Phase4cInterface(
        auto_run=True,
        use_adaptive_thresholds=True,
        pipeline_name=args.pipeline,
    )

    try:
        task_id = interface.submit_for_validation(strategy_params)
        report = interface.get_validation_report(task_id)
        q_rating = interface.generate_q_report(task_id)

        output = {
            "task_id": task_id,
            "pipeline": args.pipeline,
            "validation_report": report,
            "q_rating": q_rating,
        }

        output_path = args.output or f"{task_id}_report.json"
        Path(output_path).write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ 验证完成")
        print(f"   Q 评级: {q_rating['rating']}")
        print(f"   综合通过: {report['overall_passed']}")
        print(f"   报告: {output_path}")

    except Exception as exc:
        print(f"❌ 验证失败: {exc}")
        sys.exit(1)
    finally:
        interface.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "--demo":
            demo()
        elif sys.argv[1] == "--pipeline" or sys.argv[1] == "run":
            run_pipeline_cli()
        else:
            print("Phase 4c Interface")
            print("  --demo       运行演示")
            print("  run --help    CLI 管道模式")
    else:
        print("Phase 4c Interface — 使用 --demo 运行演示 或 run --help 查看管道模式")
