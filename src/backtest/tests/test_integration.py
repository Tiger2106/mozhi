"""
墨枢 - BacktestEngine 集成测试
覆盖空信号 → 完整信号管线的所有关键路径。

测试场景：
  1. 空信号回测：所有信号为0 → 无交易，最终权益 = 初始资金
  2. 仅买入信号：正信号 → 完整开仓 + 持仓 + 费用验证
  3. 买入+卖出信号序列：多轮信号 → 完整交易周期验证资金守恒
  4. 带滑点的真实回测：SignalBridge + SlippageModel 同时启用
  5. 含费用的回测：FeeModel 启用验证费用正确扣减
"""
from __future__ import annotations

import math
from typing import List, Optional

import pytest

from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    Bar,
    OrderRequest,
    Strategy,
)
from backtest.backtest_context import BacktestContext
from backtest.capital_manager import CapitalManager
from backtest.fee_model import CNStockFeeModel, SimpleFeeModel
from backtest.order_executor import OrderExecutor, OrderSide, OrderType
from backtest.position_manager import CostMethod, PositionManager
from backtest.signal_bridge import SignalBridge, SignalBridgeConfig, SignalStrategy
from backtest.slippage_model import FixedSlippage, NoSlippage, RatioSlippage


# ═══════════════════════════════════════════════════════════════
# 测试数据构建工具
# ═══════════════════════════════════════════════════════════════


def make_bar(date: str, symbol: str = "000001.SZ", close: float = 10.0) -> Bar:
    """构建一根标准 Bar，close 兼作 vwap。"""
    return Bar(
        date=date,
        symbol=symbol,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=1_000_000,
        vwap=close,
    )


def make_bars(days: List[str], symbol: str = "000001.SZ", base_price: float = 10.0) -> List[Bar]:
    """批量生成 K 线，价格每天上涨 1%。"""
    bars = []
    price = base_price
    for d in days:
        bars.append(make_bar(d, symbol, close=price))
        price *= 1.01
    return bars


def make_flat_bars(days: List[str], symbol: str = "000001.SZ", price: float = 10.0) -> List[Bar]:
    """批量生成固定价格的 K 线（用于验证资金守恒，排除价格涨跌干扰）。"""
    return [make_bar(d, symbol, close=price) for d in days]


# ═══════════════════════════════════════════════════════════════
# 策略实现（测试用）
# ═══════════════════════════════════════════════════════════════


class ZeroSignalStrategy:
    """所有 Bar 均返回 None（无信号）。"""

    def on_start(self, context: BacktestContext) -> None:
        pass

    def on_bar(self, context: BacktestContext, bar: Bar) -> Optional[List]:
        return None

    def on_end(self, context: BacktestContext) -> None:
        pass


class BuyOnlyStrategy:
    """第2根 Bar 发买入信号（正信号）。"""

    def __init__(self, quantity: int = 100):
        self.quantity = quantity
        self._bar_count = 0

    def on_start(self, context: BacktestContext) -> None:
        self._bar_count = 0

    def on_bar(self, context: BacktestContext, bar: Bar):
        self._bar_count += 1
        if self._bar_count == 2:
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.BUY, quantity=self.quantity)]
        return None

    def on_end(self, context: BacktestContext) -> None:
        pass


class BuySellStrategy:
    """
    多轮买入+卖出信号：
      - 第2根 Bar  → 买入信号
      - 第4根 Bar  → 卖出信号
      - 第6根 Bar  → 买入信号（第2轮）
      - 第8根 Bar  → 卖出信号（第2轮平仓）
    """

    def __init__(self, quantity: int = 100):
        self.quantity = quantity
        self._counter = 0

    def on_start(self, context: BacktestContext) -> None:
        self._counter = 0

    def on_bar(self, context: BacktestContext, bar: Bar):
        self._counter += 1
        if self._counter in (2, 6):
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.BUY, quantity=self.quantity)]
        if self._counter in (4, 8):
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.SELL, quantity=self.quantity)]
        return None

    def on_end(self, context: BacktestContext) -> None:
        pass


