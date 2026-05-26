#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
evening_pipeline_runner.py — 晚间报告管线顺序执行器

在 19:50 cron 触发，顺序执行4个步骤：
  step1: pnl_daily_settle()   — PnL日结
  step2: strategy_winrate()   — 策略胜率统计
  step3: data_audit()         — 数据审计
  step4: daily_report()       — 运行日报生成

每步执行前检查上一步的 done 文件，不存在或 failed 则跳过后续并告警。
每步完成后写入自己的 done/failed 信号文件。
支持全部成功的最终状态报告。

使用方式：
  python evening_pipeline_runner.py                    # 完整管线执行（默认）
  python evening_pipeline_runner.py --dry-run           # 预览模式，只检查不执行
  python evening_pipeline_runner.py --step 2            # 从指定步骤开始（1-4）
  python evening_pipeline_runner.py --step 2 --dry-run  # 预览+指定起始步骤

作者: moheng | created_time: 2026-05-05 17:56 GMT+8
"""

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Any

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger(__name__)

TZ_CST = SHANGHAI_TZ
PROJECT_ROOT = Path(r"C:\Users\17699\mo_zhi_sharereports")
SIGNALS_DIR = PROJECT_ROOT / "signals" / "tasks"
AUTOMATION_DIR = PROJECT_ROOT / "automation_v2"
MONITORING_DIR = AUTOMATION_DIR / "monitoring"

# ── 导入步骤模块 ──
sys.path.insert(0, str(AUTOMATION_DIR))
sys.path.insert(0, str(MONITORING_DIR))

from settle_daily import run_settle, today_str as settle_today
from reporting.evening.strategy_winrate import get_closed_trades, compute_winrate_stats, build_winrate_report, today_str as wr_today, DB_PATH as WR_DB
from reporting.evening.data_audit import get_conn, audit_fund_flow_balance, audit_transaction_flow_match
from reporting.evening.data_audit import audit_timestamp_integrity, audit_position_transaction_consistency
from reporting.evening.data_audit import audit_pnl_consistency, build_audit_report
from reporting.evening.operational_daily import generate_operational_daily

AUTHOR = "moheng"
VERSION = "1.0"
PIPELINE_NAME = "evening_report"

STEP_NAMES = {
    1: "pnl_daily_settle",
    2: "strategy_winrate",
    3: "data_audit",
    4: "daily_report",
}

STEP_MODULES = {
    1: "settle_daily",
    2: "strategy_winrate",
    3: "data_audit",
    4: "operational_daily",
}

def now_str() -> str:
    return datetime.now(TZ_CST).isoformat()

def today_str() -> str:
    return datetime.now(TZ_CST).strftime("%Y-%m-%d")

def today_compact() -> str:
    return datetime.now(TZ_CST).strftime("%Y%m%d")

def done_path(step: int) -> Path:
    """获取步骤 done 文件路径"""
    return SIGNALS_DIR / f"{PIPELINE_NAME}_step{step}_{STEP_NAMES[step]}_moheng.done"

def failed_path(step: int) -> Path:
    """获取步骤 failed 文件路径"""
    return SIGNALS_DIR / f"{PIPELINE_NAME}_step{step}_{STEP_NAMES[step]}_moheng.failed"

def write_signal(filepath: Path, data: dict) -> bool:
    """写入信号文件并验证"""
    data["author"] = AUTHOR
    data["created_time"] = now_str()
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # 读回验证
        verify = filepath.read_text(encoding="utf-8")
        parsed = json.loads(verify)
        status = parsed.get("status", "")
        if status not in ("DONE", "FAILED"):
            logger.warning(f"写入验证警告: {filepath.name} status={status}")
        return True
    except Exception as e:
        logger.error(f"写入信号文件失败 {filepath}: {e}")
        return False

def set_step_done(step: int, summary: str, details: Optional[Dict] = None) -> bool:
    """标记步骤完成"""
    data = {
        "status": "DONE",
        "pipeline": PIPELINE_NAME,
        "step": step,
        "step_name": STEP_NAMES[step],
        "summary": summary,
    }
    if details:
        data["details"] = details
    return write_signal(done_path(step), data)

def set_step_failed(step: int, error: str, trace: Optional[str] = None) -> bool:
    """标记步骤失败"""
    data = {
        "status": "FAILED",
        "pipeline": PIPELINE_NAME,
        "step": step,
        "step_name": STEP_NAMES[step],
        "error": error,
    }
    if trace:
        data["traceback"] = trace[:2000]
    return write_signal(failed_path(step), data)

def check_previous_step_done(step: int) -> Optional[str]:
    """
    检查上一步的 done 文件状态。
    返回 None 表示正常，字符串表示失败原因（跳过用）。
    """
    if step == 1:
        return None  # 第一步没有前置依赖

    prev_step = step - 1
    dp = done_path(prev_step)
    fp = failed_path(prev_step)

    if not dp.exists():
        # 也没有 failed 文件 → 上一步完全未执行
        if fp.exists():
            return f"上一步 {prev_step}({STEP_NAMES[prev_step]}) 已标记 FAILED"
        return f"上一步 {prev_step}({STEP_NAMES[prev_step]}) 未执行（无 done/failed 文件）"

    try:
        content = json.loads(dp.read_text(encoding="utf-8"))
        status = content.get("status", "")
        if status != "DONE":
            return f"上一步 {prev_step}({STEP_NAMES[prev_step]}) 状态异常: {status}"
        return None
    except Exception as e:
        return f"上一步 {prev_step}({STEP_NAMES[prev_step]}) done 文件解析失败: {e}"

# ═══════════════════════════════════════════════
# 步骤执行函数
# ═══════════════════════════════════════════════

def run_step1_pnl_daily_settle(dry_run: bool = False) -> Dict[str, Any]:
    """Step1: PnL日结"""
    logger.info("=" * 50)
    logger.info("Step1: PnL日结 (pnl_daily_settle)")
    logger.info("=" * 50)

    try:
        date_str = settle_today()
        result = run_settle(date_str, dry_run=dry_run)

        if result.get("success"):
            summary = (
                f"PnL日结完成: total_pnl={result.get('total_pnl', 0.0):+.2f}, "
                f"trades={result.get('trade_count', 0)}"
            )
            logger.info(f"  ✅ {summary}")
            set_step_done(1, summary, {
                "total_pnl": result.get("total_pnl", 0.0),
                "realized_pnl": result.get("realized_pnl", 0.0),
                "unrealized_pnl": result.get("unrealized_pnl", 0.0),
                "trade_count": result.get("trade_count", 0),
                "date": date_str,
            })
            return {"passed": True, "result": result}
        else:
            error = result.get("error", "未知错误")
            logger.error(f"  ❌ PnL日结失败: {error}")
            set_step_failed(1, error)
            return {"passed": False, "error": error}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"  ❌ Step1 异常: {e}")
        set_step_failed(1, str(e), tb)
        return {"passed": False, "error": str(e)}

def run_step2_strategy_winrate(dry_run: bool = False) -> Dict[str, Any]:
    """Step2: 策略胜率统计"""
    logger.info("=" * 50)
    logger.info("Step2: 策略胜率统计 (strategy_winrate)")
    logger.info("=" * 50)

    try:
        trades = get_closed_trades(WR_DB)
        logger.info(f"  获取到 {len(trades)} 笔已完结交易")

        stats = compute_winrate_stats(trades)

        # 写入报告（dry_run时也写，读取模式而已）
        report_content = build_winrate_report(trades, stats)
        report_path = PROJECT_ROOT / "reports" / f"strategy_winrate_{wr_today()}.md"
        if not dry_run:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_content, encoding="utf-8")
            logger.info(f"  报告已写入: {report_path}")
        else:
            logger.info(f"  [dry-run] 跳过报告写入")

        summary = (
            f"胜率统计: win_rate={stats['win_rate']:.1f}%, "
            f"{stats['win_count']}/{stats['total_trades']}笔盈利"
        )
        logger.info(f"  ✅ {summary}")
        set_step_done(2, summary, {
            "total_trades": stats["total_trades"],
            "win_rate": stats["win_rate"],
            "total_pnl": stats["total_pnl"],
            "win_count": stats["win_count"],
            "loss_count": stats["loss_count"],
        })
        return {"passed": True, "result": stats}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"  ❌ Step2 异常: {e}")
        set_step_failed(2, str(e), tb)
        return {"passed": False, "error": str(e)}

def run_step3_data_audit(dry_run: bool = False) -> Dict[str, Any]:
    """Step3: 数据审计"""
    logger.info("=" * 50)
    logger.info("Step3: 数据审计 (data_audit)")
    logger.info("=" * 50)

    try:
        conn = get_conn()
        results = {}
        try:
            results["fund_flow"] = audit_fund_flow_balance(conn)
            results["transaction_flow"] = audit_transaction_flow_match(conn)
            results["timestamp"] = audit_timestamp_integrity(conn)
            results["position_consistency"] = audit_position_transaction_consistency(conn)
            results["pnl_consistency"] = audit_pnl_consistency(conn)
        finally:
            conn.close()

        # 生成报告
        report_content = build_audit_report(results)
        if not dry_run:
            report_path = PROJECT_ROOT / "reports" / "data_audit.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_content, encoding="utf-8")
            logger.info(f"  审计报告已写入: {report_path}")
        else:
            logger.info(f"  [dry-run] 跳过报告写入")

        all_pass = all(r.get("status") == "PASS" for r in results.values())
        total_issues = sum(len(r.get("issues", [])) for r in results.values())
        total_warnings = sum(len(r.get("warnings", [])) for r in results.values())

        status_summary = {}
        for name, r in results.items():
            status_summary[name] = r.get("status", "N/A")

        if all_pass:
            summary = f"数据审计全部通过（{len(results)}项）"
        else:
            summary = f"数据审计: {total_issues} issues, {total_warnings} warnings"

        logger.info(f"  {'✅' if all_pass else '⚠️'} 审计结果: {summary}")
        set_step_done(3, summary, {
            "all_pass": all_pass,
            "total_issues": total_issues,
            "total_warnings": total_warnings,
            "status_summary": status_summary,
        })
        return {"passed": all_pass, "result": results}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"  ❌ Step3 异常: {e}")
        set_step_failed(3, str(e), tb)
        return {"passed": False, "error": str(e)}

def run_step4_daily_report(dry_run: bool = False) -> Dict[str, Any]:
    """Step4: 运行日报生成"""
    logger.info("=" * 50)
    logger.info("Step4: 运行日报生成 (daily_report)")
    logger.info("=" * 50)

    try:
        result = generate_operational_daily(date_str=None)
        if result:
            summary = f"运行日报已生成: {result}"
            logger.info(f"  ✅ {summary}")
            set_step_done(4, summary, {
                "report_path": str(result),
            })
            return {"passed": True, "result": result}
        else:
            error = "运行日报生成失败（返回空）"
            logger.error(f"  ❌ {error}")
            set_step_failed(4, error)
            return {"passed": False, "error": error}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"  ❌ Step4 异常: {e}")
        set_step_failed(4, str(e), tb)
        return {"passed": False, "error": str(e)}

# ═══════════════════════════════════════════════
# 管线控制器
# ═══════════════════════════════════════════════

RUNNERS = {
    1: run_step1_pnl_daily_settle,
    2: run_step2_strategy_winrate,
    3: run_step3_data_audit,
    4: run_step4_daily_report,
}

def run_pipeline(start_step: int = 1, dry_run: bool = False) -> Dict[str, Any]:
    """
    执行晚间报告管线。

    Args:
        start_step: 起始步骤（1-4），用于断点续跑
        dry_run: 预览模式

    Returns:
        管线执行结果报告
    """
    pipeline_start = now_str()
    logger.info(f"\n{'#'*60}")
    logger.info(f"# 晚间报告管线启动 — {pipeline_start}")
    logger.info(f"# 起始步骤: {start_step}")
    logger.info(f"# 模式: {'DRY-RUN' if dry_run else '正式执行'}")
    logger.info(f"{'#'*60}\n")

    step_results: List[Dict[str, Any]] = []
    pipeline_passed = True
    skip_remaining = False

    for step in range(start_step, 5):
        if skip_remaining:
            logger.info(f"  ⏭️  跳过 Step{step}({STEP_NAMES[step]}) — 上游失败")
            step_results.append({
                "step": step,
                "name": STEP_NAMES[step],
                "executed": False,
                "passed": False,
                "reason": "上游步骤失败，跳过",
            })
            continue

        # 检查上一步 done
        prev_check = check_previous_step_done(step)
        if prev_check:
            logger.warning(f"  ⚠️  {prev_check}")
            if step == 1:
                pass  # step1 没有前置，忽略检查
            elif step == 4 and "FAILED" in prev_check:
                # Step3（数据审计）失败不阻断 Step4（运行日报）
                # 审计报告与日报功能独立
                logger.warning(f"  ⏩ Step3 审计失败，继续执行 Step4（日报仍有用）")
            else:
                # 上一步未完成，跳过后续
                pipeline_passed = False
                skip_remaining = True
                logger.error(f"  🛑 管线终止：{prev_check}")
                step_results.append({
                    "step": step,
                    "name": STEP_NAMES[step],
                    "executed": False,
                    "passed": False,
                    "reason": prev_check,
                })
                continue

        # 执行当前步骤
        logger.info(f"  ▶️  执行 Step{step}: {STEP_NAMES[step]}...")
        runner = RUNNERS[step]
        result = runner(dry_run=dry_run)

        step_results.append({
            "step": step,
            "name": STEP_NAMES[step],
            "executed": True,
            "passed": result.get("passed", False),
            "error": result.get("error"),
        })

        if not result.get("passed", False):
            pipeline_passed = False
            if step == 3:
                # Step3（数据审计）失败不阻断 Step4（运行日报）
                # 审计发现问题不代表日报不可用，两者功能独立
                logger.warning(f"  ⚠️ Step{step}({STEP_NAMES[step]}) 发现异常，继续执行 Step4")
            else:
                skip_remaining = True
                logger.error(f"  🛑 Step{step} 失败，管线终止")
        else:
            logger.info(f"  ✅ Step{step} 完成")

    # ── 最终状态报告 ──
    pipeline_end = now_str()
    passed_count = sum(1 for r in step_results if r["passed"])
    total_count = len(step_results)

    final_report = {
        "pipeline": PIPELINE_NAME,
        "status": "PASSED" if pipeline_passed else "FAILED",
        "start_time": pipeline_start,
        "end_time": pipeline_end,
        "start_step": start_step,
        "dry_run": dry_run,
        "steps": step_results,
        "passed_steps": passed_count,
        "total_steps": total_count,
        "summary": (
            f"晚间报告管线: {passed_count}/{total_count} 步骤通过"
            if pipeline_passed else
            f"晚间报告管线: 部分失败 ({passed_count}/{total_count})"
        ),
    }

    # 输出摘要
    logger.info(f"\n{'='*60}")
    logger.info(f"晚间报告管线执行完毕")
    logger.info(f"  状态: {'✅ PASSED' if pipeline_passed else '❌ FAILED'}")
    logger.info(f"  时间: {pipeline_start} → {pipeline_end}")
    logger.info(f"  通过: {passed_count}/{total_count}")
    for r in step_results:
        icon = "✅" if r["passed"] else ("⏭️" if not r.get("executed", True) else "❌")
        logger.info(f"  {icon} Step{r['step']}({r['name']}): "
                     f"{'通过' if r['passed'] else '失败'}"
                     f"{' (' + (r.get('reason') or r.get('error') or '') + ')' if not r['passed'] else ''}")
    logger.info(f"{'='*60}\n")

    return final_report

def main():
    parser = argparse.ArgumentParser(
        description="晚间报告管线顺序执行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python evening_pipeline_runner.py                   # 完整执行
  python evening_pipeline_runner.py --dry-run          # 预览模式
  python evening_pipeline_runner.py --step 2           # 从Step2开始
  python evening_pipeline_runner.py --verbose          # 详细日志
        """,
    )
    parser.add_argument("--step", type=int, default=1, choices=range(1, 5),
                        help="起始步骤 (1-4, 默认 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览模式，只检查不写报告")
    parser.add_argument("--verbose", action="store_true",
                        help="输出详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        final_report = run_pipeline(
            start_step=args.step,
            dry_run=args.dry_run,
        )

        # 打印 JSON 摘要到 stdout（供上层 cron/tool 解析）
        safe_report = {
            "pipeline": final_report["pipeline"],
            "status": final_report["status"],
            "step_results": [
                {"step": r["step"], "name": r["name"],
                 "executed": r.get("executed"),
                 "passed": r["passed"]}
                for r in final_report["steps"]
            ],
            "passed_count": final_report["passed_steps"],
            "total_count": final_report["total_steps"],
        }
        print(f"\n---PIPELINE_STATUS---")
        print(json.dumps(safe_report, indent=2))
        print(f"---END---")

        return 0 if final_report["status"] == "PASSED" else 1

    except KeyboardInterrupt:
        logger.warning("管线执行被用户中断")
        return 130
    except Exception as e:
        logger.error(f"管线执行异常: {e}")
        traceback.print_exc()
        return 2

if __name__ == "__main__":
    sys.exit(main())
