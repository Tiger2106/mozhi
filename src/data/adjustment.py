"""
后复权价格计算 + pre_close 一致性校验（§3.1.3）

功能：
  1. 从 a50_daily_ohlcv 读取日线数据（通过 DatabaseManager 参数注入）
  2. 基于 adj_factor 计算后复权价格（adj_*_b 字段）
  3. 计算一致性比率，判断复权数据是否有断裂
  4. 数据写入 backfill 至 a50_daily_ohlcv 表：
     adj_close_b / adj_open_b / adj_high_b / adj_low_b / adj_pre_close_b
  5. 输出一致性检测报告（含断裂日期列表）

验收标准（IC_PIPELINE_T14_003）：
  - 后复权价格 = close × adj_factor
  - 所有交易日 after-rev 价格可回溯一致
  - pre_close 校验偏差率 < 0.1%
  - 偏差 > 0.1% 的交易日被记录并告警

校验说明（req_draft_v2.1 §3.1.3）：
  原始校验公式 adj_factor[t]/adj_factor[t-1] ≈ close[t]/pre_close[t] 在 pre_close
  由同一 adj_factor 链生成时恒成立、构成循环论证，v2.0 已废弃。
  改用直接比对：adj_pre_close_b[t] ≈ adj_close_b[t-1]，偏差率 < 0.1%。

用法：
    from src.db.connection import get_manager
    from src.data.adjustment import compute_backward_adjusted

    mgr = get_manager()
    with mgr.get() as conn:
        result = compute_backward_adjusted(conn)

Author: 墨衡
Created: 2026-05-30T09:50:00+08:00
"""

import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# 常量
# ════════════════════════════════════════════════════════════

# 后复权字段定义
BACKFILL_COLUMNS = [
    "adj_close_b",
    "adj_open_b",
    "adj_high_b",
    "adj_low_b",
    "adj_pre_close_b",
]

# 后复权字段对应的原始字段
BACKFILL_MAP = {
    "adj_close_b": "close",
    "adj_open_b": "open",
    "adj_high_b": "high",
    "adj_low_b": "low",
    "adj_pre_close_b": "pre_close",
}

# 一致性偏差阈值（0.1%）
CONSISTENCY_THRESHOLD = 0.001

# 批量处理大小
BATCH_SIZE = 10000


# ════════════════════════════════════════════════════════════
# Schema 变更
# ════════════════════════════════════════════════════════════

def ensure_backfill_columns(conn: sqlite3.Connection) -> list[str]:
    """确保 a50_daily_ohlcv 表存在后复权字段，不存在则 ADD COLUMN。

    Returns:
        实际新增的列名列表
    """
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(a50_daily_ohlcv)").fetchall()
    }

    added = []
    for col in BACKFILL_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE a50_daily_ohlcv ADD COLUMN {col} REAL")
            added.append(col)
            logger.info("ADD COLUMN %s to a50_daily_ohlcv", col)

    if added:
        logger.info("Backfill columns added: %s", added)
    else:
        logger.info("All backfill columns already exist")

    return added


# ════════════════════════════════════════════════════════════
# 核心计算
# ════════════════════════════════════════════════════════════

