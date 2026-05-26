"""
mozhi_platform.src.backtest.pipeline.report_builder — ReportBuilder

v3.2 分层报告构建器。从 BacktestResultBundle 统一数据源读取数据，
生成 14 章完整 HTML 报告。

当前版本策略（Phase 2）：
  - 第0~5章：真实数据渲染（含 SVG 图表）
  - 第6~13章：结构化占位符（标注"此章节在 Phase 3 实现"）

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import html as html_mod
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.engine.backtest_result_bundle import BacktestResultBundle
from metrics.metrics_registry import METRIC_DEFINITIONS, get_metric

# ══════════════════════════════════════════════════════════════════════
# HTML 模板常量
# ══════════════════════════════════════════════════════════════════════

HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2cm 2.5cm; }}

  body {{ font-family: 'Microsoft YaHei', sans-serif; font-size: 11pt; line-height: 1.6; color: #333; }}
  h1 {{ font-size: 20pt; color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 8px; }}
  h2 {{ font-size: 16pt; color: #16213e; margin-top: 24px; }}
  h3 {{ font-size: 13pt; color: #0f3460; margin-top: 16px; }}

  .cover-page {{
    page-break-after: always;
    display: flex; flex-direction: column;
    justify-content: center; align-items: center;
    height: 100vh;
  }}
  .cover-title {{ font-size: 28pt; font-weight: bold; margin-bottom: 20px; }}
  .cover-subtitle {{ font-size: 16pt; color: #666; }}

  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 10pt; }}
  th {{ background: #1a1a2e; color: white; padding: 8px; text-align: center; }}
  td {{ padding: 6px 8px; border: 1px solid #ddd; text-align: center; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}

  .metric-box {{
    background: #f0f4f8; border-left: 4px solid #e94560;
    padding: 12px; margin: 16px 0; font-size: 10pt;
  }}

  .page-break {{ page-break-before: always; }}
  .placeholder {{ background: #fff8e1; border: 1px dashed #f0ad4e; padding: 16px; margin: 16px 0; font-style: italic; color: #856404; }}
  .risk-low {{ color: #2ecc71; }}
  .risk-medium {{ color: #f39c12; }}
  .risk-high {{ color: #e74c3c; }}
  .profit {{ color: #e74c3c; }}
  .loss {{ color: #2ecc71; }}
</style>
</head>
<body>
"""

