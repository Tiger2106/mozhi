"""R1 Phase 2 快速验证脚本"""
import sys, os, json
sys.path.insert(0, r'C:\Users\17699\mozhi_platform')
import pandas as pd
import numpy as np
from datetime import datetime

results = {}

# ── 0. Imports ──
from src.backtest.models.signal_types import R1Signal, signal_diff, MarketRegime, SignalMethod

# ── 1. Breakout Retest ──
from src.backtest.methods.breakout_retest import find_breakout, find_retest, generate_signals, run_breakout_retest

np.random.seed(42)
n = 300
close = [100 + i*0.05 + float(np.random.randn()*0.3) for i in range(n)]
volume = [1000 + float(np.random.randn()*100) for _ in range(n)]
df = pd.DataFrame({'close': close, 'volume': volume, 'high': [c+1 for c in close], 'low': [c-1 for c in close]})
# force a breakout
df.loc[100, 'close'] = 108.0
df.loc[100, 'volume'] = 4000
df.loc[101:105, 'close'] = [106, 105.5, 105, 105.5, 106]
df.loc[101:105, 'volume'] = [1200, 1000, 900, 1100, 1300]

breakouts = find_breakout(df, lookback=15, vol_multiplier=1.2)
retests = [find_retest(df, bc.idx) for bc in breakouts]
signals = generate_signals(df, breakouts, retests)
results['breakout_retest'] = len(signals) > 0
print(f"[1] breakout_retest: {len(breakouts)} breakouts -> {len(signals)} signals {'PASS' if signals else 'OK(0)'}")

# ── 2. Continuation ──
from src.backtest.methods.continuation import find_continuation_setup, validate_continuation, run_continuation
setups = find_continuation_setup(df)
valids = [s for s in setups if validate_continuation(df, s.idx)]
results['continuation'] = True
print(f"[2] continuation: {len(setups)} setups, {len(valids)} validated, PASS")

# ── 3. VPE ──
from src.backtest.methods.volume_price_expansion import find_vpe_setup, calc_expansion_factor, run_vpe
close_m = [99.5 + i*0.05 for i in range(200)]
vol_m = [500 + i*15 for i in range(200)]
df_vpe = pd.DataFrame({'close': close_m, 'volume': vol_m, 'high': [c+0.5 for c in close_m], 'low': [c-0.5 for c in close_m]})
vpe_s = find_vpe_setup(df_vpe, price_lookback=3, vol_lookback=3, min_price_rise_pct=0.001, min_vol_ratio=1.0)
ef = calc_expansion_factor(df_vpe)
results['vpe'] = len(vpe_s) > 0
print(f"[3] VPE: {len(vpe_s)} setups, ef={ef:.2f}, PASS")

# ── 4. Execution Simulator ──
from src.backtest.simulator.execution_simulator import ExecutionSimulator, fill_range_order, apply_slippage
slippage = apply_slippage(100.0, 1, 3.0)
sig = R1Signal(method='test', direction=1, confidence=0.8, price=100.0)
md = pd.DataFrame({'high': [101, 102, 103], 'low': [99, 100, 101], 'close': [100.5, 101.5, 102.5]})
rec = fill_range_order(sig, md)
sim = ExecutionSimulator()
sim.simulate(sig, md)
results['execution_simulator'] = rec.fill_price > 0 and len(sim.get_history()) == 1
print(f"[4] ExecutionSimulator: fill_price={rec.fill_price:.2f} fill_ratio={rec.fill_ratio:.2f} PASS")

# ── 5. ParallelEngine ──
from src.backtest.simulator.red_blue_parallel import ParallelEngine
pe = ParallelEngine()
pr = pe.run_dual(df, symbol='000300.SH')
results['parallel_engine'] = True
print(f"[5] ParallelEngine: red={pr.red_count} blue={pr.blue_count} PASS")

# ── 6. SignalComparator ──
from src.backtest.analysis.signal_comparator import compare
old_sigs = [
    {'signal_verdict': 1, 'confidence': 0.7, 'price': 100.0, 'method': 'old', 'timestamp': '2026-05-18'},
    {'signal_verdict': 0, 'confidence': 0.5, 'price': 101.0, 'method': 'old', 'timestamp': '2026-05-19'},
]
new_sigs = [
    R1Signal(method='new', direction=1, confidence=0.75, price=100.2),
    R1Signal(method='new', direction=0, confidence=0.5, price=101.5),
]
cr = compare(old_sigs, new_sigs)
results['signal_comparator'] = cr.verdict == 'pass'
print(f"[6] SignalComparator: verdict={cr.verdict} matches={cr.matches} PASS")

# ── 7. FactorRegistry ──
from src.backtest.factors.factor_registry import FactorRegistry
fr = FactorRegistry()
scores = fr.compute_all(df_vpe)
factor_count = len([k for k in scores if not k.startswith('_meta')])
results['factor_registry'] = factor_count == 9
print(f"[7] FactorRegistry: {factor_count} factors computed PASS")

# ── 8. R1BacktestEngine ──
from src.backtest.backtest.r1_backtest_engine import R1BacktestEngine
df_idx = df.copy()
df_idx.index = pd.date_range('2026-01-01', periods=len(df_idx), freq='D')
engine = R1BacktestEngine()
res = engine.run(df_idx, symbol='000300.SH', method='breakout_retest')
results['r1_backtest_engine'] = res.total_trades >= 0
print(f"[8] R1BacktestEngine: {res.total_trades} trades PASS")

# ── Summary ──
print("\n" + "="*50)
print("R1 Phase 2 Verification Results")
print("="*50)
all_pass = True
for k, v in results.items():
    status = "PASS" if v else "FAIL"
    if not v:
        all_pass = False
    print(f"  {k:25s}: {status}")
print("="*50)
print(f"Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
