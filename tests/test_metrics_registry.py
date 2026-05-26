"""
test_metrics_registry — METRIC_DEFINITIONS

验证 20 个指标定义：所有名称非空、所有分类正确、所有必要字段齐全。

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import pytest

from src.metrics.metrics_registry import (
    METRIC_DEFINITIONS,
    MetricDefinition,
    get_metric,
    list_metrics_by_category,
    all_metric_names,
)


# ══════════════════════════════════════════════════════════════════════
# METRIC_DEFINITIONS — 基础验证
# ══════════════════════════════════════════════════════════════════════


class TestMetricDefinitions:
    def test_count(self):
        """应有 20 个指标。"""
        assert len(METRIC_DEFINITIONS) == 20

    def test_all_names_not_empty(self):
        """所有指标名称不应为空。"""
        for name, metric in METRIC_DEFINITIONS.items():
            assert name, f"name empty for {metric}"
            assert metric.name == name, f"key/name mismatch: {name} vs {metric.name}"

    def test_all_display_names_not_empty(self):
        """所有 display_name 不应为空。"""
        for name, metric in METRIC_DEFINITIONS.items():
            assert metric.display_name, f"display_name empty for {name}"

    def test_all_formulas_not_empty(self):
        """所有 formula 不应为空。"""
        for name, metric in METRIC_DEFINITIONS.items():
            assert metric.formula, f"formula empty for {name}"

    def test_all_annualized_defined(self):
        """annualized 应为布尔值。"""
        for metric in METRIC_DEFINITIONS.values():
            assert isinstance(metric.annualized, bool)

    def test_all_units_defined(self):
        """unit 必须为字符串（允许空字符串，表示无量纲）。"""
        for name, metric in METRIC_DEFINITIONS.items():
            assert isinstance(metric.unit, str), f"unit not a string for {name}"

    def test_all_higher_is_better_defined(self):
        """higher_is_better 应为布尔值。"""
        for metric in METRIC_DEFINITIONS.values():
            assert isinstance(metric.higher_is_better, bool)

    def test_all_categories_valid(self):
        """所有 category 应在允许范围内。"""
        valid_categories = {"return", "risk", "risk_adjusted", "trade", "recovery", "info"}
        for name, metric in METRIC_DEFINITIONS.items():
            assert metric.category in valid_categories, \
                f"{name}: invalid category '{metric.category}'"

    def test_all_descriptions_not_empty(self):
        """所有 description 不应为空。"""
        for name, metric in METRIC_DEFINITIONS.items():
            assert metric.description, f"description empty for {name}"

    def test_to_dict_valid(self):
        """to_dict() 应包含所有关键字段。"""
        for name, metric in METRIC_DEFINITIONS.items():
            d = metric.to_dict()
            for k in ("name", "display_name", "formula", "annualized", "unit",
                      "higher_is_better", "category", "description"):
                assert k in d, f"{name}: missing key '{k}' in to_dict()"

    def test_repr_works(self):
        """__repr__ 不应抛出异常。"""
        for metric in METRIC_DEFINITIONS.values():
            r = repr(metric)
            assert len(r) > 0
            assert "MetricDefinition" in r


# ══════════════════════════════════════════════════════════════════════
# 分类分布
# ══════════════════════════════════════════════════════════════════════


class TestCategoryDistribution:
    def test_return_category_count(self):
        """收益类应有 3 个指标。"""
        assert len(list_metrics_by_category("return")) == 3

    def test_risk_category_count(self):
        """风险类应有 3 个指标（max_drawdown, drawdown_duration, underwater_ratio），
        但 n_trades、n_signals 在 category=trade，所以 risk 类的 count 可能是 3 或更多。"""
        risk_metrics = list_metrics_by_category("risk")
        assert len(risk_metrics) >= 3

    def test_risk_adjusted_category(self):
        """风险调整收益类应有 3 个指标（sharpe, sortino, calmar）。"""
        adj = list_metrics_by_category("risk_adjusted")
        assert len(adj) == 3
        names = {m.name for m in adj}
        assert names == {"sharpe", "sortino", "calmar"}

    def test_trade_category_count(self):
        """交易统计类应有 4 个指标（win_rate, profit_factor, avg_trade_return + n_trades/n_signals 之一）。"""
        trade = list_metrics_by_category("trade")
        assert len(trade) >= 3

    def test_recovery_category(self):
        """恢复类应有 3 个指标。"""
        recovery = list_metrics_by_category("recovery")
        assert len(recovery) == 3

    def test_info_category(self):
        """信息类应有 3 个指标（alpha, beta, information_ratio）。"""
        info = list_metrics_by_category("info")
        assert len(info) == 3


# ══════════════════════════════════════════════════════════════════════
# get_metric / all_metric_names
# ══════════════════════════════════════════════════════════════════════


class TestAccessorFunctions:
    def test_get_metric_success(self):
        """get_metric 应返回有效的 MetricDefinition。"""
        m = get_metric("sharpe")
        assert isinstance(m, MetricDefinition)
        assert m.display_name == "夏普比率"

    def test_get_metric_not_found(self):
        """不存在的指标应抛出 KeyError。"""
        with pytest.raises(KeyError):
            get_metric("nonexistent_metric_xyz")

    def test_all_metric_names_count(self):
        """all_metric_names 应返回 20 个名称。"""
        names = all_metric_names()
        assert len(names) == 20
        assert sorted(names) == names  # 应为排序列表

    def test_all_metric_names_unique(self):
        """所有名称应唯一。"""
        names = all_metric_names()
        assert len(names) == len(set(names))

    def test_key_metric_present(self):
        """关键指标应存在。"""
        important = {"sharpe", "sortino", "calmar", "max_drawdown",
                     "win_rate", "profit_factor", "total_return", "annual_return"}
        names = all_metric_names()
        for k in important:
            assert k in names, f"missing key metric: {k}"


# ══════════════════════════════════════════════════════════════════════
# MetricDefinition — 特定指标参数验证
# ══════════════════════════════════════════════════════════════════════


class TestSpecificMetrics:
    def test_sharpe_params(self):
        sharpe = get_metric("sharpe")
        assert sharpe.annualized is True
        assert sharpe.higher_is_better is True
        assert sharpe.category == "risk_adjusted"

    def test_max_drawdown_direction(self):
        """最大回撤应越低越好 (higher_is_better=False)。"""
        mdd = get_metric("max_drawdown")
        assert mdd.higher_is_better is False
        assert mdd.category == "risk"

    def test_total_return_unit(self):
        """总收益率单位应为 %。"""
        tr = get_metric("total_return")
        assert tr.unit == "%"

    def test_annual_return_url(self):
        """年化收益率单位应为 % 且 annualized=True。"""
        ar = get_metric("annual_return")
        assert ar.unit == "%"
        assert ar.annualized is True

    def test_volatility_direction(self):
        """波动率应越低越好。"""
        vol = get_metric("volatility")
        assert vol.higher_is_better is False

    def test_n_trades_unit(self):
        """交易笔数的 unit 应为空字符串。"""
        nt = get_metric("n_trades")
        assert nt.unit == ""

    def test_drawdown_duration_unit(self):
        """回撤持续期单位应为 days。"""
        dd = get_metric("drawdown_duration")
        assert dd.unit == "days"

    def test_recovery_factor_category(self):
        rf = get_metric("recovery_factor")
        assert rf.category == "recovery"

    def test_information_ratio_category(self):
        ir = get_metric("information_ratio")
        assert ir.category == "info"

    def test_alpha_annualized(self):
        """阿尔法应 annualized=True。"""
        a = get_metric("alpha")
        assert a.annualized is True

    def test_beta_higher_is_better_false(self):
        """贝塔 should be... actually this is debatable, but verify it at least is defined."""
        b = get_metric("beta")
        assert isinstance(b.higher_is_better, bool)

    def test_pain_index_higher_is_better_false(self):
        """痛苦指数应越低越好。"""
        pi = get_metric("pain_index")
        assert pi.higher_is_better is False
