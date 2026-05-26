import json, os, sqlite3

# Check all JSON files count
d = r'C:\Users\17699\mozhi_platform\src\backtest_results'
json_files = [f for f in os.listdir(d) if f.endswith('.json')]
print('JSON files:', len(json_files))

# Check first JSON against run_ids
conn = sqlite3.connect('data/knowledge.db')
cur = conn.cursor()

with open(os.path.join(d, json_files[0]), 'r') as f:
    js = json.load(f)
    meta = js.get('meta', {})
print('First JSON meta: symbol=%s, config_key=%s, timestamp=%s' % (
    meta.get('symbol'), meta.get('config_key'), meta.get('timestamp')))

# Check backtest_runs
cur.execute('SELECT run_id, strategy, symbol, config_key, created_at FROM backtest_runs LIMIT 5')
print('Backtest runs:')
for r in cur.fetchall():
    print('  run_id=%s..., strategy=%s, symbol=%s, config_key=%s, created_at=%s' % (
        r[0][:50] if r[0] else '', r[1], r[2], r[3], r[4]))

# performance_results
cur.execute('PRAGMA table_info(performance_results)')
print('performance_results cols:', [c[1] for c in cur.fetchall()])
cur.execute('SELECT * FROM performance_results LIMIT 1')
row = cur.fetchone()
if row:
    print('performance_results sample:', row)
conn.close()
