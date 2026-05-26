"""
Moheng: Backfill profit_factor backtests.
Runs 9 representative backtests after fixing profit_factor calculation.
"""
import os, sys, time, json
from datetime import datetime

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, SRC_DIR)

from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig
from backtest.strategies.run_grid import (
    run_grid_backtest, make_grid_config, load_stock_bars,
)
from backtest.strategies.run_reversal import (
    run_reversal_backtest, ReversalBacktestConfig,
    load_stock_bars as rev_load_bars,
)
from backtest.strategies.run_trend import (
    run_trend_backtest, TrendBacktestConfig,
    load_stock_bars as trend_load_bars,
)
from backtest.pipeline.knowledge_db import KnowledgeDB

def make_grid_bounds(symbol):
    try:
        bars = load_stock_bars(symbol, "", "")
        prices = [b.close for b in bars]
        lo, hi = min(prices), max(prices)
        margin = (hi - lo) * 0.1
        return max(lo - margin, lo * 0.8), hi + margin
    except Exception as e:
        print(f"  [SKIP] cannot get bounds for {symbol}: {e}")
        return None

# Compute bounds once
print(">>> Computing grid bounds from data ...")
b_601857 = make_grid_bounds("601857.SH")
b_000001 = make_grid_bounds("000001.SZ")
print(f"  601857.SH -> ({b_601857[0]:.2f}, {b_601857[1]:.2f})")
print(f"  000001.SZ -> ({b_000001[0]:.2f}, {b_000001[1]:.2f})")

def run_grid(symbol, n_levels, grid_type, pos_mode, pos_kwargs, tag):
    cfg = make_grid_config(
        symbol=symbol,
        signal=StaticGridSignal(
            grid_config=GridConfig(
                lower_bound=b_601857[0] if "601857" in symbol else b_000001[0],
                upper_bound=b_601857[1] if "601857" in symbol else b_000001[1],
                n_levels=n_levels, grid_type=grid_type,
            )
        ),
        position_mode=pos_mode,
        position_kwargs=pos_kwargs,
        risk_config={"cool_down": {"cool_down_bars": 3}},
        tag=tag,
    )
    return run_grid_backtest(cfg)

t0 = time.time()
total = 9
done_good = 0
done_fail = 0

# ====================================================================
# Grid (6)
# ====================================================================
print()
print(f"=== GRID (06) === [{datetime.now().isoformat()}]")
grid_specs = [
    ("601857.SH", 10, "arithmetic", "batcher", {"total_grid_rows": 10}, "static_n10_arithmetic_batcher_cd3"),
    ("601857.SH", 10, "geometric", "batcher", {"total_grid_rows": 10}, "static_n10_geometric_batcher_cd3"),
    ("601857.SH", 10, "arithmetic", "fixed", {"quantity": 100}, "static_n10_arithmetic_fixed_cd3"),
    ("000001.SZ", 10, "arithmetic", "batcher", {"total_grid_rows": 10}, "static_n10_arithmetic_batcher_cd3"),
    ("000001.SZ", 10, "arithmetic", "fixed", {"quantity": 100}, "static_n10_arithmetic_fixed_cd3"),
    ("601857.SH", 5, "arithmetic", "batcher", {"total_grid_rows": 5}, "static_n5_arithmetic_batcher_cd3"),
]

for i, (sym, nl, gt, pm, pk, tag) in enumerate(grid_specs):
    idx = i + 1
    start = time.time()
    try:
        r = run_grid(sym, nl, gt, pm, pk, tag)
        M = r.metrics
        elapsed = time.time() - start
        done_good += 1
        pf, ret, sr, mdd = M.get("profit_factor",0), M.get("total_return_pct",0), M.get("sharpe_ratio",0), M.get("max_drawdown_pct",0)
        trades = r.backtest_result.total_trades if r.backtest_result else M.get("total_trades",0)
        print(f"  [{idx}/{total}] {sym}/{tag} -> trades={trades} pf={pf:.4f} ret={ret:+.2f}% sharpe={sr:.4f} mdd={mdd:.2f}% [{elapsed:.1f}s]")
    except Exception as e:
        elapsed = time.time() - start
        done_fail += 1
        import traceback
        traceback.print_exc()
        print(f"  [{idx}/{total}] {sym}/{tag} -> FAILED: {e} [{elapsed:.1f}s]")

