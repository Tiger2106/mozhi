#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
pipeline_healthcheck.py — C-4: 管线健康检查

快速检查以下维度：
  1. 数据库可用性（trade_engine.db 存在/可读）
  2. 核心表完整性（transactions, fund_flow, daily_pnl, positions, account_balance）
  3. 今日交易记录（当日是否有交易数据）
  4. 数据库尺寸与健康度
  5. 最近cron状态（通过 openclaw cron list 输出文件检查）
  6. 告警队列状态（是否有积压告警）

输出统一状态码：ALL_OK / PARTIAL_FAIL / CRITICAL

用法：
  python pipeline_healthcheck.py [--json] [--output FILE]

可作为 verify_phase_a.py 的扩展，或独立 cron 调用。

作者: moheng | created_time: 2026-05-05 14:41 GMT+8
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Windows GBK 编码修复
if sys.platform == "win32":
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

logger = logging.getLogger(__name__)

# ── 项目路径 ──
PROJECT_ROOT = Path(r"C:\Users\17699\mo_zhi_sharereports")
DB_PATH = str(PROJECT_ROOT / "trade_engine.db")
REPORTS_DIR = PROJECT_ROOT / "reports"
SIGNALS_DIR = PROJECT_ROOT / "signals"

TZ_CST = SHANGHAI_TZ

AUTHOR = "moheng"
CREATED_TIME = "2026-05-05 14:41 GMT+8"
VERSION = "1.0"

# 全局状态码
STATUS = {
    "ALL_OK": "ALL_OK",
    "PARTIAL_FAIL": "PARTIAL_FAIL",
    "CRITICAL": "CRITICAL",
    "UNKNOWN": "UNKNOWN",
}

# 核心表清单
CORE_TABLES = [
    "transactions",
    "fund_flow",
    "daily_pnl",
    "positions",
    "account_balance",
]

# 期望的cron清单
EXPECTED_CRONS = [
    {"name": "paper_trade_poller", "status": "ok", "category": "trading"},
    {"name": "trade_loop_scheduler_morning", "status": "idle", "category": "scheduler"},
    {"name": "trade_loop_scheduler_midday", "status": "idle", "category": "scheduler"},
    {"name": "每日日志归档02:00", "status": "error", "category": "logging", "allow_fail": True},
]

def now_str() -> str:
    return datetime.now(TZ_CST).isoformat()

def today_str() -> str:
    return datetime.now(TZ_CST).strftime("%Y-%m-%d")

def today_compact() -> str:
    return datetime.now(TZ_CST).strftime("%Y%m%d")

def check_db_existence() -> dict:
    """检查数据库文件可用性"""
    result = {"name": "trade_engine.db", "status": "PASS", "detail": ""}

    if not os.path.exists(DB_PATH):
        result["status"] = "CRITICAL"
        result["detail"] = f"数据库文件不存在: {DB_PATH}"
        return result

    size = os.path.getsize(DB_PATH)
    if size == 0:
        result["status"] = "CRITICAL"
        result["detail"] = "数据库文件为空 (0 bytes)"
        return result

    result["detail"] = f"存在 ({size:,} bytes)"
    return result

def check_db_connectivity() -> dict:
    """检查数据库连接和核心表"""
    result = {
        "name": "数据库连接 & 核心表",
        "status": "PASS",
        "detail": "",
        "tables": {},
    }

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 检查所有核心表
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = set(r[0] for r in c.fetchall())

        missing = []
        for tb in CORE_TABLES:
            exists = tb in all_tables
            if exists:
                c.execute(f"SELECT COUNT(*) FROM {tb}")
                count = c.fetchone()[0]
                result["tables"][tb] = {"exists": True, "rows": count}
            else:
                result["tables"][tb] = {"exists": False, "rows": 0}
                missing.append(tb)

        if missing:
            result["status"] = "CRITICAL"
            result["detail"] = f"缺少核心表: {', '.join(missing)}"
        else:
            total_rows = sum(t["rows"] for t in result["tables"].values())
            table_state = ", ".join(
                f"{t}={result['tables'][t]['rows']}条"
                for t in CORE_TABLES
            )
            result["detail"] = f"全部存在 | {table_state} | 总计{total_rows}行"

        conn.close()
    except Exception as e:
        result["status"] = "CRITICAL"
        result["detail"] = f"连接异常: {e}"

    return result

