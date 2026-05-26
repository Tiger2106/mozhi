"""
趋势信号模块单元测试
覆盖：MA金叉死叉 / MACD / 布林带 / 趋势强度 / 加权投票 / 边界情况
"""
import pytest
import numpy as np
from backtest.strategies.trend_strategy import (
    ma_signal,
    macd_signal,
    bollinger_signal,
    trend_strength,
    trend_intensity,
    weighted_vote,
    Signal,
)


# ─────────────────────────────────────────────
# .fixtures
# ─────────────────────────────────────────────
@pytest.fixture
def up_trend() -> np.ndarray:
    """单调上涨序列 (30 bars)"""
    return np.array([10.0 + i * 0.5 for i in range(30)], dtype=float)


@pytest.fixture
def golden_cross_series() -> np.ndarray:
    """
    MA5[-2]=97 <= MA20[-2]=99.25  且  MA5[-1]=103 > MA20[-1]=100.25  → BUY
    """
    p = np.zeros(35, dtype=float) + 100.0
    p[29] = 90.0; p[30] = 95.0; p[31] = 100.0
    p[32] = 100.0; p[33] = 100.0; p[34] = 120.0
    return p


@pytest.fixture
def dead_cross_series() -> np.ndarray:
    """
    MA5[-2]=103 > MA20[-2]=100.75  且  MA5[-1]=96 < MA20[-1]=99.25  → SELL
    """
    p = np.zeros(35, dtype=float) + 100.0
    p[29] = 110.0; p[30] = 105.0; p[31] = 100.0
    p[32] = 100.0; p[33] = 100.0; p[34] = 80.0
    return p


@pytest.fixture
def bb_break_upper() -> np.ndarray:
    """价格上穿上轨 → BUY（最后一个价格远高于中轨）"""
    base = np.array([100.0 + (i % 5) * 2 for i in range(25)], dtype=float)
    return np.concatenate([base, np.array([200.0])])


@pytest.fixture
def bb_break_lower() -> np.ndarray:
    """价格下穿下轨 → SELL（最后一个价格远低于中轨）"""
    base = np.array([100.0 - (i % 5) * 2 for i in range(25)], dtype=float)
    return np.concatenate([base, np.array([50.0])])


@pytest.fixture
def macd_up_cross_seq() -> np.ndarray:
    """
    长序列：前段恒定低价 → 后段恒定高价 → EMA(fast) > EMA(slow)
    macd_signal 会在 index 50 处有 DIF 上穿 DEA
    截取前 51 根使得上穿正好在最后 1-2 根
    """
    return np.array([10.0] * 50 + [20.0] * 20, dtype=float)


@pytest.fixture
def macd_down_cross_seq() -> np.ndarray:
    """长序列：前段恒定高价 → 后段恒定低价 → DIF 下穿 DEA"""
    return np.array([20.0] * 50 + [10.0] * 20, dtype=float)


# ─────────────────────────────────────────────
# 1. MA 金叉 / 死叉
# ─────────────────────────────────────────────
class TestMASignal:
    def test_golden_cross_buy(self, golden_cross_series):
        """MA5 上穿 MA20 → BUY"""
        sig = ma_signal(golden_cross_series, fast=5, slow=20)
        assert sig.action == "BUY"
        assert sig.strength == 1.0

    def test_dead_cross_sell(self, dead_cross_series):
        """MA5 下穿 MA20 → SELL"""
        sig = ma_signal(dead_cross_series, fast=5, slow=20)
        assert sig.action == "SELL"
        assert sig.strength == 1.0

    def test_no_cross_up_trend(self, up_trend):
        """单边上涨无交叉 → HOLD"""
        sig = ma_signal(up_trend, fast=5, slow=20)
        assert sig.action == "HOLD"

    def test_insufficient_data(self):
        """数据不足一周期 → HOLD"""
        short = np.array([1.0, 2.0, 3.0])
        sig = ma_signal(short, fast=5, slow=20)
        assert sig.action == "HOLD"
        assert sig.strength == 0.0


