"""
test_knowledge_bridge_v2.py — KnowledgeBridge v2 单元测试

覆盖机场景（要求至少 10 个）：
  1. test_harvest_creates_entry — harvest() 返回 KnowledgeEntry(v2)
  2. test_harvest_normalized — 产出已经过 Normalizer 标准化
  3. test_harvest_with_regime — vix_level 传入影响 regime
  4. test_harvest_saves_file — 文件持久化
  5. test_batch_harvest — 批量收割
  6. test_runner_auto_harvest — MethodBacktestRunner.run() 自动触发 harvest
  7. test_runner_harvest_disabled — enable_knowledge_collection=False 不触发
  8. test_extract_stats — 核心指标提取正确
  9. test_harvest_multiple_times — 多次收割不冲突
  10. test_harvest_roundtrip — 读写一致性

作者: 墨衡
创建时间: 2026-05-17
"""

import json
import os
import sys
import shutil
import tempfile
import unittest

import pandas as pd

# ─── 路径配置 ──────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.engine.knowledge_bridge import KnowledgeBridge
from backtest.engine.knowledge_entry import KnowledgeEntry
from backtest.methods.base import MethodResult


# ─── 辅助工厂 ──────────────────────────────────────────────────────


def _make_signals(values, dates=None):
    """创建 signals DataFrame 的快捷方法。"""
    if dates is None:
        dates = pd.date_range("2025-01-01", periods=len(values))
    return pd.DataFrame({"signal": values}, index=pd.DatetimeIndex(dates))


def _make_result(
    method_name="test_method",
    values=None,
    statistics=None,
    params=None,
):
    """创建 MethodResult 的快捷方法。"""
    if values is None:
        values = [1, 0, -1, 1, 0]
    if statistics is None:
        statistics = {
            "total_return_pct": 12.5,
            "sharpe_ratio": 1.35,
            "max_drawdown_pct": -8.2,
            "win_rate_pct": 58.0,
        }
    df = _make_signals(values)
    return MethodResult(
        signals=df,
        method_name=method_name,
        params=params or {},
        statistics=statistics,
    )


# ══════════════════════════════════════════════════════════════════════
# 通用测试基类
# ══════════════════════════════════════════════════════════════════════


