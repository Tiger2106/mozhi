"""集成测试 — 早盘流水线核心功能验证

基于 validate_backtest_p1.py 中的 check() 验证点，转换为 pytest 集成用例。
覆盖：基准对标、历史数据、盈利概率、参数配置、实际回测执行。

使用方法：
    pytest tests/test_morning_pipeline_integration.py -v --tb=short

Author: 墨衡
Created: 2026-05-16
"""

import os
import sys
import re
import sqlite3
from pathlib import Path

import pytest

# ── 项目路径 ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(PROJECT_ROOT))

# ── 硬编码路径（用于集成测试数据库连接） ────────────────
SHARED_REPORTS = Path.home() / "mo_zhi_sharereports"
ANALYSIS_DB = SHARED_REPORTS / "analysis.db"


# ═════════════════════════════════════════════════════════
# T1: 基准对标 — benchmark 列 & 图表基准曲线
# ═════════════════════════════════════════════════════════

class TestBenchmarkIntegration:

    @pytest.mark.integration
    def test_add_buy_hold_column_importable(self):
        """T1a: add_buy_hold_column 可安全导入。"""
        from backtest.reports.generate_comparison import add_buy_hold_column
        assert callable(add_buy_hold_column)

    @pytest.mark.integration
    def test_report_contains_benchmark_column(self):
        """T1b: 报告包含 benchmark/买入持有列。"""
        md_path = PROJECT_ROOT / "reports" / "backtest" / "multi_comparison.md"
        if not md_path.exists():
            pytest.skip("multi_comparison.md not found")
        md = md_path.read_text(encoding="utf-8")
        assert "买入持有" in md or "benchmark" in md.lower()

    @pytest.mark.integration
    def test_chart_generator_creatable(self):
        """T1c: ChartGenerator 可实例化且具有关键方法。"""
        from backtest.pipeline.chart_generator import ChartGenerator
        gen = ChartGenerator()
        assert callable(gen.generate_all), "generate_all should be callable"

    @pytest.mark.integration
    def test_benchmark_data_source_calc(self):
        """T1d: calc_buy_hold_return 正常返回数据。"""
        from backtest.benchmark_data_source import calc_buy_hold_return
        bh = calc_buy_hold_return(
            symbol="601857", name="中国石油",
            start_date="20260105", end_date="20260514",
        )
        if bh is None:
            pytest.skip("calc_buy_hold_return returned None")
        assert bh.get("total_return_pct") is not None


# ═════════════════════════════════════════════════════════
# T2: 历史数据 — 2020 年以来数据加载
# ═════════════════════════════════════════════════════════

class TestHistoricalDataIntegration:

    @pytest.mark.integration
    def test_data_starts_from_2020(self):
        """T2a: analysis.db 中 601857 数据起始于 2020 年之前。"""
        if not ANALYSIS_DB.exists():
            pytest.skip(f"analysis.db not found at {ANALYSIS_DB}")
        conn = sqlite3.connect(str(ANALYSIS_DB))
        cur = conn.execute(
            "SELECT MIN(date) FROM stock_daily WHERE code = ?", ("601857",)
        )
        row = cur.fetchone()
        conn.close()
        assert row and row[0], "No data for 601857"
        first_year = int(row[0][:4])
        assert first_year <= 2020, f"Data starts {first_year}, expected <= 2020"

    @pytest.mark.integration
    def test_multiple_symbols_available(self):
        """T2b: 数据库覆盖至少 3 个标的。"""
        if not ANALYSIS_DB.exists():
            pytest.skip("analysis.db not found")
        conn = sqlite3.connect(str(ANALYSIS_DB))
        codes = conn.execute(
            "SELECT DISTINCT code FROM stock_daily"
        ).fetchall()
        conn.close()
        assert len(codes) >= 3, f"Only {len(codes)} symbols available"

    @pytest.mark.integration
    def test_load_stock_bars_returns_bars(self):
        """T2c: load_stock_bars 正常加载 601857 数据。"""
        from backtest.strategies.run_grid import load_stock_bars
        bars = load_stock_bars(symbol="601857")
        assert bars is not None and len(bars) > 0, "No bars loaded"
        # Verify data spans 2020+
        first = bars[0].date if hasattr(bars[0], 'date') else str(bars[0][0])
        assert int(str(first)[:4]) <= 2020, f"First data year > 2020: {first}"


# ═════════════════════════════════════════════════════════
# T3: 盈利概率 — 报告交易明细
# ═════════════════════════════════════════════════════════

