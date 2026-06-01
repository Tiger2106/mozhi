---
task_id: EXP-2026-002-INVFAC
step: 2_dryrun (code preparation + dry-run validation)
agent: moheng
author: 墨衡
created_time: 2026-05-26T11:06:00+08:00
---

## EXP-2026-002-INVFAC Step 2: Dry-Run Summary

### Changes Made

| Change | File | Reason |
|--------|------|--------|
| Added `300750` to STOCK_CODES | `run_exp_invfac002.py` L16 | QC Step 1 confirmed adj_factor (+81.2%, 2023-04-26) = stock split, legitimate |
| Updated `STABILITY_N_STOCKS = 12` | `run_exp_invfac002.py` L47 | 11 → 12 with 300750 added |
| Updated `STABILITY_MIN_AGREE_CROSS = 8` | `run_exp_invfac002.py` L48 | design spec §5.3: ≥8/12 for cross-sectional stability |
| Fixed warmup_vol calculation | `run_exp_invfac002.py` Step 3 | Previously raw returns → now rolling annualized vol (std × √252), same as `classify_market_state` internal calc |
| Fixed UnicodeEncodeError | `run_exp_invfac002.py` header | Added `sys.stdout/stderr = TextIOWrapper(encoding='utf-8')` for Windows GBK compat |
| Replaced emoji markers | `run_exp_invfac002.py` | `✅/❌` → `[OK]/[FAIL]` to avoid GBK crash |

### Dry-Run Verification

**① No crashes** ✅
- `--dry-run` architecture check: 15/15 core functions verified (no exceptions)
- Full pipeline execution (skip QC, skip sensitivity): completed through Step 5.3 without crashes after fixes
- Comprehensive validation test: 26/26 checks passed

**② Output files exist & non-empty** ✅
```
dryrun_results_002.json     3,689 B
exp_results.json            7,507 B
exp_summary.md              3,118 B
stability_results.json     16,881 B
sensitivity_analysis.json  47,196 B
```

**③ Key metrics in reasonable range** ✅
- IC values: all in [-0.15, 0.15] (TrendQuality: [-0.06, 0.15], l_vol_rsi_std: [-0.06, 0.07], l_str_kdj_k: [-0.06, 0.11]) ✓
- FDR BH: 17/27 tests passed (q<0.05), consistent with negative-IC factor hypothesis ✓
- Stability L3: 27/27 (100%) combinations passed (rolling window flip rates ≤1.3%, cross-sectional directional consistency met) ✓
- Market state distribution: 3 states present for all 12 stocks (no degenerate classification) ✓

### Bug Found & Fixed
**Critical: warmup_vol scale mismatch** — the warmup period was computing raw daily returns (~0.01–0.03) and passing them as volatility thresholds, but `classify_market_state` computes rolling annualized vol (~0.1–0.5). This caused 100% of observations to be classified as "high volatility". Fixed by computing rolling annualized volatility (`std × √252`) in the warmup period, matching the function's internal methodology.

### Stock Universe (12)
```json
['000001', '000333', '002415', '300750', '600030', '600036',
 '600276', '600436', '600519', '600887', '601318', '601857']
```

### Dry-Run Result
```
dry-run: checks [✅/✅/✅]
```
