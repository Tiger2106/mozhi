"""
P1_001a — 涨跌停常量和边界计算函数 单元测试
Standalone unittest version (works around pytest/pdb Python 3.14 issue).
"""
import sys
import os
import unittest
import math

# Ensure backtest_engine is on path
sys.path.insert(0, r"C:\Users\17699\mo_zhi_sharereports")

from backtest_engine.sim_layer.price_boundary import (
    MarketType,
    LIMIT_UP_RATIO,
    LIMIT_DOWN_RATIO,
    get_market_type,
    is_st_stock,
    calc_price_boundary,
    check_limit_trade,
    enrich_bar_with_boundary,
)


# ═══════════════════════════════════════════════════════════════
# Mock Bar for testing check_limit_trade
# ═══════════════════════════════════════════════════════════════

class MockBar:
    def __init__(self, close, symbol, prev_close=None, limit_up_price=None, limit_down_price=None):
        self.close = close
        self.symbol = symbol
        self.prev_close = prev_close
        self.limit_up_price = limit_up_price
        self.limit_down_price = limit_down_price


# ═══════════════════════════════════════════════════════════════
# 1. MarketType 枚举测试
# ═══════════════════════════════════════════════════════════════

class TestMarketTypeEnum(unittest.TestCase):
    """测试 MarketType 枚举定义。"""

    def test_all_members_present(self):
        required = {"MAIN_BOARD", "CHINEXT", "STAR", "ST", "BEI"}
        actual = set(MarketType.__members__.keys())
        missing = required - actual
        self.assertFalse(missing, f"缺少板块枚举: {missing}")

    def test_values_match_string(self):
        self.assertEqual(MarketType.MAIN_BOARD.value, "main")
        self.assertEqual(MarketType.CHINEXT.value, "chinext")
        self.assertEqual(MarketType.STAR.value, "star")
        self.assertEqual(MarketType.ST.value, "st")
        self.assertEqual(MarketType.BEI.value, "bei")


# ═══════════════════════════════════════════════════════════════
# 2. 涨跌幅常量表测试
# ═══════════════════════════════════════════════════════════════

class TestLimitRatios(unittest.TestCase):
    """测试涨跌幅常量表定义。"""

    def test_limit_up_ratios(self):
        self.assertAlmostEqual(LIMIT_UP_RATIO[MarketType.MAIN_BOARD], 0.10)
        self.assertAlmostEqual(LIMIT_UP_RATIO[MarketType.CHINEXT], 0.20)
        self.assertAlmostEqual(LIMIT_UP_RATIO[MarketType.STAR], 0.20)
        self.assertAlmostEqual(LIMIT_UP_RATIO[MarketType.ST], 0.05)
        self.assertAlmostEqual(LIMIT_UP_RATIO[MarketType.BEI], 0.30)

    def test_limit_down_ratios(self):
        self.assertAlmostEqual(LIMIT_DOWN_RATIO[MarketType.MAIN_BOARD], -0.10)
        self.assertAlmostEqual(LIMIT_DOWN_RATIO[MarketType.CHINEXT], -0.20)
        self.assertAlmostEqual(LIMIT_DOWN_RATIO[MarketType.STAR], -0.20)
        self.assertAlmostEqual(LIMIT_DOWN_RATIO[MarketType.ST], -0.05)
        self.assertAlmostEqual(LIMIT_DOWN_RATIO[MarketType.BEI], -0.30)

    def test_symmetric(self):
        for mt in MarketType:
            self.assertAlmostEqual(LIMIT_UP_RATIO[mt], -LIMIT_DOWN_RATIO[mt])


# ═══════════════════════════════════════════════════════════════
# 3. get_market_type 股票代码→板块映射测试
# ═══════════════════════════════════════════════════════════════