# ─────────────────────────────────────────────
# 2. MACD 信号
# ─────────────────────────────────────────────
class TestMACDSignal:
    def test_dif_up_cross_dea_buy(self, macd_up_cross_seq):
        """
        macd_up_cross_seq 在 bar 50 处 DIF 上穿 DEA，
        截取到 bar 51 使得交叉落在最后 bar
        """
        seq = macd_up_cross_seq[:51]
        sig = macd_signal(seq, fast=12, slow=26, signal=9)
        assert sig.action == "BUY"

    def test_dif_down_cross_dea_sell(self, macd_down_cross_seq):
        """macd_down_cross_seq 在 bar 50 处 DIF 下穿 DEA"""
        seq = macd_down_cross_seq[:51]
        sig = macd_signal(seq, fast=12, slow=26, signal=9)
        assert sig.action == "SELL"

    def test_insufficient_data(self):
        """数据不足以计算 MACD → HOLD"""
        short = np.array([10.0] * 20)
        sig = macd_signal(short, fast=12, slow=26, signal=9)
        assert sig.action == "HOLD"

    def test_flat_prices_no_signal(self):
        """恒定价格无 DIF/DEA 交叉 → HOLD"""
        flat = np.array([100.0] * 100)
        sig = macd_signal(flat, fast=12, slow=26, signal=9)
        assert sig.action == "HOLD"


# ─────────────────────────────────────────────
# 3. 布林带突破
# ─────────────────────────────────────────────
class TestBollingerSignal:
    def test_break_upper_band_buy(self, bb_break_upper):
        """价格上穿上轨 → BUY"""
        sig = bollinger_signal(bb_break_upper, window=20, num_std=2.0)
        assert sig.action == "BUY"
        assert sig.strength == 1.0

    def test_break_lower_band_sell(self, bb_break_lower):
        """价格下穿下轨 → SELL"""
        sig = bollinger_signal(bb_break_lower, window=20, num_std=2.0)
        assert sig.action == "SELL"
        assert sig.strength == 1.0

    def test_insufficient_data(self):
        """数据不足 → HOLD"""
        short = np.array([1.0, 2.0, 3.0] * 6)
        sig = bollinger_signal(short, window=20)
        assert sig.action == "HOLD"


# ─────────────────────────────────────────────
# 4. 趋势强度
# ─────────────────────────────────────────────
class TestTrendStrength:
    def test_strong_up_trend(self, up_trend):
        """单调上涨 → 强趋势"""
        s = trend_strength(up_trend, window=20)
        assert s >= 0.6, f"强趋势期望 s≥0.6，实际 {s:.3f}"

    def test_strong_down_trend(self):
        """单调下跌 → 强趋势"""
        down = np.array([100.0 - i for i in range(30)], dtype=float)
        s = trend_strength(down, window=20)
        assert s >= 0.6

    def test_weak_random_walk(self):
        """随机游走数据 trend_strength 应返回有效数值（实现测度为线性相关性）"""
        np.random.seed(42)
        rw = np.cumsum(np.random.randn(50))
        s = trend_strength(rw, window=20)
        assert isinstance(s, float)
        assert 0.0 <= s <= 1.0

    def test_flat_no_trend(self):
        """恒定价格 → 无趋势 (< 0.3)"""
        flat = np.array([100.0] * 30, dtype=float)
        s = trend_strength(flat, window=20)
        assert s < 0.3, f"无趋势期望 s<0.3，实际 {s:.3f}"

    def test_insufficient_window(self):
        """窗口大于数据 → 0"""
        short = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        s = trend_strength(short, window=20)
        assert s == 0.0


class TestTrendIntensity:
    def test_intensity_strong(self, up_trend):
        assert trend_intensity(up_trend) == "strong"

    def test_intensity_none(self):
        flat = np.array([100.0] * 30, dtype=float)
        assert trend_intensity(flat) == "none"


