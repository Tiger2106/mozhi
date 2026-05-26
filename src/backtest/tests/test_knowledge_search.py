"""
test_knowledge_search.py — KnowledgeSearch 单元测试

Phase 2 覆盖场景（墨衡编写，墨涵知识审查）：
  1.  test_search_by_tags_any          — 标签任意匹配（OR 逻辑）
  2.  test_search_by_tags_all          — 标签全部匹配（AND 逻辑）
  3.  test_filter_by_method            — 过滤 method_name
  4.  test_filter_by_symbol            — 过滤标的
  5.  test_filter_by_regime            — 过滤市场状态
  6.  test_filter_by_timeframe         — 过滤时间框架
  7.  test_search_text                 — 全文搜索（insight_summary）
  8.  test_sort_by_quality             — 按 quality_score 排序
  9.  test_sort_by_sharpe              — 按 sharpe 排序
  10. test_sort_by_return              — 按 total_return 排序
  11. test_combined_query              — 组合查询（标签+字段+关键词+排序+分页）
  12. test_date_range                  — 日期范围过滤
  13. test_limit_offset                — 分页
  14. test_get_statistics              — 知识库统计
  15. test_get_top_k                   — 排名
  16. test_filter_invalid_field        — 无效过滤字段抛异常
  17. test_sort_invalid_field           — 无效排序字段抛异常
  18. test_empty_search                — 空标签/空关键词/空数据
  19. test_combined_query_all_filters   — 全部过滤器同时生效
  20. test_reload_entries              — 重新加载
  21. test_describe_insight            — 用 test_search_text 验证 insight_summary 描述准确
"""

import sys
import os
import json
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.backtest.engine.knowledge_entry import KnowledgeEntry
from src.backtest.engine.knowledge_search import KnowledgeSearch


# ─── 辅助工厂 ──────────────────────────────────────────────


def _make_entry(
    task_id: str = "bt_{now}",
    method_name: str = "ma_cross",
    symbol: str = "601857",
    regime: str = "bull",
    timeframe: str = "1d",
    tags: list[str] | None = None,
    quality_score: float = 0.7,
    total_return: float | None = 12.5,
    sharpe: float | None = 1.8,
    max_drawdown: float | None = -5.2,
    win_rate: float | None = 65.0,
    confidence: float = 0.7,
    insight_summary: str = "",
    insight_category: str = "",
    completed_time: str = "",
) -> KnowledgeEntry:
    """创建 KnowledgeEntry 的快捷工厂方法。"""
    ts = datetime.now().strftime("%H%M%S%f")
    return KnowledgeEntry(
        task_id=task_id.format(now=ts),
        method_name=method_name,
        symbol=symbol,
        completed_time=completed_time or datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
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
    )


def _build_search(entries: list[KnowledgeEntry]) -> KnowledgeSearch:
    """用给定条目列表构建 KnowledgeSearch（利用 tempfile 写入 JSON）。"""
    tmpdir = tempfile.mkdtemp()
    for i, entry in enumerate(entries):
        fpath = os.path.join(tmpdir, f"entry_{i}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": entry.task_id,
                "method_name": entry.method_name,
                "symbol": entry.symbol,
                "completed_time": entry.completed_time,
                "regime": entry.regime,
                "timeframe": entry.timeframe,
                "tags": entry.tags,
                "source_run_id": "",
                "quality_score": entry.quality_score,
                "total_return": entry.total_return,
                "sharpe": entry.sharpe,
                "max_drawdown": entry.max_drawdown,
                "win_rate": entry.win_rate,
                "insight_summary": entry.insight_summary,
                "insight_category": entry.insight_category,
                "confidence": entry.confidence,
                "parameters": {},
                "statistics": {},
                "normalized_params": {},
                "schema_version": "2.0",
            }, f, ensure_ascii=False)
    ks = KnowledgeSearch(data_dir=tmpdir)
    return ks