class SignalDFStrategy(SignalStrategy):
    """
    使用 SignalBridge 加载 DataFrame 信号，
    并将正/负信号转发为 OrderRequest。
    """

    def __init__(self, signal_df, bridge_config: Optional[SignalBridgeConfig] = None):
        super().__init__(bridge_config=bridge_config)
        self._signal_df = signal_df

    def on_start(self, ctx) -> None:
        # Skip super().on_start() to avoid bridge.reset() wiping _signal_df
        self.bridge.reset()
        self.bridge.load_signals(self._signal_df)

    def on_bar(self, ctx, bar):
        return self.bridge.signal_to_orders(ctx, bar)


# ═══════════════════════════════════════════════════════════════
# 测试夹具
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def trading_days():
    """10 个交易日。"""
    return [f"2026-01-{d:02d}" for d in range(1, 11)]


@pytest.fixture
def initial_capital():
    return 1_000_000.0


# ═══════════════════════════════════════════════════════════════
# 场景 1：空信号回测
# ═══════════════════════════════════════════════════════════════


class TestEmptySignalBacktest:
    """所有信号为 0（或 None）→ 无交易，最终权益 = 初始资金。"""

    def test_no_trades_with_zero_signals(self, trading_days, initial_capital):
        """零信号策略：trades 为空，final_equity == initial_capital。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
        )
        bars = make_bars(trading_days)
        engine = BacktestEngine(config=cfg, strategy=ZeroSignalStrategy())
        result = engine.run(bars)

        assert result.total_trades == 0, f"期望 0 笔交易，实际 {result.total_trades}"
        assert result.metrics["final_equity"] == pytest.approx(initial_capital, rel=1e-4)

    def test_no_trades_no_signal_because_threshold(self, trading_days, initial_capital):
        """
        使用 SignalBridge 加载信号 DataFrame，但信号绝对值 < threshold → 无交易。
        """
        import pandas as pd

        df = pd.DataFrame({
            "date": trading_days,
            "symbol": "000001.SZ",
            "signal": [0.0] * len(trading_days),
        })

        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
        )
        flat_bars = make_flat_bars(trading_days, price=10.0)
        engine = BacktestEngine(config=cfg, strategy=SignalDFStrategy(df))
        result = engine.run(flat_bars)

        assert result.total_trades == 0
        assert result.metrics["final_equity"] == pytest.approx(initial_capital, rel=1e-4)


# ═══════════════════════════════════════════════════════════════
# 场景 2：仅买入信号 → 完整开仓 + 持仓 + 费用验证
# ═══════════════════════════════════════════════════════════════


class TestBuyOnlySignal:
    """正信号 → 完整开仓 + 持仓 + 费用验证。"""

    def test_buy_opens_position_and_deducts_fees(self, trading_days, initial_capital):
        """
        第2根 Bar 触发买入：
          - 持仓数量 = 100
          - 买入费用 > 0
          - 可用资金减少（含费用）
          - 权益曲线包含持仓市值
        """
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            fee_rate=0.0003,
            min_fee=5.0,
        )
        bars = make_bars(trading_days)
        engine = BacktestEngine(config=cfg, strategy=BuyOnlyStrategy(quantity=100))
        result = engine.run(bars)

        # ── 交易验证 ────────────────────────────────────
        assert result.total_trades == 1, f"期望 1 笔交易，实际 {result.total_trades}"

        trade = result.trades[0]
        assert trade["side"] == "buy"
        assert trade["quantity"] == 100
        assert trade["fee"] > 0, "买入应有手续费"

        # ── 持仓验证 ────────────────────────────────────
        ctx = engine.context
        assert ctx.positions.has_position("000001.SZ"), "应有持仓"
        pos = ctx.positions.get("000001.SZ")
        assert pos.quantity == 100

        # ── 费用验证 ────────────────────────────────────
        fee = trade["fee"]
        assert fee >= cfg.min_fee, f"手续费 {fee} 应 >= 最低手续费 {cfg.min_fee}"

        # ── 资金验证 ────────────────────────────────────
        expected_available = initial_capital - (trade["price"] * 100) - fee
        assert ctx.capital.available == pytest.approx(expected_available, abs=0.01)

        # ── 权益曲线验证 ────────────────────────────────
        equity_points = result.equity_curve
        assert len(equity_points) == len(trading_days), "每个 Bar 一个净值点"
        # 最后一天权益 = 可用资金 + 持仓市值
        final_eq = equity_points[-1]["total_equity"]
        last_price = bars[-1].close
        pos_mv = pos.quantity * last_price
        expected_eq = ctx.capital.available + ctx.capital.frozen + pos_mv
        assert final_eq == pytest.approx(expected_eq, abs=1.0)

    def test_buy_quantity_rounds_to_100(self, trading_days, initial_capital):
        """验证 SignalBridge 将下单数量取整为 100 的整数倍（A股规则）。"""
        import pandas as pd
        from backtest.signal_bridge import SignalBridgeConfig

        df = pd.DataFrame({
            "date": trading_days,
            "symbol": "000001.SZ",
            "signal": [0.0] + [1.0] + [0.0] * (len(trading_days) - 2),
        })
        bridge_cfg = SignalBridgeConfig(default_quantity=150)
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
        )
        bars = make_bars(trading_days)
        engine = BacktestEngine(
            config=cfg,
            strategy=SignalDFStrategy(df, bridge_config=bridge_cfg),
        )
        result = engine.run(bars)

        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade["quantity"] % 100 == 0, f"数量 {trade['quantity']} 应为 100 的整数倍"


# ═══════════════════════════════════════════════════════════════
# 场景 3：买入 + 卖出信号序列 → 完整交易周期验证资金守恒
# ═══════════════════════════════════════════════════════════════


class TestBuySellSequence:
    """多轮买入+卖出信号 → 完整交易周期验证资金守恒。"""

    def test_two_round_trip_capital_conservation(self, trading_days, initial_capital):
        """
        两轮完整买卖（固定价格，排除价格涨跌干扰）：
          - 4 笔交易：buy, sell, buy, sell
          - 初始资金 1_000_000，最终现金 = 初始资金 - 所有费用
          - 两轮完成后无持仓
        """
        flat_days = [f"2026-01-{d:02d}" for d in range(1, 11)]
        flat_bars = make_flat_bars(flat_days, price=10.0)

        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            fee_rate=0.0003,
            min_fee=5.0,
            slippage_rate=0.0,
        )
        engine = BacktestEngine(config=cfg, strategy=BuySellStrategy(quantity=100))
        result = engine.run(flat_bars)

        assert result.total_trades == 4, f"期望 4 笔交易，实际 {result.total_trades}"

        buy_trades = [t for t in result.trades if t["side"] == "buy"]
        sell_trades = [t for t in result.trades if t["side"] == "sell"]
        assert len(buy_trades) == 2
        assert len(sell_trades) == 2

        # 资金守恒：价格不变时最终现金 = 初始资金 - 所有费用
        total_fees = sum(t["fee"] for t in result.trades)
        expected_final_cash = initial_capital - total_fees
        final_cash = engine.context.capital.available + engine.context.capital.frozen
        assert final_cash == pytest.approx(expected_final_cash, abs=0.01)

        # 最终无持仓
        assert len(engine.context.positions.positions) == 0, "两轮完成后应无持仓"

    def test_final_equity_equals_initial_after_round_trips(self, trading_days, initial_capital):
        """
        两轮完整买卖后（固定价格，无持仓盈亏）：
          最终权益 = 初始资金 - 所有费用
        """
        flat_days = [f"2026-01-{d:02d}" for d in range(1, 11)]
        flat_bars = make_flat_bars(flat_days, price=10.0)

        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            fee_rate=0.0003,
            min_fee=5.0,
            slippage_rate=0.0,
        )
        engine = BacktestEngine(config=cfg, strategy=BuySellStrategy(quantity=100))
        result = engine.run(flat_bars)

        final_eq = result.equity_curve[-1]["total_equity"]
        total_fees = sum(t["fee"] for t in result.trades)
        expected_eq = initial_capital - total_fees

        assert final_eq == pytest.approx(expected_eq, abs=1.0)


# ═══════════════════════════════════════════════════════════════
# 场景 4：带滑点的真实回测 — SignalBridge + SlippageModel 同时启用
# ═══════════════════════════════════════════════════════════════


class TestSlippageWithSignalBridge:
    """SignalBridge + SlippageModel 同时启用时，滑点正确调整成交价。"""

    def test_ratio_slippage_increases_buy_cost_and_decreases_sell_revenue(
        self, trading_days, initial_capital
    ):
        """
        比例滑点（0.1%）：
          - 买入成交价 = bar.close * (1 + 0.001)
          - 卖出成交价 = bar.close * (1 - 0.001)
        """
        import pandas as pd

        df = pd.DataFrame({
            "date": trading_days,
            "symbol": "000001.SZ",
            "signal": [0.0] + [1.0] + [0.0] + [-1.0] + [0.0] * (len(trading_days) - 4),
        })

        slippage_rate = 0.001  # 0.1%
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            slippage_rate=slippage_rate,
            fee_rate=0.0,
            min_fee=0.0,
        )
        flat_bars = make_flat_bars(trading_days, price=10.0)
        engine = BacktestEngine(config=cfg, strategy=SignalDFStrategy(df))
        result = engine.run(flat_bars)

        buy_trade = next(t for t in result.trades if t["side"] == "buy")
        sell_trade = next(t for t in result.trades if t["side"] == "sell")

        buy_bar = flat_bars[1]
        sell_bar = flat_bars[3]

        expected_buy_fill = round(buy_bar.close * (1 + slippage_rate), 4)
        assert buy_trade["price"] == expected_buy_fill, (
            f"买入滑点错误：期望 {expected_buy_fill}，实际 {buy_trade['price']}"
        )

        expected_sell_fill = round(sell_bar.close * (1 - slippage_rate), 4)
        assert sell_trade["price"] == expected_sell_fill, (
            f"卖出滑点错误：期望 {expected_sell_fill}，实际 {sell_trade['price']}"
        )

    def test_slippage_rate_is_ratio_multiplicative(self, trading_days, initial_capital):
        """
        验证 slippage_rate 按比例（乘法）应用于成交价，而非加法。
        slippage_rate=0.02 → 2% 滑点（买入价 = close * 1.02）。
        """
        import pandas as pd

        df = pd.DataFrame({
            "date": trading_days,
            "symbol": "000001.SZ",
            "signal": [0.0] + [1.0] + [0.0] + [-1.0] + [0.0] * (len(trading_days) - 4),
        })
        slippage_rate = 0.02  # 2% 比例滑点
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            slippage_rate=slippage_rate,
            fee_rate=0.0,
            min_fee=0.0,
        )
        flat_bars = make_flat_bars(trading_days, price=10.0)
        engine = BacktestEngine(config=cfg, strategy=SignalDFStrategy(df))
        result = engine.run(flat_bars)
        buy_trade = next(t for t in result.trades if t["side"] == "buy")
        sell_trade = next(t for t in result.trades if t["side"] == "sell")

        buy_bar = flat_bars[1]
        sell_bar = flat_bars[3]
        assert buy_trade["price"] == pytest.approx(buy_bar.close * (1 + slippage_rate), abs=1e-4)
        assert sell_trade["price"] == pytest.approx(sell_bar.close * (1 - slippage_rate), abs=1e-4)

    def test_slippage_impacts_total_pnl(self, trading_days, initial_capital):
        """
        滑点会侵蚀盈利：验证有滑点时最终权益低于无滑点时。
        """
        import pandas as pd

        df = pd.DataFrame({
            "date": trading_days,
            "symbol": "000001.SZ",
            "signal": [0.0] + [1.0] + [0.0] + [-1.0] + [0.0] * (len(trading_days) - 4),
        })

        cfg_no_slip = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            slippage_rate=0.0,
            fee_rate=0.0,
            min_fee=0.0,
        )
        cfg_with_slip = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            slippage_rate=0.001,
            fee_rate=0.0,
            min_fee=0.0,
        )
        bars = make_bars(trading_days)

        engine_no_slip = BacktestEngine(config=cfg_no_slip, strategy=SignalDFStrategy(df))
        result_no_slip = engine_no_slip.run(bars)

        engine_with_slip = BacktestEngine(config=cfg_with_slip, strategy=SignalDFStrategy(df))
        result_with_slip = engine_with_slip.run(bars)

        assert result_with_slip.equity_curve[-1]["total_equity"] <= result_no_slip.equity_curve[-1]["total_equity"]


# ═══════════════════════════════════════════════════════════════
# 场景 5：含费用的回测 — FeeModel 启用验证费用正确扣减
# ═══════════════════════════════════════════════════════════════


class TestFeeModel:
    """FeeModel 启用时，验证费用正确扣减。"""

    def test_cn_stock_fee_buy_has_commission_and_transfer(self):
        """
        A股买入费用：佣金（含最低5元）+ 过户费，无印花税。
        """
        model = CNStockFeeModel()
        price = 10.0
        quantity = 100
        turnover = price * quantity  # 1000

        buy_fee = model.calc_buy_fee(price, quantity)
        expected_commission = max(round(turnover * 0.00025, 2), 5.0)  # 0.25 → 5.0
        expected_transfer = round(turnover * 0.00002, 2)  # 0.02
        expected_buy_fee = expected_commission + expected_transfer

        assert buy_fee == expected_buy_fee

    def test_cn_stock_fee_sell_has_all_three_components(self):
        """
        A股卖出手续费：佣金 + 过户费 + 印花税（千分之1）。
        """
        model = CNStockFeeModel()
        price = 10.0
        quantity = 100
        turnover = price * quantity  # 1000

        sell_fee = model.calc_sell_fee(price, quantity)
        expected_commission = max(round(turnover * 0.00025, 2), 5.0)  # 0.25 → 5.0
        expected_stamp = round(turnover * 0.001, 2)  # 1.0
        expected_transfer = round(turnover * 0.00002, 2)  # 0.02
        expected_sell_fee = expected_commission + expected_stamp + expected_transfer

        assert sell_fee == expected_sell_fee

    def test_full_backtest_fee_deduction(self, trading_days, initial_capital):
        """
        完整回测验证费用扣除（使用与 executor 一致的 SimpleFeeModel）：
          - 总费用 = 所有买入费用 + 所有卖出手续费
          - 最终权益 = 初始资金 - 所有费用（所有交易完成后无持仓）
        """
        import pandas as pd

        df = pd.DataFrame({
            "date": trading_days,
            "symbol": "000001.SZ",
            "signal": [0.0] + [1.0] + [0.0] + [-1.0] + [0.0] * (len(trading_days) - 4),
        })

        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            fee_rate=0.0003,
            min_fee=5.0,
            slippage_rate=0.0,
        )
        flat_bars = make_flat_bars(trading_days, price=10.0)
        engine = BacktestEngine(config=cfg, strategy=SignalDFStrategy(df))
        result = engine.run(flat_bars)

        buy_trade = next(t for t in result.trades if t["side"] == "buy")
        sell_trade = next(t for t in result.trades if t["side"] == "sell")

        # 费用验证（使用与 executor 一致的 SimpleFeeModel）
        model = SimpleFeeModel(fee_rate=0.0003, min_fee=5.0)
        expected_buy_fee = model.calc_buy_fee(buy_trade["price"], buy_trade["quantity"])
        assert buy_trade["fee"] == pytest.approx(expected_buy_fee, abs=0.01)

        expected_sell_fee = model.calc_sell_fee(sell_trade["price"], sell_trade["quantity"])
        assert sell_trade["fee"] == pytest.approx(expected_sell_fee, abs=0.01)

        # 资金守恒
        total_fees = sum(t["fee"] for t in result.trades)
        expected_final_eq = initial_capital - total_fees
        actual_final_eq = result.equity_curve[-1]["total_equity"]
        assert actual_final_eq == pytest.approx(expected_final_eq, abs=1.0)


# ═══════════════════════════════════════════════════════════════
# 辅助验证：EquityCurve / Performance 基础验证
# ═══════════════════════════════════════════════════════════════


class TestEquityCurveBasics:
    """净值曲线基础验证。"""

    def test_equity_curve_has_one_point_per_bar(self, trading_days, initial_capital):
        """每个 Bar 应对应一个净值点。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
        )
        bars = make_bars(trading_days)
        engine = BacktestEngine(config=cfg, strategy=ZeroSignalStrategy())
        result = engine.run(bars)

        assert len(result.equity_curve) == len(trading_days)
        assert all("date" in pt and "total_equity" in pt for pt in result.equity_curve)

    def test_equity_curve_starts_at_initial_capital(self, trading_days, initial_capital):
        """首日净值应等于初始资金（无交易时）。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
        )
        bars = make_bars(trading_days)
        engine = BacktestEngine(config=cfg, strategy=ZeroSignalStrategy())
        result = engine.run(bars)

        first = result.equity_curve[0]["total_equity"]
        assert first == pytest.approx(initial_capital, rel=1e-4)

    def test_metrics_keys_are_present(self, trading_days, initial_capital):
        """所有关键绩效指标均存在。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
        )
        bars = make_bars(trading_days)
        engine = BacktestEngine(config=cfg, strategy=ZeroSignalStrategy())
        result = engine.run(bars)

        required_keys = [
            "total_return_pct", "annual_return_pct",
            "max_drawdown", "max_drawdown_pct",
            "sharpe_ratio", "volatility",
            "win_rate_pct", "total_trades", "final_equity",
        ]
        for key in required_keys:
            assert key in result.metrics, f"缺少指标: {key}"


