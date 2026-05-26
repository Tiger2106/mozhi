"""
test_knowledge_normalizer.py — KnowledgeNormalizer 单元测试

Phase 1a 覆盖场景（墨衡编写，墨萱审查）：
  1. test_normalize_ma_cross        — trend_following 标准化与策略类型检测
  2. test_normalize_grid             — grid 参数映射（spacing + grid_levels）
  3. test_normalize_reversal         — 冷却器参数映射（cooling_bars）
  4. test_detect_regime_bull         — 低波动率 → bull
  5. test_detect_regime_volatile     — 高波动率 → volatile
  6. test_quality_score              — quality_score 自动计算
  7. test_generate_tags              — 标签自动生成（策略 + 技术因子 + 风格）
  8. test_empty_required_fields      — validate() 抛 ValueError
  9. test_validate_pass              — 全部通过
  10. test_unknown_method            — 未注册方法的 fallthrough 处理
  11. test_normalize_bollinger       — bollinger（mean_reversion 类）标准化
  12. test_normalize_wyckoff         — wyckoff（volume_based 类）标准化
"""

import sys
import os
import unittest

from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.engine.knowledge_entry import KnowledgeEntry
from backtest.engine.knowledge_normalizer import KnowledgeNormalizer


# ─── 辅助工厂 ──────────────────────────────────────────────


def _make_entry(
    task_id: str = "task_001",
    method_name: str = "ma_cross",
    symbol: str = "601857",
    parameters: dict | None = None,
    confidence: float = 0.5,
    **kwargs,
) -> KnowledgeEntry:
    """创建 KnowledgeEntry 的快捷工厂方法。"""
    return KnowledgeEntry(
        task_id=task_id,
        method_name=method_name,
        symbol=symbol,
        completed_time=datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        parameters=parameters or {},
        confidence=confidence,
        **kwargs,
    )


# ════════════════════════════════════════════════════════════
# TestKnowledgeNormalizer
# ════════════════════════════════════════════════════════════


