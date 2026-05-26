"""
墨枢 - P2-21 性能报告脚本

从 BacktestResult 生成格式化文本报告，
支持单策略和多策略对比报告。

输出格式:
  交易次数 / 收益率 / 夏普 / 最大回撤 / 年化 / 胜率 / 盈亏比
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backtest.backtest_engine import BacktestResult


# ═══════════════════════════════════════════════════════════════
# 报告目录
# ═══════════════════════════════════════════════════════════════

_REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "backtest_results", "reports",
)


# ═══════════════════════════════════════════════════════════════
# 指标提取工具
# ═══════════════════════════════════════════════════════════════


def _safe_get(metrics: Dict[str, Any], key: str, fmt: Optional[str] = None) -> str:
    """安全提取指标值并格式化。"""
    val = metrics.get(key)
    if val is None:
        return "N/A"
    try:
        val_f = float(val)
        if fmt:
            return f"{val_f:{fmt}}"
        return str(val_f)
    except (ValueError, TypeError):
        return str(val)


def _divider(char: str = "─", width: int = 72) -> str:
    """生成分隔线。"""
    return char * width


# ═══════════════════════════════════════════════════════════════
# 指标格式化常量
# ═══════════════════════════════════════════════════════════════

_METRIC_LABELS: List[Tuple[str, str, str]] = [
    ("total_trades",        "交易次数",       ">8"),
    ("total_return_pct",    "总收益率(%)",    ">8.2f"),
    ("annual_return_pct",   "年化收益率(%)",  ">8.2f"),
    ("sharpe_ratio",        "夏普比率",       ">8.4f"),
    ("max_drawdown_pct",    "最大回撤(%)",    ">8.4f"),
    ("win_rate_pct",        "胜率(%)",        ">8.2f"),
    ("profit_loss_ratio",   "盈亏比",         ">8.4f"),
    ("volatility",          "波动率",         ">8.6f"),
    ("sortino_ratio",       "索提诺比率",     ">8.4f"),
    ("calmar_ratio",        "卡玛比率",       ">8.4f"),
    ("max_consecutive_wins", "连续盈利次数",  ">8"),
    ("max_consecutive_losses", "连续亏损次数",">8"),
    ("var_95_pct",          "VaR(95%)",      ">8.4f"),
]


# ═══════════════════════════════════════════════════════════════
# 单策略报告
# ═══════════════════════════════════════════════════════════════


def generate_trend_report(
    result: BacktestResult,
    title: Optional[str] = None,
    include_details: bool = False,
) -> str:
    """
    从 BacktestResult 生成格式化的文本报告。

    参数
    ----------
    result : BacktestResult
        回测结果对象。
    title : str, optional
        报告标题。默认为 "趋势回测报告"。
    include_details : bool
        是否包含详细信息（持仓明细等）。

    返回
    -------
    str
        格式化后的文本报告。
    """
    if title is None:
        title = "趋势回测报告"

    metrics = result.metrics
    cfg = result.config

    lines: List[str] = []
    lines.append(f"{'=' * 72}")
    lines.append(f"  {title}")
    lines.append(f"{'=' * 72}")
    lines.append("")

    # ── 基本信息 ─────────────────────────────────────
    lines.append(f"  [i] 基本信息")
    lines.append(f"  {_divider('─', 40)}")
    lines.append(f"    回测区间:    {result.start_date} ~ {result.end_date}")
    lines.append(f"    交易天数:    {result.total_bars}")
    lines.append(f"    初始资金:    ¥{cfg.initial_capital:,.2f}")
    lines.append(f"    最终权益:    ¥{_safe_get(metrics, 'final_equity', '.2f')}")
    lines.append(f"    手续费率:    {cfg.fee_rate:.4%}")
    lines.append(f"    滑点率:      {cfg.slippage_rate:.4%}")
    lines.append("")

    # ── 核心指标 ─────────────────────────────────────
    lines.append(f"  [*] 核心绩效指标")
    lines.append(f"  {_divider('─', 40)}")
    for key, label, fmt in _METRIC_LABELS:
        val_str = _safe_get(metrics, key, fmt)
        lines.append(f"    {label:　<12}: {val_str}")
    lines.append("")

    # ── 详细信息 ─────────────────────────────────────
    if include_details and result.trades:
        lines.append(f"  [Trade] 交易明细")
        lines.append(f"  {_divider('─', 60)}")
        for i, trade in enumerate(result.trades):
            symbol = trade.get("symbol", "N/A")
            side = trade.get("side", "N/A")
            qty = trade.get("quantity", 0)
            price = trade.get("price", 0)
            pnl = trade.get("realized_pnl", 0)
            date = trade.get("date", "N/A")
            lines.append(
                f"    #{i+1:>3}  {date}  "
                f"{side:>5}  {qty:>6}股  "
                f"¥{price:<8.2f}  PnL: ¥{pnl:<+10.2f}"
            )
        lines.append("")

    # ── 收益曲线摘要 ─────────────────────────────────
    if result.equity_curve:
        eq_points = result.equity_curve
        first_eq = eq_points[0]["total_equity"]
        last_eq = eq_points[-1]["total_equity"]
        peak_eq = max(p["total_equity"] for p in eq_points)
        low_eq = min(p["total_equity"] for p in eq_points)

        lines.append(f"  [Chart] 权益曲线摘要")
        lines.append(f"  {_divider('─', 40)}")
        lines.append(f"    起始权益:    ¥{first_eq:>12,.2f}")
        lines.append(f"    峰值权益:    ¥{peak_eq:>12,.2f}")
        lines.append(f"    谷值权益:    ¥{low_eq:>12,.2f}")
        lines.append(f"    终值权益:    ¥{last_eq:>12,.2f}")
        lines.append("")

    lines.append(f"{'=' * 72}")
    lines.append(f"  报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"{'=' * 72}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 多策略对比报告
# ═══════════════════════════════════════════════════════════════


def generate_trend_report_batch(
    results: List[BacktestResult],
    tags: Optional[List[str]] = None,
) -> str:
    """
    生成多策略对比的表格报告。

    参数
    ----------
    results : List[BacktestResult]
        多个回测结果对象列表。
    tags : List[str], optional
        策略标签列表。默认使用 result.config.tag。

    返回
    -------
    str
        格式化后的对比报告。
    """
    if not results:
        return "[batch] 未提供回测结果。\n"

    if tags is None:
        tags = [
            getattr(r.config, "tag", f"Strategy {i+1}")
            for i, r in enumerate(results)
        ]

    # 确保 tags 和 results 长度一致
    if len(tags) < len(results):
        tags += [f"Strategy {i+1}" for i in range(len(tags), len(results))]

    lines: List[str] = []
    lines.append(f"{'=' * 80}")
    lines.append(f"  墨枢 · 多策略对比报告")
    lines.append(f"{'=' * 80}")
    lines.append("")

    # ── 表头 ─────────────────────────────────────────
    header_metrics = [
        ("total_trades",        "交易次数",       ">10"),
        ("total_return_pct",    "总收益率%",      ">10.2f"),
        ("annual_return_pct",   "年化收益率%",    ">10.2f"),
        ("sharpe_ratio",        "夏普比率",       ">10.4f"),
        ("max_drawdown_pct",    "最大回撤%",      ">10.4f"),
        ("win_rate_pct",        "胜率%",          ">10.2f"),
        ("profit_loss_ratio",   "盈亏比",         ">10.4f"),
    ]

    # 计算每列宽度
    col_width = max(len(t) for t in tags) + 2
    col_width = max(col_width, 12)

    header = f"  {'策略':>{col_width}}"
    separator = f"  {'─' * col_width}"
    for _, label, _ in header_metrics:
        header += f"  {label:>10}"
        separator += f"  {'─' * 10}"
    lines.append(header)
    lines.append(separator)

    # ── 数据行 ───────────────────────────────────────
    for tag, result in zip(tags, results):
        metrics = result.metrics
        row = f"  {tag:>{col_width}}"
        for key, _, fmt in header_metrics:
            val_str = _safe_get(metrics, key, fmt)
            row += f"  {val_str:>10}"
        lines.append(row)

    lines.append("")
    lines.append(f"{'─' * 80}")
    lines.append("")

    # ── 各策略详细指标 ──────────────────────────────
    for tag, result in zip(tags, results):
        metrics = result.metrics
        lines.append(f"  [Strategy] {tag}")
        lines.append(f"  {_divider('─', 50)}")
        for key, label, fmt in _METRIC_LABELS:
            val_str = _safe_get(metrics, key, fmt)
            lines.append(f"    {label:　<12}: {val_str}")
        # 基本信息
        cfg = result.config
        lines.append(f"    回测区间:    {result.start_date} ~ {result.end_date}")
        lines.append(f"    初始资金:    ¥{cfg.initial_capital:,.2f}")
        lines.append(f"    最终权益:    ¥{_safe_get(metrics, 'final_equity', '.2f')}")
        lines.append("")

    lines.append(f"{'=' * 80}")
    lines.append(f"  报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"{'=' * 80}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 报告保存工具
# ═══════════════════════════════════════════════════════════════


def save_report(
    report_text: str,
    filepath: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """
    将报告文本保存到文件。

    参数
    ----------
    report_text : str
        报告文本内容。
    filepath : str, optional
        完整文件路径。优先级高于 filename。
    filename : str, optional
        仅文件名（自动拼接报告目录）。

    返回
    -------
    str
        保存的文件路径。
    """
    if filepath:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    elif filename:
        os.makedirs(_REPORTS_DIR, exist_ok=True)
        filepath = os.path.join(_REPORTS_DIR, filename)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(_REPORTS_DIR, exist_ok=True)
        filepath = os.path.join(_REPORTS_DIR, f"trend_report_{timestamp}.md")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[report] 报告已保存: {filepath}")
    return filepath


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    """
    CLI 入口：运行 601857 回测并生成文本报告。
    """
    import sys

    symbol = sys.argv[1] if len(sys.argv) > 1 else "601857"
    signal_type = sys.argv[2] if len(sys.argv) > 2 else "ma"
    tag = sys.argv[3] if len(sys.argv) > 3 else f"report_{symbol}"

    print(f"[report] 运行回测: symbol={symbol}, signal={signal_type}")

    from backtest.strategies.run_trend import (
        TrendBacktestConfig,
        run_trend_backtest,
    )

    cfg = TrendBacktestConfig(
        symbol=symbol,
        signal_type=signal_type,
        tag=tag,
    )
    result = run_trend_backtest(cfg)

    report = generate_trend_report(result, title=f"趋势回测报告 - {symbol}")
    print(report)

    # 保存到文件
    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"trend_report_{symbol}_{timestamp}.md"
    save_report(report, filename=filename)


if __name__ == "__main__":
    main()