# ════════════════════════════════════════════════════════════
# TestKnowledgeSearch
# ════════════════════════════════════════════════════════════


class TestKnowledgeSearch(unittest.TestCase):
    """KnowledgeSearch 单元测试"""

    def setUp(self):
        """构建 15 个不同标签/字段/指标值的知识条目。"""
        self.entries = [
            # 0: ma_cross, 601857, bull, 1d, trend+ma
            _make_entry(
                task_id="bt_e0",
                method_name="ma_cross",
                symbol="601857",
                regime="bull",
                timeframe="1d",
                tags=["trend", "ma", "long_only"],
                quality_score=0.8,
                total_return=12.5,
                sharpe=1.8,
                max_drawdown=-5.2,
                win_rate=65.0,
                confidence=0.7,
                insight_summary="MA金叉信号在上升趋势中胜率较高.",
                completed_time="2025-06-01T09:00:00+08:00",
            ),
            # 1: ma_cross, 000001, bull, 1d, trend+ma
            _make_entry(
                task_id="bt_e1",
                method_name="ma_cross",
                symbol="000001",
                regime="bull",
                timeframe="1d",
                tags=["trend", "ma"],
                quality_score=0.75,
                total_return=8.3,
                sharpe=1.5,
                max_drawdown=-3.8,
                win_rate=60.0,
                confidence=0.6,
                insight_summary="均线交叉策略在牛市表现良好.",
                completed_time="2025-06-15T09:00:00+08:00",
            ),
            # 2: grid, 601857, sideways, 1d, grid
            _make_entry(
                task_id="bt_e2",
                method_name="grid",
                symbol="601857",
                regime="sideways",
                timeframe="1d",
                tags=["grid", "mean_reversion"],
                quality_score=0.65,
                total_return=5.2,
                sharpe=0.9,
                max_drawdown=-2.1,
                win_rate=55.0,
                confidence=0.5,
                insight_summary="网格策略在震荡市中表现稳健.",
                completed_time="2025-07-01T09:00:00+08:00",
            ),
            # 3: rsi, 600519, volatile, 4h, mean_reversion+rsi
            _make_entry(
                task_id="bt_e3",
                method_name="rsi",
                symbol="600519",
                regime="volatile",
                timeframe="4h",
                tags=["mean_reversion", "rsi", "short_term"],
                quality_score=0.55,
                total_return=3.5,
                sharpe=0.6,
                max_drawdown=-4.5,
                win_rate=52.0,
                confidence=0.4,
                insight_summary="RSI 超买超卖策略在波动市中有效.",
                completed_time="2025-07-15T09:00:00+08:00",
            ),
            # 4: reversal, 002415, bear, 1d, mean_reversion
            _make_entry(
                task_id="bt_e4",
                method_name="reversal",
                symbol="002415",
                regime="bear",
                timeframe="1d",
                tags=["mean_reversion", "swing"],
                quality_score=0.45,
                total_return=-2.1,
                sharpe=-0.3,
                max_drawdown=-8.5,
                win_rate=40.0,
                confidence=0.3,
                insight_summary="反转策略在熊市中表现不佳.",
                completed_time="2025-08-01T09:00:00+08:00",
            ),
            # 5: bollinger, 300750, volatile, 1h, trend+bollinger
            _make_entry(
                task_id="bt_e5",
                method_name="bollinger",
                symbol="300750",
                regime="volatile",
                timeframe="1h",
                tags=["trend", "bollinger", "short_term"],
                quality_score=0.7,
                total_return=9.8,
                sharpe=1.2,
                max_drawdown=-3.5,
                win_rate=58.0,
                confidence=0.6,
                insight_summary="布林带策略在波动率扩大时表现突出.",
                completed_time="2025-08-15T09:00:00+08:00",
            ),
            # 6: macd, 601857, bull, 1d, trend+macd
            _make_entry(
                task_id="bt_e6",
                method_name="macd",
                symbol="601857",
                regime="bull",
                timeframe="1d",
                tags=["trend", "macd", "long_only"],
                quality_score=0.85,
                total_return=15.8,
                sharpe=2.1,
                max_drawdown=-4.8,
                win_rate=68.0,
                confidence=0.8,
                insight_summary="MACD指标在上升趋势中胜率最高.",
                completed_time="2025-09-01T09:00:00+08:00",
            ),
            # 7: vwap, 000001, sideways, 15m, volume_based
            _make_entry(
                task_id="bt_e7",
                method_name="vwap",
                symbol="000001",
                regime="sideways",
                timeframe="15m",
                tags=["vwap", "volume_based", "short_term"],
                quality_score=0.4,
                total_return=1.2,
                sharpe=0.3,
                max_drawdown=-1.5,
                win_rate=51.0,
                confidence=0.35,
                insight_summary="VWAP策略在盘整市的获利空间有限.",
                completed_time="2025-09-15T09:00:00+08:00",
            ),
            # 8: ma_cross, 601857, sideways, 4h, trend+ma (different regime)
            _make_entry(
                task_id="bt_e8",
                method_name="ma_cross",
                symbol="601857",
                regime="sideways",
                timeframe="4h",
                tags=["trend", "ma"],
                quality_score=0.6,
                total_return=4.5,
                sharpe=0.8,
                max_drawdown=-2.8,
                win_rate=53.0,
                confidence=0.5,
                insight_summary="震荡市中均线交叉信号表现一般.",
                completed_time="2025-10-01T09:00:00+08:00",
            ),
            # 9: grid, 600519, sideways, 1d, grid+mean_reversion
            _make_entry(
                task_id="bt_e9",
                method_name="grid",
                symbol="600519",
                regime="sideways",
                timeframe="1d",
                tags=["grid", "mean_reversion", "swing"],
                quality_score=0.7,
                total_return=6.5,
                sharpe=1.1,
                max_drawdown=-2.0,
                win_rate=57.0,
                confidence=0.55,
                insight_summary="网格策略在白酒股震荡区间表现稳定.",
                completed_time="2025-10-15T09:00:00+08:00",
            ),
            # 10: rsi, 300750, bear, 1d, mean_reversion+rsi
            _make_entry(
                task_id="bt_e10",
                method_name="rsi",
                symbol="300750",
                regime="bear",
                timeframe="1d",
                tags=["mean_reversion", "rsi", "swing"],
                quality_score=0.35,
                total_return=-5.5,
                sharpe=-0.8,
                max_drawdown=-12.0,
                win_rate=35.0,
                confidence=0.25,
                insight_summary="RSI抄底策略在持续下跌趋势中面临巨大回撤.",
                completed_time="2025-11-01T09:00:00+08:00",
            ),
            # 11: reversal, 601857, bull, 1h, mean_reversion
            _make_entry(
                task_id="bt_e11",
                method_name="reversal",
                symbol="601857",
                regime="bull",
                timeframe="1h",
                tags=["mean_reversion", "short_term"],
                quality_score=0.5,
                total_return=2.8,
                sharpe=0.5,
                max_drawdown=-1.8,
                win_rate=48.0,
                confidence=0.4,
                insight_summary="牛市中的小级别反转信号收益有限.",
                completed_time="2025-11-15T09:00:00+08:00",
            ),
            # 12: macd, 002415, volatile, 4h, trend+macd
            _make_entry(
                task_id="bt_e12",
                method_name="macd",
                symbol="002415",
                regime="volatile",
                timeframe="4h",
                tags=["trend", "macd", "short_term"],
                quality_score=0.6,
                total_return=7.2,
                sharpe=1.0,
                max_drawdown=-4.0,
                win_rate=55.0,
                confidence=0.5,
                insight_summary="MACD在波动市中的信号需要综合成交量确认.",
                completed_time="2025-12-01T09:00:00+08:00",
            ),
            # 13: bollinger, 000001, bull, 1d, trend+bollinger
            _make_entry(
                task_id="bt_e13",
                method_name="bollinger",
                symbol="000001",
                regime="bull",
                timeframe="1d",
                tags=["trend", "bollinger", "long_only"],
                quality_score=0.78,
                total_return=10.2,
                sharpe=1.6,
                max_drawdown=-3.2,
                win_rate=62.0,
                confidence=0.65,
                insight_summary="布林带中轨在上升趋势中提供有效支撑.",
                completed_time="2025-12-15T09:00:00+08:00",
            ),
            # 14: ma_cross, 600519, bull, 1d, trend+ma+long_only
            _make_entry(
                task_id="bt_e14",
                method_name="ma_cross",
                symbol="600519",
                regime="bull",
                timeframe="1d",
                tags=["trend", "ma", "long_only"],
                quality_score=0.82,
                total_return=14.0,
                sharpe=1.9,
                max_drawdown=-4.5,
                win_rate=66.0,
                confidence=0.75,
                insight_summary="MA金叉在茅台牛市趋势跟踪策略中表现优异.",
                completed_time="2026-01-01T09:00:00+08:00",
            ),
        ]
        self.ks = _build_search(self.entries)

    # ─── 1. 标签任意匹配 ───────────────────────────────────

    def test_search_by_tags_any(self):
        """标签任意匹配（OR 逻辑）：搜索 trend 或 grid 标签"""
        results = self.ks.search_by_tags(["trend"], mode="any")
        # trend 标签的条目：0,1,5,6,8,12,13,14 = 8 条
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("trend", r.tags)

        # 搜索 grid 或 rsi（两条独立的标签）
        results = self.ks.search_by_tags(["grid", "rsi"], mode="any")
        # grid: 2,9；rsi: 3,10 → 4 条
        self.assertEqual(len(results), 4)
        for r in results:
            found = "grid" in r.tags or "rsi" in r.tags
            self.assertTrue(found)

    # ─── 2. 标签全部匹配 ───────────────────────────────────

    def test_search_by_tags_all(self):
        """标签全部匹配（AND 逻辑）"""
        results = self.ks.search_by_tags(["trend", "ma"], mode="all")
        # trend+ma: 0,1,8,14 → 4 条
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIn("trend", r.tags)
            self.assertIn("ma", r.tags)

        # trend+macd: 6,12 → 2 条
        results = self.ks.search_by_tags(["trend", "macd"], mode="all")
        self.assertEqual(len(results), 2)

    # ─── 3. 过滤 method_name ──────────────────────────────

    def test_filter_by_method(self):
        """按 method_name 精确过滤"""
        # ma_cross 条目: 0,1,8,14 → 4 条
        results = self.ks.filter_by_field("method_name", "ma_cross")
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertEqual(r.method_name, "ma_cross")

        # grid: 2,9 → 2 条
        results = self.ks.filter_by_field("method_name", "grid")
        self.assertEqual(len(results), 2)

        # 不存在的 method
        results = self.ks.filter_by_field("method_name", "nonexistent")
        self.assertEqual(len(results), 0)

    # ─── 4. 过滤 symbol ───────────────────────────────────

    def test_filter_by_symbol(self):
        """按标的精确过滤"""
        # 601857: 0,2,6,8,11 → 5 条
        results = self.ks.filter_by_field("symbol", "601857")
        self.assertEqual(len(results), 5)
        for r in results:
            self.assertEqual(r.symbol, "601857")

        # 000001: 1,7,13 → 3 条
        results = self.ks.filter_by_field("symbol", "000001")
        self.assertEqual(len(results), 3)

    # ─── 5. 过滤 regime ──────────────────────────────────

    def test_filter_by_regime(self):
        """按市场状态精确过滤"""
        # bull: 0,1,6,11,13,14 → 6 条
        results = self.ks.filter_by_field("regime", "bull")
        self.assertEqual(len(results), 6)
        for r in results:
            self.assertEqual(r.regime, "bull")

        # volatile: 3,5,12 → 3 条
        results = self.ks.filter_by_field("regime", "volatile")
        self.assertEqual(len(results), 3)

    # ─── 6. 过滤 timeframe ──────────────────────────────

    def test_filter_by_timeframe(self):
        """按时间框架精确过滤"""
        # 1d: 0,1,2,4,6,9,10,13,14 → 9 条
        results = self.ks.filter_by_field("timeframe", "1d")
        self.assertEqual(len(results), 9)
        for r in results:
            self.assertEqual(r.timeframe, "1d")

        # 4h: 3,8,12 → 3 条
        results = self.ks.filter_by_field("timeframe", "4h")
        self.assertEqual(len(results), 3)

    # ─── 7. 全文搜索 ─────────────────────────────────────

    def test_search_text(self):
        """全文搜索 insight_summary 关键词"""
        # "金叉" → 条目0,14
        results = self.ks.search_text("金叉")
        self.assertGreaterEqual(len(results), 2)
        for r in results:
            self.assertIn("金叉", r.insight_summary)

        # "网格" → 条目2,9
        results = self.ks.search_text("网格")
        self.assertGreaterEqual(len(results), 2)
        for r in results:
            self.assertIn("网格", r.insight_summary)

        # 不存在的关键词
        results = self.ks.search_text("不存在关键词xxxx")
        self.assertEqual(len(results), 0)

    # ─── 8. 按 quality_score 排序 ────────────────────────

    def test_sort_by_quality(self):
        """按 quality_score 降序排列"""
        sorted_entries = self.ks.sort_by(self.ks.entries, "quality_score")
        self.assertEqual(len(sorted_entries), 15)
        prev = float("inf")
        for e in sorted_entries:
            self.assertLessEqual(e.quality_score, prev)
            prev = e.quality_score
        # 第一名是条目6 (0.85)
        self.assertEqual(sorted_entries[0].task_id, "bt_e6")

    # ─── 9. 按 sharpe 排序 ──────────────────────────────

    def test_sort_by_sharpe(self):
        """按 sharpe 降序排列"""
        sorted_entries = self.ks.sort_by(self.ks.entries, "sharpe")
        self.assertEqual(len(sorted_entries), 15)
        prev = float("inf")
        for e in sorted_entries:
            if e.sharpe is not None:
                self.assertLessEqual(e.sharpe, prev)
                prev = e.sharpe
        # 第一名是条目6 (2.1)
        self.assertEqual(sorted_entries[0].task_id, "bt_e6")

    # ─── 10. 按 total_return 排序 ─────────────────────────

    def test_sort_by_return(self):
        """按 total_return 降序排列"""
        sorted_entries = self.ks.sort_by(self.ks.entries, "total_return")
        self.assertEqual(len(sorted_entries), 15)
        prev = float("inf")
        for e in sorted_entries:
            if e.total_return is not None:
                self.assertLessEqual(e.total_return, prev)
                prev = e.total_return

    # ─── 11. 组合查询 ────────────────────────────────────

    def test_combined_query(self):
        """组合查询：标签+字段+排序+分页"""
        # 搜索 trend 标签 + bull regime + 按 sharpe 排序
        results = self.ks.combined_query(
            tags=["trend"],
            field_filters={"regime": "bull"},
            sort_field="sharpe",
            limit=5,
        )
        self.assertLessEqual(len(results), 5)
        if results:
            self.assertIn("trend", results[0].tags)
            self.assertEqual(results[0].regime, "bull")
            # 第一的 sharpe 应最大
            sharpe_vals = [r.sharpe for r in results if r.sharpe is not None]
            if sharpe_vals:
                self.assertEqual(
                    max(sharpe_vals),
                    sharpe_vals[0],
                )

    # ─── 12. 日期范围过滤 ─────────────────────────────────

    def test_date_range(self):
        """按 completed_time 日期范围过滤"""
        # 2025-09-01 ~ 2025-12-31 → 条目6,7,8,9,10,11,12,13
        results = self.ks.filter_date_range(
            self.ks.entries, "2025-09-01", "2025-12-31"
        )
        self.assertEqual(len(results), 8)
        for r in results:
            self.assertGreaterEqual(r.completed_time[:10], "2025-09-01")
            self.assertLessEqual(r.completed_time[:10], "2025-12-31")

        # 2026-01-01 ~ 2026-12-31 → 条目14
        results = self.ks.filter_date_range(
            self.ks.entries, "2026-01-01", "2026-12-31"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_id, "bt_e14")

    # ─── 13. 分页 ────────────────────────────────────────

    def test_limit_offset(self):
        """分页：limit + offset"""
        # 所有条目按 quality_score 排序
        all_sorted = self.ks.sort_by(self.ks.entries, "quality_score")
        self.assertEqual(len(all_sorted), 15)

        # offset=0, limit=5 → 前5条
        page1 = self.ks.combined_query(
            sort_field="quality_score", limit=5, offset=0
        )
        self.assertEqual(len(page1), 5)
        self.assertEqual(page1[0].task_id, all_sorted[0].task_id)
        self.assertEqual(page1[-1].task_id, all_sorted[4].task_id)

        # offset=5, limit=5 → 第6-10条
        page2 = self.ks.combined_query(
            sort_field="quality_score", limit=5, offset=5
        )
        self.assertEqual(len(page2), 5)
        self.assertEqual(page2[0].task_id, all_sorted[5].task_id)
        self.assertEqual(page2[-1].task_id, all_sorted[9].task_id)

    # ─── 14. 知识库统计 ───────────────────────────────────

    def test_get_statistics(self):
        """知识库统计：按 method_name/symbol/regime/timeframe 分组计数"""
        stats = self.ks.get_statistics()

        # method_name
        self.assertEqual(stats["method_name"]["ma_cross"], 4)  # 0,1,8,14
        self.assertEqual(stats["method_name"]["grid"], 2)      # 2,9
        self.assertEqual(stats["method_name"]["rsi"], 2)       # 3,10
        self.assertEqual(stats["method_name"]["reversal"], 2)  # 4,11
        self.assertEqual(stats["method_name"]["bollinger"], 2) # 5,13
        self.assertEqual(stats["method_name"]["macd"], 2)      # 6,12
        self.assertEqual(stats["method_name"]["vwap"], 1)      # 7

        # symbol
        self.assertEqual(stats["symbol"]["601857"], 5)  # 0,2,6,8,11
        self.assertEqual(stats["symbol"]["000001"], 3)  # 1,7,13
        self.assertEqual(stats["symbol"]["600519"], 3)  # 3,9,14
        self.assertEqual(stats["symbol"]["002415"], 2)  # 4,12
        self.assertEqual(stats["symbol"]["300750"], 2)  # 5,10
        # 第14条是 600519，所以 600519 应该是 3
        self.assertEqual(stats["symbol"]["600519"], 3)  # 3,9,14

        # regime
        self.assertEqual(stats["regime"]["bull"], 6)      # 0,1,6,11,13,14
        self.assertEqual(stats["regime"]["sideways"], 4)  # 2,7,8,9
        self.assertEqual(stats["regime"]["volatile"], 3)  # 3,5,12
        self.assertEqual(stats["regime"]["bear"], 2)      # 4,10

        # timeframe
        self.assertEqual(stats["timeframe"]["1d"], 9)     # 0,1,2,4,6,9,10,13,14
        self.assertEqual(stats["timeframe"]["4h"], 3)     # 3,8,12
        self.assertEqual(stats["timeframe"]["1h"], 2)     # 5,11
        self.assertEqual(stats["timeframe"]["15m"], 1)    # 7

    # ─── 15. Top-K 排名 ──────────────────────────────────

    def test_get_top_k(self):
        """获取 quality_score 排名前 k 的条目"""
        top5 = self.ks.get_top_k("quality_score", k=5)
        self.assertEqual(len(top5), 5)
        prev = float("inf")
        for e in top5:
            self.assertLessEqual(e.quality_score, prev)
            prev = e.quality_score
        # 第一名应是条目6 (0.85)
        self.assertEqual(top5[0].task_id, "bt_e6")

        # top 3
        top3 = self.ks.get_top_k("quality_score", k=3)
        self.assertEqual(len(top3), 3)
        self.assertEqual(top3[0].task_id, "bt_e6")  # 0.85

        # sharpe top 5
        top5_sharpe = self.ks.get_top_k("sharpe", k=5)
        self.assertEqual(len(top5_sharpe), 5)
        self.assertEqual(top5_sharpe[0].task_id, "bt_e6")  # 2.1

    # ─── 16. 无效过滤字段抛异常 ───────────────────────────

    def test_filter_invalid_field(self):
        """使用不支持的过滤字段应抛 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            self.ks.filter_by_field("invalid_field", "value")
        self.assertIn("不支持的过滤字段", str(ctx.exception))

    # ─── 17. 无效排序字段抛异常 ───────────────────────────

    def test_sort_invalid_field(self):
        """使用不支持的排序字段应抛 ValueError"""
        with self.assertRaises(ValueError) as ctx:
            self.ks.sort_by(self.ks.entries, "invalid_field")
        self.assertIn("不支持的排序字段", str(ctx.exception))

    # ─── 18. 空标签/空关键词/空数据 ───────────────────────

    def test_empty_search(self):
        """空标签、空关键词、空数据目录的处理"""
        # 空标签 → 返回全部
        results = self.ks.search_by_tags([], mode="any")
        self.assertEqual(len(results), 15)

        results = self.ks.search_by_tags([], mode="all")
        self.assertEqual(len(results), 15)

        # 空关键词 → 返回全部
        results = self.ks.search_text("")
        self.assertEqual(len(results), 15)

        # 不存在的标签 → 空列表
        results = self.ks.search_by_tags(["nonexistent_tag"], mode="any")
        self.assertEqual(len(results), 0)

    # ─── 19. 全部过滤器同时生效 ───────────────────────────

    def test_combined_query_all_filters(self):
        """所有过滤器同时生效：标签+字段+关键词+排序+分页"""
        results = self.ks.combined_query(
            tags=["trend"],
            field_filters={"method_name": "ma_cross", "regime": "bull"},
            keyword="金叉",
            sort_field="quality_score",
            ascending=False,
            limit=10,
            offset=0,
        )
        # 趋势+ma_cross+bull+金叉: 条目0,14 → 2条
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("trend", r.tags)
            self.assertEqual(r.method_name, "ma_cross")
            self.assertEqual(r.regime, "bull")
            self.assertIn("金叉", r.insight_summary)

    # ─── 20. 重新加载 ─────────────────────────────────────

    def test_reload_entries(self):
        """reload() 后条目数不变"""
        count_before = self.ks.count
        self.ks.reload()
        self.assertEqual(self.ks.count, count_before)

    # ─── 21. insight_summary 描述准确验证 ──────────────────

    def test_describe_insight(self):
        """验证各条目的 insight_summary 描述与其数据一致"""
        # 条目6 (macd, bull, sharpe=2.1)
        entry = [e for e in self.ks.entries if e.task_id == "bt_e6"][0]
        self.assertIn("胜率最高", entry.insight_summary)

        # 条目10 (rsi, bear, total_return=-5.5)
        entry = [e for e in self.ks.entries if e.task_id == "bt_e10"][0]
        self.assertIn("巨大回撤", entry.insight_summary)


if __name__ == "__main__":
    unittest.main()
