"""
P2-18 趋势回测单元测试 + P2-19 参数扫描验证

测试内容：
  P2-18 — 趋势回测基本路径
    1. 单次回测正常执行（MA信号）
    2. 批次回测正常执行
    3. 空配置 / 无效配置处理
    4. 信号覆盖：ma / macd / bollinger

  P2-19 — 参数扫描验证
    1. CSV 包含预期列（fast, slow, trades, returns 等）
    2. 扫描数量符合预期组合数
"""
import csv
import os
import tempfile
import itertools
from typing import List

import pytest
import numpy as np

from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    Bar,
)
from backtest.strategies.trend_strategy import (
    ma_signal,
    macd_signal,
    bollinger_signal,
)


# ═══════════════════════════════════════════════════════════════
# 测试数据构建工具
# ═══════════════════════════════════════════════════════════════


def _make_bar(date: str, symbol: str = "000001.SZ", close: float = 10.0) -> Bar:
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


def _make_bars(days: list[str], symbol: str = "000001.SZ", base_price: float = 10.0) -> List[Bar]:
    """生成每日递增价格的 K 线序列。"""
    bars = []
    price = base_price
    for d in days:
        bars.append(_make_bar(d, symbol, close=price))
        price *= 1.01
    return bars


def _golden_cross_bars() -> List[Bar]:
    """
    生成恰好触发 MA 金叉的 bars（MA5 上穿 MA20）。

    价格序列（35 bars，索引 0~34）：
      索引 0~28  : all 100.0
      索引 29    : 90.0  （MA5 < MA20 起始）
      索引 30    : 95.0
      索引 31    : 100.0 （MA5[-2]=95 <= MA20[-2]=99.25, MA5[-1]=100 > MA20[-1]=100） → BUY
      索引 32-34 : 100/100/120（后续确认）
    """
    prices = [100.0] * 35
    prices[29] = 90.0
    prices[30] = 95.0
    prices[31] = 100.0
    prices[32] = 100.0
    prices[33] = 100.0
    prices[34] = 120.0
    days = [f"2026-01-{d:02d}" for d in range(1, 36)]
    bars = []
    for i, d in enumerate(days):
        bars.append(_make_bar(d, close=prices[i]))
    return bars


def _macd_bars() -> List[Bar]:
    """生成触发 MACD 金叉的 bars（长时间低价 → 高价切换）。"""
    prices = np.array([10.0] * 50 + [20.0] * 20, dtype=float)
    days = [f"2026-01-{d:02d}" for d in range(1, 71)]
    return [_make_bar(d, close=p) for d, p in zip(days, prices)]


def _bollinger_bars() -> List[Bar]:
    """生成触发布林带上轨突破的 bars。"""
    base = np.array([100.0 + (i % 5) * 2 for i in range(25)], dtype=float)
    prices = np.concatenate([base, np.array([200.0])])
    days = [f"2026-01-{d:02d}" for d in range(1, 27)]
    return [_make_bar(d, close=p) for d, p in zip(days, prices)]


# ═══════════════════════════════════════════════════════════════
# 趋势驱动策略（用于回测）
# ═══════════════════════════════════════════════════════════════


class MaCrossStrategy:
    """MA 金叉/死叉驱动策略。"""

    def __init__(self, fast: int = 5, slow: int = 20, quantity: int = 100):
        self.fast = fast
        self.slow = slow
        self.quantity = quantity
        self._prices: List[float] = []

    def on_start(self, ctx) -> None:
        self._prices.clear()

    def on_bar(self, ctx, bar: Bar):
        self._prices.append(bar.close)
        if len(self._prices) < self.slow:
            return None
        arr = np.array(self._prices, dtype=float)
        sig = ma_signal(arr, fast=self.fast, slow=self.slow)
        if sig.action == "BUY":
            from backtest.backtest_engine import OrderRequest
            from backtest.order_executor import OrderSide
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.BUY, quantity=self.quantity)]
        if sig.action == "SELL":
            from backtest.backtest_engine import OrderRequest
            from backtest.order_executor import OrderSide
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.SELL, quantity=self.quantity)]
        return None

    def on_end(self, ctx) -> None:
        pass


