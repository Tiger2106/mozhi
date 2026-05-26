# -*- coding: utf-8 -*-
"""
test_phase1_integration.py — Phase 1 集成测试

测试链路：
  ① Q3 Regime Validator 基本验证
  ② Q3 Regime Validator → 未通过场景
  ③ ExistenceValidator FAIL → QualityGates G1 → Q9a Q_FAILURES 记录
  ④ QualityGates G1 PASS → knowledge.db 研究记录
  ⑤ Q8 Failure Attribution Engine 归因分析
  ⑥ Q9b RESEARCH_FAILURES 写入/查询
  ⑦ Q9b ↔ Q9a 交叉引用查询

作者：墨衡 (moheng)
创建时间：2026-05-19 16:28 GMT+8
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TZ_CST = timezone(timedelta(hours=8), "CST")

# ─── 确保能导入 src/utils/ ───
_HERE = Path(__file__).resolve().parent
_SRC_UTILS = _HERE / "src" / "utils"
_RESEARCH_FAILURES = _HERE / "research_failures"
if str(_SRC_UTILS) not in sys.path:
    sys.path.insert(0, str(_SRC_UTILS))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_RESEARCH_FAILURES) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_FAILURES))

# ─── 单元被测试模块 ───
from q3_regime_validator import (
    RegimeTradeRecord,
    validate_regime_consistency,
    validate_from_perf_slices,
    map_regime_name,
    RegimeName,
    RegimePerfSnapshot,
    RegimePerfAggregation,
)
from q8_failure_attribution import FailureAttributionEngine
from q_failures_db import QFailuresDB, FailureType, QFailureRecord
from q9a_failure_registry import Q9aFailureRegistry
from gate_integration import GateToQ9aIntegration
from existence_validator import ExistenceValidator
from q9b_research_failures import (
    ResearchFailuresDB,
    ResearchFailureRecord,
    ResearchFailureType,
    FailureSeverity,
    create_research_record,
)


# ============================================================
# ——— Test Q3: Regime Validator ———
# ============================================================

class TestQ3RegimeValidator(unittest.TestCase):
    """Q3 Regime Validator: 市场状态验证"""

    def setUp(self) -> None:
        self.now = datetime.now(_TZ_CST)

    def test_single_regime_only_fails(self) -> None:
        """仅一个状态有正收益 → FAIL"""
        records = [
            RegimeTradeRecord(self.now, 5.0, "UPTREND"),
            RegimeTradeRecord(self.now + timedelta(days=1), 3.0, "UPTREND"),
            RegimeTradeRecord(self.now + timedelta(days=2), -1.0, "DOWNTREND"),
            RegimeTradeRecord(self.now + timedelta(days=3), -2.0, "RANGE"),
        ]
        result = validate_regime_consistency(records, min_positive_regimes=2)
        self.assertFalse(result.passed, "单状态正收益应未通过")
        self.assertEqual(result.positive_regime_count, 1)

    def test_dual_regime_passes(self) -> None:
        """两个状态有正收益 → PASS"""
        records = [
            RegimeTradeRecord(self.now, 2.0, "UPTREND"),
            RegimeTradeRecord(self.now + timedelta(days=1), 3.0, "UPTREND"),
            RegimeTradeRecord(self.now + timedelta(days=2), 4.0, "RANGE"),
            RegimeTradeRecord(self.now + timedelta(days=3), 1.5, "RANGE"),
        ]
        result = validate_regime_consistency(records, min_positive_regimes=2)
        self.assertTrue(result.passed, "双状态正收益应通过")
        self.assertGreaterEqual(result.positive_regime_count, 2)

    def test_mixed_results(self) -> None:
        """混合收益（部分正部分负）→ 通过条件正确"""
        records = [
            RegimeTradeRecord(self.now, 5.0, "UPTREND"),
            RegimeTradeRecord(self.now + timedelta(days=1), -3.0, "DOWNTREND"),
            RegimeTradeRecord(self.now + timedelta(days=2), 2.0, "RANGE"),
            RegimeTradeRecord(self.now + timedelta(days=3), 1.0, "HIGH_VOL"),
        ]
        result = validate_regime_consistency(records, min_positive_regimes=3)
        # UPTREND, RANGE, HIGH_VOL → 3 positive
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.positive_regime_count, 3)

    def test_from_perf_slices(self) -> None:
        """预聚合数据接口"""
        perf = {"UPTREND": 5.2, "DOWNTREND": -1.3, "RANGE": 3.8}
        result = validate_from_perf_slices(perf)
        self.assertTrue(result.passed)
        self.assertEqual(result.positive_regime_count, 2)

    def test_empty_records(self) -> None:
        """空数据 → FAIL"""
        result = validate_regime_consistency([])
        self.assertFalse(result.passed)
        self.assertIn("无交易记录", result.fail_reason)

    def test_regime_name_mapping(self) -> None:
        """名称映射正确性"""
        self.assertEqual(map_regime_name("UPTREND"), "TREND_UP")
        self.assertEqual(map_regime_name("DOWNTREND"), "TREND_DOWN")
        self.assertEqual(map_regime_name("RANGE"), "SIDEWAYS")
        self.assertEqual(map_regime_name("BREAKOUT"), "HIGH_VOL")
        self.assertEqual(map_regime_name("CLIMAX"), "HIGH_VOL")
        self.assertEqual(map_regime_name("SIDEWAYS"), "SIDEWAYS")
        self.assertEqual(map_regime_name("TREND_UP"), "TREND_UP")
        self.assertEqual(map_regime_name("UNKNOWN_STATE"), "UNKNOWN")

    def test_regime_name_enum(self) -> None:
        """RegimeName 枚举"""
        self.assertEqual(RegimeName.TREND_UP.value, "TREND_UP")
        self.assertEqual(RegimeName.HIGH_VOL.value, "HIGH_VOL")
        self.assertEqual(RegimeName.UNKNOWN.value, "UNKNOWN")

    def test_integration_trade_only_interface(self) -> None:
        """dict 格式接口"""
        trades = [
            {"date": self.now, "pnl_pct": 3.0, "regime": "UPTREND"},
            {"date": self.now + timedelta(days=1), "pnl_pct": -1.0, "regime": "DOWNTREND"},
            {"date": self.now + timedelta(days=2), "pnl_pct": 2.5, "regime": "SIDEWAYS"},
        ]
        from q3_regime_validator import validate_regime_trades_only
        result = validate_regime_trades_only(trades)
        self.assertTrue(result.passed)

    def test_aggregation_snapshot(self) -> None:
        """聚合快照字段完整性"""
        records = [
            RegimeTradeRecord(self.now, 5.0, "UPTREND"),
            RegimeTradeRecord(self.now + timedelta(days=1), 3.0, "RANGE"),
        ]
        from q3_regime_validator import aggregate_by_regime
        agg = aggregate_by_regime(records)
        self.assertIsInstance(agg, RegimePerfAggregation)
        self.assertEqual(len(agg.snapshots), 2)
        for snap in agg.snapshots:
            self.assertIsInstance(snap, RegimePerfSnapshot)
            self.assertIn(snap.regime, ("TREND_UP", "SIDEWAYS"))
            self.assertGreater(snap.n_trades, 0)

    def test_concentration_warning(self) -> None:
        """过度集中（单状态贡献 >90%）→ FAIL"""
        records = [
            RegimeTradeRecord(self.now, 100.0, "UPTREND"),
            RegimeTradeRecord(self.now + timedelta(days=1), -0.5, "DOWNTREND"),
            RegimeTradeRecord(self.now + timedelta(days=2), 0.3, "RANGE"),
        ]
        result = validate_regime_consistency(records, max_dominant_share=80.0)
        # UPTREND contribution ~99.7% >> 80%
        self.assertFalse(result.passed, "过度集中应未通过")


# ============================================================
# ——— Test G1+G2: Quality Gates ———
# ============================================================

class TestQualityGates(unittest.TestCase):
    """G1 ExistenceValidator + G2 Robustness → Q9a 链路"""

    def setUp(self) -> None:
        # 使用临时目录存储 Q9a DB
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_q9a.db"
        self.q9a_db = QFailuresDB(self.db_path)
        self.q9a_db.initialize()

        # 创建 GateToQ9aIntegration (注入自定义 db_path)
        self.gate_integration = GateToQ9aIntegration(self.db_path)
        self.existence_validator = ExistenceValidator()

    def tearDown(self) -> None:
        self.q9a_db.close()
        self.gate_integration.close()
        # cleanup
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _count_q9a_records(self) -> int:
        """统计 Q9a 记录数"""
        return len(self.q9a_db.query(limit=10000))

    def _make_existence_fail(self) -> "ExistenceResult":
        """构造一个 ExistenceValidator FAIL 结果"""
        from existence_validator import ExistenceResult
        return ExistenceResult(
            exists=False,
            confidence=0.15,
            evidence={"sharpe": 0.8, "win_rate": 0.52},
            fail_reasons=["统计显著性不足（p-value > 0.05）"],
            details={"n_trades": 15},
        )

    def test_g1_fail_writes_q9a(self) -> None:
        """G1 FAIL → Q9a 记录增加"""
        from quality_gates import QualityGates
        gates = QualityGates(db_path=self.db_path)

        fail_result = self._make_existence_fail()
        gate_result = gates.run_g1(
            strategy_id="TEST_STRATEGY_G1_FAIL",
            existence_result=fail_result,
            regime="SIDEWAYS",
        )
        gates.close()

        self.assertFalse(gate_result.passed)
        self.assertTrue(gate_result.recorded)
        self.assertIsNotNone(gate_result.failure_id)

        # Q9a 应该有记录
        records = self.q9a_db.query(strategy_id="TEST_STRATEGY_G1_FAIL")
        self.assertGreaterEqual(len(records), 1)

    def test_g1_pass_writes_knowledge(self) -> None:
        """G1 PASS → knowledge.db 记录"""
        from quality_gates import QualityGates, KNOWLEDGE_DB_DIR
        from existence_validator import ExistenceResult

        gates = QualityGates(db_path=self.db_path)

        pass_result = ExistenceResult(
            exists=True,
            confidence=0.85,
            evidence={"sharpe": 2.1, "win_rate": 0.62},
            fail_reasons=[],
            details={"n_trades": 100, "expected_return": 0.025},
        )
        gate_result = gates.run_g1(
            strategy_id="TEST_STRATEGY_G1_PASS",
            existence_result=pass_result,
        )
        gates.close()

        self.assertTrue(gate_result.passed)
        self.assertFalse(gate_result.recorded)  # Q9a 不记录
        self.assertIn("knowledge_record_id", gate_result.details)

    def test_g2_fail_writes_q9a(self) -> None:
        """G2 FAIL → Q9a 记录增加"""
        from quality_gates import QualityGates

        gates = QualityGates(db_path=self.db_path)
        gate_result = gates.run_g2(
            strategy_id="TEST_STRATEGY_G2_FAIL",
            robustness_score=0.15,
            robustness_threshold=0.30,
            regime="TREND_UP",
        )
        gates.close()

        self.assertFalse(gate_result.passed)
        self.assertTrue(gate_result.recorded)
        self.assertIsNotNone(gate_result.failure_id)

        records = self.q9a_db.query(strategy_id="TEST_STRATEGY_G2_FAIL")
        self.assertGreaterEqual(len(records), 1)

    def test_g2_pass_note_records(self) -> None:
        """G2 PASS → Q9a 不记录（无失败）"""
        from quality_gates import QualityGates

        gates = QualityGates(db_path=self.db_path)

        # 预先记录数
        before = self._count_q9a_records()

        gate_result = gates.run_g2(
            strategy_id="TEST_STRATEGY_G2_PASS",
            robustness_score=0.85,
            robustness_threshold=0.30,
        )
        gates.close()

        self.assertTrue(gate_result.passed)
        # G2 PASS 时默认不写入 Q9a（因为 write_to_q9a=True 但只有 FAIL 时写）
        self.assertIn("PASS", gate_result.details.get("action", ""))

    def test_full_pipeline_g1_fail_to_q9a(self) -> None:
        """完整链路：ExistenceValidator FAIL → G1 → Q9a Q_FAILURES"""
        from quality_gates import QualityGates

        # 1. ExistenceValidator 判断（模拟失败）
        fail_result = self._make_existence_fail()

        # 2. G1 门控
        gates = QualityGates(db_path=self.db_path)
        gate_result = gates.run_g1(
            strategy_id="TEST_FULL_PIPELINE",
            existence_result=fail_result,
            regime="SIDEWAYS",
        )
        gates.close()

        # 3. 验证：G1 FAIL + Q9a 已写
        self.assertFalse(gate_result.passed)
        self.assertTrue(gate_result.recorded)
        self.assertIsNotNone(gate_result.failure_id)

        # 4. 从 Q9a 读取
        records = self.q9a_db.query(strategy_id="TEST_FULL_PIPELINE")
        self.assertGreaterEqual(len(records), 1)
        first = records[0]
        self.assertEqual(first.failure_type, FailureType.STATISTICAL_NOISE)


# ============================================================
# ——— Test Q8: Failure Attribution ———
# ============================================================

class TestQ8FailureAttribution(unittest.TestCase):
    """Q8 失败归因引擎"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_q8.db"

        # 初始化 Q9a 并插入一些测试数据
        self.q9a_db = QFailuresDB(self.db_path)
        self.q9a_db.initialize()

        # 注入数据：多个策略的多种失败类型，部分复发
        self._seed_data()

    def _seed_data(self) -> None:
        """插入测试数据"""
        now = datetime.now(_TZ_CST)
        records = [
            QFailureRecord(
                failure_id=f"f{i:04d}",
                strategy_id=sid,
                failure_type=ft,
                discovered_by=dby,
                timestamp=(now - timedelta(days=d)).isoformat(),
                parameter_set={},
                cause=cause,
            )
            for sid, ft, dby, d, cause in [
                # 策略A: 3次 STATISTICAL_NOISE → 应发现复发
                ("STRAT_A", FailureType.STATISTICAL_NOISE, "G1", 30, "噪声A"),
                ("STRAT_A", FailureType.STATISTICAL_NOISE, "G1", 20, "噪声B"),
                ("STRAT_A", FailureType.STATISTICAL_NOISE, "G1", 5, "噪声C"),
                # 策略A: 1次 PARAMETER_PEAK
                ("STRAT_A", FailureType.PARAMETER_PEAK, "G2", 10, "参数峰"),
                # 策略B: 2次 REGIME_BOUNDED → 应发现复发
                ("STRAT_B", FailureType.REGIME_BOUNDED, "Q3", 15, "单状态"),
                ("STRAT_B", FailureType.REGIME_BOUNDED, "Q3", 7, "集中"),
                # 策略C: 1次 LOW_CONFIDENCE
                ("STRAT_C", FailureType.LOW_CONFIDENCE, "C2", 3, "低置信"),
                # 策略D: 2次 OOS_FAILURE → 应发现复发
                ("STRAT_D", FailureType.OOS_FAILURE, "Q5", 25, "OOS"),
                ("STRAT_D", FailureType.OOS_FAILURE, "Q5", 12, "再测"),
            ]
        ]

        for r in records:
            self.q9a_db.insert(r)
        self.q9a_db.close()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_distribution_counts(self) -> None:
        """归因引擎：分布统计"""
        engine = FailureAttributionEngine(self.db_path)
        dist = engine.compute_distribution()
        engine.close()

        self.assertEqual(dist.total_records, 9)
        self.assertEqual(dist.by_type.get("STATISTICAL_NOISE"), 3)
        self.assertEqual(dist.by_type.get("REGIME_BOUNDED"), 2)
        self.assertEqual(dist.by_type.get("OOS_FAILURE"), 2)

    def test_recurrence_detection(self) -> None:
        """归因引擎：复发检测"""
        engine = FailureAttributionEngine(self.db_path)
        patterns = engine.detect_recurrence(min_occurrences=2)
        engine.close()

        self.assertGreaterEqual(len(patterns), 1)

        # STRAT_A + STATISTICAL_NOISE → 复发 pattern
        strat_a_patterns = [p for p in patterns if p.strategy_id == "STRAT_A"]
        self.assertGreaterEqual(len(strat_a_patterns), 1)
        self.assertEqual(strat_a_patterns[0].failure_type, "STATISTICAL_NOISE")
        self.assertEqual(strat_a_patterns[0].recurrence_count, 3)

        # STRAT_B + REGIME_BOUNDED
        strat_b_patterns = [p for p in patterns if p.strategy_id == "STRAT_B"]
        self.assertGreaterEqual(len(strat_b_patterns), 1)
        self.assertEqual(strat_b_patterns[0].failure_type, "REGIME_BOUNDED")
        self.assertEqual(strat_b_patterns[0].recurrence_count, 2)

    def test_strategy_summary(self) -> None:
        """归因引擎：单策略画像"""
        engine = FailureAttributionEngine(self.db_path)
        summary = engine.strategy_summary("STRAT_A")
        engine.close()

        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_failures, 4)
        self.assertIn("STATISTICAL_NOISE", summary.failure_types)
        self.assertIn("PARAMETER_PEAK", summary.failure_types)
        # STRAT_A 有 3 次 STATISTICAL_NOISE ≥ 2 → 复发
        self.assertIn("STATISTICAL_NOISE", summary.recurrence_types)

    def test_full_report(self) -> None:
        """归因引擎：完整报告生成"""
        engine = FailureAttributionEngine(self.db_path)
        report = engine.generate_report()
        engine.close()

        self.assertTrue(report.total_records > 0)
        self.assertGreaterEqual(len(report.recurrence_patterns), 1)
        self.assertGreaterEqual(len(report.strategy_summaries), 1)


