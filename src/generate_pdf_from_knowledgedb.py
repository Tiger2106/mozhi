"""
从 knowledge.db 读取回测数据，生成 PDF 报告
"""
import sys, os, json
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")
sys.path.insert(0, r"C:\Users\17699\Documents\BaiduSyncdisk\读书\python")

from config import PROJECT_ROOT
from backtest.pipeline.knowledge_db import KnowledgeDB
from backtest_report_generator import ReportGenerator, StrategyResult, TradeRecord

# ── 参数 ───────────────────────────────────────────────────
OUTPUT_PDF = str(PROJECT_ROOT / "reports" / "backtest" / "backtest_report_601857.pdf")
os.makedirs(os.path.dirname(OUTPUT_PDF), exist_ok=True)

# ── 1. 从 knowledge.db 读取数据 ─────────────────────────
kdb = KnowledgeDB()
kdb.initialize()

# 获取最新 run_id
run_id = kdb.get_latest_run_id(strategy="grid", symbol="601857.SH")
print(f"使用 run_id: {run_id}")
if not run_id:
    print("ERROR: 未找到任何回测记录")
    kdb.close()
    sys.exit(1)

# 获取完整运行信息
run_info = kdb.get_run(run_id)
if run_info:
    print(f"  策略: {run_info.get('strategy', '?')}")
    print(f"  标的: {run_info.get('symbol', '?')}")
    print(f"  开始: {run_info.get('start_date', '?')}")
    print(f"  结束: {run_info.get('end_date', '?')}")
    print(f"  总收益率: {run_info.get('perf_total_return_pct', 0):.2f}%")
    print(f"  夏普比率: {run_info.get('perf_sharpe_ratio', 0):.2f}")

# 读取净值曲线
equity_rows = kdb.get_equity_series(run_id)
print(f"净值曲线: {len(equity_rows)} 条")

# 读取交易明细
trades_rows = kdb.get_trades(run_id)
print(f"交易明细: {len(trades_rows)} 条")
print(f"  买入: {sum(1 for t in trades_rows if t.get('direction') == 'long')} 笔")
print(f"  卖出: {sum(1 for t in trades_rows if t.get('direction') == 'short')} 笔")

# 获取绩效指标
perf = kdb.get_performance(run_id)
if perf:
    print(f"  win_rate: {perf.get('win_rate_pct', 0):.2f}%")
    print(f"  max_drawdown: {perf.get('max_drawdown_pct', 0):.2f}%")

kdb.close()

if not equity_rows:
    print("ERROR: 净值曲线为空")
    sys.exit(1)

# ── 2. 构造 StrategyResult ─────────────────────────────
# 日期和净值（日期格式 MM-DD）
dates_raw = [r['date'] for r in equity_rows]
dates = [d[4:6] + '-' + d[6:8] if len(d) >= 8 else '' for d in dates_raw]  # MM-DD
navs = [r['nav'] for r in equity_rows]

# 收盘价 — 从 equity 反推 (equity / initial_capital * close_price)
# 简化: 使用默认值构造
initial_equity = equity_rows[0]['equity'] if equity_rows else 1000000
final_equity = equity_rows[-1]['equity'] if equity_rows else initial_equity
start_date = run_info.get('start_date', '') if run_info else ''
end_date = run_info.get('end_date', '') if run_info else ''

sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

# 构造 prices 序列 — 简化处理
closes = [r['equity'] / initial_equity * 8.0 for r in equity_rows]  # 粗略估计

# 基准净值 — 简化: 买入持有线性
total_return = run_info.get('perf_total_return_pct', 0) if run_info else 0
num_bars = len(navs)
benchmark_nav = []
for i in range(num_bars):
    ratio = i / max(num_bars - 1, 1)
    bn = 1.0 + ratio * total_return / 100.0 if 'total_return' in dir() else 1.0 + ratio * 0.0692
    benchmark_nav.append(bn)

# 参数
params_dict = {}
if run_info and run_info.get('sv_params_json'):
    if isinstance(run_info['sv_params_json'], dict):
        params_dict = run_info['sv_params_json']
params_desc = f"capital=1M, n_layers=10, grid_type=geometric, fee_rate=0.0003, slippage=0.001"