class TestKnowledgeNormalizer(unittest.TestCase):
    """KnowledgeNormalizer 单元测试"""

    def setUp(self):
        self.normalizer = KnowledgeNormalizer()

    # ─── 场景 1: ma_cross 标准化 ──────────────────────────────

    def test_normalize_ma_cross(self):
        """ma_cross 方法 → 策略类型 trend_following，参数标准化"""
        entry = _make_entry(
            method_name="ma_cross",
            parameters={"period": 20, "ma_fast": 5, "ma_slow": 20},
        )
        result = self.normalizer.normalize(entry)

        # 策略类型
        self.assertEqual(
            result.normalized_params["strategy_type"], "trend_following"
        )
        # 参数映射：period 应被抽出
        self.assertEqual(result.normalized_params.get("period"), 20)
        # 原始 key 保留
        self.assertIn("ma_fast", result.normalized_params["_original_keys"])
        self.assertIn("ma_slow", result.normalized_params["_original_keys"])

    # ─── 场景 2: grid 参数映射 ────────────────────────────────

    def test_normalize_grid(self):
        """grid 方法 → 策略类型 grid，spacing 和 grid_levels 映射"""
        entry = _make_entry(
            method_name="grid",
            parameters={
                "grid_spacing": 0.5,
                "levels": 10,
                "n_levels": 10,
                "grid_type": "arithmetic",
            },
        )
        result = self.normalizer.normalize(entry)

        self.assertEqual(result.normalized_params["strategy_type"], "grid")
        self.assertEqual(result.normalized_params.get("spacing"), 0.5)
        self.assertEqual(result.normalized_params.get("grid_levels"), 10)

    # ─── 场景 3: reversal 冷却器参数映射 ───────────────────────

    def test_normalize_reversal(self):
        """reversal 方法 → 策略类型 mean_reversion，冷却参数映射"""
        entry = _make_entry(
            method_name="reversal",
            parameters={
                "cooling_bars": 5,
                "rsi_period": 14,
                "min_votes": 2,
            },
        )
        result = self.normalizer.normalize(entry)

        self.assertEqual(result.normalized_params["strategy_type"], "mean_reversion")
        self.assertEqual(result.normalized_params.get("cooling_bars"), 5)

    # ─── 场景 4: regime bull ───────────────────────────────────

    def test_detect_regime_bull(self):
        """低波动率 (vix=10) → bull"""
        regime = self.normalizer._detect_regime(10.0)
        self.assertEqual(regime, "bull")

        regime = self.normalizer._detect_regime(14.0)
        self.assertEqual(regime, "bull")

    # ─── 场景 5: regime volatile ───────────────────────────────

    def test_detect_regime_volatile(self):
        """高波动率 (vix=35) → volatile"""
        regime = self.normalizer._detect_regime(35.0)
        self.assertEqual(regime, "volatile")

        # 边界值
        regime = self.normalizer._detect_regime(30.1)
        self.assertEqual(regime, "volatile")

    # ─── 场景 6: quality_score ─────────────────────────────────

    def test_quality_score(self):
        """quality_score 基于参数和 confidence 自动计算"""
        entry = _make_entry(
            method_name="ma_cross",
            parameters={"period": 20, "ma_fast": 5, "ma_slow": 20},
            confidence=0.7,
            regime="bull",
            insight_summary="总收益率 15.20%; 夏普比率 1.25",
        )
        result = self.normalizer.normalize(entry)

        # 有参数 (0.5 + 0.1) + 不足5个参数 (不加) + regime (0.05)
        # + confidence*0.3 (0.21) + insight (0.03) = 0.89
        self.assertGreater(result.quality_score, 0.5)
        self.assertLessEqual(result.quality_score, 0.95)

    def test_quality_score_minimal(self):
        """最小输入 → quality_score 不低于底限"""
        entry = _make_entry(
            method_name="unknown_method",
            confidence=0.0,
        )
        result = self.normalizer.normalize(entry)

        # base=0.5, 无参数(+0), regime="unknown"(+0),
        # confidence*0.3=0.0, 无insight(+0) = 0.5
        self.assertGreaterEqual(result.quality_score, 0.05)
        # 至少默认 0.5
        self.assertAlmostEqual(result.quality_score, 0.5)

    # ─── 场景 7: 标签生成 ─────────────────────────────────────

    def test_generate_tags(self):
        """标签生成：策略 + 技术因子 + 风格"""
        entry = _make_entry(
            method_name="ma_cross",
            parameters={"ma_fast": 5, "ma_slow": 20},
        )
        result = self.normalizer.normalize(entry)

        tags = result.tags
        # 策略标签
        self.assertIn("trend", tags)
        # 技术因子
        self.assertIn("ma", tags)
        # 风格（ma_fast=5 ≤ 10 → short_term）
        self.assertIn("short_term", tags)

    def test_generate_tags_long_term(self):
        """长周期参数 → long_term 标签"""
        entry = _make_entry(
            method_name="bollinger",
            parameters={"period": 50},
        )
        result = self.normalizer.normalize(entry)

        self.assertIn("long_term", result.tags)

    # ─── 场景 8: validate 异常 ────────────────────────────────

    def test_empty_required_fields(self):
        """缺少必填字段 → validate() 抛出 ValueError"""

        # 空 task_id
        entry = _make_entry(task_id="")
        with self.assertRaises(ValueError) as ctx:
            entry.validate()
        self.assertIn("task_id", str(ctx.exception))

        # 空 method_name
        entry = _make_entry(method_name="")
        with self.assertRaises(ValueError) as ctx:
            entry.validate()
        self.assertIn("method_name", str(ctx.exception))

        # 空 symbol
        entry = _make_entry(symbol="")
        with self.assertRaises(ValueError) as ctx:
            entry.validate()
        self.assertIn("symbol", str(ctx.exception))

    # ─── 场景 9: validate 通过 ────────────────────────────────

    def test_validate_pass(self):
        """全部必填字段 → validate() 返回 True"""
        entry = _make_entry()
        self.assertTrue(entry.validate())

    # ─── 场景 10: 未知方法 fallthrough ─────────────────────────

    def test_unknown_method(self):
        """未在 STRATEGY_MAP 中注册的方法 → normalized_params 中含 strategy_type=unknown"""
        entry = _make_entry(
            method_name="custom_vwap_enhanced",
            parameters={"period": 20, "threshold": 0.5},
        )
        result = self.normalizer.normalize(entry)

        # 策略类型为 unknown
        self.assertEqual(result.normalized_params["strategy_type"], "unknown")
        # 不匹配任何 PARAM_MAP 规则，不应有额外标准化字段
        self.assertNotIn("period", result.normalized_params)
        # _original_keys 保留
        self.assertIn("period", result.normalized_params["_original_keys"])

    # ─── 场景 11: bollinger 标准化（mean_reversion）────────────

    def test_normalize_bollinger(self):
        """bollinger 方法 → 策略类型 mean_reversion（按 STRATEGY_MAP）"""
        entry = _make_entry(
            method_name="bollinger",
            parameters={"period": 20, "std_dev": 2.0},
        )
        result = self.normalizer.normalize(entry)

        self.assertEqual(result.normalized_params["strategy_type"], "mean_reversion")
        self.assertEqual(result.normalized_params.get("period"), 20)
        self.assertIn("period", result.normalized_params["_original_keys"])

    # ─── 场景 12: wyckoff 标准化（volume_based）────────────────

    def test_normalize_wyckoff(self):
        """wyckoff 方法 → 策略类型 volume_based，标签含 wyckoff"""
        entry = _make_entry(
            method_name="wyckoff",
            parameters={},
        )
        result = self.normalizer.normalize(entry)

        self.assertEqual(result.normalized_params["strategy_type"], "volume_based")
        self.assertIn("wyckoff", result.tags)


if __name__ == "__main__":
    unittest.main()
