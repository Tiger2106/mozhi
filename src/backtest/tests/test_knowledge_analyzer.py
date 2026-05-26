"""
test_knowledge_analyzer.py — KnowledgeAnalyzer 单元测试

Phase 3 覆盖场景（墨衡编写，墨涵知识审查）：
  1.  test_parameter_stability_single     — 单一参数稳定性
  2.  test_parameter_stability_multiple   — 多值参数对比
  3.  test_strategy_similarity            — 策略相似度
  4.  test_cluster                        — 策略聚类
  5.  test_regime_analysis_bull           — 牛市状态分析
  6.  test_regime_analysis_sideways       — 震荡状态
  7.  test_top_performers                 — 最佳表现
  8.  test_correlation                    — 相关性矩阵
  9.  test_generate_report                — 报告生成（检查不含 AI 关键词）
  10. test_empty_data                     — 空数据处理
  11. test_single_entry                   — 单条目边界
  12. test_stability_edge_case            — 稳定性边界（std=0）

所有测试使用模拟数据，不依赖真实 knowledge_entries 文件。

作者: 墨衡
创建时间: 2026-05-17
"""

import sys
import os
import json
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.backtest.engine.knowledge_entry import KnowledgeEntry
from src.backtest.engine.knowledge_analyzer import KnowledgeAnalyzer


# ─── 辅助工厂 ──────────────────────────────────────────────


def _make_entry(
    task_id: str = "ana_{now}",
    method_name: str = "ma_cross",
    symbol: str = "601857",
    regime: str = "unknown",
    timeframe: str = "",
    tags: list[str] | None = None,
    quality_score: float = 0.7,
    total_return: float | None = 5.0,
    sharpe: float | None = 1.2,
    max_drawdown: float | None = -3.0,
    win_rate: float | None = 55.0,
    confidence: float = 0.6,
    insight_summary: str = "",
    insight_category: str = "",
    parameters: dict | None = None,
    statistics: dict | None = None,
    normalized_params: dict | None = None,
) -> KnowledgeEntry:
    """创建 KnowledgeEntry 的快捷工厂方法。"""
    from datetime import datetime

    ts = datetime.now().strftime("%H%M%S%f")
    return KnowledgeEntry(
        task_id=task_id.format(now=ts),
        method_name=method_name,
        symbol=symbol,
        completed_time=datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        regime=regime,
        timeframe=timeframe,
        tags=tags or [],
        quality_score=quality_score,
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        confidence=confidence,
        insight_summary=insight_summary,
        insight_category=insight_category,
        parameters=parameters or {},
        statistics=statistics or {},
        normalized_params=normalized_params or {},
    )


