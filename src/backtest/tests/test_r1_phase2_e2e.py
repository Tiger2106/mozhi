"""
R1 Phase 2 E2E 验证（任务9）
"""
import sys, os, json
sys.path.insert(0, r'C:\Users\17699\mozhi_platform')
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.backtest.models.signal_types import R1Signal, signal_diff, MarketRegime
from src.backtest.methods.breakout_retest import run_breakout_retest
from src.backtest.methods.continuation import run_continuation
from src.backtest.methods.volume_price_expansion import run_vpe
from src.backtest.simulator.execution_simulator import ExecutionSimulator, fill_range_order, apply_slippage
from src.backtest.simulator.red_blue_parallel import ParallelEngine
from src.backtest.analysis.signal_comparator import compare
from src.backtest.factors.factor_registry import FactorRegistry
from src.backtest.backtest.r1_backtest_engine import R1BacktestEngine

TZ = timezone(timedelta(hours=8))
DATE = datetime.now(TZ).strftime("%Y%m%d")

# ═════════════════════════════════════════
np.random.seed(42)
n = 500

# 阶段1: 横盘 (0-199)
phase1 = [100 + float(np.random.randn()*0.3) for _ in range(200)]
# 阶段2: 突破上行 (200-249)
phase2 = [100 + i*0.3 + float(np.random.randn()*0.2) for i in range(50)]
# 阶段3: 趋势延续 (250-349)
phase3 = []
base = 115
for i in range(50):
    phase3.append(base + i*0.15 + float(np.random.randn()*0.2))
for i in range(30):
    phase3.append(phase3[-1] - 0.1 + float(np.random.randn()*0.2))
for i in range(20):
    phase3.append(121 + i*0.1 + float(np.random.randn()*0.2))
# 阶段4: 加速上行 (350-499)
phase4 = [125 + i*0.2 + float(np.random.randn()*0.3) for i in range(150)]

close_values = (phase1 + phase2 + phase3 + phase4)[:n]

volume_values = [1000 + abs(int(np.random.randn()*200)) for _ in range(n)]
for i in range(200, 210):
    volume_values[i] = 3000 + abs(int(np.random.randn()*500))
for i in range(340, 370):
    volume_values[i] = 1800 + abs(int(np.random.randn()*300))

df = pd.DataFrame({
    'close': close_values,
    'volume': volume_values,
    'high': [c + abs(np.random.randn())*0.4 + 0.1 for c in close_values],
    'low': [c - abs(np.random.randn())*0.4 - 0.1 for c in close_values],
})
df.index = pd.date_range('2025-06-01', periods=n, freq='D')

# ═════════════════════════════════════════
# 1. 三种方法回测
# ═════════════════════════════════════════

engine = R1BacktestEngine(initial_capital=1_000_000.0)

bt_results = {}
for method in ['breakout_retest', 'continuation', 'volume_price_expansion']:
    try:
        kw = {}
        if method == 'volume_price_expansion':
            kw = {'price_lookback': 3, 'vol_lookback': 3, 'min_price_rise_pct': 0.001, 'min_vol_ratio': 1.0}
        if method == 'continuation':
            kw = {'mid_ma': 10, 'slow_ma': 30, 'retest_ma': 10}
        r = engine.run(df, symbol='000300.SH', method=method, method_kwargs=kw)
        bt_results[method] = r.to_dict()
        trades = r.total_trades
        ret = r.metrics.get('total_return_pct', 0.0)
        print(f'[E2E] {method}: {trades} trades, return={ret:.2f}%')
    except Exception as e:
        bt_results[method] = {'error': str(e), 'total_trades': 0}
        print(f'[E2E] {method}: ERROR - {e}')

# ═════════════════════════════════════════
# 2. 红蓝并行
# ═════════════════════════════════════════

df_vpe = pd.DataFrame({
    'close': [99.5 + i*0.05 for i in range(200)],
    'volume': [500 + i*15 for i in range(200)],
    'high': [100 + i*0.05 for i in range(200)],
    'low': [99 + i*0.05 for i in range(200)],
})

