#!/usr/bin/env python3
"""
墨枢 (MoShu) - 历史回测结果回填脚本

从两种来源目录的 JSON 文件中解析回测数据，回填到 knowledge.db:
  1. src/backtest_results/  -- 新平台 JSON（约 22 个）
  2. mo_zhi_sharereports/backtest_results/  -- 旧库 JSON（约 660 个）

用法::
    python scripts/backfill_knowledge_db.py                    # 全量回填
    python scripts/backfill_knowledge_db.py --source old        # 只回填旧库
    python scripts/backfill_knowledge_db.py --source new        # 只回填新库
    python scripts/backfill_knowledge_db.py --strategy grid     # 只回填网格
    python scripts/backfill_knowledge_db.py --symbol 601857     # 只回填指定标的
    python scripts/backfill_knowledge_db.py --dry-run           # 预扫描，不实际写入
    python scripts/backfill_knowledge_db.py --limit 50          # 只回填前50条（测试用）
    python scripts/backfill_knowledge_db.py --verify            # 完整性验证（不写入）
    python scripts/backfill_knowledge_db.py --fill-market-context           # 回填市场上下文
    python scripts/backfill_knowledge_db.py --fill-market-context --fallback # 使用降级方案回填

Author: 墨衡
Created: 2026-05-16
Version: 1.2 (added --fill-market-context + --fallback)
"""

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# -- 控制台编码适配（Windows GBK 兼容） --
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# -- 路径修正：确保项目根目录在 sys.path 中 --
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backtest.pipeline.knowledge_db import KnowledgeDB, make_run_id


# =====================================================================
# 常量
# =====================================================================

NEW_SOURCE_DIR = os.path.join(PROJECT_ROOT, "src", "backtest_results")
OLD_SOURCE_DIR = os.path.join(
    os.environ.get("HOME") or os.environ.get("USERPROFILE", "C:/Users/17699"),
    "mo_zhi_sharereports",
    "backtest_results",
)

# JSON 文件名正则（通用）：{strategy}_{symbol}_*
FILENAME_PATTERN = re.compile(r"^(grid|trend|reversal)_(.+?)_.+\.json$")

# 运行报告路径前缀（用于 report_path 记录）
REPORT_PATH_PREFIX_NEW = "src/backtest_results/"
REPORT_PATH_PREFIX_OLD = "mo_zhi_sharereports/backtest_results/"


# =====================================================================
# 文件名解析
# =====================================================================


def parse_filename(filepath: str) -> dict:
    """
    从历史 JSON 文件名解析策略类型、标的等元信息。

    支持的格式（含扩展名 .json 在文件名中可能有多个 . 需要切分）:
      grid_{symbol}_{config_key}_{tag}_{date}_{time}.json
      trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json
      reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json

    兼容通用格式 {strategy}_{symbol}_*.json

    返回
    -------
    dict
        {
            "strategy": "grid" | "trend" | "reversal",
            "symbol": str,
            "config_key": str,
            "strategy_tag": str,
            "config_tag": str,
        }
        无法解析时返回 {"strategy": None, ...}
    """
    basename = os.path.basename(filepath)
    # 移除 .json 扩展名
    stem = basename
    if stem.endswith(".json"):
        stem = stem[:-5]

    match = FILENAME_PATTERN.match(basename)
    if not match:
        return {
            "strategy": None,
            "symbol": None,
            "config_key": "",
            "strategy_tag": "",
            "config_tag": "",
        }

    strategy = match.group(1)
    symbol_part = match.group(2)

    # 按 _ 切分
    parts = stem.split("_")

    result = {
        "strategy": strategy,
        "symbol": symbol_part,
        "config_key": "",
        "strategy_tag": "",
        "config_tag": "",
    }

    if strategy == "grid":
        # grid_{symbol}_{config_key}_{tag}_{date}_{time}
        # parts = [grid, symbol, ...config_key_parts..., tag, date, time]
        if len(parts) >= 5:
            if len(parts) >= 6:
                config_key_parts = parts[2:-3]
                result["config_key"] = "_".join(config_key_parts)
                result["strategy_tag"] = parts[-3]
            else:
                # 最少格式：grid_symbol_tag_date_time
                result["config_key"] = parts[2] if len(parts) > 2 else ""
                result["strategy_tag"] = parts[3] if len(parts) > 3 else ""
            result["config_tag"] = result["config_key"]

    elif strategy in ("trend", "reversal"):
        # trend/reversal_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}
        # parts = [strategy, symbol, signal, pos_mode, tag, timestamp]
        if len(parts) >= 6:
            result["config_key"] = parts[2]  # signal
            result["strategy_tag"] = parts[4]  # tag
            pos_mode = parts[3]
            result["config_tag"] = f"{parts[2]}_{pos_mode}"

    return result