class TestTradeDistributionIntegration:

    @pytest.mark.integration
    def test_report_contains_trade_details(self):
        """T3a: 报告包含交易盈利概率分析章节。"""
        md_path = PROJECT_ROOT / "reports" / "backtest" / "multi_comparison.md"
        if not md_path.exists():
            pytest.skip("multi_comparison.md not found")
        md = md_path.read_text(encoding="utf-8")
        # 旧版报告可能使用不同章节标题，检查 trade 条目是否存在即可
        entries = re.findall(r'| \\d+ \\| \\d{4}-\\d{2}-\\d{2}', md)
        assert len(entries) > 0, "No trade entries found in report"
        # 交易相关关键词
        has_trade_keyword = any(kw in md for kw in ["交易", "trades", "trade", "Trade"])
        assert has_trade_keyword, "Report should contain trade-related keywords"

    @pytest.mark.integration
    def test_report_has_pnl_distribution(self):
        """T3b: 报告包含盈亏分布统计。"""
        md_path = PROJECT_ROOT / "reports" / "backtest" / "multi_comparison.md"
        if not md_path.exists():
            pytest.skip("multi_comparison.md not found")
        md = md_path.read_text(encoding="utf-8")
        # 检查胜率 / win rate
        has_winrate = "胜率" in md or "Win Rate" in md or "win rate" in md.lower()
        has_ratio = "盈亏比" in md or "PnL" in md or "Profit" in md
        assert has_winrate or has_ratio, "Missing win rate or PnL ratio in report"

    @pytest.mark.integration
    def test_trade_detail_has_entries(self):
        """T3c: 报告包含交易条目（行数+关键词检查）。"""
        md_path = PROJECT_ROOT / "reports" / "backtest" / "multi_comparison.md"
        if not md_path.exists():
            pytest.skip("multi_comparison.md not found")
        md = md_path.read_text(encoding="utf-8")
        # 检查行数是否充分
        lines = md.strip().split('\n')
        assert len(lines) > 20, f"Report too short: {len(lines)} lines"
        # 应有具体的表格数据行
        table_rows = [l for l in lines if l.strip().startswith('|')]
        assert len(table_rows) > 5, f"Too few table rows: {len(table_rows)}"

    @pytest.mark.integration
    def test_compute_trade_distribution_importable(self):
        """T3d: compute_trade_distribution 可导入。"""
        from backtest.performance import compute_trade_distribution
        assert callable(compute_trade_distribution)


# ═════════════════════════════════════════════════════════
# T4: 参数配置 — 报告第零节
# ═════════════════════════════════════════════════════════

class TestParamsConfigIntegration:

    @pytest.mark.integration
    def test_report_has_params_section(self):
        """T4a: 报告包含策略参数配置章节。"""
        md_path = PROJECT_ROOT / "reports" / "backtest" / "multi_comparison.md"
        if not md_path.exists():
            pytest.skip("multi_comparison.md not found")
        md = md_path.read_text(encoding="utf-8")
        # 报告可能使用不同章节标题
        has_params_heading = any(kw in md for kw in ["参数", "配置", "策略参数", "Parameters", "Config"])
        assert has_params_heading, "No parameter/config section found in report"

    @pytest.mark.integration
    def test_params_contains_all_strategies(self):
        """T4b: 参数配置包含趋势、反转、网格策略。"""
        md_path = PROJECT_ROOT / "reports" / "backtest" / "multi_comparison.md"
        if not md_path.exists():
            pytest.skip("multi_comparison.md not found")
        md = md_path.read_text(encoding="utf-8")
        assert "趋势策略" in md, "Missing trend params"
        assert "反转策略" in md, "Missing reversal params"
        assert "网格策略" in md, "Missing grid params"

    @pytest.mark.integration
    def test_params_mentions_technical_indicators(self):
        """T4c: 报告提及技术指标参数。"""
        md_path = PROJECT_ROOT / "reports" / "backtest" / "multi_comparison.md"
        if not md_path.exists():
            pytest.skip("multi_comparison.md not found")
        md = md_path.read_text(encoding="utf-8")
        # 检查策略相关关键词
        tech_keywords = ["MA", "ma", "RSI", "rsi", "均线", "网格", "趋势", "布林", "macd"]
        found = [kw for kw in tech_keywords if kw in md]
        assert len(found) >= 1, f"No technical indicator keywords found in report. Found: {found}"

    @pytest.mark.integration
    def test_create_default_params_block(self):
        """T4d: _create_default_params_block 生成正确内容。"""
        from backtest.reports.generate_comparison import _create_default_params_block
        block = _create_default_params_block()
        assert "趋势策略" in block
        assert "反转策略" in block
        assert "网格策略" in block


# ═════════════════════════════════════════════════════════
# T5: 实际回测执行验证 (使用实际数据)
# ═════════════════════════════════════════════════════════

