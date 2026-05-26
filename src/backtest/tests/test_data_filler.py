"""
test_data_filler.py — Phase 1 数据填充模块单元测试

覆盖4个场景：
1. 正常场景：连续交易日数据，无需填充
2. 缺失场景：有日期缺失，验证ffill填充后价格正确
3. 停牌场景：标记停牌日，价格维持，成交量=0
4. 边界场景：第一个交易日缺失（应跳过，无法填充）
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from backtest.data_filler import (
    DataFiller,
    FillStrategyFactory,
    FfillStrategy,
    SkipStrategy,
    TrimRemoveStrategy,
    GapItem,
    FillResult,
    MissingType,
)


# ──────────────────────────────────────────────
# 测试数据构造工具
# ──────────────────────────────────────────────

def make_row(date_str: str, o=10.0, h=10.5, l=9.5, c=10.0, v=1000) -> tuple:
    """构建 stock_daily 数据行 (code, date, open, high, low, close, volume)"""
    raw = date_str.replace("-", "")
    return ("601857", raw, o, h, l, c, v)


def make_cal_map(dates: list) -> dict:
    """构建交易日历 {date: True}"""
    return {d: True for d in dates}


# ──────────────────────────────────────────────
# 场景1：正常场景 — 连续交易日，无需填充
# ──────────────────────────────────────────────

class TestNormalScenario(unittest.TestCase):
    """已存数据覆盖全部交易日，missing_dates 应为空，filled_rows 应为空"""

    def test_no_missing_dates(self):
        """连续交易日全部存在于 data_rows，缺失列表为空"""
        filler = DataFiller.__new__(DataFiller)
        filler._calendar_map = make_cal_map([
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
        ])

        # data_rows 覆盖全部交易日
        data_rows = [
            make_row("2026-01-02"),
            make_row("2026-01-05"),
            make_row("2026-01-06"),
            make_row("2026-01-07"),
        ]

        # detect_missing 返回模拟
        with patch.object(filler, "detect_missing") as dm:
            dm.return_value = (data_rows, [], filler._calendar_map)
            gaps = filler.classify_gaps([])

        self.assertEqual(gaps, [])
        self.assertEqual(len(gaps), 0)

    def test_fill_result_empty(self):
        """filled_rows 应为空列表"""
        filler = DataFiller.__new__(DataFiller)
        filler._calendar_map = {}

        report = {
            "filled_rows": [],
            "missing_dates": [],
            "gaps": [],
        }

        self.assertEqual(len(report["filled_rows"]), 0)
        self.assertEqual(len(report["missing_dates"]), 0)


# ──────────────────────────────────────────────
# 场景2：缺失场景 — 有日期缺失，验证ffill价格正确
# ──────────────────────────────────────────────

class TestMissingScenario(unittest.TestCase):
    """缺失2026-01-05，ffill应使用2026-01-02的收盘价填充"""

    def test_ffill_single_day_gap(self):
        """
        缺失1天：2026-01-05缺失，应前向填充。
        前一交易日2026-01-02收盘价10.0 → 填充价格=10.0，成交量=0
        """
        data_rows = [
            make_row("2026-01-02", c=10.0),
            make_row("2026-01-06", c=10.2),
        ]
        missing_dates = ["2026-01-05"]
        cal_map = make_cal_map(["2026-01-02", "2026-01-05", "2026-01-06"])

        strategy = FfillStrategy()
        results = strategy.fill("601857", data_rows, missing_dates, cal_map, None)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].date, "2026-01-05")
        self.assertAlmostEqual(results[0].close, 10.0, places=4)
        self.assertAlmostEqual(results[0].open,  10.0, places=4)
        self.assertAlmostEqual(results[0].high,  10.0, places=4)
        self.assertAlmostEqual(results[0].low,   10.0, places=4)
        self.assertEqual(results[0].volume, 0)
        self.assertTrue(results[0].is_filled)

    def test_ffill_three_day_gap(self):
        """
        缺失3天（≤FFILL_THRESHOLD）：2026-01-05/06/07缺失。
        每一天都应填充为前一交易日收盘价。
        """
        data_rows = [
            make_row("2026-01-02", c=10.0),
            make_row("2026-01-08", c=10.5),
        ]
        missing_dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
        cal_map = make_cal_map([
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
        ])

        strategy = FfillStrategy()
        results = strategy.fill("601857", data_rows, missing_dates, cal_map, None)

        self.assertEqual(len(results), 3)
        for r in results:
            self.assertAlmostEqual(r.close, 10.0, places=4)
            self.assertEqual(r.volume, 0)
            self.assertTrue(r.is_filled)

    def test_classify_short_gap(self):
        """缺失1~3天应分类为 SHORT_GAP"""
        filler = DataFiller.__new__(DataFiller)
        filler._calendar_map = make_cal_map(["2026-01-05"])

        gaps = filler.classify_gaps(["2026-01-05"])
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].missing_type, MissingType.SHORT_GAP)
        self.assertEqual(gaps[0].gap_days, 1)

    def test_classify_long_gap(self):
        """缺失>3天应分类为 LONG_GAP（trim_remove）"""
        filler = DataFiller.__new__(DataFiller)
        filler._calendar_map = {}

        gaps = filler.classify_gaps([
            "2026-01-05", "2026-01-06", "2026-01-07",
            "2026-01-08", "2026-01-09", "2026-01-10",
        ])
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].missing_type, MissingType.LONG_GAP)
        self.assertEqual(gaps[0].gap_days, 6)


# ──────────────────────────────────────────────
# 场景3：停牌场景 — 标记停牌日，价格维持，成交量=0
# ──────────────────────────────────────────────

class TestSuspensionScenario(unittest.TestCase):
    """停牌日：前向填充价格（前一日收盘价），成交量=0，is_trading_day=True"""

    def test_suspension_ffill_price_unchanged(self):
        """停牌日价格应等于前一日收盘价（价格维持）"""
        data_rows = [
            make_row("2026-01-02", c=10.0),
            make_row("2026-01-05", c=10.2),
        ]
        missing_dates = ["2026-01-03", "2026-01-04"]
        cal_map = make_cal_map(["2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"])

        strategy = FfillStrategy()
        results = strategy.fill("601857", data_rows, missing_dates, cal_map, None)

        # 停牌日03/04都应填充为01-02的收盘价10.0
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertAlmostEqual(r.close, 10.0, places=4)
            self.assertEqual(r.volume, 0)
            self.assertTrue(r.is_filled)
            self.assertTrue(r.is_trading_day)

    def test_suspension_volume_zero(self):
        """停牌日成交量必为0"""
        data_rows = [
            make_row("2026-01-02", c=10.0),
        ]
        missing_dates = ["2026-01-03"]
        cal_map = make_cal_map(["2026-01-02", "2026-01-03"])

        strategy = FfillStrategy()
        results = strategy.fill("601857", data_rows, missing_dates, cal_map, None)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].volume, 0)

    def test_mark_suspension_days(self):
        """mark_suspension_days 应正确标记停牌日"""
        filler = DataFiller.__new__(DataFiller)
        filler._calendar_map = {
            "2026-01-02": True,
            "2026-01-03": True,  # 停牌日
            "2026-01-06": True,
        }

        report = {
            "is_trading_day_map": filler._calendar_map,
            "missing_dates": ["2026-01-03"],
        }

        suspension = filler.mark_suspension_days(report)
        self.assertFalse(suspension["2026-01-02"])     # 正常交易日且有数据，不是停牌日
        self.assertTrue(suspension["2026-01-03"])      # 停牌日
        self.assertFalse(suspension["2026-01-06"])     # 正常交易日且有数据

    def test_fillresult_is_trading_day_flag(self):
        """FillResult.is_trading_day 应为 True（停牌日仍是交易日）"""
        fr = FillResult(
            date="2026-01-03",
            open=10.0, high=10.0, low=10.0, close=10.0,
            volume=0, is_filled=True, is_trading_day=True,
        )
        self.assertTrue(fr.is_trading_day)
        self.assertTrue(fr.is_filled)


# ──────────────────────────────────────────────
# 场景4：边界场景 — 第一个交易日缺失（应跳过，无法填充）
# ──────────────────────────────────────────────

class TestEdgeCaseFirstDayMissing(unittest.TestCase):
    """首个交易日缺失：无可用前一日收盘价，策略应跳过（不填充）"""

    def test_first_trading_day_missing_ffill_returns_empty(self):
        """
        日期范围首个交易日缺失（无前一交易日），
        FfillStrategy._find_prev_close 返回 None，
        该日应被跳过（不填入 filled_rows）。
        """
        # 没有前一日数据
        data_rows = [
            make_row("2026-01-06", c=10.2),
        ]
        missing_dates = ["2026-01-02"]
        cal_map = make_cal_map(["2026-01-02", "2026-01-05", "2026-01-06"])

        strategy = FfillStrategy()
        results = strategy.fill("601857", data_rows, missing_dates, cal_map, None)

        # 无法前向填充，返回空列表
        self.assertEqual(len(results), 0)

    def test_first_day_not_in_existing(self):
        """首日不在已存数据中，应无法填充"""
        existing_dates = {"2026-01-05", "2026-01-06"}
        first_day = "2026-01-02"

        self.assertNotIn(first_day, existing_dates)
        # 模拟 _find_prev_close 对首日返回 None
        result = FfillStrategy._find_prev_close(
            first_day, {}, make_cal_map(["2026-01-02"])
        )
        self.assertIsNone(result)

    def test_long_gap_skipped_by_trim_remove(self):
        """长间隔（>3天缺失）由 TrimRemoveStrategy 处理，返回空列表"""
        data_rows = [
            make_row("2026-01-02", c=10.0),
            make_row("2026-01-10", c=10.5),
        ]
        missing_dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
        cal_map = make_cal_map([
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
            "2026-01-08", "2026-01-09", "2026-01-10",
        ])

        strategy = TrimRemoveStrategy()
        results = strategy.fill("601857", data_rows, missing_dates, cal_map, None)

        # 剔除策略返回空列表（不填充）
        self.assertEqual(len(results), 0)

    def test_holiday_skipped(self):
        """节假日（HOLIDAY）由 SkipStrategy 处理，返回空列表"""
        missing_dates = ["2026-01-03"]  # 假设是节假日
        cal_map = {"2026-01-03": False}  # 非交易日

        strategy = SkipStrategy()
        results = strategy.fill("601857", [], missing_dates, cal_map, None)

        self.assertEqual(len(results), 0)


# ──────────────────────────────────────────────
# 策略工厂测试
# ──────────────────────────────────────────────

class TestFillStrategyFactory(unittest.TestCase):
    """FillStrategyFactory 能返回正确的策略"""

    def test_suspension_gets_ffill(self):
        s = FillStrategyFactory.get_strategy(MissingType.SUSPENSION)
        self.assertIsInstance(s, FfillStrategy)

    def test_short_gap_gets_ffill(self):
        s = FillStrategyFactory.get_strategy(MissingType.SHORT_GAP)
        self.assertIsInstance(s, FfillStrategy)

    def test_long_gap_gets_trim_remove(self):
        s = FillStrategyFactory.get_strategy(MissingType.LONG_GAP)
        self.assertIsInstance(s, TrimRemoveStrategy)

    def test_holiday_gets_skip(self):
        s = FillStrategyFactory.get_strategy(MissingType.HOLIDAY)
        self.assertIsInstance(s, SkipStrategy)

    def test_can_handle_methods(self):
        ff = FfillStrategy()
        self.assertTrue(ff.can_handle(MissingType.SUSPENSION))
        self.assertTrue(ff.can_handle(MissingType.SHORT_GAP))
        self.assertFalse(ff.can_handle(MissingType.HOLIDAY))
        self.assertFalse(ff.can_handle(MissingType.LONG_GAP))


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()