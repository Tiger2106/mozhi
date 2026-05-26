import os, sqlite3
from datetime import datetime

base = r'C:\Users\17699\mozhi_platform\data'
files = [f for f in os.listdir(base) if f.endswith('.db')]

for fname in sorted(files):
    path = os.path.join(base, fname)
    size_kb = os.path.getsize(path) // 1024
    mtime = os.path.getmtime(path)
    dt = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cur.fetchall()]
    
    # Identify purpose
    purpose = ''
    if 'market' in fname.lower():
        purpose = '【官方唯一源】股票日线 + 复权因子 + 日历'
    elif 'analysis' in fname.lower():
        purpose = '【冗余】股票原始行情 + 原油 + 技术指标'
    elif 'backtest' in fname.lower():
        purpose = '【回测】策略回测结果'
    elif 'trade_engine' in fname.lower():
        purpose = '【交易引擎】实盘记录'
    elif 'knowledge' in fname.lower():
        purpose = '【知识库】系统记忆'
    else:
        purpose = '其他'
    
    print(f"{fname:40s} {size_kb:>5}KB  {dt}  {purpose}")
    print(f"  表: {', '.join(tables[:6])}")
    conn.close()
