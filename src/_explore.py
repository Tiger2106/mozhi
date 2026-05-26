import json, os

base = r'C:\Users\17699\mozhi_platform\src\backtest_results'
path = os.path.join(base, 'grid_601857.SH_static_n10_arithmetic_batcher_cd3_static_n10_arithmetic_batcher_cd3_20260516_194030.json')
with open(path, encoding='utf-8') as f:
    data = json.load(f)

result = data['result']

print('=== config ===')
print(json.dumps(result['config'], indent=2, ensure_ascii=False))
print()
print('=== actual_range ===')
print(json.dumps(result['actual_range'], indent=2, ensure_ascii=False))
print()
print('=== metrics ===')
print(json.dumps(result['metrics'], indent=2, ensure_ascii=False))
print()
print('=== buy_hold_kpi ===')
print(json.dumps(result['buy_hold_kpi'], indent=2, ensure_ascii=False))
print()

ec = result['equity_curve']
print(f'=== equity_curve ({len(ec)} entries) ===')
for e in ec[:5]:
    print(f'  {e}')
print('  ...')
for e in ec[-5:]:
    print(f'  {e}')

trades = result['trades']
print(f'\n=== trades ({len(trades)}) ===')
for t in trades:
    print(json.dumps(t, indent=2, ensure_ascii=False))

snaps = result['snapshots']
print(f'\n=== snapshots ({len(snaps)}) ===')
print(f'  first snapshot: {json.dumps(snaps[0], ensure_ascii=False)[:400]}')
# Check a few position snapshots
pos_snaps = [(i, s) for i, s in enumerate(snaps) if s.get('positions')]
print(f'  snapshots with positions: {len(pos_snaps)}')
