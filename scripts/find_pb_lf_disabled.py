"""查找pb_lf禁用原因"""
import sqlite3, os

db = r'C:\Users\17699\mozhi_platform\data\market\a50_ic.db'
conn = sqlite3.connect(db)
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("=== 数据库中的表 ===")
for t in tables:
    name = t[0]
    cols = conn.execute(f"PRAGMA table_info({name})").fetchall()
    cnames = [c[1] for c in cols]
    print(f"{name}: {cnames}")

    # 搜索pb_lf
    for c in cnames:
        try:
            r = conn.execute(f"SELECT DISTINCT {c} FROM {name} WHERE {c} LIKE '%pb_lf%'").fetchall()
            if r:
                print(f"  >>> {c} 包含pb_lf: {r}")
        except:
            pass

conn.close()

# 搜索所有py文件中对pb_lf enabled=False的引用
print("\n=== 搜索pb_lf禁用逻辑 ===")
import glob
for f in glob.glob(r'C:\Users\17699\mozhi_platform\src\**\*.py', recursive=True):
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            content = fh.read()
            if 'pb_lf' in content:
                lines = [l for l in content.split('\n') if 'pb_lf' in l.lower()]
                if lines:
                    print(f"\n{f}:")
                    for l in lines[:10]:
                        print(f"  {l.strip()}")
    except:
        pass

print("\n=== 搜索注册/配置 JSON ===")
for f in glob.glob(r'C:\Users\17699\mozhi_platform\**\*.json', recursive=True):
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            content = fh.read()
            if 'pb_lf' in content.lower():
                print(f"\n{f}: {len(content)} bytes")
                for i, line in enumerate(content.split('\n')):
                    if 'pb_lf' in line.lower():
                        print(f"  L{i+1}: {line.strip()}")
    except:
        pass
