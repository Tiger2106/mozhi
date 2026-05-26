#!/usr/bin/env python3
"""
R1 统⼀测试运行器 — 运行全部 Phase 1-3 测试用例

测试分组:
  - unit: ⼦模块单元测试
  - integration: 模块间集成测试
  - e2e: 端到端整链验证

输出: reports/research/{date}/r1_test_summary.json

作者: 墨衡 (moheng)
创建时间: 2026-05-18 (R1 阶段四)
"""

import json
import os
import sys
import time
import subprocess
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 项目根 ──────────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\17699\mozhi_platform")
sys.path.insert(0, str(PROJECT_ROOT))

TZ = timezone(timedelta(hours=8))

# ── 测试分组定义 ────────────────────────────────────────────
# Phase 1 测试：因子基础设施
PHASE1_UNIT_TESTS = [
    "src/backtest/tests/test_backtest_engine.py",
    "src/backtest/tests/test_benchmark.py",
    "src/backtest/tests/test_benchmark_data_source.py",
    "src/backtest/tests/test_data_filler.py",
    "src/backtest/tests/test_data_loader.py",
    "src/backtest/tests/test_data_source.py",
    "src/backtest/tests/test_data_source_cache.py",
    "src/backtest/tests/test_date_aligner.py",
    "src/backtest/tests/test_fetch_daily_sina_fallback.py",
    "src/backtest/tests/test_fee_model.py",
    "src/backtest/tests/test_fifo_cost.py",
    "src/backtest/tests/test_order_executor.py",
    "src/backtest/tests/test_performance.py",
    "src/backtest/tests/test_performance_baseline.py",
    "src/backtest/tests/test_signal_bridge.py",
    "src/backtest/tests/test_slippage_model.py",
    "src/backtest/tests/test_base_factor.py",
    "src/backtest/tests/test_runner.py",
    "src/backtest/tests/test_runner_integration.py",
    "src/backtest/tests/test_context.py",
    "src/backtest/tests/test_trend_backtest.py",
    "src/backtest/tests/test_trend_signal.py",
    "src/backtest/tests/test_reversal_signal.py",
]

PHASE1_INTEGRATION_TESTS = [
    "src/backtest/tests/test_integration.py",
    "src/backtest/tests/test_trend_position.py",
    "src/backtest/tests/test_grid_position.py",
    "src/backtest/tests/test_grid_strategy.py",
    "src/backtest/tests/test_run_grid_benchmark.py",
]

# Phase 2 测试：方法/信号
PHASE2_UNIT_TESTS = [
    "src/backtest/tests/test_bias_method.py",
    "src/backtest/tests/test_bollinger_method.py",
    "src/backtest/tests/test_grid_method.py",
    "src/backtest/tests/test_kdj_method.py",
    "src/backtest/tests/test_ma_cross_method.py",
    "src/backtest/tests/test_macd_method.py",
    "src/backtest/tests/test_method_comparison.py",
    "src/backtest/tests/test_method_manifest.py",
    "src/backtest/tests/test_method_meta_all.py",
    "src/backtest/tests/test_method_result.py",
    "src/backtest/tests/test_reversal_method.py",
    "src/backtest/tests/test_rsi_method.py",
    "src/backtest/tests/test_volume_profile_method.py",
    "src/backtest/tests/test_wyckoff_method.py",
]

PHASE2_INTEGRATION_TESTS = [
    "src/backtest/tests/test_r1_phase2_quick.py",
    "src/backtest/tests/test_r1_phase2_v2.py",
]

# Phase 3 测试：融合信号/归因/知识
PHASE3_UNIT_TESTS = [
    "src/backtest/tests/test_backtest_result_bundle.py",
    "src/backtest/tests/test_report_builder.py",
    "src/backtest/tests/test_generate_comparison_bh.py",
]

PHASE3_INTEGRATION_TESTS = [
    "src/backtest/tests/test_knowledge_analyzer.py",
    "src/backtest/tests/test_knowledge_bridge.py",
    "src/backtest/tests/test_knowledge_bridge_v2.py",
    "src/backtest/tests/test_knowledge_normalizer.py",
    "src/backtest/tests/test_knowledge_search.py",
    "src/backtest/tests/test_bitable_sync.py",
    "src/backtest/tests/test_phase4_integration.py",
]

# Phase 4 E2E 验证脚本（独立运行）
PHASE_E2E_SCRIPTS = [
    "scripts/e2e_phase1_validation.py",
    "scripts/e2e_phase3_validation.py",
]

# 汇总所有测试（含重复去重）
_all_tests = list(set(
    PHASE1_UNIT_TESTS + PHASE1_INTEGRATION_TESTS +
    PHASE2_UNIT_TESTS + PHASE2_INTEGRATION_TESTS +
    PHASE3_UNIT_TESTS + PHASE3_INTEGRATION_TESTS
))

