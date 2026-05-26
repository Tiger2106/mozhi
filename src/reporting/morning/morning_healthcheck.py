#!/usr/bin/env python3
"""P1-MC-2: 08:05-15:00 每30分钟 cron — healthcheck巡检"""
import os, sys, json
from datetime import datetime, timezone, timedelta
from src.config import SHANGHAI_TZ

TZ = SHANGHAI_TZ
SIGNALS = r"C:\Users\17699\mo_zhi_sharereports\signals"

def main():
    now = datetime.now(TZ)
    seq = int(now.timestamp())
    hb_dir = os.path.join(SIGNALS, "consensus", "heartbeat")
    os.makedirs(hb_dir, exist_ok=True)

    hb = {
        "type": "agent_heartbeat",
        "agent": "mochen",
        "seq": seq,
        "status": "active",
        "timestamp": now.isoformat(),
        "current_task": {
            "task_id": None,
            "step": "healthcheck",
            "spawning": None
        },
        "health": {
            "cpu_load": 0.0,
            "memory_pct": 0,
            "last_error": None,
            "error_count_1h": 0
        }
    }
    hb_file = os.path.join(hb_dir, f"mochen_hb_{seq}.json")
    with open(hb_file, "w", encoding="utf-8") as f:
        json.dump(hb, f, ensure_ascii=False)

    # 清理旧心跳（保留最近10条）
    hbs = sorted([f for f in os.listdir(hb_dir) if f.startswith("mochen_hb_") and f.endswith(".json")])
    for old in hbs[:-10]:
        try:
            os.remove(os.path.join(hb_dir, old))
        except OSError:
            pass

    # 检查基础目录连通性
    checks = {
        "signals_exists": os.path.isdir(SIGNALS),
        "paper_trade_dir": os.path.isdir(os.path.join(SIGNALS, "paper_trade")),
        "tasks_dir": os.path.isdir(os.path.join(SIGNALS, "tasks")),
    }
    all_ok = all(checks.values())
    status = "OK" if all_ok else "WARN"
    print(f"[morning_healthcheck] {now.strftime('%H:%M:%S')} status={status}")
    for k, v in checks.items():
        print(f"  {k}: {'[OK]' if v else '[FAIL]'}")

    if not all_ok:
        print("[morning_healthcheck] WARN: 部分目录不存在，系统可能未完全初始化")
    else:
        print("[morning_healthcheck] OK: P1-MC-2 执行完成")

if __name__ == "__main__":
    main()
