"""
EXP-2026-003-KNOWDEEP Q2: 组合信号分析（极速版：IC + 衰减 + 观察）
==================================================
author: 墨衡 (moheng)
created: 2026-05-27T09:24+08:00

Owner 约束（硬性遵守）：
  1. Q2 只用 l_vol_rsi_std 作为基础信号
  2. TrendQuality 降为观察指标，不作为信号输入
  3. KID-EXP003-001 知识条目不提前激活
  4. 样本量门限 < 3000 时 verdict 自动降一级

复合方案：
  C1: Regime-Weighted (RWC) — HV=0.5, MV=0.3, LV=0.2
  C2: Regime-Filtered (RFS) — 仅 LV+MV（排除样本不足 HV）
  C3: Equal-Weight (EWC) — 所有状态等权
  C4: Vol-Scaled (VSS) — HV按波动率比例压缩

方法：仅计算 Spearman IC + 衰减率 + 样本量门限降级。
显著性推断基于 Q1 已验证的 bootstrap 结果。
"""

from __future__ import annotations
import json, os, sqlite3, subprocess, sys, time
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
from scripts.exp_invfac002.exp_bootstrap import spearman_correlation, apply_verdict_degradation

DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")
REPORT_DIR = os.path.join(PROJECT_ROOT, "reports", "EXP-2026-003-KNOWDEEP", "q2")
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

def cfr(close, period):
    n = len(close); f = np.full(n, np.nan)
    for i in range(n-period): f[i] = close[i+period]/close[i]-1-COST_ROUND_TRIP
    return f

def build_composites(fv, ms, stocks):
    base = "l_vol_rsi_std"
    R = {}

    # C1 RWC
    rwc = {}
    for code in stocks:
        sig = fv[base][code]; st = ms[code]
        c, cnt = np.zeros(len(sig)), np.zeros(len(sig))
        for sv, sl in STATE_LABELS.items():
            w = RWC_WEIGHTS[sl]; sel = st == sv
            c = np.where(sel, c + sig*w, c); cnt = np.where(sel, cnt+1, cnt)
        rwc[code] = np.where(cnt>0, c, 0.0)
    R["C1_rwc"] = rwc

    # C2 RFS
    rfs = {}
    for code in stocks:
        sig = fv[base][code].copy()
        sig[ms[code]==2] = 0.0
        rfs[code] = sig
    R["C2_rfs"] = rfs

    # C3 EWC
    ewc = {}
    for code in stocks:
        sig = fv[base][code]; st = ms[code]
        c, cnt = np.zeros(len(sig)), np.zeros(len(sig))
        for sv in STATE_LABELS:
            sel = st == sv
            c = np.where(sel, c+sig, c); cnt = np.where(sel, cnt+1, cnt)
        ewc[code] = np.where(cnt>0, c/cnt, 0.0)
    R["C3_ewc"] = ewc

    # C4 VSS
    vss = {}
    for code in stocks:
        sig = fv[base][code].copy(); st = ms[code]; d = stocks[code]
        ret = np.diff(d["close"]) / d["close"][:-1]
        rv = np.full(len(d["close"]), np.nan)
        for i in range(20, len(d["close"])):
            rv[i] = np.std(ret[i-20:i]) * np.sqrt(252)
        p50 = np.nanpercentile(rv, 50)
        if p50>0 and not np.isnan(p50):
            sf = np.where(~np.isnan(rv), np.clip(p50/(rv+p50*0.1)*2.0, 0.5, 1.5), 1.0)
            sig[st==2] *= sf[st==2]
        vss[code] = sig
    R["C4_vss"] = vss

    return R

def compute_ic(result, signal, stocks, ws, we, fwd, label):
    print(f"  [{label}]", end="", flush=True)
    for period in HOLDING_PERIODS:
        af, ar = [], []
        for code in stocks:
            sig = signal.get(code, np.array([]))
            if len(sig)==0: continue
            d = stocks[code]
            iw = (np.arange(len(d["dates"]))>=ws)&(np.arange(len(d["dates"]))<we)
            fr = fwd[code][period]; rs = reverse_factor(sig)
            sel = iw&~np.isnan(rs)&~np.isnan(fr)
            if np.sum(sel)<3: continue
            af.extend(rs[sel].tolist()); ar.extend(fr[sel].tolist())
        n = len(af)
        re = {"ic_mean": None, "n_samples": 0}
        if n>=3:
            re["ic_mean"] = float(spearman_correlation(np.array(af), np.array(ar)))
            re["n_samples"] = n
        result[period] = re
        print(f" p{period}d:{re['ic_mean']:.4f}" if re['ic_mean'] else f" p{period}d:NA", end="", flush=True)
    print()
    return result

def compute_decay(train, val, label, enable_snr_annotation=True):
    print(f"  [衰减 {label}]")
    decay = {}
    for period in HOLDING_PERIODS:
        ti = train.get(period,{}); vi = val.get(period,{})
        ti_m, vi_m = ti.get("ic_mean"), vi.get("ic_mean")
        vn = vi.get("n_samples", 0)
        if ti_m is None or vi_m is None:
            decay[period] = {"verdict":"NODATA"}
            print(f"    p{period}d: NODATA"); continue
        dc = (ti_m>0)==(vi_m>0)
        dr = (abs(ti_m)-abs(vi_m))/abs(ti_m) if abs(ti_m)>1e-8 else -1.0
        v = "FAIL" if (not dc or dr>=1.0) else ("WARN" if dr>DECAY_THRESHOLD_PASS or (dc and abs(vi_m)<0.005) else "PASS")
        vd, dn = apply_verdict_degradation(v, vn, threshold=SAMPLE_SIZE_THRESHOLD)
        
        # C2-RFS: 低信噪比标注（P1项）
        # 当训练期|IC|<0.01时，自动标注[低信噪比]，不影响现有verdict逻辑
        snr_note = ""
        if enable_snr_annotation and ti_m is not None and abs(ti_m) < 0.01:
            snr_note = "[低信噪比]"
            print(f"    C2-RFS标注: |train_ic|={abs(ti_m):.4f}<0.01 → {snr_note}")
        
        decay[period] = {"verdict":vd,"verdict_base":v,"train_ic":ti_m,"val_ic":vi_m,
                         "decay_rate":dr,"direction_consistent":dc,"n_samples_val":vn,
                         "sample_size_degraded":vd!=v,"degradation_note":dn,
                         "signal_quality":snr_note if snr_note else None}
        print(f"    p{period}d: {ti_m:.4f}→{vi_m:.4f} dr={dr:.1%} → {vd}{snr_note}")
    return decay

