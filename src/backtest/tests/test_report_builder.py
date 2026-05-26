"""
mozhi_platform 测试 — ReportBuilder

作者: 墨衡
"""

import pytest
import pandas as pd

from backtest.engine.backtest_result_bundle import BacktestResultBundle
from backtest.pipeline.report_builder import ReportBuilder


def _make_bundle(method_name: str = "ma_cross", n_trades: int = 3) -> BacktestResultBundle:
    """生成模拟 Bundle 用于测试。"""
    dates = pd.date_range("2025-06-01", periods=10, freq="D")
    equity_curve = pd.DataFrame({
        "date": dates,
        "equity": [1.0 + i * 0.01 for i in range(10)],
        "return": [0.0] + [0.01] * 9,
    }, index=dates)
    return BacktestResultBundle(
        run_id=f"test_{method_name}",
        method_name=method_name,
        symbol="601857.SH",
        start_date="2025-06-01",
        end_date="2025-06-10",
        params={"ma_short": 5, "ma_long": 20},
        equity_curve=equity_curve,
        summary_metrics={
            "n_trades": n_trades,
            "total_return": 0.12,
            "sharpe": 1.5,
            "max_drawdown": -0.05,
        },
        data_quality={"completeness": 99.2, "rating": "A"},
    )


class TestReportBuilder:
    def test_init_single_bundle(self):
        bundle = _make_bundle()
        builder = ReportBuilder([bundle])
        assert builder is not None

    def test_init_multiple_bundles(self):
        bundles = [_make_bundle("trend"), _make_bundle("mean", 1)]
        builder = ReportBuilder(bundles)
        assert len(builder.bundles) == 2

    def test_build_returns_html(self):
        bundle = _make_bundle()
        builder = ReportBuilder([bundle])
        html = builder.build()
        assert isinstance(html, str)
        assert len(html) > 500
        # 应包含基本的 HTML 结构
        assert "<html" in html or "<!DOCTYPE" in html
        # 应包含章节标题
        assert "回测" in html

    def test_build_minimal(self):
        bundle = _make_bundle()
        builder = ReportBuilder([bundle])
        html = builder.build_minimal()
        assert isinstance(html, str)
        assert len(html) > 200

    def test_build_with_portfolio_bundle(self):
        bundle = _make_bundle("trend")
        pf = _make_bundle("portfolio", n_trades=10)
        builder = ReportBuilder([bundle], portfolio_bundle=pf)
        html = builder.build()
        assert isinstance(html, str)
        assert len(html) > 500

    def test_chapter_0_data_quality(self):
        bundle = _make_bundle()
        builder = ReportBuilder([bundle])
        html = builder.build()
        # 第0章数据质量声明应包含关键字段
        assert "数据质量" in html
        assert "A" in html  # rating

    def test_chapter_4_metrics_table(self):
        bundle = _make_bundle()
        builder = ReportBuilder([bundle])
        html = builder.build()
        # 应包含指标数据
        assert "夏普" in html or "sharpe" in html.lower()

    def test_empty_bundles(self):
        """空 bundles 列表的构建结果不应抛出异常。"""
        builder = ReportBuilder([])
        assert builder is not None

    def test_repr(self):
        bundle = _make_bundle()
        builder = ReportBuilder([bundle])
        r = repr(builder)
        assert "ReportBuilder" in r