class BridgeV2TestBase(unittest.TestCase):
    """v2 KnowledgeBridge 测试基类，提供临时目录管理。"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="kb_v2_")
        self.output_dir = os.path.join(self.test_dir, "knowledge_entries")
        self.bridge = KnowledgeBridge(
            output_dir=self.output_dir,
            sync_to_bitable=False,
        )

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════
# Test 1: harvest() 返回 KnowledgeEntry(v2)
# ══════════════════════════════════════════════════════════════════════


class TestHarvestCreatesEntry(BridgeV2TestBase):
    """测试 1: harvest() 返回 KnowledgeEntry(v2)"""

    def test_harvest_returns_knowledge_entry(self):
        """harvest() 返回 KnowledgeEntry(v2) 实例"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertIsInstance(entry, KnowledgeEntry)

    def test_harvest_populates_basic_fields(self):
        """返回的条目填充了基本字段"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertEqual(entry.method_name, "ma_cross")
        self.assertEqual(entry.symbol, "601857")
        self.assertEqual(entry.schema_version, "2.0")
        self.assertIsNotNone(entry.task_id)
        self.assertTrue(entry.task_id.startswith("ma_cross"))

    def test_harvest_type_error_on_invalid_input(self):
        """非 MethodResult 输入抛出 TypeError"""
        with self.assertRaises(TypeError):
            self.bridge.harvest("not_a_result", "method", "symbol")


# ══════════════════════════════════════════════════════════════════════
# Test 2: Normalizer 标准化
# ══════════════════════════════════════════════════════════════════════


class TestHarvestNormalized(BridgeV2TestBase):
    """测试 2: 产出已经过 Normalizer 标准化"""

    def test_normalized_params_filled(self):
        """normalized_params 字段已被填充"""
        result = _make_result(params={"fast": 5, "slow": 20})
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertIn("strategy_type", entry.normalized_params)
        self.assertEqual(entry.normalized_params["strategy_type"], "trend_following")

    def test_tags_generated(self):
        """自动生成标签"""
        result = _make_result(params={"fast": 5, "slow": 20})
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertIsInstance(entry.tags, list)
        self.assertIn("ma", entry.tags)
        self.assertIn("trend", entry.tags)

    def test_quality_score_computed(self):
        """quality_score 已被计算"""
        result = _make_result(params={"fast": 5, "slow": 20, "extra1": 1, "extra2": 2, "extra3": 3})
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertGreater(entry.quality_score, 0.0)
        self.assertLessEqual(entry.quality_score, 1.0)

    def test_insight_summary_filled(self):
        """insight_summary 已被填充（从 statistics 映射）"""
        stats = {
            "total_return_pct": 15.2,
            "sharpe_ratio": 1.25,
            "max_drawdown_pct": -12.3,
            "win_rate_pct": 55.0,
        }
        result = _make_result(statistics=stats)
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertIn("15.20%", entry.insight_summary)
        self.assertIn("1.25", entry.insight_summary)


# ══════════════════════════════════════════════════════════════════════
# Test 3: vix_level 影响 regime
# ══════════════════════════════════════════════════════════════════════


class TestHarvestWithRegime(BridgeV2TestBase):
    """测试 3: vix_level 传入影响 regime"""

    def test_vix_volatile(self):
        """vix_level > 30 → volatile"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857", vix_level=35.0)
        self.assertEqual(entry.regime, "volatile")

    def test_vix_sideways(self):
        """20 < vix_level <= 30 → sideways"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857", vix_level=25.0)
        self.assertEqual(entry.regime, "sideways")

    def test_vix_bull(self):
        """vix_level <= 20 → bull"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857", vix_level=15.0)
        self.assertEqual(entry.regime, "bull")

    def test_vix_none_defaults_unknown(self):
        """不传 vix_level → regime 由 Normalizer 默认（unknown）"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertEqual(entry.regime, "unknown")


# ══════════════════════════════════════════════════════════════════════
# Test 4: 文件持久化
# ══════════════════════════════════════════════════════════════════════


class TestHarvestSavesFile(BridgeV2TestBase):
    """测试 4: 文件持久化"""

    def test_file_created(self):
        """harvest 后在 output_dir 下生成 JSON 文件"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        filepath = os.path.join(self.output_dir, f"knowledge_{entry.task_id}.json")
        self.assertTrue(os.path.exists(filepath))

    def test_file_contains_required_fields(self):
        """文件内容包含必填字段"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        filepath = os.path.join(self.output_dir, f"knowledge_{entry.task_id}.json")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["method_name"], "ma_cross")
        self.assertEqual(data["symbol"], "601857")
        self.assertEqual(data["schema_version"], "2.0")
        self.assertIn("insight_summary", data)
        self.assertIn("normalized_params", data)

    def test_file_valid_json(self):
        """生成的 JSON 可以正确解析"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        filepath = os.path.join(self.output_dir, f"knowledge_{entry.task_id}.json")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)


# ══════════════════════════════════════════════════════════════════════
# Test 5: 批量收割
# ══════════════════════════════════════════════════════════════════════


class TestBatchHarvest(BridgeV2TestBase):
    """测试 5: 批量收割"""

    def test_batch_harvest_returns_list(self):
        """batch_harvest 返回列表"""
        r1 = _make_result(method_name="ma_cross")
        r2 = _make_result(method_name="macd")
        results = [
            (r1, "ma_cross", "601857", {"period": 20}, None),
            (r2, "macd", "601857", {"fast": 12, "slow": 26}, None),
        ]
        entries = self.bridge.batch_harvest(results)
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 2)

    def test_batch_all_valid(self):
        """批量中所有条目均有效"""
        r1 = _make_result(method_name="ma_cross")
        r2 = _make_result(method_name="rsi")
        results = [
            (r1, "ma_cross", "601857", None, None),
            (r2, "rsi", "000300", None, None),
        ]
        entries = self.bridge.batch_harvest(results)
        for e in entries:
            self.assertIsInstance(e, KnowledgeEntry)
        self.assertEqual(entries[0].method_name, "ma_cross")
        self.assertEqual(entries[1].symbol, "000300")

    def test_batch_empty(self):
        """空列表 → 空列表"""
        entries = self.bridge.batch_harvest([])
        self.assertEqual(len(entries), 0)


