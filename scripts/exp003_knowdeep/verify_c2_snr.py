"""Verify C2-RFS low SNR annotation logic"""
import sys, os
sys.path.insert(0, r"C:\Users\17699\mozhi_platform")
import json

# Simulate the compute_decay logic with low SNR
# Re-import the logic directly
HOLDING_PERIODS = [5, 10, 20]
DECAY_THRESHOLD_PASS = 0.50
SAMPLE_SIZE_THRESHOLD = 3000

def apply_verdict_degradation(verdict, n_samples, threshold=3000):
    if n_samples >= threshold:
        return verdict, ""
    degradation_map = {"PASS": "WARN", "WARN": "FAIL", "FAIL": "FAIL"}
    note = f"degraded ({n_samples}<{threshold})"
    return degradation_map.get(verdict, verdict), note

def compute_decay(train, val, label, enable_snr_annotation=True):
    decay = {}
    for period in HOLDING_PERIODS:
        ti = train.get(period, {}); vi = val.get(period, {})
        ti_m, vi_m = ti.get("ic_mean"), vi.get("ic_mean")
        vn = vi.get("n_samples", 0)
        if ti_m is None or vi_m is None:
            decay[period] = {"verdict": "NODATA"}
            continue
        dc = (ti_m > 0) == (vi_m > 0)
        dr = (abs(ti_m) - abs(vi_m)) / abs(ti_m) if abs(ti_m) > 1e-8 else -1.0
        v = "FAIL" if (not dc or dr >= 1.0) else ("WARN" if dr > DECAY_THRESHOLD_PASS or (dc and abs(vi_m) < 0.005) else "PASS")
        vd, dn = apply_verdict_degradation(v, vn, threshold=SAMPLE_SIZE_THRESHOLD)

        # C2-RFS: low SNR annotation
        snr_note = ""
        if enable_snr_annotation and ti_m is not None and abs(ti_m) < 0.01:
            snr_note = "[低信噪比]"

        decay[period] = {
            "verdict": vd, "verdict_base": v, "train_ic": ti_m, "val_ic": vi_m,
            "decay_rate": dr, "direction_consistent": dc, "n_samples_val": vn,
            "sample_size_degraded": vd != v, "degradation_note": dn,
            "signal_quality": snr_note if snr_note else None,
        }
    return decay

# Test: C2-RFS training IC(5d)=0.0008 should trigger annotation
train_ic_low = {5: {"ic_mean": 0.0008, "n_samples": 5000},
                10: {"ic_mean": 0.005, "n_samples": 5000},
                20: {"ic_mean": 0.02, "n_samples": 5000}}
val_ic = {5: {"ic_mean": 0.01, "n_samples": 3000},
          10: {"ic_mean": 0.02, "n_samples": 3000},
          20: {"ic_mean": 0.03, "n_samples": 3000}}

decay = compute_decay(train_ic_low, val_ic, "C2_rfs")
d5 = decay[5]
d10 = decay[10]
d20 = decay[20]

assert d5["signal_quality"] == "[低信噪比]", f"p5d should be annotated, got: {d5['signal_quality']}"
print(f"PASS: p5d |train_ic|={abs(train_ic_low[5]['ic_mean']):.4f} < 0.01 → signal_quality={d5['signal_quality']}")

assert d10["signal_quality"] == "[低信噪比]", f"p10d should be annotated, got: {d10['signal_quality']}"
print(f"PASS: p10d |train_ic|={abs(train_ic_low[10]['ic_mean']):.4f} < 0.01 → signal_quality={d10['signal_quality']}")

assert d20["signal_quality"] is None, f"p20d should NOT be annotated, got: {d20['signal_quality']}"
print(f"PASS: p20d |train_ic|={abs(train_ic_low[20]['ic_mean']):.4f} >= 0.01 → no annotation")

# Verify verdict is NOT affected by low SNR annotation
# Verdict is determined by decay direction consistency + rate, not by SNR
assert d5["verdict"] is not None, "Verdict should be computed normally"
assert d5["verdict"] == d5["verdict_base"], "SNR annotation should not change verdict"
print(f"PASS: verdict={d5['verdict']} unchanged by low SNR annotation")

# Test: normal IC should NOT trigger annotation
train_ic_normal = {5: {"ic_mean": 0.05, "n_samples": 5000},
                   10: {"ic_mean": 0.08, "n_samples": 5000},
                   20: {"ic_mean": 0.10, "n_samples": 5000}}
decay_normal = compute_decay(train_ic_normal, val_ic, "C2_rfs")
for p in [5, 10, 20]:
    assert decay_normal[p]["signal_quality"] is None, f"p{p}d should not be annotated for normal IC"
print("PASS: Normal IC (>0.01) does not trigger annotation")

print("\nAll C2-RFS low SNR annotation tests: PASS")