# =====================================================================
# JSON 内容解析
# =====================================================================


def parse_json_content(data: dict) -> dict:
    """
    从 JSON 内容解析回填所需字段。

    参数
    ----------
    data : dict
        从 JSON 文件加载的完整数据结构，
        包含 meta 和 result 两部分。

    返回
    -------
    dict
        {
            "symbol": str,
            "config_key": str,
            "strategy_tag": str,
            "start_date": str (YYYYMMDD),
            "end_date": str (YYYYMMDD),
            "data_days": int,
            "params_json": dict,
            "metrics": dict,
        }
        字段缺失时使用默认值。
    """
    meta = data.get("meta", {})
    result = data.get("result", {})
    metrics_raw = result.get("metrics", {})
    config = result.get("config", {})
    actual_range = result.get("actual_range", {})

    # -- symbol --
    symbol = meta.get("symbol", "")

    # -- config_key --
    config_key = meta.get("config_key", "")

    # -- tag --
    strategy_tag = meta.get("tag", "")

    # -- start_date / end_date --
    start_date = config.get("start_date", "")
    end_date = config.get("end_date", "")

    # 兼容旧 JSON 中日期格式带 "-"（如 "2020-01-01"）
    if start_date and "-" in start_date:
        start_date = start_date.replace("-", "")
    if end_date and "-" in end_date:
        end_date = end_date.replace("-", "")

    # 若 config 中没有日期，尝试从 actual_range 中取
    if not start_date:
        start_date = actual_range.get("start", "")
        if "-" in str(start_date):
            start_date = str(start_date).replace("-", "")
    if not end_date:
        end_date = actual_range.get("end", "")
        if "-" in str(end_date):
            end_date = str(end_date).replace("-", "")

    # -- data_days (total_bars) --
    data_days = result.get("total_bars", 0)

    # -- params_json --
    params_json = {
        "signal_type": meta.get("signal_type", ""),
        "signal_params": meta.get("signal_params", {}),
        "position_params": meta.get("position_params", {}),
        "position_mode": meta.get("position_mode", ""),
        "risk_params": meta.get("risk_params"),
        "initial_capital": meta.get("initial_capital", 0.0),
        "fee_rate": meta.get("fee_rate", 0.0),
        "slippage_rate": meta.get("slippage_rate", 0.0),
        "cooler_days": meta.get("cooler_days", 0),
    }

    # -- metrics --
    # 兼容新旧 JSON 指标字段名
    metrics = {
        "total_return_pct": float(
            metrics_raw.get("total_return_pct", 0.0)
            or metrics_raw.get("total_return", 0.0)
        ),
        "annual_return_pct": float(
            metrics_raw.get("annual_return_pct", 0.0)
            or metrics_raw.get("annual_return", 0.0)
        ),
        "sharpe_ratio": float(
            metrics_raw.get("sharpe_ratio", 0.0)
            or metrics_raw.get("sharpe", 0.0)
        ),
        "max_drawdown_pct": float(
            metrics_raw.get("max_drawdown_pct", 0.0)
            or metrics_raw.get("max_drawdown", 0.0)
        ),
        "win_rate_pct": float(metrics_raw.get("win_rate_pct", 0.0)),
        "profit_factor": float(
            metrics_raw.get("profit_factor", 0.0)
            or metrics_raw.get("profit_loss_ratio", 0.0)
        ),
        "total_trades": int(metrics_raw.get("total_trades", 0)),
        "avg_holding_bars": float(metrics_raw.get("avg_holding_bars", 0.0)),
        "validity_grade": "C",
    }

    return {
        "symbol": symbol,
        "config_key": config_key,
        "strategy_tag": strategy_tag,
        "start_date": start_date,
        "end_date": end_date,
        "data_days": data_days,
        "params_json": params_json,
        "metrics": metrics,
    }


# =====================================================================
# run_id 生成（与 knowledge_db.make_run_id 保持一致）
# =====================================================================


def generate_run_id(
    strategy: str,
    symbol: str,
    config_key: str = "",
    tag: str = "",
    timestamp: str = "",
) -> str:
    """
    生成与 knowledge_db.make_run_id 格式一致的 run_id。

    格式：run_{strategy}_{symbol}_{config_key}_{tag}_{timestamp}

    参数
    ----------
    strategy : str
        'grid' | 'trend' | 'reversal'
    symbol : str
        标的代码
    config_key : str
        配置键（可选）
    tag : str
        策略标签（可选）
    timestamp : str
        时间戳（可选），默认使用当前时间

    返回
    -------
    str
    """
    if not timestamp:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [strategy, symbol, config_key, tag, timestamp]
    return f"run_{'_'.join(p for p in parts if p)}"


