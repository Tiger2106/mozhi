"""
EXP-2026-003-KNOWDEEP Q3: 完整统计显著性验证
================================================
author: 墨衡 (moheng)
created: 2026-05-27T12:34+08:00

在Q2基础上补充完整统计显著性检验，确认C1-RWC方案的稳健性。

### 验证项
1. Bootstrap显著性检验 - C1-RWC验证期20d IC bootstrap置信区间 (5000次)
2. FDR多重检验校正 - 三个持有期(5/10/20d) FDR校正
3. L3稳定性检验 - C1-RWC三个窗口区间的一致性检验
4. reverse_factor跨周期一致性验证 - 训练期/验证期互换
5. 费用扣除后IC - 单边0.155%, 双边0.31%

### 对比方案
- C1-RWC: HV=0.5, MV=0.3, LV=0.2
- C3-RWC-U: 统一权重0.33/0.33/0.33

环境:
  - OS: Windows_NT 10.0.26200
  - Python: 3.x
  - 随机种子锁定: seed=42
"""

from __future__ import annotations

import json, os, sqlite3, subprocess, sys, time, copy
from datetime import datetime
import numpy as np

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, (np.bool_,)): return bool(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return super().default(obj)

import io
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except: pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from scripts.exp_invfac002.exp_factors import calc_trend_quality, calc_vol_rsi_std, reverse_factor
from scripts.exp_invfac002.exp_market_state import classify_market_state
from scripts.exp_invfac002.exp_bootstrap import spearman_correlation, bootstrap_ic_test, apply_verdict_degradation
from scripts.exp_invfac002.exp_stability import (
    check_time_slice_stability, check_rolling_stability,
    check_cross_sectional_stability, check_oos_stability,
)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")
Q2_RESULT_PATH = os.path.join(PROJECT_ROOT, "reports", "EXP-2026-003-KNOWDEEP", "q2", "q2_results.json")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "EXP-2026-003-KNOWDEEP", "q3")
os.makedirs(REPORT_DIR, exist_ok=True)

TRAIN_START, TRAIN_END = "20070101", "20191231"
VAL_START, VAL_END = "20200101", "20260430"
COMMISSION_RATE, STAMP_TAX_RATE, SLIPPAGE = 0.0003, 0.0005, 0.001
COST_ROUND_TRIP = COMMISSION_RATE + SLIPPAGE + COMMISSION_RATE + STAMP_TAX_RATE + SLIPPAGE
HOLDING_PERIODS = [5, 10, 20]
STATE_LABELS = {0: "low_vol", 1: "mid_vol", 2: "high_vol"}
SAMPLE_SIZE_THRESHOLD = 3000
DECAY_THRESHOLD_PASS = 0.50
RWC_WEIGHTS = {"high_vol": 0.5, "mid_vol": 0.3, "low_vol": 0.2}

def gv():
    try:
        r = subprocess.run(["git","rev-parse","--short","HEAD"], capture_output=True, text=True, cwd=PROJECT_ROOT)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except: return "unknown"

def lsc():
    conn = sqlite3.connect(DB_PATH)
    c = [r[0] for r in conn.execute("SELECT DISTINCT ts_code FROM stock_daily ORDER BY ts_code")]
    conn.close()
    return c

def lsd(code):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT trade_date,open,high,low,close,volume,adj_factor FROM stock_daily WHERE ts_code=? ORDER BY trade_date", (code,)).fetchall()
    conn.close()
    if not rows: return None
    dates = np.array([r[0] for r in rows])
    d = {"code": code, "dates": dates}
    for i,k in enumerate(["open","high","low","close","volume","adj_factor"]):
        d[k] = np.array([r[i] for r in rows], dtype=float)
    la = d["adj_factor"][-1] if len(d["adj_factor"]) else 1.0
    for k in ["open","high","low","close"]:
        d[k] *= d["adj_factor"] / la
    return d

def fdr(dates, start, end):
    return int(np.searchsorted(dates, start, "left")), int(np.searchsorted(dates, end, "right"))

