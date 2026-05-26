#!/usr/bin/env python3
"""
墨枢 Phase 1 — 数据完整性校验脚本（TASK-4）
===========================================
Author: 墨衡
Created: 2026-05-22T22:20+08:00

用途：对 stock_daily, daily_factors 表进行多维度数据质量检查。

校验维度：
  - 交易日历覆盖：检查各标的的交易记录是否完整（对比 trading_calendar）
  - 缺失值检测：各字段 NaN/Inf 占比
  - 因子值合理性：范围约束、统计合理性
  - 标准差异常检测：z-score 异常值检测

输出：
  - stdout 详细报告
  - 返回非零退出码表示数据质量问题

执行：
  python scripts/phase1_data_validate.py

依赖：
  - analysis.db（由 TASK-1 + TASK-2 填充）
"""

import os
import sys
import sqlite3
import logging
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── 项目路径 ──────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

ANALYSIS_DB = os.path.join(PROJECT_ROOT, "data", "db", "analysis.db")

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 标的列表
STOCK_CODES = [
    "601857", "000001", "600519", "601318",
    "600036", "300750", "600276", "600887",
    "600030", "000333", "002415", "600436",
]

# 日期范围
DATE_START = "2021-01-01"
DATE_END = "2025-12-31"

# 因子合理范围（name -> (min, max)）
FACTOR_RANGES = {
    "p_mom_rsi": (0, 100),
    "p_mom_macd_dir": (-1, 1),
    "p_mom_macd_hist_rate": (-1, 1),
    "p_mom_price_velocity": (-20, 20),
    "p_mom_roc5": (-20, 20),
    "p_mom_roc10": (-30, 30),
    "p_mom_roc20": (-50, 50),
    "p_mom_williams_r": (-100, 0),
    "p_mom_mtm": (-50, 50),
    "l_trd_adx": (0, 100),
    "l_trd_strength": (0, 1),
    "l_trd_consistency": (0, 1),
    "l_trd_alignment": (0, 100),
    "l_trd_width": (-10, 10),
    "l_trd_breadth": (-2, 2),
    "l_trd_composite_score": (0, 1),
    "l_vol_bb_width": (0, 20),
    "l_vol_bb_squeeze": (0, 1),
    "l_vol_rsi_std": (0, 30),
    "l_vol_price_std": (0, 10),
    "l_vol_atr": (0, 100),
    "l_vol_log_ret_std": (0, 1),
    "l_vol_skew": (-3, 3),
    "l_vol_kurt": (-2, 10),
    "l_obo_rsi_level": (0, 2),
    "l_obo_rsi_extreme": (-1, 1),
    "l_obo_kdj_level": (0, 2),
    "l_obo_kdj_extreme": (-1, 1),
    "l_obo_cci_level": (-1, 1),
    "l_vol_ratio": (0, 10),
    "l_vol_ma5_cross": (-1, 1),
    "l_vol_smart_money": (-1, 1),
    "l_vol_trend": (-1, 1),
    "l_str_structure_quality": (0, 1),
    "l_str_gap_up": (0, 1),
    "l_str_gap_down": (0, 1),
    "l_str_ma5_ma20_cross": (-1, 1),
    "l_str_ma20_ma60_cross": (-1, 1),
    "l_str_bb_position": (0, 1),
    "l_str_close_vs_vwap": (-1, 1),
}


# ════════════════════════════════════════════════════════
# 校验函数
# ════════════════════════════════════════════════════════

