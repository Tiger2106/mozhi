#!/usr/bin/env python3
"""P1-MC-3: 15:00 cron — settle_daily + backup_manager"""
import os, sys, json
from datetime import datetime, timezone, timedelta

# Path setup — 添加项目根路径和外部包
_AUTO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
_PROJECT_DIR = os.path.dirname(os.path.dirname(_AUTO_ROOT))  # = mozhi_platform
sys.path.insert(0, _PROJECT_DIR)          # 使 from src.config 可导入
sys.path.insert(0, os.path.dirname(_AUTO_ROOT))  # src → 使 trading/config/utils 等可导入
sys.path.insert(0, _AUTO_ROOT)             # reporting

# 添加外部包路径（mo_zhi_sharereports 体系）
_SHARED_DIR = r"C:\Users\17699\mo_zhi_sharereports"
_AUTOMATION_DIR = os.path.join(_SHARED_DIR, "automation_v2")
if os.path.isdir(os.path.join(_AUTOMATION_DIR, "paper_trade")):
    sys.path.insert(0, _AUTOMATION_DIR)  # paper_trade (has __init__.py)
if os.path.isdir(os.path.join(_AUTOMATION_DIR, "phase1_core")):
    sys.path.insert(0, _SHARED_DIR)      # automation_v2.phase1_core (namespace pkg)

import sqlite3
from pathlib import Path
from trading.core.account_manager import AccountManager
from paper_trade.order_engine import OrderEngine
from utils.backup_manager import BackupManager
from src.config import SHANGHAI_TZ

# All 6 paper-trade account IDs (fix v20260515: removed 'main' stub)
ACCOUNT_IDS = [
    "acct_agg",
    "acct_bal",
    "acct_con",
    "acct_tech_grid",
    "acct_tech_reversal",
    "acct_tech_trend",
]

TZ = SHANGHAI_TZ
SIGNALS = r"C:\Users\17699\mo_zhi_sharereports\signals"
DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"
BACKUP_DIR = r"C:\Users\17699\mo_zhi_sharereports\backup"


def main():
    now = datetime.now(TZ)
    date_str = now.strftime("%Y%m%d")
    print(f"[settle_backup_cron] {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 非交易日跳过
    if now.weekday() >= 5:
        print("[settle_backup_cron] 非交易日，跳过")
        return

    if not os.path.isfile(DB_PATH):
        print(f"[settle_backup_cron] 数据库不存在: {DB_PATH}，跳过")
        return

    # 初始化AM+OE
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    am = AccountManager(initial_capital=200_000.0, account_id=ACCOUNT_IDS[0], repository=None)
    am._conn = conn
    am._db_path = DB_PATH
    am._ensure_tables(conn)

    oe = OrderEngine(db_path=DB_PATH, account_manager=am)
    oe.set_connection(conn)

    try:
        # Step 1: settle_daily
        print(f"[settle_backup_cron] 执行 settle_daily...")
        result = oe.settle_daily(date=date_str, conn=conn)
        conn.commit()
        print(f"[settle_backup_cron] settle_daily 完成: status={result['status']}, "
              f"pnl={result.get('pnl', 'N/A')}, "
              f"cancelled={result.get('cancelled_count', 0)}")

        # Log loss_streak result (returned as int, per-account details in settlement JSON file)
        ls_value = result.get('loss_streak_update', 0)
        if isinstance(ls_value, dict):
            ls_data = ls_value.get('per_account', [])
            for acct in ls_data:
                print(f"[settle_backup_cron] {acct['account_id']}: loss_streak {acct['before']} -> {acct['after']}")
        else:
            print(f"[settle_backup_cron] loss_streak_update={ls_value}")

        # Step 2: backup
        print(f"[settle_backup_cron] 执行 backup...")
        # 确保WAL内容已刷新到主文件
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()

        bm = BackupManager(db_path=DB_PATH, backup_dir=BACKUP_DIR)
        backup_result = bm.run_daily_backup()
        print(f"[settle_backup_cron] 备份完成: {backup_result}")

        print(f"[settle_backup_cron] OK P1-MC-3 done")
    except Exception as e:
        print(f"[settle_backup_cron] FAILED: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
