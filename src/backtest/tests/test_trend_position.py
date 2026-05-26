"""
墨枢 - P2-12 仓位管理测试 (LEGACY_P2_12)

覆盖: FixedPosition / TrendScorePosition / PyramidPosition / StopLossTakeProfit
"""
import pytest
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from backtest.backtest_engine import Bar
from backtest.position_manager import Position
from backtest.strategies.trend_position import (
    FixedPosition,
    TrendScorePosition,
    PyramidPosition,
    StopLossTakeProfit,
)


def mkbar(date, open_, high, low, close, volume=1_000_000, symbol="601857"):
    return Bar(date=date, symbol=symbol, open=open_, high=high, low=low, close=close, volume=volume)


# ───────── P2-08: FixedPosition ─────────

class TestFixedPosition:
    def test_calc_open_basic(self):
        assert FixedPosition(0.3).calc_open_quantity(1_000_000, 50.0) == 6000

    def test_round_to_100(self):
        assert FixedPosition(0.3).calc_open_quantity(1_000_000, 37.8) == 7900

    def test_close_full(self):
        pos = Position(symbol="X", quantity=5000, avg_cost=10.0, cost_basis=50000)
        assert FixedPosition(0.3).calc_close_quantity(pos) == 5000

    def test_validation(self):
        with pytest.raises(ValueError): FixedPosition(0)
        with pytest.raises(ValueError): FixedPosition(1.5)
        with pytest.raises(ValueError): FixedPosition(-0.1)

    def test_params(self):
        p = FixedPosition(0.25).params
        assert p["position_ratio"] == 0.25 and p["mode"] == "fixed"

    def test_zero_shares(self):
        assert FixedPosition(0.01).calc_open_quantity(1_000, 500.0) == 0


# ───────── P2-09: TrendScorePosition ─────────

class TestTrendScorePosition:
    def test_lowest_no_trade(self):
        assert TrendScorePosition().score_to_ratio(40) == 0.0
        assert TrendScorePosition().calc_open_quantity(1_000_000, 50.0, 40) == 0

    def test_basic_mapping(self):
        tsp = TrendScorePosition()
        assert tsp.score_to_ratio(60) == 0.15
        assert tsp.score_to_ratio(80) == 0.30
        assert tsp.score_to_ratio(100) == 0.50

    def test_interpolation(self):
        assert TrendScorePosition().score_to_ratio(70) == pytest.approx(0.225)

    def test_above_max(self):
        assert TrendScorePosition().score_to_ratio(120) == 0.50
        qty = TrendScorePosition().calc_open_quantity(1_000_000, 50.0, 120)
        assert qty == 10000  # 1M*0.5/50=10000

    def test_custom_map(self):
        tsp = TrendScorePosition(score_map=[(50, 0.1), (70, 0.2), (90, 0.4)])
        assert tsp.score_to_ratio(40) == 0.0
        assert tsp.score_to_ratio(50) == 0.1
        assert tsp.score_to_ratio(60) == pytest.approx(0.15)
        assert tsp.score_to_ratio(90) == 0.4
        assert tsp.score_to_ratio(100) == 0.4
        qty = tsp.calc_open_quantity(1_000_000, 50.0, 60)
        assert qty == 3000  # 1M*0.15/50=3000

    def test_params(self):
        p = TrendScorePosition().params
        assert p["mode"] == "trend_score" and len(p["score_map"]) == 3


# ───────── P2-10: PyramidPosition ─────────

class TestPyramidPosition:
    def test_first_entry(self):
        pp = PyramidPosition(initial_ratio=0.3)
        assert pp.calc_open_quantity(1_000_000, 50.0) == 6000

    def test_close_full(self):
        pos = Position(symbol="X", quantity=3000, avg_cost=10.0, cost_basis=30000)
        assert PyramidPosition(0.3).calc_close_quantity(pos) == 3000

    def test_params(self):
        p = PyramidPosition(0.3).params
        assert p["initial_ratio"] == 0.3 and p["mode"] == "pyramid"


# ───────── P2-11: StopLossTakeProfit ─────────

class TestStopLossTakeProfit:
    def test_no_trigger(self):
        pos = Position(symbol="X", quantity=1000, avg_cost=10.0, cost_basis=10000)
        bars = [mkbar(f"202601{i+1:02d}", 9.5, 10.1, 9.4, 10.0 + i*0.02) for i in range(50)]
        r = StopLossTakeProfit(fixed_stop_loss=0.05).check_exit(pos, bars[-1], bars, len(bars)-1)
        assert r.should_exit is False

    def test_trigger(self):
        pos = Position(symbol="X", quantity=1000, avg_cost=10.0, cost_basis=10000)
        bars = [mkbar(f"202601{i+1:02d}", 9.5, 10.1, 9.4, 10.0) for i in range(20)]
        bad = mkbar("20260301", 9.5, 9.5, 9.4, 9.4)
        r = StopLossTakeProfit(fixed_stop_loss=0.05).check_exit(pos, bad, bars+[bad], -1)
        assert r.should_exit is True

    def test_trigger_reason(self):
        pos = Position(symbol="X", quantity=1000, avg_cost=10.0, cost_basis=10000)
        bars = [mkbar(f"202601{i+1:02d}", 9.5, 10.1, 9.4, 10.0) for i in range(20)]
        bad = mkbar("20260301", 9.5, 9.5, 9.4, 9.4)
        r = StopLossTakeProfit(fixed_stop_loss=0.05).check_exit(pos, bad, bars+[bad], -1)
        assert r.reason is not None

    def test_params(self):
        p = StopLossTakeProfit(fixed_stop_loss=0.05).params
        assert "fixed_stop_loss" in p