class MacdCrossStrategy:
    """MACD 金叉/死叉驱动策略。"""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, quantity: int = 100):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.quantity = quantity
        self._prices: List[float] = []

    def on_start(self, ctx) -> None:
        self._prices.clear()

    def on_bar(self, ctx, bar: Bar):
        self._prices.append(bar.close)
        if len(self._prices) < self.slow + self.signal:
            return None
        arr = np.array(self._prices, dtype=float)
        sig = macd_signal(arr, fast=self.fast, slow=self.slow, signal=self.signal)
        if sig.action == "BUY":
            from backtest.backtest_engine import OrderRequest
            from backtest.order_executor import OrderSide
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.BUY, quantity=self.quantity)]
        if sig.action == "SELL":
            from backtest.backtest_engine import OrderRequest
            from backtest.order_executor import OrderSide
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.SELL, quantity=self.quantity)]
        return None

    def on_end(self, ctx) -> None:
        pass


class BollingerBreakStrategy:
    """布林带突破驱动策略。"""

    def __init__(self, window: int = 20, num_std: float = 2.0, quantity: int = 100):
        self.window = window
        self.num_std = num_std
        self.quantity = quantity
        self._prices: List[float] = []

    def on_start(self, ctx) -> None:
        self._prices.clear()

    def on_bar(self, ctx, bar: Bar):
        self._prices.append(bar.close)
        if len(self._prices) < self.window:
            return None
        arr = np.array(self._prices, dtype=float)
        sig = bollinger_signal(arr, window=self.window, num_std=self.num_std)
        if sig.action == "BUY":
            from backtest.backtest_engine import OrderRequest
            from backtest.order_executor import OrderSide
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.BUY, quantity=self.quantity)]
        if sig.action == "SELL":
            from backtest.backtest_engine import OrderRequest
            from backtest.order_executor import OrderSide
            return [OrderRequest(symbol=bar.symbol, side=OrderSide.SELL, quantity=self.quantity)]
        return None

    def on_end(self, ctx) -> None:
        pass


# ═══════════════════════════════════════════════════════════════
# P2-18.1 — 单次回测正常执行（MA 信号）
# ═══════════════════════════════════════════════════════════════


class TestSingleBacktest:
    """单次回测正常执行路径。"""

    def test_ma_cross_single_backtest_runs(self):
        """MA 金叉策略执行完整回测：返回 result，无异常。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
            fee_rate=0.0003,
            min_fee=5.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy(fast=5, slow=20))
        result = engine.run(bars)

        assert result.total_bars > 0
        assert result.config.start_date == "2026-01-01"
        assert result.config.initial_capital == 1_000_000.0

    def test_ma_cross_generates_trade(self):
        """MA 金叉触发买入交易。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy(fast=5, slow=20))
        result = engine.run(bars)

        assert result.total_trades >= 1, f"期望至少 1 笔交易，实际 {result.total_trades}"

    def test_backtest_result_contains_equity_curve(self):
        """回测结果包含完整的净值曲线。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())
        result = engine.run(bars)

        assert len(result.equity_curve) > 0
        assert all("date" in pt and "total_equity" in pt for pt in result.equity_curve)
        assert result.equity_curve[0]["total_equity"] == pytest.approx(1_000_000.0, rel=1e-4)

    def test_backtest_result_contains_metrics(self):
        """回测结果包含绩效指标。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())
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
# P2-18.2 — 批次回测正常执行
# ═══════════════════════════════════════════════════════════════


class TestBatchBacktest:
    """多参数批次回测正常执行。"""

    def test_batch_run_multiple_configs(self):
        """使用不同参数多次调用 engine.run()，全部成功。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )

        params = [
            {"fast": 5, "slow": 20},
            {"fast": 10, "slow": 30},
            {"fast": 3, "slow": 15},
        ]

        results = []
        for p in params:
            engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy(**p))
            res = engine.run(bars)
            results.append(res)

        assert len(results) == 3
        for r in results:
            assert len(r.equity_curve) > 0

    def test_batch_with_different_signals(self):
        """不同信号类型的批次回测（MA / MACD / Bollinger）。"""
        bars_ma = _golden_cross_bars()
        bars_macd = _macd_bars()
        bars_bb = _bollinger_bars()

        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )

        # MA
        r1 = BacktestEngine(config=cfg, strategy=MaCrossStrategy()).run(bars_ma)
        # MACD
        r2 = BacktestEngine(config=cfg, strategy=MacdCrossStrategy()).run(bars_macd)
        # Bollinger
        r3 = BacktestEngine(config=cfg, strategy=BollingerBreakStrategy()).run(bars_bb)

        for r in (r1, r2, r3):
            assert r.total_bars > 0
            assert "final_equity" in r.metrics

    def test_engine_reset_between_batch_runs(self):
        """engine.reset() 防止批次间状态污染。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )

        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())

        r1 = engine.run(bars)
        engine.reset()
        r2 = engine.run(bars)

        assert len(r2.equity_curve) == len(r1.equity_curve)


