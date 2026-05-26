"""
data_filler.py — Phase 1 数据填充模块

基于 Phase 0.5 确认的填充策略完成停牌日数据插值与标记。

设计模式：
  - 工厂模式：FillStrategyFactory 根据缺失类型返回对应策略
  - 策略模式：每种填充逻辑封装为独立策略类
  - 优先队列：按 gap_days 排序，优先处理短间隔

已确认数据源：
  - analysis.db（stock_daily / trading_calendar）
  - stock_daily.code = '601857', date 格式 'YYYYMMDD'
  - trading_calendar.date 格式 'YYYY-MM-DD', is_trading_day ∈ {0, 1}

填充规则（策略4）：
  - 停牌日：前向填充（ffill）
  - 节假日：跳过（skip）
  - ≤3天缺失：前向填充（ffill）
  - >3天缺失：剔除（trim_remove）
"""

from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from heapq import heappush, heappop
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\analysis.db"
MARKET = "A"  # A股市场
DEFAULT_CODE = "601857"  # 中国石油

# 填充阈值
FFILL_THRESHOLD = 3  # ≤3天前向填充，>3天剔除


# ──────────────────────────────────────────────
# 枚举与数据类型
# ──────────────────────────────────────────────

class MissingType(Enum):
    """缺失类型分类"""
    SUSPENSION = auto()      # 停牌（交易日期有，但stock_daily无数据）
    HOLIDAY = auto()         # 节假日（非交易日）
    SHORT_GAP = auto()       # 短间隔（1~3天缺失）
    LONG_GAP = auto()        # 长间隔（>3天缺失）


class FillAction(Enum):
    """填充动作"""
    FFILL = "ffill"           # 前向填充
    SKIP = "skip"             # 跳过（保留原样）
    TRIM_REMOVE = "trim_remove"  # 剔除


@dataclass(order=True)
class GapItem:
    """缺失间隔优先队列条目"""
    gap_days: int                     # 缺失天数（排序键）
    start_date: str = field(compare=False)   # 缺失起始日期
    end_date: str = field(compare=False)     # 缺失结束日期
    missing_type: MissingType = field(compare=False)
    missing_dates: List[str] = field(compare=False, default_factory=list)


