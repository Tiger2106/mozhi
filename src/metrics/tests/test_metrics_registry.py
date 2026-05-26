"""
mozhi_platform 测试 — metrics_registry

作者: 墨衡
"""

import pytest
from metrics.metrics_registry import METRIC_DEFINITIONS, get_metric, all_metric_names


class TestMetricsRegistry:
    def test_metric_definitions_not_empty(self):
        assert len(METRIC_DEFINITIONS) >= 15

    def test_each_metric_has_required_fields(self):
        required = {"name", "display_name", "formula", "unit", "higher_is_better"}
        for key, defn in METRIC_DEFINITIONS.items():
            for field in required:
                assert hasattr(defn, field), f"{key} missing field {field}"

    def test_get_metric_exists(self):
        m = get_metric("sharpe")
        assert m is not None
        assert m.name == "sharpe"

    def test_get_metric_not_found(self):
        with pytest.raises(KeyError):
            get_metric("nonexistent")

    def test_list_metrics_returns_list(self):
        names = all_metric_names()
        assert isinstance(names, list)
        assert "sharpe" in names
        assert "max_drawdown" in names
        assert "win_rate" in names

    def test_higher_is_better_variety(self):
        """验证收益类指标 higher_is_better=True，风险类=False。"""
        assert METRIC_DEFINITIONS["sharpe"].higher_is_better is True
        assert METRIC_DEFINITIONS["max_drawdown"].higher_is_better is False
        assert METRIC_DEFINITIONS["volatility"].higher_is_better is False

    def test_display_names_are_chinese(self):
        """验证显示名为中文。"""
        assert METRIC_DEFINITIONS["sharpe"].display_name == "夏普比率"

    def test_categories(self):
        """验证分类字段存在且正确。"""
        assert METRIC_DEFINITIONS["sharpe"].category == "risk_adjusted"
        assert METRIC_DEFINITIONS["max_drawdown"].category == "risk"
        assert METRIC_DEFINITIONS["win_rate"].category == "trade"