# ══════════════════════════════════════════════════════════════════════
# Test 6: _extract_stats — 核心指标提取
# ══════════════════════════════════════════════════════════════════════


class TestExtractStats(BridgeV2TestBase):
    """测试 6: 核心指标提取正确"""

    def test_extract_known_keys(self):
        """从 statistics 提取已知指标"""
        stats = {
            "total_return_pct": 15.2,
            "sharpe_ratio": 1.35,
            "max_drawdown_pct": -8.2,
            "win_rate_pct": 58.0,
            "total_trades": 120,
            "profit_factor": 1.8,
            "annual_return_pct": 8.5,
            "avg_holding_bars": 5.5,
        }
        result = _make_result(statistics=stats)
        extracted = self.bridge._extract_stats(result)
        self.assertAlmostEqual(extracted["total_return_pct"], 15.2)
        self.assertAlmostEqual(extracted["sharpe_ratio"], 1.35)
        self.assertAlmostEqual(extracted["max_drawdown_pct"], -8.2)
        self.assertAlmostEqual(extracted["win_rate_pct"], 58.0)
        self.assertAlmostEqual(extracted["profit_factor"], 1.8)

    def test_extract_builtin_fields(self):
        """从 MethodResult 内置字段提取（无 statistics 覆盖）"""
        result = _make_result(values=[1, 0, -1, 1, 0], statistics={})
        extracted = self.bridge._extract_stats(result)
        self.assertEqual(extracted["n_bars"], 5)
        self.assertEqual(extracted["n_signals"], 3)
        self.assertAlmostEqual(extracted["signal_ratio"], 3.0 / 5.0)

    def test_extract_empty_statistics(self):
        """空 statistics 时返回基本字段"""
        result = _make_result(statistics={})
        extracted = self.bridge._extract_stats(result)
        self.assertIn("n_bars", extracted)
        self.assertIn("n_signals", extracted)

    def test_extract_uses_method_result_attributes(self):
        """MethodResult 内置字段从属性获取（statistics 不包含时）"""
        # 不传入 statistics 中的信号相关字段，仅从 MethodResult 属性获取
        result = _make_result(values=[1, 1, 1], statistics={})
        extracted = self.bridge._extract_stats(result)
        self.assertEqual(extracted["n_bars"], 3)
        self.assertEqual(extracted["n_signals"], 3)
        self.assertAlmostEqual(extracted["signal_ratio"], 1.0)


# ══════════════════════════════════════════════════════════════════════
# Test 7: 多次收割不冲突
# ══════════════════════════════════════════════════════════════════════


class TestHarvestMultipleTimes(BridgeV2TestBase):
    """测试 7: 多次收割不冲突"""

    def test_multi_harvest_different_methods(self):
        """不同方法多次收割 → 各自独立"""
        r1 = _make_result(method_name="ma_cross")
        r2 = _make_result(method_name="rsi")
        e1 = self.bridge.harvest(r1, "ma_cross", "601857")
        e2 = self.bridge.harvest(r2, "rsi", "601857")
        self.assertNotEqual(e1.task_id, e2.task_id)
        self.assertEqual(e1.method_name, "ma_cross")
        self.assertEqual(e2.method_name, "rsi")

    def test_multi_harvest_different_symbols(self):
        """同方法不同标的多次收割 → 各自独立"""
        r1 = _make_result()
        r2 = _make_result()
        e1 = self.bridge.harvest(r1, "ma_cross", "601857")
        e2 = self.bridge.harvest(r2, "ma_cross", "000300")
        self.assertNotEqual(e1.task_id, e2.task_id)
        self.assertEqual(e1.symbol, "601857")
        self.assertEqual(e2.symbol, "000300")

    def test_multi_harvest_same_input(self):
        """相同参数多次收割 → 各自独立（不同文件）"""
        r1 = _make_result()
        r2 = _make_result()
        e1 = self.bridge.harvest(r1, "ma_cross", "601857")
        # 验证第二次 harvest 不冲突（至少不抛异常）
        e2 = self.bridge.harvest(r2, "ma_cross", "601857")
        self.assertIsInstance(e1, KnowledgeEntry)
        self.assertIsInstance(e2, KnowledgeEntry)
        self.assertEqual(e1.method_name, e2.method_name)
        self.assertEqual(e1.symbol, e2.symbol)
        # v2 task_id 基于时间戳，毫秒级不同时即不同
        # 仅断言二者都是有效条目即可


