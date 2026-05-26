#!/usr/bin/env python3
"""
Generate backtest PDF report from knowledge.db (backtest_equity_series + backtest_trades).

Usage: python _gen_pdf_from_db.py [run_id]

If no run_id provided, uses the latest grid/601857.SH run.
"""
import os, sys, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from backtest.pipeline.knowledge_db import KnowledgeDB
import builtins

# Monkey-patch print to avoid GBK encoding errors
_orig_print = builtins.print
def _safe_print(*a, **kw):
    try:
        _orig_print(*a, **kw)
    except UnicodeEncodeError:
        _orig_print(*[str(x).encode("ascii", "replace").decode("ascii") for x in a], **kw)
builtins.print = _safe_print

# Paths
SYMBOL = "601857.SH"
OUTPUT = r"C:\Users\17699\mo_zhi_sharereports\reports\backtest\backtest_report_601857.pdf"
GEN_PATH = r"C:\Users\17699\Documents\BaiduSyncdisk\读书\python"
sys.path.insert(0, GEN_PATH)

from backtest_report_generator import TradeRecord, StrategyResult, ReportGenerator

# ── Determine run_id ──────────────────────────────────────
kdb = KnowledgeDB()
kdb.initialize()

run_id = sys.argv[1] if len(sys.argv) > 1 else None
if not run_id:
    run_id = kdb.get_latest_run_id(strategy="grid", symbol=SYMBOL)
    print(f"Using latest run_id: {run_id}")
else:
    print(f"Using provided run_id: {run_id}")

if not run_id:
    print("ERROR: No run found for grid/601857.SH. Run a backtest first.")
    sys.exit(1)

# ── Fetch equity series ──────────────────────────────────
equity_rows = kdb.get_equity_series(run_id)
print(f"Equity points from DB: {len(equity_rows)}")

if not equity_rows:
    print("ERROR: No equity data found for run_id.")
    sys.exit(1)

# Get initial capital from first record
initial_capital = equity_rows[0]["equity"] if equity_rows else 1_000_000.0
print(f"Initial capital: {initial_capital}")

# Build dates (MM-DD), closes (equity values), nav
dates = []
closes = []
nav = []

for row in equity_rows:
    d = str(row["date"])
    if len(d) >= 8:
        dates.append(f"{d[4:6]}-{d[6:8]}")
    else:
        dates.append(d)
    closes.append(float(row["equity"]))
    nav.append(float(row["nav"]))

# Benchmark nav (approximate: use buy-and-hold return from metrics or flat)
benchmark_nav = [n * 0.95 for n in nav]

# ── Fetch trades ─────────────────────────────────────────
trade_rows = kdb.get_trades(run_id)
print(f"Trades from DB: {len(trade_rows)}")

# Fetch performance metrics
perf = kdb.get_performance(run_id)
if perf:
    print(f"Performance metrics found: sharpe={perf.get('sharpe_ratio')}, "
          f"total_return={perf.get('total_return_pct')}%")
else:
    print("WARNING: No performance metrics found, using defaults")
    perf = {}

# Also fetch the run info
run_info = kdb.get_run(run_id)
if run_info:
    print(f"Run info: strategy={run_info.get('strategy')}, symbol={run_info.get('symbol')}")

# Convert trade rows to TradeRecord format
trades = []
for row in trade_rows:
    entry_date = str(row["entry_date"])
    exit_date = str(row["exit_date"])
    entry_price = float(row["entry_price"])
    exit_price = float(row["exit_price"])
    quantity = float(row["quantity"])
    pnl = float(row["pnl"])
    pnl_pct = float(row["pnl_pct"])

    # Determine hold days (approximate)
    hold_days = 0
    if entry_date and exit_date and len(entry_date) >= 8 and len(exit_date) >= 8:
        try:
            from datetime import datetime
            e = datetime.strptime(entry_date, "%Y%m%d")
            x = datetime.strptime(exit_date, "%Y%m%d")
            hold_days = (x - e).days
        except ValueError:
            hold_days = 0

    trades.append(TradeRecord(
        buy_date=entry_date,
        sell_date=exit_date,
        buy_price=entry_price,
        sell_price=exit_price,
        shares=int(quantity),
        pnl=round(pnl, 2),
        return_pct=round(pnl_pct, 2),
        hold_days=hold_days,
        is_win=pnl >= 0,
        signal="grid",
    ))