def compute_backward_adjusted(
    conn: sqlite3.Connection,
    batch_size: int = BATCH_SIZE,
    skip_suspended: bool = True,
) -> dict:
    """计算后复权价格并写入 a50_daily_ohlcv 表。

    后复权价格 = 原始价格 × adj_factor

    Args:
        conn:          SQLite 连接（须已设置 PRAGMA foreign_keys=ON）
        batch_size:    每批处理行数
        skip_suspended: 是否跳过错停牌日期（停牌日的 NULL 价格复权后仍为 NULL）

    Returns:
        写入统计字典
    """
    start_time = time.time()

    # ── 1. 确保 backfill 列存在 ──
    ensure_backfill_columns(conn)

    # ── 2. 统计需要处理的数据量 ──
    total = conn.execute(
        "SELECT COUNT(*) FROM a50_daily_ohlcv WHERE adj_factor IS NOT NULL"
    ).fetchone()[0]

    if total == 0:
        logger.warning("No data to process (all adj_factor are NULL)")
        return {
            "total": 0,
            "updated": 0,
            "null_adj_factor": 0,
            "elapsed_seconds": 0.0,
        }

    # ── 3. 逐批读取、计算、更新 ──
    # 使用 ROWID 进行高效分页（比 OFFSET 快）
    min_rowid = conn.execute(
        "SELECT MIN(id) FROM a50_daily_ohlcv WHERE adj_factor IS NOT NULL"
    ).fetchone()[0]
    max_rowid = conn.execute(
        "SELECT MAX(id) FROM a50_daily_ohlcv WHERE adj_factor IS NOT NULL"
    ).fetchone()[0]

    updated = 0
    null_adj_count = 0
    null_price_counts = {col: 0 for col in BACKFILL_COLUMNS}

    sql_select = """
        SELECT id, ts_code, trade_date,
               open, high, low, close, pre_close, adj_factor,
               null_reason
        FROM a50_daily_ohlcv
        WHERE adj_factor IS NOT NULL
          AND id >= ? AND id < ?
        ORDER BY id
    """

    sql_update = """
        UPDATE a50_daily_ohlcv
        SET adj_close_b = ?,
            adj_open_b = ?,
            adj_high_b = ?,
            adj_low_b = ?,
            adj_pre_close_b = ?
        WHERE id = ?
    """

    current_start = min_rowid
    conn.execute("BEGIN TRANSACTION")
    try:
        while current_start <= max_rowid:
            current_end = current_start + batch_size
            rows = conn.execute(sql_select, (current_start, current_end)).fetchall()

            if not rows:
                current_start = current_end
                continue

            batch_data = []
            for row in rows:
                adj_factor = row["adj_factor"]

                # 停牌日的 price 字段可能为 NULL
                close_val = row["close"]
                open_val = row["open"]
                high_val = row["high"]
                low_val = row["low"]
                pre_close_val = row["pre_close"]

                # 计算后复权（仅当原始值非 NULL 时计算）
                adj_close = close_val * adj_factor if close_val is not None else None
                adj_open = open_val * adj_factor if open_val is not None else None
                adj_high = high_val * adj_factor if high_val is not None else None
                adj_low = low_val * adj_factor if low_val is not None else None
                adj_pre_close = (
                    pre_close_val * adj_factor if pre_close_val is not None else None
                )

                # 统计 NULL 数量
                if adj_close is None:
                    null_price_counts["adj_close_b"] += 1
                if adj_open is None:
                    null_price_counts["adj_open_b"] += 1
                if adj_high is None:
                    null_price_counts["adj_high_b"] += 1
                if adj_low is None:
                    null_price_counts["adj_low_b"] += 1
                if adj_pre_close is None:
                    null_price_counts["adj_pre_close_b"] += 1

                batch_data.append((
                    adj_close, adj_open, adj_high, adj_low, adj_pre_close,
                    row["id"],
                ))

            conn.executemany(sql_update, batch_data)
            updated += len(rows)

            if (current_start + batch_size) % (batch_size * 5) == 0:
                logger.info(
                    "  Progress: %d / %d rows (%.1f%%)",
                    min(updated, total), total,
                    min(100.0, updated / total * 100),
                )

            current_start = current_end

        conn.commit()
        elapsed = time.time() - start_time
        logger.info(
            "Backward adjustment complete: updated=%d, elapsed=%.2fs",
            updated, elapsed,
        )
    except Exception as e:
        conn.rollback()
        logger.error("Backward adjustment FAILED: %s", e)
        raise

    return {
        "total": total,
        "updated": updated,
        "null_adj_factor_count": null_adj_count,
        "null_prices": null_price_counts,
        "elapsed_seconds": round(elapsed, 2),
    }


# ════════════════════════════════════════════════════════════
# 一致性校验
# ════════════════════════════════════════════════════════════

