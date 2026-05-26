#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨枢 (MoShu) — backtest_results 文件存储监控

扫描 backtest_results 目录下的所有文件，
输出总文件数/总大小、按策略/标的分布、按月新增文件数。

用法::
    python scripts/backtest_storage_watch.py              # 输出到 stdout
    python scripts/backtest_storage_watch.py --output out.md  # 保存到文件
    python scripts/backtest_storage_watch.py --json          # JSON 格式输出

Author: 墨衡
Created: 2026-05-16
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from src.config import SHANGHAI_TZ

# ── 控制台编码适配（Windows GBK 兼容） ──
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 常量 ──
BACKTEST_ROOT = r"C:\Users\17699\mo_zhi_sharereports\backtest_results"

# 文件名中提取 YYYYMMDD 的正则 (8 位数字，作为日期)
DATE_PATTERN = re.compile(r"(\d{8})")

# 文件名提取策略和标的的正则:
# 形如: grid_000001.SZ_static_n10_arithmetic_fixed_cd3_default_20260515_081354.json
#       或 grid_601857_static_n10_arithmetic_fixed_cd3_benchmark_20260515_090350.json
# 策略 = 第一个下划线前的部分
# 标的 = 第一个下划线和第二个下划线之间的部分
STRATEGY_SYMBOL_PATTERN = re.compile(r"^([^_]+)_([^_]+)")


def scan_directory(root: str) -> list[dict]:
    """递归扫描目录，返回每个文件的信息列表。

    每个文件信息包含:
        path, size_bytes, strategy, symbol, date_str (YYYYMMDD)
    """
    results: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            full_path = os.path.join(dirpath, fname)
            try:
                stat = os.stat(full_path)
            except OSError:
                continue

            size_bytes = stat.st_size
            # 尝试从文件名提取日期
            date_match = DATE_PATTERN.search(fname)
            date_str = date_match.group(1) if date_match else None

            # 尝试提取策略和标的（从相对路径或文件名）
            strategy, symbol = extract_strategy_symbol(fname, dirpath, root)

            results.append({
                "path": full_path,
                "filename": fname,
                "size_bytes": size_bytes,
                "strategy": strategy,
                "symbol": symbol,
                "date_str": date_str,
            })
    return results


def extract_strategy_symbol(
    filename: str, dirpath: str, root: str
) -> tuple[str, str]:
    """从文件名和目录路径中提取策略(strategy)和标的(symbol)。"""

    # 先从标准文件名格式: strategy_symbol_... 提取
    m = STRATEGY_SYMBOL_PATTERN.match(filename)
    if m:
        strategy = m.group(1)
        raw_symbol = m.group(2)
        # 验证 symbol 是否像真实的证券代码
        if re.match(r"^\d{6}(\.\w+)?$", raw_symbol):
            return strategy, raw_symbol

    # 如果根目录文件没有标准格式，或 symbol 无效，尝试从文件名中查找证券代码
    for part in filename.split("_"):
        if re.match(r"^\d{6}(\.\w+)?$", part):
            strategy = filename.split("_")[0] if "_" in filename else "other"
            return strategy, part

    # 对于 reports/ 和 scans/ 子目录下的文件
    rel = os.path.relpath(dirpath, root)
    parts = rel.split(os.sep)
    strategy_from_dir = parts[0] if parts and parts[0] != "." else "other"

    # 再尝试从文件名中查找证券代码
    for part in filename.split("_"):
        if re.match(r"^\d{6}(\.\w+)?$", part):
            return strategy_from_dir, part

    return strategy_from_dir, "-"


def format_size(mb: float) -> str:
    """格式化 MB 输出，保留一位小数。"""
    return f"{mb:.1f} MB"


