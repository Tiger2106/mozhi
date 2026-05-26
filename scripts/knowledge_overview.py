#!/usr/bin/env python3
"""
墨枢 (MoShu) — knowledge.db 全局概览脚本

输出所有表的行数统计、知识点概览、回测按策略/标的分布、
绩效聚合指标、市场状态分布等。

用法::
    python scripts/knowledge_overview.py                # 输出到 stdout
    python scripts/knowledge_overview.py --output out.md  # 保存到文件

约束:
    - 纯读取，不修改数据
    - 使用 knowledge_db.py 的 KnowledgeDB 类
    - Python 标准库 + SQLite3，无额外依赖

Author: 墨衡
Created: 2026-05-16
Version: 1.0
"""

from __future__ import annotations

import argparse
import io
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta


# ── 控制台编码适配（Windows GBK 兼容） ──
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ── 路径修正：确保项目根目录在 sys.path 中 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backtest.pipeline.knowledge_db import KnowledgeDB, DEFAULT_DB_PATH
from src.config import SHANGHAI_TZ


# ═══════════════════════════════════════════════════════════════
# 格式化工具
# ═══════════════════════════════════════════════════════════════


def _fmt_pct(v: float | None, decimals: int = 2) -> str:
    """格式化百分比，处理 None 显示为 'N/A'。"""
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}%"


def _fmt_ratio(v: float | None, decimals: int = 2) -> str:
    """格式化比率，处理 None 显示为 'N/A'。"""
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def _markdown_table(header: list[str], rows: list[list[str]]) -> str:
    """生成简单的 Markdown 表格（适用于 stdout 和文件输出）。"""
    col_count = len(header)
    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in range(col_count)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 查询函数
# ═══════════════════════════════════════════════════════════════


def get_table_counts(db: KnowledgeDB) -> dict[str, int]:
    """查询各表行数。"""
    tables = [
        "backtest_runs",
        "params_snapshot",
        "performance_results",
        "market_context",
        "knowledge_entries",
        "knowledge_run_links",
    ]
    counts: dict[str, int] = {}
    with db._conn() as conn:
        for t in tables:
            cursor = conn.execute(f"SELECT COUNT(*) AS cnt FROM {t}")
            row = cursor.fetchone()
            counts[t] = row["cnt"] if row else 0
    return counts


