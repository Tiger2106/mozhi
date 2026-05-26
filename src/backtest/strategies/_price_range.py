import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "market" / "market_data.db"
conn = sqlite3.connect(str(DB))
cur = conn.cursor()
cur.execute("SELECT MIN(close), MAX(close), AVG(close), MIN(low), MAX(high), MIN(date), MAX(date) FROM stock_daily WHERE code='601857'")
r = cur.fetchone()
print(f"Close range: {r[0]:.2f} - {r[1]:.2f}, avg: {r[2]:.2f}")
print(f"Low range: {r[3]:.2f} - High: {r[4]:.2f}")
print(f"Date range: {r[5]} - {r[6]}")
conn.close()
