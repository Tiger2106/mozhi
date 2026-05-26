import os

base = r'C:\Users\17699\mozhi_platform\data'

# Mark obsolete database files with .deprecated suffix
to_mark = [
    'backtest_back_202605.db',
    'backtest_v3_backup.db',
    'trade_engine_20260515.db',
]

for fname in to_mark:
    src = os.path.join(base, fname)
    dst = os.path.join(base, fname + '.deprecated')
    if os.path.exists(src) and not os.path.exists(dst):
        os.rename(src, dst)
        print(f"  {fname} -> {fname}.deprecated  OK")
    elif os.path.exists(dst):
        print(f"  {fname}  already marked (skipped)")
    else:
        print(f"  {fname}  NOT FOUND")

# analysis.db: actively referenced by pipeline.
# Mark as .deprecated and create a symlink/prefer-market notice
# Actually just note it for now - owner will decide.
print()
print("=== analysis.db ===")
print("Still referenced by pipeline_paths.py and 4 other active modules.")
print("Switching all references requires a coordinated update.")
print("Skipping auto-deprecate - waiting for owner decision.")

# Print final inventory
print()
print("=== Final inventory ===")
for f in sorted(os.listdir(base)):
    path = os.path.join(base, f)
    if os.path.isfile(path):
        kb = os.path.getsize(path) // 1024
        marker = ""
        if '.deprecated' in f:
            marker = " [DEPRECATED]"
        print(f"  {f:45s} {kb:>5}KB{marker}")