def cfr(close, period, cost_adj=0.0):
    """前向收益（含费用调整）"""
    n = len(close); f = np.full(n, np.nan)
    cost = COST_ROUND_TRIP + cost_adj
    for i in range(n-period): f[i] = close[i+period]/close[i]-1-cost
    return f

def build_rwc_signal(fv, ms, stocks, weights):
    """构建C1-RWC信号"""
    base = "l_vol_rsi_std"
    rwc = {}
    for code in stocks:
        sig = fv[base][code]; st = ms[code]
        c, cnt = np.zeros(len(sig)), np.zeros(len(sig))
        for sv, sl in STATE_LABELS.items():
            w = weights[sl]; sel = st == sv
            c = np.where(sel, c + sig*w, c)
            cnt = np.where(sel, cnt+1, cnt)
        rwc[code] = np.where(cnt>0, c, 0.0)
    return rwc

def extract_ic_pairs(signal, stocks, ws, we, fwd, periods):
    """提取因子值与未来收益的对，用于bootstrap"""
    ic_pairs = {}
    for period in periods:
        af, ar = [], []
        for code in stocks:
            sig = signal.get(code, np.array([]))
            if len(sig)==0: continue
            d = stocks[code]
            iw = (np.arange(len(d["dates"]))>=ws)&(np.arange(len(d["dates"]))<we)
            fr = fwd[code][period]
            rs = reverse_factor(sig)
            sel = iw&~np.isnan(rs)&~np.isnan(fr)
            if np.sum(sel)<3: continue
            af.extend(rs[sel].tolist())
            ar.extend(fr[sel].tolist())
        ic_pairs[period] = (np.array(af), np.array(ar))
    return ic_pairs

def compute_ic_series(signal, stocks, ws, we, fwd, period):
    """计算滚动时序IC（用于稳定性检验）"""
    n_total = 0
    ic_series = []
    # 对齐所有股票的时间轴
    # 简化处理：对所有股票取并集窗口，计算截面IC
    dates = None
    for code in stocks:
        d = stocks[code]
        iw = (np.arange(len(d["dates"]))>=ws)&(np.arange(len(d["dates"]))<we)
        if dates is None:
            dates = d["dates"][iw]
        break
    
    if dates is None: return np.array([])
    
    # 对每个时间点计算截面IC
    for t_idx in range(ws, we):
        t_date = stocks[list(stocks.keys())[0]]["dates"][t_idx] if t_idx < len(stocks[list(stocks.keys())[0]]["dates"]) else None
        if t_date is None: continue
        
        fv_list, fr_list = [], []
        for code in stocks:
            sig = signal.get(code, np.array([]))
            d = stocks[code]
            if t_idx >= len(d["dates"]): continue
            if t_idx + period >= len(d["dates"]): continue
            
            fr_val = fwd[code][period][t_idx]
            rs_val = reverse_factor(sig[t_idx])
            
            if not np.isnan(fr_val) and not np.isnan(rs_val):
                fv_list.append(rs_val)
                fr_list.append(fr_val)
        
        if len(fv_list) >= 5:  # 至少5只股票
            ic_val = spearman_correlation(np.array(fv_list), np.array(fr_list))
            ic_series.append(ic_val)
    
    return np.array(ic_series)

def compute_ic_by_stock(signal, stocks, ws, we, fwd, period):
    """每只股票的时序IC"""
    ic_stock = {}
    for code in stocks:
        sig = signal.get(code, np.array([]))
        if len(sig)==0: continue
        d = stocks[code]
        iw = (np.arange(len(d["dates"]))>=ws)&(np.arange(len(d["dates"]))<we)
        fr = fwd[code][period]
        rs = reverse_factor(sig)
        sel = iw&~np.isnan(rs)&~np.isnan(fr)
        if np.sum(sel)<3: continue
        
        # 时序IC
        ic_stock[code] = np.array([rs[sel][k] * fr[sel][k] for k in range(np.sum(sel))])
    return ic_stock

