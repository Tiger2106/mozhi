"""Debug: cross-validate test with imported _make_input"""
import importlib, sys

for mod_name in list(sys.modules.keys()):
    if "ingest" in mod_name or "test_ingest" in mod_name:
        del sys.modules[mod_name]

sys.path.insert(0, "src/backtest/analysis/ingest/tests")

from test_ingest_analysis import _make_input, _make_perf_row
from src.backtest.analysis.ingest.validator import Validator

pi = _make_input(run_id="r1", n_core=1)
v = Validator(":memory:")
pr = _make_perf_row(total_return=12.5)
mc = pi.metrics_core[0]

print("MetricsCore fields:")
for k, val in vars(mc).items():
    if val is not None:
        print(f"  {k} = {val}")

print("\nCross-validate check:")
for pk, an in v.CROSS_FIELDS:
    pv = pr.get(pk)
    iv = getattr(mc, an, "NOT_FOUND")
    print(f"  {pk} -> {an}: perf={pv}, input={iv}")

cr = v._check_cross_validate(pi, pr)
print(f"\nResult: level={cr.level}, detail={cr.detail}")
print(f"expected PASS but got {cr.level}")
