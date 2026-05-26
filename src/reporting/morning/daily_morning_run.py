#!/usr/bin/env python3
from src.config import SHANGHAI_TZ
"""P1-MC-1: 每日08:00 cron — 交易日检查+管道启动+数据漂移检测"""
import os, sys, json
from datetime import datetime, timezone, timedelta

TZ = SHANGHAI_TZ
SIGNALS = r"C:\Users\17699\mo_zhi_sharereports\signals"

# 添加 paper_trade 包路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "paper_trade"))

def is_trade_day() -> bool:
    """简单交易日判断：周一~周五"""
    return datetime.now(TZ).weekday() < 5

def run_drift_detection():
    """执行数据漂移检测"""
    try:
        from drift_detector import DriftDetector
        detector = DriftDetector()
        result = detector.run_check()
        if result["drift_detected"]:
            print(f"[DRIFT] 发现 {len(result['issues'])} 处数据漂移 (共检查 {result['total_checked']} 条)")
            for iss in result["issues"][:5]:
                print(f"  • {iss['date']} {iss['symbol']:>6s} | {iss['type']:15s} | {iss['detail']}")
            if len(result["issues"]) > 5:
                print(f"  ... 还有 {len(result['issues'])-5} 项")
        else:
            print(f"[DRIFT] ✅ 未发现数据漂移 (共检查 {result['total_checked']} 条)")
    except ImportError as e:
        print(f"[DRIFT] ⚠️ drift_detector 未就绪: {e}")
    except Exception as e:
        print(f"[DRIFT] ❌ 漂移检测异常: {e}")

def run_ci_self_check():
    """开盘前pytest自检 — 集成CI/CD流水线"""
    import subprocess

    ci_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "run_ci.py")
    if not os.path.exists(ci_script):
        print("[CI_PRE_CHECK] ⚠️ run_ci.py 未找到，跳过自检")
        return
    try:
        proc = subprocess.run(
            [sys.executable, ci_script],
            capture_output=True, text=True,
            cwd=os.path.dirname(ci_script),
            timeout=300
        )
        print(proc.stdout)
        if proc.stderr:
            print(f"[CI_PRE_CHECK] stderr:\n{proc.stderr}")
        if proc.returncode == 0:
            print("[CI_PRE_CHECK] ✅ 开盘前pytest自检全部通过")
        else:
            print(f"[CI_PRE_CHECK] ⚠️ pytest自检发现 {proc.returncode} 个失败，详见上文")
    except subprocess.TimeoutExpired:
        print("[CI_PRE_CHECK] ⚠️ pytest自检超时(300s)")
    except Exception as e:
        print(f"[CI_PRE_CHECK] ❌ pytest自检异常: {e}")

def main():
    now = datetime.now(TZ)
    print(f"[daily_morning_run] {now.strftime('%Y-%m-%d %H:%M:%S')}")

    if not is_trade_day():
        print("[daily_morning_run] 非交易日，跳过")
        return

    # 写入 heartbeat 标记
    hb_path = os.path.join(SIGNALS, "consensus", "heartbeat")
    os.makedirs(hb_path, exist_ok=True)
    hb = {
        "agent": "mochen",
        "status": "active",
        "timestamp": now.isoformat(),
        "task": "daily_morning_run"
    }
    hb_file = os.path.join(hb_path, f"mochen_hb_morning_{now.strftime('%Y%m%d_%H%M%S')}.json")
    with open(hb_file, "w", encoding="utf-8") as f:
        json.dump(hb, f, ensure_ascii=False)

    print("[daily_morning_run] 交易日管道准备就绪，heartbeat已写入")

    # === 开盘前pytest自检 ===
    run_ci_self_check()

    # === 数据漂移检测 ===
    run_drift_detection()

    print("[daily_morning_run] ✅ P1-MC-1 执行完成")

if __name__ == "__main__":
    main()
