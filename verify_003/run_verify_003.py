"""
VERIFY-003 随机因子噪声测试 — 独立运行脚本

直接运行 python run_verify_003.py 即可执行完整测试。
"""
import sys
import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 优先加入 mozhi_platform 路径
_MOZHI = r"C:\Users\17699\mozhi_platform"
if _MOZHI not in sys.path:
    sys.path.insert(0, _MOZHI)

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import numpy as np
from lib.random_ic_analysis import (
    get_recent_trade_dates,
    get_stock_codes,
    run_noise_ic_suite,
    analyze_noise_ic_results,
    print_analysis_report,
)

TZ = timezone(timedelta(hours=8))
DB_PATH = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"
OUTPUT_DIR = _THIS_DIR / "output"

# 配置
N_DATES = 50
SEEDS = [42, 123, 456, 789, 1024]
MIN_STOCKS = 30
FORWARD_WINDOW = 1
DISTRIBUTION = "normal"


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def main():
    print(f"VERIFY-003 启动时间: {datetime.now(TZ).isoformat()}")
    print(f"  DB: {DB_PATH}")
    print(f"  截面数: {N_DATES}")
    print(f"  种子: {SEEDS}")
    print(f"  前向窗口: {FORWARD_WINDOW}d")
    print(f"  分布: {DISTRIBUTION}")
    print()

    conn = sqlite3.connect(DB_PATH)
    stock_codes = get_stock_codes(conn)
    trade_dates = get_recent_trade_dates(conn, n_dates=N_DATES)
    conn.close()

    print(f"  A50成分股: {len(stock_codes)}")
    print(f"  有效交易日: {len(trade_dates)} ({trade_dates[0]} ~ {trade_dates[-1]})")
    print()

    print("运行随机因子 IC 试验套件...")
    df = run_noise_ic_suite(
        trade_dates=trade_dates,
        stock_codes=stock_codes,
        seeds=SEEDS,
        db_path=DB_PATH,
        forward_window=FORWARD_WINDOW,
        min_stocks=MIN_STOCKS,
        distribution=DISTRIBUTION,
    )
    print(f"  完成! 得到 {len(df)} 个有效结果\n")

    stats = analyze_noise_ic_results(df)
    print_analysis_report(stats)

    # 保存输出
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")

    csv_path = OUTPUT_DIR / f"noise_ic_results_{timestamp}.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n原始数据保存至: {csv_path}")

    json_path = OUTPUT_DIR / f"noise_ic_stats_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    print(f"统计数据保存至: {json_path}")

    ic_mean_ok = abs(stats["ic_mean"]) < 0.01
    ic_std_ok = abs(stats["ic_std"] - stats["ic_std_theoretical"]) < 0.03
    p_sig_ok = 0.03 <= stats["p_sig_rate"] <= 0.07
    pos_ok = 0.40 <= stats["positive_rate"] <= 0.60
    all_ok = all([ic_mean_ok, ic_std_ok, p_sig_ok, pos_ok])

    print(f"\n最终判定: {'PASS' if all_ok else 'NEED_REVIEW'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
