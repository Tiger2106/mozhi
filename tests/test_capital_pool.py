"""
测试：CapitalPoolAllocator 资金池分配引擎

覆盖场景：
  - 四种分配模式各至少 2 个测试
  - total_capital 不变性（总和不超出 total_capital × 1.1）
  - 空信号、空标的处理
  - 再平衡功能
  - 边界情况（单标的、超出 max_positions）
"""

import sys
import os
import unittest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
src_dir = os.path.join(project_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from backtest.signals.capital_pool import CapitalPoolAllocator


class TestCapitalPoolAllocatorInit(unittest.TestCase):
    """构造函数测试"""

    def test_default_init(self):
        """默认初始化"""
        alloc = CapitalPoolAllocator()
        self.assertEqual(alloc.total_capital, 1_000_000)
        self.assertEqual(alloc.mode, "equal")
        self.assertEqual(alloc.max_positions, 5)

    def test_custom_init(self):
        """自定义参数初始化"""
        alloc = CapitalPoolAllocator(
            total_capital=500000, mode="signal_weighted", max_positions=3, safety_margin=0.8
        )
        self.assertEqual(alloc.total_capital, 500000)
        self.assertEqual(alloc.mode, "signal_weighted")
        self.assertEqual(alloc.max_positions, 3)
        self.assertEqual(alloc.safety_margin, 0.8)

    def test_invalid_mode(self):
        """无效模式应抛异常"""
        with self.assertRaises(ValueError):
            CapitalPoolAllocator(mode="invalid_mode")

    def test_invalid_capital(self):
        """非正资金应抛异常"""
        with self.assertRaises(ValueError):
            CapitalPoolAllocator(total_capital=0)


class TestEqualMode(unittest.TestCase):
    """等分模式测试"""

    def setUp(self):
        self.alloc = CapitalPoolAllocator(total_capital=1_000_000, mode="equal", max_positions=4)

    def test_two_symbols_equal(self):
        """两个标的，等分"""
        result = self.alloc.allocate({"A": 0.8, "B": 0.6})
        self.assertAlmostEqual(result["A"], 500000.0, delta=1)
        self.assertAlmostEqual(result["B"], 500000.0, delta=1)
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)

    def test_four_symbols_equal(self):
        """四个标的，每个 25 万"""
        result = self.alloc.allocate({"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.6})
        self.assertEqual(len(result), 4)
        for v in result.values():
            self.assertAlmostEqual(v, 250000.0, delta=1)
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)

    def test_exceed_max_positions(self):
        """超出 max_positions 时，只分配前 max_positions 个"""
        result = self.alloc.allocate({"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.6, "E": 0.5, "F": 0.4})
        self.assertEqual(len(result), 4)  # max_positions=4
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)

    def test_single_symbol_equal(self):
        """单标的，全分"""
        result = self.alloc.allocate({"A": 1.0})
        self.assertAlmostEqual(result["A"], 1_000_000.0, delta=1)


class TestSignalWeightedMode(unittest.TestCase):
    """信号加权模式测试"""

    def setUp(self):
        self.alloc = CapitalPoolAllocator(
            total_capital=1_000_000, mode="signal_weighted", safety_margin=0.9, max_positions=5
        )

    def test_two_symbols_weighted(self):
        """两个标的，按置信度比例分配"""
        result = self.alloc.allocate({"A": 0.8, "B": 0.2})
        # A 应该有更大份额
        self.assertGreater(result["A"], result["B"])
        # 总和应 ≈ total_capital
        total = sum(result.values())
        self.assertAlmostEqual(total, 1_000_000.0, delta=2)
        # 安全边际 0.9 → 加权分配 90%，剩余 10% 均分
        # A: 0.8/1.0×900000 + 50000 = 770000
        self.assertAlmostEqual(result["A"], 770_000.0, delta=2)
        self.assertAlmostEqual(result["B"], 230_000.0, delta=2)

    def test_three_symbols_weighted(self):
        """三个标的"""
        result = self.alloc.allocate({"A": 0.5, "B": 0.3, "C": 0.2})
        total = sum(result.values())
        self.assertAlmostEqual(total, 1_000_000.0, delta=2)
        self.assertGreater(result["A"], result["B"])
        self.assertGreater(result["B"], result["C"])

    def test_weighted_with_zero_score(self):
        """包含置信度为 0 的标的——应退化为等分余下的"""
        result = self.alloc.allocate({"A": 1.0, "B": 0.0})
        # A 应该获得几乎全部
        self.assertGreater(result["A"], result["B"])

    def test_all_same_score(self):
        """所有标的一致分数，应等于等分"""
        result = self.alloc.allocate({"A": 0.5, "B": 0.5, "C": 0.5})
        self.assertAlmostEqual(result["A"], result["B"], delta=1)
        self.assertAlmostEqual(result["B"], result["C"], delta=1)
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)


class TestRiskParityMode(unittest.TestCase):
    """风险平价模式测试"""

    def setUp(self):
        self.alloc = CapitalPoolAllocator(
            total_capital=1_000_000, mode="risk_parity", safety_margin=0.9, max_positions=5
        )

    def test_two_symbols_risk_parity(self):
        """两个标的，回撤大的仓位小"""
        result = self.alloc.allocate(
            signal_scores={"A": 0.8, "B": 0.6},
            risk_metrics={"A": {"drawdown": 0.01}, "B": {"drawdown": 0.05}},
        )
        # A（回撤小）应获得更大仓位
        self.assertGreater(result["A"], result["B"])
        total = sum(result.values())
        self.assertAlmostEqual(total, 1_000_000.0, delta=2)

    def test_three_symbols_risk_parity(self):
        """三个标的"""
        result = self.alloc.allocate(
            signal_scores={"A": 0.7, "B": 0.6, "C": 0.5},
            risk_metrics={"A": {"drawdown": 0.02}, "B": {"drawdown": 0.04}, "C": {"drawdown": 0.08}},
        )
        # A（回撤最小）最大，C（回撤最大）最小
        self.assertGreater(result["A"], result["B"])
        self.assertGreater(result["B"], result["C"])
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)

    def test_no_risk_data(self):
        """无风险数据时，退化为信号加权"""
        result = self.alloc.allocate(
            signal_scores={"A": 0.8, "B": 0.2},
            risk_metrics={},  # 无风险数据
        )
        self.assertGreater(result["A"], result["B"])
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)