# =====================================================================
# 文件扫描
# =====================================================================


def scan_directory(
    source_dir: str,
    report_prefix: str,
    strategy_filter: str = None,
    symbol_filter: str = None,
    limit: int = None,
) -> list:
    """
    扫描目录中的 JSON 文件，返回可处理文件列表。

    返回
    -------
    list[dict]
        每个元素包含文件路径和已解析元信息：
        {
            "filepath": str,
            "report_path": str,
            "strategy": str,
            "symbol": str,
            "config_key": str,
            "strategy_tag": str,
            "config_tag": str,
            "filename_info": dict,
        }
    """
    if not os.path.isdir(source_dir):
        print(f"  [WARN] 目录不存在: {source_dir}，跳过")
        return []

    files = []

    for fp in sorted(Path(source_dir).glob("*.json")):
        filepath = str(fp)
        basename = os.path.basename(filepath)

        # 文件名解析
        info = parse_filename(filepath)
        if info["strategy"] is None:
            print(f"  [WARN] 无法解析文件名（跳过）: {basename}")
            continue

        # 策略过滤
        if strategy_filter and info["strategy"] != strategy_filter:
            continue

        # 标的过滤（支持部分匹配，如 "601857" 匹配 "601857.SH"）
        if symbol_filter:
            sym = info.get("symbol", "")
            if symbol_filter not in sym and sym not in symbol_filter:
                continue

        # 相对路径（用于 report_path 记录）
        report_path = report_prefix + basename

        source_type = "new" if "src/backtest_results" in report_path else "old"
        files.append({
            "filepath": filepath,
            "report_path": report_path,
            "source_type": source_type,
            "strategy": info["strategy"],
            "symbol": info["symbol"],
            "config_key": info["config_key"],
            "strategy_tag": info["strategy_tag"],
            "config_tag": info["config_tag"],
            "filename_info": info,
        })

        if limit is not None and len(files) >= limit:
            break

    return files


def collect_all_files(
    new_dir: str,
    old_dir: str,
    source: str = "all",
    strategy: str = None,
    symbol: str = None,
    limit: int = None,
) -> list:
    """
    收集所有符合条件的 JSON 文件。

    参数
    ----------
    new_dir : str
        新平台 backtest_results 目录
    old_dir : str
        旧库 backtest_results 目录
    source : str
        "all" | "new" | "old"
    strategy : str, optional
        策略类型过滤
    symbol : str, optional
        标的过滤
    limit : int, optional
        最大文件数

    返回
    -------
    list[dict]
    """
    all_files = []

    if source in ("all", "new"):
        print(f"[SCAN] 新平台目录: {new_dir}")
        new_files = scan_directory(
            new_dir,
            REPORT_PATH_PREFIX_NEW,
            strategy_filter=strategy,
            symbol_filter=symbol,
            limit=limit,
        )
        print(f"      找到 {len(new_files)} 个 JSON 文件")
        all_files.extend(new_files)

    if source in ("all", "old"):
        remaining = limit
        if limit is not None and source == "all":
            remaining = limit - len(all_files)
        if remaining is not None and remaining <= 0:
            print(f"[SKIP] 旧库目录: 已达到 limit={limit}，不再扫描")
        else:
            print(f"[SCAN] 旧库目录: {old_dir}")
            old_files = scan_directory(
                old_dir,
                REPORT_PATH_PREFIX_OLD,
                strategy_filter=strategy,
                symbol_filter=symbol,
                limit=remaining,
            )
            print(f"      找到 {len(old_files)} 个 JSON 文件")
            all_files.extend(old_files)

    return all_files


# =====================================================================
# 回填执行
# =====================================================================