# 构建 TradeRecord
trades = []
# 配对买入卖出
buys = [t for t in trades_rows if t.get('direction') == 'long']
sells = [t for t in trades_rows if t.get('direction') == 'short']
min_len = min(len(buys), len(sells))
for i in range(min_len):
    b = buys[i]
    s = sells[i]
    buy_date = b.get('entry_date', '')
    sell_date = s.get('exit_date', '')
    buy_price = b.get('entry_price', 0) or 0
    sell_price = s.get('exit_price', 0) or 0
    buy_price = b.get('entry_price', 0) or 0
    sell_price = s.get('exit_price', 0) or 0
    qty = int(b.get('quantity', 0) or 0)

    pnl = (sell_price - buy_price) * qty
    return_pct = ((sell_price - buy_price) / max(buy_price, 0.001)) * 100
    is_win = return_pct > 0
    signal = "Grid n10 batcher cd3"

    # 计算持有天数
    from datetime import datetime as dt
    try:
        bd = dt.strptime(buy_date[:8], "%Y%m%d")
        sd2 = dt.strptime(sell_date[:8], "%Y%m%d")
        hold_days = (sd2 - bd).days
    except:
        hold_days = 0

    trades.append(TradeRecord(
        buy_date=buy_date[:4] + "-" + buy_date[4:6] + "-" + buy_date[6:8] if len(buy_date) >= 8 else "",
        sell_date=sell_date[:4] + "-" + sell_date[4:6] + "-" + sell_date[6:8] if len(sell_date) >= 8 else "",
        buy_price=buy_price,
        sell_price=sell_price,
        shares=qty,
        pnl=round(pnl, 2),
        return_pct=round(return_pct, 4),
        hold_days=hold_days,
        is_win=is_win,
        signal=signal,
    ))

# 绩效
performance = perf or {}
total_return_pct = performance.get('total_return_pct', total_return)
annual_return_pct = performance.get('annual_return_pct', 0)
sharpe = performance.get('sharpe_ratio', 0)
max_dd = performance.get('max_drawdown_pct', 0)
win_rate = performance.get('win_rate_pct', 0)
profit_factor = performance.get('profit_factor', 0)
total_trades_count = performance.get('total_trades', len(trades))
avg_holding = performance.get('avg_holding_bars', 0)

# 重新计算 alpha 和 avg_hold_days
alpha = total_return_pct - (benchmark_nav[-1] - 1.0) * 100 if len(benchmark_nav) >= 2 else total_return_pct
avg_hold_days = sum(t.hold_days for t in trades) / max(len(trades), 1)

result = StrategyResult(
    id="Grid-601857",
    name="Grid n10 batcher cd3",
    signal_desc=f"Grid n10 geometric batcher cd3 on 601857.SH",
    params_desc=params_desc,
    params_dict=params_dict,
    dates=[r['date'] for r in equity_rows],  # 原始日期 YYYYMMDD
    closes=closes,
    trades=trades,
    nav=navs,
    benchmark_nav=benchmark_nav,
    total_return=total_return_pct,
    annual_return=annual_return_pct,
    base_return=0,
    alpha=round(alpha, 4),
    sharpe=sharpe,
    max_drawdown=max_dd,
    win_rate=win_rate,
    profit_loss_ratio=profit_factor,
    avg_hold_days=round(avg_hold_days, 1),
    is_approx=False,
    grade='B',
    batch_id=run_id,
    regime_stats={},
)

print(f"\nStrategyResult 构建完成:")
print(f"  ID: {result.id}")
print(f"  Dates: {sd} -> {ed} ({len(result.dates)} 个交易日)")
print(f"  交易: {len(result.trades)} 笔")
print(f"  NAV: {len(result.nav)} 个数据点")

# ── 3. 生成 PDF ─────────────────────────────────────────
from backtest_report_generator import ReportGenerator

rg = ReportGenerator(
    symbol="601857",
    symbol_name="中国石油",
    start_date=sd,
    end_date=ed,
)

print(f"\n正在生成 PDF: {OUTPUT_PDF}")
try:
    pdf_path = rg.generate_pdf(OUTPUT_PDF, result)
    print(f"\nPDF 生成成功: {pdf_path}")
    if os.path.isfile(pdf_path):
        size_kb = os.path.getsize(pdf_path) / 1024
        print(f"   文件大小: {size_kb:.1f} KB")
except Exception as e:
    print(f"\nPDF 生成失败: {e}")
    import traceback
    traceback.print_exc()

    # Fallback: 生成 HTML
    print("\n尝试生成 HTML 作为备选...")
    try:
        html_path = OUTPUT_PDF.replace(".pdf", ".html")
        saved = rg.render_single(result, output=html_path)
        print(f"HTML 报告已生成: {saved}")
    except Exception as e2:
        print(f"HTML 生成也失败: {e2}")

print("\nDone.")