def generate_report(
    files: list[dict], output_format: str = "text"
) -> str:
    """生成统计报告。"""

    total_files = len(files)
    total_bytes = sum(f["size_bytes"] for f in files)
    total_mb = total_bytes / (1024 * 1024)

    # 日期范围
    date_strs = [f["date_str"] for f in files if f["date_str"]]
    if date_strs:
        min_date = min(date_strs)
        max_date = max(date_strs)
        date_span = f"{min_date[:4]}-{min_date[4:6]}-{min_date[6:]} ~ {max_date[:4]}-{max_date[4:6]}-{max_date[6:]}"
    else:
        date_span = "N/A"

    # 按策略分布
    strat_groups = defaultdict(lambda: {"count": 0, "bytes": 0})
    for f in files:
        key = f["strategy"]
        strat_groups[key]["count"] += 1
        strat_groups[key]["bytes"] += f["size_bytes"]

    # 按标的分布
    symbol_groups = defaultdict(lambda: {"count": 0, "bytes": 0})
    for f in files:
        key = f["symbol"]
        symbol_groups[key]["count"] += 1
        symbol_groups[key]["bytes"] += f["size_bytes"]

    # 按月统计新增文件数
    monthly = defaultdict(int)
    for f in files:
        ds = f["date_str"]
        if ds and len(ds) == 8:
            month_key = f"{ds[:4]}-{ds[4:6]}"
            monthly[month_key] += 1

    if output_format == "json":
        report = {
            "total_files": total_files,
            "total_size_mb": round(total_mb, 1),
            "date_span": date_span,
            "by_strategy": {
                k: {
                    "files": v["count"],
                    "size_mb": round(v["bytes"] / (1024 * 1024), 1),
                }
                for k, v in sorted(strat_groups.items(), key=lambda x: -x[1]["count"])
            },
            "by_symbol": {
                k: {
                    "files": v["count"],
                    "size_mb": round(v["bytes"] / (1024 * 1024), 1),
                }
                for k, v in sorted(symbol_groups.items(), key=lambda x: -x[1]["count"])
            },
            "monthly_new_files": dict(sorted(monthly.items())),
        }
        return json.dumps(report, ensure_ascii=False, indent=2)

    # ── 文本输出 ──
    lines: list[str] = []
    lines.append("=== 回测文件存储概览 ===")
    lines.append(f"总文件数:    {total_files}")
    lines.append(f"总大小:      {format_size(total_mb)}")
    lines.append(f"时间跨度:    {date_span}")
    lines.append("")

    # 按策略分布
    lines.append("按策略分布:")
    for name, data in sorted(strat_groups.items(), key=lambda x: -x[1]["count"]):
        size_mb = data["bytes"] / (1024 * 1024)
        lines.append(f"  {name:<10s} {data['count']:>6d} files ({format_size(size_mb)})")
    lines.append("")

    # 按标的分布（只显示有多个文件的标的）
    lines.append("按标的分布:")
    for name, data in sorted(symbol_groups.items(), key=lambda x: -x[1]["count"]):
        size_mb = data["bytes"] / (1024 * 1024)
        lines.append(f"  {name:<12s} {data['count']:>6d} files ({format_size(size_mb)})")
    lines.append("")

    # 按月新增
    if monthly:
        lines.append("按月新增:")
        total_per_month = sum(monthly.values())
        for month in sorted(monthly.keys()):
            cnt = monthly[month]
            pct = cnt / total_per_month * 100
            lines.append(f"  {month}:  {cnt:>5d} files ({pct:.1f}%)")
        lines.append("")

    # 文件类型分布（按扩展名）
    ext_groups = defaultdict(int)
    for f in files:
        _, ext = os.path.splitext(f["filename"])
        ext_groups[ext.lower()] += 1
    lines.append("按文件类型:")
    for ext, cnt in sorted(ext_groups.items(), key=lambda x: -x[1]):
        lines.append(f"  {ext:<8s} {cnt:>6d} files")

    lines.append("")
    lines.append("---")
    now = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"*Generated by backtest_storage_watch.py | {now} +08:00*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="backtest_results 文件存储监控 — 纯读取，不修改数据"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出文件路径（默认输出到 stdout）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 格式输出",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=BACKTEST_ROOT,
        help=f"扫描根目录（默认: {BACKTEST_ROOT}）",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print(f"[ERROR] 目录不存在: {args.root}", file=sys.stderr)
        sys.exit(1)

    files = scan_directory(args.root)
    if not files:
        print(f"[WARN] 目录下没有文件: {args.root}", file=sys.stderr)
        sys.exit(0)

    report = generate_report(files, output_format="json" if args.json else "text")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已保存到: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