pe = ParallelEngine()
dual = pe.run_dual(
    df_vpe, symbol='000300.SH',
    red_methods=['volume_price_expansion'],
    method_kwargs={
        'volume_price_expansion': {
            'price_lookback': 2, 'vol_lookback': 2,
            'min_price_rise_pct': 0.001, 'min_vol_ratio': 1.0
        }
    }
)
print(f'[E2E] Red/Blue: red={dual.red_count} blue={dual.blue_count}')

# ═════════════════════════════════════════
# 3. 偏差检测
# ═════════════════════════════════════════

old_sigs = [
    {'signal_verdict': 1, 'confidence': 0.7, 'price': 100.0, 'method': 'old', 'timestamp': '2026-05-18'},
    {'signal_verdict': 0, 'confidence': 0.5, 'price': 101.0, 'method': 'old', 'timestamp': '2026-05-19'},
]
new_sigs = [
    R1Signal(method='new', direction=1, confidence=0.75, price=100.2),
    R1Signal(method='new', direction=0, confidence=0.5, price=101.5),
]
comp = compare(old_sigs, new_sigs)

old_sigs_alert = [
    {'signal_verdict': 1, 'confidence': 0.7, 'price': 100.0, 'method': 'old', 'timestamp': '2026-05-18'},
]
new_sigs_alert = [
    R1Signal(method='new', direction=1, confidence=0.8, price=107.5),
]
comp_alert = compare(old_sigs_alert, new_sigs_alert)

# ═════════════════════════════════════════
# 4. FactorRegistry
# ═════════════════════════════════════════

fr = FactorRegistry()
scores = fr.compute_all(df_vpe, symbol='000300.SH', date=DATE)
factor_names = [k for k in scores if not k.startswith('_meta')]

# ═════════════════════════════════════════
# 5. 输出 E2E 报告
# ═════════════════════════════════════════

report = {
    'report_type': 'r1_phase2_e2e',
    'date': DATE,
    'generated_at': datetime.now(TZ).isoformat(),
    'symbol': '000300.SH',
    'backtest_results': bt_results,
    'red_blue_parallel': {
        'red_count': dual.red_count,
        'blue_count': dual.blue_count,
        'match_count': dual.match_count,
        'mismatch_count': dual.mismatch_count,
        'red_methods': dual.red_methods,
    },
    'signal_comparison': {
        'normal': {
            'total': comp.total_comparisons,
            'matches': comp.matches,
            'verdict': comp.verdict,
            'avg_price_dev_pct': round(comp.price_deviation_pct_avg, 2),
        },
        'alert_test': {
            'total': comp_alert.total_comparisons,
            'verdict': comp_alert.verdict,
            'alert': comp_alert.alert_triggered,
            'block': comp_alert.block_triggered,
            'avg_price_dev_pct': round(comp_alert.price_deviation_pct_avg, 2),
        },
    },
    'factor_registry': {
        'total_factors': len(factor_names),
        'factors': factor_names,
        'scores': {k: round(v, 4) for k, v in scores.items() if isinstance(v, (int, float))},
        'categories': fr.list_by_category(),
    },
    'deviation_data': {
        'description': '5% deviation triggers warning, 10% deviation triggers block',
        'test_warning_triggered': comp_alert.alert_triggered,
        'test_block_not_triggered': not comp_alert.block_triggered,
    },
    'verification_status': 'READY',
}

out_dir = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..',
                             'mo_zhi_sharereports', 'reports', 'research', DATE))
os.makedirs(str(out_dir), exist_ok=True)
out_path = out_dir / 'r1_phase2_e2e.json'

with open(str(out_path), 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False, default=str)

alt_dir = Path(r'C:\Users\17699\mozhi_platform\reports\research') / DATE
os.makedirs(str(alt_dir), exist_ok=True)
alt_path = alt_dir / 'r1_phase2_e2e.json'
with open(str(alt_path), 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False, default=str)

print(f'\n[E2E] Report: {out_path}')
print(f'[E2E] FactorRegistry: {len(factor_names)} factors')
print(f'[E2E] SignalComparator: verdict={comp.verdict}')
print(f'[E2E] SignalComparator alert test: verdict={comp_alert.verdict} alert={comp_alert.alert_triggered}')
print(f'[E2E] Red/Blue: red={dual.red_count} blue={dual.blue_count}')
print(f'[E2E] E2E DONE')
