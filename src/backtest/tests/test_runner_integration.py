"""
test_runner_integration.py — Phase 4 Runner 集成测试

测试目标:
  I1: MethodBacktestRunner 模式 A（无状态方法: MA/MACD/Bollinger/RSI/KDJ/Bias）
  I2: MethodBacktestRunner 模式 B（有状态方法: Grid/Reversal）
  I3: MethodBacktestRunner.run_batch() 多时间框架
  I5: PortfolioManager 信号→订单
  I6: KnowledgeBridge 集成管道（harvest → knowledge_entries）
  I7: 错误处理

验收标准:
  - 新旧信号对比偏差 ≤ 0.1%（模式 A）
  - 模式 B 信号值域 { -1, 0, 1 } 正确
  - PortfolioManager 资金/持仓一致
  - KnowledgeBridge 条目写入成功

作者: 墨衡
创建时间: 2026-05-17
"""

import sys
import os
import json
import unittest
import shutil
import tempfile

import pandas as pd
import numpy as np

# ─── 路径设置 ────────────────────────────────────────────────
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(TEST_DIR, "..", "..")
sys.path.insert(0, SRC_DIR)

# ─── 模块导入 ────────────────────────────────────────────────
from backtest.context import StrategyContext
from backtest.runners.method_backtest_runner import MethodBacktestRunner

from backtest.portfolio.portfolio_manager import (
    PortfolioManager, Order, OrderSide, Signal, Position,
    FixedRatioSizer, PyramidSizer, TrendScoreSizer, RiskManager,
)
from backtest.methods.base import MethodResult
from backtest.engine.knowledge_bridge import KnowledgeBridge, KnowledgeEntry

# 新旧对比工具（methods 版本 v2.0, compute_deviation 返回 float）
from backtest.methods.comparison_test_helper import (
    df_to_bars, df_to_dicts,
)

# 旧系统策略函数
from backtest.strategies.trend_strategy import (
    generate_ma_cross_signals,
    generate_macd_signals,
    generate_bollinger_signals,
)
from backtest.strategies.reversal_strategy import (
    generate_rsi_signals,
    generate_kdj_signals,
    generate_bias_signals,
    voted_reversal_signal,
)


# ─── 常量 ────────────────────────────────────────────────────

DEVIATION_THRESHOLD = 0.001  # 0.1%（I1 验收标准）

_RNG_SEED = 42
_N_BARS = 120
_DATE_RANGE = ("2025-01-01", "2025-05-01")


# ═══════════════════════════════════════════════════════════════
# 辅助工具
# ═══════════════════════════════════════════════════════════════


def make_test_df(n: int = _N_BARS) -> pd.DataFrame:
    """生成可重现的测试 OHLCV DataFrame。"""
    np.random.seed(_RNG_SEED)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    volume = np.random.randint(1000, 10000, n)
    return pd.DataFrame({
        "close": close, "high": high, "low": low, "volume": volume,
    }, index=pd.DatetimeIndex(dates, name="datetime"))


def make_old_bars(n: int = _N_BARS) -> list:
    """生成旧系统兼容 bar 对象列表（含 symbol 属性）。"""
    np.random.seed(_RNG_SEED)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    volume = np.random.randint(1000, 10000, n)
    from types import SimpleNamespace
    return [
        SimpleNamespace(
            datetime=dates[i],
            date=dates[i].strftime("%Y-%m-%d"),
            symbol="TEST",
            open=float((high[i] + low[i]) / 2),
            high=float(high[i]),
            low=float(low[i]),
            close=float(close[i]),
            volume=int(volume[i]),
        )
        for i in range(n)
    ]


def compute_float_deviation(old_signal_list: list, new_signal_series: pd.Series) -> float:
    """计算新旧信号平均绝对偏差。"""
    old = [s.get("signal", 0) if isinstance(s, dict) else 0 for s in old_signal_list]
    n = min(len(old), len(new_signal_series))
    if n == 0:
        return 0.0
    old_arr = np.array(old[:n], dtype=float)
    new_arr = new_signal_series.iloc[:n].values.astype(float)
    return float(np.abs(old_arr - new_arr).mean())