# ─────────────────────────────────────────────
# 5. 加权投票
# ─────────────────────────────────────────────
class TestWeightedVote:
    def test_majority_buy(self):
        signals = [
            Signal("BUY", 1.0),
            Signal("BUY", 1.0),
            Signal("SELL", 1.0),
        ]
        result = weighted_vote(signals)
        assert result.action == "BUY"

    def test_weighted_buy_over_sell(self):
        """1个强 BUY 压制 2个弱 SELL"""
        signals = [
            Signal("BUY", 1.0),
            Signal("SELL", 0.3),
            Signal("SELL", 0.3),
        ]
        weights = [1.0, 1.0, 1.0]
        result = weighted_vote(signals, weights)
        assert result.action == "BUY"

    def test_all_hold(self):
        signals = [Signal("HOLD", 0.0), Signal("HOLD", 0.0)]
        result = weighted_vote(signals)
        assert result.action == "HOLD"

    def test_empty_signals(self):
        result = weighted_vote([])
        assert result.action == "HOLD"
        assert result.strength == 0.0

    def test_weight_length_mismatch_raises(self):
        signals = [Signal("BUY", 1.0), Signal("SELL", 0.5)]
        weights = [1.0]
        with pytest.raises(ValueError, match="长度必须一致"):
            weighted_vote(signals, weights)

    def test_no_weights_defaults_to_equal(self):
        signals = [Signal("BUY", 1.0), Signal("SELL", 0.5)]
        result = weighted_vote(signals)
        assert result.action == "BUY"

    def test_strength_normalized(self):
        signals = [Signal("BUY", 1.0), Signal("BUY", 1.0)]
        result = weighted_vote(signals)
        assert 0.0 < result.strength <= 1.0

    def test_buy_sell_tie_holds(self):
        signals = [Signal("BUY", 0.5), Signal("SELL", 0.5)]
        result = weighted_vote(signals)
        assert result.action == "HOLD"


# ─────────────────────────────────────────────
# 6. 边界情况
# ─────────────────────────────────────────────
class TestBoundaryCases:
    def test_empty_array(self):
        empty = np.array([], dtype=float)
        assert ma_signal(empty).action == "HOLD"
        assert macd_signal(empty).action == "HOLD"
        assert bollinger_signal(empty).action == "HOLD"

    def test_all_zeros(self):
        zeros = np.zeros(50, dtype=float)
        assert ma_signal(zeros).action == "HOLD"
        assert macd_signal(zeros).action == "HOLD"
        assert bollinger_signal(zeros).action == "HOLD"
        # trend_strength 对全零不应崩溃
        s = trend_strength(zeros, window=20)
        assert isinstance(s, float)

    def test_near_zero_prices(self):
        tiny = np.array([0.001] * 50, dtype=float)
        assert ma_signal(tiny).action == "HOLD"
        assert trend_strength(tiny, window=20) == 0.0

    def test_single_element(self):
        one = np.array([100.0])
        assert ma_signal(one, fast=5, slow=20).action == "HOLD"
        assert macd_signal(one).action == "HOLD"
        assert bollinger_signal(one).action == "HOLD"

    def test_inf_values(self):
        """无穷大值不崩溃，返回 Signal"""
        inf_prices = np.array([1.0] * 20 + [float("inf")] * 10)
        result = ma_signal(inf_prices)
        assert isinstance(result, Signal)

    def test_nan_values(self):
        """NaN 值不崩溃，返回 Signal"""
        nan_prices = np.array([10.0] * 20 + [float("nan")] * 5)
        result = ma_signal(nan_prices)
        assert isinstance(result, Signal)

    def test_negative_prices(self):
        """负价格应被正确处理（不崩溃）"""
        neg = np.array([-10.0] * 30)
        result = ma_signal(neg, fast=5, slow=20)
        assert isinstance(result, Signal)

    def test_single_value_repeated(self):
        """重复单一值（无方向）"""
        same = np.array([100.0] * 50)
        assert ma_signal(same).action == "HOLD"
        assert trend_intensity(same) == "none"

    def test_returns_signal_dataclass(self):
        """所有函数返回 Signal 实例"""
        prices = np.array([100.0 + i for i in range(50)], dtype=float)
        for func in [ma_signal, macd_signal, bollinger_signal]:
            result = func(prices)
            assert isinstance(result, Signal)
            assert result.action in ("BUY", "SELL", "HOLD")
            assert isinstance(result.strength, float)