def backfill_file(
    db: KnowledgeDB,
    file_info: dict,
) -> bool:
    """
    单文件回填：解析 JSON -> 写入 knowledge.db。

    参数
    ----------
    db : KnowledgeDB
    file_info : dict
        文件信息，包含 filepath、strategy、symbol 等

    返回
    -------
    bool
        True 表示写入成功（或已存在），False 表示失败
    """
    filepath = file_info["filepath"]
    basename = os.path.basename(filepath)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"    [FAIL] 读取/解析失败 {basename}: {e}")
        return False

    # -- 从 JSON 内容解析字段 --
    content = parse_json_content(data)

    # -- 如果 JSON meta 中提供了 symbol，覆盖文件名解析的 symbol --
    symbol = content["symbol"] or file_info["symbol"]
    config_key = content["config_key"] or file_info["config_key"]
    strategy_tag = content["strategy_tag"] or file_info["strategy_tag"]

    # -- 从 meta.timestamp 提取时间戳用于 run_id --
    meta = data.get("meta", {})
    raw_ts = meta.get("timestamp", "")
    if not raw_ts:
        # 从文件名提取时间戳
        stem = basename[:-5] if basename.endswith(".json") else basename
        parts = stem.split("_")
        # 尝试取最后两个部分作为 date_time
        if len(parts) >= 2:
            raw_ts = f"{parts[-2]}_{parts[-1]}"

    # -- 生成 run_id --
    run_id = generate_run_id(
        strategy=file_info["strategy"],
        symbol=symbol,
        config_key=config_key,
        tag=strategy_tag,
        timestamp=raw_ts,
    )

    # -- 写入 database --
    try:
        success = db.backfill_run(
            run_id=run_id,
            strategy=file_info["strategy"],
            symbol=symbol,
            config_key=config_key,
            strategy_tag=strategy_tag,
            start_date=content["start_date"],
            end_date=content["end_date"],
            data_days=content["data_days"],
            param_version="v0_backfill",
            run_by="auto",
            triggered_by="backfill",
            report_path=file_info["report_path"],
            params_json=content["params_json"],
            metrics=content["metrics"],
        )
        return success
    except Exception as e:
        print(f"    [FAIL] 写入失败 {basename}: {e}")
        return False


def run_backfill(
    files: list,
    dry_run: bool = False,
) -> dict:
    """
    执行回填主流程。

    参数
    ----------
    files : list[dict]
        文件列表
    dry_run : bool
        如为 True，只统计不写入

    返回
    -------
    dict
        {"total": int, "success": int, "failed": int, "skipped": int}
    """
    total = len(files)
    success_count = 0
    failed_count = 0
    skipped_count = 0

    if total == 0:
        print("  - 无符合条件的文件")
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    if dry_run:
        print(f"\n[Dry-Run] 预扫描完成，共 {total} 个文件待回填:")
        # 统计策略分布
        strategy_counts = {}
        source_counts = {}
        for f in files:
            s = f["strategy"]
            strategy_counts[s] = strategy_counts.get(s, 0) + 1
            if f.get("source_type") == "new":
                source_counts["new"] = source_counts.get("new", 0) + 1
            else:
                source_counts["old"] = source_counts.get("old", 0) + 1

        print(f"   来源分布: 新平台={source_counts.get('new', 0)}, 旧库={source_counts.get('old', 0)}")
        print(f"   策略分布: {strategy_counts}")
        print(f"   标的分布: {len(set(f['symbol'] for f in files))} 个不同标的")
        return {"total": total, "success": 0, "failed": 0, "skipped": total}

    # -- 初始化数据库 --
    db = KnowledgeDB()
    db.initialize()
    print(f"\n[DB] 知识库已初始化: {db.db_path}")

    print(f"\n[BACKFILL] 开始回填，共 {total} 个文件...")
    start_time = datetime.now()

    for i, file_info in enumerate(files, 1):
        basename = os.path.basename(file_info["filepath"])

        # -- 进度打印（每 50 条） --
        if i == 1 or i % 50 == 0 or i == total:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"  [{i}/{total}] elapsed={elapsed:.1f}s")

        ok = backfill_file(db, file_info)
        if ok:
            success_count += 1
        else:
            failed_count += 1

    db.close()

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n[DONE] 回填完成! 耗时 {elapsed:.1f}s")
    print(f"   总计: {total}")
    print(f"   成功: {success_count}")
    print(f"   失败: {failed_count}")
    print(f"   跳过（已有）: {skipped_count}")

    return {
        "total": total,
        "success": success_count,
        "failed": failed_count,
        "skipped": skipped_count,
    }


# =====================================================================
# 完整性验证
# =====================================================================