def get_knowledge_overview(db: KnowledgeDB) -> list[dict]:
    """查询 knowledge_entries 核心字段。"""
    with db._conn() as conn:
        cursor = conn.execute("""
            SELECT strategy, symbol, confidence, insight_category
            FROM knowledge_entries
            ORDER BY strategy, symbol
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_strategy_distribution(db: KnowledgeDB) -> list[dict]:
    """按 strategy 分组统计 backtest_runs。"""
    with db._conn() as conn:
        cursor = conn.execute("""
            SELECT strategy, COUNT(*) AS cnt
            FROM backtest_runs
            GROUP BY strategy
            ORDER BY cnt DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_symbol_distribution(db: KnowledgeDB) -> list[dict]:
    """按 symbol 分组统计 backtest_runs。"""
    with db._conn() as conn:
        cursor = conn.execute("""
            SELECT symbol, COUNT(*) AS cnt
            FROM backtest_runs
            GROUP BY symbol
            ORDER BY cnt DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_performance_aggregation(db: KnowledgeDB) -> list[dict]:
    """按 strategy 聚合绩效指标（win_rate, sharpe, profit_factor, max_dd）。"""
    with db._conn() as conn:
        cursor = conn.execute("""
            SELECT
                r.strategy,
                AVG(p.win_rate_pct)      AS avg_win_rate,
                AVG(p.sharpe_ratio)      AS avg_sharpe,
                AVG(p.profit_factor)     AS avg_profit_factor,
                AVG(p.max_drawdown_pct)  AS avg_max_dd
            FROM performance_results p
            JOIN backtest_runs r ON p.run_id = r.run_id
            GROUP BY r.strategy
            ORDER BY r.strategy
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_market_regime_distribution(db: KnowledgeDB) -> list[dict]:
    """按 market_regime 分组统计 market_context。"""
    with db._conn() as conn:
        cursor = conn.execute("""
            SELECT market_regime, COUNT(*) AS cnt
            FROM market_context
            GROUP BY market_regime
            ORDER BY cnt DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════


def generate_overview(db_path: str) -> str:
    """生成完整的全局概览文本。"""

    db = KnowledgeDB(db_path)
    db.initialize()  # 确保表存在（幂等）

    now = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    lines.append("=== knowledge.db 全局概览 ===")
    lines.append(f"数据库路径: {db_path}")
    lines.append(f"生成时间:   {now} (+08:00)")
    lines.append("")

    # ── 1. 表统计 ──────────────────────────────────────────
    lines.append("## 表统计")
    counts = get_table_counts(db)
    header = ["表名", "行数"]
    rows = [[t, str(counts[t])] for t in [
        "backtest_runs",
        "params_snapshot",
        "performance_results",
        "market_context",
        "knowledge_entries",
        "knowledge_run_links",
    ]]
    lines.append(_markdown_table(header, rows))
    lines.append("")

    # ── 2. knowledge_entries 概览 ────────────────────────────
    lines.append("## knowledge_entries 概览")
    knowledge_rows = get_knowledge_overview(db)
    if knowledge_rows:
        header = ["strategy", "symbol", "confidence", "insight_category"]
        rows = [[r["strategy"], r["symbol"], r["confidence"], r["insight_category"]]
                for r in knowledge_rows]
        lines.append(_markdown_table(header, rows))
    else:
        lines.append("（无记录）")
    lines.append("")

    # ── 3. backtest_runs 按策略分布 ──────────────────────────
    lines.append("## backtest_runs 按策略分布")
    total_runs = counts.get("backtest_runs", 0)
    strategy_rows = get_strategy_distribution(db)
    if strategy_rows:
        header = ["strategy", "count", "占比"]
        rows = [
            [r["strategy"], str(r["cnt"]),
             f"{r['cnt'] / total_runs * 100:.1f}%" if total_runs else "N/A"]
            for r in strategy_rows
        ]
        lines.append(_markdown_table(header, rows))
    else:
        lines.append("（无记录）")
    lines.append("")

    # ── 4. backtest_runs 按标的分布 ──────────────────────────
    lines.append("## backtest_runs 按标的分布")
    symbol_rows = get_symbol_distribution(db)
    if symbol_rows:
        header = ["symbol", "count"]
        rows = [[r["symbol"], str(r["cnt"])] for r in symbol_rows]
        lines.append(_markdown_table(header, rows))
    else:
        lines.append("（无记录）")
    lines.append("")

    # ── 5. performance_results 聚合 ──────────────────────────
    lines.append("## performance_results 聚合")
    perf_rows = get_performance_aggregation(db)
    if perf_rows:
        header = ["strategy", "avg_win_rate", "avg_sharpe", "avg_profit_factor", "avg_max_dd"]
        rows = [
            [
                r["strategy"],
                _fmt_pct(r["avg_win_rate"]),
                _fmt_ratio(r["avg_sharpe"]),
                _fmt_ratio(r["avg_profit_factor"]),
                _fmt_pct(r["avg_max_dd"]),
            ]
            for r in perf_rows
        ]
        lines.append(_markdown_table(header, rows))
    else:
        lines.append("（无记录）")
    lines.append("")

    # ── 6. market_context 按市场状态分布 ──────────────────────
    lines.append("## market_context 按市场状态分布")
    regime_rows = get_market_regime_distribution(db)
    if regime_rows:
        header = ["market_regime", "count"]
        rows = [[r["market_regime"], str(r["cnt"])] for r in regime_rows]
        lines.append(_markdown_table(header, rows))
    else:
        lines.append("（无记录）")
    lines.append("")

    # ── 尾部注释 ──────────────────────────────────────────
    lines.append("---")
    lines.append(f"*Generated by knowledge_overview.py | Author: 墨衡*")

    db.close()
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="knowledge.db 全局概览 — 纯读取，不修改数据"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出文件路径（默认输出到 stdout）",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"knowledge.db 路径（默认: {DEFAULT_DB_PATH}）",
    )
    args = parser.parse_args()

    # 检查数据库文件是否存在
    if not os.path.isfile(args.db):
        print(f"[ERROR] 数据库文件不存在: {args.db}", file=sys.stderr)
        sys.exit(1)

    overview = generate_overview(args.db)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(overview)
        print(f"概览已保存到: {args.output}")
    else:
        print(overview)


if __name__ == "__main__":
    main()
