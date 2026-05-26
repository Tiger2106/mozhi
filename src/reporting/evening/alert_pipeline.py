#!/usr/bin/env python3
"""P2-MC-1: 警示管道 + 飞书通知 — 当healthcheck或交易异常时触发通知"""
import json, os, sys, glob
from datetime import datetime, timezone, timedelta
from src.config import SHANGHAI_TZ

TZ = SHANGHAI_TZ
SIGNALS = r"C:\Users\17699\mo_zhi_sharereports\signals"
ALERT_DIR = os.path.join(SIGNALS, "alerts")

def write_alert(source: str, severity: str, message: str, details: dict = None):
    """写入警示文件，供外部管道消费"""
    os.makedirs(ALERT_DIR, exist_ok=True)
    now = datetime.now(TZ)
    alert = {
        "source": source,
        "severity": severity,
        "message": message,
        "details": details or {},
        "timestamp": now.isoformat()
    }
    fn = f"alert_{source}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(ALERT_DIR, fn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(alert, f, ensure_ascii=False, indent=2)
    return path

def collect_and_deliver():
    """收集未读告警，输出摘要（可被cron消费后推送至飞书）"""
    os.makedirs(ALERT_DIR, exist_ok=True)
    alerts = sorted(glob.glob(os.path.join(ALERT_DIR, "alert_*.json")))
    if not alerts:
        print("[alert_pipeline] 当前无未处理告警")
        return

    groups = {"CRITICAL": [], "WARNING": [], "INFO": []}
    for ap in alerts:
        with open(ap, "r", encoding="utf-8") as f:
            try:
                a = json.load(f)
                sev = a.get("severity", "INFO")
                groups.setdefault(sev, []).append(a)
            except json.JSONDecodeError:
                pass

    now = datetime.now(TZ).strftime("%H:%M:%S")
    lines = [f"[alert_pipeline] {now} — 未处理告警:"]
    for sev, items in [("CRITICAL", groups["CRITICAL"]),
                       ("WARNING", groups["WARNING"]),
                       ("INFO", groups["INFO"])]:
        if items:
            lines.append(f"  [{sev}] {len(items)}条:")
            for a in items:
                lines.append(f"    • {a['message']} (来源:{a['source']})")

    print("\n".join(lines))
    # 读取后可标记处理（可选：改名去除.json扩展以避免重复消费）
    for ap in alerts:
        os.rename(ap, ap + ".processed")
    print(f"[alert_pipeline] ✅ 已标记{len(alerts)}条告警为processed")

if __name__ == "__main__":
    collect_and_deliver()