def make_mock_context(config: dict = None, symbol: str = "TEST") -> StrategyContext:
    """创建测试用 StrategyContext。"""
    return StrategyContext(
        symbol=symbol,
        config=config or {},
        date_range=_DATE_RANGE,
    )


# ═══════════════════════════════════════════════════════════════
# I1: 模式 A — 无状态方法对比验证
# ═══════════════════════════════════════════════════════════════


class TestRunnerModeA_MaCross_I1(unittest.TestCase):
    """I1-a: MaCrossMethod"""

    def test_runner_ma_cross(self):
        df = make_test_df()
        old_bars = make_old_bars()
        ctx = make_mock_context({"ma_fast": 5, "ma_slow": 20})

        # 新系统: MethodBacktestRunner
        runner = MethodBacktestRunner("ma_cross", ctx)
        result = runner.run(df)

        # 旧系统
        old_signals = generate_ma_cross_signals(old_bars, ma_fast=5, ma_slow=20)

        dev = compute_float_deviation(old_signals, result.signals["signal"])
        self.assertLess(
            dev, DEVIATION_THRESHOLD,
            f"MaCross 偏差 {dev:.6f} 超过 {DEVIATION_THRESHOLD}"
        )

        self.assertEqual(result.method_name, "ma_cross")
        self.assertEqual(result.n_bars, _N_BARS)
        self.assertGreater(result.duration_ms, 0)

        print(f"  [I1-a] MaCrossMethod OK (dev={dev:.6f}, {result.duration_ms:.1f}ms)")


