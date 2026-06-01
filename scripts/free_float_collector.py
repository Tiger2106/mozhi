#!/usr/bin/env python3
"""
EXP-2026-004-AVGTRD — free_float 采集验证试验
==============================================
Author: 墨衡 (moheng)
Created: 2026-05-28T18:28+08:00

用途: 从 Tushare Pro 采集 A50 全池的 free_float_share 和 float_share 数据，
     验证数据质量，并回填到 market_data.db。

接口选择说明:
  - pro.daily() 支持字段: float_share, free_float_share (以 daily_basic 接口为准)
  - pro.daily_basic() 支持字段: float_share, free_share, free_float_share
  - 优先使用 daily_basic，需要确认字段是否存在

进度: 
  [1] 验证 daily_basic 和 daily 接口字段可用性
  [2] 设计采样并收集
  [3] 验证质量
  [4] 写入 DB
"""

import os
import sys
import json
import time
import sqlite3
import logging
from datetime import datetime

import tushare as ts

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

# === Config ===
TUSHARE_TOKEN = "09e84b0b5fe40141f51a0aecb21ba648f605bf421444c2d741271ded"
DB_PATH = r"C:\Users\17699\mozhi_platform\data\market\market_data.db"
REQUEST_INTERVAL = 0.35  # seconds between calls (Tushare 200/min limit)

# A50 Constituent Stocks (combined from phase1 list + A50_data_prep_check.md missing list)
# 11 stocks from phase1 that are A50 + 35 unique from missing 39 list = 46 (+ delisted replacement)
A50_STOCKS = [
    # From phase1 collection (A50 constituents only)
    "601857.SH",  # 中国石油
    "000001.SZ",  # 平安银行
    "600519.SH",  # 贵州茅台
    "601318.SH",  # 中国平安
    "600036.SH",  # 招商银行
    "300750.SZ",  # 宁德时代
    "002415.SZ",  # 海康威视
    # A50 missing list - Batch 1: 银行
    "601398.SH",  # 工商银行
    "601939.SH",  # 建设银行
    "600000.SH",  # 浦发银行
    "601328.SH",  # 交通银行
    "601288.SH",  # 农业银行
    "601988.SH",  # 中国银行
    "002142.SZ",  # 宁波银行
    # A50 missing list - Batch 2: 消费/食品
    "000568.SZ",  # 泸州老窖
    "002304.SZ",  # 洋河股份
    "600690.SH",  # 海尔智家
    # A50 missing list - Batch 3: 医药/科技
    "000538.SZ",  # 云南白药
    "002049.SZ",  # 紫光国微
    "002230.SZ",  # 科大讯飞
    "300059.SZ",  # 东方财富
    "300124.SZ",  # 汇川技术
    "300782.SZ",  # 卓胜微
    "688981.SH",  # 中芯国际
    "002916.SZ",  # 深南电路
    "300274.SZ",  # 阳光电源
    # A50 missing list - Batch 4: 制造/周期
    "601088.SH",  # 中国神华
    "600585.SH",  # 海螺水泥
    "600019.SH",  # 宝钢股份
    "000100.SZ",  # TCL科技
    "600372.SH",  # 中航机载（替代已退市的002013.SZ）
    "002129.SZ",  # TCL中环
    "000725.SZ",  # 京东方A
    "002352.SZ",  # 顺丰控股
    "000651.SZ",  # 格力电器
    # A50 missing list - Batch 5: 地产/金融
    "000002.SZ",  # 万科A
    "002714.SZ",  # 牧原股份
    "600104.SH",  # 上汽集团
    "601166.SH",  # 兴业银行
    "601668.SH",  # 中国建筑
    # A50 missing list - Batch 6: 其他
    "600028.SH",  # 中国石化
    "600016.SH",  # 民生银行
    # Also in phase1, already deduped above
    # 600276.SH (恒瑞医药) - deduped, in batch 3
    # 600887.SH (伊利股份) - deduped, in batch 2
    # 000333.SZ (美的集团) - deduped, in batch 4
    # 600030.SH (中信证券) - deduped, in batch 6
]

