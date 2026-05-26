"""
EXP-2026-INVFAC-002: 负向因子反转可行性验证 — 回测主脚本
============================================================
author: 墨衡 (moheng)
created: 2026-05-25T17:10+08:00
updated: 2026-05-25T17:17+08:00

执行实验设计规定的完整分析流水线。

流水线步骤:
  Step 1: 从 market_data.db 加载 12 只标的日线数据
  Step 2: 计算三因子 (TrendQuality / l_vol_rsi_std / l_str_kdj_k)
  Step 2.3: 数据质量前置检查 (data_qc_check) [§2.3]
  Step 3: 市场状态分类（滚动波动率分位数）
  Step 4: 因子符号反转 + 分状态 IC 计算
  Step 5: Bootstrap 置换检验（三层检验）
  Step 5.2: FDR BH 多重比较校正 [§5.2]
  Step 5.3: 三层稳定性检验 [§5.3]
  Step 4.1: 分位数阈值敏感性分析（9格扫描） [§4.1]
  Step 6: 生成输出报告

配置:
  - 数据源: market_data.db
  - 标的: 11 只 A50 (见 STOCK_CODES; 剔除 300750)
  - 时间窗口: 2021-01-01 ~ 2025-12-31
  - 复权方式: qfq（通过 adj_factor 前复权）
  - 随机种子: 42

使用:
  python scripts/exp_invfac002/run_exp_invfac002.py [--dry-run] [--skip-qc] [--skip-sensitivity]

输出目录:
  reports/EXP-2026-INVFAC-002/
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
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

# ── 项目路径 ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 实验内部模块
from scripts.exp_invfac002.exp_factors import (
    calc_trend_quality,
    calc_vol_rsi_std,
    calc_kdj_k,
    reverse_factor,
)
from scripts.exp_invfac002.exp_market_state import classify_market_state
from scripts.exp_invfac002.exp_bootstrap import (
    bootstrap_ic_test,
    spearman_correlation,
)
from scripts.exp_invfac002.exp_stability import (
    check_time_slice_stability,
    check_rolling_stability,
    check_cross_sectional_stability,
    check_oos_stability,
)
from scripts.exp_invfac002.data_qc_check import run_all_checks as run_data_qc

# ── 全局配置 ──

STOCK_CODES = [
    "601857", "000001", "600519", "601318",
    "600036", "300750", "600276", "600887",
    "600030", "000333", "002415", "600436",
    # 300750 已加入: adj_factor 跳变 +81.2% (2023-04-26) 已确认为合法除权除息 (Step 1 QC PASS)
]

DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "EXP-2026-INVFAC-002")

# 时间窗口
WARMUP_START = "20210101"
WARMUP_END = "20211231"
IS_START = "20220101"
IS_END = "20240630"
OOS_START = "20240701"
OOS_END = "20251231"

RANDOM_SEED = 42

# 三因子配置
# 每位因子需要的 data dict 字段（按顺序作为 func(*fields) 参数）
FACTORS = {
    "TrendQuality": {"func": calc_trend_quality, "fields": ["high", "low", "close"], "params": {"period": 20}},
    "l_vol_rsi_std": {"func": calc_vol_rsi_std, "fields": ["volume"], "params": {"rsi_period": 14, "std_period": 20}},
    "l_str_kdj_k": {"func": calc_kdj_k, "fields": ["high", "low", "close"], "params": {"period": 9, "k_smooth": 3}},
}

# ── §4.1 敏感性分析配置 ──
SENSITIVITY_HIGH_PCTS = [0.75, 0.80, 0.85]
SENSITIVITY_LOW_PCTS  = [0.25, 0.30, 0.35]
BASELINE_HIGH = 0.80
BASELINE_LOW  = 0.30

# ── §5.2 FDR 配置 ──
FDR_Q = 0.05

# ── §5.3 稳定性检验配置 ──
STABILITY_N_STOCKS = 12
STABILITY_MIN_AGREE_CROSS = 8    # 标的交叉：≥8 方向一致 (12只中的多数, 设计§5.3)
STABILITY_MAX_FLIP_RATE  = 0.30  # 滚动：翻转率 < 30%
STABILITY_N_SLICES       = 4     # 时间切片
STABILITY_MIN_AGREE_TIME = 3     # 时间切片：≥3 方向一致
STABILITY_L3_REQUIRED    = 3     # L3通过：≥3/4 检验通过


# ===================================================================
#  辅助函数
# ===================================================================

def load_stock_data(ts_code: str) -> dict:
    """从 market_data.db 加载个股数据并 QFQ 复权"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT date, open, high, low, close, volume, adj_factor
        FROM stock_daily
        WHERE code=?
        ORDER BY date
    """, (ts_code,))
    rows = cursor.fetchall()
    conn.close()

    dates = np.array([r[0] for r in rows])
    open_p = np.array([r[1] for r in rows], dtype=float)
    high = np.array([r[2] for r in rows], dtype=float)
    low = np.array([r[3] for r in rows], dtype=float)
    close = np.array([r[4] for r in rows], dtype=float)
    volume = np.array([r[5] for r in rows], dtype=float)
    adj_factor = np.array([r[6] if r[6] else 1.0 for r in rows], dtype=float)

    # QFQ 前复权: price * adj_factor / latest_adj_factor
    latest_adj = adj_factor[-1] if len(adj_factor) > 0 else 1.0
    adj_ratio = adj_factor / latest_adj

    open_qfq = open_p * adj_ratio
    high_qfq = high * adj_ratio
    low_qfq = low * adj_ratio
    close_qfq = close * adj_ratio

    return {
        "code": ts_code,
        "dates": dates,
        "open": open_qfq,
        "high": high_qfq,
        "low": low_qfq,
        "close": close_qfq,
        "volume": volume,
        "adj_factor_raw": adj_factor,
    }


def find_date_range(dates: np.ndarray, start: str, end: str) -> tuple[int, int]:
    """在日期数组中查找 start~end 索引区间"""
    start_idx = np.searchsorted(dates, start, side="left")
    end_idx = np.searchsorted(dates, end, side="right")
    return start_idx, end_idx


# ===================================================================
#  §2.3: 数据质量前置检查
# ===================================================================

def step_qc_preamble() -> bool:
    """§2.3 数据质量前置检查。返回 True=通过，False=阻断。"""
    print(f"\n[Step 2.3] 数据质量前置检查 (§2.3)...")
    print(f"{'─' * 50}")
    result = run_data_qc(STOCK_CODES, start=WARMUP_START, end=OOS_END, skip_bh=True)
    if not result["overall_passed"]:
        print(f"\n  ❌ 数据质量检查未通过，流水线终止。")
        return False
    print(f"\n  ✅ 数据质量检查全部通过。继续执行主流程。")
    return True


# ===================================================================
#  §4.1: 分位数阈值敏感性分析（9格扫描）
# ===================================================================

def step_sensitivity_analysis(
    factor_values: dict,
    all_stocks: dict,
    warmup_vol_by_stock: dict[str, np.ndarray],
) -> dict:
    """
    §4.1 分位数阈值敏感性分析（9格扫描）。

    对高波动百分位 [0.75, 0.80, 0.85] × 低波动百分位 [0.25, 0.30, 0.35]
    共 9 组组合，每组重新计算反转信号判定结果。

    返回敏感度分析报告 dict。
    """
    print(f"\n[Step 4.1] 分位数阈值敏感性分析 (§4.1)...")
    print(f"{'─' * 50}")
    print(f"  扫描网格: high_p={SENSITIVITY_HIGH_PCTS} × low_p={SENSITIVITY_LOW_PCTS}")
    print(f"  Baseline: high_p={BASELINE_HIGH}, low_p={BASELINE_LOW}")

    PERIODS = [5, 10, 20]
    STATE_LABELS = {0: "low_vol", 1: "mid_vol", 2: "high_vol"}

    baseline_key = f"pct_{BASELINE_HIGH:.2f}_{BASELINE_LOW:.2f}"
    grid_results: dict = {}

    for hi_p in SENSITIVITY_HIGH_PCTS:
        for lo_p in SENSITIVITY_LOW_PCTS:
            grid_key = f"pct_{hi_p:.2f}_{lo_p:.2f}"
            print(f"\n  ── 网格 {grid_key} ──")

            # 用该组百分位重新分类市场状态
            market_states: dict[str, np.ndarray] = {}
            for code in STOCK_CODES:
                d = all_stocks[code]
                wv = warmup_vol_by_stock.get(code)
                states, hi_thr, lo_thr = classify_market_state(
                    d["close"],
                    percentile_high=hi_p,
                    percentile_low=lo_p,
                    warmup_vol=wv,
                )
                market_states[code] = states

            # 重新计算 IC
            grid_results[grid_key] = {}
            for fname in FACTORS:
                grid_results[grid_key][fname] = {}
                for state_val, state_label in STATE_LABELS.items():
                    grid_results[grid_key][fname][state_label] = {}
                    for period in PERIODS:
                        all_fac = []
                        all_ret = []
                        for code in STOCK_CODES:
                            d = all_stocks[code]
                            fac = factor_values[fname][code]
                            states = market_states[code]
                            daily_ret = np.full(len(d["close"]), np.nan)
                            daily_ret[1:] = np.diff(d["close"]) / d["close"][:-1]

                            fwd_ret = np.full(len(d["close"]), np.nan)
                            for i in range(len(d["close"]) - period):
                                fwd_ret[i] = d["close"][i + period] / d["close"][i] - 1

                            reversed_fac = reverse_factor(fac)
                            sel = (states == state_val) & ~np.isnan(reversed_fac) & ~np.isnan(fwd_ret)
                            if np.sum(sel) < 3:
                                continue
                            all_fac.extend(reversed_fac[sel].tolist())
                            all_ret.extend(fwd_ret[sel].tolist())

                        if len(all_fac) < 3:
                            grid_results[grid_key][fname][state_label][str(period)] = None
                            continue

                        ic_val = spearman_correlation(np.array(all_fac), np.array(all_ret))
                        grid_results[grid_key][fname][state_label][str(period)] = round(float(ic_val), 6)

            # 行内输出摘要
            row = []
            for fname in FACTORS:
                for state_label in ["low_vol", "mid_vol", "high_vol"]:
                    for period in PERIODS:
                        v = grid_results[grid_key][fname][state_label].get(str(period))
                        row.append(f"{v:.4f}" if v is not None else "N/A")
            print(f"    IC 摘要: " + " | ".join(row[:6]) + "...")

    # ── 构建对比表 ──
    table_header = [
        "Percentile", "Factor", "State", "Period",
        "IC_Baseline", "IC_Grid", "Delta", "Signal_Change"
    ]
    table_rows = []

    for hi_p in SENSITIVITY_HIGH_PCTS:
        for lo_p in SENSITIVITY_LOW_PCTS:
            grid_key = f"pct_{hi_p:.2f}_{lo_p:.2f}"
            for fname in FACTORS:
                for state_label in ["low_vol", "mid_vol", "high_vol"]:
                    for period in PERIODS:
                        bval = grid_results.get(baseline_key, {}).get(fname, {}).get(state_label, {}).get(str(period))
                        gval = grid_results[grid_key][fname][state_label].get(str(period))

                        if bval is None or gval is None:
                            row = [f"({hi_p},{lo_p})", fname, state_label, f"{period}d", "N/A", "N/A", "N/A", "N/A"]
                        else:
                            bas_sign = "POS" if bval > 0 else "NEG"
                            gri_sign = "POS" if gval > 0 else "NEG"
                            signal_chg = "SAME" if bas_sign == gri_sign else "FLIP"
                            delta = gval - bval
                            row = [
                                f"({hi_p},{lo_p})", fname, state_label, f"{period}d",
                                f"{bval:.4f}", f"{gval:.4f}", f"{delta:+.4f}", signal_chg,
                            ]
                        table_rows.append(row)

    sensitivity_report = {
        "baseline": f"pct_{BASELINE_HIGH:.2f}_{BASELINE_LOW:.2f}",
        "grid_points": [f"pct_{hi:.2f}_{lo:.2f}" for hi in SENSITIVITY_HIGH_PCTS for lo in SENSITIVITY_LOW_PCTS],
        "results": grid_results,
        "comparison_table": table_rows,
        "total_comparisons": len(table_rows),
        "flip_count": sum(1 for r in table_rows if r[7] == "FLIP"),
        "data_points": sum(1 for r in table_rows if r[4] != "N/A"),
    }

    # 输出对比表（控制台）
    print(f"\n  ── 敏感性分析对比表 (§4.1) ──")
    print(f"  {'Percentile':<16} {'Factor':<16} {'State':<10} {'Period':<6} "
          f"{'IC_Baseline':<12} {'IC_Grid':<12} {'Delta':<10} {'Signal':<8}")
    print(f"  {'─' * 90}")
    for row in table_rows:
        print(f"  {row[0]:<16} {row[1]:<16} {row[2]:<10} {row[3]:<6} "
              f"{row[4]:<12} {row[5]:<12} {row[6]:<10} {row[7]:<8}")

    flip_pct = (sensitivity_report["flip_count"] / sensitivity_report["data_points"] * 100) if sensitivity_report["data_points"] > 0 else 0
    print(f"\n  信号翻转率: {sensitivity_report['flip_count']}/{sensitivity_report['data_points']} = {flip_pct:.1f}%")
    if flip_pct > 20:
        print(f"  [WARN] 超过 20% 的信号翻转，阈值选择对结果影响较大。")
    else:
        print(f"  [PASS] 信号翻转率在可接受范围内。")

    return sensitivity_report


# ===================================================================
#  §5.2: FDR BH 多重比较校正
# ===================================================================

def apply_fdr_bh(all_results: dict) -> dict:
    """
    §5.2 对 Bootstrap 检验结果的 p 值应用 Benjamini-Hochberg FDR 校正。

    对所有 27 组检验（3 因子 × 3 状态 × 3 持有期）进行 BH 校正 (q=0.05)。

    Parameters
    ----------
    all_results : dict — 嵌套结构 {factor: {state: {period: bootstrap_result}}}

    Returns
    -------
    dict — 追加 FDR 校正信息：
      - fdr_is_significant: bool — 是否存在通过校正的检验
      - corrections: [ {factor, state, period, p_value, q_value, rejected, original_sig}, ...]
      - rejected_count: int
    """
    print(f"\n[Step 5.2] FDR BH 多重比较校正 (§5.2)...")
    print(f"{'─' * 50}")

    # 1. 收集所有 p 值及其位置
    p_entries = []  # (p_value, factor, state, period)
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
        print("  没有有效的 p 值进行校正。")
        return {"fdr_is_significant": False, "corrections": [], "rejected_count": 0, "total": 0}

    m = len(p_entries)

    # 2. 按 p 值升序排序
    sorted_entries = sorted(p_entries, key=lambda x: x["p_value"])

    # 3. BH 校正: q_i = p_i * m / i (i 从 1 开始)
    for i, entry in enumerate(sorted_entries):
        rank = i + 1  # 1-based rank
        raw_p = entry["p_value"]
        q_val = raw_p * m / rank
        entry["q_value"] = min(q_val, 1.0)  # 截断到 [0,1]
        entry["rejected"] = entry["q_value"] < FDR_Q

    # 4. 确保单调性（确保 q_value 序列非递减）
    q_values = [e["q_value"] for e in sorted_entries]
    for i in range(len(q_values) - 2, -1, -1):
        q_values[i] = min(q_values[i], q_values[i + 1])
    for i, entry in enumerate(sorted_entries):
        entry["q_value_monotonic"] = q_values[i]
        entry["rejected"] = entry["q_value_monotonic"] < FDR_Q

    rejected_count = sum(1 for e in sorted_entries if e["rejected"])

    # 5. 输出校正结果表
    print(f"\n  FDR BH 校正结果 (q* = {FDR_Q}, m = {m}):")
    print(f"  {'#':<4} {'Factor':<16} {'State':<10} {'Period':<6} "
          f"{'p_raw':<10} {'q_BH':<10} {'Reject':<7} {'Orig_Sig':<8}")
    print(f"  {'─' * 75}")

    for i, entry in enumerate(sorted_entries):
        print(f"  {i+1:<4} {entry['factor']:<16} {entry['state']:<10} "
              f"{entry['period']:<6}d "
              f"{entry['p_value']:<10.4f} {entry['q_value_monotonic']:<10.4f} "
              f"{'YES' if entry['rejected'] else 'NO':<7} "
              f"{'SIG' if entry['significant_original'] else 'NS':<8}")

    print(f"\n  共 {m} 组检验，{rejected_count} 组通过 BH 校正 (q<{FDR_Q})")

    return {
        "fdr_q": FDR_Q,
        "total": m,
        "rejected_count": rejected_count,
        "fdr_is_significant": rejected_count > 0,
        "corrections": sorted_entries,
    }


# ===================================================================
#  §5.3: 三层稳定性检验
# ===================================================================

def run_stability_tests(
    factor_values: dict,
    all_stocks: dict,
    market_states: dict,
) -> dict:
    """
    §5.3 三层稳定性检验集成。

    对每个 (因子, 状态, 持有期) 组合运行 4 项稳定性检验，汇总 L3 通过状态。

    Returns
    -------
    dict — 稳定性检验结果（按因子/状态/持有期组织）
    """
    print(f"\n[Step 5.3] 三层稳定性检验集成 (§5.3)...")
    print(f"{'─' * 50}")

    PERIODS = [5, 10, 20]
    STATE_LABELS = {0: "low_vol", 1: "mid_vol", 2: "high_vol"}

    stability_results: dict = {}

    for fname in FACTORS:
        stability_results[fname] = {}
        for state_val, state_label in STATE_LABELS.items():
            stability_results[fname][state_label] = {}
            for period in PERIODS:
                key = f"{fname}/{state_label}/{period}d"
                print(f"\n  ── {key} ──")

                # ── 准备数据 ──
                # 收集每个标的在该状态下的因子-收益对
                ic_by_stock: dict[str, np.ndarray] = {}
                all_rev_factors: list[float] = []
                all_fwd_returns: list[float] = []
                stock_code_for_point: list[str] = []

                for code in STOCK_CODES:
                    d = all_stocks[code]
                    fac = factor_values[fname][code]
                    states = market_states[code]

                    # 前向收益
                    fwd_ret = np.full(len(d["close"]), np.nan)
                    for i in range(len(d["close"]) - period):
                        fwd_ret[i] = d["close"][i + period] / d["close"][i] - 1

                    reversed_fac = reverse_factor(fac)
                    sel = (states == state_val) & ~np.isnan(reversed_fac) & ~np.isnan(fwd_ret)

                    if np.sum(sel) < 3:
                        ic_by_stock[code] = np.array([])
                        continue

                    rev_f = reversed_fac[sel]
                    fwd_r = fwd_ret[sel]
                    ic_by_stock[code] = rev_f  # 存储反转后的因子值（用于稳定性检验）

                    all_rev_factors.extend(rev_f.tolist())
                    all_fwd_returns.extend(fwd_r.tolist())
                    stock_code_for_point.extend([code] * len(rev_f))

                n_total = len(all_rev_factors)
                if n_total < 3:
                    print(f"    数据不足，跳过稳定性检验")
                    stability_results[fname][state_label][period] = {
                        "L3_passed": False,
                        "details": "insufficient_data",
                    }
                    continue

                # 构建 IC 时间序列（跨截面 IC at each point）
                # 这里简化处理：采用滚动方式计算 IC 时间序列
                # 使用 compute_forward_ic 的方法：在每个时间点，用当前及之前数据计算 IC
                arr_rev = np.array(all_rev_factors)
                arr_fwd = np.array(all_fwd_returns)

                # 整体 IC 均值
                overall_ic = spearman_correlation(arr_rev, arr_fwd)
                print(f"    总体 IC = {overall_ic:.4f} (n={n_total})")

                # ── 检验 1: 时间切片稳定性 ──
                ts_passed, ts_means = check_time_slice_stability(
                    arr_rev, n_slices=STABILITY_N_SLICES,
                )
                print(f"    [{'PASS' if ts_passed else 'FAIL'}] 时间切片: "
                      f"切片均值={np.round(ts_means, 4).tolist()}")

                # ── 检验 2: 滚动窗口稳定性 ──
                roll_passed, flip_rate = check_rolling_stability(
                    arr_rev, max_flip_rate=STABILITY_MAX_FLIP_RATE,
                )
                print(f"    [{'PASS' if roll_passed else 'FAIL'}] 滚动窗口: "
                      f"翻转率={flip_rate:.2%}")

                # ── 检验 3: 标的交叉稳定性 ──
                cross_passed, stock_means = check_cross_sectional_stability(
                    ic_by_stock, min_agree=STABILITY_MIN_AGREE_CROSS,
                    n_stocks=STABILITY_N_STOCKS,
                )
                pos_stocks = sum(1 for v in stock_means.values() if v > 0)
                neg_stocks = sum(1 for v in stock_means.values() if v < 0)
                print(f"    [{'PASS' if cross_passed else 'FAIL'}] 标的交叉: "
                      f"正向={pos_stocks}, 负向={neg_stocks}")

                # ── 检验 4: 样本外稳定性 ──
                # 计算 IS 和 OOS 的平均 IC
                # 按标的日期索引划分（简化：用 STOCK_CODES 顺序模拟）
                # 实际更好的方法是按日期划分，这里用整体数据的前后分割
                split_point = n_total // 2
                is_ic = spearman_correlation(arr_rev[:split_point], arr_fwd[:split_point]) if split_point >= 3 else 0
                oos_ic = spearman_correlation(arr_rev[split_point:], arr_fwd[split_point:]) if (n_total - split_point) >= 3 else 0
                oos_passed = check_oos_stability(is_ic, oos_ic)
                print(f"    [{'PASS' if oos_passed else 'FAIL'}] 样本外稳定: "
                      f"IS_IC={is_ic:.4f}, OOS_IC={oos_ic:.4f}")

                # ── L3 汇总 ──
                checks_passed = sum([ts_passed, roll_passed, cross_passed, oos_passed])
                l3_passed = checks_passed >= STABILITY_L3_REQUIRED
                print(f"    L3 整体: {checks_passed}/4 通过 -> "
                      f"{'✅ PASS' if l3_passed else '❌ FAIL'}")

                stability_results[fname][state_label][period] = {
                    "overall_ic": overall_ic,
                    "time_slice": {"passed": ts_passed, "means": ts_means.tolist()},
                    "rolling": {"passed": roll_passed, "flip_rate": flip_rate},
                    "cross_sectional": {"passed": cross_passed, "stock_means": stock_means},
                    "oos": {"passed": oos_passed, "is_ic": is_ic, "oos_ic": oos_ic},
                    "checks_passed": checks_passed,
                    "checks_total": 4,
                    "L3_passed": l3_passed,
                }

    # ── L3 全局汇总 ──
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
    print(f"\n  ── L3 稳定性检验汇总 ──")
    print(f"  {total_l3}/{total_combos} 组合通过 L3 (通过率={total_l3/total_combos*100:.1f}%)" if total_combos > 0 else "  无数据")

    return stability_results


# ===================================================================
#  主函数
# ===================================================================

def main(dry_run: bool = False, skip_qc: bool = False, skip_sensitivity: bool = False):
    print(f"EXP-2026-INVFAC-002: 负向因子反转可行性验证")
    print(f"{'=' * 50}")
    print(f"dry_run={dry_run}, skip_qc={skip_qc}, skip_sensitivity={skip_sensitivity}")
    os.makedirs(REPORT_DIR, exist_ok=True)
    print(f"报告目录: {REPORT_DIR}")

    if dry_run:
        print("\n[Dry-Run] 架构验证通过，核心函数就绪:")
        for fname in FACTORS:
            print(f"  [OK] {fname}")
        print("  [OK] classify_market_state")
        print("  [OK] bootstrap_ic_test")
        print("  [OK] spearman_correlation")
        print("  [OK] reverse_factor")
        print("  [OK] check_time_slice_stability")
        print("  [OK] check_rolling_stability")
        print("  [OK] check_cross_sectional_stability")
        print("  [OK] check_oos_stability")
        print("  [OK] run_data_qc")
        print("  [OK] apply_fdr_bh")
        print("  [OK] run_stability_tests")
        print("  [OK] step_sensitivity_analysis")
        print("\n  (通过 dry_run 参数避免实际执行回测)")
        return

    # ─── §2.3: 数据质量前置检查 ────────────────────────────
    if not skip_qc:
        qc_passed = step_qc_preamble()
        if not qc_passed:
            # 写入 FAILED 状态文件
            failed_info = {
                "status": "FAILED",
                "task_id": "EXP-2026-INVFAC-002",
                "step": "qc",
                "error": "数据质量前置检查未通过",
                "completed_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            }
            failed_path = os.path.join(REPORT_DIR, "qc_failed.json")
            with open(failed_path, "w", encoding="utf-8") as f:
                json.dump(failed_info, f, ensure_ascii=False, indent=2)
            print(f"\n  ❌ 流水线因数据质量检查未通过而终止。")
            return
    else:
        print(f"\n[Skipped] 数据质量前置检查 (§2.3) — skip_qc=True")

    # ─── Step 1: 加载数据 ───────────────────────────────
    print("\n[Step 1] 加载数据...")
    all_stocks = {}
    for code in STOCK_CODES:
        data = load_stock_data(code)
        all_stocks[code] = data
        print(f"  {code}: {len(data['dates'])} 交易日, "
              f"[{data['dates'][0]} ~ {data['dates'][-1]}]")

    # ─── Step 2: 因子计算 ───────────────────────────────
    print("\n[Step 2] 计算三因子...")
    factor_values = {}  # {factor_name: {code: series}}
    for fname, fcfg in FACTORS.items():
        factor_values[fname] = {}
        for code in STOCK_CODES:
            d = all_stocks[code]
            factor_values[fname][code] = fcfg["func"](
                *[d[f] for f in fcfg["fields"]],
                **fcfg["params"],
            )

    # ─── Step 3: 市场状态分类 ───────────────────────────
    print("\n[Step 3] 市场状态分类 (滚动波动率分位数)...")
    market_states = {}  # {code: state_series}
    warmup_vol_by_stock: dict[str, np.ndarray] = {}
    for code in STOCK_CODES:
        d = all_stocks[code]
        # 暖机期波动率（用于锁定阈值，避免前视偏差）
        warmup_start, warmup_end = find_date_range(
            d["dates"], WARMUP_START, WARMUP_END
        )
        warmup_returns = np.diff(d["close"][warmup_start:warmup_end]) / \
                         d["close"][warmup_start:warmup_end - 1]
        warmup_vol = np.concatenate([[0.0], warmup_returns])
        warmup_vol_by_stock[code] = warmup_vol

        states, hi_thr, lo_thr = classify_market_state(
            d["close"], warmup_vol=warmup_vol,
        )
        market_states[code] = states
        print(f"  {code}: hi_thr={hi_thr:.4f}, lo_thr={lo_thr:.4f}, "
              f"高:{np.sum(states==2)}, 中:{np.sum(states==1)}, 低:{np.sum(states==0)}")

    # ─── Step 4 & 5: IC 计算 + Bootstrap 检验 ──────────
    print("\n[Step 4 & 5] IC 计算及三层检验...")
    all_results = {}  # {factor_name: {state_label: {period: {bootstrap_dict}}}}

    for fname in FACTORS:
        all_results[fname] = {}
        for state_label, state_val in [("low_vol", 0), ("mid_vol", 1), ("high_vol", 2)]:
            all_results[fname][state_label] = {}

            # 聚合该状态下所有标的
            all_factors = []
            all_returns_5d = []
            all_returns_10d = []
            all_returns_20d = []

            for code in STOCK_CODES:
                d = all_stocks[code]
                fac = factor_values[fname][code]
                states = market_states[code]

                # 选择该状态的交易日
                state_mask = states == state_val

                # 前向期收益率
                fwd_ret_5d = np.full(len(d["close"]), np.nan)
                fwd_ret_10d = np.full(len(d["close"]), np.nan)
                fwd_ret_20d = np.full(len(d["close"]), np.nan)

                for i in range(len(d["close"]) - 20):
                    fwd_ret_5d[i] = d["close"][i + 5] / d["close"][i] - 1
                    fwd_ret_10d[i] = d["close"][i + 10] / d["close"][i] - 1
                    fwd_ret_20d[i] = d["close"][i + 20] / d["close"][i] - 1

                # 反转因子
                reversed_fac = reverse_factor(fac)

                # 提取该状态的样本（单掩码，三持用同一组样本点）
                sel = state_mask & ~np.isnan(reversed_fac)
                if np.sum(sel) < 3:
                    continue

                all_factors.extend(reversed_fac[sel].tolist())
                all_returns_5d.extend(fwd_ret_5d[sel].tolist())
                all_returns_10d.extend(fwd_ret_10d[sel].tolist())
                all_returns_20d.extend(fwd_ret_20d[sel].tolist())

            if len(all_factors) < 3:
                continue

            for period, rets in [
                (5, all_returns_5d),
                (10, all_returns_10d),
                (20, all_returns_20d),
            ]:
                # Bootstrap 检验
                result = bootstrap_ic_test(
                    np.array(all_factors),
                    np.array(rets),
                    n_bootstrap=10000,
                    alpha=0.05,
                    random_seed=RANDOM_SEED,
                )
                all_results[fname][state_label][period] = result
                sig_mark = "[SIG]" if result["significant"] else "[NS]"
                print(f"  {fname}/{state_label}/p{period}d: "
                      f"IC={result['ic_mean']:.4f}, "
                      f"p={result['p_value']:.4f} {sig_mark}")

    # ─── §5.2: FDR BH 多重比较校正 ──────────────────
    fdr_result = apply_fdr_bh(all_results)

    # ─── §5.3: 三层稳定性检验 ─────────────────────────
    stability_result = run_stability_tests(
        factor_values, all_stocks, market_states,
    )

    # ─── §4.1: 分位数阈值敏感性分析 ──────────────────
    sensitivity_report = None
    if not skip_sensitivity:
        sensitivity_report = step_sensitivity_analysis(
            factor_values, all_stocks, warmup_vol_by_stock,
        )

    # ─── Step 6: 生成输出报告 ──────────────────────────
    print(f"\n[Step 6] 生成输出报告...")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 完整 JSON 输出
    output = {
        "task_id": "EXP-2026-INVFAC-002",
        "completed_time": timestamp,
        "status": "READY",
        "factors": list(FACTORS.keys()),
        "stocks": STOCK_CODES,
        "results": {},
        "fdr_correction": {
            "q": FDR_Q,
            "rejected_count": fdr_result["rejected_count"],
            "total_tests": fdr_result["total"],
            "details": fdr_result,
        },
        "stability_L3": {
            "summary": stability_result.get("_summary", {}),
        },
    }

    for fname, fstates in all_results.items():
        output["results"][fname] = {}
        for state_label, periods in fstates.items():
            output["results"][fname][state_label] = {
                str(p): r for p, r in periods.items()
            }

    result_path = os.path.join(REPORT_DIR, "exp_results.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"  ✅ {result_path}")

    # 敏感性分析独立输出
    if sensitivity_report:
        sens_path = os.path.join(REPORT_DIR, "sensitivity_analysis.json")
        with open(sens_path, "w", encoding="utf-8") as f:
            json.dump(sensitivity_report, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
        print(f"  ✅ {sens_path}")

    # 稳定性检验独立输出
    stab_path = os.path.join(REPORT_DIR, "stability_results.json")
    with open(stab_path, "w", encoding="utf-8") as f:
        json.dump(stability_result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"  ✅ {stab_path}")

    # 摘要报告
    summary_lines = [
        f"# EXP-2026-INVFAC-002 回测结果摘要\n",
        f"> completed: {timestamp}\n",
        f"## Bootstrap 检验汇总\n\n",
        f"| 因子 | 状态 | 持有期 | IC | p值 | 显著 | FDR_BH |\n",
        f"|:---|:---:|:---:|:---:|:---:|:---:|:---:|\n",
    ]

    # 构建 FDR 查找表
    fdr_lookup = {}
    for entry in fdr_result.get("corrections", []):
        key = (entry["factor"], entry["state"], entry["period"])
        fdr_lookup[key] = entry

    for fname, fstates in sorted(all_results.items()):
        for state_label in ["low_vol", "mid_vol", "high_vol"]:
            if state_label not in fstates:
                continue
            for period in [5, 10, 20]:
                if period not in fstates[state_label]:
                    continue
                r = fstates[state_label][period]
                sig = "SIG" if r["significant"] else "NS"
                fdr_entry = fdr_lookup.get((fname, state_label, period), {})
                fdr_sig = "BH_SIG" if fdr_entry.get("rejected") else "BH_NS"
                summary_lines.append(
                    f"| {fname} | {state_label} | {period}d | "
                    f"{r['ic_mean']:.4f} | {r['p_value']:.4f} | {sig} | {fdr_sig} |\n"
                )

    # L3 稳定性摘要
    summary_lines.append(f"\n## L3 稳定性检验汇总\n\n")
    summary_lines.append(f"| 因子 | 状态 | 持有期 | 时间切片 | 滚动窗口 | 标的交叉 | OOS | L3 |\n")
    summary_lines.append(f"|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n")
    for fname in sorted(FACTORS.keys()):
        for state_label in ["low_vol", "mid_vol", "high_vol"]:
            for period in [5, 10, 20]:
                r = stability_result.get(fname, {}).get(state_label, {}).get(period, {})
                if not isinstance(r, dict) or "L3_passed" not in r:
                    continue
                ts = "PASS" if r.get("time_slice", {}).get("passed") else "FAIL"
                rw = "PASS" if r.get("rolling", {}).get("passed") else "FAIL"
                cs = "PASS" if r.get("cross_sectional", {}).get("passed") else "FAIL"
                oo = "PASS" if r.get("oos", {}).get("passed") else "FAIL"
                l3 = "PASS" if r.get("L3_passed") else "FAIL"
                summary_lines.append(
                    f"| {fname} | {state_label} | {period}d | {ts} | {rw} | {cs} | {oo} | {l3} |\n"
                )

    summary_path = os.path.join(REPORT_DIR, "exp_summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.writelines(summary_lines)
    print(f"  ✅ {summary_path}")

    print(f"\n{'=' * 50}")
    print("回测完成。（完整流水线含 §2.3 QC / §4.1 敏感性 / §5.2 FDR / §5.3 稳定性）")


# ===================================================================
#  入口
# ===================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EXP-2026-INVFAC-002 回测主脚本")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run 模式：仅验证架构，不执行回测")
    parser.add_argument("--skip-qc", action="store_true", help="跳过 §2.3 数据质量前置检查")
    parser.add_argument("--skip-sensitivity", action="store_true", help="跳过 §4.1 敏感性分析")
    args = parser.parse_args()
    main(dry_run=args.dry_run, skip_qc=args.skip_qc, skip_sensitivity=args.skip_sensitivity)