# ═══════════════════════════════════════════════════════════════
# 边界条件测试
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界条件测试。"""

    def test_single_bar_backtest(self, initial_capital):
        """仅 1 根 Bar 的回测。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-01",
            initial_capital=initial_capital,
        )
        bars = [make_bar("2026-01-01")]
        engine = BacktestEngine(config=cfg, strategy=ZeroSignalStrategy())
        result = engine.run(bars)

        assert result.total_bars == 1
        assert result.total_trades == 0
        assert result.equity_curve[0]["total_equity"] == pytest.approx(initial_capital, rel=1e-4)

    def test_engine_reset_allows_reuse(self, trading_days, initial_capital):
        """重置引擎后可以再次 run，数据不残留。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
        )
        bars = make_bars(trading_days)
        engine = BacktestEngine(config=cfg, strategy=BuyOnlyStrategy(quantity=100))

        result1 = engine.run(bars)
        assert result1.total_trades == 1

        engine.reset()

        result2 = engine.run(bars)
        assert result2.total_trades == 1  # 与第一次相同，不会累积
        assert len(result2.equity_curve) == len(result1.equity_curve)

    def test_backtest_without_fee_and_slippage(self, trading_days, initial_capital):
        """fee_rate=0, slippage_rate=0 时无任何成本损耗。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-10",
            initial_capital=initial_capital,
            fee_rate=0.0,
            slippage_rate=0.0,
            min_fee=0.0,
        )
        flat_days = [f"2026-01-{d:02d}" for d in range(1, 11)]
        flat_bars = make_flat_bars(flat_days, price=10.0)
        engine = BacktestEngine(config=cfg, strategy=BuySellStrategy(quantity=100))
        result = engine.run(flat_bars)

        total_fees = sum(t["fee"] for t in result.trades)
        assert total_fees == 0.0
        # 两轮买卖后无持仓，最终权益 = 初始资金
        final_eq = result.equity_curve[-1]["total_equity"]
        assert final_eq == pytest.approx(initial_capital, rel=1e-4)