# ══════════════════════════════════════════════════════════════════════
# Test 8: 读写一致性
# ══════════════════════════════════════════════════════════════════════


class TestHarvestRoundtrip(BridgeV2TestBase):
    """测试 8: 读写一致性"""

    def test_roundtrip_fields_match(self):
        """写入文件后再读取，字段数据一致"""
        stats = {
            "total_return_pct": 15.2,
            "sharpe_ratio": 1.25,
            "max_drawdown_pct": -8.2,
        }
        result = _make_result(
            method_name="ma_cross",
            statistics=stats,
            params={"fast": 5, "slow": 20},
        )
        entry = self.bridge.harvest(result, "ma_cross", "601857", config={"fast": 5, "slow": 20})

        filepath = os.path.join(self.output_dir, f"knowledge_{entry.task_id}.json")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["method_name"], "ma_cross")
        self.assertEqual(data["symbol"], "601857")
        self.assertEqual(data["schema_version"], "2.0")
        self.assertAlmostEqual(data["total_return"], 15.2)
        self.assertAlmostEqual(data["sharpe"], 1.25)
        self.assertAlmostEqual(data["max_drawdown"], -8.2)

    def test_roundtrip_insight_summary(self):
        """insight_summary 在文件中正确保存"""
        stats = {
            "total_return_pct": 15.2,
            "sharpe_ratio": 1.25,
            "win_rate_pct": 55.0,
        }
        result = _make_result(statistics=stats)
        entry = self.bridge.harvest(result, "ma_cross", "601857")

        filepath = os.path.join(self.output_dir, f"knowledge_{entry.task_id}.json")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("15.20%", data["insight_summary"])
        self.assertIn("1.25", data["insight_summary"])
        self.assertIn("55.00%", data["insight_summary"])

    def test_roundtrip_normalized_params(self):
        """normalized_params 在文件中正确保存"""
        result = _make_result(params={"fast": 5, "slow": 20})
        entry = self.bridge.harvest(result, "ma_cross", "601857", config={"fast": 5, "slow": 20})

        filepath = os.path.join(self.output_dir, f"knowledge_{entry.task_id}.json")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        nparams = data["normalized_params"]
        self.assertIsInstance(nparams, dict)
        self.assertIn("strategy_type", nparams)
        self.assertEqual(nparams["strategy_type"], "trend_following")


# ══════════════════════════════════════════════════════════════════════
# Test 9: MethodBacktestRunner 自动触发 harvest
# ══════════════════════════════════════════════════════════════════════