def run_verify(
    new_dir: str,
    old_dir: str,
    source: str = "all",
    strategy: str = None,
    symbol: str = None,
) -> dict:
    """
    完整性验证模式（--verify）：扫描 JSON 文件并与 DB 记录比对，
    报告缺失情况。仅验证，不修改数据。

    验证逻辑：
      1. 扫描文件中提取每个文件的 report_path
      2. 查询 DB 中所有 report_path
      3. 比对：文件中的 report_path 在 DB 中存在即为已入库
      4. 输出统计：总文件数、已入库数、缺失数及列表

    返回
    -------
    dict
        {
            "old": {"files": int, "in_db": int, "missing": list[str]},
            "new": {"files": int, "in_db": int, "missing": list[str]},
            "total": int, "in_db_total": int, "missing_total": int,
        }
    """
    print("=" * 60)
    print("  墨枢 - 回填完整性验证")
    print("=" * 60)
    print()

    # -- 扫描所有 JSON 文件 --
    all_files = collect_all_files(
        new_dir=new_dir,
        old_dir=old_dir,
        source=source,
        strategy=strategy,
        symbol=symbol,
        limit=None,
    )

    if not all_files:
        print("[EMPTY] 无符合条件的 JSON 文件")
        return {"old": {}, "new": {}, "total": 0, "in_db_total": 0, "missing_total": 0}

    # -- 查询 DB 中所有 report_path --
    db = KnowledgeDB()
    db.initialize()

    import sqlite3
    conn = sqlite3.connect(db.db_path)
    rows = conn.execute("SELECT report_path FROM backtest_runs").fetchall()
    db_report_paths = set(r[0] for r in rows if r[0])
    conn.close()
    db.close()

    print(f"[DB] 知识库路径: {KnowledgeDB().db_path}")
    print(f"[DB] 共 {len(db_report_paths)} 条记录（含 report_path）")
    print()

    # -- 按来源分别比对 --
    from collections import defaultdict
    by_source = defaultdict(list)
    for f in all_files:
        by_source[f["source_type"]].append(f)

    result = {}
    for source_type, label in [("old", "旧路径 (mo_zhi_sharereports)"),
                               ("new", "新平台 (src/backtest_results)")]:
        items = by_source.get(source_type, [])
        total = len(items)
        missing = []
        for item in items:
            if item["report_path"] not in db_report_paths:
                missing.append(item["report_path"])

        in_db = total - len(missing)
        result[source_type] = {
            "files": total,
            "in_db": in_db,
            "missing": missing,
        }

        print(f"  [{label}]")
        print(f"    文件数:  {total}")
        print(f"    已入库:  {in_db}")
        print(f"    缺失数:  {len(missing)}")
        if missing:
            print(f"    缺失列表:")
            for mp in missing:
                print(f"      - {mp}")
        print()

    # -- 汇总 --
    total_files = result["old"]["files"] + result["new"]["files"]
    total_missing = len(result["old"]["missing"]) + len(result["new"]["missing"])
    total_in_db = total_files - total_missing

    print(f"  [汇总]")
    print(f"    文件总数:  {total_files}")
    print(f"    DB 记录数: {len(db_report_paths)}")
    print(f"    缺失总数:  {total_missing}")

    status = "PASS" if total_missing == 0 else "MISMATCH"
    print(f"\n  状态: {'✅ ' + status if total_missing == 0 else '⚠️  ' + status} 缺失 {total_missing} 条")

    result_flat = {
        "old": result["old"],
        "new": result["new"],
        "total": total_files,
        "in_db_total": total_in_db,
        "missing_total": total_missing,
    }
    return result_flat


# =====================================================================
# 市场上下文回填 + 降级方案
# =====================================================================