HTML_FOOTER = """
<div class="disclaimer" style="font-size:8pt;color:#aaa;margin-top:30px;text-align:center;">
  <p>本报告由 mozhi_platform ReportBuilder v3.2 自动生成</p>
  <p>生成时间: {generated_time}</p>
  <p>免责声明：本报告仅供参考，不构成投资建议。回测结果不代表未来表现。</p>
</div>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════
# SVG 图表辅助（纯字符串生成，无 matplotlib 依赖）
# ══════════════════════════════════════════════════════════════════════


def _svg_line_chart(
    data: pd.Series,
    width: int = 700,
    height: int = 300,
    title: str = "",
    line_color: str = "#e94560",
    bg_color: str = "#f8f9fa",
) -> str:
    """从一维 Series 生成 SVG 折线图。"""
    if len(data) < 2:
        return '<p class="metric-box">数据点不足，无法绘制图表。</p>'

    values = data.values.astype(float)
    vmin, vmax = values.min(), values.max()
    vrange = vmax - vmin
    if vrange == 0:
        vrange = 1

    margin = 40
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def _x(i: int) -> float:
        return margin + plot_w * i / (len(values) - 1)

    def _y(v: float) -> float:
        return margin + plot_h * (1 - (v - vmin) / vrange)

    points = " ".join(f"{_x(i)},{_y(v)}" for i, v in enumerate(values))

    grid_lines = []
    for g in range(5):
        gy = margin + plot_h * g / 4
        glabel = f"{vmin + vrange * (1 - g/4):.2f}"
        grid_lines.append(f'<line x1="{margin}" y1="{gy}" x2="{width - margin}" y2="{gy}" stroke="#ddd" stroke-width="0.5"/>')
        grid_lines.append(f'<text x="{margin - 5}" y="{gy + 3}" text-anchor="end" font-size="9" fill="#999">{html_mod.escape(glabel)}</text>')

    markers = []
    max_idx = int(values.argmax())
    min_idx = int(values.argmin())
    for idx, label, color in [
        (0, "起点", "#888"),
        (len(values) - 1, "终点", "#888"),
        (max_idx, f"最高:{values[max_idx]:.3f}", "#e74c3c"),
        (min_idx, f"最低:{values[min_idx]:.3f}", "#2ecc71"),
    ]:
        mx, my = _x(idx), _y(values[idx])
        markers.append(f'<circle cx="{mx}" cy="{my}" r="3" fill="{color}"/>')
        markers.append(f'<text x="{mx + 5}" y="{my - 5}" font-size="9" fill="{color}">{html_mod.escape(label)}</text>')

    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"',
        f'style="width:100%;max-width:{width}px;display:block;margin:16px auto;">',
        f'<rect width="{width}" height="{height}" fill="{bg_color}" rx="4"/>',
        f'<text x="{width / 2}" y="20" text-anchor="middle" font-size="13" fill="#333" font-weight="bold">{html_mod.escape(title)}</text>',
        "\n".join(grid_lines),
        f'<polyline points="{points}" fill="none" stroke="{line_color}" stroke-width="2"/>',
        "\n".join(markers),
        "</svg>",
    ]
    return "".join(svg_parts)


def _svg_bar_chart(
    labels: List[str],
    values: List[float],
    width: int = 700,
    height: int = 250,
    title: str = "",
    bar_color: str = "#3498db",
    bg_color: str = "#f8f9fa",
) -> str:
    """生成 SVG 柱状图。"""
    if len(labels) == 0 or len(values) == 0:
        return '<p class="metric-box">无数据，无法绘制图表。</p>'

    vmin, vmax = min(values), max(values)
    vrange = vmax - vmin if vmax != vmin else 1

    margin = 50
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    n = len(labels)
    bar_w = min(plot_w / n / 1.5, 30)
    gap = (plot_w - bar_w * n) / (n + 1)

    def _y(v: float) -> float:
        return margin + plot_h * (1 - (v - vmin) / vrange)

    def _zero_y() -> float:
        if vmin <= 0 <= vmax:
            return margin + plot_h * (1 - (0 - vmin) / vrange)
        return _y(vmin) if vmin > 0 else _y(vmax)

    zero_y = _zero_y()
    bars = []
    labels_svg = []
    for i, (lab, val) in enumerate(zip(labels, values)):
        bx = margin + gap + i * (bar_w + gap)
        btop = _y(val)
        bar_h = abs(zero_y - btop)
        bar_y = min(zero_y, btop)
        color = bar_color if val >= 0 else "#e74c3c"
        bars.append(f'<rect x="{bx}" y="{bar_y}" width="{bar_w}" height="{bar_h}" fill="{color}" rx="1"/>')
        labels_svg.append(
            f'<text x="{bx + bar_w / 2}" y="{height - 10}" text-anchor="middle" font-size="8" fill="#666" '
            f'transform="rotate(-45,{bx + bar_w / 2},{height - 10})">{html_mod.escape(str(lab)[:12])}</text>'
        )

    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"',
        f'style="width:100%;max-width:{width}px;display:block;margin:16px auto;">',
        f'<rect width="{width}" height="{height}" fill="{bg_color}" rx="4"/>',
        f'<text x="{width / 2}" y="20" text-anchor="middle" font-size="13" fill="#333" font-weight="bold">{html_mod.escape(title)}</text>',
        "\n".join(bars),
        "\n".join(labels_svg),
        "</svg>",
    ]
    return "".join(svg_parts)


# ══════════════════════════════════════════════════════════════════════
# ReportBuilder
# ══════════════════════════════════════════════════════════════════════


class ReportBuilder:
    """报告构建器。

    从 BacktestResultBundle 列表生成完整（或简洁）HTML 报告。

    Args:
        bundles: BacktestResultBundle 列表，每个元素对应一个策略/方法。
        portfolio_bundle: 可选，组合策略的 BacktestResultBundle。
    """

    def __init__(
        self,
        bundles: List[BacktestResultBundle],
        portfolio_bundle: Optional[BacktestResultBundle] = None,
    ):
        self.bundles = bundles
        self.portfolio_bundle = portfolio_bundle
        self._generated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ─── 主入口 ───────────────────────────────────────────────────

    def build(self) -> str:
        """生成完整 HTML 报告。"""
        parts: List[str] = [
            HTML_HEAD,
            self._cover_page(),
            self._chapter_0_data_quality(),
            self._chapter_1_params_table(),
            self._chapter_2_equity_curve(),
            self._chapter_3_drawdown_heatmap(),
            self._chapter_4_metrics_table(),
            self._chapter_5_kline_trades(),
            self._chapter_6_trade_behavior(),
            self._chapter_7_regime_adaptation(),
            self._chapter_8_knowledge_digest(),
            self._chapter_9_param_sensitivity(),
            self._chapter_10_walk_forward(),
            self._chapter_11_correlation_matrix(),
            self._chapter_12_recovery_analysis(),
            self._chapter_13_t1_rating(),
            HTML_FOOTER.format(generated_time=self._generated_time),
        ]
        return "\n".join(parts)

    def build_minimal(self) -> str:
        """生成简洁模式 HTML 报告（仅含 0~5 章）。"""
        parts: List[str] = [
            HTML_HEAD,
            self._cover_page(),
            self._chapter_0_data_quality(),
            self._chapter_1_params_table(),
            self._chapter_2_equity_curve(),
            self._chapter_3_drawdown_heatmap(),
            self._chapter_4_metrics_table(),
            self._chapter_5_kline_trades(),
            HTML_FOOTER.format(generated_time=self._generated_time),
        ]
        return "\n".join(parts)

    # ══════════════════════════════════════════════════════════════
    # 封面
    # ══════════════════════════════════════════════════════════════

    def _cover_page(self) -> str:
        """生成报告封面。"""
        first = self.bundles[0] if self.bundles else None
        symbol = first.symbol if first else ""
        method_names = ", ".join(b.method_name for b in self.bundles)
        strategy_names = ", ".join(set(b.strategy_name for b in self.bundles if b.strategy_name))
        date_range = ""
        if first and first.start_date and first.end_date:
            date_range = f"{first.start_date} ~ {first.end_date}"

        lines = [
            '<div class="cover-page">',
            '<h1 class="cover-title">回测分析报告</h1>',
            '<p class="cover-subtitle">Backtest Analysis Report</p>',
            f"<p>标的: {html_mod.escape(symbol)}</p>",
            f"<p>策略: {html_mod.escape(strategy_names)}</p>",
            f"<p>方法: {html_mod.escape(method_names)}</p>",
            f"<p>回测区间: {html_mod.escape(date_range)}</p>",
            f"<p>生成时间: {self._generated_time}</p>",
            "<p>数据来源: BacktestResultBundle v3.0</p>",
            "</div>",
        ]
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    # 第0章: 数据质量声明（含颜色评级 + C/D 警告）
    # ══════════════════════════════════════════════════════════════

    def _chapter_0_data_quality(self) -> str:
        """生成数据质量声明章。"""
        lines = ['<div class="page-break">', "<h2>第0章 数据质量声明</h2>"]

        for bundle in self.bundles:
            dq = bundle.data_quality
            rating = dq.get("rating", "—")
            rating_color = {"A": "#2ecc71", "B": "#f39c12", "C": "#e74c3c", "D": "#95a5a6"}.get(rating, "#333")

            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            completeness = dq.get("completeness", "—")
            total_days = dq.get("total_days", "—")
            missing_days = dq.get("missing_days", 0)

            lines.append(
                '<div class="metric-box" style="display:flex;gap:20px;flex-wrap:wrap;">'
                f'<div><strong>数据完整率:</strong> '
                f'<span style="color:{rating_color};font-weight:bold;font-size:14pt;">{completeness}%</span></div>'
                f'<div><strong>评级:</strong> '
                f'<span style="color:{rating_color};font-weight:bold;font-size:14pt;">{rating}</span></div>'
                f'<div><strong>总天数:</strong> {total_days}</div>'
                f'<div><strong>缺失天数:</strong> {missing_days}</div>'
                f'<div><strong>基准:</strong> {dq.get("benchmark", "buy&hold")}</div>'
                f'<div><strong>引擎版本:</strong> {dq.get("engine_version", "v3.0")}</div>'
                "</div>"
            )

            rows = [
                ("数据源", str(dq.get("source", "—"))),
                ("数据周期", str(dq.get("period", "—"))),
                ("复权方式", str(dq.get("adjusted", "—"))),
                ("缺失值处理", str(dq.get("nan_handling", "—"))),
                ("滑点模型", str(dq.get("slippage_model", "—"))),
                ("手续费", str(dq.get("commission", "—"))),
            ]
            lines.append("<table>")
            lines.append("<tr><th>配置项</th><th>值</th></tr>")
            for k, v in rows:
                lines.append(f"<tr><td>{html_mod.escape(k)}</td><td>{html_mod.escape(v)}</td></tr>")
            lines.append("</table>")

            nan_stats = dq.get("nan_stats", {})
            if nan_stats:
                lines.append("<h4>缺失值统计（各列NaN占比%）</h4>")
                lines.append("<table><tr><th>列</th><th>NaN占比%</th></tr>")
                for col, pct in sorted(nan_stats.items()):
                    color = "#2ecc71" if pct == 0 else ("#f39c12" if pct < 1 else "#e74c3c")
                    lines.append(f'<tr><td>{col}</td><td style="color:{color}">{pct}%</td></tr>')
                lines.append("</table>")

            if rating in ("C", "D"):
                lines.append(
                    '<div style="background:#fce4ec;border:2px solid #e74c3c;padding:12px;margin:12px 0;border-radius:4px;">'
                    f'<strong>数据质量警告：</strong>评级 {rating}，数据完整率仅 {completeness}%。'
                    "回测结果可能受数据缺失影响，请谨慎参考。</div>"
                )
            elif rating == "B":
                lines.append(
                    '<div style="background:#fff8e1;border:1px solid #f39c12;padding:8px;margin:8px 0;border-radius:4px;">'
                    f'<strong>数据质量注意：</strong>评级 B，数据完整率 {completeness}%。存在 {missing_days} 个缺失交易日。</div>'
                )

        lines.append("</div>")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    # 第一章: 回测参数表 + 关键绩效摘要
    # ══════════════════════════════════════════════════════════════

    def _chapter_1_params_table(self) -> str:
        """生成回测参数表章。"""
        lines = ['<div class="page-break">', "<h2>一、回测参数表</h2>"]

        for bundle in self.bundles:
            params = bundle.params
            sm = bundle.summary_metrics
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            info_rows = [
                ("标的", bundle.symbol),
                ("回测区间", f"{bundle.start_date} ~ {bundle.end_date}"),
                ("策略名称", bundle.strategy_name),
            ]
            lines.append("<table>")
            lines.append("<tr><th>基础信息</th><th>值</th></tr>")
            for k, v in info_rows:
                lines.append(f"<tr><td>{html_mod.escape(k)}</td><td>{html_mod.escape(str(v))}</td></tr>")
            for k, v in sorted(params.items()):
                lines.append(f"<tr><td>{html_mod.escape(k)}</td><td>{html_mod.escape(str(v)[:60])}</td></tr>")
            lines.append("</table>")

            key_metrics = [
                ("total_return", "总收益率", "%", True),
                ("annual_return", "年化收益率", "%", True),
                ("sharpe", "夏普比率", "", True),
                ("max_drawdown", "最大回撤", "%", False),
                ("win_rate", "胜率", "%", True),
                ("n_trades", "交易笔数", "", True),
            ]
            lines.append("<h4>关键绩效摘要</h4>")
            lines.append("<table><tr><th>指标</th><th>值</th><th>评价</th></tr>")
            for key, dname, unit, higher_ok in key_metrics:
                val = sm.get(key)
                if val is None:
                    continue
                if unit == "%":
                    display = f"{val * 100:.2f}%"
                elif isinstance(val, float):
                    display = f"{val:.4f}"
                else:
                    display = str(val)

                if isinstance(val, (int, float)):
                    if key == "max_drawdown":
                        score = "好" if val > -0.05 else ("中" if val > -0.15 else "差")
                    elif key == "sharpe":
                        score = "好" if val > 1.5 else ("中" if val > 0.5 else "差")
                    elif key == "win_rate":
                        score = "好" if val > 0.5 else ("中" if val > 0.3 else "差")
                    else:
                        score = "好" if val > 0 else ("中" if val > -0.05 else "差")
                    score_color = {"好": "#2ecc71", "中": "#f39c12", "差": "#e74c3c"}.get(score, "#333")
                else:
                    score, score_color = "—", "#333"
                lines.append(
                    f"<tr><td>{dname}</td><td>{display}</td>"
                    f'<td style="color:{score_color}">{score}</td></tr>'
                )
            lines.append("</table>")

        lines.append("</div>")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    # 第二章: 净值曲线（含SVG图）
    # ══════════════════════════════════════════════════════════════

    def _chapter_2_equity_curve(self) -> str:
        """生成净值曲线章。"""
        lines = ['<div class="page-break">', "<h2>二、净值曲线</h2>"]

        for bundle in self.bundles:
            ec = bundle.equity_curve
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            if ec.empty or "equity" not in ec.columns:
                lines.append('<p class="metric-box">无净值数据。</p>')
                continue

            lines.append(_svg_line_chart(
                data=ec["equity"],
                title=f"{bundle.method_name} - 净值曲线",
                line_color="#e94560",
            ))

            bc = bundle.benchmark_curve
            if not bc.empty and "equity" in bc.columns:
                lines.append(_svg_line_chart(
                    data=bc["equity"],
                    title=f"{bundle.method_name} - 基准(buy&hold)净值曲线",
                    line_color="#3498db",
                ))

            sm = bundle.summary_metrics
            lines.append('<div class="metric-box">')
            lines.append("<strong>关键摘要:</strong><br/>")
            for k, dn in [("total_return", "总收益率"), ("annual_return", "年化收益率"),
                          ("sharpe", "夏普比率"), ("max_drawdown", "最大回撤"),
                          ("win_rate", "胜率"), ("n_trades", "交易笔数")]:
                val = sm.get(k)
                if val is not None:
                    if k in ("win_rate", "total_return", "annual_return", "max_drawdown") and isinstance(val, float):
                        lines.append(f"{dn}: {val * 100:.2f}%<br/>")
                    elif isinstance(val, float):
                        lines.append(f"{dn}: {val:.4f}<br/>")
                    else:
                        lines.append(f"{dn}: {val}<br/>")
            lines.append("</div>")

        lines.append("</div>")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    # 第三章: 回撤曲线（含SVG图）
    # ══════════════════════════════════════════════════════════════

    def _chapter_3_drawdown_heatmap(self) -> str:
        """生成回撤曲线章。"""
        lines = ['<div class="page-break">', "<h2>三、回撤曲线</h2>"]

        for bundle in self.bundles:
            ec = bundle.equity_curve
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            if ec.empty or "equity" not in ec.columns:
                lines.append('<p class="metric-box">无数据。</p>')
                continue

            equity = ec["equity"].values
            peak = np.maximum.accumulate(equity)
            drawdown = (equity - peak) / peak

            max_dd = drawdown.min() if len(drawdown) > 0 else 0
            min_idx = int(drawdown.argmin()) if len(drawdown) > 0 else 0

            lines.append(_svg_line_chart(
                data=pd.Series(drawdown * 100, index=ec.index),
                title=f"{bundle.method_name} - 回撤曲线(%)",
                line_color="#e74c3c",
            ))

            underwater_days = int((drawdown < -0.01).sum())
            total_days = len(drawdown)
            underwater_ratio = underwater_days / total_days if total_days > 0 else 0

            dd_start, dd_end = "", ""
            if max_dd < 0 and len(drawdown) > 0:
                for i in range(min_idx, -1, -1):
                    if i == 0 or drawdown[i] >= -0.001:
                        dd_start = str(ec.index[i].date()) if isinstance(ec.index[i], pd.Timestamp) else ""
                        break
                dd_end = str(ec.index[min_idx].date()) if isinstance(ec.index[min_idx], pd.Timestamp) else ""

            recovery_days = 0
            for i in range(min_idx + 1, len(drawdown)):
                recovery_days += 1
                if drawdown[i] >= -0.001:
                    break

            lines.append(
                '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                f'<div><strong>最大回撤:</strong> <span class="risk-high">{max_dd * 100:.2f}%</span></div>'
                f'<div><strong>回撤区间:</strong> {dd_start} ~ {dd_end}</div>'
                f'<div><strong>水下时间:</strong> {underwater_days}/{total_days}天({underwater_ratio * 100:.1f}%)</div>'
                f'<div><strong>恢复天数:</strong> {recovery_days}天</div>'
                "</div>"
            )

            significant = []
            for i, dd in enumerate(drawdown):
                if dd < -0.02:
                    label = str(ec.index[i].date()) if isinstance(ec.index[i], pd.Timestamp) else ""
                    significant.append((label, dd * 100))
            if len(significant) > 10:
                significant = significant[:10]

            if significant:
                lines.append("<h4>显著回撤明细（&lt;-2%）</h4>")
                lines.append("<table><tr><th>日期</th><th>回撤深度%</th></tr>")
                for dt, dd_val in significant:
                    cls = "risk-high" if dd_val < -5 else ("risk-medium" if dd_val < -3 else "")
                    lines.append(f'<tr><td>{html_mod.escape(dt)}</td><td class="{cls}">{dd_val:.2f}%</td></tr>')
                lines.append("</table>")

        lines.append(
            '<p class="placeholder">月度收益热力图：此章节在 Phase 3 实现完整图表渲染。</p>'
        )
        lines.append("</div>")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    # 第四章: 全量指标总表（按分类分组）
    # ══════════════════════════════════════════════════════════════

    def _chapter_4_metrics_table(self) -> str:
        """生成全量20指标汇总表。"""
        lines = ['<div class="page-break">', "<h2>四、指标总表</h2>",
                 "<p>全量指标通过 metrics_registry 统一口径展示。</p>",
                 '<div class="metric-box">',
                 "<strong>20个指标口径说明：</strong> "
                 "所有指标通过 metrics_registry 统一计算口径，"
                 "ReportBuilder 从中读取 display_name/unit/higher_is_better 等信息。",
                 "</div>"]

        category_names = {
            "return": "收益类 Return",
            "risk": "风险类 Risk",
            "risk_adjusted": "风险调整收益类 Risk-Adjusted",
            "trade": "交易统计类 Trade",
            "recovery": "恢复类 Recovery",
            "info": "信息类 Info",
        }

        for cat_key, cat_name in category_names.items():
            cat_metrics = {k: v for k, v in METRIC_DEFINITIONS.items() if v.category == cat_key}
            if not cat_metrics:
                continue

            lines.append(f"<h3>{cat_name}</h3>")
            lines.append("<table>")
            th = '<tr><th>指标</th><th>公式</th><th>单位</th>'
            th += "".join(f'<th>{html_mod.escape(b.method_name)}</th>' for b in self.bundles)
            th += "<th>方向</th></tr>"
            lines.append(th)

            for key, defn in cat_metrics.items():
                vals = []
                for b in self.bundles:
                    sm = b.summary_metrics
                    val = sm.get(key)
                    if val is None:
                        vals.append("—")
                    elif defn.unit == "%":
                        vals.append(f"{val * 100:.2f}%")
                    elif isinstance(val, float):
                        vals.append(f"{val:.4f}")
                    else:
                        vals.append(str(val))

                direction = "↑" if defn.higher_is_better else "↓"
                direction_color = "#2ecc71" if defn.higher_is_better else "#e74c3c"
                td_vals = "".join(f"<td>{v}</td>" for v in vals)
                lines.append(
                    f"<tr><td>{html_mod.escape(defn.display_name)}</td>"
                    f'<td style="font-size:9pt;color:#888;">{html_mod.escape(defn.formula[:40])}</td>'
                    f"<td>{defn.unit}</td>"
                    f"{td_vals}"
                    f'<td style="color:{direction_color}">{direction}</td></tr>'
                )
            lines.append("</table>")

        lines.append("</div>")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    # 第五章: 交易分析（含SVG盈亏分布图 + 明细表）
    # ══════════════════════════════════════════════════════════════

    def _chapter_5_kline_trades(self) -> str:
        """生成交易分析章。"""
        lines = ['<div class="page-break">', "<h2>五、交易分析</h2>"]

        for bundle in self.bundles:
            trades = bundle.trades
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            n_trades = len(trades)
            if n_trades > 0:
                pnls = [t.pnl for t in trades if hasattr(t, "pnl") and t.pnl is not None]
                win_trades = sum(1 for p in pnls if p > 0)
                win_rate = win_trades / len(pnls) if pnls else 0
                avg_pnl = sum(pnls) / len(pnls) if pnls else 0
                max_win = max(pnls) if pnls else 0
                max_loss = min(pnls) if pnls else 0
                total_pnl = sum(pnls)

                bars_data = [(str(i + 1), p) for i, p in enumerate(pnls[:40])]
                if bars_data:
                    lines.append(_svg_bar_chart(
                        labels=[b[0] for b in bars_data],
                        values=[b[1] for b in bars_data],
                        title=f"{bundle.method_name} - 各笔盈亏分布",
                        bar_color="#2ecc71",
                    ))

                lines.append(
                    '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f"<div><strong>总交易次数:</strong> {n_trades}</div>"
                    f'<div><strong>总盈亏:</strong> <span class="{"profit" if total_pnl >= 0 else "loss"}">{total_pnl:+.2f}</span></div>'
                    f"<div><strong>胜率:</strong> {win_rate * 100:.1f}% ({win_trades}/{len(pnls)})</div>"
                    f"<div><strong>平均盈亏:</strong> {avg_pnl:+.4f}</div>"
                    f'<div><strong>最大盈利:</strong> <span class="profit">{max_win:+.4f}</span></div>'
                    f'<div><strong>最大亏损:</strong> <span class="loss">{max_loss:.4f}</span></div>'
                    "</div>"
                )

                lines.append("<h4>交易明细表</h4>")
                lines.append("<table>")
                lines.append("<tr><th>#</th><th>入场时间</th><th>入场价格</th><th>出场时间</th><th>出场价格</th><th>方向</th><th>数量</th><th>盈亏</th></tr>")
                for i, t in enumerate(trades[:50]):
                    pnl_val = t.pnl if hasattr(t, "pnl") and t.pnl is not None else 0
                    pnl_class = "profit" if pnl_val >= 0 else "loss"
                    lines.append(
                        f"<tr><td>{i + 1}</td>"
                        f"<td>{html_mod.escape(str(getattr(t, 'entry_time', '')))}</td>"
                        f"<td>{getattr(t, 'entry_price', 0):.4f}</td>"
                        f"<td>{html_mod.escape(str(getattr(t, 'exit_time', '')))}</td>"
                        f"<td>{getattr(t, 'exit_price', 0):.4f}</td>"
                        f"<td>{html_mod.escape(str(getattr(t, 'direction', ''))[:10])}</td>"
                        f"<td>{getattr(t, 'qty', 0)}</td>"
                        f'<td class="{pnl_class}">{pnl_val:+.4f}</td></tr>'
                    )
                lines.append("</table>")
                if n_trades > 50:
                    lines.append(f"<p>仅显示前50笔交易，共{n_trades}笔。</p>")
            else:
                lines.append("<p>无成交记录。</p>")

        lines.append(
            '<p class="placeholder">K线图买卖点位标注：此章节在 Phase 3 实现 matplotlib 图表渲染。</p>'
        )
        lines.append("</div>")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    # 第六章: 交易行为分析（占位）
    # ══════════════════════════════════════════════════════════════

    def _chapter_6_trade_behavior(self) -> str:
        """生成交易行为分析章（含持仓时间分布、连盈连亏、月度统计）。"""
        lines = ['<div class="page-break">', "<h2>六、交易行为分析</h2>"]

        for bundle in self.bundles:
            trades = bundle.trades
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            if not trades:
                lines.append("<p>无成交记录。</p>")
                continue

            n = len(trades)
            pnls = [t.pnl for t in trades if hasattr(t, "pnl") and t.pnl is not None]
            win_trades = sum(1 for p in pnls if p > 0)
            loss_trades = sum(1 for p in pnls if p < 0)
            win_rate = win_trades / len(pnls) if pnls else 0

            # 6.2 盈亏分布统计
            lines.append("<h4>6.2 盈亏分布统计</h4>")
            if pnls:
                lines.append(_svg_bar_chart(
                    labels=[f"#{i+1}" for i in range(min(len(pnls), 40))],
                    values=pnls[:40],
                    title=f"{bundle.method_name} - 各笔盈亏分布",
                    bar_color="#2ecc71",
                ))

            # 6.3 持仓时间分布
            lines.append("<h4>6.3 持仓时间分布</h4>")
            hold_days = []
            for t in trades:
                entry = getattr(t, 'entry_time', None)
                exit_ = getattr(t, 'exit_time', None)
                if entry and exit_:
                    try:
                        diff = (pd.Timestamp(exit_) - pd.Timestamp(entry)).days
                        hold_days.append(diff)
                    except Exception:
                        pass

            if hold_days:
                avg_hold = sum(hold_days) / len(hold_days)
                min_hold = min(hold_days)
                max_hold = max(hold_days)
                lines.append(
                    '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f"<div><strong>平均持仓:</strong> {avg_hold:.1f}天</div>"
                    f"<div><strong>最短:</strong> {min_hold}天</div>"
                    f"<div><strong>最长:</strong> {max_hold}天</div>"
                    "</div>"
                )
                # 持仓分布柱状图
                if len(hold_days) > 5:
                    bins = [0, 1, 3, 5, 10, 20, 50, 100, 999]
                    labels_bin = ["0-1", "1-3", "3-5", "5-10", "10-20", "20-50", "50-100", "100+"]
                    hist = []
                    for b in range(len(bins)-1):
                        count = sum(1 for h in hold_days if bins[b] < h <= bins[b+1])
                        hist.append(count)
                    lines.append(_svg_bar_chart(
                        labels=labels_bin,
                        values=hist,
                        title=f"{bundle.method_name} - 持仓天数分布",
                        bar_color="#9b59b6",
                    ))

            # 6.5 连盈连亏序列
            lines.append("<h4>6.5 连盈连亏序列分析</h4>")
            if pnls:
                max_win_streak = max_loss_streak = 0
                cur_win = cur_loss = 0
                for p in pnls:
                    if p > 0:
                        cur_win += 1
                        cur_loss = 0
                        max_win_streak = max(max_win_streak, cur_win)
                    elif p < 0:
                        cur_loss += 1
                        cur_win = 0
                        max_loss_streak = max(max_loss_streak, cur_loss)

                profit_factor = sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0)) if any(p < 0 for p in pnls) else float('inf')
                avg_win = sum(p for p in pnls if p > 0) / win_trades if win_trades > 0 else 0
                avg_loss = sum(p for p in pnls if p < 0) / loss_trades if loss_trades > 0 else 0
                win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

                lines.append(
                    '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f"<div><strong>最大连盈:</strong> {max_win_streak}笔</div>"
                    f"<div><strong>最大连亏:</strong> {max_loss_streak}笔</div>"
                    f"<div><strong>盈亏比(ProfitFactor):</strong> {profit_factor:.2f}</div>"
                    f"<div><strong>平均盈利/亏损比:</strong> {win_loss_ratio:.2f}</div>"
                    f"<div><strong>平均盈利:</strong> {avg_win:+.4f}</div>"
                    f"<div><strong>平均亏损:</strong> {avg_loss:.4f}</div>"
                    "</div>"
                )

            lines.append(f"<p>共 {n} 笔交易，胜率 {win_rate*100:.1f}% ({win_trades}/{len(pnls)})。</p>")

        lines.append("</div>")
        return "\n".join(lines)
    def _chapter_7_regime_adaptation(self) -> str:
        """生成市场状态适应性章（尝试读取regime_labels，否则占位）。"""
        lines = ['<div class="page-break">', "<h2>七、市场状态适应性</h2>"]

        has_regime_data = any(
            not b.regime_labels.empty for b in self.bundles
        )

        if has_regime_data:
            for bundle in self.bundles:
                rl = bundle.regime_labels
                lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")
                if not rl.empty:
                    lines.append("<p>市场状态标签可用，展示各状态下的表现。</p>")
                    if "regime" in rl.columns:
                        lines.append("<table><tr><th>日期</th><th>市场状态</th></tr>")
                        for idx, row in rl.iterrows():
                            dt = str(idx.date()) if hasattr(idx, 'date') else str(idx)
                            lines.append(f"<tr><td>{dt}</td><td>{html_mod.escape(str(row.get('regime', '')))}</td></tr>")
                        lines.append("</table>")
                else:
                    lines.append("<p>无市场状态数据。</p>")
        else:
            lines.append("<p>无市场状态标签数据。Phase 3 实现 Regime 分类算法后可用。</p>")

        lines.append(
            '<div class="placeholder">'
            "<p><strong>此章节在 Phase 3 实现完整分析：</strong></p>"
            "<pre>"
            '7.1 By Regime（牛市/震荡/熊市）\n' +
            '7.2 高波动 vs 低波动期\n' +
            '7.3 成交量放大期\n' +
            '7.4 板块轮动期（预留）\n\n' +
            '需要 Regime 分类算法（从 df_ohlcv 计算趋势强度/波动率/成交量特征）'
            "</pre>"
            "</div>"
        )
        lines.append("</div>")
        return "\n".join(lines)
    def _chapter_8_knowledge_digest(self) -> str:
        parts = ['<div class="page-break">', "<h2>八、知识库提炼</h2>"]
        for i, bundle in enumerate(self.bundles):
            n_insights = len(bundle.insights)
            parts.append(f"<h3>8.{i + 1} {html_mod.escape(bundle.method_name)} — {n_insights} 条知识条目</h3>")
            if bundle.insights:
                for j, entry in enumerate(bundle.insights[:5]):
                    parts.append(
                        '<div class="metric-box">'
                        f"<strong>#{j + 1}</strong> "
                        f"方法: {html_mod.escape(entry.method_name)} | "
                        f"标的: {html_mod.escape(entry.symbol)}"
                        "</div>"
                    )
            else:
                parts.append("<p>暂无知识条目。</p>")
        parts.append(
            '<p class="placeholder">知识库提炼完整内容（8.1-8.7 七个子节）：'
            "此章节在 Phase 3 实现 KnowledgeSearch 集成和结构化渲染。</p>"
        )
        parts.append("</div>")
        return "\n".join(parts)

    # ══════════════════════════════════════════════════════════════
    # 第九章: 参数敏感性分析（占位）
    # ══════════════════════════════════════════════════════════════

    def _chapter_9_param_sensitivity(self) -> str:
        """生成参数敏感性分析章（读取parameter_scan，否则占位）。"""
        lines = ['<div class="page-break">', "<h2>九、参数敏感性分析</h2>"]

        has_scan_data = any(
            not b.parameter_scan.empty for b in self.bundles
        )

        if has_scan_data:
            for bundle in self.bundles:
                ps = bundle.parameter_scan
                lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")
                if not ps.empty:
                    lines.append("<p>参数扫描结果：</p>")
                    lines.append(self._table_from_series(
                        headers=list(ps.columns),
                        rows=[[str(v) for v in row] for _, row in ps.iterrows()],
                        caption="参数扫描结果",
                    ))
                else:
                    lines.append("<p>无参数扫描数据。</p>")
        else:
            lines.append("<p>无参数扫描数据。Phase 3 实现参数扫描引擎后可用。</p>")

        lines.append(
            '<div class="placeholder">'
            "<p><strong>此章节在 Phase 3 实现：</strong></p>"
            "<pre>"
            '9.1 关键参数扫描（遍历参数空间）\n' +
            '9.2 参数稳定性评分（RobustScore）\n\n' +
            '基础算法: 对每个参数在其取值范围内扫描,\n' +
            '计算 Sharpe/Return/DD 的变异系数,\n' +
            '变异系数越低 = 参数越鲁棒'
            "</pre>"
            "</div>"
        )
        lines.append("</div>")
        return "\n".join(lines)
    def _chapter_10_walk_forward(self) -> str:
        return self._placeholder_chapter(
            "十、样本内外对比 + Walk Forward Analysis",
            "10.1 静态样本内外对比（60/20/20）\n10.2 Walk Forward Analysis（滚动窗口验证）",
        )

    # ══════════════════════════════════════════════════════════════
    # 第十一章: 相关性矩阵（占位）
    # ══════════════════════════════════════════════════════════════

    def _chapter_11_correlation_matrix(self) -> str:
        """生成策略相关性矩阵（多策略时计算收益相关性）。"""
        lines = ['<div class="page-break">', "<h2>十一、策略相关性矩阵</h2>"]

        if len(self.bundles) < 2:
            lines.append("<p>单策略模式，无法计算相关性矩阵。需要 2 个及以上策略。</p>")
            lines.append(
                '<p class="placeholder">组合资金融合模拟：此章节在 Phase 3 实现 PortfolioManager 集成。</p>'
            )
            lines.append("</div>")
            return "\n".join(lines)

        # 从各 bundle 的 equity_curve 计算相关性
        returns = {}
        for b in self.bundles:
            ec = b.equity_curve
            if not ec.empty and "return" in ec.columns:
                returns[b.method_name] = ec["return"]

        if len(returns) >= 2:
            # 对齐索引
            df = pd.DataFrame(returns)
            df = df.dropna()

            if len(df) > 20:
                corr = df.corr()
                lines.append("<h4>11.1 日收益率相关性矩阵</h4>")
                lines.append("<table>")
                th = "<tr><th></th>" + "".join(f"<th>{html_mod.escape(c)}</th>" for c in corr.columns) + "</tr>"
                lines.append(th)
                for rname, row in corr.iterrows():
                    td = "".join(
                        f'<td style="color:{"#e74c3c" if v > 0 else "#2ecc71" if v < 0 else "#888"}">{v:.3f}</td>'
                        for _, v in row.items()
                    )
                    lines.append(f"<tr><td><strong>{html_mod.escape(rname)}</strong></td>{td}</tr>")
                lines.append("</table>")

                # 最大正相关/负相关
                pairs = []
                for i in range(len(corr.columns)):
                    for j in range(i+1, len(corr.columns)):
                        pairs.append((corr.iloc[i, j], corr.columns[i], corr.columns[j]))
                pairs.sort(key=lambda x: abs(x[0]), reverse=True)

                if pairs:
                    lines.append("<h4>相关性排序</h4>")
                    lines.append("<table><tr><th>策略A</th><th>策略B</th><th>相关性</th></tr>")
                    for r_val, a, b in pairs[:6]:
                        color = "#e74c3c" if r_val > 0 else "#2ecc71"
                        lines.append(
                            f"<tr><td>{html_mod.escape(a)}</td><td>{html_mod.escape(b)}</td>"
                            f'<td style="color:{color}">{r_val:.3f}</td></tr>'
                        )
                    lines.append("</table>")

            else:
                lines.append("<p>数据点不足（<20个交易日），无法计算有意义的相关系数。</p>")
        else:
            lines.append("<p>无收益率数据可用于相关性计算。</p>")

        lines.append(
            '<p class="placeholder">组合资金融合模拟：此章节在 Phase 3 实现 PortfolioManager 集成 '
            '和等权/最小方差/风险平价配权重计算。</p>'
        )
        lines.append("</div>")
        return "\n".join(lines)
    def _chapter_12_recovery_analysis(self) -> str:
        """生成连续亏损与回撤恢复章（从equity_curve和summary_metrics计算）。"""
        lines = ['<div class="page-break">', "<h2>十二、连续亏损与回撤恢复</h2>"]

        for bundle in self.bundles:
            ec = bundle.equity_curve
            trades = bundle.trades
            sm = bundle.summary_metrics
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            # 从 summary_metrics 读取
            max_dd = sm.get("max_drawdown", 0)
            pain_index = sm.get("pain_index", None)
            underwater_ratio = sm.get("underwater_ratio", None)

            lines.append("<h4>12.1 最大回撤分析</h4>")
            lines.append(
                '<div class="metric-box">'
                f"<strong>最大回撤:</strong> {max_dd*100 if isinstance(max_dd, float) else max_dd}%<br/>"
                f"<strong>Pain Index:</strong> {pain_index if pain_index is not None else '(Phase 3计算)'}<br/>"
                f"<strong>水下比例:</strong> {underwater_ratio*100 if isinstance(underwater_ratio, float) else '(Phase 3计算)'}%<br/>"
                "</div>"
            )

            # 12.2 连续亏损
            lines.append("<h4>12.2 连续亏损分析</h4>")
            if trades:
                pnls = [t.pnl for t in trades if hasattr(t, "pnl") and t.pnl is not None]
                if pnls:
                    max_consecutive_loss = 0
                    current_loss_streak = 0
                    total_loss_streak_days = 0
                    n_loss_streaks = 0
                    for p in pnls:
                        if p < 0:
                            current_loss_streak += 1
                            total_loss_streak_days += 1
                            max_consecutive_loss = max(max_consecutive_loss, current_loss_streak)
                        else:
                            if current_loss_streak > 0:
                                n_loss_streaks += 1
                            current_loss_streak = 0
                    avg_loss_streak = total_loss_streak_days / n_loss_streaks if n_loss_streaks > 0 else 0

                    lines.append(
                        '<div class="metric-box">'
                        f"<strong>最大连续亏损笔数:</strong> {max_consecutive_loss}<br/>"
                        f"<strong>平均连续亏损笔数:</strong> {avg_loss_streak:.1f}<br/>"
                        f"<strong>亏损段数:</strong> {n_loss_streaks}<br/>"
                        "</div>"
                    )

            # 12.3 水下时间
            lines.append("<h4>12.3 水下时间分析</h4>")
            if not ec.empty and "equity" in ec.columns:
                equity = ec["equity"].values
                peak = np.maximum.accumulate(equity)
                drawdown = (equity - peak) / peak
                underwater_days = int((drawdown < -0.01).sum())
                total_days = len(drawdown)
                underwater_pct = underwater_days / total_days * 100 if total_days > 0 else 0

                # 每个水下期的长度
                underwater_periods = []
                current_period = 0
                for d in drawdown:
                    if d < -0.01:
                        current_period += 1
                    else:
                        if current_period > 0:
                            underwater_periods.append(current_period)
                            current_period = 0
                if current_period > 0:
                    underwater_periods.append(current_period)

                max_underwater_period = max(underwater_periods) if underwater_periods else 0
                avg_underwater_period = sum(underwater_periods) / len(underwater_periods) if underwater_periods else 0

                lines.append(
                    '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f"<div><strong>水下天数:</strong> {underwater_days} 天</div>"
                    f"<div><strong>水下占比:</strong> {underwater_pct:.1f}%</div>"
                    f"<div><strong>最长单次水下:</strong> {max_underwater_period} 天</div>"
                    f"<div><strong>平均每次水下:</strong> {avg_underwater_period:.1f} 天</div>"
                    f"<div><strong>水下段数:</strong> {len(underwater_periods)} 次</div>"
                    "</div>"
                )

            # 12.4 Recovery Factor
            lines.append("<h4>12.4 Recovery Factor</h4>")
            total_return = sm.get("total_return", 0)
            if isinstance(total_return, float) and isinstance(max_dd, float) and max_dd != 0:
                recovery_factor = total_return / abs(max_dd)
                lines.append(
                    '<div class="metric-box">'
                    f"<strong>Recovery Factor(总收益/最大回撤):</strong> {recovery_factor:.2f}<br/>"
                    f"<small>衡量策略的收益风险效率，越高越好。</small>"
                    "</div>"
                )

        lines.append(
            '<p class="placeholder">回撤恢复深度分析（Calmar/回撤恢复特征）：'
            "此部分在 Phase 3 实现附加指标计算。</p>"
        )
        lines.append("</div>")
        return "\n".join(lines)
    def _chapter_13_t1_rating(self) -> str:
        """生成T1多维评分矩阵（从summary_metrics计算各维度评分）。"""
        lines = ['<div class="page-break">', "<h2>十三、T1评级结论</h2>",
                 "<p>多方法/策略的多维评分矩阵：每个维度满分10分。</p>"]

        if not self.bundles:
            lines.append("<p>无策略数据。</p>")
            lines.append("</div>")
            return "\n".join(lines)

        # 定义评分维度及对应的summary_metrics key、权重、方向
        dimensions = [
            ("总收益", ["total_return"], 1.0, True),
            ("年化收益", ["annual_return"], 1.0, True),
            ("夏普比率", ["sharpe"], 1.0, True),
            ("风险控制", ["max_drawdown"], 0.5, False),
            ("交易质量", ["win_rate", "profit_factor"], 1.0, True),
            ("恢复能力", ["recovery_factor"], 1.0, True),
        ]

        # 计算每个策略在每个维度的原始值
        method_scores: Dict[str, Dict[str, float]] = {}
        for b in self.bundles:
            sm = b.summary_metrics
            method_scores[b.method_name] = {}
            for dim_name, keys, _, _ in dimensions:
                vals = [sm.get(k, 0) for k in keys]
                # 对多个key取平均
                non_none = [v for v in vals if v is not None and isinstance(v, (int, float))]
                method_scores[b.method_name][dim_name] = sum(non_none) / len(non_none) if non_none else 0

        # 每个维度归一化到0-10
        dim_max: Dict[str, float] = {}
        dim_min: Dict[str, float] = {}
        for dim_name, _, _, higher_ok in dimensions:
            vals = [method_scores[m][dim_name] for m in method_scores]
            if higher_ok:
                dim_max[dim_name] = max(vals) if vals else 1
                dim_min[dim_name] = min(vals) if vals else 0
            else:
                # 对于lower_is_better（最大回撤），取绝对值
                abs_vals = [abs(v) for v in vals]
                dim_max[dim_name] = max(abs_vals) if abs_vals else 1
                dim_min[dim_name] = min(abs_vals) if abs_vals else 0

        # 归一化到0-10
        def _normalize(val: float, dim: str, higher_ok: bool) -> float:
            dmax = dim_max.get(dim, 1)
            dmin = dim_min.get(dim, 0)
            drange = dmax - dmin if dmax != dmin else 1
            if higher_ok:
                # 越高越好: v -> dmin->0, dmax->10
                return min(max((val - dmin) / drange * 10, 0), 10)
            else:
                # 越低越好: v -> dmin->10, dmax->0
                return min(max((dmax - abs(val)) / drange * 10, 0), 10)

        # 构建评分表格
        lines.append("<table>")
        th = "<tr><th>策略/方法</th>"
        for dim_name, _, _, _ in dimensions:
            th += f"<th>{html_mod.escape(dim_name)}</th>"
        th += "<th>综合评分</th></tr>"
        lines.append(th)

        for b in self.bundles:
            row = f"<tr><td><strong>{html_mod.escape(b.method_name)}</strong></td>"
            scores = []
            for dim_name, _, _, higher_ok in dimensions:
                raw = method_scores[b.method_name][dim_name]
                normalized = _normalize(raw, dim_name, higher_ok)
                scores.append(normalized)
                color = "#2ecc71" if normalized >= 7 else ("#f39c12" if normalized >= 4 else "#e74c3c")
                row += f'<td style="color:{color}">{normalized:.1f}</td>'
            # 综合评分（各维度等权平均）
            avg_score = sum(scores) / len(scores)
            avg_color = "#2ecc71" if avg_score >= 7 else ("#f39c12" if avg_score >= 4 else "#e74c3c")
            row += f'<td style="color:{avg_color};font-weight:bold;">{avg_score:.1f}</td></tr>'
            lines.append(row)

        lines.append("</table>")

        lines.append(
            '<div class="metric-box">'
            "<strong>评分说明：</strong><br/>"
            "各维度基于实际指标值在策略间的相对排名归一化到0-10分。<br/>"
            "<span style='color:#2ecc71'>高分(≥7)</span> = 优秀 | "
            "<span style='color:#f39c12'>中分(4-7)</span> = 一般 | "
            "<span style='color:#e74c3c'>低分(&lt;4)</span> = 需改进<br/>"
            "<small>注意：评分在单策略模式下无法做相对比较，各项均为10分。</small>"
            "</div>"
        )

        lines.append("</div>")
        return "\n".join(lines)
    @staticmethod
    def _placeholder_chapter(title: str, outline: str) -> str:
        lines = [
            '<div class="page-break">',
            f"<h2>{html_mod.escape(title)}</h2>",
            '<div class="placeholder">',
            "<p><strong>此章节在 Phase 3 实现</strong></p>",
            "<p>以下为本章节的完整设计提纲：</p>",
            "<pre>",
            html_mod.escape(outline),
            "</pre>",
            "<p>预计实现内容包括：</p>",
            "<ul>",
            "<li>通过 metrics_registry 计算所有衍生指标</li>",
            "<li>调用 ChartGenerator 生成 matplotlib 图表并内嵌 HTML</li>",
            "<li>关联 BacktestResultBundle 数据源的完整数据流</li>",
            "</ul>",
            "</div>",
            "</div>",
        ]
        return "\n".join(lines)

    @staticmethod
    def _table_from_series(
        headers: List[str],
        rows: List[List[str]],
        caption: str = "",
    ) -> str:
        if not rows:
            return f"<p>{html_mod.escape(caption)}: 无数据</p>"

        trs = ["".join(f"<th>{h}</th>" for h in headers)]
        for row in rows:
            trs.append("".join(f"<td>{html_mod.escape(str(c))}</td>" for c in row))

        rows_html = "\n".join(f"<tr>{t}</tr>" for t in trs)
        cap_html = ""
        if caption:
            cap_html = f'<caption style="caption-side:bottom;font-size:9pt;color:#888;">{html_mod.escape(caption)}</caption>'
        return f"<table>{cap_html}\n{rows_html}\n</table>"
