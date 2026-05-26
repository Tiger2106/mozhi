"""
墨枢 - Trend Strategy HTML Report Generator
============================================

生成自包含的HTML回测报告，内嵌图表（base64）、指标表格、交易明细表。
"""

from __future__ import annotations

import base64
import datetime
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── 13项核心指标定义 ────────────────────────────────────────

METRICS_DEF = [
    ("total_return_pct",       "总收益率",         "{:.2f}%"),
    ("annual_return_pct",      "年化收益率",       "{:.2f}%"),
    ("sharpe_ratio",           "夏普比率",         "{:.4f}"),
    ("max_drawdown_pct",       "最大回撤",         "{:.2f}%"),
    ("calmar_ratio",           "卡玛比率",         "{:.4f}"),
    ("volatility",             "波动率",           "{:.6f}"),
    ("sortino_ratio",          "索提诺比率",       "{:.4f}"),
    ("var_95_pct",             "VaR(95%)",         "{:.4f}%"),
    ("win_rate_pct",           "胜率",             "{:.2f}%"),
    ("profit_loss_ratio",      "盈亏比",           "{:.4f}"),
    ("max_consecutive_wins",   "连续盈利次数",     "{:d}"),
    ("max_consecutive_losses", "连续亏损次数",     "{:d}"),
    ("profit_factor",          "盈利因子",         "{:.4f}"),
]


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════