def _fill_market_context_fallback(
    symbol: str,
    date: str,
    ma_window: int = 20,
    atr_window: int = 14,
    slope_threshold: float = 0.001,
    atr_high_quantile: float = 0.7,
) -> dict:
    """
    降级版市场状态判断：用 20日均线斜率 + ATR 粗分类取代对 akshare 的依赖。

    分类规则：
        MA斜率 > threshold 且 ATR < high_vol_threshold  → bullish
        MA斜率 < -threshold                                → bearish
        其余                                                  → sideways

    只使用本地 pickle 缓存文件（backtest_data_cache/），不调用 akshare。

    参数
    ----------
    symbol : str
        标的代码，如 '601857.SH' 或 '601857'
    date : str
        参考日期，格式 YYYYMMDD
    ma_window : int
        均线窗口，默认 20
    atr_window : int
        ATR 窗口，默认 14
    slope_threshold : float
        均线斜率判定阈值（相对价格比率），默认 0.001
    atr_high_quantile : float
        ATR 高波动分位数阈值，默认 0.7

    返回
    -------
    dict
        {
            'regime': 'bullish' | 'bearish' | 'sideways',
            'volatility': 'low' | 'medium' | 'high',
            'ma_slope': float,      # 20日均线斜率
            'atr': float,            # ATR 值
            'price': float,
            'confidence': 'rough',   # 标记为降级数据
        }
    """
    import pandas as pd
    import numpy as np
    import glob as _glob
    import os as _os

    # ── 归一化 symbol 代码 ──
    code = symbol.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')

    # ── 获取项目根目录 ──
    try:
        root = PROJECT_ROOT
    except Exception:
        root = _os.path.normpath(
            _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..")
        )

    cache_dir = _os.path.join(root, "backtest_data_cache")
    df = None

    if _os.path.isdir(cache_dir):
        pattern = _os.path.join(cache_dir, f"{code}_*.parquet")
        cache_files = sorted(_glob.glob(pattern))

        if cache_files:
            try:
                chunks = []
                for f in cache_files:
                    try:
                        chunk = pd.read_pickle(f)
                        chunks.append(chunk)
                    except Exception:
                        continue
                if chunks:
                    full = pd.concat(chunks, ignore_index=True)
                    full = full.drop_duplicates(subset=['date']).sort_values('date')
                    full['date'] = pd.to_datetime(full['date'])
                    target = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8])
                    # 取目标日期或之前的数据，需要充足的日期来计算 MA + ATR
                    needed = ma_window + atr_window + 5  # 额外余量
                    hist = full[full['date'] <= target].tail(needed)
                    if len(hist) >= ma_window + 5:
                        df = hist
            except Exception:
                df = None

    # ── 本地缓存无数据，返回 unknown ──
    if df is None or len(df) < ma_window + 5:
        return {
            'regime': 'unknown',
            'volatility': 'medium',
            'ma_slope': 0.0,
            'atr': 0.0,
            'price': 0.0,
            'confidence': 'rough',
            'data_source': 'fallback_local',
        }

    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    price = float(close[-1])

    # ── 计算 20 日均线 ──
    if len(close) >= ma_window:
        ma_series = pd.Series(close).rolling(window=ma_window).mean().values
        # 取最近 5 个有效均线值计算斜率（线性回归）
        valid_ma = ma_series[~np.isnan(ma_series)]
        if len(valid_ma) >= 5:
            x = np.arange(len(valid_ma))
            slope = np.polyfit(x[-5:], valid_ma[-5:], 1)[0]
            # 斜率相对于当前价格归一化
            ma_slope = slope / max(price, 0.001)
        else:
            ma_slope = 0.0
    else:
        ma_slope = 0.0

    # ── 计算 ATR (14日) ──
    # TR = max(high-low, |high-prev_close|, |low-prev_close|)
    tr_values = []
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        tr_values.append(tr)

    if len(tr_values) >= atr_window:
        tr_series = pd.Series(tr_values)
        # Wilder's smoothed ATR
        atr_vals = tr_series.ewm(alpha=1.0 / atr_window, adjust=False).mean().values
        current_atr = float(atr_vals[-1])
        # ATR 相对价格百分比
        atr_pct = current_atr / max(price, 0.001)

        # ATR 高波动阈值：取所有 ATR 值的 70% 分位数
        high_threshold = float(pd.Series(atr_vals).quantile(atr_high_quantile))
        low_threshold = float(pd.Series(atr_vals).quantile(0.3))
    else:
        current_atr = 0.0
        atr_pct = 0.0
        high_threshold = 0.0
        low_threshold = 0.0

    # ── 波动率分级（按 ATR 百分位） ──
    if current_atr > high_threshold:
        vol_level = 'high'
    elif current_atr < low_threshold:
        vol_level = 'low'
    else:
        vol_level = 'medium'

    # ── 市场状态分类 ──
    # 规则：MA斜率向上 + 非高波动 → bullish; MA斜率向下 → bearish; 其余 → sideways
    if ma_slope > slope_threshold and vol_level != 'high':
        regime = 'bullish'
    elif ma_slope < -slope_threshold:
        regime = 'bearish'
    else:
        regime = 'sideways'

    return {
        'regime': regime,
        'volatility': vol_level,
        'ma_slope': round(ma_slope, 6),
        'atr': round(current_atr, 4),
        'price': round(price, 2),
        'confidence': 'rough',
        'data_source': 'fallback_local',
    }


