"""
测试：CrossSectionReport 横截面对比报告

覆盖场景：
  - 3 个标的基本对比表生成
  - 排名功能测试
  - 相关矩阵计算测试
  - 边界测试（1 个标的、0 个标的）
  - 数据不足时的行为
"""

import sys
import os
import unittest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.join(project_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from backtest.signals.cross_section import CrossSectionReport
from backtest.signals.multi_instrument_engine import MultiInstrumentEngine


def _make_mock_result(
    symbol: str,
    status: str = "READY",
    sharpe: float = 0.5,
    capital_efficiency: float = 0.01,
    total_breakouts: int = 50,
    false_rate: float = 0.15,
    bar_count: int = 360,
    avg_return: float = 0.005,
    signal_frequency: float = 30.0,
) -> dict:
    """
    构建一个模拟的 MultiInstrumentEngine 单标的结果字典。
    模拟 engine.run() 的输出格式。
    """
    return {
        "symbol": symbol,
        "status": status,
        "bar_count": bar_count,
        "date_range": {"start": "2025-01-01", "end": "2025-12-31"},
        "breakout": {
            "event_count": total_breakouts,
            "summary": {
                "total_breakouts": total_breakouts,
                "false_breakouts": int(total_breakouts * false_rate),
                "false_rate": false_rate,
            },
        },
        "lifecycle": {
            "total_bars_staged": bar_count,
            "current_stage": "STAGE_2",
            "stage_distribution": {
                "STAGE_1": bar_count // 5,
                "STAGE_2": bar_count // 2,
                "STAGE_3": bar_count // 4,
                "STAGE_4": bar_count // 20,
            },
            "stage_pct": {
                "STAGE_1": 0.20,
                "STAGE_2": 0.50,
                "STAGE_3": 0.25,
                "STAGE_4": 0.05,
            },
        },
        "conditional_return_matrix": {
            "status": "READY",
            "lookback": 20,
            "forward": 5,
            "total_samples": bar_count - 25,
            "matrix": {
                "up_up": {
                    "count": 40,
                    "avg_return": avg_return * 1.5,
                    "max_return": avg_return * 3.0,
                    "min_return": -avg_return,
                    "positive_rate": 0.65,
                    "avg_max_fwd": avg_return * 2.5,
                    "avg_min_fwd": -avg_return * 0.8,
                },
                "down_down": {
                    "count": 30,
                    "avg_return": avg_return * 0.5,
                    "max_return": avg_return * 2.0,
                    "min_return": -avg_return * 2.0,
                    "positive_rate": 0.40,
                    "avg_max_fwd": avg_return * 1.5,
                    "avg_min_fwd": -avg_return * 1.5,
                },
            },
            "_raw_results": [
                {"date": f"2025-{i:02d}-01", "price_trend": "up", "vol_trend": "up",
                 "ret_lookback": 0.02, "ret_forward": 0.01 + (i % 5) * 0.005,
                 "max_forward": 0.03, "min_forward": -0.01}
                for i in range(20)
            ],
        },
        "capital_efficiency": {
            "status": "READY",
            "capital_efficiency": capital_efficiency,
            "avg_return_per_trade": avg_return,
            "signal_frequency": signal_frequency,
            "sharpe_approx": sharpe,
            "total_samples": bar_count - 25,
            "total_bars": bar_count,
        },
    }


class TestCrossSectionReportBasic(unittest.TestCase):
    """基本功能测试"""

    def setUp(self):
        self.symbols = ["A", "B", "C"]
        self.results = {
            "A": _make_mock_result("A", sharpe=0.76, capital_efficiency=0.0279, total_breakouts=909, false_rate=0.1309, bar_count=360, avg_return=0.005, signal_frequency=9.8),
            "B": _make_mock_result("B", sharpe=1.20, capital_efficiency=0.0350, total_breakouts=500, false_rate=0.0800, bar_count=360, avg_return=0.008, signal_frequency=8.0),
            "C": _make_mock_result("C", sharpe=0.50, capital_efficiency=0.0150, total_breakouts=300, false_rate=0.2000, bar_count=360, avg_return=0.003, signal_frequency=12.0),
        }
        self.report = CrossSectionReport(self.results)

    def test_summary_table_keys(self):
        """对比表应包含所有标的"""
        table = self.report.summary_table()
        for s in self.symbols:
            self.assertIn(s, table, f"对比表缺少标的 {s}")

    def test_summary_table_metrics(self):
        """对比表应包含基本指标"""
        table = self.report.summary_table()
        row = table["A"]
        expected_metrics = [
            "symbol", "annualized_return", "max_drawdown", "sharpe",
            "calmar", "total_breakouts", "false_breakout_rate",
            "capital_efficiency", "avg_hold_days", "current_stage",
        ]
        for m in expected_metrics:
            self.assertIn(m, row, f"指标缺失: {m}")

    def test_sharpe_values(self):
        """Sharpe 值应正确提取"""
        table = self.report.summary_table()
        self.assertAlmostEqual(table["A"]["sharpe"], 0.76, delta=0.01)
        self.assertAlmostEqual(table["B"]["sharpe"], 1.20, delta=0.01)
        self.assertAlmostEqual(table["C"]["sharpe"], 0.50, delta=0.01)

    def test_breakout_counts(self):
        """突破数应正确"""
        table = self.report.summary_table()
        self.assertEqual(table["A"]["total_breakouts"], 909)
        self.assertEqual(table["B"]["total_breakouts"], 500)
        self.assertEqual(table["C"]["total_breakouts"], 300)


class TestRanking(unittest.TestCase):
    """排名功能测试"""

    def setUp(self):
        # B 最强，A 居中，C 最弱
        self.results = {
            "A": _make_mock_result("A", sharpe=0.76, capital_efficiency=0.0279, total_breakouts=909, false_rate=0.13, bar_count=360, avg_return=0.005),
            "B": _make_mock_result("B", sharpe=1.20, capital_efficiency=0.0350, total_breakouts=500, false_rate=0.08, bar_count=360, avg_return=0.008),
            "C": _make_mock_result("C", sharpe=0.50, capital_efficiency=0.0150, total_breakouts=300, false_rate=0.20, bar_count=360, avg_return=0.003),
        }
        self.report = CrossSectionReport(self.results)

    def test_rank_by_sharpe(self):
        """按 Sharpe 排名：B > A > C"""
        ranked = self.report.rank_by("sharpe")
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0]["symbol"], "B")
        self.assertEqual(ranked[1]["symbol"], "A")
        self.assertEqual(ranked[2]["symbol"], "C")
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[1]["rank"], 2)
        self.assertEqual(ranked[2]["rank"], 3)

    def test_rank_by_capital_efficiency(self):
        """按资本效率排名：B > A > C"""
        ranked = self.report.rank_by("capital_efficiency")
        self.assertEqual(ranked[0]["symbol"], "B")

    def test_rank_by_total_breakouts(self):
        """按突破数排名：A > B > C"""
        ranked = self.report.rank_by("total_breakouts")
        self.assertEqual(ranked[0]["symbol"], "A")
        self.assertEqual(ranked[1]["symbol"], "B")

    def test_rank_contains_metric(self):
        """排名条目应包含指标值"""
        ranked = self.report.rank_by("sharpe")
        self.assertIn("sharpe", ranked[0])
        self.assertIn("rank", ranked[0])
        self.assertIn("symbol", ranked[0])