def check_consistency(
    conn: sqlite3.Connection,
    threshold: float = CONSISTENCY_THRESHOLD,
    batch_size: int = BATCH_SIZE,
) -> dict:
    """校验后复权数据一致性。

    校验方法（§3.1.3 v2.0 修正公式）：
      对于每个成分股，对连续交易日 (t-1, t) 校验：
        adj_pre_close_b[t] ≈ adj_close_b[t-1]  →  偏差率 < threshold

    其中：
      adj_pre_close_b[t] = pre_close[t] × adj_factor[t]
      adj_close_b[t-1]  = close[t-1] × adj_factor[t-1]

      偏差率 = |adj_pre_close_b[t] / adj_close_b[t-1] - 1|
      偏差率 < 0.001 (0.1%) 视为一致

    Args:
        conn:     SQLite 连接
        threshold: 偏差阈值（默认 0.001 = 0.1%）
        batch_size: 每批处理股票数

    Returns:
        {
            "passed": True/False,          # 全部一致？
            "total_pairs": N,              # 检查的连续交易对数量
            "breach_pairs": N,             # 偏差超限的对数
            "breach_ratio": 0.0,           # 偏差超限比例
            "max_deviation": 0.0,          # 最大偏差率
            "breach_details": [...],       # 偏差超限详情（前 100 条）
            "stocks_checked": N,
            "stocks_with_breaches": N,
        }
    """
    start_time = time.time()

    # ── 1. 确认后复权列已存在 ──
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(a50_daily_ohlcv)").fetchall()
    }
    for col in ["adj_close_b", "adj_pre_close_b"]:
        if col not in existing:
            raise RuntimeError(
                f"Backfill column '{col}' does not exist. "
                "Run compute_backward_adjusted() first."
            )

    # ── 2. 获取所有成分股代码 ──
    codes = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT ts_code FROM a50_daily_ohlcv ORDER BY ts_code"
        ).fetchall()
    ]

    total_pairs = 0
    breach_pairs = 0
    max_deviation = 0.0
    breaches = []
    stocks_with_breaches = set()

    # ── 3. 逐成分股校验 ──
    for code in codes:
        rows = conn.execute(
            """
            SELECT trade_date, close, pre_close, adj_factor,
                   adj_close_b, adj_pre_close_b
            FROM a50_daily_ohlcv
            WHERE ts_code = ?
              AND adj_close_b IS NOT NULL
              AND adj_pre_close_b IS NOT NULL
            ORDER BY trade_date
            """,
            (code,),
        ).fetchall()

        if len(rows) < 2:
            continue

        for i in range(1, len(rows)):
            prev = rows[i - 1]
            curr = rows[i]

            adj_close_prev = prev["adj_close_b"]
            adj_pre_close_curr = curr["adj_pre_close_b"]

            if adj_close_prev is None or adj_close_prev == 0:
                continue
            if adj_pre_close_curr is None:
                continue

            # 偏差率 = |adj_pre_close_b[t] / adj_close_b[t-1] - 1|
            deviation = abs(adj_pre_close_curr / adj_close_prev - 1.0)
            total_pairs += 1

            if deviation > max_deviation:
                max_deviation = deviation

            if deviation > threshold:
                breach_pairs += 1
                stocks_with_breaches.add(code)

                if len(breaches) < 100:  # 最多记录 100 条
                    breaches.append({
                        "ts_code": code,
                        "trade_date": curr["trade_date"],
                        "prev_date": prev["trade_date"],
                        "adj_close_prev": round(adj_close_prev, 6),
                        "adj_pre_close_curr": round(adj_pre_close_curr, 6),
                        "deviation": round(deviation, 8),
                        "raw_close_prev": round(prev["close"], 4),
                        "raw_pre_close_curr": round(curr["pre_close"], 4),
                        "adj_factor_prev": round(prev["adj_factor"], 6),
                        "adj_factor_curr": round(curr["adj_factor"], 6),
                    })

    elapsed = time.time() - start_time
    breach_ratio = breach_pairs / total_pairs if total_pairs > 0 else 0.0
    passed = breach_pairs == 0

    logger.info(
        "Consistency check: total_pairs=%d, breaches=%d (%.4f%%), "
        "max_deviation=%.6f, stocks_with_breaches=%d, elapsed=%.2fs",
        total_pairs, breach_pairs, breach_ratio * 100,
        max_deviation, len(stocks_with_breaches), elapsed,
    )

    return {
        "passed": passed,
        "total_pairs": total_pairs,
        "breach_pairs": breach_pairs,
        "breach_ratio": round(breach_ratio, 8),
        "max_deviation": round(max_deviation, 8),
        "threshold": threshold,
        "breach_details": breaches,
        "stocks_checked": len(codes),
        "stocks_with_breaches": sorted(stocks_with_breaches),
        "elapsed_seconds": round(elapsed, 2),
    }