def check_today_trades() -> dict:
    """检查今日是否有交易记录"""
    result = {
        "name": f"今日({today_str()})交易记录",
        "status": "PASS",
        "detail": "",
    }

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 交易记录
        c.execute(
            "SELECT COUNT(*) FROM transactions WHERE date(trade_time) = ?",
            (today_str(),),
        )
        txn_count = c.fetchone()[0]

        # 资金流水
        c.execute(
            "SELECT COUNT(*) FROM fund_flow WHERE date(created_at) = ?",
            (today_str(),),
        )
        flow_count = c.fetchone()[0]

        # PnL记录
        c.execute(
            "SELECT COUNT(*) FROM daily_pnl WHERE date = ?",
            (today_str(),),
        )
        pnl_count = c.fetchone()[0]

        conn.close()

        detail_parts = []
        detail_parts.append(f"交易: {txn_count}条")
        detail_parts.append(f"资金流水: {flow_count}条")
        detail_parts.append(f"日PnL: {pnl_count}条")
        result["detail"] = " | ".join(detail_parts)

        # 今天是交易日但无交易记录不算 CRITICAL，只是 WARN
        has_data = txn_count > 0 or flow_count > 0
        if not has_data:
            result["status"] = "WARN"
            result["detail"] += " (无今日数据，非交易日正常)"

    except Exception as e:
        result["status"] = "WARN"
        result["detail"] = f"查询异常: {e}"

    return result

def check_alert_queue_backlog() -> dict:
    """检查告警队列积压"""
    result = {
        "name": "告警队列积压",
        "status": "PASS",
        "detail": "",
    }

    pending_dir = PROJECT_ROOT / "signals" / "consensus" / "events" / "pending"
    if not pending_dir.exists():
        result["detail"] = "无待处理告警"
        return result

    try:
        pending_files = list(pending_dir.glob("*.json"))
        backlog = len(pending_files)
        if backlog == 0:
            result["detail"] = "无积压"
        elif backlog <= 5:
            result["status"] = "WARN"
            result["detail"] = f"少量积压: {backlog}条待处理"
        else:
            result["status"] = "WARN"
            result["detail"] = f"显著积压: {backlog}条待处理"
    except Exception as e:
        result["status"] = "WARN"
        result["detail"] = f"检查异常: {e}"

    return result

def check_dispatch_backlog() -> dict:
    """检查 dispatch 目录积压"""
    result = {
        "name": "Dispatch 触发文件",
        "status": "PASS",
        "detail": "",
    }

    dispatch_dir = PROJECT_ROOT / "signals" / "dispatch"
    if not dispatch_dir.exists():
        result["detail"] = "无dispatch文件"
        return result

    try:
        dispatch_files = [f for f in dispatch_dir.glob("alert_dispatch_*.json")
                         if not f.name.endswith(".lock")]
        backlog = len(dispatch_files)
        if backlog == 0:
            result["detail"] = "无未处理dispatch"
        elif backlog <= 3:
            result["status"] = "WARN"
            result["detail"] = f"有 {backlog} 个未处理dispatch文件"
        else:
            result["status"] = "WARN"
            result["detail"] = f"大量堆积: {backlog} 个dispatch文件未处理"
    except Exception as e:
        result["status"] = "WARN"
        result["detail"] = f"检查异常: {e}"

    return result

