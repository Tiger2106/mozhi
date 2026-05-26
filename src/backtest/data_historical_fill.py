#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
data_historical_fill.py — 历史日K数据批量采集脚本

用途：
  采集 A 股历史行情数据并灌入 analysis.db 的 stock_daily 表，
  使回测覆盖周期从当前的 2023-01-03→2026-05-14 扩展到 2020-01 至今。

依赖：
  - mozhi_platform/src/backtest/data_source.py (AkshareDataSource)
  - mozhi_platform/src/backtest/data_loader.py  (populate_stock_daily)

用法：
  cd mozhi_platform
  python -m src.backtest.data_historical_fill

author: moheng
created_time: 2026-05-16 07:01 +08:00
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

# ── 项目根路径注入（确保 from backtest.* 可导入） ──
_THIS_DIR = Path(__file__).resolve().parent          # src/backtest/
_PROJECT_ROOT = _THIS_DIR.parent.parent              # mozhi_platform/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backtest.data_loader import populate_stock_daily

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 采集配置 ──────────────────────────────────────────────

STOCKS: List[str] = [
    "601857",   # 中国石油
    "600519",   # 贵州茅台
    "000001",   # 平安银行
]

START_DATE: str = "20200101"
END_DATE: str = datetime.now(timezone.utc).strftime("%Y%m%d")  # 今日

CHUNK_INTERVAL_DAYS: int = 180     # 每块 ~6 个月，避免 API 超时
BETWEEN_CHUNK_SLEEP: float = 1.0   # 块间休眠（秒），缓解限流


# ── 工具函数 ──────────────────────────────────────────────

def _chunk_dates(start: str, end: str, interval_days: int) -> List[Tuple[str, str]]:
    """将 [start, end] 按 interval_days 分割成连续子区间（YYYYMMDD）"""
    from datetime import datetime, timedelta

    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    chunks: List[Tuple[str, str]] = []
    cur = s
    while cur <= e:
        nxt = min(cur + timedelta(days=interval_days), e)
        chunks.append((cur.strftime("%Y%m%d"), nxt.strftime("%Y%m%d")))
        cur = nxt + timedelta(days=1)
    return chunks


def _verify_coverage(db_path: str) -> dict:
    """验证并返回各标的 coverage 统计"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    result = {}
    for code in STOCKS:
        cur.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM stock_daily WHERE code=?",
            (code,),
        )
        row = cur.fetchone()
        result[code] = {
            "min_date": row[0],
            "max_date": row[1],
            "count": row[2],
        }

    conn.close()
    return result


# ── 主流程 ──────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("墨枢历史行情数据批量采集")
    logger.info(f"标的:   {STOCKS}")
    logger.info(f"范围:   {START_DATE} ~ {END_DATE}")
    logger.info(f"分块:   每块 {CHUNK_INTERVAL_DAYS} 天，块间休眠 {BETWEEN_CHUNK_SLEEP}s")
    logger.info("=" * 60)

    # 1. 生成时间分块
    chunks = _chunk_dates(START_DATE, END_DATE, CHUNK_INTERVAL_DAYS)
    logger.info(f"时间分块数: {len(chunks)}")
    logger.info(f"分块列表: {', '.join(f'{s}~{e}' for s, e in chunks)}")

    # 2. 逐标的逐块采集
    total_written = 0
    error_symbols: List[str] = []

    for symbol in STOCKS:
        logger.info(f"\n>>> 开始采集 [{symbol}]")
        symbol_written = 0

        for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
            try:
                written = populate_stock_daily(
                    symbol=symbol,
                    start_date=chunk_start,
                    end_date=chunk_end,
                )
                symbol_written += written
                logger.info(
                    f"  [{symbol}] chunk {i:02d}/{len(chunks):02d} "
                    f"{chunk_start}~{chunk_end} → {written} 条"
                )
            except Exception as e:
                logger.warning(
                    f"  [{symbol}] chunk {i:02d}/{len(chunks):02d} "
                    f"失败: {type(e).__name__}: {e}，跳过"
                )

            # 块间等待
            if i < len(chunks):
                time.sleep(BETWEEN_CHUNK_SLEEP)

        total_written += symbol_written
        logger.info(f"<<< [{symbol}] 合计写入 {symbol_written} 条")

        # 各标的中途验证
        db_path = Path(__file__).resolve().parent.parent.parent / "data" / "market" / "market_data.db"
        default_db = str(db_path)
        coverage = _verify_coverage(default_db)
        c = coverage.get(symbol, {})
        logger.info(f"  [{symbol}] 当前覆盖: {c.get('min_date','')} ~ {c.get('max_date','')}, {c.get('count',0)} 行")

    # 3. 最终验证
    logger.info(f"\n{'=' * 60}")
    logger.info(f"采集完成！总计写入 {total_written} 条记录")

    final_path = str(
        Path(__file__).resolve().parent.parent.parent /
        "data" / "market" / "market_data.db"
    )
    coverage = _verify_coverage(final_path)

    print()
    print("=" * 60)
    print("最终数据覆盖验证")
    print("=" * 60)
    all_ok = True
    for code, info in coverage.items():
        min_d = info["min_date"]
        max_d = info["max_date"]
        cnt = info["count"]
        # 检查是否覆盖到 2021-01-01 之前
        has_2021 = min_d is not None and min_d <= "20210101"
        has_2020 = min_d is not None and min_d <= "20200131"
        status = "✅" if has_2021 else "❌"
        info_str = f"{code}: {min_d} ~ {max_d}  ({cnt}行)"
        info_str += f"  覆盖2021={'是' if has_2021 else '否'}"
        info_str += f"  覆盖2020={'是' if has_2020 else '否'}"
        print(f"  {status} {info_str}")
        if not has_2021:
            all_ok = False

    if all_ok:
        print("\n✅ 所有标的均覆盖到 2021-01-01 之前，满足要求。")
    else:
        print("\n⚠️ 部分标的未覆盖到 2021-01-01，需手动检查。")

    return all_ok


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