class TestGetMarketType(unittest.TestCase):
    """测试 get_market_type 板块判定。"""

    def test_sh_main_board(self):
        self.assertEqual(get_market_type("600000"), MarketType.MAIN_BOARD)
        self.assertEqual(get_market_type("601857"), MarketType.MAIN_BOARD)
        self.assertEqual(get_market_type("603259"), MarketType.MAIN_BOARD)

    def test_sz_main_board(self):
        self.assertEqual(get_market_type("000001"), MarketType.MAIN_BOARD)
        self.assertEqual(get_market_type("001979"), MarketType.MAIN_BOARD)

    def test_sme_board(self):
        self.assertEqual(get_market_type("002415"), MarketType.MAIN_BOARD)
        self.assertEqual(get_market_type("002594"), MarketType.MAIN_BOARD)

    def test_chinext(self):
        self.assertEqual(get_market_type("300750"), MarketType.CHINEXT)
        self.assertEqual(get_market_type("300059"), MarketType.CHINEXT)

    def test_star(self):
        self.assertEqual(get_market_type("688981"), MarketType.STAR)
        self.assertEqual(get_market_type("688036"), MarketType.STAR)

    def test_bei(self):
        self.assertEqual(get_market_type("830799"), MarketType.BEI)
        self.assertEqual(get_market_type("872925"), MarketType.BEI)

    def test_with_suffix(self):
        self.assertEqual(get_market_type("600000.SH"), MarketType.MAIN_BOARD)
        self.assertEqual(get_market_type("300750.SZ"), MarketType.CHINEXT)
        self.assertEqual(get_market_type("688981.SH"), MarketType.STAR)
        self.assertEqual(get_market_type("830799.BJ"), MarketType.BEI)

    def test_unknown_fallback_to_main(self):
        self.assertEqual(get_market_type("999999"), MarketType.MAIN_BOARD)
        self.assertEqual(get_market_type(""), MarketType.MAIN_BOARD)


# ═══════════════════════════════════════════════════════════════
# 4. is_st_stock ST 判定测试
# ═══════════════════════════════════════════════════════════════

class TestIsStStock(unittest.TestCase):
    def test_st_prefix(self):
        self.assertTrue(is_st_stock("ST康美"))
        self.assertTrue(is_st_stock("ST华仪"))

    def test_ast_prefix(self):
        self.assertTrue(is_st_stock("*ST盐湖"))
        self.assertTrue(is_st_stock("*ST中天"))

    def test_sst_prefix(self):
        self.assertTrue(is_st_stock("SST华新"))

    def test_non_st(self):
        self.assertFalse(is_st_stock("贵州茅台"))
        self.assertFalse(is_st_stock("中国平安"))
        self.assertFalse(is_st_stock(""))

    def test_case_insensitive(self):
        self.assertTrue(is_st_stock("st康美"))
        self.assertTrue(is_st_stock("*st盐湖"))


# ═══════════════════════════════════════════════════════════════
# 5. calc_price_boundary 边界值计算测试
# ═══════════════════════════════════════════════════════════════

class TestCalcPriceBoundary(unittest.TestCase):
    """测试涨跌停价格边界计算。"""

    def test_main_board(self):
        up, down = calc_price_boundary(100.0, MarketType.MAIN_BOARD)
        self.assertAlmostEqual(up, 110.0)
        self.assertAlmostEqual(down, 90.0)

    def test_chinext(self):
        up, down = calc_price_boundary(100.0, MarketType.CHINEXT)
        self.assertAlmostEqual(up, 120.0)
        self.assertAlmostEqual(down, 80.0)

    def test_star(self):
        up, down = calc_price_boundary(50.0, MarketType.STAR)
        self.assertAlmostEqual(up, 60.0)
        self.assertAlmostEqual(down, 40.0)

    def test_st(self):
        up, down = calc_price_boundary(100.0, MarketType.ST)
        self.assertAlmostEqual(up, 105.0)
        self.assertAlmostEqual(down, 95.0)

    def test_bei(self):
        up, down = calc_price_boundary(10.0, MarketType.BEI)
        self.assertAlmostEqual(up, 13.0)
        self.assertAlmostEqual(down, 7.0)

    def test_precision_rounding(self):
        up, down = calc_price_boundary(8.56, MarketType.MAIN_BOARD)
        self.assertAlmostEqual(up, 9.42)
        self.assertAlmostEqual(down, 7.70)

    def test_boundary_safety(self):
        up, down = calc_price_boundary(0.01, MarketType.MAIN_BOARD)
        self.assertGreaterEqual(up, 0.01)
        self.assertLessEqual(down, 0.01)

    def test_all_markets_covered(self):
        for mt in MarketType:
            up, down = calc_price_boundary(100.0, mt)
            self.assertGreater(up, 100.0)
            self.assertLess(down, 100.0)

    def test_ipo_first_day(self):
        up, down = calc_price_boundary(10.0, MarketType.MAIN_BOARD, is_ipo_first_day=True)
        self.assertAlmostEqual(up, 14.40)
        self.assertAlmostEqual(down, 6.40)

    def test_ipo_non_main_board(self):
        up, down = calc_price_boundary(10.0, MarketType.CHINEXT, is_ipo_first_day=True)
        self.assertAlmostEqual(up, 12.00)
        self.assertAlmostEqual(down, 8.00)

    def test_point_value(self):
        up, down = calc_price_boundary(8.56, MarketType.MAIN_BOARD, point_value=0.001)
        self.assertAlmostEqual(up, 9.416)
        self.assertAlmostEqual(down, 7.704)


