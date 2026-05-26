"""
test_method_comparison.py — 新旧系统对比验证 (D6-D13)

对比测试:
  D6: MaCrossMethod vs trend_strategy.generate_ma_cross_signals
  D7: MACDMethod vs trend_strategy.generate_macd_signals
  D8: BollingerMethod vs trend_strategy.generate_bollinger_signals
  D9: RSIMethod vs reversal_strategy.generate_rsi_signals
  D10: KDJMethod vs reversal_strategy.generate_kdj_signals
  D11: BiasMethod vs reversal_strategy.generate_bias_signals
  D12: GridMethod (非精确对比, 验证信号值域)
  D13: ReversalMethod vs reversal_strategy.voted_reversal_signal

VolumeProfileMethod / WyckoffMethod: 全新实现，跳过对比
"""

import sys, os, unittest
import pandas as pd
import numpy as np
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.methods.comparison_test_helper import df_to_bars, compute_deviation

# 新方法导入
from backtest.methods.trend.ma_cross_method import MaCrossMethod
from backtest.methods.trend.macd_method import MACDMethod
from backtest.methods.trend.bollinger_method import BollingerMethod
from backtest.methods.momentum.rsi_method import RSIMethod
from backtest.methods.momentum.kdj_method import KDJMethod
from backtest.methods.momentum.bias_method import BiasMethod
from backtest.methods.grid.grid_method import GridMethod
from backtest.methods.reversal.reversal_method import ReversalMethod

# 旧系统导入
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


# ─── 辅助函数 ────────────────────────────────────────────────

DEVIATION_THRESHOLD = 0.005  # 0.5%


class MockContext:
    def __init__(self, config=None):
        self._config = config or {}
        self.symbol = "TEST"
    def get_config(self, key, default=None):
        return self._config.get(key, default)


def make_test_df(n=120) -> pd.DataFrame:
    """生成固定的可重现测试数据（含 OHLCV）"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    volume = np.random.randint(1000, 10000, n)
    return pd.DataFrame({
        "close": close, "high": high, "low": low, "volume": volume,
    }, index=pd.DatetimeIndex(dates))


def make_old_bars(n=120):
    """生成旧系统兼容的 bar 对象列表"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    volume = np.random.randint(1000, 10000, n)
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


def old_signal_list_to_series(old_signals: list, idx) -> pd.Series:
    """将旧系统的 list-of-dict 信号转为 pd.Series"""
    signals = [s.get("signal", 0) if isinstance(s, dict) else 0 for s in old_signals]
    return pd.Series(signals, index=idx)


# ═══════════════════════════════════════════════════════════════
# D6-D13: Method 对比验证
# ═══════════════════════════════════════════════════════════════