# ====================================================================
# Reversal (2)
# ====================================================================
print()
print(f"=== REVERSAL (02) === [{datetime.now().isoformat()}]")
rev_specs = [
    ("601857", "rsi", "fixed", "rsi_default"),
    ("000001", "rsi", "fixed", "rsi_default"),
]
for i, (sym, st, pm, tag) in enumerate(rev_specs):
    idx = len(grid_specs) + i + 1
    start = time.time()
    try:
        cfg = ReversalBacktestConfig(symbol=sym, signal_type=st, position_mode=pm, tag=tag)
        r = run_reversal_backtest(cfg)
        M = r.metrics
        elapsed = time.time() - start
        done_good += 1
        pf, ret, sr, mdd = M.get("profit_factor",0), M.get("total_return_pct",0), M.get("sharpe_ratio",0), M.get("max_drawdown_pct",0)
        trades = M.get("total_trades",0)
        print(f"  [{idx}/{total}] {sym}/{tag} -> trades={trades} pf={pf:.4f} ret={ret:+.2f}% sharpe={sr:.4f} mdd={mdd:.2f}% [{elapsed:.1f}s]")
    except Exception as e:
        elapsed = time.time() - start
        done_fail += 1
        import traceback
        traceback.print_exc()
        print(f"  [{idx}/{total}] {sym}/{tag} -> FAILED: {e} [{elapsed:.1f}s]")

# ====================================================================
# Trend (1)
# ====================================================================
print()
print(f"=== TREND (01) === [{datetime.now().isoformat()}]")
start = time.time()
try:
    cfg = TrendBacktestConfig(symbol="601857", signal_type="ma", position_mode="fixed", tag="default")
    r = run_trend_backtest(cfg)
    M = r.metrics
    elapsed = time.time() - start
    done_good += 1
    pf, ret, sr, mdd = M.get("profit_factor",0), M.get("total_return_pct",0), M.get("sharpe_ratio",0), M.get("max_drawdown_pct",0)
    trades = M.get("total_trades",0)
    print(f"  [9/9] 601857/ma_fixed -> trades={trades} pf={pf:.4f} ret={ret:+.2f}% sharpe={sr:.4f} mdd={mdd:.2f}% [{elapsed:.1f}s]")
except Exception as e:
    elapsed = time.time() - start
    done_fail += 1
    import traceback
    traceback.print_exc()
    print(f"  [9/9] 601857/ma_fixed -> FAILED: {e} [{elapsed:.1f}s]")

# ====================================================================
# Verify DB
# ====================================================================
print()
print(f"=== VERIFY DB ===")
elapsed_total = time.time() - t0
print(f"Total: {elapsed_total:.1f}s | OK: {done_good} | FAIL: {done_fail}")

try:
    kdb = KnowledgeDB()
    with kdb._conn() as conn:
        # latest records with profit_factor > 0
        rows = conn.execute("""
            SELECT r.strategy, r.config_key, r.symbol,
                   p.profit_factor, p.total_return_pct,
                   p.sharpe_ratio, p.max_drawdown_pct,
                   r.created_at
            FROM backtest_runs r
            JOIN performance_results p ON r.run_id = p.run_id
            WHERE p.profit_factor > 0
            ORDER BY r.created_at DESC
            LIMIT 20
        """).fetchall()

        print(f"\nNewly backfilled (profit_factor > 0): {len(rows)} records")
        print(f"{'strategy':<12} {'config_key':<45} {'symbol':<12} {'pf':<10} {'ret%':<8} {'sharpe':<8} {'mdd%':<8}")
        print("-" * 105)
        for r in rows:
            print(f"{r['strategy']:<12} {str(r['config_key'] or ''):<45} {r['symbol']:<12} "
                  f"{r['profit_factor']:<10.4f} {r['total_return_pct']:<8.2f} "
                  f"{r['sharpe_ratio']:<8.2f} {r['max_drawdown_pct']:<8.2f}")

        # zero-count (old legacy data)
        zero_cnt = conn.execute("SELECT COUNT(*) as cnt FROM performance_results WHERE profit_factor = 0").fetchone()
        print(f"\nLegacy records profit_factor=0 (untouched): {zero_cnt['cnt']}")

        # any suspicious <=0 in recent writes?
        suspect = conn.execute("""
            SELECT COUNT(*) as cnt FROM performance_results p
            JOIN backtest_runs r ON r.run_id = p.run_id
            WHERE r.created_at >= datetime('now', '-15 minutes')
              AND p.profit_factor <= 0
        """).fetchone()
        if suspect['cnt'] > 0:
            print(f"[WARN] {suspect['cnt']} recent writes with profit_factor <= 0")
        else:
            print("[OK] No recent writes with profit_factor <= 0")

    kdb.close()
except Exception as e:
    print(f"DB verification error: {e}")
    import traceback
    traceback.print_exc()

print("\nDone.")
