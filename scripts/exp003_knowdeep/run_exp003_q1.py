"""
EXP-2026-003-KNOWDEEP Q1: 跨窗口鲁棒性验证 — 回测主脚本
============================================================
author: 墨衡 (moheng)
created: 2026-05-26T16:34+08:00

执行 Q1 工作包规定的完整分析流水线：
  Step 1: 从 market_data.db 加载 A50 全池日线数据
  Step 2: 计算两因子 (l_vol_rsi_std / TrendQuality)
  Step 2.3: 数据质量前置检查
  Step 3: 市场状态分类（滚动波动率分位数）
  Step 4: 双窗口 IC 计算（训练期 2007~2019 / 验证期 2020~2026-04）
  Step 5: Bootstrap 置换检验 + FDR BH 校正（双窗口独立）
  Step 5.3: 三层稳定性检验（验证期）
  Step 5.4: 跨窗口衰减分析（IC 衰减率判定）
  Step 5.5: 因子间相关性预计算（为 Q2 做准备）
  Step 6: 生成输出报告

配置:
  - 数据源: market_data.db
  - 标的: A50 全池（从数据库自动读取）
  - 训练期: 2007-01-01 ~ 2019-12-31
  - 验证期: 2020-01-01 ~ 2026-04-30
  - 持有期: 20 日主验证（5日/10日参考输出，附带成本警示）
  - 交易成本: commission=0.0003, stamp_tax=0.0005(卖出), slippage=0.001
  - 随机种子: 42

使用:
  python scripts/exp003_knowdeep/run_exp003_q1.py [--dry-run] [--skip-qc]

输出目录:
  reports/EXP-2026-003-KNOWDEEP/q1/
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

import numpy as np


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# ── 自检清单模块（超时检查用） ──
from scripts.exp003_knowdeep.self_check import check_timeout

# ── 控制台编码修复（Windows GBK 兼容） ──
import io
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass
try:
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass


# ── 项目路径 ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 继承 EXP-002 的内部模块
from scripts.exp_invfac002.exp_factors import (
    calc_trend_quality,
    calc_vol_rsi_std,
    reverse_factor,
)
from scripts.exp_invfac002.exp_market_state import classify_market_state
from scripts.exp_invfac002.exp_bootstrap import (
    bootstrap_ic_test,
    spearman_correlation,
    apply_verdict_degradation,
)
from scripts.exp_invfac002.exp_stability import (
    check_time_slice_stability,
    check_rolling_stability,
    check_cross_sectional_stability,
    check_oos_stability,
)
from scripts.exp_invfac002.data_qc_check import run_all_checks as run_data_qc


# ── 全局配置 ──

# 超时阈值（秒）：40分钟
TIMEOUT_THRESHOLD_SECONDS = 2400

DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "EXP-2026-003-KNOWDEEP", "q1")

# 时间窗口（训练期 → 验证期，独立窗口设计）
TRAIN_START = "20070101"
TRAIN_END   = "20191231"
VAL_START   = "20200101"
VAL_END     = "20260430"

RANDOM_SEED = 42

# 交易成本（净收益计算用）
COMMISSION_RATE = 0.0003   # 佣金费率（不含印花税）
STAMP_TAX_RATE  = 0.0005   # 印花税（仅卖出时征收）
SLIPPAGE        = 0.001    # 滑点（单边）
COST_PER_TRADE  = COMMISSION_RATE + SLIPPAGE          # 买入单边成本 0.13%
COST_PER_SELL   = COMMISSION_RATE + STAMP_TAX_RATE + SLIPPAGE  # 卖出单边成本 0.18%
COST_ROUND_TRIP = COST_PER_TRADE + COST_PER_SELL      # 完整交易成本 0.31%


# ── 版本标记 ──
def get_version_tag() -> str:
    """获取 git HEAD hash (short) 作为版本标记"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ── 因子配置（仅 Q1 两因子：l_vol_rsi_std + TrendQuality） ──
FACTORS = {
    "l_vol_rsi_std": {
        "func": calc_vol_rsi_std,
        "fields": ["volume"],
        "params": {"rsi_period": 14, "std_period": 20},
        "expected_direction": "positive",  # EXP-002 高波动/20d 下 IC=+0.0478
    },
    "TrendQuality": {
        "func": calc_trend_quality,
        "fields": ["high", "low", "close"],
        "params": {"period": 20},
        "expected_direction": "negative",  # EXP-002 高波动/20d 下 IC=-0.0202
    },
}

# 持有期配置：20d 为主验证，5d/10d 为参考（附带成本警示）
HOLDING_PERIODS = [5, 10, 20]
PRIMARY_HOLDING = 20