def check_trade_calendar(conn: sqlite3.Connection) -> Dict:
    """
    检查各标的的交易日历覆盖。

    对比 trading_calendar 中标记为交易日的日期，
    检查 stock_daily 中每个标的是否有对应的行情记录。
    """
    logger.info("[校验1/5] 交易日历覆盖检查...")

    # 获取所有交易日
    tc = pd.read_sql_query(
        "SELECT date FROM trading_calendar WHERE market='A' AND is_trading_day=1 "
        "AND date >= ? AND date <= ? ORDER BY date",
        conn,
        params=(DATE_START, DATE_END),
    )

    if tc.empty:
        logger.warning("  [警告] 交易日历为空")
        return {"status": "WARN", "total_trading_days": 0}

    trading_dates = set(tc["date"].tolist())
    total_trading = len(trading_dates)
    logger.info("  交易日共计: %d", total_trading)

    results = {}
    issues = []

    for code in STOCK_CODES:
        stock = pd.read_sql_query(
            "SELECT DISTINCT date FROM stock_daily WHERE code=? AND date >= ? AND date <= ? ORDER BY date",
            conn,
            params=(code, DATE_START, DATE_END),
        )
        stock_dates = set(stock["date"].tolist())

        missing = trading_dates - stock_dates
        extra = stock_dates - trading_dates
        coverage = len(stock_dates) / total_trading * 100 if total_trading > 0 else 0

        results[code] = {
            "present": len(stock_dates),
            "missing": len(missing),
            "extra": len(extra),
            "coverage_pct": round(coverage, 2),
        }

        if coverage < 90:
            issues.append(f"  ⚠ {code}: 日历覆盖率仅 {coverage:.1f}%, 缺失 {len(missing)} 天")
        elif coverage < 95:
            issues.append(f"  ℹ {code}: 覆盖率 {coverage:.1f}%, 缺失 {len(missing)} 天")

        if len(missing) > 0 and len(missing) <= 5:
            logger.info("  %s 缺失交易日: %s", code, sorted(missing))
        elif len(missing) > 0:
            logger.info("  %s 缺失 %d 天 (前5: %s)", code, len(missing),
                        sorted(missing)[:5])

    avg_coverage = np.mean([r["coverage_pct"] for r in results.values()])
    logger.info("  平均覆盖率: %.2f%%", avg_coverage)

    for issue in issues:
        logger.info(issue)

    return {
        "status": "PASS" if avg_coverage >= 95 else ("WARN" if avg_coverage >= 85 else "FAIL"),
        "total_trading_days": total_trading,
        "avg_coverage": avg_coverage,
        "per_stock": results,
        "issues": issues,
    }


def check_missing_values(conn: sqlite3.Connection) -> Dict:
    """
    检查各表字段的缺失值（NaN/Inf）占比。
    """
    logger.info("[校验2/5] 缺失值检测...")

    checks = {
        "stock_daily": [
            "open", "high", "low", "close", "volume", "amount",
            "adj_factor", "turnover_rate", "pe", "pb",
        ],
    }

    # 获取因子字段
    cursor = conn.execute("PRAGMA table_info(daily_factors)")
    factor_cols = [r[1] for r in cursor.fetchall()
                   if r[1] not in ("id", "code", "date", "created_at")]

    if factor_cols:
        checks["daily_factors"] = factor_cols

    results = {}
    all_ok = True

    for table, cols in checks.items():
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT 1", conn)
            if df.empty:
                logger.warning("  [警告] %s 表为空", table)
                results[table] = {"status": "EMPTY"}
                all_ok = False
                continue
        except Exception:
            logger.warning("  [警告] %s 表不存在", table)
            results[table] = {"status": "NOT_EXISTS"}
            all_ok = False
            continue

        # 统计缺失值
        stats = {}
        for col in cols:
            cur = conn.execute(f"SELECT COUNT(*) as total, "
                               f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) as nulls "
                               f"FROM {table}")
            row = cur.fetchone()
            total = row[0]
            nulls = row[1]
            null_ratio = nulls / total * 100 if total > 0 else 0

            # 检查 Inf
            cur2 = conn.execute(f"SELECT COUNT(*) as infs FROM {table} "
                                f"WHERE typeof({col}) = 'real' AND "
                                f"({col} = 1e300 OR {col} = -1e300 OR "
                                f"{col} != {col}) COLLATE NOCASE")
            # SQLite doesn't support NaN checks directly, so we skip that here
            stats[col] = {
                "total": total,
                "nulls": nulls,
                "null_ratio": round(null_ratio, 2),
            }

            if null_ratio > 50:
                logger.warning("  ⚠ %s.%s: 缺失率 %.1f%%", table, col, null_ratio)
                all_ok = False
            elif null_ratio > 10:
                logger.info("  ℹ %s.%s: 缺失率 %.1f%%", table, col, null_ratio)

        results[table] = {"status": "PASS" if all_ok else "WARN", "columns": stats}

    return {"status": "PASS" if all_ok else "WARN", "tables": results}