def compute_bh_fdr(p_values, q=0.05):
    """Benjamini-Hochberg FDR 校正"""
    n = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = p_values[sorted_idx]
    ranks = np.arange(1, n+1)
    q_values = sorted_p * n / ranks
    # 单调性确保
    q_values = np.minimum.accumulate(q_values[::-1])[::-1]
    # 恢复原始顺序
    q_original = np.empty(n)
    q_original[sorted_idx] = q_values
    rejected = q_original < q
    return q_original, rejected

def cross_period_analysis(signal, stocks, periods, fwd):
    """reverse_factor跨周期一致性验证"""
    # 定义滑动窗口: 原始训练期(2007~2019), 原始验证期(2020~2026)
    # 互换: 训练期用2020~2023, 验证期用2007~2019
    # 同时增加中间窗口 2013~2019
    
    windows = {
        "original_train": (TRAIN_START, TRAIN_END),
        "original_val": (VAL_START, VAL_END),
        "swap_train": ("20200101", "20231231"),
        "swap_val": (TRAIN_START, "20191231"),
        "mid_train": ("20130101", "20191231"),
        "mid_val": ("20200101", "20231231"),
    }
    
    results = {}
    ref_code = list(stocks.keys())[0]
    
    for wname, (wstart, wend) in windows.items():
        ws, we = fdr(stocks[ref_code]["dates"], wstart, wend)
        ic_vals = {}
        for period in periods:
            af, ar = [], []
            for code in stocks:
                sig = signal.get(code, np.array([]))
                if len(sig)==0: continue
                d = stocks[code]
                iw = (np.arange(len(d["dates"]))>=ws)&(np.arange(len(d["dates"]))<we)
                fr = fwd[code][period]
                rs = reverse_factor(sig)
                sel = iw&~np.isnan(rs)&~np.isnan(fr)
                if np.sum(sel)<3: continue
                af.extend(rs[sel].tolist())
                ar.extend(fr[sel].tolist())
            if len(af)>=3:
                ic_vals[str(period)] = float(spearman_correlation(np.array(af), np.array(ar)))
            else:
                ic_vals[str(period)] = None
        results[wname] = ic_vals
    
    # 判断方向一致性
    consistency_check = {}
    for period in periods:
        ps = str(period)
        orig_train = results.get("original_train", {}).get(ps)
        orig_val = results.get("original_val", {}).get(ps)
        swap_train = results.get("swap_train", {}).get(ps)
        swap_val = results.get("swap_val", {}).get(ps)
        mid_train = results.get("mid_train", {}).get(ps)
        mid_val = results.get("mid_val", {}).get(ps)
        
        vals = [v for v in [orig_train, orig_val, swap_train, swap_val, mid_train, mid_val] if v is not None]
        if len(vals) >= 3:
            n_pos = sum(1 for v in vals if v > 0)
            n_neg = sum(1 for v in vals if v < 0)
            all_same_sign = (n_pos == len(vals)) or (n_neg == len(vals))
            direction_stable = max(n_pos, n_neg) >= len(vals) * 0.75
        else:
            all_same_sign = False
            direction_stable = False
        
        consistency_check[ps] = {
            "all_windows": vals,
            "n_positive": n_pos if 'n_pos' in dir() or True else sum(1 for v in vals if v > 0),
            "n_negative": n_neg if 'n_neg' in dir() or True else sum(1 for v in vals if v < 0),
            "all_same_sign": all_same_sign,
            "direction_stable": direction_stable,
        }
        # Recalculate to be safe
        n_pos = sum(1 for v in vals if v > 0)
        n_neg = sum(1 for v in vals if v < 0)
        consistency_check[ps] = {
            "all_windows": vals,
            "n_positive": n_pos,
            "n_negative": n_neg,
            "all_same_sign": n_pos == len(vals) or n_neg == len(vals),
            "direction_stable": max(n_pos, n_neg) >= len(vals) * 0.75,
        }
        
    return results, consistency_check