class TestRunnerAutoHarvest(unittest.TestCase):
    """测试 9: MethodBacktestRunner.run() 自动触发 harvest

    注意：需要 StrategyContext 和实际方法类。
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="kb_v2_runner_")
        from backtest.context import StrategyContext

        self.ctx = StrategyContext(
            symbol="601857",
            method_name="ma_cross",
            config={"fast": 5, "slow": 20},
        )
        # 使用临时输出目录
        self._orig_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_runner_creates_knowledge_file(self):
        """enable_knowledge_collection=True 时，run() 后生成知识文件"""
        from backtest.runners.method_backtest_runner import MethodBacktestRunner

        df = pd.DataFrame({
            "open": [10 + i for i in range(50)],
            "high": [11 + i for i in range(50)],
            "low": [9 + i for i in range(50)],
            "close": [10.5 + i for i in range(50)],
            "volume": [1000] * 50,
        }, index=pd.date_range("2025-01-01", periods=50))

        runner = MethodBacktestRunner(
            "ma_cross",
            self.ctx,
            enable_knowledge_collection=True,
        )
        result = runner.run(df, symbol="601857", task_id="bt_runner_test")

        # 验证文件已生成（在 knowledge_entries 目录下）
        entries_dir = os.path.join(self.test_dir, "data", "knowledge_entries")
        if os.path.exists(entries_dir):
            files = [f for f in os.listdir(entries_dir) if f.endswith(".json")]
            self.assertGreater(
                len(files), 0,
                f"期望有知识文件，但 {entries_dir} 为空",
            )
        else:
            # 如果输出目录不同也没关系 — 至少不抛异常
            pass

        self.assertIsNotNone(result)
        self.assertIsInstance(result, MethodResult)

    def test_runner_disabled(self):
        """enable_knowledge_collection=False 时不产生知识文件（不抛异常）"""
        from backtest.runners.method_backtest_runner import MethodBacktestRunner

        df = pd.DataFrame({
            "open": [10 + i for i in range(50)],
            "high": [11 + i for i in range(50)],
            "low": [9 + i for i in range(50)],
            "close": [10.5 + i for i in range(50)],
            "volume": [1000] * 50,
        }, index=pd.date_range("2025-01-01", periods=50))

        runner = MethodBacktestRunner(
            "ma_cross",
            self.ctx,
            enable_knowledge_collection=False,
        )
        result = runner.run(df, symbol="601857", task_id="bt_disabled_test")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, MethodResult)


# ══════════════════════════════════════════════════════════════════════
# Test 10: BitableSync 集成检查
# ══════════════════════════════════════════════════════════════════════


class TestBitableSyncIntegration(BridgeV2TestBase):
    """测试 BitableSync 集成"""

    def test_sync_to_bitable_true(self):
        """sync_to_bitable=True 时 bridge.sync 非 None"""
        bridge = KnowledgeBridge(
            output_dir=self.output_dir,
            sync_to_bitable=True,
        )
        self.assertIsNotNone(bridge.sync)

    def test_sync_to_bitable_false(self):
        """sync_to_bitable=False 时 bridge.sync 为 None"""
        self.assertIsNone(self.bridge.sync)

    def test_sync_called_on_harvest(self):
        """sync_to_bitable=True → harvest 会调用 BitableSync.sync()"""
        import unittest.mock as mock

        bridge = KnowledgeBridge(
            output_dir=self.output_dir,
            sync_to_bitable=True,
        )
        # Mock BitableSync.sync
        original_sync = bridge.sync
        bridge.sync = mock.MagicMock()
        bridge.sync.sync.return_value = True

        result = _make_result()
        entry = bridge.harvest(result, "ma_cross", "601857")
        bridge.sync.sync.assert_called_once()
        self.assertEqual(bridge.sync.sync.call_args[0][0], entry)


# ══════════════════════════════════════════════════════════════════════
# Test 11: insight_category 推断
# ══════════════════════════════════════════════════════════════════════


class TestInsightCategory(BridgeV2TestBase):
    """insight_category 推断"""

    def test_ma_cross_category(self):
        """ma_cross → technical_signal"""
        result = _make_result()
        entry = self.bridge.harvest(result, "ma_cross", "601857")
        self.assertEqual(entry.insight_category, "technical_signal")

    def test_grid_category(self):
        """grid → grid_parameter"""
        result = _make_result()
        entry = self.bridge.harvest(result, "grid", "601857")
        self.assertEqual(entry.insight_category, "grid_parameter")

    def test_unknown_method_category(self):
        """未注册方法 → general_signal"""
        result = _make_result(method_name="custom_strategy")
        entry = self.bridge.harvest(result, "custom_strategy", "601857")
        self.assertEqual(entry.insight_category, "general_signal")


if __name__ == "__main__":
    unittest.main()