class TestMomentumMode(unittest.TestCase):
    """动量分配模式测试"""

    def setUp(self):
        self.alloc = CapitalPoolAllocator(
            total_capital=1_000_000, mode="momentum", safety_margin=0.9, max_positions=5
        )

    def test_two_symbols_momentum(self):
        """动量大的标的分更多"""
        result = self.alloc.allocate(
            signal_scores={"A": 0.7, "B": 0.7},
            risk_metrics={"A": {"mom_5d": 0.05}, "B": {"mom_5d": -0.03}},
        )
        # A 动量正，B 动量负 → A > B
        self.assertGreater(result["A"], result["B"])
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)

    def test_three_symbols_momentum(self):
        """三个标的动量分配"""
        result = self.alloc.allocate(
            signal_scores={"A": 0.8, "B": 0.6, "C": 0.4},
            risk_metrics={
                "A": {"mom_5d": 0.1},
                "B": {"mom_5d": 0.02},
                "C": {"mom_5d": -0.05},
            },
        )
        self.assertGreater(result["A"], result["B"])
        self.assertGreater(result["B"], result["C"])
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)

    def test_no_momentum_data(self):
        """无动量数据时，退化为信号加权"""
        result = self.alloc.allocate(
            signal_scores={"A": 0.8, "B": 0.2},
            risk_metrics={},
        )
        self.assertGreater(result["A"], result["B"])
        self.assertAlmostEqual(sum(result.values()), 1_000_000.0, delta=2)

    def test_negative_momentum_clamped(self):
        """负动量被截断"""
        result = self.alloc.allocate(
            signal_scores={"A": 0.5, "B": 0.5},
            risk_metrics={"A": {"mom_5d": -0.6}, "B": {"mom_5d": 0.1}},
        )
        # A 即使负动量很大，也不应分配负资金
        self.assertGreaterEqual(result["A"], 0)
        self.assertGreater(result["B"], result["A"])


