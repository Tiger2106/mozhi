import json, os, sqlite3

# Map JSON filenames to run_ids
d = r'C:\Users\17699\mozhi_platform\src\backtest_results'
json_files = sorted([f for f in os.listdir(d) if f.endswith('.json')])

# JSON filename format: grid|trend|reversal_{symbol}_{config_key}_{timestamp}.json
# DB run_id format: run_grid|trend|reversal_{symbol}_{config_tag}_{timestamp}
# Check match pattern

conn = sqlite3.connect('data/knowledge.db')
cur = conn.cursor()
cur.execute('SELECT run_id FROM backtest_runs')
all_run_ids = set(r[0] for r in cur.fetchall())

matched = []
unmatched_files = []
unmatched_runs = []

for fname in json_files:
    # Convert JSON filename to run_id pattern
    fname_base = fname.replace('.json', '')
    expected_run_id = 'run_' + fname_base
    if expected_run_id in all_run_ids:
        matched.append(fname)
    else:
        unmatched_files.append(fname)

# Check if run_ids connect to JSON files (look at first 10)
cur.execute('SELECT run_id, strategy, symbol FROM backtest_runs LIMIT 10')
print('First 10 run_ids and whether they have a JSON file:')
for r in cur.fetchall():
    rid = r[0]
    # Remove 'run_' prefix to get JSON filename
    json_name = rid[4:] + '.json'  # strip 'run_' prefix
    has_json = os.path.exists(os.path.join(d, json_name))
    print('  %s -> json_exists=%s' % (rid, has_json))

print()
print('Total JSON files:', len(json_files))
print('Matched JSON -> backtest_runs:', len(matched))
print('Unmatched JSON files:', len(unmatched_files))

# What's in knowledge_run_links?
cur.execute('SELECT COUNT(*) FROM knowledge_run_links')
print('knowledge_run_links count:', cur.fetchone()[0])

conn.close()
