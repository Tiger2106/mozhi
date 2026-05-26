"""
date_aligner.py — P1-05 回测起始日期对齐模块

职责：
  1. 从交易日历读取指定市场的交易日序列
  2. 支持多标的统一起始日对齐（找到所有标的共同的起始交易日）
  3. 检查回测起始日是否晚于统一起点，晚则抛出异常

数据源：
  - analysis.db（trading_calendar / stock_daily）
  - trading_calendar.date 格式 'YYYY-MM-DD', is_trading_day ∈ {0, 1}
  - stock_daily.code / stock_daily.date 格式 'YYYYMMDD'

用法示例：
  aligner = DateAligner()
  aligned_start, aligned_end = aligner.align(
      codes=["601857", "600519"],
      start_date="2026-01-01",
      end_date="2026-05-14",
  )
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\analysis.db"
MARKET = "A"  # A股市场
DEFAULT_CODES = ["601857", "600519", "000001"]
DATE_FMT_LONG = "%Y-%m-%d"
DATE_FMT_SHORT = "%Y%m%d"

# ──────────────────────────────────────────────
# 自定义异常
# ──────────────────────────────────────────────

class DateAlignmentError(Exception):
    """回测起始日期对齐相关异常"""
    pass


class LateStartError(DateAlignmentError):
    """
    标的起始日过晚异常。
    当某个标的的第一条可用数据晚于请求的结束日时抛出（无可回测区间）。
    """
    def __init__(self, code: str, earliest_date: str, end_date: str):
        self.code = code
        self.earliest_date = earliest_date
        self.end_date = end_date
        super().__init__(
            f"标的 [{code}] 最早可用数据日为 {earliest_date}，"
            f"晚于回测结束日 {end_date}，无可回测区间"
        )


class NoCommonStartError(DateAlignmentError):
    """多个标的之间无共同起始交易日"""
    def __init__(self, codes: List[str], details: Dict[str, Optional[str]]):
        self.codes = codes
        self.details = details
        super().__init__(
            f"标的 [{', '.join(codes)}] 之间无共同起始交易日\n"
            + "\n".join(f"  {c}: 最早数据日={d}" for c, d in details.items())
        )


# ──────────────────────────────────────────────
# DateAligner — 回测起始日期对齐器
# ──────────────────────────────────────────────

class DateAligner:
    """
    回测起始日期对齐器（P1-05）

    职责：
      - 从 trading_calendar 表获取指定市场的交易日序列
      - 从 stock_daily 表获取每只标的的最早可用数据日
      - 对齐多标的的统一起始日（取所有标的共同的第一天）
      - 校验请求的回测起点是否可执行

    设计原则：
      - 所有标的必须同时有可用数据，不能某标的缺数据
      - 最早的共同交易日 = max(每个标的的最早数据日)
      - 回测起点必须 ≥ 最早的共同交易日
    """

    def __init__(self, db_path: str = DB_PATH, market: str = MARKET):
        self.db_path = db_path
        self.market = market
        self._conn: Optional[sqlite3.Connection] = None
        self._trading_days: List[str] = []       # 已排序交易日列表 YYYY-MM-DD
        self._trading_day_set: Set[str] = set()  # 快速查找

    # ── 数据库连接 ────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self._get_conn()
        return self

    def __exit__(self, *args):
        self.close()

    # ── 交易日历 ──────────────────────────────

    def load_trading_days(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[str]:
        """
        加载交易日序列。

        参数：
          start_date / end_date: YYYY-MM-DD，为 None 则取全部

        返回：排序后的交易日列表 YYYY-MM-DD
        """
        conn = self._get_conn()
        cur = conn.cursor()

        query = (
            "SELECT date FROM trading_calendar "
            "WHERE market=? AND is_trading_day=1"
        )
        params: List = [self.market]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date"

        cur.execute(query, params)
        self._trading_days = [row[0] for row in cur.fetchall()]
        self._trading_day_set = set(self._trading_days)

        logger.info(
            "交易日历已加载：%d 天 [%s ~ %s]",
            len(self._trading_days),
            self._trading_days[0] if self._trading_days else "N/A",
            self._trading_days[-1] if self._trading_days else "N/A",
        )
        return self._trading_days

    def is_trading_day(self, date_str: str) -> bool:
        """判断给定日期是否为交易日"""
        return date_str in self._trading_day_set

    # ── 单标的最早数据日 ─────────────────────

    def get_earliest_data_date(self, code: str) -> Optional[str]:
        """
        获取单只标的存在于 stock_daily 中的最早日期。
        返回 YYYY-MM-DD 格式，若无数据返回 None。
        """
        conn = self._get_conn()
        cur = conn.cursor()

        cur.execute(
            "SELECT MIN(date) FROM stock_daily WHERE code=?",
            (code,),
        )
        raw = cur.fetchone()[0]
        if raw is None:
            return None

        raw = str(raw)
        # YYYYMMDD → YYYY-MM-DD
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    # ── 多标的对齐 ───────────────────────────

    def get_earliest_dates(
        self, codes: List[str]
    ) -> Dict[str, Optional[str]]:
        """
        批量获取每个标的最早数据日。
        返回 {code: earliest_date_YYYY_MM_DD or None}
        """
        result: Dict[str, Optional[str]] = {}
        for code in codes:
            result[code] = self.get_earliest_data_date(code)
        return result

    def find_common_start(
        self, codes: List[str]
    ) -> Tuple[str, Dict[str, str]]:
        """
        找出多个标的的共同起始日。

        返回：(common_start, {code: earliest_date})
        其中 common_start = max(所有标的最早数据日)
        如果有标的无数据则抛出 NoCommonStartError。
        """
        earliest_dates = self.get_earliest_dates(codes)

        # 检查无数据的标的
        no_data = [c for c, d in earliest_dates.items() if d is None]
        if no_data:
            raise NoCommonStartError(codes, earliest_dates)

        # 计算共同起始日 = 最晚的最早数据日
        valid_dates: Dict[str, str] = {
            c: d for c, d in earliest_dates.items() if d is not None
        }
        common_start = max(valid_dates.values())

        logger.info(
            "共同起始日对齐结果：%s  <- max(%s)",
            common_start,
            {c: d for c, d in valid_dates.items()},
        )
        return common_start, valid_dates

    # ── 核心对齐方法 ─────────────────────────

    def align(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
    ) -> Tuple[str, str]:
        """
        主对齐方法。

        流程：
          1. 加载交易日历
          2. 获取每只标的最早数据日
          3. 计算统一起始日 = max(各标的最早数据日)
          4. 校验请求的 start_date 是否不早于统一起始日
          5. 将 start_date 修正为统一起始日（如果需要）
          6. 校验 end_date 不早于 start_date

        参数：
          codes: 标的代码列表
          start_date / end_date: 请求的回测日期范围 YYYY-MM-DD

        返回：
          (aligned_start, aligned_end)
          - aligned_start: 实际可用的起始日（≥ 请求的 start_date）
          - aligned_end: 实际可用的结束日

        异常：
          LateStartError: 标的开始晚于请求起点
          NoCommonStartError: 无共同起始
        """
        # 1. 加载交易日历
        self.load_trading_days()

        # 2. 获取最早期数据日
        earliest_dates = self.get_earliest_dates(codes)

        # 3. 检查无数据的标的
        no_data_codes = [c for c, d in earliest_dates.items() if d is None]
        if no_data_codes:
            raise NoCommonStartError(codes, earliest_dates)

        # 4. 计算统一起始日
        valid_earliest = {c: d for c, d in earliest_dates.items() if d is not None}
        common_start = max(valid_earliest.values())

        # 5. 检查是否有标的的最早可用日已超出结束日（无任何重叠区间）
        for code, earliest in valid_earliest.items():
            if earliest > end_date:
                raise LateStartError(code, earliest, end_date)

        # 6. 确定最终起始日 = max(请求 start_date, 共同起始日)
        aligned_start = max(start_date, common_start)

        # 7. 校验结束日
        if end_date < aligned_start:
            raise DateAlignmentError(
                f"结束日期 {end_date} 早于对齐后的起始日 {aligned_start}"
            )

        # 8. 确保对齐后的起始日和结束日都是交易日
        #    如果 aligned_start 不是交易日，向前找到第一个交易日
        if aligned_start not in self._trading_day_set:
            for d in self._trading_days:
                if d >= aligned_start:
                    aligned_start = d
                    break
            logger.info("起始日对齐到最近交易日：%s", aligned_start)

        #    如果 end_date 不是交易日，向后找到最后一个交易日
        if end_date not in self._trading_day_set:
            for d in reversed(self._trading_days):
                if d <= end_date:
                    end_date = d
                    break
            logger.info("结束日对齐到最近交易日：%s", end_date)

        # 9. 最终校验
        if aligned_start > end_date:
            raise DateAlignmentError(
                f"对齐后起始日 {aligned_start} 晚于结束日 {end_date}，无可回测区间"
            )

        logger.info(
            "日期对齐完成：codes=%s start=%s end=%s (共同起始=%s)",
            codes, aligned_start, end_date, common_start,
        )
        return aligned_start, end_date

    # ── 工具方法 ─────────────────────────────

    @staticmethod
    def to_short(date_str: str) -> str:
        """YYYY-MM-DD → YYYYMMDD"""
        return date_str.replace("-", "")

    @staticmethod
    def to_long(date_str: str) -> str:
        """YYYYMMDD → YYYY-MM-DD"""
        s = str(date_str)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    def get_trading_day_count(self, start_date: str, end_date: str) -> int:
        """获取日期范围内交易日数量"""
        return sum(
            1 for d in self._trading_days if start_date <= d <= end_date
        )

    def list_trading_days_in_range(
        self, start_date: str, end_date: str
    ) -> List[str]:
        """获取日期范围内的交易日列表"""
        return [d for d in self._trading_days if start_date <= d <= end_date]


# ──────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────

def main():
    """CLI 入口：演示日期对齐功能"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    import argparse

    parser = argparse.ArgumentParser(description="墨枢 P1-05 回测起始日期对齐")
    parser.add_argument("--codes", nargs="+", default=DEFAULT_CODES, help="标的代码列表")
    parser.add_argument("--start", default="2026-01-01", help="回测开始日期")
    parser.add_argument("--end", default="2026-05-14", help="回测结束日期")
    args = parser.parse_args()

    aligner = DateAligner()
    with aligner:
        print(f"标的: {args.codes}")
        print(f"请求: {args.start} ~ {args.end}")

        earliest_dates = aligner.get_earliest_dates(args.codes)
        print(f"\n各标的最早数据日:")
        for code, date in earliest_dates.items():
            status = date or "无数据"
            print(f"  {code}: {status}")

        common_start, _ = aligner.find_common_start(args.codes)
        print(f"\n共同起始日: {common_start}")

        try:
            aligned_start, aligned_end = aligner.align(
                codes=args.codes,
                start_date=args.start,
                end_date=args.end,
            )
            print(f"\n对齐结果: {aligned_start} ~ {aligned_end}")
            print(f"交易日数: {aligner.get_trading_day_count(aligned_start, aligned_end)}")
        except DateAlignmentError as e:
            print(f"\n[ERROR] {e}")


if __name__ == "__main__":
    main()