class TestCapitalInvariance(unittest.TestCase):
    """资金总量不变性测试"""

    def setUp(self):
        self.capital = 1_000_000

    def test_equal_invariance(self):
        """等分模式：总和不超过 total_capital × 1.1"""
        alloc = CapitalPoolAllocator(total_capital=self.capital, mode="equal")
        result = alloc.allocate({"A": 0.9, "B": 0.8, "C": 0.7})
        total = sum(result.values())
        self.assertLessEqual(total, self.capital * 1.1)

    def test_weighted_invariance(self):
        """信号加权：总和不超过 total_capital × 1.1"""
        alloc = CapitalPoolAllocator(total_capital=self.capital, mode="signal_weighted")
        result = alloc.allocate({"A": 0.9, "B": 0.8, "C": 0.7})
        total = sum(result.values())
        self.assertLessEqual(total, self.capital * 1.1)

    def test_risk_parity_invariance(self):
        """风险平价：总和不超过 total_capital × 1.1"""
        alloc = CapitalPoolAllocator(total_capital=self.capital, mode="risk_parity")
        result = alloc.allocate(
            {"A": 0.9, "B": 0.8},
            {"A": {"drawdown": 0.01}, "B": {"drawdown": 0.02}},
        )
        total = sum(result.values())
        self.assertLessEqual(total, self.capital * 1.1)

    def test_momentum_invariance(self):
        """动量分配：总和不超过 total_capital × 1.1"""
        alloc = CapitalPoolAllocator(total_capital=self.capital, mode="momentum")
        result = alloc.allocate(
            {"A": 0.9, "B": 0.8},
            {"A": {"mom_5d": 0.05}, "B": {"mom_5d": -0.02}},
        )
        total = sum(result.values())
        self.assertLessEqual(total, self.capital * 1.1)


class TestEdgeCases(unittest.TestCase):
    """边界情况测试"""

    def setUp(self):
        self.alloc = CapitalPoolAllocator(total_capital=1_000_000)

    def test_empty_signal(self):
        """空信号字典"""
        result = self.alloc.allocate({})
        self.assertEqual(result, {})

    def test_single_symbol(self):
        """单标的"""
        result = self.alloc.allocate({"A": 1.0})
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result["A"], 1_000_000.0, delta=1)

    def test_mode_switch(self):
        """运行时切换模式"""
        self.alloc.change_mode("signal_weighted")
        self.assertEqual(self.alloc.mode, "signal_weighted")
        result = self.alloc.allocate({"A": 0.8, "B": 0.2})
        self.assertGreater(result["A"], result["B"])

    def test_invalid_mode_switch(self):
        """切换到无效模式应抛异常"""
        with self.assertRaises(ValueError):
            self.alloc.change_mode("unknown")

    def test_utilization_rate(self):
        """资金利用率计算"""
        result = self.alloc.allocate({"A": 0.8, "B": 0.2})
        rate = self.alloc.utilization_rate(result)
        self.assertAlmostEqual(rate, 1.0, delta=0.001)  # 全分配 ≈ 100%

    def test_partial_utilization(self):
        """部分分配时的资金利用率"""
        alloc = CapitalPoolAllocator(total_capital=1_000_000, mode="equal", max_positions=10)
        result = alloc.allocate({"A": 0.8})  # 只有 1 个
        rate = alloc.utilization_rate(result)
        # 1 个 / max_positions=10 → 1/10, 但 equal 分配不会留下闲钱
        self.assertAlmostEqual(rate, 1.0, delta=0.001)


class TestRebalance(unittest.TestCase):
    """再平衡功能测试"""

    def setUp(self):
        self.alloc = CapitalPoolAllocator(total_capital=1_000_000, mode="equal", max_positions=3)

    def test_rebalance_equal(self):
        """等分模式再平衡"""
        result = self.alloc.rebalance({"A": 480000, "B": 520000})
        # 总和不变，分配应趋向等分
        total = sum(result.values())
        self.assertAlmostEqual(total, 1_000_000.0, delta=2)
        # 等分目标：各 50 万
        for v in result.values():
            self.assertAlmostEqual(v, 500_000.0, delta=2000)

    def test_rebalance_empty(self):
        """空持仓再平衡"""
        result = self.alloc.rebalance({})
        self.assertEqual(result, {})

    def test_rebalance_single(self):
        """单标的再平衡"""
        result = self.alloc.rebalance({"A": 800000})
        self.assertIn("A", result)
        self.assertAlmostEqual(result["A"], 800000.0, delta=1)

    def test_rebalance_with_market_data(self):
        """带市场数据的再平衡"""
        result = self.alloc.rebalance(
            positions={"A": 500000, "B": 500000},
            market_data={
                "A": {"signal_score": 0.9},
                "B": {"signal_score": 0.5},
            },
        )
        # A 信号更强，但在等分模式下分配应仍相近
        total = sum(result.values())
        self.assertAlmostEqual(total, 1_000_000.0, delta=2)

    def test_rebalance_with_low_usage(self):
        """总持仓低于 50% 时，不触发再平衡"""
        self.alloc.total_capital = 1_000_000
        result = self.alloc.rebalance({"A": 200000, "B": 200000})  # 40% 使用
        # 应返回原样
        self.assertAlmostEqual(result["A"], 200000.0, delta=1)
        self.assertAlmostEqual(result["B"], 200000.0, delta=1)


if __name__ == "__main__":
    unittest.main()