class TestRunnerModeA_MACD_I1(unittest.TestCase):
    """I1-b: MACDMethod"""

    def test_runner_macd(self):
        df = make_test_df()
        old_bars = make_old_bars()
        ctx = make_mock_context({"macd_fast": 12, "macd_slow": 26, "macd_signal": 9})

        runner = MethodBacktestRunner("macd", ctx)
        result = runner.run(df)

        old_signals = generate_macd_signals(old_bars, fast_period=12, slow_period=26, signal_period=9)

        dev = compute_float_deviation(old_signals, result.signals["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"MACD 偏差 {dev:.6f} 超过 {DEVIATION_THRESHOLD}")
        print(f"  [I1-b] MACDMethod OK (dev={dev:.6f}, {result.duration_ms:.1f}ms)")


class TestRunnerModeA_Bollinger_I1(unittest.TestCase):
    """I1-c: BollingerMethod"""

    def test_runner_bollinger(self):
        df = make_test_df()
        old_bars = make_old_bars()
        ctx = make_mock_context({"bollinger_period": 20, "bollinger_std": 2.0})

        runner = MethodBacktestRunner("bollinger", ctx)
        result = runner.run(df)

        old_signals = generate_bollinger_signals(old_bars, period=20, std_dev=2.0)

        dev = compute_float_deviation(old_signals, result.signals["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"Bollinger 偏差 {dev:.6f} 超过 {DEVIATION_THRESHOLD}")
        print(f"  [I1-c] BollingerMethod OK (dev={dev:.6f}, {result.duration_ms:.1f}ms)")


class TestRunnerModeA_RSI_I1(unittest.TestCase):
    """I1-d: RSIMethod"""

    def test_runner_rsi(self):
        df = make_test_df()
        old_bars = make_old_bars()
        ctx = make_mock_context({"rsi_period": 14})

        runner = MethodBacktestRunner("rsi", ctx)
        result = runner.run(df)

        old_signals = generate_rsi_signals(old_bars, period=14)

        dev = compute_float_deviation(old_signals, result.signals["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"RSI 偏差 {dev:.6f} 超过 {DEVIATION_THRESHOLD}")
        print(f"  [I1-d] RSIMethod OK (dev={dev:.6f}, {result.duration_ms:.1f}ms)")


class TestRunnerModeA_KDJ_I1(unittest.TestCase):
    """I1-e: KDJMethod"""

    def test_runner_kdj(self):
        df = make_test_df()
        old_bars = make_old_bars()
        ctx = make_mock_context({"kdj_n": 9, "kdj_k_buy": 20.0, "kdj_k_sell": 80.0})

        runner = MethodBacktestRunner("kdj", ctx)
        result = runner.run(df)

        old_signals = generate_kdj_signals(old_bars, period=9)

        dev = compute_float_deviation(old_signals, result.signals["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"KDJ 偏差 {dev:.6f} 超过 {DEVIATION_THRESHOLD}")
        print(f"  [I1-e] KDJMethod OK (dev={dev:.6f}, {result.duration_ms:.1f}ms)")


class TestRunnerModeA_Bias_I1(unittest.TestCase):
    """I1-f: BiasMethod"""

    def test_runner_bias(self):
        df = make_test_df()
        old_bars = make_old_bars()
        ctx = make_mock_context({"bias_period": 20})

        runner = MethodBacktestRunner("bias", ctx)
        result = runner.run(df)

        old_signals = generate_bias_signals(old_bars, ma_period=20)

        dev = compute_float_deviation(old_signals, result.signals["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"Bias 偏差 {dev:.6f} 超过 {DEVIATION_THRESHOLD}")
        print(f"  [I1-f] BiasMethod OK (dev={dev:.6f}, {result.duration_ms:.1f}ms)")


# ═══════════════════════════════════════════════════════════════
# I2: 模式 B — 有状态方法验证
# ═══════════════════════════════════════════════════════════════


class TestRunnerModeB_Grid_I2(unittest.TestCase):
    """I2-a: GridMethod (requires_state=True)"""

    def test_runner_grid_mode_b(self):
        df = make_test_df()
        # 使用较窄网格确保有触发信号
        close_range = (df["close"].min(), df["close"].max())
        mid = (close_range[0] + close_range[1]) / 2
        ctx = make_mock_context({
            "grid_lower": close_range[0],
            "grid_upper": close_range[1],
            "grid_n_levels": 8,
        }, symbol="TEST")

        runner = MethodBacktestRunner("grid", ctx)
        result = runner.run(df)

        # 验证信号值域
        self.assertIn("signal", result.signals.columns)
        self.assertEqual(len(result.signals), _N_BARS)

        valid_signals = result.signals["signal"].isin({-1, 0, 1}).all()
        self.assertTrue(valid_signals, "GridMethod 信号值域应为 -1/0/1")

        print(f"  [I2-a] GridMethod OK (bars={result.n_bars}, "
              f"duration={result.duration_ms:.1f}ms)")


class TestRunnerModeB_Reversal_I2(unittest.TestCase):
    """I2-b: ReversalMethod (requires_state=True)"""

    def test_runner_reversal_mode_b(self):
        df = make_test_df()
        ctx = make_mock_context({
            "rsi_period": 14, "kdj_n": 9, "cooldown_bars": 5,
        }, symbol="TEST")

        runner = MethodBacktestRunner("reversal", ctx)
        result = runner.run(df)

        self.assertIn("signal", result.signals.columns)
        self.assertEqual(len(result.signals), _N_BARS)

        valid_signals = result.signals["signal"].isin({-1, 0, 1}).all()
        self.assertTrue(valid_signals, "ReversalMethod 信号值域应为 -1/0/1")

        non_zero = (result.signals["signal"] != 0).sum()
        self.assertGreater(non_zero, 0, "ReversalMethod 应产生非零信号")

        print(f"  [I2-b] ReversalMethod OK (bars={result.n_bars}, signals={non_zero}, "
              f"duration={result.duration_ms:.1f}ms)")


# ═══════════════════════════════════════════════════════════════
# I3: run_batch 多时间框架
# ═══════════════════════════════════════════════════════════════


class TestRunnerBatch_I3(unittest.TestCase):
    """I3: run_batch 多时间框架"""

    def test_run_batch(self):
        df_daily = make_test_df(60)
        df_weekly = make_test_df(20)

        ctx = make_mock_context({"ma_fast": 5, "ma_slow": 20})
        runner = MethodBacktestRunner("ma_cross", ctx)

        results = runner.run_batch({"daily": df_daily, "weekly": df_weekly})

        self.assertIn("daily", results)
        self.assertIn("weekly", results)
        self.assertEqual(results["daily"].n_bars, 60)
        self.assertEqual(results["weekly"].n_bars, 20)
        self.assertGreater(results["daily"].duration_ms, 0)
        self.assertGreater(results["weekly"].duration_ms, 0)

        print(f"  [I3] run_batch OK (daily={results['daily'].n_bars}, "
              f"weekly={results['weekly'].n_bars})")


# ═══════════════════════════════════════════════════════════════
# I5: PortfolioManager 单元测试
# ═══════════════════════════════════════════════════════════════


class TestPortfolioManager_I5(unittest.TestCase):
    """I5: PortfolioManager 信号→订单"""

    def test_process_buy_signal(self):
        mgr = PortfolioManager(initial_cash=1_000_000, symbol="601857")
        signal = Signal(symbol="601857", signal_value=1, confidence=0.8, price=100.0)
        bar = {"close": 100.0, "date": "2025-01-01"}

        order = mgr.process_signal(signal, bar)

        self.assertIsNotNone(order)
        self.assertEqual(order.side, OrderSide.BUY)
        self.assertGreater(order.quantity, 0)

    def test_process_sell_without_position(self):
        mgr = PortfolioManager(initial_cash=1_000_000, symbol="601857")
        signal = Signal(symbol="601857", signal_value=-1, confidence=0.8, price=100.0)

        order = mgr.process_signal(signal, {"close": 100.0})

        self.assertIsNone(order)

    def test_process_sell_with_position(self):
        mgr = PortfolioManager(initial_cash=1_000_000, symbol="601857")

        buy_signal = Signal(symbol="601857", signal_value=1, confidence=0.8, price=100.0)
        buy_order = mgr.process_signal(buy_signal, {"close": 100.0})
        mgr.on_order_filled("601857", OrderSide.BUY, buy_order.quantity, 100.0, fee=5)

        sell_signal = Signal(symbol="601857", signal_value=-1, confidence=0.8, price=105.0)
        sell_order = mgr.process_signal(sell_signal, {"close": 105.0})

        self.assertIsNotNone(sell_order)
        self.assertEqual(sell_order.side, OrderSide.SELL)
        self.assertEqual(sell_order.quantity, buy_order.quantity)

    def test_low_confidence_rejected(self):
        mgr = PortfolioManager(initial_cash=1_000_000, symbol="601857",
                                risk_manager=RiskManager(min_signal_confidence=0.5))
        signal = Signal(symbol="601857", signal_value=1, confidence=0.1, price=100.0)

        order = mgr.process_signal(signal, {"close": 100.0})
        self.assertIsNone(order)

    def test_order_filled_tracking(self):
        mgr = PortfolioManager(initial_cash=1_000_000, symbol="601857")

        # 开仓
        signal = Signal(symbol="601857", signal_value=1, confidence=0.9, price=50.0)
        order = mgr.process_signal(signal, {"close": 50.0})
        self.assertIsNotNone(order)
        mgr.on_order_filled("601857", OrderSide.BUY, order.quantity, 50.0)
        cash_after_buy = mgr.available_cash

        # 平仓获利
        mgr.on_order_filled("601857", OrderSide.SELL, order.quantity, 55.0)
        cash_after_sell = mgr.available_cash

        self.assertGreater(cash_after_sell, cash_after_buy)
        self.assertEqual(mgr.total_trades, 2)
        self.assertFalse(mgr.has_position)
        print(f"  [I5-e] order_tracking: buy_cash={cash_after_buy:.2f}, "
              f"sell_cash={cash_after_sell:.2f}")

    def test_update_market(self):
        mgr = PortfolioManager(initial_cash=1_000_000, symbol="601857")
        signal = Signal(symbol="601857", signal_value=1, confidence=0.8, price=100.0)
        order = mgr.process_signal(signal, {"close": 100.0})
        mgr.on_order_filled("601857", OrderSide.BUY, order.quantity, 100.0)

        mgr.update_market({"close": 110.0, "date": "2025-01-02"})
        pos = mgr.get_position("601857")
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos.unrealized_pnl, order.quantity * 10.0, delta=1)
        print(f"  [I5-f] market_update: qty={pos.quantity}, pnl={pos.unrealized_pnl:.2f}")

    def test_sizer_fixed_ratio(self):
        mgr = PortfolioManager(
            initial_cash=100_000, symbol="601857",
            sizer=FixedRatioSizer(0.5),
        )
        signal = Signal(symbol="601857", signal_value=1, confidence=1.0, price=100.0)
        order = mgr.process_signal(signal, {"close": 100.0})

        self.assertIsNotNone(order)
        self.assertEqual(order.quantity, 500)

    def test_result_to_signals(self):
        df = pd.DataFrame({
            "signal": [0, 1, 0, -1, 0],
            "confidence": [0, 0.8, 0, 0.7, 0],
        }, index=pd.date_range("2025-01-01", periods=5))
        result = MethodResult(signals=df, method_name="test")

        signals_list = PortfolioManager.result_to_signals(result, symbol="601857")

        self.assertEqual(len(signals_list), 2)
        self.assertEqual(signals_list[0].signal_value, 1)
        self.assertEqual(signals_list[1].signal_value, -1)
        print(f"  [I5-h] result_to_signals: {len(signals_list)} signals")


# ═══════════════════════════════════════════════════════════════
# I6: KnowledgeBridge 集成测试
# ═══════════════════════════════════════════════════════════════


class TestKnowledgeBridgeIntegration_I6(unittest.TestCase):
    """I6: KnowledgeBridge v2 通过 MethodBacktestRunner 集成"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_harvest_after_runner(self):
        """Runner 执行后调用 v2 harvest 生成知识条目"""
        df = make_test_df()
        ctx = make_mock_context({"ma_fast": 5, "ma_slow": 20}, symbol="601857")

        runner = MethodBacktestRunner("ma_cross", ctx)
        result = runner.run(df, symbol="601857", task_id="I6_test_001", harvest=True)

        # v2 接口: output_dir / harvest(result, method_name, symbol)
        bridge = KnowledgeBridge(output_dir=self.tmpdir, sync_to_bitable=False)
        entry = bridge.harvest(result, method_name="ma_cross", symbol="601857")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.method_name, "ma_cross")
        self.assertEqual(entry.symbol, "601857")
        print(f"  [I6-a] v2 harvest OK: method={entry.method_name}")

    def test_harvest_with_minimal_result(self):
        """最小 MethodResult 的 v2 harvest"""
        df = pd.DataFrame({"signal": [0, 1, 0]}, index=pd.date_range("2025-01-01", periods=3))
        result = MethodResult(signals=df, method_name="test", params={})

        bridge = KnowledgeBridge(output_dir=self.tmpdir, sync_to_bitable=False)
        entry = bridge.harvest(result, method_name="test", symbol="MIN")

        self.assertIsNotNone(entry)
        print(f"  [I6-b] minimal v2 harvest OK: method={entry.method_name}")


# ═══════════════════════════════════════════════════════════════
# I7: 错误处理
# ═══════════════════════════════════════════════════════════════


class TestRunnerErrorHandling_I7(unittest.TestCase):
    """I7: 异常路径"""

    def test_unknown_method(self):
        ctx = make_mock_context({})
        with self.assertRaises(ValueError):
            MethodBacktestRunner("nonexistent_method_xyz", ctx)
        print("  [I7] unknown method: ValueError raised")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