class TestCorrelationMatrix(unittest.TestCase):
    """相关矩阵测试"""

    def setUp(self):
        self.results = {
            "A": _make_mock_result("A", sharpe=0.76, capital_efficiency=0.0279, total_breakouts=909, bar_count=360),
            "B": _make_mock_result("B", sharpe=1.20, capital_efficiency=0.0350, total_breakouts=500, bar_count=360),
            "C": _make_mock_result("C", sharpe=0.50, capital_efficiency=0.0150, total_breakouts=300, bar_count=360),
        }
        self.report = CrossSectionReport(self.results)

    def test_correlation_matrix_keys(self):
        """相关矩阵应包含所有标的"""
        matrix = self.report.correlation_matrix()
        for s in ["A", "B", "C"]:
            self.assertIn(s, matrix, f"相关矩阵缺少标的 {s}")

    def test_self_correlation(self):
        """自相关系数为 1.0"""
        matrix = self.report.correlation_matrix()
        for s in ["A", "B", "C"]:
            self.assertEqual(matrix[s][s], 1.0)

    def test_correlation_symmetric(self):
        """相关矩阵应是对称的"""
        matrix = self.report.correlation_matrix()
        for s1 in ["A", "B", "C"]:
            for s2 in ["A", "B", "C"]:
                if s1 != s2:
                    self.assertAlmostEqual(
                        matrix[s1][s2], matrix[s2][s1],
                        places=2,
                        msg=f"不对称: {s1}↔{s2}",
                    )

    def test_correlation_range(self):
        """相关系数应在 [-1, 1] 范围内"""
        matrix = self.report.correlation_matrix()
        for s1, sub in matrix.items():
            for s2, v in sub.items():
                if s1 != s2:
                    self.assertGreaterEqual(v, -1.0)
                    self.assertLessEqual(v, 1.0)


