#!/usr/bin/env python3
from src.config import SHANGHAI_TZ
"""P2-MC-2: 成交后偏差检查 — 信号suggested_price vs 实际成交价，偏差>5%写deviation_alert"""
import json, os, sys
from datetime import datetime, timezone, timedelta

TZ = SHANGHAI_TZ
SIGNALS = r"C:\Users\17699\mo_zhi_sharereports\signals"
DEVIATION_THRESHOLD = 0.05  # 5%

def check_deviation(signal: dict, fill_price: float):
    """
    检查信号建议价与实际成交价的偏差。
    返回 (has_deviation, deviation_pct, alert_message)
    """
    suggested = signal.get("suggested_price")
    if suggested is None or suggested <= 0:
        return False, 0.0, None

    deviation_pct = abs(fill_price - suggested) / suggested
    if deviation_pct >= DEVIATION_THRESHOLD:
        alert = (
            f"成交价偏差 {deviation_pct:.1%}: "
            f"{signal.get('symbol','?')} "
            f"建议价{suggested:.2f} → 实成交{fill_price:.2f}"
        )
        return True, deviation_pct, alert
    return False, deviation_pct, None

def write_deviation_alert(signal: dict, fill_price: float, order_id: int):
    """写入偏差预警JSON"""
    has_dev, dev_pct, msg = check_deviation(signal, fill_price)
    if not has_dev:
        return None

    alert_dir = os.path.join(SIGNALS, "alerts")
    os.makedirs(alert_dir, exist_ok=True)
    now = datetime.now(TZ)
    entry = {
        "alert_type": "price_deviation",
        "severity": "WARNING",
        "order_id": order_id,
        "task_id": signal.get("task_id", "?"),
        "symbol": signal.get("symbol", "?"),
        "action": signal.get("action", "?"),
        "suggested_price": signal.get("suggested_price"),
        "fill_price": fill_price,
        "deviation_pct": round(dev_pct, 4),
        "threshold": DEVIATION_THRESHOLD,
        "message": msg,
        "timestamp": now.isoformat()
    }
    fn = f"deviation_{signal.get('task_id','unknown')}_{order_id}.json"
    path = os.path.join(alert_dir, fn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    print(f"[deviation_check] ⚠️ {msg}")
    return path

if __name__ == "__main__":
    # CLI 测试
    import argparse

    parser = argparse.ArgumentParser(description="price deviation check")
    parser.add_argument("--signal-file", required=True, help="信号JSON文件路径")
    parser.add_argument("--fill-price", type=float, required=True, help="实际成交价")
    parser.add_argument("--order-id", type=int, default=0, help="订单ID")
    args = parser.parse_args()
    with open(args.signal_file, "r", encoding="utf-8") as f:
        signal = json.load(f)
    path = write_deviation_alert(signal, args.fill_price, args.order_id)
    if path:
        print(f"[deviation_check] 预警已写入: {path}")
    else:
        print("[deviation_check] 无偏差，正常")