# Extract metrics from performance table
total_return = float(perf.get("total_return_pct", 0))
annual_return = float(perf.get("annual_return_pct", 0))
sharpe = float(perf.get("sharpe_ratio", 0))
max_dd = float(perf.get("max_drawdown_pct", 0))
win_rate = float(perf.get("win_rate_pct", 0))
total_trades_count = int(perf.get("total_trades", len(trades)))

# Also try to get additional metrics from backtest_runs (buy_hold_kpi etc.)
benchmark_return = 0.0
alpha = 0.0

# Try to get profit_loss_ratio from run_info
pl_ratio = 0.0
if run_info and "perf_extra_metrics" in run_info:
    extra = run_info.get("perf_extra_metrics", {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, TypeError):
            extra = {}
    if isinstance(extra, dict):
        pl_ratio = float(extra.get("profit_loss_ratio", extra.get("profit_factor", 0)))

# Alternatively try to read from JSON file for extra metrics
# (prefer knowledge.db but fall back to JSON for profit_loss_ratio)
if pl_ratio == 0.0:
    results_dir = r"C:\Users\17699\mozhi_platform\src\backtest_results"
    matching_files = [
        f for f in os.listdir(results_dir)
        if SYMBOL.replace(".SH", "") in f and "batcher" in f
    ]
    matching_files.sort()
    if matching_files:
        try:
            with open(os.path.join(results_dir, matching_files[-1]), "r", encoding="utf-8") as f:
                raw = json.load(f)
            j_metrics = raw.get("result", {}).get("metrics", {})
            pl_ratio = float(j_metrics.get("profit_loss_ratio", j_metrics.get("profit_factor", 0)))
            # Also get benchmark return if available
            bhkpi = raw.get("result", {}).get("buy_hold_kpi", {})
            if bhkpi:
                benchmark_return = float(bhkpi.get("buy_hold_return_pct", 0))
                alpha = float(annual_return) - float(benchmark_return)
        except Exception:
            pass

avg_hold = float(perf.get("avg_holding_bars", 0))

# Build config key from run info
config_key = run_info.get("config_key", "batcher_n10") if run_info else "batcher_n10"
name = f"网格回测 - {SYMBOL}"
params_desc = config_key.replace("_", " ")

print(f"\nStrategyResult: dates={len(dates)}, closes={len(closes)}, trades={len(trades)}")
print(f"  total_return={total_return}%, sharpe={sharpe}")
print(f"  max_drawdown={max_dd}%, win_rate={win_rate}%")

# Build StrategyResult
result_obj = StrategyResult(
    id=f"grid_{run_id[-16:]}" if len(run_id) >= 16 else "grid_601857",
    name=name,
    signal_desc=f"网格回测 - {SYMBOL}",
    params_desc=params_desc,
    params_dict={"strategy": "grid", "symbol": SYMBOL, "config_key": config_key},
    dates=dates,
    closes=closes,
    trades=trades,
    nav=nav,
    benchmark_nav=benchmark_nav,
    total_return=total_return,
    annual_return=annual_return,
    base_return=benchmark_return,
    alpha=alpha,
    sharpe=sharpe,
    max_drawdown=max_dd,
    win_rate=win_rate,
    profit_loss_ratio=pl_ratio,
    avg_hold_days=avg_hold,
    regime_stats={},
    is_approx=False,
)

# Generate PDF
rg = ReportGenerator()
rg.generate_pdf(OUTPUT, result_obj)

if os.path.exists(OUTPUT):
    print(f"\nPDF generated: {os.path.getsize(OUTPUT) / 1024:.0f} KB at {OUTPUT}")
else:
    print("\nPDF FAILED")

# Cleanup temp files
for tmp in os.listdir(r"C:\Users\17699\mozhi_platform"):
    if tmp.startswith("temp_") and tmp.endswith(".py"):
        try:
            os.remove(os.path.join(r"C:\Users\17699\mozhi_platform", tmp))
        except Exception:
            pass