class TestEdgeCases(unittest.TestCase):
    """边界情况测试"""

    def test_single_instrument(self):
        """单个标的"""
        results = {"A": _make_mock_result("A")}
        report = CrossSectionReport(results)
        table = report.summary_table()
        self.assertEqual(len(table), 1)
        self.assertIn("A", table)

        # 单标的排名
        ranked = report.rank_by("sharpe")
        self.assertEqual(len(ranked), 1)

        # 单标的相关矩阵为空
        matrix = report.correlation_matrix()
        self.assertEqual(matrix, {})

    def test_empty_instruments(self):
        """空标的字典"""
        report = CrossSectionReport({})
        table = report.summary_table()
        self.assertEqual(table, {})

        ranked = report.rank_by("sharpe")
        self.assertEqual(ranked, [])

        matrix = report.correlation_matrix()
        self.assertEqual(matrix, {})

    def test_failed_instrument(self):
        """包含失败标的"""
        results = {
            "A": _make_mock_result("A"),
            "B": _make_mock_result("B", status="FAILED", sharpe=0),
        }
        report = CrossSectionReport(results)
        table = report.summary_table()
        # 失败标的不应出现在对比表
        self.assertIn("A", table)
        self.assertNotIn("B", table)

    def test_unknown_metric_ranking(self):
        """使用不存在的指标排名"""
        results = {"A": _make_mock_result("A")}
        report = CrossSectionReport(results)
        ranked = report.rank_by("nonexistent_metric")
        self.assertEqual(ranked, [])

    def test_correlation_single_symbol(self):
        """单个标的的相关矩阵为空"""
        results = {"A": _make_mock_result("A")}
        report = CrossSectionReport(results)
        matrix = report.correlation_matrix()
        self.assertEqual(matrix, {})

    def test_missing_matrix_data(self):
        """缺少条件收益矩阵数据的标的"""
        results = {
            "A": _make_mock_result("A"),
            "B": {
                "symbol": "B",
                "status": "READY",
                "bar_count": 360,
                "capital_efficiency": {"sharpe_approx": 0.5, "capital_efficiency": 0.01},
                "breakout": {},
                "lifecycle": {},
                "conditional_return_matrix": {"status": "INSUFFICIENT_DATA"},
            },
        }
        report = CrossSectionReport(results)
        table = report.summary_table()
        self.assertIn("A", table)
        self.assertIn("B", table)


class TestCrossReference(unittest.TestCase):
    """交叉引用综述测试"""

    def setUp(self):
        self.results = {
            "A": _make_mock_result("A", sharpe=0.76, capital_efficiency=0.0279, total_breakouts=909),
            "B": _make_mock_result("B", sharpe=1.20, capital_efficiency=0.0350, total_breakouts=500),
        }
        self.report = CrossSectionReport(self.results)

    def test_cross_reference(self):
        """交叉引用应包含所有标的"""
        cross = self.report.cross_reference()
        symbols = {c["symbol"] for c in cross}
        self.assertIn("A", symbols)
        self.assertIn("B", symbols)

    def test_cross_reference_structure(self):
        """交叉引用应包含最佳和最弱指标"""
        cross = self.report.cross_reference()
        for c in cross:
            self.assertIn("best_metric", c)
            self.assertIn("worst_metric", c)
            self.assertIn("best_value", c)
            self.assertIn("worst_value", c)

    def test_cross_reference_empty(self):
        """空数据交叉引用"""
        report = CrossSectionReport({})
        cross = report.cross_reference()
        self.assertEqual(cross, [])


if __name__ == "__main__":
    unittest.main()
