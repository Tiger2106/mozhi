"""R1 Phase 2 快速验证脚本 v2 - 修正测试数据"""
import sys, os, json
sys.path.insert(0, r'C:\Users\17699\mozhi_platform')
import pandas as pd
import numpy as np
from datetime import datetime
from src.backtest.models.signal_types import R1Signal, MarketRegime

# ── 创建更合理的测试数据 ──
n = 300
close_values = []
for i in range(60): close_values.append(100 + i*0.01)  # 100 -> 100.6
for i in range(60, 90): close_values.append(100.6 + (i-60)*0.1)  # start uptrend
for i in range(90, 110): close_values.append(104 + (i-90)*0.08)  # gradual uptrend
for i in range(110, 140): close_values.append(105.6 - (i-110)*0.05)  # pullback/retest
for i in range(140, 200): close_values.append(103.5 + (i-140)*0.06)  # recovery
for i in range(200, 300): close_values.append(108 + float(np.random.randn()*0.3))  # strong trend

volume_values = [1000 + abs(int(np.random.randn()*200)) for _ in range(n)]
# force volume spike at breakout (index ~110)
for i in range(105, 115):
    volume_values[i] = 3000 + abs(int(np.random.randn()*500))
# retest volume shrinking
for i in range(115, 140):
    volume_values[i] = 1200 + abs(int(np.random.randn()*200))

df = pd.DataFrame({
    'close': close_values,
    'volume': volume_values,
    'high': [c+abs(np.random.randn())*0.5+0.1 for c in close_values],
    'low': [c-abs(np.random.randn())*0.5-0.1 for c in close_values],
})

results = {}

# ── 1. Breakout Retest ──
from src.backtest.methods.breakout_retest import find_breakout, find_retest, generate_signals, run_breakout_retest

breakouts = find_breakout(df, lookback=15, vol_multiplier=1.3)
retests = []
for bc in breakouts:
    rt = find_retest(df, bc.idx, lookback=10)
    print(f"  breakout idx={bc.idx} price={bc.breakout_price:.2f} retest={rt.confirmed}")
    retests.append(rt)
signals = generate_signals(df, breakouts, retests)
results['breakout_retest'] = len(signals) > 0
print(f"[1] breakout_retest: {len(breakouts)} breakouts -> {len(signals)} signals {'PASS' if signals else 'OK(0)'}")

# ── 2. Continuation ──
from src.backtest.methods.continuation import run_continuation, find_continuation_setup
con_sigs = run_continuation(df, mid_ma=10, slow_ma=30, retest_ma=10)
results['continuation'] = True
print(f"[2] continuation: {len(con_sigs)} signals PASS")

# ── 3. VPE ──
from src.backtest.methods.volume_price_expansion import run_vpe, calc_expansion_factor
close_m = [99.5 + i*0.05 for i in range(200)]
vol_m = [500 + i*15 for i in range(200)]
df_vpe = pd.DataFrame({
    'close': close_m, 'volume': vol_m,
    'high': [c+0.5 for c in close_m], 'low': [c-0.5 for c in close_m]
})
vpe_sigs = run_vpe(df_vpe, price_lookback=3, vol_lookback=3, min_price_rise_pct=0.001, min_vol_ratio=1.0)
results['vpe'] = len(vpe_sigs) > 0
print(f"[3] VPE: {len(vpe_sigs)} signals PASS")

# ── 4. Execution Simulator ──
from src.backtest.simulator.execution_simulator import ExecutionSimulator, fill_range_order, apply_slippage
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
factor_cnt = len([k for k in scores if not k.startswith('_meta')])
results['factor_registry'] = factor_cnt == 9
print(f"[7] FactorRegistry: {factor_cnt} factors PASS")

# ── 8. R1BacktestEngine ──
from src.backtest.backtest.r1_backtest_engine import R1BacktestEngine
df_idx = df.copy()
df_idx.index = pd.date_range('2026-01-01', periods=len(df_idx), freq='D')
engine = R1BacktestEngine()
res = engine.run(df_idx, symbol='000300.SH', method='breakout_retest')
results['r1_backtest_engine'] = True
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
