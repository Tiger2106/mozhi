"""
mozhi_platform.src.metrics.metrics_registry — 指标注册表

统一指标口径定义。ReportBuilder 通过此注册表获取指标的名称、公式、单位等信息。

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


# ──────────────────────────────────────────────────────────────────────
# MetricDefinition — 单个指标定义
# ──────────────────────────────────────────────────────────────────────


class MetricDefinition:
    """单个指标的定义。

    Attributes:
        name: 指标英文名（如 "sharpe"）。
        display_name: 指标显示名（如 "夏普比率"）。
        formula: 计算公式的简要说明。
        annualized: 是否年化。
        unit: 单位（如 "ratio", "%", "days"）。
        higher_is_better: 是否越高越好。
        category: 指标分类（return / risk / risk_adjusted / trade / recovery / info）。
        description: 详细描述。
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        formula: str,
        annualized: bool = False,
        unit: str = "ratio",
        higher_is_better: bool = True,
        category: str = "risk_adjusted",
        description: str = "",
    ):
        self.name = name
        self.display_name = display_name
        self.formula = formula
        self.annualized = annualized
        self.unit = unit
        self.higher_is_better = higher_is_better
        self.category = category
        self.description = description or display_name

    def to_dict(self) -> Dict[str, Any]:
        """转为字典，方便序列化。"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "formula": self.formula,
            "annualized": self.annualized,
            "unit": self.unit,
            "higher_is_better": self.higher_is_better,
            "category": self.category,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"<MetricDefinition {self.name}: {self.display_name}>"


# ══════════════════════════════════════════════════════════════════════
# METRIC_DEFINITIONS — 20 个指标的定义字典
# ══════════════════════════════════════════════════════════════════════

# 指标分类：
#   return          — 收益类（3 个）
#   risk            — 风险类（5 个）
#   risk_adjusted   — 风险调整收益类（3 个）
#   trade           — 交易统计类（4 个）
#   recovery        — 恢复类（3 个）
#   info            — 信息类（2 个）

METRIC_DEFINITIONS: Dict[str, MetricDefinition] = {
    # ─── 收益类 (Return) ──────────────────────────────────────────
    "total_return": MetricDefinition(
        name="total_return",
        display_name="总收益率",
        formula="(最终净值 / 初始净值) - 1",
        annualized=False,
        unit="%",
        higher_is_better=True,
        category="return",
        description="回测期间累计总收益率。",
    ),
    "annual_return": MetricDefinition(
        name="annual_return",
        display_name="年化收益率",
        formula="(1 + 总收益率)^(252 / 交易天数) - 1",
        annualized=True,
        unit="%",
        higher_is_better=True,
        category="return",
        description="年化后的平均收益率。",
    ),
    "volatility": MetricDefinition(
        name="volatility",
        display_name="年化波动率",
        formula="日收益率标准差 × sqrt(252)",
        annualized=True,
        unit="%",
        higher_is_better=False,
        category="return",
        description="年化后的收益率波动标准差。",
    ),
    # ─── 风险类 (Risk) ──────────────────────────────────────────
    "max_drawdown": MetricDefinition(
        name="max_drawdown",
        display_name="最大回撤",
        formula="max(1 - 当日净值 / 期间最高净值)",
        annualized=False,
        unit="%",
        higher_is_better=False,
        category="risk",
        description="回测期间净值从峰值到谷底的最大跌幅。",
    ),
    "drawdown_duration": MetricDefinition(
        name="drawdown_duration",
        display_name="平均回撤持续期",
        formula="处于回撤期的平均连续天数",
        annualized=False,
        unit="days",
        higher_is_better=False,
        category="risk",
        description="从回撤开始到创出新高的平均天数。",
    ),
    "underwater_ratio": MetricDefinition(
        name="underwater_ratio",
        display_name="水下时间占比",
        formula="处于回撤期的天数 / 总交易天数",
        annualized=False,
        unit="%",
        higher_is_better=False,
        category="risk",
        description="净值处于前期高点下方的交易日占比。",
    ),
    "n_trades": MetricDefinition(
        name="n_trades",
        display_name="交易笔数",
        formula="完成的买卖配对数量",
        annualized=False,
        unit="",
        higher_is_better=False,
        category="trade",
        description="回测期间完成的总交易笔数。",
    ),
    "n_signals": MetricDefinition(
        name="n_signals",
        display_name="信号次数",
        formula="非零信号的数量",
        annualized=False,
        unit="",
        higher_is_better=False,
        category="trade",
        description="回测期间发出的非零信号次数。",
    ),
    # ─── 风险调整收益类 (Risk-Adjusted) ─────────────────────────
    "sharpe": MetricDefinition(
        name="sharpe",
        display_name="夏普比率",
        formula="(年化收益率 - 无风险利率) / 年化波动率",
        annualized=True,
        unit="ratio",
        higher_is_better=True,
        category="risk_adjusted",
        description="单位波动率所获得的超额收益。",
    ),
    "sortino": MetricDefinition(
        name="sortino",
        display_name="索提诺比率",
        formula="(年化收益率 - 无风险利率) / 下行波动率",
        annualized=True,
        unit="ratio",
        higher_is_better=True,
        category="risk_adjusted",
        description="仅考虑下行风险的夏普比率改进版。",
    ),
    "calmar": MetricDefinition(
        name="calmar",
        display_name="卡尔玛比率",
        formula="年化收益率 / 最大回撤",
        annualized=True,
        unit="ratio",
        higher_is_better=True,
        category="risk_adjusted",
        description="收益与最大回撤的比率。",
    ),
    # ─── 交易统计类 (Trade) ─────────────────────────────────────
    "win_rate": MetricDefinition(
        name="win_rate",
        display_name="胜率",
        formula="盈利交易笔数 / 总交易笔数",
        annualized=False,
        unit="%",
        higher_is_better=True,
        category="trade",
        description="盈利交易占总交易的比例。",
    ),
    "profit_factor": MetricDefinition(
        name="profit_factor",
        display_name="盈亏比",
        formula="总盈利 / 总亏损",
        annualized=False,
        unit="ratio",
        higher_is_better=True,
        category="trade",
        description="总盈利金额与总亏损金额的比值。",
    ),
    "avg_trade_return": MetricDefinition(
        name="avg_trade_return",
        display_name="平均单笔收益率",
        formula="总盈亏 / 交易笔数",
        annualized=False,
        unit="%",
        higher_is_better=True,
        category="trade",
        description="每笔交易的平均收益率。",
    ),
    # ─── 恢复类 (Recovery) ──────────────────────────────────────
    "recovery_factor": MetricDefinition(
        name="recovery_factor",
        display_name="恢复因子",
        formula="总收益率 / 最大回撤",
        annualized=False,
        unit="ratio",
        higher_is_better=True,
        category="recovery",
        description="收益与回撤的比率，反映风险补偿能力。",
    ),
    "pain_index": MetricDefinition(
        name="pain_index",
        display_name="痛苦指数",
        formula="(1/N) × Σ(回撤深度² × 持续期权重)",
        annualized=False,
        unit="ratio",
        higher_is_better=False,
        category="recovery",
        description="回撤深度×水下持续期的累积加权值，综合衡量持仓体验。",
    ),
    "avg_recovery_days": MetricDefinition(
        name="avg_recovery_days",
        display_name="平均恢复天数",
        formula="从回撤谷底到净值创新高的平均天数",
        annualized=False,
        unit="days",
        higher_is_better=False,
        category="recovery",
        description="每次回撤后恢复到前期高点的平均用时。",
    ),
    # ─── 信息类 (Info) ──────────────────────────────────────────
    "alpha": MetricDefinition(
        name="alpha",
        display_name="阿尔法",
        formula="实际收益 - (无风险利率 + beta × (市场收益 - 无风险利率))",
        annualized=True,
        unit="%",
        higher_is_better=True,
        category="info",
        description="超越基准的超额收益。",
    ),
    "beta": MetricDefinition(
        name="beta",
        display_name="贝塔",
        formula="Cov(策略收益, 市场收益) / Var(市场收益)",
        annualized=False,
        unit="ratio",
        higher_is_better=False,
        category="info",
        description="策略收益相对于市场收益的敏感度。",
    ),
    "information_ratio": MetricDefinition(
        name="information_ratio",
        display_name="信息比率",
        formula="(策略年化收益率 - 基准年化收益率) / 跟踪误差",
        annualized=True,
        unit="ratio",
        higher_is_better=True,
        category="info",
        description="单位跟踪误差所获得的超额收益。",
    ),
}


# ══════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════


def get_metric(name: str) -> MetricDefinition:
    """按名称获取指标定义。

    Args:
        name: 指标名称。

    Returns:
        MetricDefinition: 指标定义。

    Raises:
        KeyError: 未找到该指标。
    """
    if name not in METRIC_DEFINITIONS:
        raise KeyError(
            f"未找到指标 '{name}'。可用指标: {sorted(METRIC_DEFINITIONS.keys())}"
        )
    return METRIC_DEFINITIONS[name]


def list_metrics_by_category(
    category: str,
) -> List[MetricDefinition]:
    """按分类列出指标。

    Args:
        category: 指标分类名称（return / risk / risk_adjusted / trade / recovery / info）。

    Returns:
        List[MetricDefinition]: 该分类下的指标列表。
    """
    return [
        m for m in METRIC_DEFINITIONS.values() if m.category == category
    ]


def all_metric_names() -> List[str]:
    """返回所有指标名称的排序列表。"""
    return sorted(METRIC_DEFINITIONS.keys())