@dataclass
class FillResult:
    """单次填充结果"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_filled: bool = False          # 是否由填充产生
    is_trading_day: bool = True      # 是否为交易日


# ──────────────────────────────────────────────
# 策略抽象基类
# ──────────────────────────────────────────────

class FillStrategy(ABC):
    """填充策略基类"""

    @abstractmethod
    def fill(self,
             code: str,
             data_rows: List[Tuple],
             missing_dates: List[str],
             calendar_map: Dict[str, bool],
             conn: sqlite3.Connection) -> List[FillResult]:
        ...

    @abstractmethod
    def can_handle(self, missing_type: MissingType) -> bool:
        ...


class FfillStrategy(FillStrategy):
    """
    前向填充策略（P1-02）
    - 基于交易日历识别缺失日期
    - 缺失日期的 open/high/low/close = 前一日收盘价
    - 成交量填充为 0
    """

    def can_handle(self, missing_type: MissingType) -> bool:
        return missing_type in (MissingType.SUSPENSION, MissingType.SHORT_GAP)

    def fill(self,
             code: str,
             data_rows: List[Tuple],
             missing_dates: List[str],
             calendar_map: Dict[str, bool],
             conn: sqlite3.Connection) -> List[FillResult]:
        """
        前向填充实现：
        1. 建立已存数据 date → OHLCV 的映射
        2. 对每个缺失日期，寻找最近的前一交易日收盘价
        3. 返回填充后数据行列表
        """
        # 构建已存数据索引 {date_str: (open, high, low, close, volume)}
        existing: Dict[str, Tuple] = {}
        for row in data_rows:
            raw_date = str(row[1])
            # YYYYMMDD → YYYY-MM-DD
            date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            existing[date_str] = (row[2], row[3], row[4], row[5], row[6])

        results: List[FillResult] = []

        for missing_date in missing_dates:
            # 寻找最近的前一交易日（从 missing_date 倒推）
            fill_price = self._find_prev_close(missing_date, existing, calendar_map)
            if fill_price is None:
                logger.warning(
                    "[%s] 无法前向填充 %s：缺少前一日收盘价，跳过",
                    code, missing_date
                )
                continue

            results.append(FillResult(
                date=missing_date,
                open=fill_price,
                high=fill_price,
                low=fill_price,
                close=fill_price,
                volume=0,
                is_filled=True,
                is_trading_day=True,
            ))

        return results

    @staticmethod
    def _find_prev_close(
        date_str: str,
        existing: Dict[str, Tuple],
        calendar_map: Dict[str, bool],
    ) -> Optional[float]:
        """
        从 date_str 倒推，找到最近一个已有数据的交易日的收盘价。
        跳过非交易日和日历中标记为 is_trading_day=0 的日期。
        """
        from datetime import datetime, timedelta

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

        # 最多倒推 30 天
        for _ in range(30):
            dt -= timedelta(days=1)
            prev_date = dt.strftime("%Y-%m-%d")

            if prev_date in existing:
                _, _, _, prev_close, _ = existing[prev_date]
                return float(prev_close)

            # 如果 prev_date 不存在且不是交易日，继续倒推
            if prev_date in calendar_map and not calendar_map[prev_date]:
                continue

        return None


class SkipStrategy(FillStrategy):
    """跳过策略：保留数据原样，不做任何填充"""

    def can_handle(self, missing_type: MissingType) -> bool:
        return missing_type == MissingType.HOLIDAY

    def fill(self,
             code: str,
             data_rows: List[Tuple],
             missing_dates: List[str],
             calendar_map: Dict[str, bool],
             conn: sqlite3.Connection) -> List[FillResult]:
        return []


class TrimRemoveStrategy(FillStrategy):
    """
    剔除策略：对长间隔（>3天缺失）的缺失行进行标记或剔除。
    注意：剔除仅在数据集层面生效，本方法返回空列表（不填充），
    由上层调用者根据 LONG_GAP 标记执行删除。
    """

    def can_handle(self, missing_type: MissingType) -> bool:
        return missing_type == MissingType.LONG_GAP

    def fill(self,
             code: str,
             data_rows: List[Tuple],
             missing_dates: List[str],
             calendar_map: Dict[str, bool],
             conn: sqlite3.Connection) -> List[FillResult]:
        logger.info(
            "[%s] 长间隔 %s 标记为剔除，共 %d 天",
            code, missing_dates[0] if missing_dates else "?",
            len(missing_dates)
        )
        # 返回空列表表示不填充，由调用者删除
        return []


# ──────────────────────────────────────────────
# 策略工厂
# ──────────────────────────────────────────────

class FillStrategyFactory:
    """
    策略工厂（P1-01）
    根据缺失类型返回对应的填充策略。
    支持：ffill / skip / trim_remove
    """

    _strategies: Dict[MissingType, FillStrategy] = {}

    @classmethod
    def get_strategy(cls, missing_type: MissingType) -> FillStrategy:
        """工厂方法：根据缺失类型返回对应策略"""
        if missing_type not in cls._strategies:
            cls._build_registry()
        return cls._strategies[missing_type]

    @classmethod
    def _build_registry(cls):
        cls._strategies = {
            MissingType.SUSPENSION: FfillStrategy(),
            MissingType.SHORT_GAP: FfillStrategy(),
            MissingType.HOLIDAY: SkipStrategy(),
            MissingType.LONG_GAP: TrimRemoveStrategy(),
        }

    @classmethod
    def list_available(cls) -> List[str]:
        """列出所有可用策略名称"""
        return [s.__class__.__name__ for s in cls._strategies.values()]

    @classmethod
    def get_priority_queue(cls) -> List[FillStrategy]:
        """
        返回策略优先队列（短间隔优先处理）
        顺序：ffill（短）→ ffill（停牌）→ skip → trim_remove
        """
        return [
            cls.get_strategy(MissingType.SHORT_GAP),
            cls.get_strategy(MissingType.SUSPENSION),
            cls.get_strategy(MissingType.HOLIDAY),
            cls.get_strategy(MissingType.LONG_GAP),
        ]


# ──────────────────────────────────────────────
# 核心填充引擎
# ──────────────────────────────────────────────

class DataFiller:
    """
    数据填充引擎

    职责：
      1. 从数据库加载交易日历和股票数据
      2. 识别缺失的交易日
      3. 分类缺失类型（停牌/节假日/短间隔/长间隔）
      4. 按策略优先队列执行填充
      5. 标记 is_trading_day（P1-03）
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._calendar_map: Dict[str, bool] = {}  # date → is_trading_day

    # ── 数据库连接 ────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self._get_conn()
        return self

    def __exit__(self, *args):
        self.close()

    # ── 交易日历加载 ──────────────────────────

    def load_calendar(self, market: str = MARKET) -> Dict[str, bool]:
        """
        从 trading_calendar 表加载交易日历。
        返回 {date_str: is_trading_day} 字典。
        """
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT date, is_trading_day FROM trading_calendar WHERE market=? ORDER BY date",
            (market,)
        )
        self._calendar_map = {row[0]: bool(row[1]) for row in cur.fetchall()}
        logger.info("已加载交易日历：%d 天（市场=%s）", len(self._calendar_map), market)
        return self._calendar_map

    def get_trading_days_in_range(
        self, start_date: str, end_date: str
    ) -> List[str]:
        """获取指定日期范围内所有交易日（YYYY-MM-DD格式）"""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT date FROM trading_calendar "
            "WHERE market=? AND is_trading_day=1 "
            "AND date >= ? AND date <= ? ORDER BY date",
            (MARKET, start_date, end_date)
        )
        return [row[0] for row in cur.fetchall()]

    # ── 缺失检测 ──────────────────────────────

    def detect_missing(
        self, code: str, start_date: str, end_date: str
    ) -> Tuple[List[Tuple], List[str], Dict[str, bool]]:
        """
        检测缺失日期。

        参数：
          code: 股票代码
          start_date / end_date: YYYY-MM-DD 格式

        返回：
          (data_rows, missing_dates, calendar_map)
        """
        conn = self._get_conn()
        cur = conn.cursor()

        # 加载股票数据
        start_raw = start_date.replace("-", "")
        end_raw = end_date.replace("-", "")
        cur.execute(
            "SELECT * FROM stock_daily WHERE code=? AND date >= ? AND date <= ? ORDER BY date",
            (code, start_raw, end_raw)
        )
        data_rows = cur.fetchall()

        # 构建已存日期集合 (YYYY-MM-DD)
        existing_dates: Set[str] = set()
        for row in data_rows:
            raw = str(row[1])
            existing_dates.add(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")

        # 加载交易日历
        if not self._calendar_map:
            self.load_calendar()

        # 计算该范围内的所有 A 股交易日
        all_trading_days = self.get_trading_days_in_range(start_date, end_date)

        # 找出缺失的交易日
        missing_dates = [
            d for d in all_trading_days if d not in existing_dates
        ]

        return data_rows, missing_dates, self._calendar_map

    # ── 缺失分类 ──────────────────────────────

    def classify_gaps(
        self, missing_dates: List[str]
    ) -> List[GapItem]:
        """
        将缺失日期列表分类为连续的间隔（GapItem），
        并填入优先队列按 gap_days 排序。

        停牌日：持续缺失且 >=1 天
        节假日：is_trading_day=0 → 跳过
        ≤3 天：短间隔 → ffill
        >3 天：长间隔 → trim_remove
        """
        if not missing_dates:
            return []

        queue: list = []

        # 分组连续缺失
        groups: List[List[str]] = []
        current_group: List[str] = [missing_dates[0]]

        from datetime import datetime, timedelta

        for i in range(1, len(missing_dates)):
            prev_dt = datetime.strptime(missing_dates[i - 1], "%Y-%m-%d")
            curr_dt = datetime.strptime(missing_dates[i], "%Y-%m-%d")
            gap = (curr_dt - prev_dt).days

            if gap == 1:
                # 连续交易日
                current_group.append(missing_dates[i])
            else:
                # 间隔 >1 天说明有非交易日夹在中间，另起一组
                groups.append(current_group)
                current_group = [missing_dates[i]]

        if current_group:
            groups.append(current_group)

        # 分类
        for group in groups:
            gap_len = len(group)

            if gap_len <= FFILL_THRESHOLD:
                mtype = MissingType.SHORT_GAP
            else:
                mtype = MissingType.LONG_GAP

            item = GapItem(
                gap_days=gap_len,
                start_date=group[0],
                end_date=group[-1],
                missing_type=mtype,
                missing_dates=group,
            )
            heappush(queue, item)

        # 按 gap_days 从小到大排序输出
        sorted_items = []
        while queue:
            sorted_items.append(heappop(queue))

        return sorted_items

    # ── 执行填充（P1-02 + P1-03） ─────────────

    def fill(
        self,
        code: str = DEFAULT_CODE,
        start_date: str = "2020-01-01",
        end_date: str = "2026-05-16",
        dry_run: bool = True,
    ) -> Dict[str, object]:
        """
        主入口：执行完整的数据填充流程。

        参数：
          code: 股票代码
          start_date / end_date: 日期范围
          dry_run: True=仅预览不写入数据库，False=写入数据库

        返回：
          {
            "code": str,
            "start_date": str,
            "end_date": str,
            "total_trading_days": int,
            "existing_rows": int,
            "missing_dates": List[str],
            "gaps": [GapItem, ...],
            "filled_rows": [FillResult, ...],
            "is_trading_day_map": {date: bool, ...},
            "dry_run": bool,
          }
        """
        # 1. 加载数据
        data_rows, missing_dates, cal_map = self.detect_missing(
            code, start_date, end_date
        )
        logger.info(
            "[%s] 已存 %d 行，缺失 %d 个交易日",
            code, len(data_rows), len(missing_dates),
        )

        # 2. 分类间隔
        gaps = self.classify_gaps(missing_dates)
        logger.info("[%s] 识别到 %d 个缺失间隔", code, len(gaps))

        # 3. 按策略优先队列执行填充
        all_filled: List[FillResult] = []
        strategy_priority = FillStrategyFactory.get_priority_queue()

        for gap in gaps:
            # 找到能处理此缺失类型的策略
            applied = False
            for strategy in strategy_priority:
                if strategy.can_handle(gap.missing_type):
                    results = strategy.fill(
                        code, data_rows, gap.missing_dates, cal_map, self._get_conn()
                    )
                    all_filled.extend(results)
                    applied = True
                    logger.info(
                        "  [%s] 策略 %s 处理间隔 %s (%d 天): 生成 %d 行",
                        code,
                        strategy.__class__.__name__,
                        gap.start_date,
                        gap.gap_days,
                        len(results),
                    )
                    break

            if not applied:
                logger.warning(
                    "[%s] 间隔 %s (%d 天) 无匹配策略，跳过",
                    code, gap.start_date, gap.gap_days,
                )

        # 4. 构建 is_trading_day 标记（P1-03）
        #    将所有日期（含缺失填充）标记 is_trading_day
        #    - 停牌日：有日期但数据缺失且非节假日的交易日 → is_trading_day=True（价格维持）
        #    - 节假日：日历标记为 is_trading_day=0 → 跳过
        is_trading_day_map: Dict[str, bool] = {}
        for date_str in cal_map:
            is_trading_day_map[date_str] = cal_map[date_str]

        # 5. 结果汇总
        report = {
            "code": code,
            "start_date": start_date,
            "end_date": end_date,
            "total_trading_days": len(self.get_trading_days_in_range(start_date, end_date)),
            "existing_rows": len(data_rows),
            "missing_dates": missing_dates,
            "gaps": gaps,
            "filled_rows": all_filled,
            "is_trading_day_map": is_trading_day_map,
            "dry_run": dry_run,
        }

        # 6. 如不是 dry_run，写入数据库
        if not dry_run:
            self._write_filled_to_db(code, all_filled)

        return report

    def _write_filled_to_db(
        self, code: str, filled_rows: List[FillResult]
    ):
        """将填充结果写入 stock_daily 表"""
        conn = self._get_conn()
        cur = conn.cursor()

        written = 0
        for fr in filled_rows:
            # FillResult date → YYYYMMDD
            raw_date = fr.date.replace("-", "")
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO stock_daily "
                    "(code, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (code, raw_date, fr.open, fr.high, fr.low, fr.close, fr.volume),
                )
                if cur.rowcount > 0:
                    written += 1
            except sqlite3.Error as e:
                logger.error("写入失败 %s %s: %s", code, fr.date, e)

        conn.commit()
        logger.info("[%s] 写入填充数据 %d 行", code, written)

    # ── 报告输出 ──────────────────────────────

    @staticmethod
    def print_report(report: Dict[str, object]):
        """打印可读的填充报告"""
        print("=" * 60)
        print(f"  数据填充报告 - {report['code']}")
        print(f"  日期范围: {report['start_date']} ~ {report['end_date']}")
        print(f"  总交易日: {report['total_trading_days']}")
        print(f"  已存数据: {report['existing_rows']} 行")
        print(f"  缺失日期: {len(report['missing_dates'])} 天")
        print(f"  填充行数: {len(report['filled_rows'])} 行")
        print(f"  Dry Run:  {report['dry_run']}")
        print("-" * 60)
        print("  Gap 详情:")
        for gap in report["gaps"]:
            print(
                f"    {gap.start_date} ~ {gap.end_date}: "
                f"{gap.gap_days} 天, "
                f"type={gap.missing_type.name}, "
                f"count={len(gap.missing_dates)}"
            )
        print("-" * 60)
        print("  填充详情:")
        for fr in report["filled_rows"]:
            ohlc_vol = f"O={fr.open:.2f} H={fr.high:.2f} L={fr.low:.2f} C={fr.close:.2f} V={fr.volume}"
            print(f"    {fr.date}  {ohlc_vol}  filled={fr.is_filled}")
        print("=" * 60)

    # ── 停牌日标记工具（P1-03） ───────────────

    def mark_suspension_days(
        self,
        report: Dict[str, object],
    ) -> Dict[str, bool]:
        """
        明确标记停牌日（P1-03）。

        停牌日定义：
          - 是交易日（is_trading_day=1）
          - 有该日期但缺失数据（不在 stock_daily 中）
          - 价格维持逻辑：前向填充后的价格为前一日收盘价
          - 成交量 = 0

        返回 {date: is_suspension} 词典，
        仅在 is_trading_day=True 且数据缺失时标记为 True。
        """
        cal_map = report.get("is_trading_day_map", {})
        missing_dates = report.get("missing_dates", [])

        suspension_map: Dict[str, bool] = {}
        for date_str in cal_map:
            if cal_map[date_str]:
                # 是交易日 → 检查是否缺失数据
                suspension_map[date_str] = date_str in missing_dates
            else:
                suspension_map[date_str] = False

        return suspension_map


# ──────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────

def main():
    """CLI 入口：执行数据填充并打印报告"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    import argparse

    parser = argparse.ArgumentParser(description="墨枢 Phase 1 数据填充模块")
    parser.add_argument("--code", default=DEFAULT_CODE, help="股票代码")
    parser.add_argument("--start", default="2020-01-01", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="2026-05-16", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--write", action="store_true", help="写入数据库（默认 dry-run）")
    args = parser.parse_args()

    filler = DataFiller()
    with filler:
        report = filler.fill(
            code=args.code,
            start_date=args.start,
            end_date=args.end,
            dry_run=not args.write,
        )
        DataFiller.print_report(report)

        # P1-03: 停牌日标记
        print("\nP1-03 停牌日标记:")
        suspension = filler.mark_suspension_days(report)
        susp_days = [d for d, v in suspension.items() if v]
        for d in susp_days:
            print(f"  [SUSPENSION] 停牌日: {d}")
        print(f"  共 {len(susp_days)} 天停牌日")


if __name__ == "__main__":
    main()
