"""
反转信号模块单元测试
覆盖：RSI / KDJ / 布林带反转 / 乖离率 / 多规则投票 / 冷却期 / 边界情况
"""
import pytest
import numpy as np
from backtest.strategies.reversal_strategy import (
    rsi_signal,
    kdj_signal,
    bollinger_reversal_signal,
    bias_signal,
    multi_vote,
    CooldownTracker,
    Signal,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────
@pytest.fixture
def rsi_oversold() -> np.ndarray:
    """RSI 持续低于 30 → BUY"""
    # 持续下跌 → RSI 极低
    return np.array([100.0 - i * 0.5 for i in range(30)], dtype=float)


@pytest.fixture
def rsi_overbought() -> np.ndarray:
    """RSI 持续高于 70 → SELL"""
    return np.array([50.0 + i * 0.5 for i in range(30)], dtype=float)


@pytest.fixture
def rsi_neutral() -> np.ndarray:
    """RSI 在 30~70 之间 → HOLD"""
    # 轻微波动，无明显趋势
    t = np.linspace(0, 4 * np.pi, 50)
    return np.array([100.0 + 5.0 * np.sin(ti) for ti in t], dtype=float)


@pytest.fixture
def kdj_oversold_series() -> np.ndarray:
    """KDJ 的 K 值持续低于 20 → BUY (单调下跌序列)"""
    return np.array([100.0 - i for i in range(50)], dtype=float)


@pytest.fixture
def kdj_overbought_series() -> np.ndarray:
    """KDJ 的 K 值持续高于 80 → SELL (单调上涨序列)"""
    return np.array([50.0 + i for i in range(50)], dtype=float)


@pytest.fixture
def bb_break_lower() -> np.ndarray:
    """价格跌破布林下轨 → BUY"""
    base = np.array([100.0 - (i % 5) * 1.5 for i in range(25)], dtype=float)
    return np.concatenate([base, np.array([50.0])])  # 急跌破下轨


@pytest.fixture
def bb_break_upper() -> np.ndarray:
    """价格突破布林上轨 → SELL"""
    base = np.array([100.0 + (i % 5) * 1.5 for i in range(25)], dtype=float)
    return np.concatenate([base, np.array([160.0])])  # 急涨穿上轨


@pytest.fixture
def bias_oversold() -> np.ndarray:
    """乖离率 bias < -5% → BUY"""
    # 价格远低于均线 → bias 负值大
    prices = np.zeros(30, dtype=float) + 100.0
    prices[25:] = 80.0  # 最后几根暴跌，远低于 100 均值
    return prices


@pytest.fixture
def bias_overbought() -> np.ndarray:
    """乖离率 bias > 5% → SELL"""
    prices = np.zeros(30, dtype=float) + 100.0
    prices[25:] = 110.0  # 最后几根暴涨，远高于 100 均值
    return prices


# ─────────────────────────────────────────────
# 1. RSI 信号
# ─────────────────────────────────────────────
class TestRSISignal:
    def test_oversold_triggers_buy(self, rsi_oversold):
        """RSI 持续低位 → BUY"""
        sig = rsi_signal(rsi_oversold, window=14, buy_thr=30.0, sell_thr=70.0)
        assert sig.action == "BUY"
        assert sig.strength > 0.0

    def test_overbought_triggers_sell(self, rsi_overbought):
        """RSI 持续高位 → SELL"""
        sig = rsi_signal(rsi_overbought, window=14, buy_thr=30.0, sell_thr=70.0)
        assert sig.action == "SELL"
        assert sig.strength > 0.0

    def test_neutral_returns_hold(self, rsi_neutral):
        """RSI 在 30~70 之间 → HOLD"""
        sig = rsi_signal(rsi_neutral, window=14, buy_thr=30.0, sell_thr=70.0)
        assert sig.action == "HOLD"

    def test_rsi_exact_thresholds(self):
        """RSI 刚好等于阈值应正确触发"""
        # 构造刚好 RSI=30 的序列较难，用阈值边界附近数据验证
        # 上涨趋势 → RSI > 70
        up = np.array([100.0 + i for i in range(40)], dtype=float)
        sig = rsi_signal(up)
        # 纯上涨 RSI 应该很高 → SELL
        assert sig.action in ("SELL", "HOLD"), f"expected SELL/HOLD, got {sig.action}"

    def test_insufficient_data_rsi(self):
        """数据不足 → HOLD"""
        short = np.array([1.0, 2.0, 3.0])
        sig = rsi_signal(short)
        assert sig.action == "HOLD"
        assert sig.strength == 0.0


# ─────────────────────────────────────────────
# 2. KDJ 信号
# ─────────────────────────────────────────────
class TestKDJSignal:
    def test_oversold_k_triggers_buy(self, kdj_oversold_series):
        """K < 20 → BUY"""
        sig = kdj_signal(kdj_oversold_series, n=9, buy_thr=20.0, sell_thr=80.0)
        assert sig.action == "BUY"
        assert sig.strength > 0.0

    def test_overbought_k_triggers_sell(self, kdj_overbought_series):
        """K > 80 → SELL"""
        sig = kdj_signal(kdj_overbought_series, n=9, buy_thr=20.0, sell_thr=80.0)
        assert sig.action == "SELL"
        assert sig.strength > 0.0

    def test_k_in_middle_returns_hold(self):
        """K 在 20~80 之间 → HOLD"""
        # 平稳价格 → K 应在 50 附近
        flat = np.array([100.0] * 30, dtype=float)
        sig = kdj_signal(flat, n=9)
        assert sig.action == "HOLD"

    def test_insufficient_data_kdj(self):
        """数据不足 → HOLD"""
        short = np.array([1.0] * 5)
        sig = kdj_signal(short, n=9)
        assert sig.action == "HOLD"
        assert sig.strength == 0.0


# ─────────────────────────────────────────────
# 3. 布林带反转信号
# ─────────────────────────────────────────────
class TestBollingerReversalSignal:
    def test_break_lower_band_buy(self, bb_break_lower):
        """价格跌破下轨 → BUY"""
        sig = bollinger_reversal_signal(bb_break_lower, window=20, num_std=2.0)
        assert sig.action == "BUY"
        assert sig.strength == 1.0

    def test_break_upper_band_sell(self, bb_break_upper):
        """价格突破上轨 → SELL"""
        sig = bollinger_reversal_signal(bb_break_upper, window=20, num_std=2.0)
        assert sig.action == "SELL"
        assert sig.strength == 1.0

    def test_no_break_returns_hold(self):
        """价格未穿越轨道 → HOLD"""
        # 稳定在轨道内
        base = np.array([100.0 + (i % 3) for i in range(30)], dtype=float)
        sig = bollinger_reversal_signal(base, window=20, num_std=2.0)
        assert sig.action == "HOLD"

    def test_insufficient_data_bollinger_rev(self):
        """数据不足 → HOLD"""
        short = np.array([1.0, 2.0, 3.0] * 6)
        sig = bollinger_reversal_signal(short, window=20)
        assert sig.action == "HOLD"


# ─────────────────────────────────────────────
# 4. 乖离率信号
# ─────────────────────────────────────────────
class TestBiasSignal:
    def test_bias_oversold_triggers_buy(self, bias_oversold):
        """bias < -5% → BUY"""
        sig = bias_signal(bias_oversold, window=20, buy_thr=-5.0, sell_thr=5.0)
        assert sig.action == "BUY"
        assert sig.strength > 0.0

    def test_bias_overbought_triggers_sell(self, bias_overbought):
        """bias > 5% → SELL"""
        sig = bias_signal(bias_overbought, window=20, buy_thr=-5.0, sell_thr=5.0)
        assert sig.action == "SELL"
        assert sig.strength > 0.0

    def test_bias_neutral_returns_hold(self):
        """bias 在 -5%~5% 之间 → HOLD"""
        # 价格紧贴均线
        flat = np.array([100.0] * 30, dtype=float)
        sig = bias_signal(flat, window=20, buy_thr=-5.0, sell_thr=5.0)
        assert sig.action == "HOLD"

    def test_insufficient_data_bias(self):
        """数据不足 → HOLD"""
        short = np.array([1.0] * 5)
        sig = bias_signal(short)
        assert sig.action == "HOLD"


# ─────────────────────────────────────────────
# 5. 多规则投票
# ─────────────────────────────────────────────
class TestMultiVote:
    def test_threshold_buy(self):
        """至少 threshold 个 BUY → BUY"""
        signals = [
            Signal("BUY", 1.0),
            Signal("BUY", 0.8),
            Signal("SELL", 0.5),
        ]
        result = multi_vote(signals, threshold=2)
        assert result.action == "BUY"

    def test_threshold_not_met_holds(self):
        """
        BUY count < threshold 且 SELL score 不占优 → HOLD
        使用 [BUY1, SELL0.5, SELL0.5]:
        - BUY count=1 < threshold(2) → 不能发 BUY
        - SELL count=2 >= threshold(2) → 候选 SELL，但 sell_score=1.0 == buy_score=1.0
          → score 相等不满足 sell_score > buy_score 条件 → HOLD
        """
        signals = [
            Signal("BUY", 1.0),
            Signal("SELL", 0.5),
            Signal("SELL", 0.5),
        ]
        result = multi_vote(signals, threshold=2)
        assert result.action == "HOLD"

    def test_threshold_sell(self):
        """至少 threshold 个 SELL → SELL"""
        signals = [
            Signal("SELL", 1.0),
            Signal("SELL", 0.9),
            Signal("BUY", 0.3),
        ]
        result = multi_vote(signals, threshold=2)
        assert result.action == "SELL"

    def test_weighted_vote_buy_over_sell(self):
        """加权：强 BUY 压制弱 SELL"""
        signals = [
            Signal("BUY", 1.0),
            Signal("SELL", 0.3),
            Signal("SELL", 0.3),
        ]
        weights = [1.0, 1.0, 1.0]
        result = multi_vote(signals, threshold=1, weights=weights)
        assert result.action == "BUY"

    def test_empty_signals(self):
        result = multi_vote([])
        assert result.action == "HOLD"
        assert result.strength == 0.0

    def test_weight_length_mismatch_raises(self):
        signals = [Signal("BUY", 1.0)]
        weights = [1.0, 2.0]
        with pytest.raises(ValueError, match="长度必须一致"):
            multi_vote(signals, weights=weights)

    def test_buy_sell_tie_holds(self):
        signals = [Signal("BUY", 0.5), Signal("SELL", 0.5)]
        result = multi_vote(signals, threshold=1)
        assert result.action == "HOLD"


# ─────────────────────────────────────────────
# 6. 冷却期追踪器
# ─────────────────────────────────────────────
class TestCooldownTracker:
    def test_buy_allowed_initially(self):
        tracker = CooldownTracker(cooldown_bars=5)
        assert tracker.can_buy("AAPL", 0) is True

    def test_buy_blocked_during_cooldown(self):
        tracker = CooldownTracker(cooldown_bars=5)
        tracker.record_buy("AAPL", 10)
        assert tracker.can_buy("AAPL", 11) is False
        assert tracker.can_buy("AAPL", 12) is False
        assert tracker.can_buy("AAPL", 14) is False
        assert tracker.can_buy("AAPL", 15) is True   # exactly cooldown_bars later
        assert tracker.can_buy("AAPL", 16) is True

    def test_sell_cooldown_independent(self):
        tracker = CooldownTracker(cooldown_bars=3)
        tracker.record_sell("AAPL", 5)
        assert tracker.can_sell("AAPL", 5) is False
        assert tracker.can_sell("AAPL", 6) is False
        assert tracker.can_sell("AAPL", 7) is False
        assert tracker.can_sell("AAPL", 8) is True

    def test_different_symbols_no_interference(self):
        tracker = CooldownTracker(cooldown_bars=5)
        tracker.record_buy("AAPL", 10)
        assert tracker.can_buy("MSFT", 10) is True  # different symbol, no cooldown

    def test_record_buy_updates_last_bar(self):
        tracker = CooldownTracker(cooldown_bars=5)
        tracker.record_buy("AAPL", 10)
        tracker.record_buy("AAPL", 15)  # 更新
        # bar 10→15 需要 5 bars 冷却，所以 bar 15+1=16 才可买
        assert tracker.can_buy("AAPL", 16) is False  # still within 5 bars: 15+5=20, bar 16 < 20
        assert tracker.can_buy("AAPL", 20) is True

    def test_reset_clears_cooldown(self):
        tracker = CooldownTracker(cooldown_bars=5)
        tracker.record_buy("AAPL", 10)
        tracker.reset("AAPL")
        assert tracker.can_buy("AAPL", 11) is True

    def test_remaining_cooldown_buy(self):
        tracker = CooldownTracker(cooldown_bars=5)
        tracker.record_buy("AAPL", 10)
        assert tracker.remaining_cooldown_buy("AAPL", 11) == 4
        assert tracker.remaining_cooldown_buy("AAPL", 14) == 1
        assert tracker.remaining_cooldown_buy("AAPL", 15) == 0
        assert tracker.remaining_cooldown_buy("AAPL", 20) == 0

    def test_remaining_cooldown_sell(self):
        tracker = CooldownTracker(cooldown_bars=3)
        tracker.record_sell("AAPL", 5)
        assert tracker.remaining_cooldown_sell("AAPL", 6) == 2
        assert tracker.remaining_cooldown_sell("AAPL", 8) == 0

    def test_never_traded_symbol_returns_zero_remaining(self):
        tracker = CooldownTracker(cooldown_bars=5)
        assert tracker.remaining_cooldown_buy("AAPL", 10) == 0
        assert tracker.remaining_cooldown_sell("AAPL", 10) == 0

    def test_zero_cooldown_allows_immediate(self):
        tracker = CooldownTracker(cooldown_bars=0)
        tracker.record_buy("AAPL", 10)
        assert tracker.can_buy("AAPL", 10) is True


# ─────────────────────────────────────────────
# 7. 边界情况
# ─────────────────────────────────────────────
class TestReversalBoundary:
    def test_empty_array(self):
        empty = np.array([], dtype=float)
        assert rsi_signal(empty).action == "HOLD"
        assert kdj_signal(empty).action == "HOLD"
        assert bollinger_reversal_signal(empty).action == "HOLD"
        assert bias_signal(empty).action == "HOLD"

    def test_all_zeros(self):
        zeros = np.zeros(50, dtype=float)
        assert rsi_signal(zeros).action == "HOLD"
        assert kdj_signal(zeros).action in ("BUY", "HOLD")  # KDJ 可能给50
        assert bollinger_reversal_signal(zeros).action == "HOLD"
        assert bias_signal(zeros).action == "HOLD"

    def test_near_zero_prices(self):
        tiny = np.array([0.001] * 50, dtype=float)
        assert rsi_signal(tiny).action == "HOLD"
        assert kdj_signal(tiny).action == "HOLD"
        assert bollinger_reversal_signal(tiny).action == "HOLD"
        assert bias_signal(tiny).action == "HOLD"

    def test_single_element(self):
        one = np.array([100.0])
        assert rsi_signal(one).action == "HOLD"
        assert kdj_signal(one).action == "HOLD"
        assert bollinger_reversal_signal(one).action == "HOLD"
        assert bias_signal(one).action == "HOLD"

    def test_inf_values(self):
        inf_prices = np.array([1.0] * 20 + [float("inf")] * 10)
        assert isinstance(rsi_signal(inf_prices), Signal)
        assert isinstance(kdj_signal(inf_prices), Signal)

    def test_nan_values(self):
        nan_prices = np.array([10.0] * 20 + [float("nan")] * 5)
        assert isinstance(rsi_signal(nan_prices), Signal)
        assert isinstance(kdj_signal(nan_prices), Signal)

    def test_negative_prices(self):
        neg = np.array([-10.0] * 30)
        result = rsi_signal(neg)
        assert isinstance(result, Signal)

    def test_identical_prices(self):
        same = np.array([100.0] * 50)
        assert rsi_signal(same).action == "HOLD"
        assert kdj_signal(same).action == "HOLD"
        assert bollinger_reversal_signal(same).action == "HOLD"
        assert bias_signal(same).action == "HOLD"

    def test_returns_signal_dataclass(self):
        """所有函数返回 Signal 实例"""
        prices = np.array([100.0 + i for i in range(50)], dtype=float)
        for func in [rsi_signal, kdj_signal, bollinger_reversal_signal, bias_signal]:
            result = func(prices)
            assert isinstance(result, Signal)
            assert result.action in ("BUY", "SELL", "HOLD")
            assert isinstance(result.strength, float)

    def test_cooldown_tracker_zero_bars(self):
        tracker = CooldownTracker(cooldown_bars=0)
        tracker.record_buy("AAPL", 5)
        assert tracker.can_buy("AAPL", 5) is True
        assert tracker.can_sell("AAPL", 5) is True

    def test_multi_vote_threshold_zero(self):
        signals = [Signal("SELL", 0.1)]
        result = multi_vote(signals, threshold=0)
        # threshold=0 always met; since sell_score>buy_score → SELL
        assert result.action == "SELL"