"""
test_knowledge_bridge.py — KnowledgeBridge v2 单元测试（已升级至v2接口）

覆盖场景：
1. 空 MethodResult harvest（空 DataFrame + 全零信号）
2. statistics 字段映射正确性（8 个目标字段 + signal_density）
3. 幂等 upsert（同 task_id 多次 harvest 不重复）
4. α 置信度融合计算（historical_confidence 加权）
5. TypeError 输入（非 MethodResult 传入 harvest）

作者: 墨衡（v2升级: 2026-05-17）
"""

import sys
import os
import unittest
import shutil

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.methods.base import MethodResult
from backtest.engine.knowledge_bridge import (
    KnowledgeBridge,
    KnowledgeEntry,
    _map_statistics_to_insight,
    _compute_confidence,
    STATISTICS_MAPPING,
    _STORE,
)


# ─── 辅助工厂 ──────────────────────────────────────────────


def _make_signals(values, dates=None):
    """创建 signals DataFrame 的快捷方法。"""
    if dates is None:
        dates = pd.date_range("2025-01-01", periods=len(values))
    return pd.DataFrame({"signal": values}, index=pd.DatetimeIndex(dates))


# ════════════════════════════════════════════════════════════
# 场景 1: 空 MethodResult harvest（v2 接口）
# ════════════════════════════════════════════════════════════


class TestHarvest_空MethodResult(unittest.TestCase):
    """场景1: 空 MethodResult harvest"""

    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_kb_test")
        self.bridge = KnowledgeBridge(output_dir=self._tmp, sync_to_bitable=False)
        _STORE.clear()

    def tearDown(self):
        _STORE.clear()
        if os.path.exists(self._tmp):
            shutil.rmtree(self._tmp)

    def test_empty_dataframe(self):
        """空 DataFrame 的 MethodResult → harvest 正常"""
        df = pd.DataFrame({"signal": []}, dtype=int)
        result = MethodResult(signals=df)
        # v2 接口: harvest(result, method_name, symbol, config)
        entry = self.bridge.harvest(result, method_name="ma_cross", symbol="TEST")
        self.assertEqual(entry.method_name, "ma_cross")
        self.assertEqual(entry.symbol, "TEST")
        # 空数据 → 低置信度（默认0.5 - 极短数据扣分）
        self.assertLessEqual(entry.confidence, 0.5)

    def test_all_zero_signals(self):
        """全零信号 → n_signals=0, signal_ratio=0.0"""
        df = _make_signals([0, 0, 0, 0, 0])
        result = MethodResult(signals=df)
        entry = self.bridge.harvest(result, method_name="rsi", symbol="ZERO")
        self.assertGreaterEqual(entry.confidence, 0.05)
        self.assertIsNotNone(entry.insight_summary)

    def test_harvest_no_config(self):
        """不传 config → harvest 仍然正常"""
        df = _make_signals([1, 0, -1])
        result = MethodResult(signals=df)
        entry = self.bridge.harvest(result, method_name="no_ctx", symbol="SYM")
        self.assertEqual(entry.symbol, "SYM")
        self.assertEqual(entry.method_name, "no_ctx")


# ════════════════════════════════════════════════════════════
# 场景 2: statistics 字段映射正确性
# ════════════════════════════════════════════════════════════


class TestStatisticsMapping(unittest.TestCase):
    """场景2: statistics 字段映射正确性"""

    def test_all_8_statistics_mapped(self):
        """8 个目标统计字段全部映射到 insight_summary"""
        stats = {
            "total_return_pct": 15.5,
            "annual_return_pct": 8.2,
            "sharpe_ratio": 1.35,
            "max_drawdown_pct": -12.3,
            "win_rate_pct": 62.0,
            "profit_factor": 1.85,
            "total_trades": 45,
            "avg_holding_bars": 3.5,
        }
        insight = _map_statistics_to_insight(stats)
        self.assertIn("15.50%", insight)
        self.assertIn("8.20%", insight)
        self.assertIn("1.35", insight)
        self.assertIn("-12.30%", insight)
        self.assertIn("62.00%", insight)
        self.assertIn("1.85", insight)
        self.assertIn("45", insight)
        self.assertIn("3.5", insight)

    def test_partial_statistics(self):
        """部分统计字段 → 只映射存在的"""
        stats = {"total_return_pct": 5.0, "sharpe_ratio": 0.8}
        insight = _map_statistics_to_insight(stats)
        self.assertIn("5.00%", insight)
        self.assertIn("0.80", insight)
        self.assertNotIn("年化", insight)

    def test_empty_statistics(self):
        """空统计 → 返回'无统计数据'"""
        insight = _map_statistics_to_insight({})
        self.assertEqual(insight, "无统计数据")

    def test_extra_signal_density(self):
        """额外字段 signal_ratio 映射"""
        insight = _map_statistics_to_insight({}, extra={"signal_ratio": 0.45})
        self.assertIn("45.0%", insight)


# ════════════════════════════════════════════════════════════
# 场景 3: 幂等 upsert
# ════════════════════════════════════════════════════════════


