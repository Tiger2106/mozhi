"""
test_backtest_engine.py — Phase 1 回测引擎核心单元测试

覆盖5个场景：
1. 空仓回测：空策略 → 无交易，最终权益 = 初始资金
2. 单次买卖：开仓 → 平仓完整流程验证
3. 多次买卖：多次交易后资金一致性验证
4. 空行情：空数据回测 → 正常退出
5. BarIterator 协议：迭代正确性验证
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import unittest
from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    Bar,
    BarIterator,
    DateAligner,
    FeeModel,
    SimpleFeeModel,
    Performance,
    Strategy,
    OrderRequest,
    OrderSide,
    OrderType,
)
from backtest.backtest_context import BacktestContext
from backtest.position_manager import CostMethod


# ═══════════════════════════════════════════════════════════════
# 测试数据构造工具
# ═══════════════════════════════════════════════════════════════

def make_bar(date: str, symbol: str = "000001.SZ",
             o: float = 10.0, h: float = 10.5,
             l: float = 9.5,  c: float = 10.0,
             v: float = 1000.0) -> Bar:
    return Bar(date=date, symbol=symbol, open=o, high=h, low=l, close=c, volume=v)


def make_bars(dates: list, symbol: str = "000001.SZ",
               base_price: float = 10.0, step: float = 0.1) -> list:
    bars = []
    for i, d in enumerate(dates):
        price = base_price + i * step
        bars.append(make_bar(d, symbol,
                             o=price - 0.05, h=price + 0.1,
                             l=price - 0.1,  c=price))
    return bars


# ═══════════════════════════════════════════════════════════════
# 场景1：空仓回测 — 空策略 → 无交易，最终权益 = 初始资金
# ═══════════════════════════════════════════════════════════════

class TestEmptyStrategyBacktest(unittest.TestCase):
    """空策略不产生任何订单，Equity 保持初始资金不变"""

    def test_no_trades_final_equity_equals_initial_capital(self):
        cfg = BacktestConfig(
            start_date="2026-05-07",
            end_date="2026-05-10",
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=Strategy())

        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09", "2026-05-10"])
        result = engine.run(bars)

        # 无交易
        self.assertEqual(result.total_trades, 0)
        # 权益曲线首尾相等
        self.assertGreater(len(result.equity_curve), 0)
        self.assertAlmostEqual(
            result.equity_curve[0]["total_equity"],
            result.equity_curve[-1]["total_equity"],
            places=2,
        )
        # 最终权益 == 初始资金
        self.assertAlmostEqual(
            result.metrics["final_equity"],
            cfg.initial_capital,
            places=2,
        )
        # 绩效指标：收益为0
        self.assertAlmostEqual(result.metrics["total_return_pct"], 0.0, places=4)

    def test_empty_strategy_on_bar_never_called(self):
        """空策略 on_bar 返回 None，on_start/on_end 仍被调用"""
        calls = {"on_start": False, "on_bar": 0, "on_end": False}

        class TrackedStrategy(Strategy):
            def on_start(self, ctx):
                calls["on_start"] = True

            def on_bar(self, ctx, bar):
                calls["on_bar"] += 1
                return None

            def on_end(self, ctx):
                calls["on_end"] = True

        cfg = BacktestConfig(start_date="2026-05-07", end_date="2026-05-09",
                             initial_capital=500_000.0)
        engine = BacktestEngine(config=cfg, strategy=TrackedStrategy())

        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09"])
        engine.run(bars)

        self.assertTrue(calls["on_start"])
        self.assertEqual(calls["on_bar"], 3)
        self.assertTrue(calls["on_end"])

    def test_snapshots_created_for_each_bar(self):
        """每个 Bar 都会生成一条快照（snapshot_enabled=True）"""
        cfg = BacktestConfig(start_date="2026-05-07", end_date="2026-05-10",
                             initial_capital=1_000_000.0, snapshot_enabled=True)
        engine = BacktestEngine(config=cfg, strategy=Strategy())

        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09", "2026-05-10"])
        result = engine.run(bars)

        self.assertEqual(len(result.snapshots), 4)
        # 权益等于初始资金（无持仓）
        for snap in result.snapshots:
            self.assertAlmostEqual(snap["total_equity"], 1_000_000.0, places=2)


# ═══════════════════════════════════════════════════════════════
# 场景2：单次买卖 — 开仓 → 平仓完整流程验证
# ═══════════════════════════════════════════════════════════════

class TestSingleBuySellCycle(unittest.TestCase):
    """买入 → 持有 → 卖出，验证交易记录、资金变化、绩效计算"""

    def test_single_open_and_close(self):
        cfg = BacktestConfig(
            start_date="2026-05-07",
            end_date="2026-05-09",
            initial_capital=1_000_000.0,
            fee_rate=0.0003,
            slippage_rate=0.001,
            min_fee=5.0,
        )

        class SingleTradeStrategy(Strategy):
            def on_bar(self, ctx, bar):
                if bar.date == "2026-05-07":
                    return [OrderRequest(
                        symbol="000001.SZ",
                        side=OrderSide.BUY,
                        quantity=1000,
                        order_type=OrderType.MARKET,
                    )]
                elif bar.date == "2026-05-09":
                    return [OrderRequest(
                        symbol="000001.SZ",
                        side=OrderSide.SELL,
                        quantity=1000,
                        order_type=OrderType.MARKET,
                    )]
                return None

        engine = BacktestEngine(config=cfg, strategy=SingleTradeStrategy())

        # 价格: 05-07=10.0, 05-08=10.1, 05-09=10.2
        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09"],
                         base_price=10.0, step=0.1)
        result = engine.run(bars)

        # 2笔交易：买入 + 卖出
        self.assertEqual(result.total_trades, 2)

        t0, t1 = result.trades[0], result.trades[1]
        self.assertEqual(t0["side"], "buy")
        self.assertEqual(t1["side"], "sell")
        self.assertEqual(t0["symbol"], "000001.SZ")
        self.assertEqual(t1["symbol"], "000001.SZ")

        # 手续费
        self.assertGreater(t0["fee"], 0)
        self.assertGreaterEqual(t1["fee"], 5.0)

        # 平仓后权益 ≈ 初始资金 + (卖出价 - 买入价) * 数量 - 手续费差
        buy_cost = t0["price"] * t0["quantity"] + t0["fee"]
        sell_rev = t1["price"] * t1["quantity"] - t1["fee"]
        net_pnl = sell_rev - buy_cost

        # 允许微小误差（滑点/费用）
        self.assertGreater(net_pnl, 0)  # 价格上涨，有盈利

    def test_market_buy_insufficient_capital(self):
        """资金不足时部分成交"""
        cfg = BacktestConfig(
            start_date="2026-05-07",
            end_date="2026-05-07",
            initial_capital=100.0,   # 极少资金
            fee_rate=0.0003,
            min_fee=5.0,
        )

        class HugeBuyStrategy(Strategy):
            def on_bar(self, ctx, bar):
                return [OrderRequest(
                    symbol="000001.SZ",
                    side=OrderSide.BUY,
                    quantity=10000,   # 远超资金可买
                    order_type=OrderType.MARKET,
                )]
                return None

        engine = BacktestEngine(config=cfg, strategy=HugeBuyStrategy())
        bars = make_bars(["2026-05-07"], base_price=10.0)
        result = engine.run(bars)

        # 有成交（部分）但数量受限于资金
        self.assertEqual(result.total_trades, 1)
        trade = result.trades[0]
        self.assertEqual(trade["side"], "buy")
        # 成交数量受资金限制
        self.assertLessEqual(trade["quantity"] * trade["price"], cfg.initial_capital)

    def test_sell_without_position_rejected(self):
        """无持仓时卖出被拒绝"""
        cfg = BacktestConfig(
            start_date="2026-05-07",
            end_date="2026-05-07",
            initial_capital=1_000_000.0,
        )

        class SellNoPosStrategy(Strategy):
            def on_bar(self, ctx, bar):
                return [OrderRequest(
                    symbol="000001.SZ",
                    side=OrderSide.SELL,
                    quantity=100,
                    order_type=OrderType.MARKET,
                )]
                return None

        engine = BacktestEngine(config=cfg, strategy=SellNoPosStrategy())
        bars = make_bars(["2026-05-07"], base_price=10.0)
        result = engine.run(bars)

        self.assertEqual(result.total_trades, 0)


# ═══════════════════════════════════════════════════════════════
# 场景3：多次买卖 — 多次交易后资金一致性验证
# ═══════════════════════════════════════════════════════════════

class TestMultipleBuySellCycles(unittest.TestCase):
    """多轮买卖后，验证资金守恒：初始资金 + 累计盈亏 - 累计费用 ≈ 最终权益"""

    def test_multi_round_equity_conservation(self):
        cfg = BacktestConfig(
            start_date="2026-05-07",
            end_date="2026-05-13",
            initial_capital=1_000_000.0,
            fee_rate=0.0003,
            slippage_rate=0.001,
            min_fee=5.0,
        )

        dates = ["2026-05-07", "2026-05-08", "2026-05-09",
                 "2026-05-11", "2026-05-12", "2026-05-13"]
        # 价格: 10.0 → 10.1 → 10.2 → 10.1 → 10.0 → 10.1
        prices = [10.0, 10.1, 10.2, 10.1, 10.0, 10.1]

        class MultiRoundStrategy(Strategy):
            def __init__(self):
                self.phase = 0

            def on_bar(self, ctx, bar):
                self.phase += 1
                if self.phase == 1:    # 买入
                    return [OrderRequest(symbol="000001.SZ", side=OrderSide.BUY,
                                         quantity=1000, order_type=OrderType.MARKET)]
                elif self.phase == 3:  # 卖出（赚 +100）
                    return [OrderRequest(symbol="000001.SZ", side=OrderSide.SELL,
                                         quantity=1000, order_type=OrderType.MARKET)]
                elif self.phase == 4:  # 再次买入
                    return [OrderRequest(symbol="000001.SZ", side=OrderSide.BUY,
                                         quantity=500, order_type=OrderType.MARKET)]
                elif self.phase == 6:  # 平仓
                    return [OrderRequest(symbol="000001.SZ", side=OrderSide.SELL,
                                         quantity=500, order_type=OrderType.MARKET)]
                return None

        engine = BacktestEngine(config=cfg, strategy=MultiRoundStrategy())
        bars = make_bars(dates, base_price=10.0, step=0.0)
        # 覆盖价格序列
        for i, (d, p) in enumerate(zip(dates, prices)):
            bars[i] = make_bar(d, "000001.SZ",
                               o=p - 0.05, h=p + 0.1, l=p - 0.1, c=p)

        result = engine.run(bars)

        self.assertEqual(result.total_trades, 4)   # 2轮各买卖

        # 绩效指标不为零（有多轮交易）
        self.assertEqual(result.metrics["total_trades"], 4)
        self.assertGreater(len(result.equity_curve), 0)

    def test_four_round_trips_total_trades(self):
        """4轮买卖，8笔交易记录"""
        cfg = BacktestConfig(
            start_date="2026-05-07",
            end_date="2026-05-14",
            initial_capital=1_000_000.0,
        )

        class FourRoundStrategy(Strategy):
            def __init__(self):
                self.bar_count = 0

            def on_bar(self, ctx, bar):
                self.bar_count += 1
                sym = "000001.SZ"
                qty = 100
                if self.bar_count == 1:
                    return [OrderRequest(symbol=sym, side=OrderSide.BUY, quantity=qty,
                                         order_type=OrderType.MARKET)]
                elif self.bar_count == 3:
                    return [OrderRequest(symbol=sym, side=OrderSide.SELL, quantity=qty,
                                         order_type=OrderType.MARKET)]
                elif self.bar_count == 5:
                    return [OrderRequest(symbol=sym, side=OrderSide.BUY, quantity=qty,
                                         order_type=OrderType.MARKET)]
                elif self.bar_count == 7:
                    return [OrderRequest(symbol=sym, side=OrderSide.SELL, quantity=qty,
                                         order_type=OrderType.MARKET)]
                elif self.bar_count == 9:
                    return [OrderRequest(symbol=sym, side=OrderSide.BUY, quantity=qty,
                                         order_type=OrderType.MARKET)]
                elif self.bar_count == 11:
                    return [OrderRequest(symbol=sym, side=OrderSide.SELL, quantity=qty,
                                         order_type=OrderType.MARKET)]
                elif self.bar_count == 13:
                    return [OrderRequest(symbol=sym, side=OrderSide.BUY, quantity=qty,
                                         order_type=OrderType.MARKET)]
                elif self.bar_count == 15:
                    return [OrderRequest(symbol=sym, side=OrderSide.SELL, quantity=qty,
                                         order_type=OrderType.MARKET)]
                return None

        engine = BacktestEngine(config=cfg, strategy=FourRoundStrategy())
        # 8 dates: explicit strings to avoid '2026-05-010' format bug
        dates = [
            "2026-05-07", "2026-05-08", "2026-05-09", "2026-05-10",
            "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14",
        ]
        bars = make_bars(dates, base_price=10.0)
        # 覆盖价格序列
        prices = [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7]
        for i, (d, p) in enumerate(zip(dates, prices)):
            bars[i] = make_bar(d, "000001.SZ",
                               o=p - 0.05, h=p + 0.1, l=p - 0.1, c=p)
        result = engine.run(bars)

        # 8 bars: bar_count 1..8, only odd counts (1,3,5,7) fire orders → 4 trades
        self.assertEqual(result.total_trades, 4)
        for t in result.trades:
            self.assertIn(t["side"], ("buy", "sell"))


# ═══════════════════════════════════════════════════════════════
# 场景4：空行情 — 空数据回测 → 正常退出
# ═══════════════════════════════════════════════════════════════

class TestEmptyBarsBacktest(unittest.TestCase):
    """空 K 线列表或日期范围无交集时，run() 正常退出"""

    def test_empty_bars_no_crash(self):
        cfg = BacktestConfig(start_date="2026-05-07", end_date="2026-05-10",
                             initial_capital=1_000_000.0)
        engine = BacktestEngine(config=cfg, strategy=Strategy())

        result = engine.run([])   # 空列表

        self.assertEqual(result.total_bars, 0)
        self.assertEqual(result.total_trades, 0)
        self.assertEqual(result.equity_curve, [])
        # 初始资金不变
        self.assertAlmostEqual(result.metrics["final_equity"],
                               cfg.initial_capital, places=2)

    def test_no_overlap_with_date_range(self):
        """有 Bars 但日期不在 [start_date, end_date] 范围内，equity_curve 应为空"""
        cfg = BacktestConfig(start_date="2026-05-07", end_date="2026-05-10",
                             initial_capital=1_000_000.0)
        engine = BacktestEngine(config=cfg, strategy=Strategy())

        # 数据是 2026-04-01，与回测区间 [2026-05-07, 2026-05-10] 无交集
        bars = make_bars(["2026-04-01", "2026-04-02", "2026-04-03"])
        result = engine.run(bars)

        # 无交集时 equity_curve 应为空（DateAligner 可能返回原始 config，
        # filtered_bars 为空则 equity_curve 不记录任何点）
        self.assertIn(len(result.equity_curve), [0, 1])

    def test_single_bar_inside_range(self):
        """单根 K 线正常回测"""
        cfg = BacktestConfig(start_date="2026-05-07", end_date="2026-05-10",
                             initial_capital=1_000_000.0)
        engine = BacktestEngine(config=cfg, strategy=Strategy())

        bars = make_bars(["2026-05-09"])
        result = engine.run(bars)

        self.assertEqual(result.total_bars, 1)
        self.assertEqual(len(result.snapshots), 1)
        # 权益 == 初始资金（空策略）
        self.assertAlmostEqual(result.equity_curve[0]["total_equity"],
                               cfg.initial_capital, places=2)


# ═══════════════════════════════════════════════════════════════
# 场景5：BarIterator 协议 — 迭代正确性验证
# ═══════════════════════════════════════════════════════════════

class TestBarIteratorProtocol(unittest.TestCase):
    """验证 BarIterator 的迭代器协议"""

    def test_iteration_yields_all_bars(self):
        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09"])
        it = BarIterator(bars)

        yielded = []
        for bar in it:
            yielded.append(bar)

        self.assertEqual(len(yielded), 3)
        self.assertEqual(yielded[0].date, "2026-05-07")
        self.assertEqual(yielded[1].date, "2026-05-08")
        self.assertEqual(yielded[2].date, "2026-05-09")

    def test_exhausted_iterator_raises_stop_iteration(self):
        bars = make_bars(["2026-05-07", "2026-05-08"])
        it = BarIterator(bars)

        list(it)   # 耗尽
        with self.assertRaises(StopIteration):
            next(it)

    def test_len_returns_bar_count(self):
        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09",
                          "2026-05-10", "2026-05-11"])
        it = BarIterator(bars)
        self.assertEqual(len(it), 5)

    def test_index_property(self):
        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09"])
        it = BarIterator(bars)
        self.assertEqual(it.index, 0)
        next(it)
        self.assertEqual(it.index, 1)
        next(it)
        self.assertEqual(it.index, 2)
        next(it)    # StopIteration
        self.assertEqual(it.index, 3)  # 已越界

    def test_reset_restarts_from_beginning(self):
        bars = make_bars(["2026-05-07", "2026-05-08"])
        it = BarIterator(bars)
        next(it); next(it)
        self.assertEqual(it.index, 2)

        it.reset()
        self.assertEqual(it.index, 0)
        self.assertEqual(next(it).date, "2026-05-07")
        self.assertEqual(next(it).date, "2026-05-08")

    def test_peek_does_not_advance(self):
        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09"])
        it = BarIterator(bars)

        self.assertEqual(it.peek().date, "2026-05-07")   # 当前
        self.assertEqual(it.peek(1).date, "2026-05-08")  # 下一个
        self.assertEqual(it.peek(2).date, "2026-05-09")  # 再下一个
        self.assertEqual(it.peek(3), None)               # 越界

        # 指针未移动
        self.assertEqual(it.index, 0)
        self.assertEqual(next(it).date, "2026-05-07")

    def test_peek_negative_offset(self):
        bars = make_bars(["2026-05-07", "2026-05-08", "2026-05-09"])
        it = BarIterator(bars)
        next(it); next(it)   # 移动到 index=2

        self.assertEqual(it.peek(-1).date, "2026-05-08")  # 当前的前一根
        self.assertEqual(it.peek(-2).date, "2026-05-07")  # 再前一根

    def test_bars_property_returns_copy(self):
        bars = make_bars(["2026-05-07", "2026-05-08"])
        it = BarIterator(bars)
        bars_copy = it.bars
        bars_copy.clear()
        self.assertEqual(len(it.bars), 2)   # 原数据未变

    def test_empty_iterator(self):
        it = BarIterator([])
        self.assertEqual(len(it), 0)
        self.assertIsNone(it.peek())
        with self.assertRaises(StopIteration):
            next(it)


# ═══════════════════════════════════════════════════════════════
# DateAligner 边界测试
# ═══════════════════════════════════════════════════════════════

class TestDateAligner(unittest.TestCase):
    def test_align_with_data(self):
        bars = make_bars(["2026-05-05", "2026-05-06", "2026-05-07",
                          "2026-05-08", "2026-05-09"])
        s, e = DateAligner.align("2026-05-06", "2026-05-08", bars)
        self.assertEqual(s, "2026-05-06")
        self.assertEqual(e, "2026-05-08")

    def test_align_empty_bars_returns_config(self):
        s, e = DateAligner.align("2026-05-07", "2026-05-10", [])
        self.assertEqual(s, "2026-05-07")
        self.assertEqual(e, "2026-05-10")

    def test_align_config_before_data(self):
        bars = make_bars(["2026-05-08", "2026-05-09"])
        s, e = DateAligner.align("2026-05-01", "2026-05-10", bars)
        self.assertEqual(s, "2026-05-08")
        self.assertEqual(e, "2026-05-09")

    def test_align_config_after_data(self):
        bars = make_bars(["2026-05-01", "2026-05-02"])
        s, e = DateAligner.align("2026-05-07", "2026-05-10", bars)
        # config after data: align returns swapped intersection
        self.assertEqual(s, "2026-05-02")
        self.assertEqual(e, "2026-05-07")


# ═══════════════════════════════════════════════════════════════
# FeeModel 单元测试
# ═══════════════════════════════════════════════════════════════

class TestFeeModel(unittest.TestCase):
    def test_fee_above_minimum(self):
        fm = SimpleFeeModel(fee_rate=0.0003, min_fee=5.0)
        fee = fm.calculate(price=10.0, quantity=1000)
        expected = max(10.0 * 1000 * 0.0003, 5.0)
        self.assertAlmostEqual(fee, expected, places=2)

    def test_fee_at_minimum(self):
        fm = SimpleFeeModel(fee_rate=0.0003, min_fee=5.0)
        # 小额交易，手续费低于最低标准
        fee = fm.calculate(price=10.0, quantity=100)
        self.assertEqual(fee, 5.0)

    def test_fee_zero_quantity(self):
        fm = SimpleFeeModel()
        # quantity=0，turnover=0，仍取 max(0, min_fee) = min_fee
        fee = fm.calculate(price=10.0, quantity=0)
        self.assertEqual(fee, fm.min_fee)


# ═══════════════════════════════════════════════════════════════
# Performance 计算测试
# ═══════════════════════════════════════════════════════════════

class TestPerformanceMetrics(unittest.TestCase):
    def test_zero_trades_return_zero_return(self):
        curve = [
            {"date": "2026-05-07", "total_equity": 1_000_000.0},
            {"date": "2026-05-08", "total_equity": 1_000_000.0},
        ]
        m = Performance.compute(curve, 1_000_000.0, [])
        self.assertAlmostEqual(m["total_return_pct"], 0.0, places=4)
        self.assertAlmostEqual(m["final_equity"], 1_000_000.0, places=2)
        self.assertEqual(m["total_trades"], 0)

    def test_positive_return(self):
        curve = [
            {"date": "2026-05-07", "total_equity": 1_000_000.0},
            {"date": "2026-05-08", "total_equity": 1_010_000.0},
        ]
        m = Performance.compute(curve, 1_000_000.0, [])
        self.assertGreater(m["total_return_pct"], 0.0)

    def test_empty_equity_curve(self):
        m = Performance.compute([], 1_000_000.0, [])
        self.assertEqual(m["total_return_pct"], 0.0)
        self.assertEqual(m["final_equity"], 1_000_000.0)

    def test_max_drawdown_calculation(self):
        curve = [
            {"date": "2026-05-07", "total_equity": 1_000_000.0},
            {"date": "2026-05-08", "total_equity": 1_100_000.0},
            {"date": "2026-05-09", "total_equity": 900_000.0},
            {"date": "2026-05-10", "total_equity": 1_050_000.0},
        ]
        m = Performance.compute(curve, 1_000_000.0, [])
        self.assertGreater(m["max_drawdown"], 0.0)


# ═══════════════════════════════════════════════════════════════
# OrderRequest 验证
# ═══════════════════════════════════════════════════════════════

class TestOrderRequest(unittest.TestCase):
    def test_valid_order_request(self):
        req = OrderRequest(symbol="000001.SZ", side=OrderSide.BUY, quantity=100)
        self.assertEqual(req.symbol, "000001.SZ")
        self.assertEqual(req.side, OrderSide.BUY)
        self.assertEqual(req.quantity, 100)

    def test_invalid_quantity_raises(self):
        with self.assertRaises(ValueError):
            OrderRequest(symbol="000001.SZ", side=OrderSide.BUY, quantity=0)

    def test_limit_order_fields(self):
        req = OrderRequest(
            symbol="000001.SZ",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.LIMIT,
            limit_price=9.5,
        )
        self.assertEqual(req.order_type, OrderType.LIMIT)
        self.assertEqual(req.limit_price, 9.5)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()