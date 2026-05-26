# -*- coding: utf-8 -*-
"""
test_phase1_integration.py — Phase 1 集成测试

测试从 Q3 Regime Validator → Q8 Attribution → G1 Gate → Q9a 的完整链路。
覆盖以下场景：

Test 1: 策略在 84天/2笔交易 窗口上 FAIL Q1 → G1 拦截 → 写入 Q9a
Test 2: 策略在多 regime 下分散 → PASS Q3 → 正常通过
Test 3: G3 三方会签完整流程一次

运行方式:
    python -m pytest scripts/test_phase1_integration.py -v
    或
    python scripts/test_phase1_integration.py

作者：墨衡 (moheng)
创建时间：2026-05-19 16:31 GMT+8
"""

import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── 确保 src 在 path 中 ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

_TZ_CST = timezone(timedelta(hours=8), "CST")

# ── 模块导入 ──
from utils.existence_validator import (
    validate_existence, TradeRecord, ExistenceResult,
)
from utils.q3_regime_validator import (
    validate_regime_consistency, RegimeTradeRecord,
    aggregate_by_regime, RegimeValidationResult,
)
from utils.q5_temporal_validator import (
    validate_temporal_stability, TemporalStabilityResult,
)
from utils.q8_failure_attribution import (
    FailureAttributionEngine, FailureAttributionReport,
)
from utils.q9a_failure_registry import Q9aFailureRegistry
from utils.q_failures_db import (
    QFailuresDB, QFailureRecord, FailureType,
)
from utils.gate_integration import (
    GateToQ9aIntegration,
)


# ============================================================
# 测试工具
# ============================================================

