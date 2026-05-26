#!/usr/bin/env python3
"""生成示例PDF报告 - 快速原型脚本

产出:
  - sample_report_20260517.html  (中间HTML, 带内嵌base64图表)
  - sample_report_20260517.pdf   (最终PDF)

用法: python generate_sample_report.py
"""

import base64
import io
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

# 中文字体配置
ZH_FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
fm.fontManager.addfont(ZH_FONT_PATH)
plt.rcParams["font.family"] = "Microsoft YaHei"
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

import numpy as np

# ── 路径 ──
OUT_DIR = Path(__file__).parent
HTML_PATH = OUT_DIR / "sample_report_20260517.html"
PDF_PATH = OUT_DIR / "sample_report_20260517.pdf"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# ── 种子 (可复现) ──
RNG = np.random.RandomState(42)


def img_to_data_uri(fig):
    """matplotlib figure → base64 data URI"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.3)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    plt.close(fig)
    return f"data:image/png;base64,{b64}"


# ═══════════════════════════════════════════════════════════
# 1. Mock 数据生成
# ═══════════════════════════════════════════════════════════

def generate_equity_curve(n_days=252):
    """生成模拟净值曲线 (3 策略 + 组合 + 基准)"""
    dates = [datetime(2025, 6, 1) + timedelta(days=i) for i in range(n_days)]
    strategies = {
        "趋势追踪": {"drift": 0.0008, "vol": 0.015},
        "均值回归": {"drift": 0.0005, "vol": 0.012},
        "动量突破": {"drift": 0.0010, "vol": 0.018},
    }
    curves = {}
    for name, params in strategies.items():
        returns = RNG.normal(params["drift"], params["vol"], n_days)
        curves[name] = np.cumprod(1 + returns)

    # 组合 (等权)
    portfolio = np.mean(list(curves.values()), axis=0)
    curves["组合"] = portfolio

    # 买入持有基准 (沪深300模拟)
    bench_returns = RNG.normal(0.0004, 0.013, n_days)
    curves["买入持有"] = np.cumprod(1 + bench_returns)

    return dates, curves


def generate_drawdown_curve(equity_curve):
    """从净值曲线计算回撤"""
    peak = np.maximum.accumulate(equity_curve)
    return (equity_curve - peak) / peak


def generate_monthly_returns(dates, equity_curve, n_months=12):
    """生成月度收益热力图数据"""
    monthly = {}
    for i in range(1, len(equity_curve)):
        if dates[i].month != dates[i - 1].month:
            month_key = dates[i - 1].strftime("%Y-%m")
            monthly[month_key] = (equity_curve[i - 1] / equity_curve[i - 2] - 1) * 100
    # 补全到 n_months
    months = sorted(monthly.keys())[-n_months:]
    values = [monthly[m] for m in months]
    return months, values


def generate_trade_orders():
    """生成模拟下单记录"""
    orders = []
    base_date = datetime(2025, 8, 1)
    methods = ["趋势追踪", "均值回归", "动量突破"]
    entry_prices = [15.23, 15.47, 15.91, 16.12, 15.68, 15.02, 14.75, 14.88, 15.11, 15.33]
    exit_prices = [15.68, 15.31, 15.02, 16.47, 15.89, 15.54, 15.12, 14.52, 14.96, 15.78]

    for i in range(10):
        method = methods[i % 3]
        entry_price = entry_prices[i] + RNG.uniform(-0.2, 0.2)
        exit_price = exit_prices[i] + RNG.uniform(-0.2, 0.2)
        volume = int(RNG.uniform(1000, 5000))
        pnl = round((exit_price - entry_price) * volume, 2)
        pnl_pct = round((exit_price / entry_price - 1) * 100, 2)
        entry_time = base_date + timedelta(days=i * 7, hours=9, minutes=30 + RNG.randint(0, 60))
        exit_time = entry_time + timedelta(days=RNG.randint(1, 5), hours=RNG.randint(0, 8))

        orders.append({
            "idx": i + 1,
            "method": method,
            "direction": "LONG" if pnl > -50 else "SHORT",
            "entry_time": entry_time.strftime("%Y-%m-%d %H:%M"),
            "entry_price": round(entry_price, 2),
            "volume": volume,
            "exit_time": exit_time.strftime("%Y-%m-%d %H:%M"),
            "exit_price": round(exit_price, 2),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })

    return orders


def generate_candlestick_data(n_bars=60):
    """生成模拟K线数据 (OHLC) + 交易标记"""
    base_price = 15.0
    closes = [base_price]
    for i in range(1, n_bars):
        ret = RNG.normal(0.0003, 0.008)
        closes.append(closes[-1] * (1 + ret))

    ohlc = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c * 0.998
        h = max(o, c) * (1 + abs(RNG.normal(0, 0.003)))
        l = min(o, c) * (1 - abs(RNG.normal(0, 0.003)))
        ohlc.append((o, h, l, c))

    # 生成买卖点
    buy_points = []
    sell_points = []
    for i in range(5, n_bars - 5, 10):
        if i < len(closes):
            buy_points.append((i, closes[i] * 0.995))
            sell_idx = min(i + RNG.randint(3, 8), n_bars - 1)
            sell_points.append((sell_idx, closes[sell_idx] * 1.005))

    dates = [datetime(2025, 8, 1) + timedelta(days=i) for i in range(n_bars)]
    return dates, ohlc, closes, buy_points, sell_points


# ═══════════════════════════════════════════════════════════
# 2. 图表生成 (matplotlib)
# ═══════════════════════════════════════════════════════════

def chart_equity_curve(dates, curves):
    """净值曲线图"""
    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = {"趋势追踪": "#3498db", "均值回归": "#2ecc71", "动量突破": "#e67e22", "组合": "#e74c3c", "买入持有": "#95a5a6"}
    styles = {"趋势追踪": "-", "均值回归": "-", "动量突破": "-", "组合": "--", "买入持有": ":"}

    for name, curve in sorted(curves.items()):
        ax.plot(dates, curve, label=name, color=colors.get(name, "#333"),
                linestyle=styles.get(name, "-"), linewidth=1.5 if name == "组合" else 1.0)

    ax.set_title("净值曲线 (Equity Curve)", fontsize=13, fontweight="bold")
    ax.set_ylabel("净值", fontsize=10)
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()

    # 指标摘要框
    final_values = {k: v[-1] for k, v in curves.items()}
    best = max(final_values, key=final_values.get)
    summary = (
        f"累计收益:\n"
        f"  组合: {(final_values['组合']-1)*100:.1f}%\n"
        f"  最佳: {best} {(final_values[best]-1)*100:.1f}%\n"
        f"  基准: {(final_values['买入持有']-1)*100:.1f}%"
    )
    ax.text(0.98, 0.15, summary, transform=ax.transAxes, fontsize=8,
            va="bottom", ha="right",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#f0f4f8", edgecolor="#e94560"))

    return fig


def chart_drawdown(dates, curves):
    """回撤曲线图 (含组合回撤 + 5%/10% 预警线)"""
    comb_curve = curves["组合"]
    dd = generate_drawdown_curve(comb_curve)

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.fill_between(dates, dd * 100, 0, color="#e74c3c", alpha=0.3, label="回撤")
    ax.plot(dates, dd * 100, color="#c0392b", linewidth=1.0)

    # 5% / 10% 预警线
    ax.axhline(y=-5, color="#f39c12", linestyle="--", linewidth=0.8, alpha=0.7, label="5% 预警")
    ax.axhline(y=-10, color="#e74c3c", linestyle="--", linewidth=0.8, alpha=0.7, label="10% 预警")
    ax.axhline(y=0, color="#333", linestyle="-", linewidth=0.5)

    ax.set_title("组合回撤曲线 (Drawdown)", fontsize=13, fontweight="bold")
    ax.set_ylabel("回撤 (%)", fontsize=10)
    ax.set_ylim(max(dd * 100) * 1.5, 5)
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()

    # 标注最大回撤
    max_dd_idx = np.argmin(dd)
    ax.annotate(f"最大回撤 {dd[max_dd_idx]*100:.1f}%",
                xy=(dates[max_dd_idx], dd[max_dd_idx] * 100),
                xytext=(dates[max(max_dd_idx - 30, 0)], dd[max_dd_idx] * 100 + 3),
                arrowprops=dict(arrowstyle="->", color="#c0392b"),
                fontsize=8, color="#c0392b")

    return fig


def chart_heatmap(dates, curves):
    """月度收益热力图"""
    months, vals = generate_monthly_returns(dates, curves["组合"])
    n = len(months)
    if n == 0:
        return None

    # 排列成 3 行 x 4 列
    n_cols = 4
    n_rows = math.ceil(n / n_cols)
    grid = np.full((n_rows, n_cols), np.nan)
    for i, v in enumerate(vals):
        r, c = divmod(i, n_cols)
        grid[r, c] = v

    fig, ax = plt.subplots(figsize=(8, max(3, n_rows * 1.2)))
    cmap = plt.cm.RdYlGn
    cmap.set_bad("#f0f0f0")

    im = ax.imshow(grid, cmap=cmap, aspect="auto", vmin=-5, vmax=5)

    # 标注数值
    for i in range(n_rows):
        for j in range(n_cols):
            idx = i * n_cols + j
            if idx < n:
                v = vals[idx]
                color = "white" if abs(v) > 2.5 else "black"
                ax.text(j, i, f"{months[idx]}\n{v:+.1f}%", ha="center", va="center",
                        fontsize=8, color=color, fontweight="bold")

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels([f"Col {j+1}" for j in range(n_cols)], fontsize=0)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([f"Row {i+1}" for i in range(n_rows)], fontsize=0)

    ax.set_title("月度收益热力图 (Monthly Returns)", fontsize=13, fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.6, label="月收益 (%)")
    return fig


def chart_candlestick(dates, ohlc, closes, buys, sells):
    """K线图 (标注买卖点位) — 使用matplotlib绘制"""
    fig, ax = plt.subplots(figsize=(9, 5))

    # 绘制K线
    width = 0.6
    for i, (o, h, l, c) in enumerate(ohlc):
        color = "#2ecc71" if c >= o else "#e74c3c"
        # 影线
        ax.plot([i, i], [l, h], color=color, linewidth=0.8)
        # 实体
        ax.bar(i, abs(c - o), bottom=min(o, c), width=width, color=color, alpha=0.8)

    # 均线 (MA5, MA20)
    if len(closes) >= 5:
        ma5 = np.convolve(closes, np.ones(5) / 5, mode="valid")
        ax.plot(range(4, len(closes)), ma5, color="#3498db", linewidth=0.8, alpha=0.7, label="MA5")
    if len(closes) >= 20:
        ma20 = np.convolve(closes, np.ones(20) / 20, mode="valid")
        ax.plot(range(19, len(closes)), ma20, color="#e67e22", linewidth=0.8, alpha=0.7, label="MA20")

    # 🟢入场点标注 (▲ 绿色)
    for idx, price in buys:
        ax.scatter(idx, price, marker="^", s=150, color="#2ecc71", zorder=5,
                   edgecolors="white", linewidth=1.5, label="入场" if idx == buys[0][0] else "")
        # 盈亏标注
        for s_idx, s_price in sells:
            if abs(s_idx - idx) < 10:
                pnl_pct = (s_price / price - 1) * 100
                ax.annotate(f"+{pnl_pct:.1f}%" if pnl_pct > 0 else f"{pnl_pct:.1f}%",
                            xy=(idx, price), xytext=(idx + 3, price * 1.01),
                            fontsize=7, color="#2ecc71" if pnl_pct > 0 else "#e74c3c",
                            arrowprops=dict(arrowstyle="->", color="#555", lw=0.5))

    # 🔴出场点标注 (▼ 红色)
    for idx, price in sells:
        ax.scatter(idx, price, marker="v", s=150, color="#e74c3c", zorder=5,
                   edgecolors="white", linewidth=1.5, label="出场" if idx == sells[0][0] else "")

    # 支撑/阻力位
    support = min(closes[-20:]) if len(closes) >= 20 else min(closes)
    resistance = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    ax.axhline(y=support, color="#3498db", linestyle="--", linewidth=0.7, alpha=0.5, label="支撑位")
    ax.axhline(y=resistance, color="#e74c3c", linestyle="--", linewidth=0.7, alpha=0.5, label="阻力位")

    ax.set_title("K线图 — 买卖点位标注 (Candlestick Chart)", fontsize=13, fontweight="bold")
    ax.set_ylabel("价格", fontsize=10)
    ax.set_xlabel("交易日期", fontsize=10)

    # X轴标签 (仅显示部分)
    step = max(1, len(dates) // 10)
    ax.set_xticks(range(0, len(dates), step))
    ax.set_xticklabels([dates[i].strftime("%m/%d") for i in range(0, len(dates), step)], fontsize=7)
    ax.legend(loc="upper left", fontsize=7, ncol=2)
    ax.grid(True, alpha=0.2)

    return fig


# ═══════════════════════════════════════════════════════════
# 3. HTML 模板生成
# ═══════════════════════════════════════════════════════════

def generate_html(trade_orders, chart_uris):
    """组装完整的HTML报告"""
    edge_chart = chart_uris.get("equity", "")
    dd_chart = chart_uris.get("drawdown", "")
    heatmap_chart = chart_uris.get("heatmap", "")
    candle_chart = chart_uris.get("candlestick", "")

    # 参数表
    param_rows = [
        ("标的", "601857 (A50)"),
        ("回测区间", "2025-06-01 ~ 2026-05-17"),
        ("初始资金", "¥1,000,000"),
        ("手续费率", "0.03%"),
        ("滑点", "0.01%"),
        ("策略分配", "趋势追踪 40% / 均值回归 30% / 动量突破 30%"),
        ("信号冲突策略", "动量突破优先"),
    ]
    param_table = "\n".join(
        f"            <tr><td>{k}</td><td>{v}</td></tr>" for k, v in param_rows
    )

    # 指标总表
    metrics_rows = [
        ("趋势追踪", "+18.5%", "1.32", "-8.2%", "62.5%", "1.58", "45"),
        ("均值回归", "+12.3%", "1.05", "-6.8%", "55.0%", "1.22", "38"),
        ("动量突破", "+23.7%", "1.68", "-11.5%", "58.3%", "1.85", "52"),
        ("组合", "+18.7%", "1.42", "-7.5%", "60.2%", "1.65", "—"),
        ("买入持有", "+8.2%", "0.62", "-14.3%", "—", "—", "—"),
    ]
    metrics_table = "\n".join(
        "            <tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"
        for row in metrics_rows
    )

    # 下单情况表
    trade_rows = []
    for o in trade_orders:
        pnl_cls = "profit" if o["pnl"] >= 0 else "loss"
        trade_rows.append(
            f"            <tr>"
            f"<td>{o['idx']}</td>"
            f"<td>{o['method']}</td>"
            f"<td>{o['direction']}</td>"
            f"<td>{o['entry_time']}</td>"
            f"<td>{o['entry_price']}</td>"
            f"<td>{o['exit_time']}</td>"
            f"<td>{o['exit_price']}</td>"
            f"<td>{o['volume']}</td>"
            f"<td class='{pnl_cls}'>{o['pnl']:+.2f}</td>"
            f"<td class='{pnl_cls}'>{o['pnl_pct']:+.2f}%</td>"
            f"</tr>"
        )
    trade_table = "\n".join(trade_rows)

    # 赢率统计表
    winrate_rows = [
        ("Bull (上涨)", "12", "3", "1", "75.0%"),
        ("Bear (下跌)", "5", "7", "0", "41.7%"),
        ("Range (震荡)", "8", "6", "2", "50.0%"),
        ("合计", "25", "16", "3", "56.8%"),
    ]
    winrate_table = "\n".join(
        "            <tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"
        for row in winrate_rows
    )

    # 连续盈亏序列
    streak = [1, 1, 1, 1, -1, -1, -1, 1, 1, -1, 1, 1, -1, 1, 1, 1, 1]
    streak_html = " ".join(
        f'<span class="{"win" if s>0 else "loss"}">{ "+" if s>0 else "-" }</span>'
        for s in streak
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>回测分析报告 — 示例</title>
<style>
  /* ── 打印页面设置 ── */
  @page {{ size: A4; margin: 2cm 2.5cm; }}

  /* ── 封面样式 ── */
  .cover-page {{
    page-break-after: always;
    display: flex; flex-direction: column;
    justify-content: center; align-items: center;
    height: 90vh;
    text-align: center;
  }}
  .cover-title {{ font-size: 28pt; font-weight: bold; margin-bottom: 10px; color: #1a1a2e; }}
  .cover-subtitle {{ font-size: 18pt; color: #666; margin-bottom: 30px; }}
  .cover-meta {{ font-size: 11pt; color: #888; line-height: 2; }}

  /* ── 正文样式 ── */
  body {{ font-family: 'Microsoft YaHei', -apple-system, sans-serif; font-size: 11pt; line-height: 1.6; color: #333; }}
  h1 {{ font-size: 20pt; color: #1a1a2e; border-bottom: 3px solid #e94560; padding-bottom: 8px; margin-top: 30px; }}
  h2 {{ font-size: 16pt; color: #16213e; margin-top: 24px; }}
  h3 {{ font-size: 13pt; color: #0f3460; margin-top: 16px; }}

  /* ── 表格样式 ── */
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 10pt; }}
  th {{ background: #1a1a2e; color: white; padding: 8px; text-align: center; font-weight: bold; }}
  td {{ padding: 6px 8px; border: 1px solid #ddd; text-align: center; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}

  /* ── 图表 ── */
  img.chart {{ width: 100%; max-width: 750px; display: block; margin: 16px auto; }}

  /* ── 工具样式 ── */
  .page-break {{ page-break-before: always; }}
  .profit {{ color: #2ecc71; font-weight: bold; }}
  .loss {{ color: #e74c3c; font-weight: bold; }}
  .win {{ color: #2ecc71; font-weight: bold; font-size: 14pt; }}
  .loss {{ color: #e74c3c; font-weight: bold; font-size: 14pt; }}

  .metric-box {{
    background: #f0f4f8; border-left: 4px solid #e94560;
    padding: 12px; margin: 16px 0; font-size: 10pt;
    border-radius: 4px;
  }}

  .stats-card {{
    background: #f0f4f8; border-radius: 6px; padding: 16px;
    margin: 12px 0; font-size: 10pt;
  }}

  .summary-block {{
    background: #eaf7ea; border: 1px solid #27ae60;
    border-radius: 6px; padding: 16px; margin: 20px 0;
  }}

  .appendix {{ font-size: 9pt; color: #888; }}
  .disclaimer {{ font-size: 8pt; color: #aaa; margin-top: 30px; line-height: 1.8; }}

  .streak-container {{ font-size: 14pt; letter-spacing: 2px; }}
</style>
</head>
<body>

<!-- ════════ 封面 ════════ -->
<div class="cover-page">
    <h1 class="cover-title">回测分析报告</h1>
    <p class="cover-subtitle">Backtest Analysis Report</p>
    <div class="cover-meta">
        <p>📅 生成时间: 2026-05-17 21:00 +08:00</p>
        <p>[DATA]  数据范围: 2025-06-01 ~ 2026-05-17</p>
        <p>== 标的: 601857.SH (A50 成分股)</p>
        <p>⚙️ 版本: v1.0 | 任务ID: demo_sample_20260517</p>
        <p>🤖 生成引擎: 墨衡 (MoHeng) · KnowledgeAnalyzer v1.0</p>
    </div>
</div>

<!-- ════════ 目录 ════════ -->
<div class="page-break">
    <h1>目录</h1>
    <ul style="font-size: 12pt; line-height: 2.2;">
        <li>一、回测参数表</li>
        <li>二、净值曲线</li>
        <li>三、回撤曲线 + 月度收益热力图</li>
        <li>四、指标总表</li>
        <li>五、K线图 — 买卖点位标注</li>
        <li>六、交易记录</li>
        <li>七、赢率分析</li>
        <li>附录 &amp; 免责声明</li>
    </ul>
</div>

<!-- ════════ 一、回测参数表 ════════ -->
<div>
    <h1>一、回测参数表</h1>
    <table>
        <tr><th style="width:30%">参数</th><th>值</th></tr>
{param_table}
    </table>
</div>

<!-- ════════ 二、净值曲线 ════════ -->
<div class="page-break">
    <h1>二、净值曲线</h1>
    <p>各策略 + 组合 + 买入持有基准对比，完整回测区间表现。</p>
    <img class="chart" src="{edge_chart}" alt="净值曲线">
    <div class="metric-box">
        <strong>关键指标摘要:</strong><br>
        组合累计收益: +18.7% | 夏普比率: 1.42 | 最大回撤: -7.5%
    </div>
</div>

<!-- ════════ 三、回撤曲线 + 月度收益热力图 ════════ -->
<div class="page-break">
    <h1>三、回撤曲线</h1>
    <p>组合回撤曲线（含 5% / 10% 预警线）</p>
    <img class="chart" src="{dd_chart}" alt="回撤曲线">

    <h2>月度收益热力图</h2>
    <p>各月收益概览（绿色 = 正收益，红色 = 负收益）</p>
    <img class="chart" src="{heatmap_chart}" alt="月度收益热力图">
</div>

<!-- ════════ 四、指标总表 ════════ -->
<div class="page-break">
    <h1>四、指标总表</h1>
    <p>各策略 + 组合的完整性能指标矩阵</p>
    <table>
        <tr>
            <th>策略</th><th>累计收益</th><th>夏普比率</th><th>最大回撤</th>
            <th>胜率</th><th>盈亏比</th><th>交易次数</th>
        </tr>
{metrics_table}
    </table>
</div>

<!-- ════════ 五、K线图 ════════ -->
<div class="page-break">
    <h1>五、K线图 — 买卖点位标注</h1>
    <p>🟢 ▲ = 入场点 (买入) &nbsp;|&nbsp; 🔴 ▼ = 出场点 (卖出) &nbsp;|&nbsp; 虚线 = 支撑位/阻力位</p>
    <img class="chart" src="{candle_chart}" alt="K线图买卖点位">
    <div class="metric-box">
        <strong>标注说明:</strong><br>
        ▲ 绿色标注入场点，▼ 红色标注出场点。图表上方标注每笔交易的盈亏百分比。蓝色虚线为支撑位，红色虚线为阻力位。MA5/MA20均线辅助趋势判断。
    </div>
</div>

<!-- ════════ 六、交易记录 ════════ -->
<div class="page-break">
    <h1>六、交易记录</h1>
    <p>逐笔交易明细（按策略分组）</p>
    <table class="trade-table">
        <tr>
            <th>#</th><th>策略</th><th>方向</th><th>入场时间</th><th>入场价</th>
            <th>出场时间</th><th>出场价</th><th>持仓量</th><th>盈亏</th><th>盈亏%</th>
        </tr>
{trade_table}
    </table>
    <div class="metric-box">
        <strong>交易统计:</strong><br>
        总交易数: {len(trade_orders)} | 盈利笔数: {sum(1 for o in trade_orders if o['pnl'] > 0)} |
        亏损笔数: {sum(1 for o in trade_orders if o['pnl'] <= 0)} |
        总盈亏: {sum(o['pnl'] for o in trade_orders):+.2f}
    </div>
</div>

<!-- ════════ 七、赢率分析 ════════ -->
<div class="page-break">
    <h1>七、赢率分析</h1>
    <p>按市场状态 (Regime) 分组的赢率统计</p>

    <h2>赢率统计 — 组合</h2>
    <table class="winrate-table">
        <tr><th>Regime</th><th>赢</th><th>亏</th><th>平</th><th>赢率</th></tr>
{winrate_table}
    </table>

    <div class="stats-card">
        <strong>盈亏比:</strong> 1.65 &nbsp;&nbsp;|&nbsp;&nbsp;
        <strong>最大连续盈利:</strong> 5 笔 &nbsp;&nbsp;|&nbsp;&nbsp;
        <strong>最大连续亏损:</strong> 3 笔 &nbsp;&nbsp;|&nbsp;&nbsp;
        <strong>当前连续:</strong> 盈利 2 笔
    </div>

    <h3>连续盈亏序列</h3>
    <div class="streak-container">
        {streak_html}
    </div>
    <p style="font-size: 9pt; color: #888;">绿色 + = 盈利 &nbsp;|&nbsp; 红色 - = 亏损</p>

    <div class="summary-block">
        <h3>📋 分析小结</h3>
        <p>在回测区间内，组合夏普比率 1.42，累计收益 +18.7%，显著优于买入持有基准。动量突破策略表现最佳 (夏普 1.68)，但最大回撤 -11.5% 较高，建议配合趋势追踪策略组合使用。上涨市场 (Bull) 中赢率 75.0%，但在下跌市场中仅 41.7%，存在明显的 regime 依赖特征。</p>
    </div>
</div>

<!-- ════════ 附录 ════════ -->
<div class="page-break">
    <h1>附录</h1>
    <div class="appendix">
        <h3>数据来源</h3>
        <p>回测知识库 knowledge_entries 目录</p>

        <h3>分析引擎</h3>
        <p>KnowledgeAnalyzer v1.0 (纯 pandas/numpy 计算)</p>

        <h3>图表引擎</h3>
        <p>matplotlib 3.10.9</p>

        <h3>PDF 渲染</h3>
        <p>Microsoft Edge headless (Chromium)</p>

        <h3>技术栈</h3>
        <p>Python 3.14 | matplotlib | numpy | Edge headless</p>
    </div>

    <div class="disclaimer">
        <hr>
        <p><strong>免责声明</strong></p>
        <p>本报告由系统自动生成，仅供参考，不构成投资建议。回测结果不代表未来收益，历史表现不能保证未来表现。投资有风险，入市需谨慎。</p>
        <p>© 2026 墨家投资室 · 墨衡 (MoHeng) · v1.0</p>
    </div>
</div>

</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════════════
# 4. Edge headless → PDF
# ═══════════════════════════════════════════════════════════

def html_to_pdf(html_path, pdf_path):
    """使用 Edge headless 将 HTML 转为 PDF"""
    edge = EDGE_PATH
    if not os.path.exists(edge):
        print(f"[ERROR] Edge not found at: {edge}")
        return False

    url = f"file:///{html_path.as_posix()}"
    cmd = [
        edge,
        "--headless",
        "--disable-gpu",
        f"--print-to-pdf={pdf_path}",
        "--no-margins",
        url,
    ]
    print(f"[INFO] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"[ERROR] Edge headless failed:")
        print(f"  stdout: {result.stdout[:500]}")
        print(f"  stderr: {result.stderr[:500]}")
        return False

    if os.path.exists(pdf_path):
        kb = os.path.getsize(pdf_path) / 1024
        print(f"[OK] PDF generated: {pdf_path} ({kb:.1f} KB)")
        return True
    else:
        print(f"[ERROR] PDF not found after Edge run: {pdf_path}")
        return False


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  墨衡 · 示例PDF报告生成器")
    print("=" * 60)

    # Step 1: 生成数据
    print("\n[1/5] 生成模拟数据...")
    dates, curves = generate_equity_curve()
    trade_orders = generate_trade_orders()
    c_dates, ohlc, closes, buys, sells = generate_candlestick_data()
    print(f"  - 净值曲线: {len(dates)} 点, {len(curves)} 策略")
    print(f"  - 交易记录: {len(trade_orders)} 笔")
    print(f"  - K线数据: {len(c_dates)} 根")

    # Step 2: 生成图表
    print("\n[2/5] 生成 matplotlib 图表...")
    chart_uris = {}
    print("  - 净值曲线...")
    fig = chart_equity_curve(dates, curves)
    chart_uris["equity"] = img_to_data_uri(fig)

    print("  - 回撤曲线...")
    fig = chart_drawdown(dates, curves)
    chart_uris["drawdown"] = img_to_data_uri(fig)

    print("  - 月度收益热力图...")
    fig = chart_heatmap(dates, curves)
    if fig:
        chart_uris["heatmap"] = img_to_data_uri(fig)

    print("  - K线买卖点...")
    fig = chart_candlestick(c_dates, ohlc, closes, buys, sells)
    chart_uris["candlestick"] = img_to_data_uri(fig)

    # 估算大小
    total_b64_len = sum(len(v) for v in chart_uris.values())
    print(f"  - 图表 base64 总大小: {total_b64_len / 1024:.0f} KB (4张图)")

    # Step 3: 生成 HTML
    print("\n[3/5] 生成 HTML 报告...")
    html = generate_html(trade_orders, chart_uris)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    html_kb = os.path.getsize(HTML_PATH) / 1024
    print(f"  - HTML 已保存: {HTML_PATH} ({html_kb:.0f} KB)")

    # Step 4: HTML → PDF
    print("\n[4/5] Edge headless → PDF...")
    success = html_to_pdf(HTML_PATH, PDF_PATH)

    # Step 5: 结果
    print(f"\n[5/5] 完成！")
    if success and os.path.exists(PDF_PATH):
        pdf_kb = os.path.getsize(PDF_PATH) / 1024
        print(f"  [OK]  PDF: {PDF_PATH} ({pdf_kb:.1f} KB)")
        print(f"  [HTML]  HTML: {HTML_PATH} ({html_kb:.0f} KB)")
    else:
        print(f"  [WARN]  PDF 生成失败，HTML 可预览: {HTML_PATH}")
        print(f"     请手动在浏览器中打开 HTML，然后 Ctrl+P → 另存为PDF")

    print(f"\n{'=' * 60}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