def compute_consistency_ratio_report(
    conn: sqlite3.Connection,
) -> dict:
    """计算一致性比率并按股票、日期维度输出综合报告。

    一致性比率（按 subtask 描述）：
      consistency_ratio = adj_factor × pre_close / close

    对于每个股票，按交易日排序，检查 consistency_ratio 的逐日波动。
    """
    codes = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT ts_code FROM a50_daily_ohlcv ORDER BY ts_code"
        ).fetchall()
    ]

    all_ratios = []
    stock_summaries = []

    for code in codes:
        rows = conn.execute(
            """
            SELECT trade_date, close, pre_close, adj_factor
            FROM a50_daily_ohlcv
            WHERE ts_code = ?
              AND close IS NOT NULL
              AND close != 0
              AND pre_close IS NOT NULL
              AND adj_factor IS NOT NULL
            ORDER BY trade_date
            """,
            (code,),
        ).fetchall()

        if len(rows) < 2:
            continue

        ratios = []
        for row in rows:
            ratio = row["adj_factor"] * row["pre_close"] / row["close"]
            ratios.append({
                "trade_date": row["trade_date"],
                "consistency_ratio": round(ratio, 6),
            })
            all_ratios.append({
                "ts_code": code,
                "trade_date": row["trade_date"],
                "consistency_ratio": round(ratio, 6),
            })

        # 逐日波动检查
        max_fluctuation = 0.0
        fluctuation_count = 0
        for i in range(1, len(ratios)):
            prev_r = ratios[i - 1]["consistency_ratio"]
            curr_r = ratios[i]["consistency_ratio"]
            if prev_r != 0:
                fluct = abs(curr_r / prev_r - 1.0)
                if fluct > max_fluctuation:
                    max_fluctuation = fluct
                if fluct > CONSISTENCY_THRESHOLD:
                    fluctuation_count += 1

        stock_summaries.append({
            "ts_code": code,
            "trading_days": len(ratios),
            "max_fluctuation": round(max_fluctuation, 8),
            "fluctuation_count": fluctuation_count,
            "fluctuation_ratio": round(
                fluctuation_count / max(len(ratios) - 1, 1), 6
            ),
            "ratio_mean": round(
                sum(r["consistency_ratio"] for r in ratios) / len(ratios), 6
            ),
        })

    # 全局统计
    if all_ratios:
        all_vals = [r["consistency_ratio"] for r in all_ratios]
        global_mean = sum(all_vals) / len(all_vals)
        global_max = max(all_vals)
        global_min = min(all_vals)
    else:
        global_mean = global_max = global_min = 0.0

    stocks_with_issues = [
        s for s in stock_summaries if s["fluctuation_count"] > 0
    ]

    return {
        "global_stats": {
            "mean_ratio": round(global_mean, 6),
            "min_ratio": round(global_min, 6),
            "max_ratio": round(global_max, 6),
            "total_records": len(all_ratios),
        },
        "stocks_summary": stock_summaries,
        "stocks_with_fluctuations": stocks_with_issues,
        "detailed_ratios": all_ratios,
    }


# ════════════════════════════════════════════════════════════
# 完整执行流程
# ════════════════════════════════════════════════════════════

def run_adjustment_pipeline(conn: sqlite3.Connection) -> dict:
    """执行完整的后复权计算 + 一致性校验流水线。

    Args:
        conn: SQLite 连接（须已设置 PRAGMA foreign_keys=ON）

    Returns:
        {
            "status": "SUCCESS" | "FAILED",
            "task": "后复权+一致性校验",
            "backfill": {...},       # 复权写入统计
            "consistency": {...},     # 一致性校验结果
            "report": {...},          # 一致性比率报告
            "timestamp": "...",
        }
    """
    logger.info("=" * 60)
    logger.info("后复权计算 + 一致性校验管线")
    logger.info("=" * 60)

    try:
        # Step 1: 后复权价格计算与写入
        logger.info("\n[Step 1/3] 后复权价格计算...")
        backfill_result = compute_backward_adjusted(conn)

        # Step 2: 一致性校验（跨日对比）
        logger.info("\n[Step 2/3] 一致性校验（跨日对比）...")
        consistency_result = check_consistency(conn)

        # Step 3: 一致性比率报告
        logger.info("\n[Step 3/3] 一致性比率报告生成...")
        ratio_report = compute_consistency_ratio_report(conn)

        # ── 输出摘要 ──
        logger.info("=" * 60)
        logger.info("管线执行摘要")
        logger.info("  Updated rows: %d", backfill_result["updated"])
        logger.info("  Consistency check: %s (breaches: %d / %d)",
                     "✅ PASS" if consistency_result["passed"] else "❌ FAIL",
                     consistency_result["breach_pairs"],
                     consistency_result["total_pairs"])
        logger.info("  Max deviation: %.6f%%",
                     consistency_result["max_deviation"] * 100)
        logger.info("=" * 60)

        return {
            "status": "SUCCESS",
            "task": "后复权+一致性校验",
            "backfill": backfill_result,
            "consistency": consistency_result,
            "report": ratio_report,
            "timestamp": datetime.now(
                timezone(timedelta(hours=8))
            ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    except Exception as e:
        logger.error("Pipeline FAILED: %s", e, exc_info=True)
        return {
            "status": "FAILED",
            "task": "后复权+一致性校验",
            "error": str(e),
            "timestamp": datetime.now(
                timezone(timedelta(hours=8))
            ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        }


# ════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════

def main():
    import argparse
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    parser = argparse.ArgumentParser(
        description="后复权价格计算 + pre_close 一致性校验"
    )
    parser.add_argument(
        "--db",
        default=r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db",
        help="数据库路径",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="一致性报告输出路径（JSON）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细日志输出",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from src.db.connection import get_manager

    mgr = get_manager(db_path=args.db)
    conn = mgr.get()

    try:
        result = run_adjustment_pipeline(conn)

        print("\n--- 后复权管线结果 ---")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if args.output:
            os.makedirs(os.path.dirname(args.output), exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logger.info("报告写入: %s", args.output)

        return 0 if result["status"] == "SUCCESS" else 1

    finally:
        mgr.put(conn)


if __name__ == "__main__":
    sys.exit(main())
