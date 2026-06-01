#!/usr/bin/env python3
"""
run_verify_pipeline.py — 验证管线编排脚本
================================================================
调用 pytest 运行对应模式的测试文件，解析 junitxml 结果文件判断通过情况。

模式：
  --mode=e2e       仅运行端到端样本验证（第一级）
  --mode=output    仅运行输出校验（第二级）
  --mode=full      串联运行两级（默认）

退出码：
  0 = 全部通过
  1 = 至少一个 WARN
  2 = 至少一个 FAIL

用法：
  python verify_golden/run_verify_pipeline.py --mode=full
  python verify_golden/run_verify_pipeline.py --mode=e2e
  python verify_golden/run_verify_pipeline.py --mode=output

Author: moheng
Created: 2026-06-01T16:21:00+08:00
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


# ─── Paths ───────────────────────────────────────────────────────────────
VERIFY_DIR = Path(__file__).resolve().parent
TESTS_DIR = VERIFY_DIR / "tests"


# ─── Mode definitions ────────────────────────────────────────────────────
MODE_MAP = {
    "e2e":    {"label": "端到端样本验证",     "file": "test_e2e_golden.py"},
    "output": {"label": "输出校验",           "file": "test_output_validation.py"},
}


# ===================================================================
# junitxml 解析 & 结果判定
# ===================================================================


def parse_junit_results(junit_path: str) -> dict:
    """解析 junitxml 文件，按 violation 严重等级分类。

    WARN 判定依据：failure message 中包含 ``[WARN]`` 标记。
    FAIL 判定依据：
      - failure message 中包含 ``[FAIL]`` 标记
      - 任何其他未标记的 failure（pytest 异常、assert 失败等）

    Returns:
        dict::
            {
                "passed": int,      # 通过的测试数
                "warn": int,        # 触发 WARN 的测试数
                "fail": int,        # 触发 FAIL 的测试数
                "skipped": int,     # 跳过的测试数
                "total": int,       # 总测试数
                "errors": int,      # 测试错误数（非断言类异常）
            }
    """
    if not os.path.isfile(junit_path):
        return {"passed": 0, "warn": 0, "fail": 0, "skipped": 0, "total": 1, "errors": 1}

    tree = ET.parse(junit_path)
    root = tree.getroot()

    passed = 0
    warn = 0
    fail = 0
    skipped = 0
    errors = 0
    total = 0
    error_details = []

    for testsuite in root.iter("testsuite"):
        total += int(testsuite.get("tests", 0))
        errors += int(testsuite.get("errors", 0))

    for testsuite in root.iter("testsuite"):
        for sk in testsuite.iter("skipped"):
            skipped += 1

    for testcase in root.iter("testcase"):
        failure = testcase.find("failure")
        err = testcase.find("error")
        skip = testcase.find("skipped")
        test_name = testcase.get("classname", "") + "::" + testcase.get("name", "")

        if skip is not None:
            continue

        if failure is not None:
            message = failure.get("message", "") or (failure.text or "")
            if "[FAIL]" in message:
                fail += 1
                error_details.append(f"{test_name} FAIL: {message.strip()}")
            elif "[WARN]" in message:
                warn += 1
                error_details.append(f"{test_name} WARN: {message.strip()}")
            else:
                # 未标记的 failure → 按 FAIL 处理（最严格）
                fail += 1
                error_details.append(f"{test_name} FAIL: {message.strip()}")
        elif err is not None:
            errors += 1
            error_details.append(f"{test_name} ERROR: {(err.get('message','') or err.text or '').strip()}")
        else:
            passed += 1

    return {
        "passed": passed,
        "warn": warn,
        "fail": fail,
        "skipped": skipped,
        "total": total,
        "errors": errors,
        "error_details": error_details,
    }


def aggregate_results(results: list) -> dict:
    """合并多个 junit 解析结果。

    Returns:
        dict: 同 parse_junit_results 格式，各字段累加。
    """
    agg = {"passed": 0, "warn": 0, "fail": 0, "skipped": 0, "total": 0, "errors": 0, "error_details": []}
    for r in results:
        for k in agg:
            if k == "error_details":
                agg[k].extend(r.get(k, []))
            else:
                agg[k] += r[k]
    return agg


def classify_exit_code(results_agg: dict) -> int:
    """根据聚合结果判定退出码。

    优先级：
      2 → 有 FAIL
      1 → 无 FAIL 但有 WARN
      0 → 全部通过（含跳过）

    注意：errors（pytest 异常）也按 FAIL 处理。
    """
    if results_agg["fail"] > 0 or results_agg["errors"] > 0:
        return 2
    if results_agg["warn"] > 0:
        return 1
    return 0


# ===================================================================
# 校验失败阻断信号
# ===================================================================


def _write_alert_signal(exit_code: int, agg: dict, mode: str) -> None:
    """根据退出码写入校验失败/警告信号文件。"""
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M+08:00")
    ts_safe = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")

    if exit_code >= 2:
        status = "FAIL"
        filename = f"verify_fail_{ts_safe}.json"
    elif exit_code == 1:
        status = "WARN"
        filename = f"verify_warn_{ts_safe}.json"
    else:
        return  # 全部通过，不写入

    signal = {
        "timestamp": timestamp,
        "mode": mode,
        "status": status,
        "exit_code": exit_code,
        "details": {
            "passed": agg.get("passed", 0),
            "failed": agg.get("fail", 0),
            "warn": agg.get("warn", 0),
            "errors": agg.get("error_details", []),
        },
    }

    alert_dir = VERIFY_DIR.parent / "signals" / "alert"
    alert_dir.mkdir(parents=True, exist_ok=True)

    signal_path = alert_dir / filename
    with open(signal_path, "w", encoding="utf-8") as f:
        json.dump(signal, f, ensure_ascii=False, indent=2)

    print(f"\n  [ALERT] 信号文件已写入: {signal_path}")
    print(f"  [ALERT] status={status}, exit_code={exit_code}")
    if status == "FAIL":
        print(f"  [ALERT] [BLOCK] 阻断信号已发送，下游流转终止")
    elif status == "WARN":
        print(f"  [ALERT] [WARN] 警告信号已记录，不阻断")


# ===================================================================
# 执行引擎
# ===================================================================


def run_pytest(test_file: str) -> tuple:
    """对单个测试文件执行 pytest，返回 (junit_path, returncode, output)。"""
    with tempfile.NamedTemporaryFile(
        suffix=".xml", prefix="verify_", delete=False, mode="w", newline=""
    ) as f:
        junit_path = f.name

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(TESTS_DIR / test_file),
        "-v",
        "--tb=short",
        f"--junitxml={junit_path}",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    return junit_path, result.returncode, result.stdout + result.stderr


def run_mode(mode: str) -> dict:
    """运行一个模式的测试，返回解析后的 junit 结果。"""
    info = MODE_MAP[mode]
    label = info["label"]
    test_file = info["file"]

    print(f"\n{'='*60}")
    print(f"  [{mode}] {label}")
    print(f"  文件: {test_file}")
    print(f"{'='*60}")

    junit_path, retcode, output = run_pytest(test_file)

    # 打印 pytest 输出
    for line in output.splitlines():
        if line.strip():
            print(f"  {line.strip()}")

    # 解析 junitxml
    results = parse_junit_results(junit_path)

    # 清理临时文件
    try:
        os.unlink(junit_path)
    except OSError:
        pass

    print(f"\n  ── 结果 ──")
    print(f"  passed: {results['passed']}, warn: {results['warn']}, "
          f"fail: {results['fail']}, skipped: {results['skipped']}, "
          f"errors: {results['errors']}")
    print(f"  pytest exit code: {retcode}")
    print()

    return results


# ===================================================================
# CLI
# ===================================================================


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="验证管线编排 — 调用 pytest 运行 WI4 golden 验证测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python verify_golden/run_verify_pipeline.py --mode=full\n"
            "  python verify_golden/run_verify_pipeline.py --mode=e2e\n"
            "  python verify_golden/run_verify_pipeline.py --mode=output\n"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["e2e", "output", "full"],
        default="full",
        help="验证模式（默认: full）",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.mode == "full":
        # 先 E2E 后 Output
        result_e2e = run_mode("e2e")
        result_output = run_mode("output")
        agg = aggregate_results([result_e2e, result_output])
    else:
        single = run_mode(args.mode)
        agg = single

    exit_code = classify_exit_code(agg)

    # ─── 校验失败阻断信号 ─────────────────────────────────────────
    _write_alert_signal(exit_code, agg, args.mode)

    # ─── 最终汇总 ────────────────────────────────────────────────
    print(f"{'='*60}")
    print(f"  管线验证汇总")
    print(f"{'='*60}")
    print(f"  模式:     {args.mode}")
    print(f"  passed:   {agg['passed']}")
    print(f"  warn:     {agg['warn']}")
    print(f"  fail:     {agg['fail']}")
    print(f"  skipped:  {agg['skipped']}")
    print(f"  errors:   {agg['errors']}")
    print(f"  总计:     {agg['total']}")

    if exit_code == 0:
        print(f"\n  [PASS] 全部通过 (exit 0)")
    elif exit_code == 1:
        print(f"\n  [WARN] 存在 WARN (exit 1)")
    else:
        print(f"\n  [FAIL] 存在 FAIL (exit 2)")

    print(f"{'='*60}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