# 测试名称 → 分组映射
TEST_GROUP_MAP: Dict[str, List[str]] = {}
for t in PHASE1_UNIT_TESTS + PHASE2_UNIT_TESTS + PHASE3_UNIT_TESTS:
    TEST_GROUP_MAP.setdefault("unit", []).append(t)
for t in PHASE1_INTEGRATION_TESTS + PHASE2_INTEGRATION_TESTS + PHASE3_INTEGRATION_TESTS:
    TEST_GROUP_MAP.setdefault("integration", []).append(t)
for t in PHASE_E2E_SCRIPTS:
    TEST_GROUP_MAP.setdefault("e2e", []).append(t)

# Phase 映射
TEST_PHASE_MAP: Dict[int, List[str]] = {
    1: PHASE1_UNIT_TESTS + PHASE1_INTEGRATION_TESTS,
    2: PHASE2_UNIT_TESTS + PHASE2_INTEGRATION_TESTS,
    3: PHASE3_UNIT_TESTS + PHASE3_INTEGRATION_TESTS,
}

# 模块覆盖率统计
MODULE_CATEGORIES = {
    "backtest.engine": [
        "src/backtest/engine/*.py",
        "src/backtest/backtest*.py",
    ],
    "backtest.factors": ["src/backtest/factors/**/*.py"],
    "backtest.methods": ["src/backtest/methods/**/*.py"],
    "backtest.signals": ["src/backtest/signals/*.py"],
    "backtest.factors.factor_registry": ["src/backtest/factors/factor_registry.py"],
    "backtest.simulator": ["src/backtest/simulator/*.py"],
    "backtest.analysis": ["src/backtest/analysis/*.py"],
    "backtest.models": ["src/backtest/models/*.py"],
    "backtest.regime": ["src/backtest/regime/*.py"],
    "backtest.data": ["src/backtest/data/*.py"],
    "backtest.portfolio": ["src/backtest/portfolio/*.py"],
    "backtest.pipeline": ["src/backtest/pipeline/*.py"],
    "backtest.adapter": ["src/backtest/adapter/*.py"],
    "backtest.runners": ["src/backtest/runners/*.py"],
    "backtest.reports": ["src/backtest/reports/*.py"],
    "backtest.events": ["src/backtest/events/*.py"],
    "backtest.strategies": ["src/backtest/strategies/*.py"],
}


def get_test_file_list(tests: List[str]) -> List[str]:
    """将相对路径转换为绝对路径"""
    return [str(PROJECT_ROOT / t.replace("/", "\\")) if "/" in t else str(PROJECT_ROOT / t)
            for t in tests]


def run_pytest(test_files: List[str], label: str) -> Dict[str, Any]:
    """运行 pytest 并返回结果"""
    if not test_files:
        return {"label": label, "exit_code": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}

    abs_paths = get_test_file_list(test_files)
    result = {
        "label": label,
        "test_count": len(test_files),
        "exit_code": -1,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 0.0,
    }

    print(f"\n{'='*60}")
    print(f"[RUN] {label} ({len(test_files)} files)")
    print(f"{'='*60}")

    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest"] + abs_paths + [
                "-v", "--tb=short", "--no-header", "-q"
            ],
            capture_output=True, text=True, timeout=300,
            cwd=PROJECT_ROOT,
        )
        elapsed = time.time() - start
        result["duration_seconds"] = round(elapsed, 2)
        result["exit_code"] = proc.returncode

        # 解析输出统计
        stdout = proc.stdout
        stderr = proc.stderr

        # 记录最后几行输出
        lines = stdout.strip().split("\n")
        summary_lines = [l for l in lines
                        if any(x in l for x in ("passed", "failed", "error", "PASSED", "FAILED", "ERROR"))]

        # 尝试从 pytest 输出解析
        for line in lines:
            if "passed" in line and "failed" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "passed":
                        result["passed"] += int(parts[i-1]) if i > 0 else 0
                    elif p == "failed":
                        result["failed"] += int(parts[i-1]) if i > 0 else 0
                    elif p == "error":
                        result["errors"] += int(parts[i-1]) if i > 0 else 0
                    elif p == "skipped":
                        result["skipped"] += int(parts[i-1]) if i > 0 else 0

        result["stdout_summary"] = "\n".join(summary_lines[-20:])
        result["short_status"] = "PASS" if proc.returncode == 0 else "FAIL"

    except subprocess.TimeoutExpired:
        result["exit_code"] = -9
        result["short_status"] = "TIMEOUT"
        result["error"] = "Test execution timed out (300s)"
    except Exception as e:
        result["exit_code"] = -1
        result["short_status"] = "ERROR"
        result["error"] = str(e)

    print(f"[DONE] {label}: {result['short_status']} ({result['duration_seconds']:.1f}s)")
    return result