def generate_html_report(
    result: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    chart_paths: Optional[List[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    生成自包含HTML回测报告。

    Parameters
    ----------
    result : dict
        回测结果字典，包含 metrics, trades, equity_curve, total_trades 等字段。
    config : dict, optional
        回测配置（start_date, end_date, initial_capital, fee_rate, slippage_rate）。
        缺省时自动从 result 中提取。
    chart_paths : list of str, optional
        图表文件路径列表（PNG），将内嵌为 base64。
    meta : dict, optional
        元信息（symbol, signal_type, signal_params, timestamp 等）。

    Returns
    -------
    str
        生成的HTML文件路径。
    """
    # ── 提取数据 ──────────────────────────────────────────
    metrics: Dict[str, Any] = result.get("metrics", result)
    trades: List[Dict[str, Any]] = result.get("trades", [])
    equity_curve: List[Dict[str, Any]] = result.get("equity_curve", [])
    total_trades_val: int = result.get("total_trades", len(trades))

    if config is None:
        config = result.get("config", {})
    if meta is None:
        meta = result.get("meta", {})

    symbol = meta.get("symbol", config.get("symbol", "601857"))
    signal_type = meta.get("signal_type", "")
    signal_params = meta.get("signal_params", {})
    tag = meta.get("tag", "")

    start_date = config.get("start_date", "")
    end_date = config.get("end_date", "")
    initial_capital = config.get("initial_capital", 1_000_000.0)
    fee_rate = config.get("fee_rate", 0.0)
    slippage_rate = config.get("slippage_rate", 0.0)
    total_bars = result.get("total_bars", len(equity_curve))
    final_equity = metrics.get("final_equity")

    # 如果 result 没有 final_equity，从 equity_curve 取最后一笔
    if final_equity is None and equity_curve:
        final_equity = equity_curve[-1].get("total_equity", initial_capital)
    if final_equity is None:
        final_equity = initial_capital

    # ── 计算盈利因子（如果 metrics 没有提供） ─────────────
    profit_factor = metrics.get("profit_factor", 0.0)
    if profit_factor == 0.0 and not metrics.get("total_return_pct", None):
        profit_factor = _calc_profit_factor(trades)

    # ── 内嵌图表 ──────────────────────────────────────────
    chart_html_parts: List[str] = []
    if chart_paths:
        for cpath in chart_paths:
            b64 = _img_to_b64(cpath)
            if b64:
                name = os.path.basename(cpath).replace("_", " ").replace(".png", "")
                chart_html_parts.append(
                    f'<div class="chart"><h3>{name}</h3>'
                    f'<img src="data:image/png;base64,{b64}" '
                    f'alt="{name}" /></div>'
                )

    # ── 信号描述 ──────────────────────────────────────────
    signal_desc_parts = []
    if signal_type:
        signal_desc_parts.append(f"信号类型: {signal_type}")
    if signal_params:
        for k, v in signal_params.items():
            signal_desc_parts.append(f"{_param_label(k, signal_type)}: {v}")

    # ── 构建HTML ──────────────────────────────────────────
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_title = f"回测报告 - {symbol}"
    if tag:
        report_title += f" ({tag})"

    metrics_rows = _build_metrics_rows(metrics, metrics, profit_factor)
    trades_rows = _build_trades_rows(trades)

    html = _HTML_TEMPLATE.format(
        title=report_title,
        symbol=symbol,
        timestamp=timestamp_str,
        start_date=start_date,
        end_date=end_date,
        total_bars=total_bars,
        initial_capital=_fmt_money(initial_capital),
        final_equity=_fmt_money(final_equity),
        fee_rate=f"{fee_rate*100:.4f}%" if fee_rate else "—",
        slippage_rate=f"{slippage_rate*100:.4f}%" if slippage_rate else "—",
        total_trades=total_trades_val,
        signal_desc=" | ".join(signal_desc_parts) if signal_desc_parts else "—",
        metrics_rows=metrics_rows,
        trades_rows=trades_rows,
        charts="\n".join(chart_html_parts) if chart_html_parts else "",
    )

    # ── 写入文件 ──────────────────────────────────────────
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(r"C:\Users\17699\mozhi_platform") / "reports" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"trend_report_{symbol}_{now}.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"[HTML Report] 报告已生成: {out_path.resolve()}")
    return str(out_path.resolve())


# ═══════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════


def _img_to_b64(path: str) -> Optional[str]:
    """将 PNG 图片文件转换为 base64 字符串。"""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except (FileNotFoundError, IOError):
        return None


def _calc_profit_factor(trades: List[Dict[str, Any]]) -> float:
    """计算盈利因子 = 总盈利 / 总亏损绝对值。"""
    gross_profit = 0.0
    gross_loss = 0.0
    for t in trades:
        pnl = _get_pnl(t)
        if pnl is not None:
            if pnl > 0:
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += abs(pnl)
    if gross_loss == 0:
        return 0.0 if gross_profit == 0 else float("inf")
    return round(gross_profit / gross_loss, 4)


def _get_pnl(t: Dict[str, Any]) -> Optional[float]:
    """从交易记录中提取 realized_pnl，兼容无该字段的情况。"""
    pnl = t.get("realized_pnl")
    if pnl is not None:
        return pnl
    # 尝试从 buy_price / sell_price 推断
    side = t.get("side", "buy")
    if side == "sell" and t.get("price"):
        if "avg_buy_price" in t:
            return (t["price"] - t["avg_buy_price"]) * t.get("quantity", 0)
    return None


def _param_label(key: str, signal_type: str) -> str:
    """参数名汉化。"""
    labels = {
        "ma_fast": "快线周期",
        "ma_slow": "慢线周期",
        "position_ratio": "仓位比例",
        "order_type": "订单类型",
        "stop_loss_pct": "止损比例",
        "take_profit_pct": "止盈比例",
    }
    return labels.get(key, key)


def _fmt_money(value: float) -> str:
    """¥1,234,567.89 格式化。"""
    return f"¥{value:,.2f}"


def _build_metrics_rows(
    raw_result: Dict[str, Any], metrics: Dict[str, Any], profit_factor: float
) -> str:
    """构建指标表格HTML行。"""
    rows = []
    for key, label, fmt in METRICS_DEF:
        if key == "profit_factor":
            val = profit_factor
        else:
            val = metrics.get(key, raw_result.get(key))
        if val is None:
            formatted = "—"
        elif val == float("inf"):
            formatted = "∞"
        else:
            try:
                formatted = fmt.format(val)
            except (ValueError, TypeError):
                formatted = str(val)

        is_positive = _is_good_metric(key, val)
        cls = "positive" if is_positive else ("negative" if not _is_undecided(key) else "")
        rows.append(f'<tr class="{cls}"><td>{label}</td><td>{formatted}</td></tr>')
    return "\n".join(rows)


def _is_good_metric(key: str, val) -> bool:
    """判断指标是否为『好』（绿色）。"""
    if val is None:
        return False
    if key in ("sharpe_ratio", "sortino_ratio", "calmar_ratio", "profit_loss_ratio", "profit_factor"):
        return val > 1.0
    if key in ("total_return_pct", "annual_return_pct", "win_rate_pct"):
        return val > 0.0
    if key in ("max_consecutive_wins",):
        return val >= 3
    if key in ("max_consecutive_losses",):
        return val <= 2
    return False


def _is_undecided(key: str) -> bool:
    """哪些指标没有明确的好坏倾向（如交易次数）。"""
    return key in ("total_trades",)


def _build_trades_rows(trades: List[Dict[str, Any]]) -> str:
    """构建交易记录明细表HTML行。"""
    if not trades:
        return '<tr><td colspan="8" class="empty">无交易记录</td></tr>'

    rows = []
    for i, t in enumerate(trades, 1):
        date = t.get("date", "—")
        side = t.get("side", "—")
        price = t.get("price", 0.0)
        qty = t.get("quantity", 0)
        fee = t.get("fee", 0.0)
        pnl = _get_pnl(t)
        pnl_str = f"¥{pnl:+,.2f}" if pnl is not None else "—"
        pnl_cls = "positive" if (pnl is not None and pnl > 0) else ("negative" if (pnl is not None and pnl < 0) else "")

        # 成交额
        turnover = price * qty if price else 0.0

        rows.append(
            f'<tr>'
            f'<td>{i}</td>'
            f'<td>{date}</td>'
            f'<td>{side}</td>'
            f'<td>{price:.4f}</td>'
            f'<td>{qty}</td>'
            f'<td>{_fmt_money(turnover)}</td>'
            f'<td>¥{fee:.2f}</td>'
            f'<td class="{pnl_cls}">{pnl_str}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


# ═══════════════════════════════════════════════════════════════
# HTML 模板
# ═══════════════════════════════════════════════════════════════

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
    background: #f0f2f5;
    color: #333;
    padding: 24px;
  }}
  .container {{
    max-width: 1100px;
    margin: 0 auto;
  }}
  .header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: #fff;
    padding: 32px 40px;
    border-radius: 12px;
    margin-bottom: 24px;
  }}
  .header h1 {{ font-size: 26px; font-weight: 700; margin-bottom: 8px; }}
  .header .subtitle {{ font-size: 14px; opacity: 0.8; }}
  .card {{
    background: #fff;
    border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    padding: 24px;
    margin-bottom: 20px;
  }}
  .card h2 {{
    font-size: 18px;
    font-weight: 600;
    color: #1a1a2e;
    border-bottom: 2px solid #e8e8e8;
    padding-bottom: 10px;
    margin-bottom: 16px;
  }}
  .info-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }}
  .info-item {{
    padding: 8px 12px;
    background: #f8f9fb;
    border-radius: 6px;
    font-size: 14px;
  }}
  .info-item .label {{ color: #888; font-size: 12px; }}
  .info-item .value {{ font-weight: 600; font-size: 15px; margin-top: 2px; }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  th, td {{
    padding: 10px 12px;
    text-align: left;
    border-bottom: 1px solid #eee;
  }}
  th {{
    background: #f5f6fa;
    font-weight: 600;
    color: #555;
    font-size: 13px;
    white-space: nowrap;
  }}
  tr:hover {{ background: #f8f9fb; }}
  tr.positive td:last-child {{ color: #e74c3c; font-weight: 600; }}
  tr.negative td:last-child {{ color: #27ae60; font-weight: 600; }}

  td.positive {{ color: #e74c3c; font-weight: 600; }}
  td.negative {{ color: #27ae60; font-weight: 600; }}
  td.empty {{ text-align: center; color: #aaa; padding: 32px; }}

  .charts-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
    gap: 20px;
  }}
  .chart {{
    background: #fafbfc;
    border: 1px solid #e8e8e8;
    border-radius: 8px;
    padding: 12px;
    text-align: center;
  }}
  .chart h3 {{
    font-size: 14px;
    color: #555;
    margin-bottom: 8px;
    font-weight: 500;
  }}
  .chart img {{
    max-width: 100%;
    height: auto;
    border-radius: 4px;
  }}

  .footer {{
    text-align: center;
    color: #aaa;
    font-size: 12px;
    padding: 20px 0;
  }}

  @media (max-width: 600px) {{
    body {{ padding: 12px; }}
    .header {{ padding: 20px; }}
    .header h1 {{ font-size: 20px; }}
    .info-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .charts-grid {{ grid-template-columns: 1fr; }}
    table {{ font-size: 13px; }}
    th, td {{ padding: 8px 8px; }}
  }}

  .trades-wrap {{
    overflow-x: auto;
  }}
</style>
</head>
<body>
<div class="container">

  <!-- ── 头部 ────────────────────────────────────────── -->
  <div class="header">
    <h1>📈 {title}</h1>
    <div class="subtitle">生成时间: {timestamp}</div>
  </div>

  <!-- ── 基本信息 ────────────────────────────────────── -->
  <div class="card">
    <h2>📋 基本信息</h2>
    <div class="info-grid">
      <div class="info-item">
        <div class="label">股票代码</div>
        <div class="value">{symbol}</div>
      </div>
      <div class="info-item">
        <div class="label">回测区间</div>
        <div class="value">{start_date} ~ {end_date}</div>
      </div>
      <div class="info-item">
        <div class="label">交易天数</div>
        <div class="value">{total_bars}</div>
      </div>
      <div class="info-item">
        <div class="label">初始资金</div>
        <div class="value">{initial_capital}</div>
      </div>
      <div class="info-item">
        <div class="label">最终权益</div>
        <div class="value">{final_equity}</div>
      </div>
      <div class="info-item">
        <div class="label">手续费率</div>
        <div class="value">{fee_rate}</div>
      </div>
      <div class="info-item">
        <div class="label">滑点率</div>
        <div class="value">{slippage_rate}</div>
      </div>
      <div class="info-item">
        <div class="label">交易次数</div>
        <div class="value">{total_trades}</div>
      </div>
      <div class="info-item">
        <div class="label">信号参数</div>
        <div class="value" style="font-size:13px;">{signal_desc}</div>
      </div>
    </div>
  </div>

  <!-- ── 核心绩效指标 ────────────────────────────────── -->
  <div class="card">
    <h2>⭐ 核心绩效指标</h2>
    <table>
      <thead>
        <tr><th>指标</th><th>数值</th></tr>
      </thead>
      <tbody>
        {metrics_rows}
      </tbody>
    </table>
  </div>

  <!-- ── 交易记录明细 ────────────────────────────────── -->
  <div class="card">
    <h2>📝 交易记录明细</h2>
    <div class="trades-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>日期</th>
            <th>方向</th>
            <th>价格</th>
            <th>数量</th>
            <th>成交额</th>
            <th>手续费</th>
            <th>盈亏</th>
          </tr>
        </thead>
        <tbody>
          {trades_rows}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ── 图表 ────────────────────────────────────────── -->
  <div class="card" id="charts">
    <h2>📊 图表</h2>
    <div class="charts-grid">
      {charts}
    </div>
  </div>

  <div class="footer">
    Powered by 墨枢 (MoShu) Backtest Engine &middot; {timestamp}
  </div>

</div>
</body>
</html>
"""