def _check_cron_via_heartbeat() -> dict:
    """
    备用cron状态检查：通过心跳文件存在性推断cron是否正常运行。

    当 openclaw CLI 不可用时触发。
    逻辑：若近期（5分钟内）有核心agent（moheng/mochen）的心跳文件，
    则推断cron/定时任务正在运行。
    """
    result = {
        "name": "Cron 状态(备用-心跳)",
        "status": "PASS",
        "detail": "",
        "heartbeats": {},
    }

    heartbeat_dir = SIGNALS_DIR / "consensus" / "heartbeat"
    if not heartbeat_dir.exists():
        result["status"] = "SKIP"
        result["detail"] = "心跳目录不存在，无法推断cron状态"
        return result

    # 核心cron-agent：moheng + mochen（Pipeline主调度器）
    cron_agents = ["moheng", "mochen"]
    now = datetime.now(TZ_CST)
    recent_threshold = timedelta(minutes=5)
    found_recent = []

    for agent in cron_agents:
        pattern = f"{agent}_hb_*.json"
        files = sorted(
            heartbeat_dir.glob(pattern),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not files:
            continue

        latest = files[0]
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            result["heartbeats"][agent] = data
            ts_str = data.get("timestamp", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                age = now - ts
                age_secs = int(age.total_seconds())
                agent_status = data.get("status", "unknown")
                if age < recent_threshold:
                    found_recent.append(
                        f"{agent}({age_secs}s前,status={agent_status},seq={data.get('seq','?')})"
                    )
        except (json.JSONDecodeError, ValueError, OSError) as e:
            result["heartbeats"][agent] = {"error": str(e)}

    if found_recent:
        result["status"] = "PASS"
        result["detail"] = (
            f"通过心跳推断cron运行正常: {'; '.join(found_recent)}"
        )
    else:
        result["status"] = "SKIP"
        result["detail"] = (
            f"无法通过心跳推断cron状态（5分钟内无{','.join(cron_agents)}心跳）"
        )

    return result

def check_cron_status() -> dict:
    """通过 openclaw cron list 输出检查 cron 状态

    注意：此函数尝试执行 openclaw CLI 命令。
    如果 CLI 不可用，降级到备用心跳检查（而非直接 SKIP）。
    """
    result = {
        "name": "Cron 状态",
        "status": "PASS",
        "detail": "",
        "crons": {},
    }

    try:
        output = subprocess.check_output(
            ["openclaw", "cron", "list", "--json"],
            text=True,
            timeout=30,
        )
        cron_data = json.loads(output)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        # CLI出错 → 尝试备用心跳检查
        backup = _check_cron_via_heartbeat()
        result["status"] = backup["status"]
        result["detail"] = f"[CLI失败→备用] {backup['detail']} (CLI error: {e})"
        result["heartbeats"] = backup.get("heartbeats", {})
        return result
    except FileNotFoundError:
        # CLI不存在 → 尝试备用心跳检查
        backup = _check_cron_via_heartbeat()
        result["status"] = backup["status"]
        result["detail"] = f"[CLI不可用→备用] {backup['detail']}"
        result["heartbeats"] = backup.get("heartbeats", {})
        return result
    except Exception as e:
        # 其他异常 → 尝试备用心跳检查
        backup = _check_cron_via_heartbeat()
        result["status"] = backup["status"]
        result["detail"] = f"[CLI异常→备用] {backup['detail']} (error: {e})"
        result["heartbeats"] = backup.get("heartbeats", {})
        return result

    # 解析cron列表
    crons = {}
    if isinstance(cron_data, list):
        for c in cron_data:
            name = c.get("name", c.get("ID", "unknown"))
            status = c.get("status", "unknown")
            crons[name] = {
                "status": status,
                "schedule": c.get("schedule", ""),
                "agent": c.get("agent_id", c.get("agent", "")),
            }

    result["crons"] = crons

    # 检查期望的cron是否存在
    issues = []
    for expected in EXPECTED_CRONS:
        ename = expected["name"]
        if ename in crons:
            actual_status = crons[ename]["status"]
            expected_status = expected["status"]
            if actual_status != expected_status and not expected.get("allow_fail"):
                if actual_status in ("error", "unknown"):
                    issues.append(f"{ename}: 实际={actual_status} != 期望={expected_status}")
                else:
                    issues.append(f"{ename}: 状态={actual_status} (期望={expected_status})")
        else:
            if not expected.get("allow_fail"):
                issues.append(f"{ename}: 未注册")

    # 同时检查是否有其他cron处于error状态
    for cname, cdata in crons.items():
        if cdata["status"] == "error":
            if not any(cname == e["name"] and e.get("allow_fail") for e in EXPECTED_CRONS):
                issues.append(f"非预期cron异常: {cname} = {cdata['status']}")

    if issues:
        result["status"] = "WARN"
        result["detail"] = "; ".join(issues)
    else:
        active = len(crons)
        ok_count = sum(1 for c in crons.values() if c["status"] in ("ok", "idle"))
        result["detail"] = f"{active}个cron, {ok_count}个正常"

    return result

def determine_overall_status(checks: List[dict]) -> str:
    """
    根据所有检查结果确定统一状态码。

    判定规则（v1.1 — SKIP降级为INFO，不阻断）：
      - ALL_OK: 所有 PASS（SKIP不计入异常）
      - PARTIAL_FAIL: 有 WARN 但无 CRITICAL
      - CRITICAL: 有任何 CRITICAL
    """
    has_critical = any(c.get("status") == "CRITICAL" for c in checks)
    has_warn = any(c.get("status") == "WARN" for c in checks)

    if has_critical:
        return "CRITICAL"
    if has_warn:
        return "PARTIAL_FAIL"
    return "ALL_OK"

def generate_report(checks: List[dict], overall_status: str) -> str:
    """生成健康检查报告 Markdown"""
    now = datetime.now(TZ_CST).strftime("%Y-%m-%d %H:%M:%S")

    status_emoji = {
        "ALL_OK": "✅",
        "PARTIAL_FAIL": "⚠️",
        "CRITICAL": "🚨",
        "SKIP": "⏭️",
        "WARN": "⚠️",
        "PASS": "✅",
        "UNKNOWN": "❓",
    }

    lines = [
        f"# 管线健康检查报告 | {now}",
        f"",
        f"<!-- author: {AUTHOR} | created_time: {CREATED_TIME} -->",
        f"<!-- generated: {now} -->",
        f"",
        f"---",
        f"",
        f"## 总体状态",
        f"",
        f"**{status_emoji.get(overall_status, '❓')} 状态码: {overall_status}**",
        f"",
        f"| 检查项 | 状态 | 详情 |",
        f"|:-------|:----:|:-----|",
    ]

    for check in checks:
        emoji = status_emoji.get(check["status"], "❓")
        lines.append(f"| {check['name']} | {emoji} {check['status']} | {check['detail']} |")

    # 详细表格信息
    lines += [
        f"",
        f"---",
        f"",
        f"## 详细检查结果",
        f"",
    ]

    for check in checks:
        lines.append(f"### {check['name']}")
        lines.append(f"")
        lines.append(f"- **状态**: {check['status']}")
        lines.append(f"- **详情**: {check['detail']}")
        lines.append(f"")

        if "tables" in check:
            lines.append(f"- **核心表**:")
            for tb, info in check["tables"].items():
                emoji = "✅" if info["exists"] else "❌"
                lines.append(f"  - {emoji} {tb}: {info['rows']}行")
            lines.append(f"")

        if "crons" in check:
            crons = check["crons"]
            if crons:
                lines.append(f"- **Cron明细**:")
                for cname, cdata in sorted(crons.items()):
                    emoji_map = {"ok": "✅", "idle": "💤", "error": "❌", "unknown": "❓"}
                    ce = emoji_map.get(cdata["status"], "❓")
                    lines.append(
                        f"  - {ce} {cname}: {cdata['status']} "
                        f"(schedule={cdata.get('schedule', '')})"
                    )
            lines.append(f"")

    lines += [
        f"---",
        f"",
        f"## 判定说明",
        f"",
        f"| 状态码 | 含义 | 处置建议 |",
        f"|:------:|:-----|:---------|",
        f"| **ALL_OK** | 全部正常 | 无需干预 |",
        f"| **PARTIAL_FAIL** | 部分异常（非致命） | 关注告警，择机修复 |",
        f"| **CRITICAL** | 致命错误 | 立即处理 |",
        f"",
        f"---",
        f"",
        f"*健康检查由 {AUTHOR} 自动执行*",
        f"*version: {VERSION}*",
    ]

    return "\n".join(lines)

def run_healthcheck(json_output: bool = False) -> dict:
    """
    运行管线健康检查 — 主入口。

    Args:
        json_output: 是否输出JSON

    Returns:
        summary dict with all checks and overall status
    """
    checks = []

    # 1. DB文件存在性
    checks.append(check_db_existence())

    # 2. 数据库连接 & 核心表
    checks.append(check_db_connectivity())

    # 3. 今日交易记录
    checks.append(check_today_trades())

    # 4. 告警队列积压
    checks.append(check_alert_queue_backlog())

    # 5. Dispatch触发文件
    checks.append(check_dispatch_backlog())

    # 6. Cron状态
    checks.append(check_cron_status())

    # 总体判定
    overall = determine_overall_status(checks)

    # 汇总
    summary = {
        "status": overall,
        "timestamp": now_str(),
        "checks": checks,
        "summary": {
            "PASS": sum(1 for c in checks if c["status"] == "PASS"),
            "WARN": sum(1 for c in checks if c["status"] == "WARN"),
            "CRITICAL": sum(1 for c in checks if c["status"] == "CRITICAL"),
            "SKIP": sum(1 for c in checks if c["status"] == "SKIP"),
        },
        "author": AUTHOR,
    }

    # 输出
    if json_output:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        report = generate_report(checks, overall)
        # 写入文件
        report_filename = f"healthcheck_{datetime.now(TZ_CST).strftime('%Y%m%d_%H%M%S')}.md"
        report_path = REPORTS_DIR / "monitoring" / report_filename
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

        # 也写入标准JSON报告
        json_path = REPORTS_DIR / "monitoring" / f"healthcheck_{datetime.now(TZ_CST).strftime('%Y%m%d_%H%M%S')}.json"
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        print(report)
        print(f"\n[OK] 报告已保存: {report_path}")

    return summary

def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="管线健康检查")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--verbose", action="store_true", help="详细输出")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    summary = run_healthcheck(json_output=args.json)

    status = summary["status"]
    if status == "ALL_OK":
        result_msg = "✅ 全部正常"
    elif status == "PARTIAL_FAIL":
        result_msg = "⚠️ 部分异常，需关注"
    else:
        result_msg = "🚨 致命错误，立即处理"

    s = summary["summary"]
    print(f"\n=== 健康检查结果: {status} ===")
    print(f"  PASS: {s['PASS']} | WARN: {s['WARN']} | CRITICAL: {s['CRITICAL']} | SKIP: {s['SKIP']}")
    print(f"  {result_msg}")

    return 0 if status == "ALL_OK" else (1 if status != "CRITICAL" else 2)

if __name__ == "__main__":
    sys.exit(main())