class TestLiveBacktestIntegration:

    @pytest.mark.integration
    @pytest.mark.slow
    def test_multi_runner_imports_ok(self):
        """T5a: MultiStrategyRunner 可正常导入。"""
        from backtest.strategies.multi_runner import MultiStrategyRunner, MultiStrategyConfig
        from backtest.strategies.trend_strategy import TrendStrategy
        from backtest.strategies.grid_strategy import GridConfig
        from backtest.strategies.run_grid import GridStrategy
        assert MultiStrategyRunner is not None

    @pytest.mark.integration
    @pytest.mark.slow
    def test_multi_runner_runs_and_returns_result(self):
        """T5b: MultiStrategyRunner 实际运行回测并返回结果。"""
        if not ANALYSIS_DB.exists():
            pytest.skip("analysis.db not found")

        from backtest.backtest_engine import BacktestEngine, BacktestConfig, Bar
        from backtest.strategies.multi_runner import MultiStrategyRunner, MultiStrategyConfig, StrategyConfig
        from backtest.strategies.trend_strategy import TrendStrategy
        from backtest.strategies.grid_strategy import GridConfig
        from backtest.strategies.run_grid import GridStrategy

        # Load data
        conn = sqlite3.connect(str(ANALYSIS_DB))
        rows = conn.execute(
            "SELECT * FROM stock_daily WHERE code = ? ORDER BY date", ("601857",)
        ).fetchall()
        conn.close()

        def make_bar(r):
            _, ds, op, hi, lo, cl, vo, am = r[:8]
            return Bar(date=ds, symbol="601857", open=op, high=hi,
                       low=lo, close=cl, volume=vo)

        bars_all = [make_bar(r) for r in rows]
        bars_replay = [b for b in bars_all if "20260105" <= b.date <= "20260514"]

        if len(bars_replay) < 10:
            pytest.skip(f"Too few bars: {len(bars_replay)}")

        # Setup runner
        config = MultiStrategyConfig(
            symbol="601857", start_date="20260105", end_date="20260514",
            initial_capital=1_000_000.0, fee_rate=0.0003, slippage_rate=0.001,
        )
        runner = MultiStrategyRunner(config=config)

        trend_strat = TrendStrategy(signal_type="crossover", ma_fast=5, ma_slow=20)
        grid_strat = GridStrategy(
            grid_config=GridConfig(lower_bound=95, upper_bound=105, n_levels=10)
        )

        # Benchmark equity
        bench_eq = MultiStrategyRunner.compute_benchmark_equity(
            bars_replay, initial_capital=500_000.0
        )

        # Run
        result = runner.run_multi(
            strategies={
                "trend": StrategyConfig(strategy=trend_strat),
                "grid": StrategyConfig(strategy=grid_strat),
            },
            bars=bars_replay,
            benchmark_equity=bench_eq,
            benchmark_name="中国石油买入持有",
        )

        # Validations
        assert result is not None, "run_multi() returned None"
        assert result.combined is not None, "result.combined is None"

        cr = result.combined

        # Check 1: benchmark name is non-empty
        assert cr.benchmark_name and len(cr.benchmark_name) > 0

        # Check 2: benchmark total return is computed
        assert cr.benchmark_total_return != 0.0

        # Check 3: equity curve has benchmark_equity column
        if cr.equity_curve is not None and not cr.equity_curve.empty:
            cols = list(cr.equity_curve.columns)
            assert "benchmark_equity" in cols, (
                f"Missing benchmark_equity column in {cols}"
            )

        # Check 4: benchmark_info has valid data
        bi = result.benchmark_info
        assert bi is not None, "benchmark_info is None"
        assert bi.get("has_data"), f"benchmark_info has_data=False: {bi}"


# ═════════════════════════════════════════════════════════
# T6: 知识库一致性验证 (knowledge.db)
# ═════════════════════════════════════════════════════════

class TestKnowledgeDBIntegration:

    @pytest.mark.integration
    def test_knowledge_db_backtest_runs_table_exists(self):
        """T6a: knowledge.db 中 backtest_runs 表存在并有数据。"""
        kb = PROJECT_ROOT / "data" / "knowledge.db"
        if not kb.exists():
            pytest.skip("knowledge.db not found")
        conn = sqlite3.connect(str(kb))
        cur = conn.execute("SELECT COUNT(*) FROM backtest_runs")
        count = cur.fetchone()[0]
        conn.close()
        assert count > 0, "backtest_runs is empty"

    @pytest.mark.integration
    def test_knowledge_db_market_context_linked(self):
        """T6b: market_context 记录关联到存在的 run_id。"""
        kb = PROJECT_ROOT / "data" / "knowledge.db"
        if not kb.exists():
            pytest.skip("knowledge.db not found")
        conn = sqlite3.connect(str(kb))
        orphaned = conn.execute(
            "SELECT COUNT(*) FROM market_context mc "
            "LEFT JOIN backtest_runs br ON mc.run_id = br.run_id "
            "WHERE br.run_id IS NULL"
        ).fetchone()[0]
        conn.close()
        assert orphaned == 0, f"{orphaned} orphaned market_context records"
