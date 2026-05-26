"""
test_report_builder — ReportBuilder（14 章 HTML 报告生成器）

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine.backtest_result_bundle import BacktestResultBundle
from backtest.engine.portfolio_integration import TradePair
from backtest.pipeline.report_builder import ReportBuilder


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def basic_bundle() -> BacktestResultBundle:
    """标准 Bundle，含基本字段。"""
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    ec = pd.DataFrame({
        "date": dates,
        "equity": np.linspace(1.0, 1.15, 30),
        "return": np.concatenate([[0.0], np.diff(np.linspace(1.0, 1.15, 30)) / np.linspace(1.0, 1.15, 30)[:-1]]),
    }, index=dates)

    bc = pd.DataFrame({
        "date": dates,
        "equity": np.linspace(1.0, 1.08, 30),
        "return": np.concatenate([[0.0], np.diff(np.linspace(1.0, 1.08, 30)) / np.linspace(1.0, 1.08, 30)[:-1]]),
    }, index=dates)

    dm = pd.DataFrame({
        "return": [0.0, 0.01, -0.005, 0.015, -0.01, 0.02] * 5,
        "equity": [1.0, 1.01, 1.005, 1.02, 1.01, 1.03] * 5,
    }, index=dates[:30])

    trades = [
        TradePair("2025-01-03", 100.0, "2025-01-10", 110.0, 10.0, 1000),
        TradePair("2025-01-13", 105.0, "2025-01-20", 102.0, -3.0, 800),
        TradePair("2025-01-22", 103.0, "2025-01-29", 115.0, 12.0, 1200),
    ]

    return BacktestResultBundle(
        run_id="test_run_001",
        strategy_name="均值回归",
        method_name="mean_rev_v1",
        symbol="000300.SH",
        start_date="2025-01-01",
        end_date="2025-01-31",
        params={"window": 20, "initial_capital": 1_000_000},
        equity_curve=ec,
        benchmark_curve=bc,
        trades=trades,
        daily_metrics=dm,
        insights=[],
        summary_metrics={
            "total_return": 0.15,
            "n_trades": 3,
            "win_rate": 0.6667,
            "n_signals": 15,
            "signal_ratio": 0.5,
        },
        data_quality={
            "source": "akshare",
            "period": "daily",
            "adjusted": "qfq",
            "completeness": 99.8,
            "rating": "A",
            "missing_days": 0,
            "total_days": 30,
            "nan_handling": "forward fill",
            "slippage_model": "fixed 0.1%",
            "commission": "0.03%",
        },
    )


@pytest.fixture
def empty_bundle() -> BacktestResultBundle:
    """空 Bundle（无数据）。"""
    return BacktestResultBundle(method_name="empty")


# ══════════════════════════════════════════════════════════════════════
# ReportBuilder — 基础构造
# ══════════════════════════════════════════════════════════════════════


class TestReportBuilderInit:
    def test_default_init(self, basic_bundle: BacktestResultBundle):
        builder = ReportBuilder(bundles=[basic_bundle])
        assert len(builder.bundles) == 1
        assert builder.portfolio_bundle is None

    def test_with_portfolio(self, basic_bundle: BacktestResultBundle):
        builder = ReportBuilder(bundles=[basic_bundle], portfolio_bundle=basic_bundle)
        assert builder.portfolio_bundle is not None

    def test_empty_list(self):
        """允许空列表（报告仍会生成）。"""
        builder = ReportBuilder(bundles=[])
        html = builder.build()
        assert isinstance(html, str)
        assert len(html) > 0


# ══════════════════════════════════════════════════════════════════════
# ReportBuilder — build() 基础验证
# ══════════════════════════════════════════════════════════════════════


class TestReportBuilderBuild:
    def test_build_returns_string(self, basic_bundle: BacktestResultBundle):
        builder = ReportBuilder(bundles=[basic_bundle])
        html = builder.build()
        assert isinstance(html, str)

    def test_build_contains_html_structure(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html

    def test_build_contains_cover(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "回测分析报告" in html
        assert "000300.SH" in html

    def test_build_contains_all_chapters(self, basic_bundle: BacktestResultBundle):
        """build() 应包含所有 14 章标题。"""
        html = ReportBuilder(bundles=[basic_bundle]).build()
        chapter_markers = [
            "第0章", "一、回测参数表", "二、净值曲线",
            "三、回撤", "四、指标总表", "五、K线",
            "六、交易行为", "七、市场状态", "八、知识库提炼",
            "九、参数敏感性", "十、样本内外对比", "十一、策略相关性",
            "十二、连续亏损", "十三、T1评级",
        ]
        for marker in chapter_markers:
            assert marker in html, f"missing chapter marker: {marker}"

    def test_build_data_quality_section(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "数据质量声明" in html
        assert "A" in html  # rating
        assert "99.8" in html  # completeness

    def test_build_params_table(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "回测参数表" in html
        assert "000300.SH" in html
        assert "window" in html

    def test_build_equity_curve(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "权益" in html or "equity" in html
        assert "%" in html  # 收益率包含百分比

    def test_build_metrics_table(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "总收益率" in html
        assert "交易笔数" in html
        assert "胜率" in html

    def test_build_trades_section(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "3 笔" in html or "3笔" in html

    def test_multi_bundle(self, basic_bundle: BacktestResultBundle):
        """多 bundle 应生成所有方法的章节。"""
        b1 = basic_bundle
        from copy import deepcopy
        b2 = deepcopy(b1)
        b2.method_name = "momentum_v2"
        b2.run_id = "test_run_002"

        html = ReportBuilder(bundles=[b1, b2]).build()
        assert "mean_rev_v1" in html
        assert "momentum_v2" in html
        # 排他性断言：各方法名至少各出现一次
        assert html.count("mean_rev_v1") >= 1
        assert html.count("momentum_v2") >= 1


# ══════════════════════════════════════════════════════════════════════
# ReportBuilder — build_minimal()
# ══════════════════════════════════════════════════════════════════════


class TestReportBuilderMinimal:
    def test_minimal_returns_string(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build_minimal()
        assert isinstance(html, str)

    def test_minimal_contains_html_structure(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build_minimal()
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_minimal_has_fewer_chapters(self, basic_bundle: BacktestResultBundle):
        full = ReportBuilder(bundles=[basic_bundle]).build()
        minimal = ReportBuilder(bundles=[basic_bundle]).build_minimal()
        assert len(minimal) < len(full), "minimal should be shorter than full"

    def test_minimal_contains_only_0_to_5(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build_minimal()
        # 应包含 0~5 章内容
        assert "回测参数表" in html
        assert "净值曲线" in html
        # 不应包含第 6 章后的内容
        assert "交易行为分析" not in html
        assert "知识库提炼" not in html
        assert "参数敏感性" not in html


# ══════════════════════════════════════════════════════════════════════
# ReportBuilder — 边缘情况
# ══════════════════════════════════════════════════════════════════════


class TestReportBuilderEdgeCases:
    def test_empty_bundles_no_crash(self, empty_bundle: BacktestResultBundle):
        """空数据的 Bundle 不应导致崩溃。"""
        html = ReportBuilder(bundles=[empty_bundle]).build()
        assert isinstance(html, str)

    def test_empty_bundle_has_no_benchmark(self, empty_bundle: BacktestResultBundle):
        """空 benchmark_curve 不应崩溃。"""
        html = ReportBuilder(bundles=[empty_bundle]).build()
        assert isinstance(html, str)
        assert len(html) > 0

    def test_no_trades_in_bundle(self, basic_bundle: BacktestResultBundle):
        """无成交记录不应崩溃。"""
        b = basic_bundle
        b.trades = []
        html = ReportBuilder(bundles=[b]).build()
        assert "无成交记录" in html or isinstance(html, str)

    def test_special_chars_in_names(self, basic_bundle: BacktestResultBundle):
        """特殊字符不应破坏 HTML。"""
        b = basic_bundle
        b.method_name = "<test&method>"
        html = ReportBuilder(bundles=[b]).build()
        assert "&lt;test&amp;method&gt;" in html

    def test_non_ascii_ok(self, basic_bundle: BacktestResultBundle):
        """中文方法名应正常显示（HTML 中可通过渲染看到）。"""
        b = basic_bundle
        b.method_name = "均值回归策略_v2.0"
        b.strategy_name = "量化策略"
        html = ReportBuilder(bundles=[b]).build()
        # 中文字符在 HTML 中不应被转义为空白
        assert "均值" in html  # 通过子串验证
        assert "量化策略" in html

    def test_data_quality_missing_fields(self, basic_bundle: BacktestResultBundle):
        """data_quality 缺少部分字段时不应崩溃。"""
        b = basic_bundle
        b.data_quality = {"rating": "B"}  # 只有 rating
        html = ReportBuilder(bundles=[b]).build()
        assert isinstance(html, str)
        assert "B" in html


# ══════════════════════════════════════════════════════════════════════
# ReportBuilder — 占位章节验证
# ══════════════════════════════════════════════════════════════════════


class TestPlaceholderChapters:
    def test_chapter_6_has_placeholder_stamp(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "Phase 3" in html

    def test_chapter_9_has_param_sensitivity_content(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "参数敏感性" in html

    def test_chapter_13_has_t1_rating(self, basic_bundle: BacktestResultBundle):
        html = ReportBuilder(bundles=[basic_bundle]).build()
        assert "T1评级" in html