def run_standalone_script(script_paths: List[str], label: str) -> Dict[str, Any]:
    """以独立 Python 脚本运行（非 pytest，e2e 专项）"""
    if not script_paths:
        return {"label": label, "exit_code": 0, "short_status": "PASS", "duration_seconds": 0, "test_count": 0}

    abs_paths = get_test_file_list(script_paths)
    result = {
        "label": label,
        "test_count": len(script_paths),
        "exit_code": -1,
        "duration_seconds": 0.0,
        "short_status": "FAIL",
    }

    print(f"\n{'='*60}")
    print(f"[RUN] {label} ({len(script_paths)} scripts)")
    print(f"{'='*60}")

    all_passed = True
    start = time.time()
    for script_path in abs_paths:
        script_name = Path(script_path).name
        print(f"  -> Running: {script_name}")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True, timeout=300,
                cwd=PROJECT_ROOT, env=env,
            )
            if proc.returncode != 0:
                all_passed = False
                result["error"] = f"{script_name} failed (rc={proc.returncode})"
                # 打印最后几行 stderr
                err_lines = (proc.stderr or "").strip().split("\n")
                print(f"    FAIL: {err_lines[-1] if err_lines else 'unknown'}")
            else:
                print(f"    PASS")
        except subprocess.TimeoutExpired:
            all_passed = False
            result["error"] = f"{script_name} timed out (300s)"
        except Exception as e:
            all_passed = False
            result["error"] = f"{script_name}: {e}"

    elapsed = time.time() - start
    result["duration_seconds"] = round(elapsed, 2)
    result["short_status"] = "PASS" if all_passed else "FAIL"

    print(f"[DONE] {label}: {result['short_status']} ({result['duration_seconds']:.1f}s)")
    return result


def get_coverage_notes() -> Dict[str, Any]:
    """统计测试覆盖的模块数量"""
    module_count = len(MODULE_CATEGORIES)
    return {
        "module_categories": module_count,
        "module_list": list(MODULE_CATEGORIES.keys()),
        "note": "覆盖率计数基于测试文件，实际覆盖率需运行 coverage run/pytest --cov",
    }


def main() -> int:
    """主入口"""
    today_str = date.today().strftime("%Y%m%d")
    print(f"R1 Unified Test Runner — {today_str}")
    print(f"Python: {sys.version}")
    print(f"Project root: {PROJECT_ROOT}")

    # ── 按分组运⾏测试 ──────────────────────────────────────
    results: Dict[str, Any] = {
        "report_type": "r1_test_summary",
        "date": today_str,
        "generated_at": datetime.now(TZ).isoformat(),
        "python_version": sys.version,
        "total_test_files": len(_all_tests),
        "by_group": {},
        "by_phase": {},
        "summary": {},
        "coverage_notes": get_coverage_notes(),
    }

    # 按分组运⾏
    for group_name, test_files in TEST_GROUP_MAP.items():
        if test_files:
            if group_name == "e2e":
                result = run_standalone_script(test_files, f"R1-{group_name}")
            else:
                result = run_pytest(test_files, f"R1-{group_name}")
            results["by_group"][group_name] = result

    # 按阶段运⾏
    for phase_num, test_files in TEST_PHASE_MAP.items():
        if test_files:
            result = run_pytest(test_files, f"R1-Phase{phase_num}")
            results["by_phase"][f"phase{phase_num}"] = result

    # ── 汇总 ──────────────────────────────────────────────
    total_passed = sum(
        r.get("passed", 0) for r in list(results["by_group"].values())
    )
    total_failed = sum(
        r.get("failed", 0) for r in list(results["by_group"].values())
    )
    total_groups_passed = sum(
        1 for r in results["by_group"].values() if r.get("short_status") == "PASS"
    )
    total_groups = len(results["by_group"])

    results["summary"] = {
        "total_test_files": len(_all_tests),
        "test_groups": total_groups,
        "groups_passed": total_groups_passed,
        "overall_status": "PASS" if total_groups_passed == total_groups else "FAIL",
        "annotated_tests_passed": total_passed,
        "annotated_tests_failed": total_failed,
        "coverage_module_count": get_coverage_notes()["module_categories"],
    }

    # ── 输出报告 ──────────────────────────────────────────
    report_dir = PROJECT_ROOT / "reports" / "research" / today_str
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "r1_test_summary.json"

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"R1 测试报告已生成: {report_path}")
    print(f"分组: {total_groups_passed}/{total_groups} 通过")
    print(f"状态: {results['summary']['overall_status']}")
    print(f"{'='*60}")

    return 0 if results["summary"]["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