def _run_fill_market_context(
    symbol: str = None,
    use_fallback: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    执行 market_context 回填主流程。

    当 use_fallback=True 时，使用 _fill_market_context_fallback()
    （MA斜率 + ATR 分类，不依赖 akshare）。
    当 use_fallback=False 时，使用 KnowledgeDB.backfill_market_context()
    （即 _estimate_market_regime，本地缓存优先，兜底 akshare）。

    参数
    ----------
    symbol : str, optional
        标的过滤
    use_fallback : bool
        强制使用降级方案
    dry_run : bool
        仅扫描不写入

    返回
    -------
    dict
        {"filled": int, "dry_run": bool, "method": str}
    """
    db = KnowledgeDB()
    db.initialize()

    print("=" * 60)
    print("  墨枢 - 市场上下文回填")
    print(f"  KnowledgeDB: {db.db_path}")
    print(f"  方法: {'降级方案 (MA斜率+ATR)' if use_fallback else '标准方案 (缓存+akshare)'}")
    print(f"  标的过滤: {symbol or '(全部)'}")
    print(f"  模式: {'Dry-Run' if dry_run else '实际写入'}")
    print("=" * 60)
    print()

    if use_fallback:
        return _run_market_context_fallback_backfill(db, symbol=symbol, dry_run=dry_run)
    else:
        return _run_market_context_standard_backfill(db, symbol=symbol, dry_run=dry_run)


def _run_market_context_standard_backfill(
    db: KnowledgeDB,
    symbol: str = None,
    dry_run: bool = False,
) -> dict:
    """
    标准方案：使用 KnowledgeDB.backfill_market_context()。
    本地缓存优先，兜底 akshare。
    """
    print("[INFO] 使用标准方案（本地缓存 → akshare 兜底）...")

    if dry_run:
        # Dry-run 模式下，只统计待回填的 run_id 数量
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        if symbol:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM backtest_runs r
                LEFT JOIN market_context mc ON r.run_id = mc.run_id
                WHERE mc.run_id IS NULL
                  AND r.symbol LIKE ?
                """,
                (f"%{symbol}%",),
            )
        else:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM backtest_runs r
                LEFT JOIN market_context mc ON r.run_id = mc.run_id
                WHERE mc.run_id IS NULL
                """
            )
        count = cursor.fetchone()[0]
        conn.close()
        print(f"[Dry-Run] 待回填 market_context: {count} 条")
        db.close()
        return {"filled": 0, "dry_run": True, "method": "standard", "pending": count}

    filled = db.backfill_market_context()
    db.close()
    print(f"[DONE] 标准方案回填完成: {filled} 条")
    return {"filled": filled, "dry_run": False, "method": "standard"}


def _run_market_context_fallback_backfill(
    db: KnowledgeDB,
    symbol: str = None,
    dry_run: bool = False,
    ma_window: int = 20,
    atr_window: int = 14,
) -> dict:
    """
    降级方案：使用 _fill_market_context_fallback() 逐条回填。
    仅依赖本地 pickle 缓存，不调用 akshare。
    """
    import sqlite3

    print("[INFO] 使用降级方案（MA斜率 + ATR，仅本地缓存）...")

    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row

    # ── 查询待回填记录 ──
    if symbol:
        cursor = conn.execute(
            """
            SELECT r.run_id, r.symbol, r.end_date
            FROM backtest_runs r
            LEFT JOIN market_context mc ON r.run_id = mc.run_id
            WHERE mc.run_id IS NULL
              AND r.symbol LIKE ?
            ORDER BY r.created_at ASC
            """,
            (f"%{symbol}%",),
        )
    else:
        cursor = conn.execute(
            """
            SELECT r.run_id, r.symbol, r.end_date
            FROM backtest_runs r
            LEFT JOIN market_context mc ON r.run_id = mc.run_id
            WHERE mc.run_id IS NULL
            ORDER BY r.created_at ASC
            """
        )

    rows = cursor.fetchall()
    pending = [(r['run_id'], r['symbol'], r['end_date']) for r in rows]
    conn.close()

    if not pending:
        print("[EMPTY] 无待回填的 market_context 记录")
        db.close()
        return {"filled": 0, "dry_run": dry_run, "method": "fallback", "pending": 0}

    print(f"[SCAN] 共 {len(pending)} 条待回填记录")

    if dry_run:
        # 统计降级分类预测分布
        from collections import Counter
        regime_counter: Counter = Counter()
        unknown_count = 0

        for run_id, sym, end_date in pending:
            if not sym or not end_date:
                unknown_count += 1
                continue
            date_key = end_date[:8]
            ctx = _fill_market_context_fallback(
                sym, date_key, ma_window=ma_window, atr_window=atr_window
            )
            if ctx['regime'] == 'unknown':
                unknown_count += 1
            else:
                regime_counter[ctx['regime']] += 1

        print(f"\n[Dry-Run] 降级分类预测分布:")
        for regime, cnt in sorted(regime_counter.items(), key=lambda x: -x[1]):
            print(f"    {regime}: {cnt}")
        print(f"    unknown: {unknown_count}")
        print(f"    可回填: {len(pending) - unknown_count} / {len(pending)}")
        db.close()
        return {
            "filled": 0,
            "dry_run": True,
            "method": "fallback",
            "pending": len(pending),
            "prediction": dict(regime_counter),
        }

    # ── 实际回填 ──
    filled = 0
    errors = []
    start_time = datetime.now()

    for idx, (run_id, sym, end_date) in enumerate(pending, 1):
        if not sym or not end_date:
            continue
        date_key = end_date[:8]

        try:
            ctx = _fill_market_context_fallback(
                sym, date_key, ma_window=ma_window, atr_window=atr_window
            )

            if ctx['regime'] == 'unknown':
                continue

            # 转换为 _estimate_market_regime 输出格式以兼容 store_market_context
            legacy_ctx = {
                'regime': ctx['regime'],
                'volatility': ctx['volatility'],
                'short_ma': ctx['ma_slope'],  # 降级方案用 slope 替代
                'long_ma': 0.0,
                'price': ctx['price'],
                'confidence': 'rough',
            }

            db.store_market_context(run_id, legacy_ctx, date_key=date_key)
            filled += 1

            if idx % 100 == 0 or idx == len(pending):
                elapsed = (datetime.now() - start_time).total_seconds()
                print(f"  [{idx}/{len(pending)}] filled={filled} elapsed={elapsed:.1f}s")

        except Exception as exc:
            errors.append(f"{run_id}: {exc}")

    db.close()

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n[DONE] 降级回填完成! 耗时 {elapsed:.1f}s")
    print(f"   总计: {len(pending)}")
    print(f"   成功: {filled}")
    print(f"   错误: {len(errors)}")

    if errors:
        print(f"   (前5条):")
        for e in errors[:5]:
            print(f"      {e}")

    return {"filled": filled, "dry_run": False, "method": "fallback", "errors": len(errors)}


# =====================================================================
# CLI
# =====================================================================


def main():
    parser = argparse.ArgumentParser(
        description="墨枢 - 历史回测结果回填脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/backfill_knowledge_db.py                    # 全量回填
  python scripts/backfill_knowledge_db.py --source old        # 只回填旧库
  python scripts/backfill_knowledge_db.py --source new        # 只回填新库
  python scripts/backfill_knowledge_db.py --strategy grid     # 只回填网格
  python scripts/backfill_knowledge_db.py --symbol 601857     # 只回填指定标的
  python scripts/backfill_knowledge_db.py --dry-run           # 预扫描
  python scripts/backfill_knowledge_db.py --limit 50          # 测试用
  python scripts/backfill_knowledge_db.py --verify            # 完整性验证
        """,
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        dest="verify_mode",
        help="完整性验证模式：扫描 JSON 并与 DB 比对，不修改数据",
    )
    parser.add_argument(
        "--source",
        choices=["all", "new", "old"],
        default="all",
        help="数据来源（默认: all）",
    )
    parser.add_argument(
        "--strategy",
        choices=["grid", "trend", "reversal"],
        default=None,
        help="策略类型过滤",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="标的过滤（支持部分匹配，如 601857 匹配 601857.SH）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预扫描模式，只统计不写入",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最大处理文件数（测试用）",
    )
    parser.add_argument(
        "--fill-market-context",
        action="store_true",
        dest="fill_market_context",
        help="回填 market_context（市场状态标签）",
    )
    parser.add_argument(
        "--fallback",
        action="store_true",
        dest="use_fallback",
        help="强制使用降级方案（MA斜率 + ATR）填充 market_context，而非 akshare",
    )

    args = parser.parse_args()

    # ── --verify 模式：直接验证后退出 ─────────────────
    if args.verify_mode:
        run_verify(
            new_dir=NEW_SOURCE_DIR,
            old_dir=OLD_SOURCE_DIR,
            source=args.source,
            strategy=args.strategy,
            symbol=args.symbol,
        )
        return

    # ── --fill-market-context 模式 ────────────────────
    if args.fill_market_context:
        _run_fill_market_context(
            symbol=args.symbol,
            use_fallback=args.use_fallback,
            dry_run=args.dry_run,
        )
        return

    print("=" * 60)
    print("  墨枢 - 回测知识库回填工具")
    print(f"  KnowledgeDB: {KnowledgeDB().db_path}")
    print("=" * 60)
    print(f"  来源: {args.source}")
    print(f"  策略过滤: {args.strategy or '(全部)'}")
    print(f"  标的过滤: {args.symbol or '(全部)'}")
    print(f"  模式: {'Dry-Run' if args.dry_run else '实际回填'}")
    if args.limit:
        print(f"  限制: 前 {args.limit} 个文件")
    print()

    # -- 扫描文件 --
    files = collect_all_files(
        new_dir=NEW_SOURCE_DIR,
        old_dir=OLD_SOURCE_DIR,
        source=args.source,
        strategy=args.strategy,
        symbol=args.symbol,
        limit=args.limit,
    )

    print(f"\n[SUM] 共扫描到 {len(files)} 个文件")

    # -- 执行回填 --
    result = run_backfill(files, dry_run=args.dry_run)

    # -- 返回码 --
    if result["failed"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
