"""
EXP-2026-003-KNOWDEEP: C1-RWC 权重灵敏度分析 (±20%)
===========================================================
author: 墨衡 (moheng)
created: 2026-05-27T11:42+08:00

对 C1-RWC 当前权重 (HV=0.5, MV=0.3, LV=0.2) 进行扰动测试：
  - 每个权重分量分别扰动 ±20%（共6种组合）
  - 同时扰动3个权重（极端组合）
  - 测试 IC 变化范围，验证权重是否在 ±20% 范围内保持方向一致性和 IC>0

依赖: scripts.exp_invfac002.*, market_data.db
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import io
from datetime import datetime
from copy import deepcopy

import numpy as np

# ── 控制台编码修复 ──
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except:
    pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from scripts.exp_invfac002.exp_factors import calc_vol_rsi_std, reverse_factor
from scripts.exp_invfac002.exp_market_state import classify_market_state
from scripts.exp_invfac002.exp_bootstrap import spearman_correlation

# ── 配置 ──
DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "EXP-2026-003-KNOWDEEP", "optimization")
os.makedirs(REPORT_DIR, exist_ok=True)

TRAIN_START, TRAIN_END = "20070101", "20191231"
VAL_START, VAL_END = "20200101", "20260430"
HOLDING_PERIODS = [5, 10, 20]
STATE_LABELS = {0: "low_vol", 1: "mid_vol", 2: "high_vol"}
RWC_BASE_WEIGHTS = {"high_vol": 0.5, "mid_vol": 0.3, "low_vol": 0.2}


def list_codes():
    conn = sqlite3.connect(DB_PATH)
    codes = [r[0] for r in conn.execute("SELECT DISTINCT ts_code FROM stock_daily ORDER BY ts_code")]
    conn.close()
    return codes


def load_stock(code):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT trade_date,open,high,low,close,volume,adj_factor FROM stock_daily WHERE ts_code=? ORDER BY trade_date",
        (code,)
    ).fetchall()
    conn.close()
    if not rows:
        return None
    d = {"code": code, "dates": np.array([r[0] for r in rows])}
    for i, k in enumerate(["open", "high", "low", "close", "volume", "adj_factor"]):
        d[k] = np.array([r[i] for r in rows], dtype=float)
    la = d["adj_factor"][-1] if len(d["adj_factor"]) else 1.0
    for k in ["open", "high", "low", "close"]:
        d[k] *= d["adj_factor"] / la
    return d


def date_range(dates, start, end):
    return (int(np.searchsorted(dates, start, "left")),
            int(np.searchsorted(dates, end, "right")))


def compute_forward_returns(close, period, cost=None):
    """多持有期前向收益（含交易成本）"""
    if cost is None:
        cost = 0.0003 + 0.001 + 0.0003 + 0.0005 + 0.001
    n = len(close)
    fwd = np.full(n, np.nan)
    for i in range(n - period):
        fwd[i] = close[i + period] / close[i] - 1.0 - cost
    return fwd


def compute_c1_rwc(signal, ms, weights):
    """构建 C1-RWC 复合信号"""
    result = {}
    for code in signal:
        sig = signal[code]
        st = ms[code]
        c = np.zeros(len(sig))
        cnt = np.zeros(len(sig))
        for sv, sl in STATE_LABELS.items():
            w = weights[sl]
            sel = st == sv
            c = np.where(sel, c + sig * w, c)
            cnt = np.where(sel, cnt + 1, cnt)
        result[code] = np.where(cnt > 0, c, 0.0)
    return result


def compute_ic_for_composite(signal, stocks, ws, we, fwd):
    """计算复合信号的 IC（训练期或验证期）"""
    result = {}
    for period in HOLDING_PERIODS:
        all_f, all_r = [], []
        for code in signal:
            sig = signal.get(code, np.array([]))
            if len(sig) == 0:
                continue
            d = stocks[code]
            iw = (np.arange(len(d["dates"])) >= ws) & (np.arange(len(d["dates"])) < we)
            fr = fwd[code][period]
            rs = reverse_factor(sig)
            sel = iw & ~np.isnan(rs) & ~np.isnan(fr)
            if np.sum(sel) < 3:
                continue
            all_f.extend(rs[sel].tolist())
            all_r.extend(fr[sel].tolist())
        n = len(all_f)
        if n >= 3:
            result[period] = {
                "ic_mean": float(spearman_correlation(np.array(all_f), np.array(all_r))),
                "n_samples": n
            }
        else:
            result[period] = {"ic_mean": None, "n_samples": n}
    return result


def direction_consistent(ic_mean_a, ic_mean_b, tolerance=1e-8):
    """检查两个 IC 的方向一致性"""
    if ic_mean_a is None or ic_mean_b is None:
        return None
    return (ic_mean_a > tolerance) == (ic_mean_b > tolerance)


def format_ic_line(ic_data, periods, label):
    """格式化 IC 输出"""
    parts = []
    for p in periods:
        v = ic_data[p].get("ic_mean")
        if v is not None:
            parts.append(f"p{p}d:{v:.4f}")
        else:
            parts.append(f"p{p}d:NA")
    return f"    {label}: {', '.join(parts)}"


# ── 主分析 ──
def main():
    t0 = time.time()
    print("=" * 60)
    print("C1-RWC 权重灵敏度分析 (±20%)")
    hvw = RWC_BASE_WEIGHTS["high_vol"]
    mvw = RWC_BASE_WEIGHTS["mid_vol"]
    lvw = RWC_BASE_WEIGHTS["low_vol"]
    print(f"基准权重: HV={hvw}, MV={mvw}, LV={lvw}")
    print("=" * 60)

    # 1. 加载数据
    codes = list_codes()
    stocks = {c: load_stock(c) for c in codes if load_stock(c) is not None}
    valid_codes = list(stocks.keys())
    print(f"[1] 加载 {len(valid_codes)} 只标的")

    # 2. 计算因子（仅 l_vol_rsi_std）
    base_signal = {}
    for code in valid_codes:
        base_signal[code] = calc_vol_rsi_std(stocks[code]["volume"])
    print("[2] 因子计算完成 (l_vol_rsi_std)")

    # 3. 市场状态分类
    ms = {}
    for code in valid_codes:
        d = stocks[code]
        ws, _ = date_range(d["dates"], TRAIN_START, TRAIN_END)
        ret = np.diff(d["close"]) / d["close"][:-1]
        wv = np.full(len(d["close"]), np.nan)
        for i in range(20, min(len(d["close"]), ws + 200)):
            wv[i] = np.std(ret[i - 19:i + 1]) * np.sqrt(252)
        ms[code], _, _ = classify_market_state(d["close"], warmup_vol=wv)
    print("[3] 市场状态分类完成")

    # 4. 前向收益缓存
    fwd = {
        code: {p: compute_forward_returns(stocks[code]["close"], p) for p in HOLDING_PERIODS}
        for code in valid_codes
    }
    print("[4] 前向收益缓存完成")

    # 5. 窗口范围
    _, te = date_range(stocks[valid_codes[0]]["dates"], TRAIN_START, TRAIN_END)
    vs, ve = date_range(stocks[valid_codes[0]]["dates"], VAL_START, VAL_END)

    # 6. 定义扰动组合
    perturbations = []

    # 6a. 单权重扰动 ±20%
    weight_names = ["high_vol", "mid_vol", "low_vol"]
    for dim in weight_names:
        for delta in [-0.20, +0.20]:
            w = deepcopy(RWC_BASE_WEIGHTS)
            w[dim] = round(w[dim] * (1 + delta), 4)
            desc = f"{dim}_{delta*100:+.0f}%"
            perturbations.append((desc, w))

    # 6b. 极端组合：三个权重同向扰动
    for delta in [-0.20, +0.20]:
        w = {k: round(v * (1 + delta), 4) for k, v in RWC_BASE_WEIGHTS.items()}
        # 归一化确保和为1
        total = sum(w.values())
        if abs(total - 1.0) > 1e-6:
            w_norm = {k: round(v / total, 4) for k, v in w.items()}
            desc = f"all_{delta*100:+.0f}%_normed"
            perturbations.append((desc, w_norm))
        else:
            desc = f"all_{delta*100:+.0f}%"
            perturbations.append((desc, w))

    # 7. 运行分析
    print(f"\n[5] 运行 {len(perturbations)} 种扰动组合\n")

    # 7a. 先跑基准
    sep = "\u2500" * 50
    print(f"  {sep}")
    print(f"  基准: HV={hvw} MV={mvw} LV={lvw}")
    base_signal_c1 = compute_c1_rwc(base_signal, ms, RWC_BASE_WEIGHTS)
    base_train = compute_ic_for_composite(base_signal_c1, stocks, 0, te, fwd)
    base_val = compute_ic_for_composite(base_signal_c1, stocks, vs, ve, fwd)
    print(format_ic_line(base_train, HOLDING_PERIODS, "Train"))
    print(format_ic_line(base_val, HOLDING_PERIODS, "Val"))
    print()

    # 7b. 跑所有扰动
    results_dict = {
        "baseline": {"weights": RWC_BASE_WEIGHTS, "train_ic": base_train, "val_ic": base_val}
    }

    for label, weights in perturbations:
        hw = weights["high_vol"]
        mw = weights["mid_vol"]
        lw = weights["low_vol"]
        print(f"  {label}: HV={hw} MV={mw} LV={lw}")
        signal_c1 = compute_c1_rwc(base_signal, ms, weights)
        train_ic = compute_ic_for_composite(signal_c1, stocks, 0, te, fwd)
        val_ic = compute_ic_for_composite(signal_c1, stocks, vs, ve, fwd)
        print(format_ic_line(train_ic, HOLDING_PERIODS, "Train"))
        print(format_ic_line(val_ic, HOLDING_PERIODS, "Val"))

        # 方向一致性检查
        dc_train = {}
        dc_val = {}
        for p in HOLDING_PERIODS:
            bt_ic = base_train[p].get("ic_mean")
            tt_ic = train_ic[p].get("ic_mean")
            bv_ic = base_val[p].get("ic_mean")
            tv_ic = val_ic[p].get("ic_mean")
            dc_train[p] = direction_consistent(bt_ic, tt_ic)
            dc_val[p] = direction_consistent(bv_ic, tv_ic)

        dc_train_str = ", ".join(f"p{p}d:{dc_train[p]}" for p in HOLDING_PERIODS)
        dc_val_str = ", ".join(f"p{p}d:{dc_val[p]}" for p in HOLDING_PERIODS)
        print(f"    DirCons(train): {dc_train_str}")
        print(f"    DirCons(val):   {dc_val_str}")

        # IC>0 检查
        ic_pos_train = {}
        ic_pos_val = {}
        for p in HOLDING_PERIODS:
            ic_pos_train[p] = train_ic[p]["ic_mean"] > 0 if train_ic[p].get("ic_mean") else None
            ic_pos_val[p] = val_ic[p]["ic_mean"] > 0 if val_ic[p].get("ic_mean") else None

        ip_train_str = ", ".join(f"p{p}d:{ic_pos_train[p]}" for p in HOLDING_PERIODS)
        ip_val_str = ", ".join(f"p{p}d:{ic_pos_val[p]}" for p in HOLDING_PERIODS)
        print(f"    IC>0(train):   {ip_train_str}")
        print(f"    IC>0(val):     {ip_val_str}")
        print()

        results_dict[label] = {
            "weights": weights,
            "train_ic": train_ic,
            "val_ic": val_ic,
            "direction_consistent": {"train": dc_train, "val": dc_val},
            "ic_positive": {"train": ic_pos_train, "val": ic_pos_val},
        }

    # 8. 汇总判断
    print(f"\n{'=' * 60}")
    print("汇总判断")
    print(f"{'=' * 60}")

    # 方向一致性汇总
    all_train_dc = {p: [] for p in HOLDING_PERIODS}
    all_val_dc = {p: [] for p in HOLDING_PERIODS}
    for label, _ in perturbations:
        dc_entry = results_dict[label]["direction_consistent"]
        for p in HOLDING_PERIODS:
            all_train_dc[p].append(dc_entry["train"].get(p))
            all_val_dc[p].append(dc_entry["val"].get(p))

    print("\n方向一致性保持率 (Train):")
    for p in HOLDING_PERIODS:
        ok = sum(1 for v in all_train_dc[p] if v is True)
        total = sum(1 for v in all_train_dc[p] if v is not None)
        print(f"  p{p}d: {ok}/{total}")

    print("\n方向一致性保持率 (Val):")
    for p in HOLDING_PERIODS:
        ok = sum(1 for v in all_val_dc[p] if v is True)
        total = sum(1 for v in all_val_dc[p] if v is not None)
        print(f"  p{p}d: {ok}/{total}")

    # IC>0 保持率
    print("\nIC>0 保持率 (Train):")
    for p in HOLDING_PERIODS:
        ok = sum(1 for lbl, _ in perturbations if results_dict[lbl]["ic_positive"]["train"].get(p) is True)
        total = sum(1 for lbl, _ in perturbations if results_dict[lbl]["ic_positive"]["train"].get(p) is not None)
        print(f"  p{p}d: {ok}/{total}")

    print("\nIC>0 保持率 (Val):")
    for p in HOLDING_PERIODS:
        ok = sum(1 for lbl, _ in perturbations if results_dict[lbl]["ic_positive"]["val"].get(p) is True)
        total = sum(1 for lbl, _ in perturbations if results_dict[lbl]["ic_positive"]["val"].get(p) is not None)
        print(f"  p{p}d: {ok}/{total}")

    # IC 变化范围
    print("\nIC 变化范围:")
    for period in HOLDING_PERIODS:
        train_ics = [
            results_dict[lbl]["train_ic"][period]["ic_mean"]
            for lbl, _ in perturbations
            if results_dict[lbl]["train_ic"][period].get("ic_mean") is not None
        ]
        val_ics = [
            results_dict[lbl]["val_ic"][period]["ic_mean"]
            for lbl, _ in perturbations
            if results_dict[lbl]["val_ic"][period].get("ic_mean") is not None
        ]
        bt = base_train[period].get("ic_mean")
        bv = base_val[period].get("ic_mean")
        if train_ics:
            print(f"  Train p{period}d: [{min(train_ics):.4f}, {max(train_ics):.4f}] (基准: {bt:.4f})")
        if val_ics:
            print(f"  Val   p{period}d: [{min(val_ics):.4f}, {max(val_ics):.4f}] (基准: {bv:.4f})")

    # 9. 结论判定
    all_dc_good = True
    all_ic_pos = True
    for lbl, _ in perturbations:
        for p in HOLDING_PERIODS:
            dc_t = results_dict[lbl]["direction_consistent"]["train"].get(p)
            dc_v = results_dict[lbl]["direction_consistent"]["val"].get(p)
            ip_t = results_dict[lbl]["ic_positive"]["train"].get(p)
            ip_v = results_dict[lbl]["ic_positive"]["val"].get(p)
            if dc_t is False or dc_v is False:
                all_dc_good = False
            if ip_t is False or ip_v is False:
                all_ic_pos = False

    print(f"\n{'=' * 60}")
    print("结论")
    print(f"{'=' * 60}")
    print(f"  扰动组合数: {len(perturbations)}")
    print(f"  方向一致性保持: {'PASS' if all_dc_good else 'FAIL'}")
    print(f"  IC>0 保持: {'PASS' if all_ic_pos else 'WARN'}")
    print()
    if all_dc_good:
        print(f"  复杂度判定: C1-RWC 权重在 ±20% 范围内稳健 → 复杂度 C1≈C3")
    else:
        print(f"  复杂度判定: C1-RWC 权重对结果有显著影响 → 复杂度高于 C3")
    print()

    # 10. 保存结果
    perturb_list = []
    for lbl, w in perturbations:
        perturb_list.append({"label": lbl, "weights": dict(w)})

    report = {
        "title": "C1-RWC 权重灵敏度分析 (±20%)",
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "baseline_weights": RWC_BASE_WEIGHTS,
        "perturbation_count": len(perturbations),
        "perturbations": perturb_list,
        "direction_consistent_maintained": all_dc_good,
        "ic_positive_maintained": all_ic_pos,
        "verdict": "PASS" if all_dc_good else "WARN",
        "complexity_implication": "C1≈C3" if all_dc_good else "C1>C3",
        "baseline": {
            "weights": RWC_BASE_WEIGHTS,
            "train_ic": base_train,
            "val_ic": base_val,
        },
        "details": results_dict,
    }

    path = os.path.join(REPORT_DIR, "c1_rwc_sensitivity.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # 验证写入
    with open(path, "r", encoding="utf-8") as f:
        v = json.load(f)
    assert v.get("verdict") in ("PASS", "WARN"), f"verdict mismatch: {v.get('verdict')}"
    print(f"[OK] 写入验证通过: {path}")

    elapsed = time.time() - t0
    print(f"\n耗时: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
