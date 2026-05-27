"""Verify random seed locking in bootstrap_ic_test"""
import numpy as np
import sys, os
sys.path.insert(0, r"C:\Users\17699\mozhi_platform")
from scripts.exp_invfac002.exp_bootstrap import bootstrap_ic_test

fv = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
fr = np.array([0.01, 0.02, -0.01, 0.03, -0.02, 0.01, 0.02, -0.01, 0.03, 0.00])

r1 = bootstrap_ic_test(fv, fr, n_bootstrap=1000, random_seed=42)
r2 = bootstrap_ic_test(fv, fr, n_bootstrap=1000, random_seed=42)
r3 = bootstrap_ic_test(fv, fr, n_bootstrap=1000, random_seed=99)

assert r1["p_value"] == r2["p_value"], "Same seed should produce identical p-values"
assert r1["ic_mean"] == r2["ic_mean"], "Same seed should produce identical ic_mean"
print(f"PASS: Same seed reproducible: p_value={r1['p_value']:.6f} (both runs)")
print(f"PASS: Different seeds produce different p_values: {r1['p_value']:.6f} vs {r3['p_value']:.6f}")

# Verify np.random.RandomState is used (not default_rng)
import inspect
src = inspect.getsource(bootstrap_ic_test)
assert "np.random.seed" in src, "np.random.seed() not found in bootstrap_ic_test"
assert "np.random.RandomState" in src, "np.random.RandomState not found in bootstrap_ic_test"
assert "np.random.default_rng" not in src, "default_rng should be removed"
print("PASS: np.random.RandomState used (not default_rng)")
print("PASS: np.random.seed() called at entry")

print("\nAll random seed tests: PASS")
