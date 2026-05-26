"""
tests/test_date_aligner.py — P1-06 日期对齐单元测试

覆盖场景：
  TC-01  单标的正常对齐（601857, 2026-01-05起）
  TC-02  多标的同时对齐（601857 + 600519）
  TC-03  标的晚于回测起始日（应报 LateStartError）
  TC-04  回测区间内无数据（应报 NoCommonStartError / DateAlignmentError）
  TC-05  边界值测试（起点/终点恰好为交易日/非交易日）
"""

import unittest
import sqlite3
import os
import tempfile
from datetime import date
from unittest.mock import patch, MagicMock

# ── 被测模块 ────────────────────────────────────
import sys
# Workaround: add mozhi_platform parent so "src.backtest.date_aligner" resolves
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from backtest.date_aligner import (
    DateAligner,
    DateAlignmentError,
    LateStartError,
    NoCommonStartError,
)


# ── 测试夹具 ────────────────────────────────────

class TestDateAligner(unittest.TestCase):
    """DateAligner 单元测试套件"""

    @classmethod
    def setUpClass(cls):
        """创建临时内存数据库，用真实表结构预填充交易日历"""
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        conn = sqlite3.connect(cls.db_path)
        cur = conn.cursor()

        # 建交易日历表（与 analysis.db 结构一致）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trading_calendar (
                market TEXT NOT NULL,
                date   TEXT NOT NULL,
                is_trading_day INTEGER NOT NULL,
                PRIMARY KEY (market, date)
            )
        """)
        # 建 stock_daily 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (code, date)
            )
        """)

        # 插入交易日：2026-01 的工作日（不含周末和元旦）
        trading_days = [
            # 1月
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
            "2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15",
            "2026-01-16", "2026-01-19", "2026-01-20", "2026-01-21", "2026-01-22",
            "2026-01-23", "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29", "2026-01-30",
            # 2月（春节假设） — 2月16~22日放假
            "2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-06",
            "2026-02-09", "2026-02-10", "2026-02-11", "2026-02-12", "2026-02-13",
            "2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27",
            # 3月
            "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",
            "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13",
            "2026-03-16", "2026-03-17", "2026-03-18", "2026-03-19", "2026-03-20",
            "2026-03-23", "2026-03-24", "2026-03-25", "2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31",
            # 4月
            "2026-04-01", "2026-04-02", "2026-04-03", "2026-04-07", "2026-04-08",
            "2026-04-09", "2026-04-10", "2026-04-13", "2026-04-14", "2026-04-15",
            "2026-04-16", "2026-04-17", "2026-04-20", "2026-04-21", "2026-04-22",
            "2026-04-23", "2026-04-24", "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
            # 5月
            "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08",
            "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15",
        ]
        cur.executemany(
            "INSERT OR IGNORE INTO trading_calendar VALUES ('A', ?, 1)",
            [(d,) for d in trading_days],
        )
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def setUp(self):
        # Fresh aligner + wipe stock_daily to avoid cross-test pollution
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM stock_daily")
        conn.commit()
        conn.close()
        self.aligner = DateAligner(db_path=self.db_path, market="A")

    def tearDown(self):
        self.aligner.close()

    # ── TC-01：单标的正常对齐 ──────────────────────
    def test_single_code_normal_align(self):
        """
        TC-01：单标的正常对齐（601857, 2026-01-05起）
        601857 最早数据日 = 2026-01-05，共同起始日 = 2026-01-05
        请求 start_date 2026-01-01 < 共同起始日 → 对齐到 2026-01-05
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260106')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260107')"
        )
        conn.commit()
        conn.close()

        aligned_start, aligned_end = self.aligner.align(
            codes=["601857"],
            start_date="2026-01-01",
            end_date="2026-01-10",
        )
        self.assertEqual(aligned_start, "2026-01-05")  # 对齐到标的最早数据日
        self.assertEqual(aligned_end, "2026-01-09")    # 非交易日向前找到最近交易日

    # ── TC-02：多标的同时对齐 ──────────────────────
    def test_multi_code_align(self):
        """
        TC-02：多标的同时对齐（601857 + 600519）
        601857: 2026-01-05, 600519: 2026-01-06
        → 共同起始日 = max(2026-01-05, 2026-01-06) = 2026-01-06
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260106')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('600519', '20260106')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('600519', '20260107')"
        )
        conn.commit()
        conn.close()

        aligned_start, aligned_end = self.aligner.align(
            codes=["601857", "600519"],
            start_date="2026-01-01",
            end_date="2026-01-10",
        )
        self.assertEqual(aligned_start, "2026-01-06")
        self.assertEqual(aligned_end, "2026-01-09")

    # ── TC-03：标的晚于回测起始日（LateStartError） ─
    def test_late_start_error(self):
        """
        TC-03：标的晚于回测起始日（应报 LateStartError）
        601857_LATE 最早数据日 2026-03-01，晚于 end_date 2026-02-01
        → 抛出 LateStartError
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857_LATE', '20260301')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857_LATE', '20260302')"
        )
        conn.commit()
        conn.close()

        with self.assertRaises(LateStartError) as ctx:
            self.aligner.align(
                codes=["601857_LATE"],
                start_date="2026-01-01",
                end_date="2026-02-01",
            )
        self.assertEqual(ctx.exception.code, "601857_LATE")
        self.assertEqual(ctx.exception.earliest_date, "2026-03-01")
        self.assertEqual(ctx.exception.end_date, "2026-02-01")

    # ── TC-04：回测区间内无数据 ─────────────────────
    def test_no_common_start_error(self):
        """
        TC-04：回测区间内无数据（应报 NoCommonStartError）
        999999 根本无任何数据 → 抛出 NoCommonStartError
        """
        with self.assertRaises(NoCommonStartError) as ctx:
            self.aligner.align(
                codes=["999999"],
                start_date="2026-01-01",
                end_date="2026-01-10",
            )
        self.assertIn("999999", str(ctx.exception))

    def test_no_data_in_range_date_alignment_error(self):
        """
        TC-04 变体：有数据但均在回测区间外（应报 LateStartError）
        888888_OUT 最早数据日 2026-04-01，晚于 end_date 2026-03-01
        但 2026-03-01 在交易日历中 → LateStartError 路径
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('888888_OUT', '20260401')"
        )
        conn.commit()
        conn.close()

        with self.assertRaises(LateStartError):
            self.aligner.align(
                codes=["888888_OUT"],
                start_date="2026-03-01",
                end_date="2026-03-10",
            )

    # ── TC-05：边界值测试 ─────────────────────────
    def test_boundary_start_is_trading_day(self):
        """
        TC-05-a：起点恰好为交易日
        601857 最早数据日 2026-01-05（本身就是交易日）
        请求 start_date = 2026-01-05 → 无需对齐
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260106')"
        )
        conn.commit()
        conn.close()

        aligned_start, _ = self.aligner.align(
            codes=["601857"],
            start_date="2026-01-05",  # 恰好是交易日
            end_date="2026-01-09",
        )
        self.assertEqual(aligned_start, "2026-01-05")

    def test_boundary_start_is_holiday(self):
        """
        TC-05-b：起点恰好为非交易日（周末/节假日）
        请求 start_date = 2026-01-03（周六），对齐到 2026-01-05（最近交易日）
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260106')"
        )
        conn.commit()
        conn.close()

        # 2026-01-03 是周六（非交易日），2026-01-05 是最近的后续交易日
        aligned_start, _ = self.aligner.align(
            codes=["601857"],
            start_date="2026-01-03",  # 非交易日
            end_date="2026-01-09",
        )
        self.assertEqual(aligned_start, "2026-01-05")

    def test_boundary_end_is_trading_day(self):
        """
        TC-05-c：终点恰好为交易日
        end_date = 2026-01-09（本身就是交易日），无需调整
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260109')"
        )
        conn.commit()
        conn.close()

        _, aligned_end = self.aligner.align(
            codes=["601857"],
            start_date="2026-01-05",
            end_date="2026-01-09",  # 恰好是交易日
        )
        self.assertEqual(aligned_end, "2026-01-09")

    def test_boundary_end_is_holiday(self):
        """
        TC-05-d：终点恰好为非交易日（周末/节假日）
        end_date = 2026-01-10（周六），对齐到 2026-01-09（最近的前一个交易日）
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260109')"
        )
        conn.commit()
        conn.close()

        _, aligned_end = self.aligner.align(
            codes=["601857"],
            start_date="2026-01-05",
            end_date="2026-01-10",  # 非交易日
        )
        self.assertEqual(aligned_end, "2026-01-09")

    def test_boundary_both_holiday(self):
        """
        TC-05-e：起点和终点同时为非交易日
        start = 2026-01-03（周六），end = 2026-01-04（周日）
        共同起始日 2026-01-05 > end_date 2026-01-04 → LateStartError
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857_HOL', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857_HOL', '20260106')"
        )
        conn.commit()
        conn.close()

        # common_start=2026-01-05 > end=2026-01-04 → LateStartError
        with self.assertRaises(LateStartError):
            self.aligner.align(
                codes=["601857_HOL"],
                start_date="2026-01-03",
                end_date="2026-01-04",
            )

    # ── 工具方法测试 ──────────────────────────────
    def test_get_earliest_data_date(self):
        """测试 get_earliest_data_date 单标查询"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260106')"
        )
        conn.commit()
        conn.close()

        result = self.aligner.get_earliest_data_date("601857")
        self.assertEqual(result, "2026-01-05")

    def test_get_earliest_dates_batch(self):
        """测试批量查询各标的最早数据日"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('601857', '20260105')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO stock_daily (code, date) VALUES ('600519', '20260106')"
        )
        conn.commit()
        conn.close()

        result = self.aligner.get_earliest_dates(["601857", "600519"])
        self.assertEqual(result["601857"], "2026-01-05")
        self.assertEqual(result["600519"], "2026-01-06")

    def test_to_short_and_to_long(self):
        """测试日期格式互转"""
        self.assertEqual(DateAligner.to_short("2026-01-05"), "20260105")
        self.assertEqual(DateAligner.to_long("20260105"), "2026-01-05")

    def test_is_trading_day(self):
        """测试 is_trading_day 判断"""
        self.aligner.load_trading_days()
        self.assertTrue(self.aligner.is_trading_day("2026-01-05"))   # 交易日内
        self.assertFalse(self.aligner.is_trading_day("2026-01-03"))  # 周六非交易日
        self.assertFalse(self.aligner.is_trading_day("2026-01-01"))  # 元旦非交易日

    def test_get_trading_day_count(self):
        """测试 get_trading_day_count 计数"""
        self.aligner.load_trading_days("2026-01-01", "2026-01-10")
        count = self.aligner.get_trading_day_count("2026-01-05", "2026-01-09")
        # 2026-01-05 ~ 2026-01-09 中的交易日: 05(Mon), 06(Tue), 07(Wed), 08(Thu), 09(Fri)
        self.assertEqual(count, 5)

    def test_list_trading_days_in_range(self):
        """测试 list_trading_days_in_range 列表"""
        self.aligner.load_trading_days("2026-01-01", "2026-01-10")
        days = self.aligner.list_trading_days_in_range("2026-01-05", "2026-01-09")
        self.assertEqual(days, ["2026-01-05", "2026-01-06", "2026-01-07",
                                 "2026-01-08", "2026-01-09"])


if __name__ == "__main__":
    unittest.main()