# ═══════════════════════════════════════════════════════════════
# 6. check_limit_trade 交易预检测试
# ═══════════════════════════════════════════════════════════════

class TestCheckLimitTrade(unittest.TestCase):
    """测试涨跌停交易预检。"""

    def test_normal_buy_allowed(self):
        bar = MockBar(close=50.0, symbol="600000", prev_close=50.0)
        allowed, reason = check_limit_trade(bar, "buy", prev_close=50.0, market_type=MarketType.MAIN_BOARD)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_normal_sell_allowed(self):
        bar = MockBar(close=50.0, symbol="600000", prev_close=50.0)
        allowed, reason = check_limit_trade(bar, "sell", prev_close=50.0, market_type=MarketType.MAIN_BOARD)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_limit_up_buy_rejected(self):
        bar = MockBar(close=110.0, symbol="600000", prev_close=100.0,
                      limit_up_price=110.0, limit_down_price=90.0)
        allowed, reason = check_limit_trade(bar, "buy")
        self.assertFalse(allowed)
        self.assertIn("涨停", reason)
        self.assertIn("110", reason)

    def test_limit_down_sell_rejected(self):
        bar = MockBar(close=90.0, symbol="600000", prev_close=100.0,
                      limit_up_price=110.0, limit_down_price=90.0)
        allowed, reason = check_limit_trade(bar, "sell")
        self.assertFalse(allowed)
        self.assertIn("跌停", reason)
        self.assertIn("90", reason)

    def test_limit_down_sell_allowed_not_at_limit(self):
        bar = MockBar(close=91.0, symbol="600000", prev_close=100.0,
                      limit_up_price=110.0, limit_down_price=90.0)
        allowed, reason = check_limit_trade(bar, "sell")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_limit_up_buy_allowed_below(self):
        bar = MockBar(close=109.0, symbol="600000", prev_close=100.0,
                      limit_up_price=110.0, limit_down_price=90.0)
        allowed, reason = check_limit_trade(bar, "buy")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_auto_detect_market_type(self):
        bar = MockBar(close=120.0, symbol="300750", prev_close=100.0)
        allowed, reason = check_limit_trade(bar, "buy", prev_close=100.0)
        self.assertFalse(allowed)
        self.assertIn("涨停", reason)

    def test_no_prev_close_default_allowed(self):
        bar = MockBar(close=100.0, symbol="600000")
        allowed, reason = check_limit_trade(bar, "buy")
        self.assertTrue(allowed)

    def test_chinext_limit_up(self):
        bar = MockBar(close=120.0, symbol="300750", prev_close=100.0)
        allowed, reason = check_limit_trade(bar, "buy", prev_close=100.0, market_type=MarketType.CHINEXT)
        self.assertFalse(allowed)

    def test_chinext_not_at_limit(self):
        bar = MockBar(close=119.0, symbol="300750", prev_close=100.0)
        allowed, reason = check_limit_trade(bar, "buy", prev_close=100.0, market_type=MarketType.CHINEXT)
        self.assertTrue(allowed)

    def test_st_limit_up(self):
        bar = MockBar(close=10.50, symbol="600000", prev_close=10.0)
        allowed, reason = check_limit_trade(bar, "buy", prev_close=10.0, market_type=MarketType.ST)
        self.assertFalse(allowed)

    def test_star_limit_up(self):
        bar = MockBar(close=60.0, symbol="688981", prev_close=50.0)
        allowed, reason = check_limit_trade(bar, "buy", prev_close=50.0)
        self.assertFalse(allowed)

    def test_bei_limit_up(self):
        bar = MockBar(close=13.0, symbol="830799", prev_close=10.0)
        allowed, reason = check_limit_trade(bar, "buy", prev_close=10.0)
        self.assertFalse(allowed)

    def test_invalid_side_allowed(self):
        bar = MockBar(close=110.0, symbol="600000", prev_close=100.0)
        allowed, reason = check_limit_trade(bar, "invalid")
        self.assertTrue(allowed)