# ============================================================
# ——— Test Q9b: RESEARCH_FAILURES ———
# ============================================================

class TestQ9bResearchFailures(unittest.TestCase):
    """Q9b RESEARCH_FAILURES 写入/查询/交叉引用"""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.rf_root = self.tmpdir / "research_failures"
        self.db = ResearchFailuresDB(self.rf_root)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_insert_and_get(self) -> None:
        """写入 + 按 failure_id 查询"""
        record = create_research_record(
            strategy_id="STRAT_TEST",
            context="回测中发现数据源异常",
            failure_type=ResearchFailureType.DATA_ISSUE,
            discovered_by="MOZHEN",
            severity=FailureSeverity.CRITICAL,
            root_cause="股票拆分未复权",
            tags=["数据质量", "复权"],
        )
        fid = self.db.insert(record)
        self.assertIsNotNone(fid)

        # 读回验证
        loaded = self.db.get(fid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.strategy_id, "STRAT_TEST")
        self.assertEqual(loaded.failure_type, ResearchFailureType.DATA_ISSUE)
        self.assertEqual(loaded.severity, FailureSeverity.CRITICAL)
        self.assertIn("数据质量", loaded.tags)

    def test_query_by_strategy(self) -> None:
        """按策略查询"""
        r1 = create_research_record("S1", "问题A", ResearchFailureType.DATA_ISSUE)
        r2 = create_research_record("S1", "问题B", ResearchFailureType.METHODOLOGY_BIAS)
        r3 = create_research_record("S2", "问题C", ResearchFailureType.VETO_FAILURE)
        self.db.batch_insert([r1, r2, r3])

        results = self.db.get_by_strategy("S1")
        self.assertEqual(len(results), 2)

        results_s2 = self.db.get_by_strategy("S2")
        self.assertEqual(len(results_s2), 1)
        self.assertEqual(results_s2[0].failure_type, ResearchFailureType.VETO_FAILURE)

    def test_query_by_type(self) -> None:
        """按类型查询"""
        r1 = create_research_record("S1", "数据问题", ResearchFailureType.DATA_ISSUE)
        r2 = create_research_record("S2", "偏见", ResearchFailureType.METHODOLOGY_BIAS)
        r3 = create_research_record("S3", "数据问题2", ResearchFailureType.DATA_ISSUE)
        self.db.batch_insert([r1, r2, r3])

        issues = self.db.get_by_type(ResearchFailureType.DATA_ISSUE)
        self.assertEqual(len(issues), 2)

        bias = self.db.get_by_type(ResearchFailureType.METHODOLOGY_BIAS)
        self.assertEqual(len(bias), 1)

    def test_statistics(self) -> None:
        """统计接口"""
        r1 = create_research_record("S1", "A", ResearchFailureType.DATA_ISSUE, severity=FailureSeverity.CRITICAL)
        r2 = create_research_record("S2", "B", ResearchFailureType.METHODOLOGY_BIAS, severity=FailureSeverity.MAJOR)
        r3 = create_research_record("S3", "C", ResearchFailureType.DATA_ISSUE, severity=FailureSeverity.MINOR)
        self.db.batch_insert([r1, r2, r3])

        by_type = self.db.count_by_type()
        self.assertEqual(by_type.get("DATA_ISSUE"), 2)
        self.assertEqual(by_type.get("METHODOLOGY_BIAS"), 1)

        by_sev = self.db.count_by_severity()
        self.assertEqual(by_sev.get("CRITICAL"), 1)

    def test_update_resolution(self) -> None:
        """更新解决状态"""
        record = create_research_record(
            "S1", "过拟合", ResearchFailureType.METHODOLOGY_BIAS
        )
        fid = self.db.insert(record)

        success = self.db.update_resolution(
            fid,
            resolution_notes="改用滚动验证，过拟合问题已解决",
            resolved=True,
        )
        self.assertTrue(success)

        loaded = self.db.get(fid)
        self.assertTrue(loaded.resolved)
        self.assertIn("滚动验证", loaded.resolution_notes)

    def test_cross_reference_with_q9a(self) -> None:
        """Q9b ↔ Q9a 交叉引用"""
        # 先创建 Q9a 数据库
        q9a_db_path = self.tmpdir / "test_cross_q9a.db"
        q9a_db = QFailuresDB(q9a_db_path)
        q9a_db.initialize()

        q9a_record = QFailureRecord(
            failure_id="cross_ref_fid",
            strategy_id="STRAT_CROSS",
            failure_type=FailureType.STATISTICAL_NOISE,
            discovered_by="G1",
            timestamp=datetime.now(_TZ_CST).isoformat(),
            parameter_set={},
            cause="测试交叉引用",
        )
        q9a_db.insert(q9a_record)
        q9a_db.close()

        # Q9b 记录关联 Q9a failure_id
        rf_record = create_research_record(
            strategy_id="STRAT_CROSS",
            context="人工复查确认噪声问题",
            failure_type=ResearchFailureType.DATA_ISSUE,
            q9a_failure_id="cross_ref_fid",
        )
        self.db.insert(rf_record)

        # Q9b 交叉查询
        cross = self.db.find_cross_references("STRAT_CROSS")
        self.assertEqual(cross["strategy_id"], "STRAT_CROSS")
        self.assertIn("cross_ref_fid", cross["q9a_ids"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
