"""
澧ㄦ灑 - P1-16 璧勯噾鎸佷粨FIFO鎴愭湰娴嬭瘯 (LEGACY_P1_16)
"""
import pytest
from pathlib import Path; import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from backtest.position_manager import PositionManager, Position, CostMethod


class TestFIFOCost:
    """FIFO 鍏堣繘鍏堝嚭鎴愭湰璁＄畻"""

    def test_fifo_simple_buy_sell(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600000", 1000, 10.0, fee=5.0)
        pnl, revenue = pm.close_position("600000", 500, 12.0, fee=3.0)
        # exp_pnl: revenue(500*12-3=5997) - cost(500*10=5000) = 997
        assert pnl == pytest.approx(997.0, rel=1e-3), f"pnl={pnl}"

    def test_fifo_lifo_vs_fifo(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600001", 500, 8.0)
        pm.open_position("600001", 500, 12.0)
        pnl, _ = pm.close_position("600001", 500, 15.0)
        # FIFO: 鍗栧嚭绗竴鎵?8.0) -> pnl = 500*15 - 500*8 = 3500
        assert pnl == pytest.approx(3500.0, rel=1e-3), f"pnl={pnl}"

    def test_fifo_multi_lot(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600002", 300, 10.0)
        pm.open_position("600002", 200, 12.0)
        pm.open_position("600002", 100, 15.0)
        pnl, _ = pm.close_position("600002", 400, 14.0)
        # 鍗栧嚭400鑲? len1(300@10) + len2(100@12) -> cost=300*10+100*12=4200, rev=400*14=5600
        assert pnl == pytest.approx(1400.0, rel=1e-3), f"pnl={pnl}"
        # 鍓╀綑200鑲?(100@12 + 100@15)
        pos = pm.get("600002")
        assert pos is not None and pos.quantity == 200
        assert abs(pos.cost_basis - (100*12 + 100*15)) < 0.01

    def test_fifo_close_all(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600003", 500, 11.0)
        pnl, rev = pm.close_position("600003", 500, 13.0)
        assert pnl == pytest.approx(1000.0, rel=1e-3)
        assert pm.get("600003") is None or pm.get("600003").quantity == 0

    def test_fifo_partial_close_keeps_cost_basis(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600004", 1000, 20.0)
        pm.open_position("600004", 500, 22.0)
        # 閮ㄥ垎骞充粨300鑲?
        pnl, rev = pm.close_position("600004", 300, 25.0)
        # 棣栨壒1000@20涓崠300
        assert pnl == pytest.approx(300*25 - 300*20, rel=1e-3)
        pos = pm.get("600004")
        assert pos.quantity == 1200, f"qty={pos.quantity}"
        # 鍓╀綑: 700@20 + 500@22 = 14000+11000=25000
        assert abs(pos.cost_basis - (700*20 + 500*22)) < 0.01

    def test_fifo_zero_fee(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600005", 100, 50.0, fee=0)
        pnl, rev = pm.close_position("600005", 100, 55.0, fee=0)
        assert pnl == pytest.approx(500.0, rel=1e-3)
        assert rev == pytest.approx(5500.0, rel=1e-3)

    def test_fifo_error_insufficient_position(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600006", 100, 10.0)
        with pytest.raises(ValueError):
            pm.close_position("600006", 200, 12.0)

    def test_wavg_different_from_fifo(self):
        """楠岃瘉鍔犳潈骞冲潎涓嶧IFO鍦ㄥ悓涓€鎵逛氦鏄撲笂缁撴灉涓嶅悓"""
        pm_fifo = PositionManager(cost_method=CostMethod.FIFO)
        pm_fifo.open_position("600007", 500, 10.0)
        pm_fifo.open_position("600007", 500, 20.0)
        pnl_fifo, _ = pm_fifo.close_position("600007", 500, 15.0)

        pm_wavg = PositionManager(cost_method=CostMethod.WEIGHTED_AVG)
        pm_wavg.open_position("600007", 500, 10.0)
        pm_wavg.open_position("600007", 500, 20.0)
        pnl_wavg, _ = pm_wavg.close_position("600007", 500, 15.0)
        # FIFO: selling 500@10 -> rev-rev=7500-5000=2500
        # WAVG: avg=15, cost=500*15=7500, rev=500*15=7500 -> pnl=0
        assert pnl_fifo == pytest.approx(2500.0, rel=1e-3)
        assert pnl_wavg == pytest.approx(0.0, rel=1e-3)

    def test_fifo_lots_cleanup_on_full_close(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600008", 200, 10.0)
        pm.open_position("600008", 300, 12.0)
        pm.close_position("600008", 500, 15.0)
        # 鍏ㄥ钩鍚庢鏌ユ竻鐞?
        pos = pm.get("600008")
        assert pos is None or pos.quantity == 0


class TestCapitalWithFIFO:
    """璧勯噾绠＄悊+FIFO鎸佷粨鑱斿姩"""

    def test_capital_freeze_deduct(self):
        from ..capital_manager import CapitalManager
        cap = CapitalManager(initial_capital=100000)
        cap.freeze(50000)
        assert cap.available == pytest.approx(50000.0)
        assert cap.frozen == pytest.approx(50000.0)
        cap.deduct(48000)  # 瀹為檯鎴愪氦
        assert cap.frozen == pytest.approx(2000.0)
        cap.unfreeze(2000)  # 閫€鍥?
        assert cap.frozen == pytest.approx(0.0)
        assert cap.available == pytest.approx(52000.0)

    def test_capital_simple_buy_sell(self):
        from ..capital_manager import CapitalManager
        cap = CapitalManager(initial_capital=100000)
        pm = PositionManager(cost_method=CostMethod.FIFO)
        # 涔板叆1000鑲20, 鏃犳墜缁垂
        pm.open_position("600900", 1000, 20.0, 0)
        cap.freeze(20000)
        cap.deduct(20000)
        assert cap.available == 80000
        # 鍗栧嚭涓€鍗?00鑲22, 鏃犳墜缁垂
        pnl, rev = pm.close_position("600900", 500, 22.0, 0)
        cap.add(rev)
        assert cap.available == 91000  # 80000 + 11000
        assert pnl == 1000.0  # 500*(22-20)

    def test_fifo_lot_tracking(self):
        pm = PositionManager(cost_method=CostMethod.FIFO)
        pm.open_position("600010", 100, 10.0)
        pm.open_position("600010", 200, 12.0)
        pm.open_position("600010", 150, 11.0)
        pos = pm.get("600010")
        assert len(pos.lots) == 3
        assert pos.lots[0] == (100, 10.0)
        assert pos.lots[1] == (200, 12.0)
        assert pos.lots[2] == (150, 11.0)
        # 閮ㄥ垎骞充粨250鑲? 100@10(鍏ㄧ敤) + 200@12(鐢?50) = 250
        pm.close_position("600010", 250, 15.0)
        # 鍓╀綑: 50@12 + 150@11
        assert len(pos.lots) == 2
        assert pos.lots[0] == (50, 12.0)
        assert pos.lots[1] == (150, 11.0)