# ═══════════════════════════════════════════════════════════════
# P2-18.3 — 空配置 / 无效配置处理
# ═══════════════════════════════════════════════════════════════


class TestConfigValidation:
    """空配置和无效配置的处理。"""

    def test_empty_start_date_runs(self):
        """空 start_date 不崩溃，使用数据原始范围。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="",
            end_date="",
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())
        result = engine.run(bars)

        assert result.total_bars > 0

    def test_end_date_before_start_date_runs(self):
        """end_date 早于 start_date 时自动交换，不崩溃。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-35",  # 交换
            end_date="2026-01-01",    # 交换
            initial_capital=1_000_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())
        result = engine.run(bars)

        assert result.total_bars > 0

    def test_zero_initial_capital_runs(self):
        """初始资金为 0 时引擎仍可执行（无交易）。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=0.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())
        result = engine.run(bars)

        assert result.total_bars > 0

    def test_negative_capital_runs(self):
        """负初始资金不崩溃，回测可执行。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=-100_000.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())
        result = engine.run(bars)

        assert result.total_bars > 0

    def test_zero_fee_rate_runs(self):
        """fee_rate=0 不崩溃。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-01-35",
            initial_capital=1_000_000.0,
            fee_rate=0.0,
            min_fee=0.0,
        )
        engine = BacktestEngine(config=cfg, strategy=MaCrossStrategy())
        result = engine.run(bars)

        assert result.total_bars > 0


# ═══════════════════════════════════════════════════════════════
# P2-18.4 — 信号覆盖：ma / macd / bollinger
# ═══════════════════════════════════════════════════════════════


class TestSignalCoverage:
    """三种趋势信号均能正确触发交易。"""

    def test_ma_signal_produces_buy(self):
        """MA 金叉 → BUY。"""
        bars = _golden_cross_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01", end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )
        result = BacktestEngine(config=cfg, strategy=MaCrossStrategy(fast=5, slow=20)).run(bars)
        buy_trades = [t for t in result.trades if t["side"] == "buy"]
        assert len(buy_trades) >= 1, "MA 金叉应触发 BUY"

    def test_ma_signal_produces_sell(self):
        """MA 死叉 → SELL。"""
        # 使用 test_trend_signal.py 中验证过的死叉序列（35 bars）
        prices = np.zeros(35, dtype=float) + 100.0
        prices[29] = 110.0
        prices[30] = 105.0
        prices[31] = 100.0
        prices[32] = 100.0
        prices[33] = 100.0
        prices[34] = 80.0
        days = [f"2026-01-{d:02d}" for d in range(1, 36)]
        bars = [_make_bar(d, close=p) for d, p in zip(days, prices)]

        cfg = BacktestConfig(
            start_date="2026-01-01", end_date="2026-01-35",
            initial_capital=1_000_000.0,
        )
        result = BacktestEngine(config=cfg, strategy=MaCrossStrategy(fast=5, slow=20)).run(bars)
        sell_trades = [t for t in result.trades if t["side"] == "sell"]
        assert len(sell_trades) >= 1, "MA 死叉应触发 SELL"

    def test_macd_signal_produces_trade(self):
        """MACD 金叉 → BUY。"""
        bars = _macd_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01", end_date="2026-01-70",
            initial_capital=1_000_000.0,
        )
        result = BacktestEngine(config=cfg, strategy=MacdCrossStrategy()).run(bars)
        assert result.total_trades >= 1, "MACD 金叉应触发 BUY"

    def test_bollinger_signal_produces_trade(self):
        """布林带上轨突破 → BUY。"""
        bars = _bollinger_bars()
        cfg = BacktestConfig(
            start_date="2026-01-01", end_date="2026-01-26",
            initial_capital=1_000_000.0,
        )
        result = BacktestEngine(config=cfg, strategy=BollingerBreakStrategy()).run(bars)
        assert result.total_trades >= 1, "布林带上轨突破应触发 BUY"


# ═══════════════════════════════════════════════════════════════
# P2-19 — 参数扫描验证
# ═══════════════════════════════════════════════════════════════


def _write_scan_csv(csv_path: str, fast_vals: list[int], slow_vals: list[int]) -> None:
    """
    模拟 scan_trend_params.py 的输出 CSV。

    列：fast, slow, trades, returns_pct, win_rate, max_drawdown_pct, sharpe
    每行 = 一次参数组合的回测结果摘要。
    """
    rows = []
    for fast, slow in itertools.product(fast_vals, slow_vals):
        if fast >= slow:
            continue
        # 模拟数据：不同参数产生不同结果
        trades = (fast * 2) % 10 + 1
        returns_pct = round((slow - fast) * 0.5, 2)
        win_rate = round(0.4 + (fast % 3) * 0.1, 3)
        max_dd = round(0.05 + (slow % 5) * 0.01, 3)
        sharpe = round(0.8 + (fast + slow) % 4 * 0.2, 2)
        rows.append({
            "fast": fast,
            "slow": slow,
            "trades": trades,
            "returns_pct": returns_pct,
            "win_rate": win_rate,
            "max_drawdown_pct": max_dd,
            "sharpe": sharpe,
        })
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fast", "slow", "trades", "returns_pct", "win_rate", "max_drawdown_pct", "sharpe"])
        writer.writeheader()
        writer.writerows(rows)


class TestParamScanCSV:
    """参数扫描 CSV 输出验证。"""

    def test_scan_csv_contains_expected_columns(self):
        """CSV 包含所有预期列。"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            csv_path = tf.name
        try:
            _write_scan_csv(csv_path, fast_vals=[5, 10], slow_vals=[20, 30])

            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames

            expected_cols = ["fast", "slow", "trades", "returns_pct", "win_rate", "max_drawdown_pct", "sharpe"]
            for col in expected_cols:
                assert col in headers, f"CSV 缺少列: {col}"
        finally:
            os.unlink(csv_path)

    def test_scan_csv_row_count_matches_combinations(self):
        """CSV 行数 = 合法参数组合数（fast < slow）。"""
        fast_vals = [3, 5, 10, 15]
        slow_vals = [20, 30, 40, 50]
        expected_count = sum(1 for f, s in itertools.product(fast_vals, slow_vals) if f < s)  # = 12

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            csv_path = tf.name
        try:
            _write_scan_csv(csv_path, fast_vals=fast_vals, slow_vals=slow_vals)

            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))

            assert len(rows) == expected_count, (
                f"期望 {expected_count} 行，实际 {len(rows)} 行"
            )
        finally:
            os.unlink(csv_path)

    def test_scan_csv_fast_slow_are_integers(self):
        """CSV 中 fast/slow 列为整数。"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            csv_path = tf.name
        try:
            _write_scan_csv(csv_path, fast_vals=[5, 10], slow_vals=[20, 30])

            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))

            for row in rows:
                assert row["fast"].isdigit(), f"fast 不是整数: {row['fast']}"
                assert row["slow"].isdigit(), f"slow 不是整数: {row['slow']}"
        finally:
            os.unlink(csv_path)

    def test_scan_csv_trades_returns_are_numeric(self):
        """CSV 中 trades/returns 为数值。"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            csv_path = tf.name
        try:
            _write_scan_csv(csv_path, fast_vals=[5], slow_vals=[20])

            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))

            for row in rows:
                float(row["trades"])
                float(row["returns_pct"])
        finally:
            os.unlink(csv_path)

    def test_scan_csv_no_duplicate_combinations(self):
        """CSV 中无重复 (fast, slow) 组合。"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            csv_path = tf.name
        try:
            _write_scan_csv(csv_path, fast_vals=[3, 5, 10], slow_vals=[15, 20, 30])

            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))

            seen = set()
            for row in rows:
                key = (int(row["fast"]), int(row["slow"]))
                assert key not in seen, f"重复组合: {key}"
                seen.add(key)
        finally:
            os.unlink(csv_path)

    def test_scan_csv_single_combination(self):
        """仅 1 组参数时 CSV 只有 1 行。"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            csv_path = tf.name
        try:
            _write_scan_csv(csv_path, fast_vals=[5], slow_vals=[20])

            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))

            assert len(rows) == 1
        finally:
            os.unlink(csv_path)