# Also include overlapping stocks explicitly (ensure sampling)
OVERLAP = [
    "600276.SH",  # 恒瑞医药（在phase1和batch3中都有）
    "600887.SH",  # 伊利股份（在phase1和batch2中都有）
    "000333.SZ",  # 美的集团（在phase1和batch4中都有）
    "600030.SH",  # 中信证券（在phase1和batch6中都有）
]

# Deduplicate
ALL_STOCKS = list(dict.fromkeys(A50_STOCKS + OVERLAP))
logger.info("Total A50 stocks to collect: %d", len(ALL_STOCKS))


def test_api_fields():
    """Step 1: Test which API and fields provide free_float data"""
    pro = ts.pro_api()

    # Test daily_basic with free_share field
    logger.info("Testing daily_basic fields...")
    try:
        df = pro.daily_basic(
            ts_code="601857.SH",
            start_date="20260520",
            end_date="20260526",
            fields="ts_code,trade_date,float_share,free_share,free_float_share",
        )
        logger.info("daily_basic columns: %s", df.columns.tolist() if df is not None else "None")
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                logger.info("  %s | %s | float=%.2f | free=%.2f | free_float=%.2f",
                           r.get('ts_code',''), r.get('trade_date',''),
                           r.get('float_share', -1) or -1,
                           r.get('free_share', -1) or -1,
                           r.get('free_float_share', -1) or -1)
    except Exception as e:
        logger.warning("daily_basic with free_share failed: %s", e)
        # Fall back to fewer fields
        try:
            df = pro.daily_basic(
                ts_code="601857.SH",
                start_date="20260520",
                end_date="20260526",
                fields="ts_code,trade_date,float_share,free_share",
            )
            logger.info("Fallback daily_basic columns: %s", df.columns.tolist())
        except Exception as e2:
            logger.error("Fallback also failed: %s", e2)

    # Test daily API
    logger.info("Testing daily API with free_float fields...")
    try:
        df = pro.daily(
            ts_code="601857.SH",
            start_date="20260520",
            end_date="20260526",
            fields="ts_code,trade_date,vol,amount,float_share,free_float_share",
        )
        logger.info("daily columns: %s", df.columns.tolist() if df is not None else "None")
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                logger.info("  %s | %s | float=%.2f | free_float=%.2f",
                           r.get('ts_code',''), r.get('trade_date',''),
                           r.get('float_share', -1) or -1,
                           r.get('free_float_share', -1) or -1)
    except Exception as e:
        logger.warning("daily with float_share failed: %s", e)

    # Test free_float API (dedicated)
    logger.info("Testing dedicated free_float API...")
    try:
        df = pro.free_float(ts_code="601857.SH", trade_date="20260526")
        logger.info("free_float columns: %s", df.columns.tolist() if df is not None else "None")
        if df is not None and not df.empty:
            logger.info("free_float data: %s", df.to_dict('records'))
    except Exception as e:
        logger.warning("free_float API failed: %s", e)


def collect_free_float(pro, stocks, start_date="20200101", end_date="20260526"):
    """Step 2: Collect float_share and free_float_share for all stocks using daily_basic"""
    
    results = []
    failed = []
    
    for stock in stocks:
        try:
            # Daily_basic with free_float_share
            df = pro.daily_basic(
                ts_code=stock,
                start_date=start_date,
                end_date=end_date,
                fields="ts_code,trade_date,float_share,free_share,free_float_share",
            )
            time.sleep(REQUEST_INTERVAL)
            
            if df is None or df.empty:
                logger.warning("[SKIP] %s - no data returned", stock)
                failed.append(stock)
                continue
            
            records = df.to_dict('records')
            results.extend(records)
            logger.info("[OK] %s - %d rows (float range: %.2f-%.2f, free_float range: %.2f-%.2f)",
                       stock, len(records),
                       min((r['float_share'] for r in records if r.get('float_share')), default=0),
                       max((r['float_share'] for r in records if r.get('float_share')), default=0),
                       min((r.get('free_float_share', 0) or 0 for r in records if r.get('free_float_share')), default=0),
                       max((r.get('free_float_share', 0) or 0 for r in records if r.get('free_float_share')), default=0))
            
        except Exception as e:
            logger.error("[FAIL] %s - %s", stock, e)
            failed.append(stock)
            time.sleep(REQUEST_INTERVAL)
    
    return results, failed


