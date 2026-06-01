import sys, json
sys.path.insert(0, '.')

# 读取基线
with open('experiments/baselines/backtest_golden_baseline_bc5f464.json') as f:
    bl = json.load(f)

bl_trades = bl['output']['trades']
bl_metrics = bl['output']['metrics']

print('基线终值:', bl_metrics['final_capital'])
print('基线收益:', bl_metrics['total_return_pct'], '%')
print('基线交易:', bl_metrics['total_trades'])
print()

# 当前运行
from src.backtest.engine.engine import run_backtest
r = run_backtest()
print('当前终值:', r.final_capital)
print('当前收益:', r.total_return_pct, '%')
print('当前交易:', len(r.trades))
print()

dev_nav = abs(r.final_capital - float(bl_metrics['final_capital']))
pct_dev = dev_nav / float(bl_metrics['final_capital']) * 100
print('NAV偏差:', round(dev_nav, 2), '(', round(pct_dev, 4), '%)')
status = 'PASS' if pct_dev < 0.01 else 'FAIL'
print('结果:', status)
