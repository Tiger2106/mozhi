"""
测试：MultiInstrumentEngine 多标的并行引擎

覆盖场景：
  - 2~3 个标的的基本流程
  - 空标列表处理
  - 单个标的兼容
  - 模拟数据下的全链路分析
"""

import sys
import os
import json
import tempfile
import unittest

# 添加 src 到 path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.join(project_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from backtest.signals.multi_instrument_engine import (
    MultiInstrumentEngine,
    _build_conditional_return_matrix,
    _compute_capital_efficiency,
    _generate_mock_bars,
    _load_bars_from_csv,
    Bar,
)


class TestMultiInstrumentEngine(unittest.TestCase):
    """MultiInstrumentEngine 核心测试"""

    def setUp(self):
        self.engine = MultiInstrumentEngine(max_workers=2)
        # 使用模拟数据，种子确保可复现
        self.bars_A = _generate_mock_bars("TEST_A", days=200)
        self.bars_B = _generate_mock_bars("TEST_B", days=200)

    # ──────────────── 基本流程 ────────────────

    def test_single_instrument(self):
        """测试单个标的：兼容性验证"""
        results = self.engine.run(["TEST_A"])
        self.assertIn("TEST_A", results)
        self.assertEqual(results["TEST_A"]["status"], "READY")
        self.assertGreater(results["TEST_A"]["bar_count"], 0)

    def test_two_instruments(self):
        """测试两个标的的基本流程"""
        results = self.engine.run(["TEST_A", "TEST_B"])

        self.assertEqual(len(results), 2)
        for symbol in ["TEST_A", "TEST_B"]:
            self.assertIn(symbol, results)
            self.assertEqual(results[symbol]["status"], "READY")
            self.assertIn("breakout", results[symbol])
            self.assertIn("lifecycle", results[symbol])
            self.assertIn("conditional_return_matrix", results[symbol])
            self.assertIn("capital_efficiency", results[symbol])

    def test_three_instruments(self):
        """测试三个标的"""
        bars_C = _generate_mock_bars("TEST_C", days=150)
        # 将 C 的数据注入到缓存路径
        results = self.engine.run(["TEST_A", "TEST_B", "TEST_C"])
        self.assertEqual(len(results), 3)
        for symbol in ["TEST_A", "TEST_B", "TEST_C"]:
            self.assertIn(symbol, results)
            self.assertEqual(results[symbol]["status"], "READY")

    # ──────────────── 边界情况 ────────────────

    def test_empty_instruments(self):
        """测试空标列表处理"""
        results = self.engine.run([])
        self.assertEqual(results, {})
        self.assertIsInstance(results, dict)

    def test_unknown_symbol(self):
        """测试不存在的标的——应使用模拟数据回落"""
        results = self.engine.run(["__UNKNOWN_SYMBOL_XYZ__"])
        self.assertIn("__UNKNOWN_SYMBOL_XYZ__", results)
        self.assertEqual(results["__UNKNOWN_SYMBOL_XYZ__"]["status"], "READY")

    # ──────────────── 汇总方法 ────────────────

    def test_aggregate_results(self):
        """测试 aggregate_results 方法"""
        results = self.engine.run(["TEST_A", "TEST_B"])
        agg = self.engine.aggregate_results(results)

        self.assertEqual(agg["total_instruments"], 2)
        self.assertEqual(agg["successful"], 2)
        self.assertEqual(agg["failed"], 0)
        self.assertIn("total_breakouts", agg)
        self.assertIn("false_breakout_rate", agg)

    def test_compare_metrics(self):
        """测试 compare_metrics 横截面对比"""
        results = self.engine.run(["TEST_A", "TEST_B"])
        comparison = self.engine.compare_metrics(results)

        # 检查对比维度键
        expected_keys = [
            "breakout_frequency", "false_breakout_rate", "current_stage",
            "capital_efficiency", "sharpe_approx", "best_condition_pattern",
            "total_breakouts", "stage_distribution_summary",
        ]
        for key in expected_keys:
            self.assertIn(key, comparison, f"缺少对比维度: {key}")

        # 每个维度应包含所有标的
        for key in expected_keys:
            if key == "stage_distribution_summary":
                continue  # 该维度可能为空
            self.assertEqual(
                set(comparison[key].keys()),
                {"TEST_A", "TEST_B"},
                f"{key} 维度缺少标的",
            )

    def test_generate_summary(self):
        """测试 generate_summary Markdown 输出"""
        results = self.engine.run(["TEST_A"])
        summary = self.engine.generate_summary(results)

        self.assertIsInstance(summary, str)
        self.assertIn("多标的并行分析报告", summary)
        self.assertIn("TEST_A", summary)
        # 应包含各分项表头
        self.assertIn("标的", summary)
        self.assertIn("突破事件", summary)

    # ──────────────── JSON 序列化 ────────────────

    def test_to_json_string(self):
        """测试 to_json 返回字符串"""
        results = self.engine.run(["TEST_A"])
        json_str = self.engine.to_json(results)
        self.assertIsInstance(json_str, str)
        data = json.loads(json_str)
        self.assertIn("results", data)
        self.assertIn("TEST_A", data["results"])

    def test_to_json_file(self):
        """测试 to_json 写入文件"""
        results = self.engine.run(["TEST_A"])
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            self.engine.to_json(results, filepath=tmp_path)
            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("results", data)
            self.assertIn("TEST_A", data["results"])
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # ──────────────── 工具函数 ────────────────

    def test_generate_mock_bars(self):
        """测试模拟数据生成的一致性（种子决定）"""
        bars1 = _generate_mock_bars("SEED_TEST", days=100)
        bars2 = _generate_mock_bars("SEED_TEST", days=100)
        self.assertEqual(len(bars1), len(bars2))
        # 相同 symbol + seed → 相同数据
        for b1, b2 in zip(bars1, bars2):
            self.assertEqual(b1.date, b2.date)
            self.assertEqual(b1.close, b2.close)

    def test_conditional_return_matrix(self):
        """测试条件收益矩阵构建"""
        bars = _generate_mock_bars("MATRIX_TEST", days=200)
        matrix = _build_conditional_return_matrix(bars)

        self.assertEqual(matrix["status"], "READY")
        self.assertGreater(len(matrix["matrix"]), 0)
        for key, val in matrix["matrix"].items():
            self.assertIn("count", val)
            self.assertIn("avg_return", val)
            self.assertIn("positive_rate", val)

    def test_capital_efficiency(self):
        """测试资本效率计算"""
        bars = _generate_mock_bars("CE_TEST", days=200)
        matrix = _build_conditional_return_matrix(bars)
        ce = _compute_capital_efficiency(bars, matrix)

        self.assertIn("status", ce)
        if ce["status"] == "READY":
            self.assertIn("capital_efficiency", ce)
            self.assertIn("sharpe_approx", ce)

    def test_insufficient_data_matrix(self):
        """测试数据不足时的条件收益矩阵"""
        bars = _generate_mock_bars("SHORT", days=10)
        matrix = _build_conditional_return_matrix(bars)
        self.assertEqual(matrix["status"], "INSUFFICIENT_DATA")

    def test_insufficient_data_capital(self):
        """测试数据不足时的资本效率"""
        bars = _generate_mock_bars("SHORT", days=10)
        matrix = _build_conditional_return_matrix(bars)
        ce = _compute_capital_efficiency(bars, matrix)
        self.assertEqual(ce["status"], "INSUFFICIENT_DATA")


class TestDataLoading(unittest.TestCase):
    """数据加载层测试"""

    def test_csv_loading(self):
        """测试 CSV 加载函数"""
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write("date,open,high,low,close,volume\n")
            f.write("2026-01-01,10.0,10.5,9.8,10.2,1000000\n")
            f.write("2026-01-02,10.2,10.8,10.1,10.6,1200000\n")
            f.write("2026-01-03,10.6,10.9,10.3,10.4,900000\n")
            tmp_path = f.name

        try:
            bars = _load_bars_from_csv(tmp_path, symbol="TEST_CSV")
            self.assertEqual(len(bars), 3)
            self.assertEqual(bars[0].symbol, "TEST_CSV")
            self.assertEqual(bars[0].date, "2026-01-01")
            self.assertAlmostEqual(bars[0].open, 10.0)
            self.assertAlmostEqual(bars[-1].close, 10.4)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
