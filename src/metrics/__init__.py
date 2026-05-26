"""
mozhi_platform.src.metrics — 指标计算与注册

统一指标口径定义和计算功能。
"""

from __future__ import annotations

from .metrics_registry import (
    METRIC_DEFINITIONS,
    MetricDefinition,
    get_metric,
    list_metrics_by_category,
    all_metric_names,
)

__all__ = [
    "METRIC_DEFINITIONS",
    "MetricDefinition",
    "get_metric",
    "list_metrics_by_category",
    "all_metric_names",
]