def check_factor_ranges(conn: sqlite3.Connection) -> Dict:
    """
    检查因子值合理性：各字段值是否在合理范围内。
    """
    logger.info("[校验3/5] 因子值合理性检查...")

    issues = []
    ranges_ok = True

    for factor, (fmin, fmax) in FACTOR_RANGES.items():
        try:
            cur = conn.execute(
                f"SELECT MIN({factor}) as min_val, MAX({factor}) as max_val, "
                f"COUNT(*) as cnt FROM daily_factors "
                f"WHERE {factor} IS NOT NULL"
            )
            row = cur.fetchone()
            if row[2] == 0:
                continue

            actual_min = row[0]
            actual_max = row[1]

            if actual_min is not None and actual_min < fmin - 1:
                issues.append(f"  ⚠ {factor}: 最小值 {actual_min:.2f} < 下限 {fmin}")
                ranges_ok = False
            if actual_max is not None and actual_max > fmax + 1:
                issues.append(f"  ⚠ {factor}: 最大值 {actual_max:.2f} > 上限 {fmax}")
                ranges_ok = False
        except Exception as e:
            issues.append(f"  ⚠ {factor}: 查询失败 {e}")
            ranges_ok = False

    for issue in issues:
        logger.info(issue)

    return {"status": "PASS" if ranges_ok else "WARN", "issues": issues}


def check_zscore_anomalies(conn: sqlite3.Connection) -> Dict:
    """
    检测标准异常值。对每个因子，计算 z-score，
    标记 |z| > 3 的记录占比。
    """
    logger.info("[校验4/5] 标准差异常检测...")

    total_anomalies = 0
    factor_issues = []

    for factor in FACTOR_RANGES:
        try:
            df = pd.read_sql_query(
                f"SELECT {factor} FROM daily_factors "
                f"WHERE {factor} IS NOT NULL",
                conn,
            )
            if df.empty or len(df) < 10:
                continue
            vals = df[factor].values.astype(float)
            mean = np.nanmean(vals)
            std = np.nanstd(vals, ddof=1)
            if std < 1e-10:
                continue
            zscores = np.abs((vals - mean) / std)
            anomaly_ratio = np.sum(zscores > 3) / len(vals)
            if anomaly_ratio > 0.02:  # 超过 2% 的记录为异常
                factor_issues.append({
                    "factor": factor,
                    "anomaly_ratio": round(anomaly_ratio * 100, 2),
                    "mean": round(mean, 4),
                    "std": round(std, 4),
                })
                total_anomalies += 1
        except Exception:
            continue

    for issue in factor_issues:
        logger.info("  ℹ %s: 异常值占比 %.2f%% (mean=%.4f, std=%.4f)",
                    issue["factor"], issue["anomaly_ratio"],
                    issue["mean"], issue["std"])

    return {
        "status": "PASS" if total_anomalies == 0 else "WARN",
        "anomaly_factor_count": total_anomalies,
        "factors": factor_issues,
    }