def validate_data(results, failed):
    """Step 3: Validate data quality"""
    
    total = len(results)
    if total == 0:
        logger.error("No data collected, cannot validate")
        return None
    
    # Null analysis
    null_float = sum(1 for r in results if r.get('float_share') is None)
    null_free = sum(1 for r in results if r.get('free_share') is None)
    null_free_float = sum(1 for r in results if r.get('free_float_share') is None)
    
    # Non-null stats
    valid_float = [r['float_share'] for r in results if r.get('float_share') is not None]
    valid_free = [r['free_share'] for r in results if r.get('free_share') is not None]
    valid_free_float = [r['free_float_share'] for r in results if r.get('free_float_share') is not None]
    
    # Logic check: free_float_share should be <= float_share (or equal)
    inconsistencies = 0
    for r in results:
        if r.get('float_share') is not None and r.get('free_float_share') is not None:
            if r['free_float_share'] > r['float_share'] * 1.01:  # Allow 1% tolerance
                inconsistencies += 1
    
    # Distinct stocks and date range
    stocks_set = set(r['ts_code'] for r in results if 'ts_code' in r)
    dates = [r['trade_date'] for r in results if 'trade_date' in r]
    
    report = {
        "total_rows": total,
        "distinct_stocks": len(stocks_set),
        "failed_stocks": failed,
        "stocks_failed": failed,
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "null_analysis": {
            "float_share": {"null_count": null_float, "null_pct": round(null_float/total*100, 2)},
            "free_share": {"null_count": null_free, "null_pct": round(null_free/total*100, 2)},
            "free_float_share": {"null_count": null_free_float, "null_pct": round(null_free_float/total*100, 2)},
        },
        "stats": {
            "float_share": {
                "min": round(min(valid_float), 2) if valid_float else None,
                "max": round(max(valid_float), 2) if valid_float else None,
                "mean": round(sum(valid_float)/len(valid_float), 2) if valid_float else None,
            } if valid_float else None,
            "free_share": {
                "min": round(min(valid_free), 2) if valid_free else None,
                "max": round(max(valid_free), 2) if valid_free else None,
                "mean": round(sum(valid_free)/len(valid_free), 2) if valid_free else None,
            } if valid_free else None,
            "free_float_share": {
                "min": round(min(valid_free_float), 2) if valid_free_float else None,
                "max": round(max(valid_free_float), 2) if valid_free_float else None,
                "mean": round(sum(valid_free_float)/len(valid_free_float), 2) if valid_free_float else None,
            } if valid_free_float else None,
        },
        "logic_consistency": {
            "free_float_greater_than_float_count": inconsistencies,
            "inconsistency_rate": round(inconsistencies/total*100, 4),
        },
    }
    
    return report