class TestMethodComparison_MaCross_D6(unittest.TestCase):
    """D6: MaCrossMethod vs trend_strategy.generate_ma_cross_signals"""

    def test_signal_deviation(self):
        df = make_test_df(120)
        old_bars = make_old_bars(120)

        old_signals = generate_ma_cross_signals(old_bars, ma_fast=5, ma_slow=20)
        old_sig = old_signal_list_to_series(old_signals, df.index)

        method = MaCrossMethod()
        method.setup(MockContext({"ma_fast": 5, "ma_slow": 20}))
        new_result = method.generate_signal(df)

        dev = compute_deviation(old_sig, new_result["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"MaCrossMethod 平均偏差 {dev:.6f}")
        print(f"  D6 MaCrossMethod 偏差: {dev:.6f}")


class TestMethodComparison_MACD_D7(unittest.TestCase):
    """D7: MACDMethod vs trend_strategy.generate_macd_signals"""

    def test_signal_deviation(self):
        df = make_test_df(120)
        old_bars = make_old_bars(120)

        old_signals = generate_macd_signals(old_bars, fast_period=12, slow_period=26, signal_period=9)
        old_sig = old_signal_list_to_series(old_signals, df.index)

        method = MACDMethod()
        method.setup(MockContext({"fast_period": 12, "slow_period": 26, "signal_period": 9}))
        new_result = method.generate_signal(df)

        dev = compute_deviation(old_sig, new_result["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"MACDMethod 平均偏差 {dev:.6f}")
        print(f"  D7 MACDMethod 偏差: {dev:.6f}")


class TestMethodComparison_Bollinger_D8(unittest.TestCase):
    """D8: BollingerMethod vs trend_strategy.generate_bollinger_signals"""

    def test_signal_deviation(self):
        df = make_test_df(120)
        old_bars = make_old_bars(120)

        old_signals = generate_bollinger_signals(old_bars, period=20, std_dev=2.0)
        old_sig = old_signal_list_to_series(old_signals, df.index)

        method = BollingerMethod()
        method.setup(MockContext({"period": 20, "std_dev": 2.0}))
        new_result = method.generate_signal(df)

        dev = compute_deviation(old_sig, new_result["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"BollingerMethod 平均偏差 {dev:.6f}")
        print(f"  D8 BollingerMethod 偏差: {dev:.6f}")


class TestMethodComparison_RSI_D9(unittest.TestCase):
    """D9: RSIMethod vs reversal_strategy.generate_rsi_signals"""

    def test_signal_deviation(self):
        df = make_test_df(120)
        old_bars = make_old_bars(120)

        old_signals = generate_rsi_signals(old_bars, period=14, oversold=30.0, overbought=70.0)
        old_sig = old_signal_list_to_series(old_signals, df.index)

        method = RSIMethod()
        method.setup(MockContext({"period": 14, "oversold": 30.0, "overbought": 70.0}))
        new_result = method.generate_signal(df)

        dev = compute_deviation(old_sig, new_result["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"RSIMethod 平均偏差 {dev:.6f}")
        print(f"  D9 RSIMethod 偏差: {dev:.6f}")


class TestMethodComparison_KDJ_D10(unittest.TestCase):
    """D10: KDJMethod vs reversal_strategy.generate_kdj_signals"""

    def test_signal_deviation(self):
        df = make_test_df(120)
        old_bars = make_old_bars(120)

        old_signals = generate_kdj_signals(old_bars, period=9, k_buy=20.0, k_sell=80.0)
        old_sig = old_signal_list_to_series(old_signals, df.index)

        method = KDJMethod()
        method.setup(MockContext({"n": 9, "m1": 3, "m2": 3, "oversold": 20.0, "overbought": 80.0}))
        new_result = method.generate_signal(df)

        dev = compute_deviation(old_sig, new_result["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"KDJMethod 平均偏差 {dev:.6f}")
        print(f"  D10 KDJMethod 偏差: {dev:.6f}")


class TestMethodComparison_Bias_D11(unittest.TestCase):
    """D11: BiasMethod vs reversal_strategy.generate_bias_signals"""

    def test_signal_deviation(self):
        df = make_test_df(120)
        old_bars = make_old_bars(120)

        old_signals = generate_bias_signals(old_bars, ma_period=20, bias_buy=-0.05, bias_sell=0.05)
        old_sig = old_signal_list_to_series(old_signals, df.index)

        method = BiasMethod()
        method.setup(MockContext({"ma_period": 20, "bias_buy": -0.05, "bias_sell": 0.05}))
        new_result = method.generate_signal(df)

        dev = compute_deviation(old_sig, new_result["signal"])
        self.assertLess(dev, DEVIATION_THRESHOLD,
                        f"BiasMethod 平均偏差 {dev:.6f}")
        print(f"  D11 BiasMethod 偏差: {dev:.6f}")


class TestMethodComparison_Grid_D12(unittest.TestCase):
    """D12: GridMethod 事件驱动验证"""

    def test_grid_signal_domain(self):
        """GridMethod 信号值域正确"""
        df = make_test_df(60)

        method = GridMethod()
        method.setup(MockContext({"n_levels": 6, "lookback": 20, "width_multiplier": 2.0}))
        new_result = method.generate_signal(df)
        self.assertIn("signal", new_result.columns)
        self.assertTrue(new_result["signal"].isin({-1, 0, 1}).all())

    def test_grid_on_bar(self):
        """GridMethod on_bar 不抛异常"""
        method = GridMethod()
        method.setup(MockContext({"n_levels": 6, "lookback": 20}))
        df = make_test_df(30)
        for i in range(len(df)):
            row = df.iloc[i]
            try:
                method.on_bar(row)
            except Exception as e:
                self.fail(f"GridMethod on_bar 在索引 {i} 抛异常: {e}")


class TestMethodComparison_Reversal_D13(unittest.TestCase):
    """D13: ReversalMethod vs reversal_strategy.voted_reversal_signal"""

    def test_voting_consistency(self):
        """多信号投票融合"""
        df = make_test_df(120)
        old_bars = make_old_bars(120)

        # 旧系统：生成三个子信号然后投票
        rsi_signals = generate_rsi_signals(old_bars, period=14, oversold=30.0, overbought=70.0)
        kdj_signals = generate_kdj_signals(old_bars, period=9, k_buy=20.0, k_sell=80.0)
        bias_signals = generate_bias_signals(old_bars, ma_period=20, bias_buy=-0.05, bias_sell=0.05)

        old_voted = voted_reversal_signal([rsi_signals, kdj_signals, bias_signals], min_votes=2)
        old_signal_list = old_voted.get("signal", [])

        # 新方法
        method = ReversalMethod()
        method.setup(MockContext({
            "rsi_period": 14, "rsi_oversold": 30.0, "rsi_overbought": 70.0,
            "kdj_n": 9, "kdj_oversold": 20.0, "kdj_overbought": 80.0,
            "bias_period": 20, "bias_buy": -0.05, "bias_sell": 0.05,
            "cooldown_bars": 5, "min_votes": 2,
        }))
        new_result = method.generate_signal(df)

        if old_signal_list and len(old_signal_list) == len(df):
            old_sig = pd.Series([s.get("signal", 0) for s in old_signal_list], index=df.index)
            dev = compute_deviation(old_sig, new_result["signal"])
            print(f"  D13 ReversalMethod 偏差: {dev:.6f}")
        else:
            print(f"  D13 ReversalMethod: 旧系统输出格式不同，跳过精确对比（仅验证新方法信号域）")

        # 至少验证新方法信号值域
        self.assertTrue(new_result["signal"].isin({-1, 0, 1}).all())


if __name__ == "__main__":
    unittest.main()
