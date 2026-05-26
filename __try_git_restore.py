#!/usr/bin/env python3
"""
Fix check_orders_fill.py - comprehensive encoding fix
"""
import subprocess, sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
cwd = r'C:\Users\17699\mozhi_platform'

# First try git restore
result = subprocess.run(
    ['git', 'restore', path],
    cwd=cwd,
    capture_output=True, text=True
)
if result.returncode == 0:
    print('Git restore successful!')
    # Try running it
    r2 = subprocess.run(
        [sys.executable, path, '--mode', 'check_only'],
        capture_output=True, text=True, timeout=30
    )
    print(f'stdout: {r2.stdout[:500]}')
    print(f'stderr: {r2.stderr[:500]}')
    sys.exit(0 if r2.returncode == 0 else 1)
else:
    print(f'Git restore failed: {result.stderr[:200]}')
    print('Will rebuild from scratch')