def ingest_to_db(conn, results):
    """Step 4: Update market_data.db with collected free_float data"""
    
    # Check if the fields are mapped correctly - daily_basic uses ts_code without .SH/.SZ suffix
    # But stock_daily stores full ts_code format like "601857.SH"
    
    updated = 0
    skipped = 0
    errors = 0
    
    for r in results:
        ts_code = r.get('ts_code', '')
        trade_date = r.get('trade_date', '')
        
        # Ensure full ts_code format (daily_basic returns "601857" without suffix)
        if len(ts_code) <= 6:
            # Need to add suffix - check existing data
            logger.warning("Short ts_code '%s' - guessing suffix, skipping row", ts_code)
            skipped += 1
            continue
        
        float_val = r.get('float_share')
        free_float_val = r.get('free_float_share') or r.get('free_share')  # Try both
        
        if trade_date and ts_code:
            try:
                conn.execute(
                    """UPDATE stock_daily 
                       SET float_share = ?, free_float_share = ?
                       WHERE ts_code = ? AND trade_date = ?""",
                    (float_val, free_float_val, ts_code, trade_date)
                )
                if conn.total_changes > 0:
                    updated += 1
            except Exception as e:
                logger.error("DB update error: %s | %s|%s: %s", e, ts_code, trade_date)
                errors += 1
    
    return updated, skipped, errors


def main():
    logger.info("=" * 60)
    logger.info("EXP-2026-004-AVGTRD: free_float 采集验证试验")
    logger.info("Tushare Pro v%s", ts.__version__)
    logger.info("A50 标的数: %d", len(ALL_STOCKS))
    logger.info("DB: %s", DB_PATH)
    logger.info("=" * 60)
    
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    
    # == Step 1: Test API fields ==
    logger.info("\n>>> Step 1: API 字段测试")
    test_api_fields()
    time.sleep(1)
    
    # == Step 2: Collect data ==
    logger.info("\n>>> Step 2: 批量采集 (A50全池)")
    results, failed = collect_free_float(pro, ALL_STOCKS)
    
    logger.info("\n采集完成: %d rows, %d stocks failed",
               len(results), len(failed))
    if failed:
        logger.warning("失败标的: %s", failed)
    
    # == Step 3: Validate ==
    logger.info("\n>>> Step 3: 数据质量验证")
    report = validate_data(results, failed)
    if report:
        logger.info("验证报告:")
        logger.info("  总行数: %d", report["total_rows"])
        logger.info("  去重标的数: %d", report["distinct_stocks"])
        logger.info("  日期范围: %s ~ %s", report["date_min"], report["date_max"])
        logger.info("  float_share NULL率: %.2f%%", report["null_analysis"]["float_share"]["null_pct"])
        logger.info("  free_share NULL率: %.2f%%", report["null_analysis"]["free_share"]["null_pct"])
        logger.info("  free_float_share NULL率: %.2f%%", report["null_analysis"]["free_float_share"]["null_pct"])
        if report["stats"]["float_share"]:
            logger.info("  float_share: %.2f ~ %.2f (mean=%.2f)",
                       report["stats"]["float_share"]["min"],
                       report["stats"]["float_share"]["max"],
                       report["stats"]["float_share"]["mean"])
        if report["stats"]["free_float_share"]:
            logger.info("  free_float_share: %.2f ~ %.2f (mean=%.2f)",
                       report["stats"]["free_float_share"]["min"],
                       report["stats"]["free_float_share"]["max"],
                       report["stats"]["free_float_share"]["mean"])
        logger.info("  float<free_float 不一致率: %.4f%%",
                   report["logic_consistency"]["inconsistency_rate"])
    
    # == Step 4: Ingest to DB ==
    logger.info("\n>>> Step 4: 回写 market_data.db")
    if results:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        updated, skipped, errors = ingest_to_db(conn, results)
        conn.commit()
        conn.close()
        logger.info("写入完成: %d 行更新, %d 跳过, %d 错误", updated, skipped, errors)
    else:
        logger.warning("无数据可写入")
    
    # Save report
    output = {
        "task": "free_float_collection_verification",
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "status": "COMPLETED" if results else "FAILED",
        "total_collected": len(results),
        "failed_stocks": failed,
        "validation": report,
        "db_ingest": {
            "updated": updated if results else 0,
            "skipped": skipped if results else 0,
            "errors": errors if results else 0,
        }
    }
    
    logger.info("\n>>> 试验完成: %s", output["status"])
    return output


if __name__ == "__main__":
    main()