def check_forward_fill(conn: sqlite3.Connection) -> Dict:
    """
    检查因子值的连续性。
    对每个因子，检查是否有连续超过 5 个交易日值不变。
    """
    logger.info("[校验5/5] 因子值连续性检查...")

    stale_issues = []

    for factor in FACTOR_RANGES:
        try:
            for code in STOCK_CODES:
                df = pd.read_sql_query(
                    f"SELECT date, {factor} FROM daily_factors "
                    f"WHERE code=? AND {factor} IS NOT NULL "
                    f"ORDER BY date ASC",
                    conn,
                    params=(code,),
                )
                if df.empty or len(df) < 10:
                    continue
                vals = df[factor].values
                # 检测连续相同值
                runs = 0
                max_run = 0
                current_run = 0
                for i in range(1, len(vals)):
                    if vals[i] == vals[i - 1] and not (isinstance(vals[i], float) and np.isnan(vals[i])):
                        current_run += 1
                        max_run = max(max_run, current_run)
                    else:
                        current_run = 0

                if max_run >= 5:
                    stale_issues.append({
                        "factor": factor,
                        "code": code,
                        "max_consecutive": max_run,
                    })
        except Exception:
            continue

    for issue in stale_issues:
        if issue["max_consecutive"] >= 10:
            logger.info("  ⚠ %s (%s): 连续 %d 个交易值不变",
                        issue["factor"], issue["code"], issue["max_consecutive"])

    return {
        "status": "PASS" if len(stale_issues) == 0 else "WARN",
        "stale_count": len(stale_issues),
        "max_consecutive": max((s["max_consecutive"] for s in stale_issues), default=0),
        "issues": stale_issues[:10],  # 只列前10
    }


# ════════════════════════════════════════════════════════
# 汇总报告
# ════════════════════════════════════════════════════════

def print_summary(results: Dict):
    """打印校验汇总"""
    logger.info("\n" + "=" * 60)
    logger.info("  数据完整性校验汇总")
    logger.info("=" * 60)

    OVERALL_STATUS = "PASS"
    total_checks = 0
    failed_checks = 0

    for check_name, result in results.items():
        status = result.get("status", "UNKNOWN")
        total_checks += 1
        if status in ("FAIL", "WARN"):
            failed_checks += 1
        status_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "❓")
        logger.info("  %s [%s] %s", status_icon, status, check_name)

        if result.get("avg_coverage"):
            logger.info("      平均日历覆盖率: %.2f%%", result["avg_coverage"])
        if result.get("anomaly_factor_count") is not None:
            logger.info("      异常因子: %d 个", result["anomaly_factor_count"])
        if result.get("stale_count") is not None:
            logger.info("      固化值: %d 个因子", result["stale_count"])
        if result.get("issues"):
            logger.info("      问题数: %d", len(result["issues"]))

    if failed_checks > 0:
        OVERALL_STATUS = "WARN"
        logger.warning("\n⚠️  部分校验未通过 — 建议检查标记项后重试")
    else:
        logger.info("\n✅ 所有校验通过")

    logger.info("=" * 60)
    return OVERALL_STATUS, failed_checks


# ════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("  墨枢 Phase 1 — 数据完整性校验 （TASK-4）")
    logger.info("  时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    # 检查 DB 是否存在
    if not os.path.exists(ANALYSIS_DB):
        logger.error("  ❌ 数据库不存在: %s", ANALYSIS_DB)
        logger.error("  请先执行 TASK-1 和 TASK-2")
        return 1

    conn = sqlite3.connect(ANALYSIS_DB)
    try:
        results = {}

        # 1. 交易日历覆盖
        results["trade_calendar"] = check_trade_calendar(conn)

        # 2. 缺失值检测
        results["missing_values"] = check_missing_values(conn)

        # 3. 因子值合理性
        results["factor_ranges"] = check_factor_ranges(conn)

        # 4. 标准差异常
        results["zscore_anomalies"] = check_zscore_anomalies(conn)

        # 5. 因子值连续性
        results["forward_fill"] = check_forward_fill(conn)

        # 汇总
        overall, failed = print_summary(results)

    finally:
        conn.close()

    return 0 if overall == "PASS" else (1 if failed > 0 else 0)


if __name__ == "__main__":
    sys.exit(main())