# 波动率状态（聚焦 high_vol，扩展 low/mid 在 Q3）
STATE_LABELS = {0: "low_vol", 1: "mid_vol", 2: "high_vol"}
PRIMARY_STATE = "high_vol"

# 稳定性检验配置
STABILITY_N_SLICES = 4
STABILITY_MAX_FLIP_RATE = 0.30
STABILITY_N_STOCKS = None  # 运行时自动设定
STABILITY_MIN_AGREE_CROSS = None  # 运行时自动设定
STABILITY_L3_REQUIRED = 3

# FDR
FDR_Q = 0.05

# 跨窗口衰减判定阈值
DECAY_THRESHOLD_PASS = 0.50   # 衰减率 ≤ 50% → PASS
DECAY_THRESHOLD_WARN = 1.00   # 衰减率 > 50% 但 < 100% → WARN
                                # 衰减率 ≥ 100% → FAIL


# ===================================================================
#  辅助函数
# ===================================================================

def load_stock_codes() -> list[str]:
    """从 market_data.db 读取全部可用标的代码（自动扩展至 A50 全池）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT ts_code FROM stock_daily ORDER BY ts_code")
    codes = [r[0] for r in cursor.fetchall()]
    conn.close()
    return codes


def load_stock_data(ts_code: str) -> dict:
    """从 market_data.db 加载个股数据并 QFQ 复权"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT trade_date, open, high, low, close, volume, adj_factor
        FROM stock_daily
        WHERE ts_code=?
        ORDER BY trade_date
    """, (ts_code,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    dates = np.array([r[0] for r in rows])
    open_p = np.array([r[1] for r in rows], dtype=float)
    high = np.array([r[2] for r in rows], dtype=float)
    low = np.array([r[3] for r in rows], dtype=float)
    close = np.array([r[4] for r in rows], dtype=float)
    volume = np.array([r[5] for r in rows], dtype=float)
    adj_factor = np.array([r[6] if r[6] else 1.0 for r in rows], dtype=float)

    # QFQ 前复权
    latest_adj = adj_factor[-1] if len(adj_factor) > 0 else 1.0
    adj_ratio = adj_factor / latest_adj

    return {
        "code": ts_code,
        "dates": dates,
        "open": open_p * adj_ratio,
        "high": high * adj_ratio,
        "low": low * adj_ratio,
        "close": close * adj_ratio,
        "volume": volume,
        "adj_factor_raw": adj_factor,
    }


def find_date_range(dates: np.ndarray, start: str, end: str) -> tuple[int, int]:
    """在日期数组中查找 start~end 索引区间"""
    start_idx = np.searchsorted(dates, start, side="left")
    end_idx = np.searchsorted(dates, end, side="right")
    return start_idx, end_idx


def compute_forward_returns(close: np.ndarray, period: int) -> np.ndarray:
    """计算前向收益率（含成本扣除）"""
    fwd_ret = np.full(len(close), np.nan)
    for i in range(len(close) - period):
        raw_ret = close[i + period] / close[i] - 1
        # 扣除交易成本（买入 + 卖出）
        fwd_ret[i] = raw_ret - COST_ROUND_TRIP
    return fwd_ret


# ===================================================================
#  §2.3: 数据质量前置检查
# ===================================================================

def step_qc_preamble(stock_codes: list[str]) -> bool:
    """§2.3 数据质量前置检查。返回 True=通过，False=阻断。"""
    print(f"\n[Step 2.3] 数据质量前置检查 (§2.3)...")
    print(f"{'─' * 50}")
    result = run_data_qc(stock_codes, start=TRAIN_START, end=VAL_END, skip_bh=True)
    if not result.get("overall_passed", True):
        print(f"\n  [FAIL] 数据质量检查未通过，流水线终止。")
        return False
    print(f"\n  [OK] 数据质量检查全部通过。继续执行主流程。")
    return True


# ===================================================================
#  Step 5.4: 跨窗口衰减分析
# ===================================================================

def compute_decay_analysis(train_results: dict, val_results: dict) -> dict:
    """
    计算训练期→验证期的 IC 方向一致性和衰减率。

    判定逻辑:
      - PASS: 方向一致 + 衰减率 ≤ 50%
      - WARN: 方向一致但衰减率 > 50% 且 < 100%（或 FDR 不显著）
      - FAIL: 方向不一致 或 衰减率 ≥ 100%
    """
    print(f"\n[Step 5.4] 跨窗口衰减分析...")
    print(f"{'─' * 50}")

    decay_results = {}

    # 样本量门限常量（引擎级硬逻辑）
    SAMPLE_SIZE_THRESHOLD = 3000

    for fname in FACTORS:
        decay_results[fname] = {}
        for state_label in ["high_vol", "mid_vol", "low_vol"]:
            decay_results[fname][state_label] = {}
            for period in HOLDING_PERIODS:
                train_ic = train_results.get(fname, {}).get(state_label, {}).get(period, {}).get("ic_mean")
                val_ic = val_results.get(fname, {}).get(state_label, {}).get(period, {}).get("ic_mean")
                train_p = train_results.get(fname, {}).get(state_label, {}).get(period, {}).get("p_value")
                val_p = val_results.get(fname, {}).get(state_label, {}).get(period, {}).get("p_value")
                train_sig = train_results.get(fname, {}).get(state_label, {}).get(period, {}).get("significant", False)
                val_sig = val_results.get(fname, {}).get(state_label, {}).get(period, {}).get("significant", False)
                val_n = val_results.get(fname, {}).get(state_label, {}).get(period, {}).get("n_samples", 0)

                if train_ic is None or val_ic is None:
                    decay_results[fname][state_label][period] = {
                        "verdict": "NODATA",
                        "train_ic": None,
                        "val_ic": None,
                        "decay_rate": None,
                        "direction_consistent": None,
                        "n_samples_val": val_n,
                        "sample_size_degraded": False,
                        "degradation_note": "",
                    }
                    continue

                # 方向一致性
                expected_pos = FACTORS[fname]["expected_direction"] == "positive"
                train_direction = train_ic > 0
                val_direction = val_ic > 0
                direction_consistent = (train_direction == val_direction)

                # 衰减率
                train_abs = abs(train_ic)
                decay_rate = (train_abs - abs(val_ic)) / train_abs if train_abs > 1e-8 else -1.0

                # 判定（基础判定逻辑）
                if not direction_consistent or decay_rate >= 1.0:
                    verdict = "FAIL"
                elif decay_rate > DECAY_THRESHOLD_PASS or (direction_consistent and not val_sig):
                    verdict = "WARN"
                else:
                    verdict = "PASS"

                # § 样本量门限自动降级（引擎级硬逻辑）
                # 当验证期样本量 < 3000 时，统计检验力受限，verdict 自动降一级
                verdict_degraded, degradation_note = apply_verdict_degradation(
                    verdict, val_n, threshold=SAMPLE_SIZE_THRESHOLD,
                )
                sample_size_degraded = (verdict_degraded != verdict)

                decay_results[fname][state_label][period] = {
                    "verdict": verdict_degraded,
                    "verdict_base": verdict,
                    "train_ic": train_ic,
                    "val_ic": val_ic,
                    "decay_rate": decay_rate,
                    "direction_consistent": direction_consistent,
                    "train_significant": train_sig,
                    "val_significant": val_sig,
                    "train_p_value": train_p,
                    "val_p_value": val_p,
                    "n_samples_val": val_n,
                    "sample_size_degraded": sample_size_degraded,
                    "degradation_note": degradation_note,
                }

                deg_mark = " [DEGRADED]" if sample_size_degraded else ""
                print(
                    f"  {fname}/{state_label}/p{period}d: "
                    f"train_IC={train_ic:.4f} → val_IC={val_ic:.4f} "
                    f"(decay={decay_rate:.1%}, dir={'OK' if direction_consistent else 'FLIP'}) "
                    f"→ {verdict_degraded}{deg_mark} (n_val={val_n})"
                )

    return decay_results


# ===================================================================
#  Step 5.5: 因子间相关性预计算（为 Q2 组合信号准备）
# ===================================================================

def compute_factor_correlation(factor_values: dict, all_stocks: dict,
                                window_start: str, window_end: str,
                                state_label: str = "high_vol") -> dict:
    """
    计算 l_vol_rsi_std 与 TrendQuality 在指定状态下的 Spearman 相关性。
    输出跨窗口的相关系数矩阵。
    """
    fnames = list(FACTORS.keys())
    print(f"\n[Step 5.5] 因子间相关性预计算 ({fnames[0]} × {fnames[1]})...")
    print(f"{'─' * 50}")

    results = {}
    for state_label_actual in ["low_vol", "mid_vol", "high_vol"]:
        all_f1 = []
        all_f2 = []
        for code in all_stocks:
            d = all_stocks[code]
            start_idx, end_idx = find_date_range(d["dates"], window_start, window_end)
            f1 = factor_values.get(fnames[0], {}).get(code, np.array([]))
            f2 = factor_values.get(fnames[1], {}).get(code, np.array([]))

            if len(f1) == 0 or len(f2) == 0:
                continue

            # 市场状态过滤
            states = _compute_market_state_simple(d["close"][start_idx:end_idx])

            sel = (states == [{"low_vol": 0, "mid_vol": 1, "high_vol": 2}[state_label_actual]]) \
                  & ~np.isnan(f1[start_idx:end_idx]) & ~np.isnan(f2[start_idx:end_idx])
            if np.sum(sel) < 3:
                continue
            all_f1.extend(f1[start_idx:end_idx][sel].tolist())
            all_f2.extend(f2[start_idx:end_idx][sel].tolist())

        if len(all_f1) >= 3:
            corr = spearman_correlation(np.array(all_f1), np.array(all_f2))
        else:
            corr = None
        results[state_label_actual] = {
            "correlation": corr,
            "n_samples": len(all_f1),
        }
        corr_str = f"{corr:.4f}" if corr is not None else "N/A"
        print(f"  {state_label_actual}: rho={corr_str} (n={len(all_f1)})")

    return results


def _compute_market_state_simple(close: np.ndarray) -> np.ndarray:
    """简化市场状态计算（仅用于因子相关性预计算）"""
    ret = np.diff(close) / close[:-1]
    vol = np.full(len(close), np.nan)
    for i in range(20, len(close)):
        vol[i] = np.std(ret[i - 20:i]) * np.sqrt(252)

    hi_thr = np.nanpercentile(vol, 80)
    lo_thr = np.nanpercentile(vol, 30)

    states = np.full(len(close), 1)  # 默认中波动
    states[vol > hi_thr] = 2        # 高波动
    states[vol < lo_thr] = 0        # 低波动
    return states


# ===================================================================
#  §5.2: FDR BH 校正
# ===================================================================

def apply_fdr_bh(all_results: dict, window_label: str) -> dict:
    """
    Benjamini-Hochberg FDR 校正。
    实现逻辑与 EXP-002 §5.2 一致。
    """
    print(f"\n[Step 5.2] FDR BH 校正 ({window_label})...")
    print(f"{'─' * 50}")

    p_entries = []
    for fname, fstates in all_results.items():
        for state_label, periods in fstates.items():
            for period, result in periods.items():
                p_val = result.get("p_value")
                if p_val is not None:
                    p_entries.append({
                        "p_value": p_val,
                        "factor": fname,
                        "state": state_label,
                        "period": period,
                        "significant_original": result.get("significant", False),
                    })

    if not p_entries:
        return {"fdr_is_significant": False, "corrections": [], "rejected_count": 0, "total": 0}

    m = len(p_entries)
    sorted_entries = sorted(p_entries, key=lambda x: x["p_value"])

    for i, entry in enumerate(sorted_entries):
        rank = i + 1
        q_val = entry["p_value"] * m / rank
        entry["q_value"] = min(q_val, 1.0)
        entry["rejected"] = entry["q_value"] < FDR_Q

    q_values = [e["q_value"] for e in sorted_entries]
    for i in range(len(q_values) - 2, -1, -1):
        q_values[i] = min(q_values[i], q_values[i + 1])
    for i, entry in enumerate(sorted_entries):
        entry["q_value_monotonic"] = q_values[i]
        entry["rejected"] = entry["q_value_monotonic"] < FDR_Q

    rejected_count = sum(1 for e in sorted_entries if e["rejected"])

    print(f"\n  共 {m} 组检验，{rejected_count} 组通过 BH 校正 (q<{FDR_Q})")
    return {
        "fdr_q": FDR_Q,
        "total": m,
        "rejected_count": rejected_count,
        "fdr_is_significant": rejected_count > 0,
        "corrections": sorted_entries,
    }


# ===================================================================
#  §5.3: 三层稳定性检验（验证期）
# ===================================================================

def run_stability_tests(factor_values: dict, all_stocks: dict,
                        market_states: dict, val_start: int, val_end: int) -> dict:
    """
    三层稳定性检验（验证期窗口内）。
    逻辑与 EXP-002 §5.3 保持一致。
    """
    print(f"\n[Step 5.3] 三层稳定性检验（验证期）...")
    print(f"{'─' * 50}")

    stability_results = {}

    for fname in FACTORS:
        stability_results[fname] = {}
        for state_val, state_label in STATE_LABELS.items():
            stability_results[fname][state_label] = {}
            for period in HOLDING_PERIODS:
                print(f"\n  ── {fname}/{state_label}/{period}d ──")

                ic_by_stock = {}
                all_rev_factors = []
                all_fwd_returns = []

                for code in all_stocks:
                    d = all_stocks[code]
                    if d is None:
                        continue
                    fac = factor_values[fname].get(code, np.array([]))
                    if len(fac) == 0:
                        continue
                    states = market_states.get(code, np.array([]))
                    if len(states) == 0:
                        continue

                    fwd_ret = np.full(len(d["close"]), np.nan)
                    for i in range(len(d["close"]) - period):
                        fwd_ret[i] = d["close"][i + period] / d["close"][i] - 1

                    reversed_fac = reverse_factor(fac)
                    sel = (states == state_val) & ~np.isnan(reversed_fac) & ~np.isnan(fwd_ret)
                    sel = sel & (np.arange(len(d["dates"])) >= val_start) & (np.arange(len(d["dates"])) < val_end)

                    if np.sum(sel) < 3:
                        ic_by_stock[code] = np.array([])
                        continue

                    ic_by_stock[code] = reversed_fac[sel]
                    all_rev_factors.extend(reversed_fac[sel].tolist())
                    all_fwd_returns.extend(fwd_ret[sel].tolist())

                n_total = len(all_rev_factors)
                if n_total < 3:
                    print(f"    数据不足，跳过稳定性检验")
                    stability_results[fname][state_label][period] = {
                        "L3_passed": False, "details": "insufficient_data",
                    }
                    continue

                arr_rev = np.array(all_rev_factors)
                arr_fwd = np.array(all_fwd_returns)
                overall_ic = spearman_correlation(arr_rev, arr_fwd)
                print(f"    总体 IC = {overall_ic:.4f} (n={n_total})")

                # 检验 1: 时间切片
                ts_passed, ts_means = check_time_slice_stability(
                    arr_rev, n_slices=STABILITY_N_SLICES,
                )
                print(f"    [{'PASS' if ts_passed else 'FAIL'}] 时间切片")

                # 检验 2: 滚动窗口
                roll_passed, flip_rate = check_rolling_stability(
                    arr_rev, max_flip_rate=STABILITY_MAX_FLIP_RATE,
                )
                print(f"    [{'PASS' if roll_passed else 'FAIL'}] 滚动窗口 ({flip_rate:.2%})")

                # 检验 3: 标的交叉
                cross_passed, stock_means = check_cross_sectional_stability(
                    ic_by_stock,
                    min_agree=len(all_stocks) // 2 + 1,
                    n_stocks=len(all_stocks),
                )
                print(f"    [{'PASS' if cross_passed else 'FAIL'}] 标的交叉")

                # 检验 4: OOS（内部 IS/OOS 分割）
                split_point = n_total // 2
                is_ic = spearman_correlation(arr_rev[:split_point], arr_fwd[:split_point]) if split_point >= 3 else 0
                oos_ic = spearman_correlation(arr_rev[split_point:], arr_fwd[split_point:]) if (n_total - split_point) >= 3 else 0
                oos_passed = check_oos_stability(is_ic, oos_ic)
                print(f"    [{'PASS' if oos_passed else 'FAIL'}] OOS (IS={is_ic:.4f}, OOS={oos_ic:.4f})")

                checks_passed = sum([ts_passed, roll_passed, cross_passed, oos_passed])
                l3_passed = checks_passed >= STABILITY_L3_REQUIRED
                print(f"    L3: {checks_passed}/4 → {'PASS' if l3_passed else 'FAIL'}")

                stability_results[fname][state_label][period] = {
                    "overall_ic": overall_ic,
                    "time_slice": {"passed": ts_passed, "means": ts_means.tolist() if hasattr(ts_means, 'tolist') else list(ts_means)},
                    "rolling": {"passed": roll_passed, "flip_rate": flip_rate},
                    "cross_sectional": {"passed": cross_passed, "stock_means": stock_means},
                    "oos": {"passed": oos_passed, "is_ic": is_ic, "oos_ic": oos_ic},
                    "checks_passed": checks_passed,
                    "checks_total": 4,
                    "L3_passed": l3_passed,
                }

    # 全局汇总
    total_l3 = 0
    total_combos = 0
    for fname, fstates in stability_results.items():
        for s_label, periods in fstates.items():
            for period, result in periods.items():
                if isinstance(result, dict) and result.get("L3_passed", False):
                    total_l3 += 1
                total_combos += 1
    stability_results["_summary"] = {
        "total_combinations": total_combos,
        "L3_passed_count": total_l3,
        "L3_pass_rate": total_l3 / total_combos if total_combos > 0 else 0,
    }
    return stability_results


# ===================================================================
#  核心计算：单窗口 IC + Bootstrap
# ===================================================================

def compute_window_results(factor_values: dict, all_stocks: dict,
                            market_states: dict,
                            window_start: int, window_end: int,
                            window_label: str,
                            precomputed_fwd_returns: dict = None) -> dict:
    """
    对指定窗口计算各因子 × 各状态 × 各持有期的 IC 及 Bootstrap 检验结果。

    Parameters
    ----------
    precomputed_fwd_returns : dict, optional
        预计算的前向收益缓存 {code: {period: np.ndarray}}
        若未提供，回退到实时计算（兼容旧调用）
    """
    print(f"\n[Step 4 & 5] IC 计算及 Bootstrap 检验 ({window_label})...")
    print(f"{'─' * 50}")

    all_results = {}

    for fname in FACTORS:
        all_results[fname] = {}
        for state_val, state_label in STATE_LABELS.items():
            all_results[fname][state_label] = {}
            for period in HOLDING_PERIODS:
                all_factors = []
                all_returns = []

                for code in all_stocks:
                    d = all_stocks[code]
                    if d is None:
                        continue
                    fac = factor_values[fname].get(code, np.array([]))
                    if len(fac) == 0:
                        continue
                    states = market_states.get(code, np.array([]))
                    if len(states) != len(d["dates"]):
                        continue

                    # 窗口内掩码
                    in_window = (np.arange(len(d["dates"])) >= window_start) & \
                                (np.arange(len(d["dates"])) < window_end)

                    # 前向收益（优先使用缓存，回退实时计算）
                    if precomputed_fwd_returns is not None and \
                       code in precomputed_fwd_returns and \
                       period in precomputed_fwd_returns[code]:
                        fwd_ret = precomputed_fwd_returns[code][period]
                    else:
                        fwd_ret = compute_forward_returns(d["close"], period)
                    reversed_fac = reverse_factor(fac)

                    sel = in_window & (states == state_val) & \
                          ~np.isnan(reversed_fac) & ~np.isnan(fwd_ret)

                    if np.sum(sel) < 3:
                        continue
                    all_factors.extend(reversed_fac[sel].tolist())
                    all_returns.extend(fwd_ret[sel].tolist())

                if len(all_factors) < 3:
                    all_results[fname][state_label][period] = {
                        "ic_mean": None, "p_value": None,
                        "significant": False, "n_samples": 0,
                    }
                    continue

                result = bootstrap_ic_test(
                    np.array(all_factors), np.array(all_returns),
                    n_bootstrap=10000, alpha=0.05,
                    random_seed=RANDOM_SEED,
                )
                result["n_samples"] = len(all_factors)
                all_results[fname][state_label][period] = result

                sig_mark = "[SIG]" if result["significant"] else "[NS]"
                print(f"  {fname}/{state_label}/p{period}d: "
                      f"IC={result['ic_mean']:.4f}, "
                      f"p={result['p_value']:.4f} {sig_mark} "
                      f"(n={len(all_factors)})")

    return all_results


# ===================================================================
#  主函数
# ===================================================================

def main(dry_run: bool = False, skip_qc: bool = False):
    # 计时开始
    t0_total = time.time()

    print(f"EXP-2026-003-KNOWDEEP Q1: 跨窗口鲁棒性验证")
    print(f"{'=' * 50}")
    print(f"dry_run={dry_run}, skip_qc={skip_qc}")
    os.makedirs(REPORT_DIR, exist_ok=True)

    version_tag = get_version_tag()
    run_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # ── Step 0: 读取标的列表 ──
    print(f"\n[Step 0] 读取标的列表...")
    stock_codes = load_stock_codes()
    print(f"  从 market_data.db 读取到 {len(stock_codes)} 只标的")
    for code in stock_codes:
        print(f"    {code}")

    if dry_run:
        print(f"\n[Dry-Run] 版本标记: {version_tag}")
        print(f"[Dry-Run] 运行时间: {run_timestamp}")
        print(f"\n[Dry-Run] 架构验证通过，核心函数就绪:")
        for fname in FACTORS:
            print(f"  [OK] {fname}")
        print("  [OK] classify_market_state")
        print("  [OK] bootstrap_ic_test")
        print("  [OK] spearman_correlation")
        print("  [OK] reverse_factor")
        print("  [OK] run_stability_tests")
        print("  [OK] apply_fdr_bh")
        print("  [OK] compute_decay_analysis")
        print("  [OK] compute_factor_correlation")
        print("\n  参数配置:")
        print(f"    标的数: {len(stock_codes)}")
        print(f"    训练期: {TRAIN_START} ~ {TRAIN_END}")
        print(f"    验证期: {VAL_START} ~ {VAL_END}")
        print(f"    持有期: {HOLDING_PERIODS} (主验证: {PRIMARY_HOLDING}d)")
        print(f"    交易成本: commission={COMMISSION_RATE}, stamp_tax={STAMP_TAX_RATE}, slippage={SLIPPAGE}")
        print(f"    单次完整成本: {COST_ROUND_TRIP:.4%}")
        print("\n  (通过 dry_run 参数避免实际执行回测)")
        return

    # ── §2.3: 数据质量前置检查 ──
    if not skip_qc:
        qc_passed = step_qc_preamble(stock_codes)
        if not qc_passed:
            failed_info = {
                "status": "FAILED",
                "task_id": "EXP-2026-003-KNOWDEEP-Q1",
                "step": "qc",
                "error": "数据质量前置检查未通过",
                "version_tag": version_tag,
                "run_timestamp": run_timestamp,
            }
            with open(os.path.join(REPORT_DIR, "qc_failed.json"), "w", encoding="utf-8") as f:
                json.dump(failed_info, f, ensure_ascii=False, indent=2)
            print(f"\n  [FAIL] 流水线因数据质量检查未通过而终止。")
            return
    else:
        print(f"\n[Skipped] 数据质量前置检查 (§2.3) — skip_qc=True")

    # ── Step 1: 加载数据 ──
    all_stocks = {}
    print(f"\n[Step 1] 加载数据...")
    for code in stock_codes:
        data = load_stock_data(code)
        if data is None:
            print(f"  [WARN] {code}: 无数据")
            continue
        all_stocks[code] = data
        print(f"  {code}: {len(data['dates'])} 交易日, [{data['dates'][0]} ~ {data['dates'][-1]}]")

    valid_codes = list(all_stocks.keys())

    # ── Step 2: 因子计算 ──
    factor_values = {}
    print(f"\n[Step 2] 计算两因子...")
    for fname, fcfg in FACTORS.items():
        factor_values[fname] = {}
        for code in valid_codes:
            d = all_stocks[code]
            factor_values[fname][code] = fcfg["func"](
                *[d[f] for f in fcfg["fields"]],
                **fcfg["params"],
            )
        print(f"  [OK] {fname}")

    # ── Step 3: 市场状态分类 ──
    market_states = {}
    warmup_vol_by_stock = {}
    print(f"\n[Step 3] 市场状态分类...")
    for code in valid_codes:
        d = all_stocks[code]
        warmup_start, _ = find_date_range(d["dates"], TRAIN_START, TRAIN_END)
        wu_returns = np.diff(d["close"][:warmup_start + 200]) / d["close"][:warmup_start + 199]
        warmup_vol = np.full(len(d["close"]), np.nan)
        for i in range(20, min(len(wu_returns), warmup_start + 200)):
            warmup_vol[i] = np.std(wu_returns[i - 20 + 1:i + 1]) * np.sqrt(252)
        warmup_vol_by_stock[code] = warmup_vol

        states, hi_thr, lo_thr = classify_market_state(d["close"], warmup_vol=warmup_vol)
        market_states[code] = states

    # ── 前向收益预计算缓存 ──
    print(f"\n[Cache] 预计算前向收益缓存...")
    t0_cache = time.time()
    forward_returns_cache = {}
    for code in valid_codes:
        d = all_stocks[code]
        forward_returns_cache[code] = {}
        for period in HOLDING_PERIODS:
            forward_returns_cache[code][period] = compute_forward_returns(d["close"], period)
    elapsed_cache = time.time() - t0_cache
    print(f"  [TIMING] 前向收益缓存构建: {elapsed_cache:.2f}s")

    # ── Step 4 & 5: 双窗口 Bootstrap 检验 ──
    train_start_idx = 0  # 数据起点即训练起点
    _, train_end_idx = find_date_range(all_stocks[valid_codes[0]]["dates"], TRAIN_START, TRAIN_END)
    val_start_idx, _ = find_date_range(all_stocks[valid_codes[0]]["dates"], VAL_START, VAL_END)
    _, val_end_idx = find_date_range(all_stocks[valid_codes[0]]["dates"], VAL_START, VAL_END)

    train_results = compute_window_results(
        factor_values, all_stocks, market_states,
        train_start_idx, train_end_idx, "训练期",
        precomputed_fwd_returns=forward_returns_cache,
    )
    # 中间保存：训练窗口完成后立即落盘（防止超时丢失）
    train_interim_path = os.path.join(REPORT_DIR, "q1_train_results_intermediate.json")
    with open(train_interim_path, "w", encoding="utf-8") as f:
        json.dump(train_results, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"  [OK] 训练窗口中间结果已保存到 {train_interim_path}")

    val_results = compute_window_results(
        factor_values, all_stocks, market_states,
        val_start_idx, val_end_idx, "验证期",
        precomputed_fwd_returns=forward_returns_cache,
    )

    # ── §5.2: FDR BH 校正（双窗口独立） ──
    fdr_train = apply_fdr_bh(train_results, "训练期")
    fdr_val = apply_fdr_bh(val_results, "验证期")

    # ── §5.3: 三层稳定性检验（验证期） ──
    stability_result = run_stability_tests(
        factor_values, all_stocks, market_states,
        val_start_idx, val_end_idx,
    )

    # ── Step 5.4: 跨窗口衰减分析 ──
    decay_results = compute_decay_analysis(train_results, val_results)

    # ── Step 5.5: 因子间相关性预计算 ──
    factor_corr_train = compute_factor_correlation(
        factor_values, all_stocks, TRAIN_START, TRAIN_END
    )
    factor_corr_val = compute_factor_correlation(
        factor_values, all_stocks, VAL_START, VAL_END
    )

    # ── Step 6: 生成输出报告 ──
    print(f"\n[Step 6] 生成输出报告...")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

    output = {
        "task_id": "EXP-2026-003-KNOWDEEP",
        "work_package": "Q1",
        "version_tag": version_tag,
        "run_timestamp": run_timestamp,
        "completed_time": timestamp,
        "status": "READY",
        "config": {
            "stocks": valid_codes,
            "n_stocks": len(valid_codes),
            "train_window": f"{TRAIN_START}~{TRAIN_END}",
            "val_window": f"{VAL_START}~{VAL_END}",
            "holding_periods": HOLDING_PERIODS,
            "primary_holding": PRIMARY_HOLDING,
            "commission_rate": COMMISSION_RATE,
            "stamp_tax_rate": STAMP_TAX_RATE,
            "slippage": SLIPPAGE,
            "cost_per_trade": COST_PER_TRADE,
            "cost_per_sell": COST_PER_SELL,
            "cost_round_trip": COST_ROUND_TRIP,
        },
        "factors": list(FACTORS.keys()),
        "train_results": train_results,
        "val_results": val_results,
        "fdr_train": fdr_train,
        "fdr_val": fdr_val,
        "stability_val": stability_result,
        "decay_analysis": decay_results,
        "factor_correlation": {
            "train": factor_corr_train,
            "val": factor_corr_val,
        },
    }

    result_path = os.path.join(REPORT_DIR, "q1_results.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"  [OK] {result_path}")

    # 清理中间文件
    train_interim_path = os.path.join(REPORT_DIR, "q1_train_results_intermediate.json")
    if os.path.exists(train_interim_path):
        os.remove(train_interim_path)

    # 独立输出：衰减分析报告
    decay_path = os.path.join(REPORT_DIR, "decay_analysis.json")
    with open(decay_path, "w", encoding="utf-8") as f:
        json.dump(decay_results, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"  [OK] {decay_path}")

    # ── 超时自检（使用 self_check 模块自动化校验） ──
    elapsed_total = time.time() - t0_total
    timeout_result = check_timeout(
        elapsed_seconds=elapsed_total,
        threshold_seconds=TIMEOUT_THRESHOLD_SECONDS,
    )
    print(f"\n[自检] 超时检查: {timeout_result['note']}")
    print(f"  elapsed={timeout_result['elapsed_formatted']}, "
          f"threshold={timeout_result['threshold_formatted']}")

    # 将超时结果写入文件（供报告生成使用）
    timeout_path = os.path.join(REPORT_DIR, "timeout_check.json")
    with open(timeout_path, "w", encoding="utf-8") as f:
        json.dump(timeout_result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"  [OK] {timeout_path}")

    # 将超时信息附加到 q1_results.json
    result_path = os.path.join(REPORT_DIR, "q1_results.json")
    if os.path.exists(result_path):
        with open(result_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing["self_check_timeout"] = timeout_result
        existing["elapsed_total_seconds"] = round(elapsed_total, 1)
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
        print(f"  [OK] 超时信息已附加到 {result_path}")

    print(f"\n{'=' * 50}")
    print(f"EXP-003 Q1 回测完成。总耗时: {timeout_result['elapsed_formatted']}")


# ===================================================================
#  入口
# ===================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EXP-2026-003-KNOWDEEP Q1 回测主脚本")
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry-run 模式：仅验证架构，不执行回测")
    parser.add_argument("--skip-qc", action="store_true",
                        help="跳过 §2.3 数据质量前置检查")
    args = parser.parse_args()
    main(dry_run=args.dry_run, skip_qc=args.skip_qc)
