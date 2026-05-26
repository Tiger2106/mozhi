"""
EXP-2026-INVFAC-002 Step 2: Quick stress test.
Runs the full pipeline with --skip-qc and --skip-sensitivity, captures output to file.
"""
import sys, os, subprocess, time

script = r"C:\Users\17699\mozhi_platform\scripts\exp_invfac002\run_exp_invfac002.py"
log_path = r"C:\Users\17699\mozhi_platform\scripts\exp_invfac002\dryrun_output.log"

start = time.time()
env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"

with open(log_path, "w", encoding="utf-8") as f:
    proc = subprocess.run(
        [sys.executable, "-u", script, "--skip-qc", "--skip-sensitivity"],
        capture_output=True, text=True, timeout=600,
        env=env,
    )
    f.write(proc.stdout)
    f.write(proc.stderr)

elapsed = time.time() - start
print(f"Elapsed: {elapsed:.1f}s")
print(f"Return code: {proc.returncode}")
print(f"Stdout: {len(proc.stdout)} chars")
print(f"Stderr: {len(proc.stderr)} chars")
print(f"Output written to: {log_path}")