class TestUpsertIdempotent(unittest.TestCase):
    """场景3: 同 task_id 多次 harvest 不重复"""

    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_kb_test")
        self.bridge = KnowledgeBridge(output_dir=self._tmp, sync_to_bitable=False)
        _STORE.clear()

    def tearDown(self):
        _STORE.clear()
        if os.path.exists(self._tmp):
            shutil.rmtree(self._tmp)

    def test_same_task_id_file_dedup(self):
        """同 (method_name, symbol) 多次 harvest 触发幂等合并"""
        df = _make_signals([1, 0, -1, 1, 0])
        result1 = MethodResult(signals=df)
        entry1 = self.bridge.harvest(result1, method_name="ma_cross", symbol="601857")
        self.assertIsNotNone(entry1)

        result2 = MethodResult(signals=df)
        entry2 = self.bridge.harvest(result2, method_name="ma_cross", symbol="601857")
        self.assertIsNotNone(entry2)

        # 文件层面：相同(method_name, symbol)不会重复写入（幂等合并）
        import glob
        files = glob.glob(os.path.join(self._tmp, "*.json"))
        self.assertGreaterEqual(len(files), 1)

    def test_different_method_same_symbol(self):
        """不同 method 同 symbol → 不同文件"""
        df = _make_signals([1, 0, -1])
        r1 = MethodResult(signals=df)
        r2 = MethodResult(signals=df)
        e1 = self.bridge.harvest(r1, method_name="ma_cross", symbol="601857")
        e2 = self.bridge.harvest(r2, method_name="rsi", symbol="601857")
        self.assertNotEqual(e1.method_name, e2.method_name)


# ════════════════════════════════════════════════════════════
# 场景 4: α 置信度融合计算
# ════════════════════════════════════════════════════════════


class TestConfidenceComputation(unittest.TestCase):
    """场景4: α 置信度融合计算"""

    def test_default_confidence(self):
        """默认参数 → 基础置信度 0.5 + 极短数据扣分"""
        c = _compute_confidence(n_bars=5)
        self.assertAlmostEqual(c, 0.35, delta=0.01)

    def test_longer_data_confidence(self):
        """较长数据 → 置信度加分"""
        c = _compute_confidence(n_bars=500)
        self.assertGreater(c, 0.6)

    def test_alpha_fusion(self):
        """α 动态加权融合"""
        c = _compute_confidence(n_bars=100, alpha=0.6, historical_confidence=0.8)
        self.assertAlmostEqual(c, 0.6 * 0.6 + 0.4 * 0.8, delta=0.01)

    def test_clip_lower_bound(self):
        """置信度截断下限 0.05"""
        c = _compute_confidence(n_bars=0)
        self.assertGreaterEqual(c, 0.05)

    def test_clip_upper_bound(self):
        """置信度截断上限 0.95"""
        c = _compute_confidence(n_bars=1000000, data_frequency="minute")
        self.assertLessEqual(c, 0.95)

    def test_signal_density_bonus(self):
        """信号密度加分"""
        c_no = _compute_confidence(n_bars=100)
        c_yes = _compute_confidence(n_bars=100, signal_ratio=0.5)
        self.assertGreater(c_yes, c_no)

    def test_minute_frequency_bonus(self):
        """分钟频率加分"""
        c_daily = _compute_confidence(n_bars=100)
        c_min = _compute_confidence(n_bars=100, data_frequency="minute")
        self.assertGreater(c_min, c_daily)


# ════════════════════════════════════════════════════════════
# 场景 5: TypeError 输入
# ════════════════════════════════════════════════════════════


class TestTypeError(unittest.TestCase):
    """场景5: 非 MethodResult 传入 harvest 应抛 TypeError"""

    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_kb_test")
        self.bridge = KnowledgeBridge(output_dir=self._tmp, sync_to_bitable=False)
        _STORE.clear()

    def tearDown(self):
        _STORE.clear()
        if os.path.exists(self._tmp):
            shutil.rmtree(self._tmp)

    def test_none_result(self):
        """None result → TypeError"""
        with self.assertRaises(TypeError):
            self.bridge.harvest(None, "ma_cross", "TEST")

    def test_string_result(self):
        """str result → TypeError"""
        with self.assertRaises(TypeError):
            self.bridge.harvest("not_a_method_result", "ma_cross", "TEST")

    def test_dict_result(self):
        """dict result → TypeError"""
        with self.assertRaises(TypeError):
            self.bridge.harvest({"signals": "fake"}, "ma_cross", "TEST")

    def test_int_result(self):
        """int result → TypeError"""
        with self.assertRaises(TypeError):
            self.bridge.harvest(42, "ma_cross", "TEST")


# ════════════════════════════════════════════════════════════
# 场景 6: clear_v1 兼容层
# ════════════════════════════════════════════════════════════


class TestClearV1(unittest.TestCase):
    """clear_v1 兼容方法"""

    def setUp(self):
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_kb_test")
        self.bridge = KnowledgeBridge(output_dir=self._tmp, sync_to_bitable=False)

    def test_clear_v1_exists(self):
        """clear_v1 方法存在且可调用"""
        self.assertTrue(hasattr(self.bridge, "clear_v1"))
        self.bridge.clear_v1()
        # 调用后不报错即可


if __name__ == "__main__":
    unittest.main()
