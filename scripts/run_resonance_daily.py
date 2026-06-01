#!/usr/bin/env python3
"""
run_resonance_daily — 右侧交易共振系统每日例行运行脚本

用途：
  - 作为独立脚本被 daily_morning_run.py 调用
  - 也可独立执行（python run_resonance_daily.py）
  - 运行 601857.SH 的完整共振流水线
  - 输出 Markdown 信号报告

输出路径：
  {SHARED_REPORTS}/morning/{YYYYMMDD}/resonance_report_{YYYYMMDD}.md

设计原则：
  - 不改动 existing pipeline 模块（只加调用层）
  - 路径自解析，不依赖 cwd
  - 报告格式：Markdown + 关键数值 + 粗体信号摘要

依赖：
  - src.resonance.pipeline.PipelineOrchestrator
  - src.resonance.data_bridge

Author: moheng
Created: 2026-05-29T15:07:00+08:00
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# ── 本脚本绝对路径 ──
_SCRIPT_DIR = Path(__file__).resolve().parent          # scripts/
_PROJECT_ROOT = _SCRIPT_DIR.parent                    # mozhi_platform/

# ── 共享报告输出目录 ──
_SHARED_REPORTS = Path(r"C:\Users\17699\mo_zhi_sharereports\reports")

# ── 时区 ──
_CST_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

# ── 默认标的 ──
_DEFAULT_TICKER = "601857.SH"


def _now_cst() -> str:
    """当前 CST 时间，ISO8601 +08:00"""
    return datetime.now(_CST_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _today_str() -> str:
    """当日日期 YYYYMMDD"""
    return datetime.now(_CST_TZ).strftime("%Y%m%d")


# ══════════════════════════════════════════════════════════
# 导入（延迟导入：允许脚本被 import 而不阻塞）
# ══════════════════════════════════════════════════════════

def _import_pipeline():
    """延迟导入 resonance pipeline，确保项目根在 sys.path 中。"""
    root_str = str(_PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from src.resonance.pipeline import PipelineOrchestrator
    from src.resonance.pipeline import run_pipeline as _run_pipeline_func
    from src.resonance.models import (
        ModuleStatus,
        RSMState,
        ResonanceSignal,
    )
    from src.resonance.scl import consume as scl_consume
    from src.resonance.dsv import DSVResult
    return {
        "PipelineOrchestrator": PipelineOrchestrator,
        "run_pipeline": _run_pipeline_func,
        "ModuleStatus": ModuleStatus,
        "RSMState": RSMState,
        "ResonanceSignal": ResonanceSignal,
        "scl_consume": scl_consume,
        "DSVResult": DSVResult,
    }


# ══════════════════════════════════════════════════════════
# 报告生成
# ══════════════════════════════════════════════════════════

def _fmt_val(v: Any, decimals: int = 4) -> str:
    """格式化数值：None → N/A，float → 保留 decimals 位小数。"""
    if v is None:
        return "N/A"
    if isinstance(v, (int, float)):
        return f"{v:.{decimals}f}"
    return str(v)


def _signal_marker(sg_signal: Optional[str]) -> str:
    """信号类型 → 标记符号（避免 emoji 在 GBK 终端乱码）。"""
    if sg_signal == "BUY":
        return "[BUY]"
    elif sg_signal == "SELL":
        return "[SELL]"
    elif sg_signal in ("CONDITIONAL_BUY", "CONDITIONAL_SELL"):
        return "[COND]"
    return "[HOLD]"


def _build_markdown_report(
    ticker: str,
    date: str,
    pipeline_status: str,
    errors: list,
    warnings: list,
    execution_time_ms: float,
    modules: Dict[str, Any],
    signal: Optional[Dict[str, Any]],
) -> str:
    """构建 Markdown 信号报告。

    Args:
        ticker: 标的代码。
        date: 执行日期 YYYYMMDD。
        pipeline_status: 流水线整体状态。
        errors: 错误列表。
        warnings: 警告列表。
        execution_time_ms: 执行时间（毫秒）。
        modules: 各模块状态字典。
        signal: 信号摘要字典。

    Returns:
        完整的 Markdown 报告字符串。
    """
    sg_signal = (signal or {}).get("sg_signal")
    bold_signal = f"**{sg_signal}**" if sg_signal else "*无信号*"
    marker = _signal_marker(sg_signal)

    lines = []
    lines.append(f"# 右侧交易共振报告 {marker}")
    lines.append("")
    lines.append(f"**标的**: {ticker}  |  **日期**: {date}  |  **生成时间**: {_now_cst()}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 信号摘要")
    lines.append("")
    lines.append(f"- **整体状态**: `{pipeline_status}`")
    lines.append(f"- **信号**: {bold_signal}")
    if signal:
        sig = signal
        lines.append(f"- **信号强度**: {_fmt_val(sig.get('rsm_strength'), 4)}")
        lines.append(f"- **CPE 综合评分**: {_fmt_val(sig.get('cpe_score'), 4)}")
        lines.append(f"- **仓位上限**: {_fmt_val(sig.get('position_cap', 1.0), 2)}")
        if sig.get("reason"):
            lines.append(f"- **理由**: {sig['reason']}")
        if sig.get("suggested_price"):
            lines.append(f"- **建议价格**: {_fmt_val(sig['suggested_price'], 2)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 模块执行状态")
    lines.append("")
    lines.append("| 模块 | 状态 | 关键数值 |")
    lines.append("|:---:|:---:|:---|")

    module_rows = [
        ("DataBridge", modules.get("data_bridge_status"), _fmt_val(modules.get("data_rows"))),
        ("DCM", modules.get("dcm_status"), f"波动率={_fmt_val(modules.get('dcm_volatility'))}"),
        ("LQM", modules.get("lqm_status"), f"流动性评分={_fmt_val(modules.get('lqm_score'))}"),
        ("ZNM", modules.get("znm_status"), f"z-score={_fmt_val(modules.get('znm_zscore'))}"),
        ("RSM", modules.get("rsm_status"), f"状态={modules.get('rsm_state','N/A')} | 强度={_fmt_val(modules.get('rsm_strength'))}"),
        ("DSV", modules.get("dsv_status"), f"通过={modules.get('dsv_passed','N/A')} | 偏离度={_fmt_val(modules.get('dsv_divergence'))}"),
        ("GKV", modules.get("gkv_status"), f"闸门开放={modules.get('gkv_gate_open','N/A')} | 通过={modules.get('gkv_passed','N/A')}"),
        ("CPE", modules.get("cpe_status"), f"评分={_fmt_val(modules.get('cpe_score'))} | 裁决={_fmt_val(modules.get('cpe_verdict'))}"),
        ("SG", modules.get("sg_status"), f"信号={bold_signal} | 强度={_fmt_val(modules.get('sg_strength'))}"),
        ("SCL", modules.get("scl_status"), f"操作={modules.get('scl_action','N/A')}"),
    ]

    for name, status, detail in module_rows:
        status_str = status if status else "N/A"
        lines.append(f"| {name} | {status_str} | {detail} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    if errors:
        lines.append("## ⚠️ 错误")
        lines.append("")
        for i, err in enumerate(errors, 1):
            lines.append(f"{i}. {err}")
        lines.append("")

    if warnings:
        lines.append("## ⚠️ 警告")
        lines.append("")
        for i, warn in enumerate(warnings, 1):
            lines.append(f"{i}. {warn}")
        lines.append("")

    lines.append("## 执行信息")
    lines.append("")
    lines.append(f"- **执行耗时**: {execution_time_ms:.1f} ms")
    lines.append(f"- **流水线版本**: 0.3.0")
    lines.append(f"- **作者**: moheng")
    lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 主执行函数
# ══════════════════════════════════════════════════════════

def run_resonance_daily(
    ticker: str = _DEFAULT_TICKER,
    date: Optional[str] = None,
    output_dir: Optional[Path] = None,
    persist_signals: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """执行共振流水线并输出信号报告。

    Args:
        ticker: 标的代码（默认 "601857.SH"）。
        date: 执行日期 YYYYMMDD（默认当日）。
        output_dir: 报告输出目录（默认自动计算）。
        persist_signals: 是否持久化信号文件。
        verbose: 详细日志输出。

    Returns:
        {
            "status": "SUCCESS" | "FAILED",
            "report_path": str | None,
            "pipeline_status": str,
            "summary": dict,
        }
    """
    resolved_date = date or _today_str()

    # ── 解析输出路径 ──
    if output_dir is None:
        output_dir = _SHARED_REPORTS / "morning" / resolved_date
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"resonance_report_{resolved_date}.md"

    # ── 导入 pipeline ──
    try:
        mods = _import_pipeline()
    except Exception as e:
        result = {
            "status": "FAILED",
            "report_path": None,
            "pipeline_status": "IMPORT_FAILED",
            "summary": {},
            "error": str(e),
        }
        print(json.dumps(result, ensure_ascii=False))
        return result

    PipelineOrchestrator = mods["PipelineOrchestrator"]
    ModuleStatus = mods["ModuleStatus"]

    # ── 运行 pipeline ──
    orch = PipelineOrchestrator(verbose=verbose)
    t_start = time.time()

    try:
        results = orch.run_once(
            tickers=[ticker],
            date=resolved_date,
            persist_signals=persist_signals,
        )
    except Exception as e:
        result = {
            "status": "FAILED",
            "report_path": None,
            "pipeline_status": "PIPELINE_ERROR",
            "summary": {},
            "error": str(e),
        }
        print(json.dumps(result, ensure_ascii=False))
        return result

    execution_time_ms = (time.time() - t_start) * 1000

    # ── 提取结果 ──
    pipeline_result = results.get(ticker)
    if pipeline_result is None:
        result = {
            "status": "FAILED",
            "report_path": None,
            "pipeline_status": "NO_RESULT",
            "summary": {},
            "error": f"pipeline 未返回 {ticker} 的结果",
        }
        print(json.dumps(result, ensure_ascii=False))
        return result

    summary = pipeline_result.to_summary()

    # ── 各模块关键数值 ──
    modules: Dict[str, Any] = {}

    # DataBridge
    if pipeline_result.data_bridge_result is not None:
        df = pipeline_result.data_bridge_result
        modules["data_bridge_status"] = "PASS"
        modules["data_rows"] = len(df)
    else:
        modules["data_bridge_status"] = "FAILED"
        modules["data_rows"] = 0

    # DCM
    if pipeline_result.dcm_result:
        d = pipeline_result.dcm_result
        modules["dcm_status"] = d.status.value if hasattr(d.status, "value") else str(d.status)
        modules["dcm_volatility"] = float(d.volatility) if hasattr(d, "volatility") else None
    else:
        modules["dcm_status"] = None

    # LQM
    if pipeline_result.lqm_result:
        d = pipeline_result.lqm_result
        modules["lqm_status"] = d.status.value if hasattr(d.status, "value") else str(d.status)
        modules["lqm_score"] = float(d.liquidity_score) if hasattr(d, "liquidity_score") else None
    else:
        modules["lqm_status"] = None

    # ZNM
    if pipeline_result.znm_result:
        d = pipeline_result.znm_result
        modules["znm_status"] = d.status.value if hasattr(d.status, "value") else str(d.status)
        modules["znm_zscore"] = float(d.zscore) if hasattr(d, "zscore") else None
    else:
        modules["znm_status"] = None

    # RSM
    modules["rsm_status"] = summary.get("rsm_state", None)
    modules["rsm_state"] = summary.get("rsm_state", None)
    modules["rsm_strength"] = summary.get("rsm_strength", None)

    # DSV
    if pipeline_result.dsv_result:
        d = pipeline_result.dsv_result
        modules["dsv_status"] = d.status.value if hasattr(d.status, "value") else str(d.status)
        modules["dsv_passed"] = str(d.passed) if hasattr(d, "passed") else "N/A"
        modules["dsv_divergence"] = float(d.divergence) if hasattr(d, "divergence") else None
    else:
        modules["dsv_status"] = summary.get("dsv_passed", None)

    # GKV
    if pipeline_result.gkv_result:
        d = pipeline_result.gkv_result
        modules["gkv_status"] = d.status.value if hasattr(d.status, "value") else str(d.status)
        modules["gkv_passed"] = str(d.passed) if hasattr(d, "passed") else "N/A"
        modules["gkv_gate_open"] = str(d.gate_open) if hasattr(d, "gate_open") else "N/A"
    else:
        modules["gkv_status"] = None

    # CPE
    if pipeline_result.cpe_result:
        d = pipeline_result.cpe_result
        modules["cpe_status"] = d.status.value if hasattr(d.status, "value") else str(d.status)
        modules["cpe_score"] = float(d.score) if hasattr(d, "score") else None
        modules["cpe_verdict"] = str(d.verdict) if hasattr(d, "verdict") else None
    else:
        modules["cpe_status"] = None
        modules["cpe_score"] = summary.get("cpe_score", None)

    # SG
    if pipeline_result.sg_result:
        d = pipeline_result.sg_result
        modules["sg_status"] = d.status.value if hasattr(d.status, "value") else str(d.status)
        modules["sg_signal_type"] = str(d.signal_type) if hasattr(d, "signal_type") else None
        modules["sg_strength"] = str(d.signal_strength) if hasattr(d, "signal_strength") else None
    else:
        modules["sg_status"] = summary.get("sg_signal", None)
        modules["sg_signal_type"] = summary.get("sg_signal", None)

    # SCL
    if pipeline_result.scl_result:
        d = pipeline_result.scl_result
        modules["scl_status"] = d.get("status", "N/A") if isinstance(d, dict) else "PASS"
        modules["scl_action"] = d.get("action", "N/A") if isinstance(d, dict) else "N/A"
    else:
        modules["scl_status"] = None

    # ── 信号摘要 ──
    signal_info = {
        "sg_signal": summary.get("sg_signal", None),
        "rsm_strength": summary.get("rsm_strength", None),
        "cpe_score": summary.get("cpe_score", None),
        "position_cap": None,
        "reason": None,
        "suggested_price": None,
    }
    if pipeline_result.sg_result and hasattr(pipeline_result.sg_result, "reason"):
        signal_info["reason"] = pipeline_result.sg_result.reason

    # ── 生成报告 ──
    report = _build_markdown_report(
        ticker=ticker,
        date=resolved_date,
        pipeline_status=pipeline_result.status,
        errors=pipeline_result.errors,
        warnings=pipeline_result.warnings,
        execution_time_ms=execution_time_ms,
        modules=modules,
        signal=signal_info,
    )

    report_path.write_text(report, encoding="utf-8")

    # ── 写入验证 ──
    if not report_path.exists():
        # 重试一次
        report_path.write_text(report, encoding="utf-8")
    assert report_path.exists(), f"报告写入失败: {report_path}"

    # ── 构造返回 ──
    result = {
        "status": "SUCCESS",
        "report_path": str(report_path),
        "pipeline_status": pipeline_result.status,
        "summary": summary,
    }

    # 输出 JSON 行供调用方解析
    print(json.dumps(result, ensure_ascii=False))
    return result


# ══════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════

def main():
    """CLI 入口，支持参数覆盖。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="右侧交易共振系统每日运行脚本",
    )
    parser.add_argument(
        "--ticker", type=str, default=_DEFAULT_TICKER,
        help=f"标的代码 (默认: {_DEFAULT_TICKER})",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="执行日期 YYYYMMDD (默认: 当日)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="详细日志输出",
    )
    parser.add_argument(
        "--no-persist", action="store_true",
        help="不持久化信号文件",
    )

    args = parser.parse_args()

    result = run_resonance_daily(
        ticker=args.ticker,
        date=args.date,
        persist_signals=not args.no_persist,
        verbose=args.verbose,
    )

    if result["status"] == "SUCCESS":
        print(f"\n[OK] 共振报告已生成: {result['report_path']}")
        sys.exit(0)
    else:
        print(f"\n[FAIL] 共振流水线执行失败: {result.get('error', 'unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
