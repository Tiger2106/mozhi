"""
P1-15 订单执行器单元测试
覆盖：市价单、限价单、部分成交、滑点模型
"""
import pytest

from backtest.backtest_context import BacktestContext
from backtest.order_executor import (
    FillReport,
    OrderExecutor,
    OrderSide,
    OrderType,
    TradeRecord,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ctx():
    """默认100万资金的回测上下文。"""
    return BacktestContext(initial_capital=1_000_000.0)


@pytest.fixture
def exec_(ctx):
    """默认滑点0.1%手续0.03%的订单执行器。"""
    return OrderExecutor(context=ctx, slippage_rate=0.001, fee_rate=0.0003)


@pytest.fixture
def ctx_zero_slip(ctx):
    c = BacktestContext(initial_capital=1_000_000.0)
    return c


@pytest.fixture
def exec_zero_slip(ctx_zero_slip):
    return OrderExecutor(context=ctx_zero_slip, slippage_rate=0.0, fee_rate=0.0003)


@pytest.fixture
def ctx_fixed_slip():
    c = BacktestContext(initial_capital=1_000_000.0)
    return c


@pytest.fixture
def exec_fixed_slip(ctx_fixed_slip):
    return OrderExecutor(
        context=ctx_fixed_slip,
        slippage_rate=0.0,   # 固定滑点模型用 fill_price 传入
        fee_rate=0.0003,
    )


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def market_buy(exec_, symbol, qty, price):
    exec_.context.on_bar("2026-01-10", symbol)
    return exec_.execute_market(symbol, OrderSide.BUY, qty, price)


def limit_buy(exec_, symbol, qty, limit_price, current_price):
    exec_.context.on_bar("2026-01-10", symbol)
    return exec_.execute_limit(symbol, OrderSide.BUY, qty, limit_price, current_price)


# ══════════════════════════════════════════════════════════════════════════════
# 1. 市价单测试
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketOrder:
    """市价单立即成交 + 滑点调整价格验证"""

    def test_market_buy_filled(self, exec_, ctx):
        """买入市价单：全部成交，滑点向上调整"""
        report = market_buy(exec_, "000001.SZ", 100, 10.0)

        assert report.filled is True
        assert report.fill_quantity == 100
        assert report.partial is False
        assert report.remaining == 0

        # 滑点向上：fill_price = 10.0 * (1 + 0.001) = 10.01
        assert report.fill_price == 10.01
        assert report.trade.slippage == 0.001
        assert report.trade.order_type == OrderType.MARKET
        assert "全部成交" in report.message

        # 持仓验证
        pos = ctx.positions.get("000001.SZ")
        assert pos is not None
        assert pos.quantity == 100
        assert ctx.capital.available < 1_000_000.0   # 资金已扣除

    def test_market_sell_filled(self, exec_, ctx):
        """卖出市价单：先开仓再卖出，滑点向下"""
        # 先买入建仓
        market_buy(exec_, "000001.SZ", 100, 10.0)

        # 再卖出
        exec_.context.on_bar("2026-01-11", "000001.SZ")
        report = exec_.execute_market("000001.SZ", OrderSide.SELL, 100, 10.0)

        assert report.filled is True
        assert report.fill_quantity == 100
        # 滑点向下：fill_price = 10.0 * (1 - 0.001) = 9.99
        assert report.fill_price == 9.99
        assert report.trade.side == OrderSide.SELL
        assert report.message == "市价卖出成交（全部成交）"

    def test_market_buy_insufficient_capital(self, exec_, ctx):
        """资金不足时部分成交：自动按最大可成交量执行"""
        # 100万资金，股价100元，费0.03%，最低5元
        # 可买数量 = (1000000 - 5) / (100 * 1.0003) ≈ 9995
        report = market_buy(exec_, "600000.SH", 10_000, 100.0)

        assert report.filled is True
        assert report.partial is True
        assert report.fill_quantity < 10_000
        assert report.fill_quantity > 0
        assert "部分成交" in report.message

        # 全部资金被消耗（误差1元以内）
        assert ctx.capital.total_assets <= 1_000_000.0

    def test_market_sell_no_position(self, exec_):
        """无持仓卖出：拒绝成交"""
        exec_.context.on_bar("2026-01-10", "000001.SZ")
        report = exec_.execute_market("000001.SZ", OrderSide.SELL, 100, 10.0)

        assert report.filled is False
        assert report.fill_quantity == 0
        assert "无持仓" in report.message

    def test_market_sell_partial_position(self, exec_, ctx):
        """卖出数量超过持仓：只能卖出实际持有数量"""
        market_buy(exec_, "000001.SZ", 50, 10.0)

        exec_.context.on_bar("2026-01-11", "000001.SZ")
        report = exec_.execute_market("000001.SZ", OrderSide.SELL, 100, 10.0)

        assert report.filled is True
        assert report.partial is True
        assert report.fill_quantity == 50
        assert report.remaining == 0

    def test_trade_history_recorded(self, exec_, ctx):
        """成交记录正确写入历史"""
        market_buy(exec_, "000001.SZ", 100, 10.0)

        history = exec_.get_trade_history()
        assert len(history) == 1
        rec = history[0]
        assert rec["symbol"] == "000001.SZ"
        assert rec["side"] == "buy"
        assert rec["quantity"] == 100
        assert rec["price"] == 10.01
        assert rec["order_type"] == "market"


# ══════════════════════════════════════════════════════════════════════════════
# 2. 限价单测试
# ══════════════════════════════════════════════════════════════════════════════

class TestLimitOrder:
    """限价单：价格触发/未触发场景"""

    def test_limit_buy_triggered(self, exec_, ctx):
        """买入限价：当前价 <= 限价 → 触发成交"""
        # 限价10.0，当前价9.5 → 可触发
        report = limit_buy(exec_, "000001.SZ", 100, limit_price=10.0, current_price=9.5)

        assert report.filled is True
        assert report.fill_price == 10.0       # 限价成交，无额外滑点
        assert report.fill_quantity == 100
        assert report.partial is False
        assert report.trade.slippage == 0.0    # 限价单slippage=0
        assert report.trade.order_type == OrderType.LIMIT

    def test_limit_buy_not_triggered(self, exec_):
        """买入限价：当前价 > 限价 → 不触发"""
        report = limit_buy(exec_, "000001.SZ", 100, limit_price=10.0, current_price=11.0)

        assert report.filled is False
        assert report.fill_quantity == 0
        assert "未触发" in report.message

    def test_limit_sell_triggered(self, exec_, ctx):
        """卖出限价：当前价 >= 限价 → 触发"""
        # 先建仓
        market_buy(exec_, "000001.SZ", 100, 10.0)

        exec_.context.on_bar("2026-01-11", "000001.SZ")
        report = exec_.execute_limit(
            "000001.SZ", OrderSide.SELL, 100,
            limit_price=11.0, current_price=11.5
        )

        assert report.filled is True
        assert report.fill_price == 11.0
        assert report.fill_quantity == 100

    def test_limit_sell_not_triggered(self, exec_, ctx):
        """卖出限价：当前价 < 限价 → 不触发"""
        market_buy(exec_, "000001.SZ", 100, 10.0)

        exec_.context.on_bar("2026-01-11", "000001.SZ")
        report = exec_.execute_limit(
            "000001.SZ", OrderSide.SELL, 100,
            limit_price=12.0, current_price=11.0
        )

        assert report.filled is False
        assert "未触发" in report.message

    def test_limit_buy_partial_on_capital(self, exec_, ctx):
        """限价单触发但资金不足 → 部分成交"""
        # 100万资金，限价100元，可买约9995股
        report = limit_buy(exec_, "600000.SH", 10_000, limit_price=100.0, current_price=99.0)

        assert report.filled is True
        assert report.partial is True
        assert 0 < report.fill_quantity < 10_000

    def test_limit_buy_no_capital(self, exec_):
        """资金耗尽后限价单不成交（0股都无法买）"""
        ctx2 = BacktestContext(initial_capital=1.0)
        exec2 = OrderExecutor(context=ctx2, slippage_rate=0.0, fee_rate=0.0003)
        ctx2.on_bar("2026-01-10", "000001.SZ")

        report = exec2.execute_limit("000001.SZ", OrderSide.BUY, 100, 10.0, 9.5)

        assert report.filled is False
        assert "资金" in report.message or "不足" in report.message


# ══════════════════════════════════════════════════════════════════════════════
# 3. 部分成交测试
# ══════════════════════════════════════════════════════════════════════════════

class TestPartialFill:
    """资金不足时自动按最大可成交量执行"""

    def test_partial_fill_quantity_reduced(self, exec_, ctx):
        """部分成交时 fill_quantity < requested quantity"""
        initial_cash = ctx.capital.available
        report = market_buy(exec_, "600000.SH", 100_000, 50.0)

        assert report.partial is True
        assert report.fill_quantity < 100_000
        assert report.fill_quantity > 0
        # 资金消耗约等于初始资金（留点余地给手续费）
        assert ctx.capital.total_assets < initial_cash

    def test_partial_fill_reports_remaining(self, exec_):
        """部分成交后 remaining=0（因为自动按最大可成交量执行）"""
        report = market_buy(exec_, "600000.SH", 100_000, 50.0)
        assert report.remaining == 0
        assert report.fill_quantity > 0

    def test_sell_exceeds_position_partial(self, exec_, ctx):
        """卖出超过持仓时部分成交"""
        market_buy(exec_, "000001.SZ", 30, 10.0)

        exec_.context.on_bar("2026-01-11", "000001.SZ")
        report = exec_.execute_market("000001.SZ", OrderSide.SELL, 50, 10.0)

        assert report.partial is True
        assert report.fill_quantity == 30   # 只能卖30

    def test_full_fill_properties(self, exec_):
        """全部成交时 is_full_fill=True"""
        report = market_buy(exec_, "000001.SZ", 10, 10.0)
        assert report.is_full_fill is True
        assert report.is_partial_fill is False

    def test_partial_fill_properties(self, exec_):
        """部分成交时 is_partial_fill=True"""
        ctx2 = BacktestContext(initial_capital=500.0)
        exec2 = OrderExecutor(context=ctx2, slippage_rate=0.0, fee_rate=0.0003)
        ctx2.on_bar("2026-01-10", "000001.SZ")
        report = exec2.execute_market("000001.SZ", OrderSide.BUY, 1000, 1.0)

        assert report.is_partial_fill is True
        assert report.is_full_fill is False


# ══════════════════════════════════════════════════════════════════════════════
# 4. 滑点模型测试
# ══════════════════════════════════════════════════════════════════════════════

class TestSlippageModels:
    """固定滑点 / 比例滑点 / 零滑点"""

    def test_zero_slippage(self, exec_zero_slip, ctx):
        """零滑点：fill_price = market_price"""
        exec_zero_slip.context.on_bar("2026-01-10", "000001.SZ")
        report = exec_zero_slip.execute_market("000001.SZ", OrderSide.BUY, 100, 10.0)

        assert report.fill_price == 10.0
        assert report.trade.slippage == 0.0

        # 卖单也零滑点
        exec_zero_slip.context.on_bar("2026-01-11", "000001.SZ")
        exec_zero_slip.context.positions.open_position("000001.SZ", 100, 10.0, 0.0)
        ctx.capital._available = 1_000_000.0

        exec_zero_slip.context.on_bar("2026-01-12", "000001.SZ")
        report2 = exec_zero_slip.execute_market("000001.SZ", OrderSide.SELL, 100, 10.0)
        assert report2.fill_price == 10.0

    def test_proportional_slippage_buy(self):
        """比例滑点（买入）：fill_price = price * (1 + slippage_rate)"""
        ctx = BacktestContext(initial_capital=1_000_000.0)
        exec_ = OrderExecutor(context=ctx, slippage_rate=0.005, fee_rate=0.0)  # 0.5%

        ctx.on_bar("2026-01-10", "000001.SZ")
        report = exec_.execute_market("000001.SZ", OrderSide.BUY, 100, 100.0)

        # 100 * (1 + 0.005) = 100.5
        assert report.fill_price == 100.5
        assert report.trade.slippage == 0.005

    def test_proportional_slippage_sell(self):
        """比例滑点（卖出）：fill_price = price * (1 - slippage_rate)"""
        ctx = BacktestContext(initial_capital=1_000_000.0)
        exec_ = OrderExecutor(context=ctx, slippage_rate=0.005, fee_rate=0.0)  # 0.5%

        ctx.on_bar("2026-01-10", "000001.SZ")
        ctx.positions.open_position("000001.SZ", 100, 100.0, 0.0)
        ctx.capital._available = 1_000_000.0

        ctx.on_bar("2026-01-11", "000001.SZ")
        report = exec_.execute_market("000001.SZ", OrderSide.SELL, 100, 100.0)

        # 100 * (1 - 0.005) = 99.5
        assert report.fill_price == 99.5
        assert report.trade.slippage == 0.005

    def test_fixed_slippage_via_constructor(self):
        """固定滑点模型：OrderExecutor 用 slippage_rate=0，
        调用方通过传入预调价格实现固定滑点"""
        ctx = BacktestContext(initial_capital=1_000_000.0)
        exec_ = OrderExecutor(context=ctx, slippage_rate=0.0, fee_rate=0.0)

        ctx.on_bar("2026-01-10", "000001.SZ")
        # 买入时手动加0.05固定滑点
        fixed_slippage = 0.05
        adjusted_price = round(100.0 + fixed_slippage, 4)
        report = exec_.execute_market("000001.SZ", OrderSide.BUY, 100, adjusted_price)

        assert report.fill_price == 100.05
        assert report.trade.slippage == 0.0  # 执行器记录slippage=0因为rate=0

    def test_various_slippage_rates(self):
        """不同滑点率验证价格正确调整"""
        rates = [0.0, 0.0005, 0.001, 0.003, 0.005, 0.01]
        price = 50.0

        for rate in rates:
            ctx = BacktestContext(initial_capital=1_000_000.0)
            exec_ = OrderExecutor(context=ctx, slippage_rate=rate, fee_rate=0.0)
            ctx.on_bar("2026-01-10", "000001.SZ")

            buy_report = exec_.execute_market("000001.SZ", OrderSide.BUY, 10, price)
            expected_buy = round(price * (1 + rate), 4)
            assert buy_report.fill_price == expected_buy, f"rate={rate} buy failed"

            ctx2 = BacktestContext(initial_capital=1_000_000.0)
            exec2 = OrderExecutor(context=ctx2, slippage_rate=rate, fee_rate=0.0)
            ctx2.on_bar("2026-01-10", "000001.SZ")
            ctx2.positions.open_position("000001.SZ", 10, price, 0.0)
            ctx2.capital._available = 1_000_000.0

            ctx2.on_bar("2026-01-11", "000001.SZ")
            sell_report = exec2.execute_market("000001.SZ", OrderSide.SELL, 10, price)
            expected_sell = round(price * (1 - rate), 4)
            assert sell_report.fill_price == expected_sell, f"rate={rate} sell failed"


# ══════════════════════════════════════════════════════════════════════════════
# 5. FillReport 属性 & 边界
# ══════════════════════════════════════════════════════════════════════════════

class TestFillReport:
    """FillReport 关键属性验证"""

    def test_unfilled_report(self, exec_):
        exec_.context.on_bar("2026-01-10", "000001.SZ")
        report = exec_.execute_market("000001.SZ", OrderSide.SELL, 100, 10.0)

        assert report.filled is False
        assert report.is_full_fill is False
        assert report.is_partial_fill is False
        assert report.trade is None
        assert report.fill_quantity == 0

    def test_message_not_empty(self, exec_):
        report = market_buy(exec_, "000001.SZ", 10, 10.0)
        assert len(report.message) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 6. 手续费验证
# ══════════════════════════════════════════════════════════════════════════════

class TestFee:
    """手续费：按费率计算 + 最低手续费"""

    def test_fee_above_minimum(self, ctx):
        """成交金额足够时，手续费 = price * quantity * fee_rate（最低5元被超过）"""
        exec_ = OrderExecutor(context=ctx, slippage_rate=0.0, fee_rate=0.0003, min_fee=0.0)
        report = market_buy(exec_, "000001.SZ", 100, 10.0)

        # 手续费 = 10.0 * 100 * 0.0003 = 0.3；min_fee=0.0 时取 0.3
        assert report.fill_fee == 0.3
        assert report.trade.fee == 0.3

    def test_fee_at_minimum(self, ctx):
        """成交金额过小时，手续费 = min_fee（5元）"""
        exec_ = OrderExecutor(context=ctx, slippage_rate=0.0, fee_rate=0.0003)
        report = market_buy(exec_, "000001.SZ", 10, 10.0)

        # 10 * 10 * 0.0003 = 0.3 < 5 → 取 5
        assert report.fill_fee == 5.0


# ══════════════════════════════════════════════════════════════════════════════
# 7. TradeRecord & History
# ══════════════════════════════════════════════════════════════════════════════

class TestTradeRecord:
    """TradeRecord 序列化 & 历史记录"""

    def test_trade_record_to_dict(self):
        rec = TradeRecord(
            date="2026-01-10",
            symbol="000001.SZ",
            side=OrderSide.BUY,
            price=10.01,
            quantity=100,
            fee=0.3,
            slippage=0.001,
            order_type=OrderType.MARKET,
        )
        d = rec.to_dict()

        assert d["date"] == "2026-01-10"
        assert d["symbol"] == "000001.SZ"
        assert d["side"] == "buy"
        assert d["price"] == 10.01
        assert d["quantity"] == 100
        assert d["fee"] == 0.3
        assert d["slippage"] == 0.001
        assert d["order_type"] == "market"

    def test_clear_trade_history(self, exec_):
        market_buy(exec_, "000001.SZ", 10, 10.0)
        assert len(exec_.get_trade_history()) == 1

        exec_.clear_trade_history()
        assert len(exec_.get_trade_history()) == 0