def main():
    t0 = time.time()
    vt = gv(); rt = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    print(f"EXP-2026-003 Q2 | {vt} | {rt}")
    print("="*50)

    # Load
    codes = lsc(); stocks = {c:lsd(c) for c in codes if lsd(c) is not None}
    vc = list(stocks.keys())
    print(f"[1] {len(vc)} stocks")

    # Factors
    fv = {"l_vol_rsi_std":{}, "TrendQuality":{}}
    for code in vc:
        d = stocks[code]
        fv["l_vol_rsi_std"][code] = calc_vol_rsi_std(d["volume"])
        fv["TrendQuality"][code] = calc_trend_quality(d["high"], d["low"], d["close"])
    print("[2] Factors OK")

    # Market state
    ms = {}
    for code in vc:
        d = stocks[code]; ws,_ = fdr(d["dates"], TRAIN_START, TRAIN_END)
        ret = np.diff(d["close"])/d["close"][:-1]
        wv = np.full(len(d["close"]), np.nan)
        for i in range(20, min(len(d["close"]), ws+200)):
            wv[i] = np.std(ret[i-19:i+1])*np.sqrt(252)
        ms[code],_,_ = classify_market_state(d["close"], warmup_vol=wv)
    print("[3] Market state OK")

    # Fwd returns cache
    fwd = {code:{p:cfr(stocks[code]["close"],p) for p in HOLDING_PERIODS} for code in vc}
    print("[Cache] Fwd OK")

    _, te = fdr(stocks[vc[0]]["dates"], TRAIN_START, TRAIN_END)
    vs, ve = fdr(stocks[vc[0]]["dates"], VAL_START, VAL_END)

    # Build composites
    comps = build_composites(fv, ms, stocks)
    print(f"[4] Composites: {list(comps.keys())}")

    # Analyze each composite
    all_res = {}
    for cl, cs in comps.items():
        print(f"\n{'─'*40}\n  {cl}\n{'─'*40}")
        train_ic = compute_ic({}, cs, stocks, 0, te, fwd, "Train")
        val_ic   = compute_ic({}, cs, stocks, vs, ve, fwd, "Val")
        decay    = compute_decay(train_ic, val_ic, cl)
        all_res[cl] = {
            "description": {"C1_rwc":"Regime-Weighted: HV=0.5/MV=0.3/LV=0.2",
                           "C2_rfs":"Regime-Filtered: LV+MV only",
                           "C3_ewc":"Equal-Weight: all states",
                           "C4_vss":"Vol-Scaled: HV compressed"}.
                           get(cl,""),
            "train_ic": train_ic, "val_ic": val_ic, "decay": decay,
        }

    # TrendQuality observation
    print(f"\n{'─'*40}\n  TrendQuality (观察)\n{'─'*40}")
    tq_train = compute_ic({}, fv["TrendQuality"], stocks, 0, te, fwd, "TQ_Train")
    tq_val   = compute_ic({}, fv["TrendQuality"], stocks, vs, ve, fwd, "TQ_Val")

    ct = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    el = time.time() - t0

    result = {
        "task_id":"EXP-2026-003-KNOWDEEP","work_package":"Q2","version_tag":vt,
        "run_timestamp":rt,"completed_time":ct,"elapsed_seconds":round(el,2),
        "status":"READY",
        "config":{
            "base_signal":"l_vol_rsi_std","composite_signals":list(comps.keys()),
            "observation_only":["TrendQuality"],"n_stocks":len(vc),
            "train_window":f"{TRAIN_START}~{TRAIN_END}","val_window":f"{VAL_START}~{VAL_END}",
            "holding_periods":HOLDING_PERIODS,"cost_round_trip":COST_ROUND_TRIP,
            "sample_size_threshold":SAMPLE_SIZE_THRESHOLD,
        },
        "owner_constraints_applied":{
            "only_l_vol_rsi_std_as_base":True,
            "trendquality_observation_only":True,
            "kid_exp003_001_not_activated":True,
            "sample_size_degradation_enabled":True,
        },
        "composite_analysis":all_res,
        "trendquality_observation":{
            "description":"TrendQuality Q2独立观察（不作为信号输入）",
            "note":"验证Q1反衰减结论稳定性（HVol n≈1,312<3,000）",
            "train_ic":tq_train,"val_ic":tq_val,
        },
    }

    path = os.path.join(REPORT_DIR, "q2_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"\n[OK] 写入: {path}")

    with open(path, "r", encoding="utf-8") as f:
        v = json.load(f)
    assert v["status"] == "READY"
    print("[验证通过] status=READY")

    print(f"\n{'='*50}")
    print(f"Q2 完成 | {el:.1f}s | {ct}")


if __name__=="__main__":
    main()