class IntegrationTestResult:
    """单条集成测试结果"""
    def __init__(self, name: str):
        self.name = name
        self.passed: bool = False
        self.errors: list[str] = []
        self.duration_ms: float = 0.0
        self._start: Optional[float] = None

    def start(self) -> None:
        self._start = time.perf_counter()

    def stop(self) -> None:
        if self._start is not None:
            self.duration_ms = (time.perf_counter() - self._start) * 1000

    def fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def assert_eq(self, actual, expected, label: str) -> None:
        if actual != expected:
            self.fail(f"{label}: 期望 {expected!r}, 实际 {actual!r}")

    def assert_true(self, cond: bool, label: str) -> None:
        if not cond:
            self.fail(f"{label}: 条件不成立")

    def summary(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        errs = "; ".join(self.errors) if self.errors else ""
        return f"  {status} | {self.name} ({self.duration_ms:.0f}ms) {errs}"


def run_test(name: str, fn, *args, **kwargs) -> IntegrationTestResult:
    """运行单个测试"""
    result = IntegrationTestResult(name)
    result.start()
    try:
        fn(result, *args, **kwargs)
    except Exception as e:
        result.fail(f"异常: {type(e).__name__}: {e}")
    result.stop()
    return result


# ============================================================
# 临时数据库上下文管理器
# ============================================================

class TempQ9aDB:
    """临时 Q9a 数据库（使用内存 SQLite）"""

    def __init__(self):
        self.db_path: Optional[str] = None
        self._tmpfile: Optional[str] = None

    def __enter__(self):
        # 创建临时文件数据库
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._tmpfile = tmp.name
        self.db_path = self._tmpfile
        return self

    def __exit__(self, *args):
        if self._tmpfile and os.path.exists(self._tmpfile):
            try:
                os.unlink(self._tmpfile)
            except PermissionError:
                pass

    def create_gate(self) -> GateToQ9aIntegration:
        return GateToQ9aIntegration(self.db_path)

    def create_registry(self) -> Q9aFailureRegistry:
        return Q9aFailureRegistry(self.db_path)

    def create_db(self) -> QFailuresDB:
        return QFailuresDB(self.db_path)


# ============================================================
# Test 1: FAIL Q1 → G1 拦截 → 写入 Q9a
# ============================================================

def test_1_fail_q1_to_g1_to_q9a(result: IntegrationTestResult):
    """
    场景：策略在 84 天内只有 2 笔交易 → FAIL Q1 ExistenceValidator
    → G1 Gate 拦截 → 自动写入 Q9a Q_FAILURES
    """
    base_date = datetime(2026, 3, 1, tzinfo=_TZ_CST)

    # ── 构造 2 笔交易（84 天内） ──
    trades = [
        TradeRecord(
            date=base_date,
            pnl_pct=2.5,
            regime="TREND_UP",
        ),
        TradeRecord(
            date=base_date + timedelta(days=83),
            pnl_pct=-1.0,
            regime="TREND_UP",
        ),
    ]

    # Step A: 执行 Q1 ExistenceValidator → 期望 FAIL
    q1_result = validate_existence(
        trades,
        c1_min_trades=30,
        c2_min_regimes=2,
        c3_min_years=2.0,
        c4_max_share=0.40,
        c5_min_density=12.0,
        c6_max_fraction=0.50,
    )

    result.assert_eq(q1_result.exists, False, "Q1 应返回 exists=False")
    result.assert_true(len(q1_result.fail_reasons) >= 1, "Q1 应有失败原因")
    result.assert_true(q1_result.confidence < 0.8, "Q1 置信度应较低")

    # 记录失败原因，后面验证 G1 写入 Q9a 时用到
    fail_reasons = q1_result.fail_reasons.copy()

    # Step B: G1 Gate 拦截 → 通过 GateToQ9aIntegration 写入 Q9a
    with TempQ9aDB() as tmp_db:
        gate = tmp_db.create_gate()

        # G1 拦截
        fid_1, cause = GateToQ9aIntegration.from_existence_result(
            strategy_id="test_grid_fail_84d_2trades",
            fail_reasons=fail_reasons,
            parameter_set={"window": "84d", "min_trades": 30},
            regime="TREND_UP",
            run_id="test_run_001",
            report_id="test_report_001",
            confidence_before=q1_result.confidence,
        )
        result.assert_true(len(fid_1) > 0, "G1 应返回 failure_id")

        # Step C: 验证 Q9a 已写入
        q9a_db = tmp_db.create_db()
        records = q9a_db.query(
            strategy_id="test_grid_fail_84d_2trades",
        )
        result.assert_eq(len(records), 1, "Q9a 应包含 1 条记录")

        record = records[0]
        result.assert_eq(record.failure_type, FailureType.STATISTICAL_NOISE,
                         "failure_type 应为 STATISTICAL_NOISE")
        result.assert_eq(record.discovered_by, "Q1",
                         "discovered_by 应为 Q1")
        result.assert_eq(record.strategy_id, "test_grid_fail_84d_2trades",
                         "strategy_id 应匹配")
        result.assert_true("C1" in record.cause,
                           "cause 应包含 C1 原因（最小交易数不足）")

        gate.close()
        q9a_db.close()

    result.passed = len(result.errors) == 0


# ============================================================
# Test 2: 多 regime 分散 → PASS Q3 → 正常通过
# ============================================================

def test_2_multi_regime_pass_q3(result: IntegrationTestResult):
    """
    场景：策略在多个 regime (4个) 下均有正收益 → PASS Q3 → 正常通过
    G3 会签不拦截
    """
    base_date = datetime(2024, 1, 1, tzinfo=_TZ_CST)

    # ── 构造 50 笔交易，分布在 4 个 regime 下（全部正收益） ──
    regimes = ["TREND_UP", "SIDEWAYS", "HIGH_VOL", "LOW_VOL"]
    records: list[RegimeTradeRecord] = []

    for i in range(50):
        regime = regimes[i % 4]
        pnl = 1.0 + (i % 10) * 0.5  # 全部正收益
        records.append(RegimeTradeRecord(
            date=(base_date + timedelta(days=i * 7)),
            pnl_pct=pnl,
            regime=regime,
        ))

    # Step A: 执行 Q3 Regime Validator → 期望 PASS
    q3_result = validate_regime_consistency(
        records,
        min_positive_regimes=2,
    )

    result.assert_eq(q3_result.passed, True, "Q3 应返回 passed=True")
    result.assert_true(q3_result.positive_regime_count >= 2,
                       f"正收益 regime 数应 ≥ 2 (实际 {q3_result.positive_regime_count})")
    result.assert_true(q3_result.regime_aggregation.regime_diversity > 0.5,
                       "regime 多样性应 > 0.5")

    # Step B: 验证聚合分布正确
    aggregation = q3_result.regime_aggregation
    result.assert_true(len(aggregation.snapshots) >= 3,
                       "应至少覆盖 3 个 regime")

    # Step C: 验证 G3 不拦截（模拟会签场景）
    with TempQ9aDB() as tmp_db:
        gate = tmp_db.create_gate()

        # Q3 通过了 → G3 不会触发写入
        q9a_db = tmp_db.create_db()
        q_records = q9a_db.query(strategy_id="test_multi_regime_pass")
        result.assert_eq(len(q_records), 0,
                         "Q3 PASS 后 Q9a 应无记录")

        # 模拟 G3 会签通过（不调用 record_g3_failure）
        gate.close()
        q9a_db.close()

    result.passed = len(result.errors) == 0


# ============================================================
# Test 3: G3 三方会签完整流程
# ============================================================

def test_3_g3_triple_sign_flow(result: IntegrationTestResult):
    """
    场景：G3 三方会签完整流程
    1. 策略通过 G1+G2 → 进入 G3
    2. G3 三方会签：假设备份否决 (墨萱/Owner 任一否决)
    3. G3 FAIL → 自动写入 Q9a (HUMAN_REJECTED)
    """
    base_date = datetime(2024, 6, 1, tzinfo=_TZ_CST)
    strategy_id = "test_g3_triple_sign"
    run_id = f"test_g3_{uuid.uuid4().hex[:8]}"

    # Step A: 构造一个技术上通过 G1+G2 但会被人工否决的策略
    trades = [
        TradeRecord(date=base_date + timedelta(days=i * 12),
                    pnl_pct=1.0 + (i % 5) * 0.3,
                    regime=["TREND_UP", "SIDEWAYS", "HIGH_VOL"][i % 3])
        for i in range(35)
    ]

    q1_result = validate_existence(trades)
    result.assert_eq(q1_result.exists, True,
                     "G1 应通过（35 笔交易 ≥ 30）")

    # Step B: 模拟 G3 三方会签流程
    # 会签角色：墨涵 (MiniMax) + 墨萱 (Claude) + Owner
    signatories = [
        {"name": "mohan", "role": "research_review", "approved": True,
         "comment": "策略逻辑完整"},
        {"name": "moxuan", "role": "technical_review", "approved": False,
         "comment": "参数稳定性存疑：最优参数孤立 (PlateauScore=0.25)"},
        {"name": "owner", "role": "final_approval", "approved": False,
         "comment": "同意墨萱意见，不可放行"},
    ]

    # 会签逻辑：任一否决 = 整体否决
    all_approved = all(s["approved"] for s in signatories)
    result.assert_eq(all_approved, False, "G3 会签应整体否决")

    # Step C: G3 否决 → GateToQ9aIntegration 写入 Q9a
    with TempQ9aDB() as tmp_db:
        gate = tmp_db.create_gate()

        # G3 否决
        fid = gate.record_g3_failure(
            strategy_id=strategy_id,
            cause="G3 三方会签否决：墨萱参数稳定性存疑 + Owner 确认",
            parameter_set={"signatories": signatories},
            regime="TREND_UP",
            run_id=run_id,
            report_id=f"report_{run_id}",
            confidence_before=q1_result.confidence,
            human_notes="会签记录：墨涵通过，墨萱否决（PlateauScore=0.25），Owner否决",
        )
        result.assert_true(len(fid) > 0, "G3 失败应返回 failure_id")

        # Step D: 验证 Q9a 记录
        q9a_db = tmp_db.create_db()
        records = q9a_db.query(strategy_id=strategy_id)
        result.assert_eq(len(records), 1, "Q9a 应有 1 条 G3 失败记录")

        record = records[0]
        result.assert_eq(record.failure_type, FailureType.HUMAN_REJECTED,
                         "failure_type 应为 HUMAN_REJECTED")
        result.assert_eq(record.discovered_by, "G3",
                         "discovered_by 应为 G3")

        # Step E: 验证 Q8 归因引擎能定位该记录
        attribution = FailureAttributionEngine(str(tmp_db.db_path))
        summary = attribution.strategy_summary(strategy_id)
        result.assert_true(summary is not None, "Q8 应能查询到策略失败画像")
        if summary:
            result.assert_eq(summary.total_failures, 1,
                             "策略失败画像应有 1 条记录")
            result.assert_eq(summary.gate_failures, 1,
                             "G3 fail 应算作 gate_failures")
            result.assert_eq(summary.recurrence_count, 0,
                             "单次失败不应标记为复发")
            result.assert_true("HUMAN_REJECTED" in summary.failure_types,
                               "失败类型应包含 HUMAN_REJECTED")

        # Step F: 全库报告验证
        report = attribution.generate_report()
        result.assert_eq(report.total_records, 1,
                         "全库报告应统计到 1 条记录")
        result.assert_true(len(report.strategy_summaries) >= 1,
                           "报告应包含策略画像")

        attribution.close()
        gate.close()
        q9a_db.close()

    result.passed = len(result.errors) == 0


# ============================================================
# 主入口
# ============================================================

def main():
    print("=" * 70)
    print("Phase 1 集成测试 — Q3 → Q8 → G1/G3 → Q9a 完整链路")
    print("=" * 70)
    print()

    tests = [
        ("Test 1: FAIL Q1 → G1拦截 → 写入Q9a (84天/2笔交易)",
         test_1_fail_q1_to_g1_to_q9a),
        ("Test 2: 多regime分散 → PASS Q3 → 正常通过 (4 regime 全部正收益)",
         test_2_multi_regime_pass_q3),
        ("Test 3: G3三方会签完整流程 (墨萱否决 → 写入Q9a HUMAN_REJECTED)",
         test_3_g3_triple_sign_flow),
    ]

    all_results: list[IntegrationTestResult] = []

    for name, fn in tests:
        print(f"▶ {name}")
        result = run_test(name, fn)
        all_results.append(result)
        print(result.summary())
        print()

    # ── 汇总 ──
    passed = sum(1 for r in all_results if r.passed)
    total = len(all_results)
    print("=" * 70)
    print(f"结果: {passed}/{total} 通过 ({passed/total*100:.0f}%)")
    print("=" * 70)

    for r in all_results:
        if not r.passed:
            print(f"\n❌ {r.name}:")
            for e in r.errors:
                print(f"   • {e}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