# ═══════════════════════════════════════════════════════════════
# 7. enrich_bar_with_boundary 注入测试
# ═══════════════════════════════════════════════════════════════

class TestEnrichBar(unittest.TestCase):
    def test_enrich_main_board(self):
        bar = MockBar(close=100.0, symbol="600000", prev_close=100.0)
        enrich_bar_with_boundary(bar, prev_close=100.0, market_type=MarketType.MAIN_BOARD)
        self.assertTrue(hasattr(bar, 'limit_up_price'))
        self.assertTrue(hasattr(bar, 'limit_down_price'))
        self.assertAlmostEqual(bar.limit_up_price, 110.0)
        self.assertAlmostEqual(bar.limit_down_price, 90.0)
        self.assertEqual(bar.market_type, "main")

    def test_enrich_chinext(self):
        bar = MockBar(close=100.0, symbol="300750", prev_close=100.0)
        enrich_bar_with_boundary(bar, market_type=MarketType.CHINEXT)
        self.assertAlmostEqual(bar.limit_up_price, 120.0)
        self.assertAlmostEqual(bar.limit_down_price, 80.0)

    def test_enrich_auto_detect(self):
        bar = MockBar(close=50.0, symbol="688981", prev_close=50.0)
        enrich_bar_with_boundary(bar, prev_close=50.0)
        self.assertAlmostEqual(bar.limit_up_price, 60.0)
        self.assertAlmostEqual(bar.limit_down_price, 40.0)

    def test_enrich_after_check(self):
        """注入后预检正确。"""
        bar = MockBar(close=55.0, symbol="600000", prev_close=50.0)
        enrich_bar_with_boundary(bar, prev_close=50.0, market_type=MarketType.MAIN_BOARD)

        allowed, reason = check_limit_trade(bar, "buy")
        self.assertFalse(allowed)
        self.assertIn("涨停", reason)

        allowed, _ = check_limit_trade(bar, "sell")
        self.assertTrue(allowed)


# ═══════════════════════════════════════════════════════════════
# 8. 集成测试
# ═══════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):
    def test_market_type_to_boundary_to_check(self):
        """完整链路：板块判定 → 边界计算 → 交易预检。"""
        code = "688981"
        mt = get_market_type(code)
        self.assertEqual(mt, MarketType.STAR)

        prev_close = 80.0
        up, down = calc_price_boundary(prev_close, mt)
        self.assertAlmostEqual(up, 96.0)
        self.assertAlmostEqual(down, 64.0)

        bar = MockBar(close=96.0, symbol=code, prev_close=prev_close,
                      limit_up_price=up, limit_down_price=down)
        allowed, _ = check_limit_trade(bar, "buy")
        self.assertFalse(allowed)

        allowed, _ = check_limit_trade(bar, "sell")
        self.assertTrue(allowed)

    def test_all_boards_integration(self):
        test_cases = [
            ("600000", 100.0, 110.0, 90.0),
            ("300750", 100.0, 120.0, 80.0),
            ("688981", 50.0, 60.0, 40.0),
            ("000001", 100.0, 105.0, 95.0),
            ("830799", 10.0, 13.0, 7.0),
        ]
        for code, prev_close, exp_up, exp_down in test_cases:
            mt = get_market_type(code)
            if code == "000001":
                mt = MarketType.ST
            up, down = calc_price_boundary(prev_close, mt)
            self.assertAlmostEqual(up, exp_up, msg=f"{code}: 涨停价")
            self.assertAlmostEqual(down, exp_down, msg=f"{code}: 跌停价")


# ═══════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════

def create_test_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Collect all TestCase classes from this module
    for name, obj in globals().items():
        if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and name.startswith("Test"):
            suite.addTests(loader.loadTestsFromTestCase(obj))

    return suite


if __name__ == "__main__":
    suite = create_test_suite()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print(f"\n{'='*60}")
    print(f"Test result: {result.testsRun} tests run, "
          f"{len(result.failures)} failures, "
          f"{len(result.errors)} errors")
    sys.exit(0 if result.wasSuccessful() else 1)