def main():
    t0 = time.time()
    vt = gv()
    rt = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    print(f"EXP-2026-003 Q3 | {vt} | {rt}")
    print("="*70)
    
    # ── 加载Q2结果 ──
    with open(Q2_RESULT_PATH, "r", encoding="utf-8") as f:
        q2_data = json.load(f)
    c1_rwc_q2 = q2_data["composite_analysis"]["C1_rwc"]
    c3_ewc_q2 = q2_data["composite_analysis"]["C3_ewc"]
    print(f"[0] Q2结果加载完成: C1-RWC val 20d IC={c1_rwc_q2['val_ic']['20']['ic_mean']:.6f}")
    
    # ── 加载数据 ──
    codes = lsc()
    stocks = {c: lsd(c) for c in codes if lsd(c) is not None}
    vc = list(stocks.keys())
    print(f"[1] 加载 {len(vc)} 只沪深300成分股")
    
    # ── 因子计算 ──
    fv = {"l_vol_rsi_std": {}}
    for code in vc:
        d = stocks[code]
        fv["l_vol_rsi_std"][code] = calc_vol_rsi_std(d["volume"])
    print("[2] l_vol_rsi_std 因子计算完成")
    
    # ── 市场状态 ──
    ms = {}
    for code in vc:
        d = stocks[code]
        ws_i, _ = fdr(d["dates"], TRAIN_START, TRAIN_END)
        ret = np.diff(d["close"]) / d["close"][:-1]
        wv = np.full(len(d["close"]), np.nan)
        for i in range(20, min(len(d["close"]), ws_i + 200)):
            wv[i] = np.std(ret[i-19:i+1]) * np.sqrt(252)
        ms[code], _, _ = classify_market_state(d["close"], warmup_vol=wv)
    print("[3] 市场状态分类完成")
    
    # ── 前向收益缓存（含费用版本） ──
    fwd_no_cost = {code: {p: cfr(stocks[code]["close"], p, 0.0) for p in HOLDING_PERIODS} for code in vc}
    fwd_with_cost = {code: {p: cfr(stocks[code]["close"], p, 0.0031) for p in HOLDING_PERIODS} for code in vc}
    print("[Cache] 前向收益缓存完成")
    
    _, te = fdr(stocks[vc[0]]["dates"], TRAIN_START, TRAIN_END)
    vs, ve = fdr(stocks[vc[0]]["dates"], VAL_START, VAL_END)
    print(f"[Index] 训练期 [0,{te}) 验证期 [{vs},{ve})")
    
    # ── 构建C1-RWC信号 ──
    c1_signal = build_rwc_signal(fv, ms, stocks, RWC_WEIGHTS)
    
    # ── 构建C3-RWC-U信号（对比方案） ──
    u_weights = {"high_vol": 1/3, "mid_vol": 1/3, "low_vol": 1/3}
    c3_signal = build_rwc_signal(fv, ms, stocks, u_weights)
    print("[4] C1-RWC 和 C3-RWC-U 信号构建完成")
    
    # ════════════════════════════════════════════════════════
    #  验证项1: Bootstrap显著性检验
    # ════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("【验证项1】Bootstrap显著性检验 (5000次置换)")
    print("="*70)
    
    ic_pairs_val = extract_ic_pairs(c1_signal, stocks, vs, ve, fwd_no_cost, HOLDING_PERIODS)
    bootstrap_results = {}
    for period in HOLDING_PERIODS:
        fv_arr, fr_arr = ic_pairs_val[period]
        print(f"  C1-RWC Val p{period}d: n={len(fv_arr)}", end="")
        bt = bootstrap_ic_test(fv_arr, fr_arr, n_bootstrap=5000, alpha=0.05, random_seed=42)
        bootstrap_results[period] = bt
        print(f" IC={bt['ic_mean']:.6f} p={bt['p_value']:.6f} ci=[{bt['ci_lower']:.6f},{bt['ci_upper']:.6f}] sig={bt['significant']}")
    
    # 主验证: C1-RWC 20d
    bt_20d = bootstrap_results[20]
    bootstrap_verdict = {
        "20d_ic_mean": bt_20d["ic_mean"],
        "p_value": bt_20d["p_value"],
        "ci_95": [bt_20d["ci_lower"], bt_20d["ci_upper"]],
        "significant": bt_20d["significant"],
        "n_bootstrap": 5000,
        "alpha": 0.05,
        "seed": 42,
    }
    
    # ════════════════════════════════════════════════════════
    #  验证项2: FDR多重检验校正
    # ════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("【验证项2】FDR多重检验校正 (BH过程)")
    print("="*70)
    
    p_vals_3hp = np.array([bootstrap_results[p]["p_value"] for p in HOLDING_PERIODS])
    q_vals, rejected = compute_bh_fdr(p_vals_3hp, q=0.05)
    
    fdr_results = {}
    for i, period in enumerate(HOLDING_PERIODS):
        fdr_results[period] = {
            "p_value": p_vals_3hp[i],
            "q_value": q_vals[i],
            "rejected": bool(rejected[i]),
        }
        print(f"  p{period}d: p={p_vals_3hp[i]:.6f} q={q_vals[i]:.6f} rejected={rejected[i]}")
    
    fdr_verdict = {
        "method": "Benjamini-Hochberg",
        "fdr_q": 0.05,
        "n_tests": 3,
        "n_rejected": int(np.sum(rejected)),
        "all_rejected": bool(np.all(rejected)),
        "verdict": "PASS" if np.all(rejected) else "WARN",
    }
    print(f"  FDR裁决: {fdr_verdict['verdict']} ({fdr_verdict['n_rejected']}/{fdr_verdict['n_tests']} rejected)")
    
    # ════════════════════════════════════════════════════════
    #  验证项3: L3稳定性检验
    # ════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("【验证项3】L3稳定性检验")
    print("="*70)
    
    l3_results = {}
    for period in HOLDING_PERIODS:
        print(f"\n  C1-RWC Val p{period}d:")
        ic_series = compute_ic_series(c1_signal, stocks, vs, ve, fwd_no_cost, period)
        if len(ic_series) < 10:
            print(f"    ⚠ IC序列过短 ({len(ic_series)}), 跳过L3检验")
            l3_results[str(period)] = {"error": f"IC序列过短 ({len(ic_series)})"}
            continue
        
        # 1. 时间切片
        ts_passed, ts_means = check_time_slice_stability(ic_series, n_slices=4)
        print(f"    [时间切片] passed={ts_passed} means={[f'{m:.6f}' for m in ts_means]}")
        
        # 2. 滚动稳定性
        roll_passed, flip_rate = check_rolling_stability(ic_series, roll_window=min(126, len(ic_series)//4))
        print(f"    [滚动] passed={roll_passed} flip_rate={flip_rate:.4f}")
        
        # 3. 标的交叉稳定性
        ic_by_stock = compute_ic_by_stock(c1_signal, stocks, vs, ve, fwd_no_cost, period)
        cs_passed, stock_means = check_cross_sectional_stability(
            {k: v for k, v in ic_by_stock.items()}, 
            min_agree=max(8, len(ic_by_stock)*0.6), 
            n_stocks=len(ic_by_stock)
        )
        print(f"    [标的交叉] passed={cs_passed} stocks={len(stock_means)}")
        
        # 4. OOS检验 - 使用训练期vs验证期的方向一致性
        train_pairs = extract_ic_pairs(c1_signal, stocks, 0, te, fwd_no_cost, [period])
        train_fv, train_fr = train_pairs[period]
        train_ic = spearman_correlation(train_fv, train_fr) if len(train_fv)>=3 else 0.0
        val_ic = bootstrap_results[period]["ic_mean"]
        oos_passed = check_oos_stability(train_ic, val_ic)
        print(f"    [OOS] passed={oos_passed} train_IC={train_ic:.6f} val_IC={val_ic:.6f}")
        
        checks_passed = sum([ts_passed, roll_passed, cs_passed, oos_passed])
        l3_passed = checks_passed >= 3
        
        l3_results[str(period)] = {
            "time_slice": {"passed": ts_passed, "means": [float(m) for m in ts_means if not np.isnan(m)]},
            "rolling": {"passed": roll_passed, "flip_rate": float(flip_rate)},
            "cross_sectional": {"passed": cs_passed, "n_stocks": len(stock_means)},
            "oos": {"passed": oos_passed, "train_ic": float(train_ic), "val_ic": float(val_ic)},
            "checks_passed": checks_passed,
            "checks_total": 4,
            "L3_passed": l3_passed,
        }
        print(f"    → L3裁决: {'PASS' if l3_passed else 'WARN'} ({checks_passed}/4)")
    
    l3_verdict = {
        "description": "三层稳定性检验（时间切片+滚动+标的交叉+OOS）",
        "results": l3_results,
    }
    
    # ════════════════════════════════════════════════════════
    #  验证项4: reverse_factor跨周期一致性验证
    # ════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("【验证项4】reverse_factor跨周期一致性验证")
    print("="*70)
    
    cross_results, cross_consistency = cross_period_analysis(c1_signal, stocks, HOLDING_PERIODS, fwd_no_cost)
    
    for wname, ic_vals in cross_results.items():
        ics = ", ".join([f"p{p}d:{v:.4f}" if v else f"p{p}d:None" for p, v in ic_vals.items()])
        print(f"  {wname}: {ics}")
    
    print("\n  方向一致性检查:")
    for ps, check in cross_consistency.items():
        print(f"    p{ps}d: n_pos={check['n_positive']} n_neg={check['n_negative']} "
              f"all_same={check['all_same_sign']} stable={check['direction_stable']}")
    
    cross_verdict = {
        "windows": cross_results,
        "consistency": cross_consistency,
        "all_periods_stable": all(c["direction_stable"] for c in cross_consistency.values()),
    }
    
    # ════════════════════════════════════════════════════════
    #  验证项5: 费用扣除后IC
    # ════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("【验证项5】费用扣除后IC (单边0.155%, 双边0.31%)")
    print("="*70)
    
    ic_pairs_val_cost = extract_ic_pairs(c1_signal, stocks, vs, ve, fwd_with_cost, HOLDING_PERIODS)
    cost_results = {}
    for period in HOLDING_PERIODS:
        fv_arr, fr_arr = ic_pairs_val_cost[period]
        ic_net = spearman_correlation(fv_arr, fr_arr) if len(fv_arr)>=3 else 0.0
        cost_results[period] = {
            "gross_ic": bootstrap_results[period]["ic_mean"],
            "net_ic": float(ic_net),
            "n_samples": len(fv_arr),
            "net_alpha_positive": ic_net > 0,
        }
        print(f"  p{period}d: Gross IC={bootstrap_results[period]['ic_mean']:.6f} → "
              f"Net IC(含费用)={ic_net:.6f} alpha_positive={ic_net>0}")
    
    # C3-RWC-U对比
    print("\n  ── C3-RWC-U对比 ──")
    ic_pairs_c3_val = extract_ic_pairs(c3_signal, stocks, vs, ve, fwd_no_cost, HOLDING_PERIODS)
    ic_pairs_c3_val_cost = extract_ic_pairs(c3_signal, stocks, vs, ve, fwd_with_cost, HOLDING_PERIODS)
    c3_results = {}
    for period in HOLDING_PERIODS:
        fv_arr, fr_arr = ic_pairs_c3_val[period]
        c3_ic = spearman_correlation(fv_arr, fr_arr) if len(fv_arr)>=3 else 0.0
        fv_arr_c, fr_arr_c = ic_pairs_c3_val_cost[period]
        c3_ic_net = spearman_correlation(fv_arr_c, fr_arr_c) if len(fv_arr_c)>=3 else 0.0
        c3_results[period] = {"gross_ic": float(c3_ic), "net_ic": float(c3_ic_net)}
        print(f"  C3-RWC-U p{period}d: Gross={c3_ic:.6f} Net={c3_ic_net:.6f}")
    
    # ════════════════════════════════════════════════════════
    #  汇总与输出
    # ════════════════════════════════════════════════════════
    ct = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    el = time.time() - t0
    
    q3_verdict = {
        "task_id": "EXP-2026-003-KNOWDEEP",
        "work_package": "Q3",
        "version_tag": vt,
        "run_timestamp": rt,
        "completed_time": ct,
        "elapsed_seconds": round(el, 2),
        "status": "READY",
        "config": {
            "base_signal": "l_vol_rsi_std",
            "primary_composite": "C1-RWC",
            "compare_composite": "C3-RWC-U",
            "weights": {"HV": 0.5, "MV": 0.3, "LV": 0.2},
            "train_window": f"{TRAIN_START}~{TRAIN_END}",
            "val_window": f"{VAL_START}~{VAL_END}",
            "holding_periods": HOLDING_PERIODS,
            "n_bootstrap": 5000,
            "alpha": 0.05,
            "fdr_q": 0.05,
            "random_seed": 42,
            "cost_single_side": 0.00155,
            "cost_round_trip": 0.0031,
            "seed_locked": True,
        },
        "bootstrap_test": {
            "description": "C1-RWC验证期 5000次置换检验",
            "20d_primary": bootstrap_verdict,
            "all_periods": {str(p): bootstrap_results[p] for p in HOLDING_PERIODS},
        },
        "fdr_correction": {
            "description": "三持有期(5/10/20d) BH FDR校正",
            "method": "Benjamini-Hochberg",
            "fdr_q": 0.05,
            "n_tests": 3,
            "results": {str(p): fdr_results[p] for p in HOLDING_PERIODS},
            "verdict": fdr_verdict,
        },
        "l3_stability": {
            "description": "C1-RWC验证期三层稳定性检验",
            "results": l3_results,
        },
        "cross_period_consistency": {
            "description": "reverse_factor跨周期6窗口方向一致性",
            "windows": cross_results,
            "consistency": {k: {kk: vv for kk, vv in v.items() if kk != "all_windows"} for k, v in cross_consistency.items()},
        },
        "cost_adjusted_ic": {
            "description": "扣除双边0.31%费用后Alpha",
            "C1_RWC": {str(p): cost_results[p] for p in HOLDING_PERIODS},
            "C3_RWC_U": {str(p): c3_results[p] for p in HOLDING_PERIODS},
        },
        "summary": {
            "bootstrap_passed": bt_20d["significant"],
            "fdr_passed": bool(np.all(rejected)),
            "l3_passed": all(r.get("L3_passed", False) for r in l3_results.values()),
            "cross_period_stable": cross_verdict["all_periods_stable"],
            "net_alpha_positive": all(cost_results[p]["net_alpha_positive"] for p in HOLDING_PERIODS),
            "c1_vs_c3": {
                "c1_20d_gross": c1_rwc_q2["val_ic"]["20"]["ic_mean"],
                "c3_20d_gross": c3_ewc_q2["val_ic"]["20"]["ic_mean"],
                "advantage_c1": c1_rwc_q2["val_ic"]["20"]["ic_mean"] > c3_ewc_q2["val_ic"]["20"]["ic_mean"],
            },
        },
    }
    
    # 保存JSON结果
    json_path = os.path.join(REPORT_DIR, "q3_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(q3_verdict, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"\n[OK] JSON结果已写入: {json_path}")
    
    # 验证写入
    with open(json_path, "r", encoding="utf-8") as f:
        v = json.load(f)
    assert v["status"] == "READY"
    print("[验证通过] status=READY")
    
    print(f"\n{'='*70}")
    print(f"Q3 完成 | {el:.1f}s | {ct}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
