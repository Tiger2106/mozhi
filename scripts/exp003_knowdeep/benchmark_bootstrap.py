"""
EXP-003 Q1 Bootstrap 置换检验基准测试 + P2 自洽性验证
=======================================================
模拟实际数据规模（n=50000）测试 bootstrap_ic_test 性能。
"""
import sys, os, time, json, copy

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np

# 先导入原始版（优化前）
from scripts.exp_invfac002.exp_bootstrap import bootstrap_ic_test as bootstrap_original
from scripts.exp_invfac002.exp_bootstrap import spearman_correlation

# ── 模拟数据 ──
np.random.seed(42)
N = 50000
FACTOR_THETA = 0.03

factor_values = np.random.randn(N)
true_signal = FACTOR_THETA * factor_values
forward_returns = true_signal + np.random.randn(N) * 0.1
# 加入 5% NaN
nan_mask = np.random.random(N) < 0.05
factor_values[nan_mask] = np.nan
forward_returns[nan_mask] = np.nan

print("=" * 60)
print("EXP-003 Q1 Bootstrap 置换检验基准测试")
print(f"数据规模: N={N}")
print("=" * 60)

# ── 测试 1: 原始版计时 ──
print("\n[Test 1] 原始版 bootstrap_ic_test (n_bootstrap=10000)...")
t0 = time.time()
result_orig = bootstrap_original(
    factor_values, forward_returns,
    n_bootstrap=10000, alpha=0.05, random_seed=42,
)
elapsed_orig = time.time() - t0
print(f"  [TIMING] {elapsed_orig:.2f}s")
print(f"  IC_mean = {result_orig['ic_mean']:.10f}")
print(f"  p_value = {result_orig['p_value']:.10f}")
print(f"  significant = {result_orig['significant']}")

# ── 保存原始结果用于后续比较 ──
baseline = {
    "ic_mean": result_orig["ic_mean"],
    "p_value": result_orig["p_value"],
    "elapsed": elapsed_orig,
}

print(f"\n{'=' * 60}")
print(f"原始版完成: {elapsed_orig:.2f}s")
print(f"{'=' * 60}")

# 输出供后续使用的 JSON
print(f"\n[BASELINE]")
print(json.dumps(baseline, indent=2))
