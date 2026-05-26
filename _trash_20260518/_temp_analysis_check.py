# -*- coding: utf-8 -*-
import sys
from pathlib import Path
from datetime import datetime

# 1. 回测记录统计
import sqlite3
conn = sqlite3.connect('data/knowledge.db')
cur = conn.cursor()
runs = cur.execute('SELECT strategy, COUNT(*) as cnt, MAX(created_at) FROM backtest_runs GROUP BY strategy ORDER BY cnt DESC').fetchall()
print('=== 回测记录统计 ===')
for r in runs:
    ts = r[2][:16] if r[2] else "N/A"
    print(f'  {r[0]}: {r[1]} 条, 最新 {ts}')

# 2. 知识分析产出
entries = cur.execute('SELECT strategy, category, title, created_at FROM knowledge_entries ORDER BY created_at DESC LIMIT 10').fetchall()
print(f'\n=== 知识分析产出 ({len(entries)} 条最新) ===')
for e in entries:
    ts = e[3][:16] if e[3] else "N/A"
    title = e[2][:40] if e[2] else "N/A"
    print(f'  [{e[0]}] {title} ({ts})')
conn.close()

# 3. 检查报告目录
mo_zhi = Path(r'C:\Users\17699\mo_zhi_sharereports\reports')
reports = []
for p in mo_zhi.rglob('*'):
    if p.is_file() and p.suffix in ('.md', '.json', '.txt'):
        mtime = p.stat().st_mtime
        reports.append((mtime, p))
reports.sort(reverse=True)
print(f'\n=== 最新产出文件 (top 15) ===')
for mtime, p in reports[:15]:
    dt = datetime.fromtimestamp(mtime).strftime('%H:%M')
    sz = p.stat().st_size
    rel = p.relative_to(mo_zhi)
    print(f'  {dt} {rel} ({sz/1024:.1f}KB)')

# 4. 回测 JSON 结果文件
results_dir = Path('src/backtest_results')
if results_dir.exists():
    json_files = list(results_dir.glob('*.json'))
    print(f'\n=== 回测结果 JSON: {len(json_files)} 个文件 ===')
    if json_files:
        # 按时间排序，展示最近5个
        json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for jf in json_files[:5]:
            mtime = datetime.fromtimestamp(jf.stat().st_mtime).strftime('%H:%M')
            sz = jf.stat().st_size
            print(f'  {mtime} {jf.name} ({sz/1024:.1f}KB)')
else:
    print('\n❌ src/backtest_results/ 目录不存在')

import os
os.remove(__file__)