def _build_analyzer(entries: list[KnowledgeEntry]) -> KnowledgeAnalyzer:
    """用给定条目列表构建 KnowledgeAnalyzer（利用 tempfile 写入 JSON）。"""
    import dataclasses
    tmpdir = tempfile.mkdtemp()
    for i, entry in enumerate(entries):
        fpath = os.path.join(tmpdir, f"entry_{i}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(entry), f, ensure_ascii=False)

    ka = KnowledgeAnalyzer(data_dir=tmpdir)
    return ka


def _build_analyzer_from_dicts(data_list: list[dict]) -> KnowledgeAnalyzer:
    """用 dict 列表构建 KnowledgeAnalyzer。"""
    tmpdir = tempfile.mkdtemp()
    for i, data in enumerate(data_list):
        fpath = os.path.join(tmpdir, f"entry_{i}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return KnowledgeAnalyzer(data_dir=tmpdir)


# ════════════════════════════════════════════════════════════
# 测试类
# ════════════════════════════════════════════════════════════


class TestKnowledgeAnalyzer(unittest.TestCase):
    """KnowledgeAnalyzer 核心功能测试。"""

    # ─── 1. 单一参数稳定性 ──────────────────────────────────

    def test_parameter_stability_single(self):
        """单一参数稳定性分析。

        用一个方法+一个参数键的多条记录测试稳定性评分。
        """
        entries = [
            _make_entry(
                task_id="t1", method_name="ma_cross",
                total_return=5.0, sharpe=1.2, win_rate=60.0,
                parameters={"ma_fast": 5, "ma_slow": 20},
                normalized_params={"strategy_type": "trend_following"},
            ),
            _make_entry(
                task_id="t2", method_name="ma_cross",
                total_return=6.0, sharpe=1.5, win_rate=65.0,
                parameters={"ma_fast": 10, "ma_slow": 20},
                normalized_params={"strategy_type": "trend_following"},
            ),
            _make_entry(
                task_id="t3", method_name="ma_cross",
                total_return=7.0, sharpe=1.8, win_rate=70.0,
                parameters={"ma_fast": 20, "ma_slow": 20},
                normalized_params={"strategy_type": "trend_following"},
            ),
        ]
        ka = _build_analyzer(entries)
        result = ka.parameter_stability("ma_cross", "ma_fast")

        self.assertEqual(result["method_name"], "ma_cross")
        self.assertEqual(result["param_key"], "ma_fast")
        self.assertEqual(sorted(result["values"]), [5, 10, 20])
        self.assertIn("total_return", result["metrics"])
        self.assertIn("sharpe", result["metrics"])
        self.assertIn("win_rate", result["metrics"])
        self.assertGreaterEqual(result["stability_score"], 0.0)
        self.assertLessEqual(result["stability_score"], 1.0)
        self.assertIsNotNone(result["best_value"])
        self.assertTrue(len(result["recommendation"]) > 0)

    # ─── 2. 多值参数对比 ────────────────────────────────────

    def test_parameter_stability_multiple(self):
        """多值参数对比：通过多个不同参数值验证稳定性评分的区分度。"""
        entries = []
        # 返回与 ma_fast 值正相关：稳定性应较高（单调性）
        for fast in [5, 10, 20, 30]:
            entries.append(
                _make_entry(
                    task_id=f"t{fast}",
                    method_name="ma_cross",
                    total_return=float(fast * 0.5),
                    sharpe=float(fast * 0.1),
                    win_rate=float(50 + fast),
                    parameters={"ma_fast": fast, "ma_slow": 20},
                )
            )
        # 添加一个离群点
        entries.append(
            _make_entry(
                task_id="toutlier",
                method_name="ma_cross",
                total_return=0.5,
                sharpe=0.1,
                win_rate=30.0,
                parameters={"ma_fast": 50, "ma_slow": 20},
            )
        )

        ka = _build_analyzer(entries)
        result = ka.parameter_stability("ma_cross", "ma_fast")

        self.assertEqual(len(result["values"]), 5)
        self.assertEqual(len(result["metrics"]["total_return"]), 5)
        # 即使有离群点，稳定性也应在合理范围
        self.assertGreaterEqual(result["stability_score"], 0.0)
        self.assertIn(result["best_value"], [5, 10, 20, 30, 50])

    # ─── 3. 策略相似度 ──────────────────────────────────────

    def test_strategy_similarity(self):
        """策略相似度分析。"""
        entries = [
            _make_entry(
                task_id="t1", method_name="ma_cross",
                total_return=5.0, sharpe=1.2,
                parameters={"ma_fast": 5, "ma_slow": 20},
                normalized_params={"strategy_type": "trend_following"},
            ),
            _make_entry(
                task_id="t2", method_name="ma_cross",
                total_return=6.0, sharpe=1.5,
                parameters={"ma_fast": 10, "ma_slow": 30},
                normalized_params={"strategy_type": "trend_following"},
            ),
            _make_entry(
                task_id="t3", method_name="bollinger",
                total_return=3.0, sharpe=0.8,
                parameters={"period": 20, "std_dev": 2.0},
                normalized_params={"strategy_type": "mean_reversion"},
            ),
        ]
        ka = _build_analyzer(entries)
        result = ka.strategy_similarity("ma_cross", "bollinger")

        self.assertEqual(result["method_a"], "ma_cross")
        self.assertEqual(result["method_b"], "bollinger")
        self.assertGreaterEqual(result["n_a"], 1)
        self.assertGreaterEqual(result["n_b"], 1)
        self.assertIn("param_overlap", result)
        self.assertIn("performance_correlation", result)
        self.assertIn("overall_similarity", result)
        self.assertIn("interpretation", result)
        # 两种不同策略的相似度应在合理范围
        self.assertGreaterEqual(result["overall_similarity"], 0.0)
        self.assertLessEqual(result["overall_similarity"], 1.0)

    # ─── 4. 策略聚类 ────────────────────────────────────────

    def test_cluster(self):
        """策略聚类。"""
        entries = [
            # 同一类簇的两个方法（trend_following + ma_cross 和 macd 可能类似）
            _make_entry(
                task_id="t1", method_name="ma_cross",
                total_return=5.0, sharpe=1.2,
                parameters={"ma_fast": 5, "ma_slow": 20},
                normalized_params={"strategy_type": "trend_following"},
            ),
            _make_entry(
                task_id="t2", method_name="bollinger",
                total_return=3.0, sharpe=0.8,
                parameters={"period": 20, "std_dev": 2.0},
                normalized_params={"strategy_type": "mean_reversion"},
            ),
            _make_entry(
                task_id="t3", method_name="grid",
                total_return=4.0, sharpe=1.0,
                parameters={"levels": 10, "grid_spacing": 0.5},
                normalized_params={"strategy_type": "grid"},
            ),
        ]
        ka = _build_analyzer(entries)
        clusters = ka.cluster_strategies(min_similarity=0.6)

        self.assertIsInstance(clusters, list)
        # 条目中各方法应全部出现在聚类结果中
        all_methods = set()
        for c in clusters:
            all_methods.update(c["methods"])
        for m in ["ma_cross", "bollinger", "grid"]:
            self.assertIn(m, all_methods)
        # 至少应有一个簇
        self.assertGreaterEqual(len(clusters), 1)
        for c in clusters:
            self.assertIn("cluster_id", c)
            self.assertIn("methods", c)
            self.assertIn("avg_similarity", c)
            self.assertIn("n_members", c)

    # ─── 5. 牛市状态分析 ────────────────────────────────────

    def test_regime_analysis_bull(self):
        """牛市（bull）状态分析。"""
        entries = [
            _make_entry(
                task_id="t1", method_name="ma_cross", regime="bull",
                total_return=12.0, sharpe=2.0, win_rate=70.0,
            ),
            _make_entry(
                task_id="t2", method_name="ma_cross", regime="bull",
                total_return=15.0, sharpe=2.2, win_rate=75.0,
            ),
            _make_entry(
                task_id="t3", method_name="grid", regime="bull",
                total_return=8.0, sharpe=1.5, win_rate=60.0,
            ),
        ]
        ka = _build_analyzer(entries)
        result = ka.regime_analysis()

        self.assertIn("regimes", result)
        self.assertIn("bull", result["regimes"])
        self.assertIn("methods", result)
        self.assertIn("ma_cross", result["matrix"])
        self.assertIn("grid", result["matrix"])
        # ma_cross 在 bull 下应该有统计信息
        self.assertIn("bull", result["matrix"]["ma_cross"])
        self.assertEqual(result["matrix"]["ma_cross"]["bull"]["count"], 2)
        self.assertIsNotNone(result["best_combination"])
        self.assertEqual(result["best_combination"]["regime"], "bull")

    # ─── 6. 震荡状态 ────────────────────────────────────────

    def test_regime_analysis_sideways(self):
        """震荡（sideways）状态分析。"""
        entries = [
            _make_entry(
                task_id="t1", method_name="bollinger", regime="sideways",
                total_return=6.0, sharpe=1.8, win_rate=65.0,
            ),
            _make_entry(
                task_id="t2", method_name="grid", regime="sideways",
                total_return=4.5, sharpe=1.2, win_rate=55.0,
            ),
            _make_entry(
                task_id="t3", method_name="bollinger", regime="bull",
                total_return=3.0, sharpe=0.8, win_rate=50.0,
            ),
        ]
        ka = _build_analyzer(entries)
        result = ka.regime_analysis()

        self.assertIn("sideways", result["regimes"])
        self.assertIn("bollinger", result["matrix"])
        self.assertIn("grid", result["matrix"])
        if "sideways" in result["matrix"]["bollinger"]:
            self.assertIn("avg_return", result["matrix"]["bollinger"]["sideways"])
        if "sideways" in result["matrix"]["grid"]:
            self.assertIn("avg_return", result["matrix"]["grid"]["sideways"])

    # ─── 7. Top 表现者 ──────────────────────────────────────

    def test_top_performers(self):
        """最佳表现组合。"""
        entries = [
            _make_entry(
                task_id=f"t{i}", method_name="ma_cross",
                regime="bull", sharpe=1.0 + i * 0.5,
                total_return=5.0 + i * 3.0,
                parameters={"ma_fast": 5, "ma_slow": 20},
            )
            for i in range(5)
        ]
        ka = _build_analyzer(entries)

        # 按 sharpe 排序
        top_sharpe = ka.top_performers(metric="sharpe", top_k=3)
        self.assertEqual(len(top_sharpe), 3)
        self.assertEqual(top_sharpe[0]["rank"], 1)
        self.assertGreater(top_sharpe[0].get("sharpe", 0), top_sharpe[1].get("sharpe", 0))
        self.assertEqual(top_sharpe[0]["method_name"], "ma_cross")
        self.assertIn("parameters", top_sharpe[0])
        self.assertIn("task_id", top_sharpe[0])

        # 按 total_return 排序
        top_return = ka.top_performers(metric="total_return", top_k=2)
        self.assertEqual(len(top_return), 2)
        self.assertGreater(top_return[0].get("total_return", 0), top_return[1].get("total_return", 0))

        # 测试无效指标
        with self.assertRaises(ValueError):
            ka.top_performers(metric="invalid_metric")

    # ─── 8. 相关性矩阵 ──────────────────────────────────────

    def test_correlation(self):
        """相关性矩阵。"""
        entries = [
            _make_entry(
                task_id=f"t{i}", method_name="ma_cross",
                total_return=5.0 + i * 2.0,
                sharpe=1.0 + i * 0.3,
                max_drawdown=-2.0 - i * 0.5,
                win_rate=55.0 + i * 5.0,
            )
            for i in range(10)
        ]
        ka = _build_analyzer(entries)
        result = ka.correlation_matrix(method="pearson")

        self.assertEqual(result["method"], "pearson")
        self.assertEqual(result["metrics"], ["total_return", "sharpe", "max_drawdown", "win_rate"])
        # 自身相关应为 1.0
        for m in result["metrics"]:
            self.assertEqual(result["matrix"][m][m], 1.0)
        # total_return 与 sharpe 应正相关（数据构造如此）
        self.assertGreater(result["matrix"]["total_return"]["sharpe"], 0)

        # spearman
        result_s = ka.correlation_matrix(method="spearman")
        self.assertEqual(result_s["method"], "spearman")
        self.assertEqual(result_s["metrics"], ["total_return", "sharpe", "max_drawdown", "win_rate"])
        for m in result_s["metrics"]:
            self.assertEqual(result_s["matrix"][m][m], 1.0)

        # 无效方法
        with self.assertRaises(ValueError):
            ka.correlation_matrix(method="kendall")

    # ─── 9. 报告生成 ────────────────────────────────────────

    def test_generate_report(self):
        """报告生成（检查不含 AI/LLM 关键词）。"""
        entries = [
            _make_entry(
                task_id="t1", method_name="ma_cross", regime="bull",
                total_return=12.0, sharpe=2.0, win_rate=70.0,
                parameters={"ma_fast": 5, "ma_slow": 20},
            ),
            _make_entry(
                task_id="t2", method_name="bollinger", regime="sideways",
                total_return=6.0, sharpe=1.5, win_rate=60.0,
                parameters={"period": 20, "std_dev": 2.0},
            ),
            _make_entry(
                task_id="t3", method_name="grid", regime="volatile",
                total_return=4.0, sharpe=1.0, win_rate=50.0,
                parameters={"levels": 10, "grid_spacing": 0.5},
            ),
        ]
        ka = _build_analyzer(entries)
        report = ka.generate_summary_report()

        # 报告应包含核心章节
        self.assertIn("知识库分析报告", report)
        self.assertIn("基本统计", report)
        self.assertIn("最佳表现者", report)
        self.assertIn("市场状态分析", report)
        self.assertIn("参数稳定性", report)
        self.assertIn("指标相关性", report)
        self.assertIn("聚类概述", report)

        # 应包含条目总数
        self.assertIn("条目总数: 3", report)

        # ⚠️ 关键检查：不应包含 AI/LLM 关键词
        forbidden_keywords = ["AI", "llm", "LLM", "人工智能", "生成式", "大模型", "神经网络", "深度学习"]
        for keyword in forbidden_keywords:
            with self.subTest(keyword=keyword):
                self.assertNotIn(keyword, report,
                                 f"报告不应包含关键词 '{keyword}'，但实际包含")

        # 空数据报告
        ka_empty = _build_analyzer([])
        empty_report = ka_empty.generate_summary_report()
        self.assertIn("知识库为空", empty_report)

    # ─── 10. 空数据 ─────────────────────────────────────────

    def test_empty_data(self):
        """空数据处理。"""
        ka = _build_analyzer([])
        self.assertEqual(ka.count, 0)
        self.assertEqual(len(ka.entries), 0)

        # 空数据时各方法应优雅处理
        with self.assertRaises(ValueError):
            ka.parameter_stability("ma_cross", "ma_fast")

        similar = ka.strategy_similarity
        with self.assertRaises(ValueError):
            similar("ma_cross", "grid")

        clusters = ka.cluster_strategies()
        # 空数据时 cluster_strategies 也返回一个空成员簇
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["n_members"], 0)

        regime_result = ka.regime_analysis()
        self.assertEqual(regime_result["regimes"], [])
        self.assertEqual(regime_result["matrix"], {})

        top = ka.top_performers("sharpe", 5)
        self.assertEqual(top, [])

        corr = ka.correlation_matrix()
        self.assertEqual(corr["matrix"]["total_return"]["sharpe"], 0.0)

        report = ka.generate_summary_report()
        self.assertIn("知识库为空", report)

    # ─── 11. 单条目边界 ─────────────────────────────────────

    def test_single_entry(self):
        """单条目边界测试。"""
        entry = _make_entry(
            task_id="t1", method_name="ma_cross", regime="bull",
            total_return=5.0, sharpe=1.2,
            parameters={"ma_fast": 5, "ma_slow": 20},
        )
        ka = _build_analyzer([entry])
        self.assertEqual(ka.count, 1)

        # parameter_stability: 需要 > 1 条数据才能计算有意义的结果
        result = ka.parameter_stability("ma_cross", "ma_fast")
        # 只有一组参数值
        self.assertEqual(len(result["values"]), 1)
        self.assertEqual(result["stability_score"], 0.0)  # < 2 样本 → 0
        self.assertEqual(result["best_value"], 5)

        # strategy_similarity: 同方法名不同条目
        similar = ka.strategy_similarity("ma_cross", "ma_cross")
        self.assertEqual(similar["n_a"], 1)
        self.assertEqual(similar["n_b"], 1)
        self.assertGreaterEqual(similar["overall_similarity"], 0.0)

        # regime_analysis
        reg = ka.regime_analysis()
        self.assertIn("bull", reg["regimes"])
        self.assertEqual(reg["matrix"]["ma_cross"]["bull"]["count"], 1)

        # top_performers: 只有一条
        top = ka.top_performers("sharpe", 5)
        self.assertEqual(len(top), 1)

        # clustering: 只有一种方法
        clusters = ka.cluster_strategies()
        self.assertGreaterEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["n_members"], 1)

        # correlation: 单条目不足以计算有意义的相关系数
        corr = ka.correlation_matrix()
        for m in corr["metrics"]:
            self.assertEqual(corr["matrix"][m][m], 1.0)

    # ─── 12. 稳定性边界（std=0） ────────────────────────────

    def test_stability_edge_case(self):
        """稳定性边界：所有绩效值完全相同（std=0）。"""
        entries = [
            _make_entry(
                task_id=f"t{i}",
                method_name="ma_cross",
                total_return=5.0,
                sharpe=1.0,
                win_rate=60.0,
                parameters={"ma_fast": 5, "ma_slow": 20},
            )
            for i in range(3)
        ]
        # 全部使用相同的 ma_fast=5
        ka = _build_analyzer(entries)
        result = ka.parameter_stability("ma_cross", "ma_fast")

        # 只有一种参数值，单组无法计算标准差
        self.assertEqual(len(result["values"]), 1)  # 都相同值
        self.assertEqual(result["stability_score"], 0.0)  # < 2 种不同参数值

        # 另一种边界：两组不同参数值但绩效完全一致（std=0）
        entries2 = [
            _make_entry(
                task_id="t1", method_name="ma_cross",
                total_return=5.0, sharpe=1.0,
                parameters={"ma_fast": 5, "ma_slow": 20},
            ),
            _make_entry(
                task_id="t2", method_name="ma_cross",
                total_return=5.0, sharpe=1.0,
                parameters={"ma_fast": 10, "ma_slow": 20},
            ),
        ]
        ka2 = _build_analyzer(entries2)
        result2 = ka2.parameter_stability("ma_cross", "ma_fast")

        self.assertEqual(len(result2["values"]), 2)
        # std = 0，stability_score = 1.0
        self.assertEqual(result2["stability_score"], 1.0)

    # ─── 辅助测试：无效方法名 ──────────────────────────────

    def test_invalid_method_name(self):
        """无效方法名应抛出 ValueError。"""
        entry = _make_entry(
            task_id="t1", method_name="ma_cross",
            parameters={"ma_fast": 5},
        )
        ka = _build_analyzer([entry])

        with self.assertRaises(ValueError):
            ka.parameter_stability("nonexistent_method", "ma_fast")

        with self.assertRaises(ValueError):
            ka.parameter_stability("ma_cross", "nonexistent_param")


if __name__ == "__main__":
    unittest.main()
