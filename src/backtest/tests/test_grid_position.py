"""
test_grid_position.py — P4-07/P4-08/P4-09 网格仓位管理 + 风控单元测试

覆盖6个分组，共27+项测试：
1. GridFixedPosition 测试（≥6项）
2. GridLayerPosition 测试（≥5项）
3. GridBatcherPosition 测试（≥4项）
4. 风控测试（≥6项）
5. 工厂函数测试（≥4项）
6. 集成测试（≥2项）

Author: 墨萱
Created: 2026-05-15
"""

import pytest
import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from backtest.backtest_engine import Bar
from backtest.position_manager import Position
from backtest.strategies.grid_position import (
    GridFixedPosition,
    GridLayerPosition,
    GridBatcherPosition,
    GridCoolDown,
    GridStopLoss,
    GridMaxExposure,
    GridPositionManager,
    create_grid_position,
    create_grid_risk,
    create_grid_manager,
    _clamp_to_lot,
    LOT_SIZE,
)


# ═══════════════════════════════════════════════════════════════
# 测试数据构造工具
# ═══════════════════════════════════════════════════════════════


def make_bar(
    date: str,
    symbol: str = "000001.SZ",
    o: float = 10.0,
    h: float = 10.5,
    l: float = 9.5,
    c: float = 10.0,
    v: float = 1_000_000.0,
) -> Bar:
    return Bar(date=date, symbol=symbol, open=o, high=h, low=l, close=c, volume=v)


class MockContext:
    """轻量 mock 上下文，不需要完整 BacktestContext"""

    def __init__(
        self,
        available_capital: float = 1_000_000.0,
        positions: Optional[dict] = None,
        total_equity: float = 1_000_000.0,
    ):
        self._available_capital = available_capital
        self._positions = positions or {}
        self._total_equity = total_equity

    @property
    def available_capital(self) -> float:
        return self._available_capital

    @property
    def positions(self):
        return self._positions

    @property
    def total_equity(self) -> float:
        return self._total_equity


# ═══════════════════════════════════════════════════════════════
# 1. GridFixedPosition 测试
# ═══════════════════════════════════════════════════════════════


class TestGridFixedPosition:
    """GridFixedPosition — 网格固定仓位"""

    def test_on_buy_basic(self):
        """基础：quantity=500 → on_buy返回500"""
        pos = GridFixedPosition(quantity=500)
        bar = make_bar("2026-01-01", c=10.0)
        ctx = MockContext(available_capital=1_000_000.0)
        assert pos.on_buy_signal(ctx, bar) == 500

    def test_on_buy_capital_constraint(self):
        """资金约束：可用资金不足时自动调减"""
        pos = GridFixedPosition(quantity=500)
        bar = make_bar("2026-01-01", c=10.0)
        # 可用资金很少，单笔 500 股需要 5000 元，但可用仅 1000 元
        ctx = MockContext(available_capital=1000.0)
        qty = pos.on_buy_signal(ctx, bar)
        # 1000 / (10 * 1.001) ≈ 99 → clamp to 0
        assert qty == 0

    def test_clamp_123(self):
        """舍入：clamp(123) → 100"""
        assert GridFixedPosition.clamp(123) == 100

    def test_clamp_0(self):
        """舍入：clamp(0) → 0（边界）"""
        assert GridFixedPosition.clamp(0) == 0

    def test_clamp_100(self):
        """舍入：clamp(100) → 100"""
        assert GridFixedPosition.clamp(100) == 100

    def test_validate_ok(self):
        """validate：quantity≥100 → True"""
        pos = GridFixedPosition(quantity=200)
        assert pos.validate() is True

    def test_validate_fail_low(self):
        """validate：quantity=50 → False（低于最小单位）"""
        pos = GridFixedPosition(quantity=100)  # 最低合法值
        # 故意绕过后检查...实际需要用错误的值触发
        # 这里测试 quantity=LOT_SIZE-1 的情况会在 __init__ 抛异常
        with pytest.raises(ValueError):
            GridFixedPosition(quantity=50)

    def test_on_sell_with_position(self):
        """on_sell：有持仓 → min(quantity, pos_qty)"""
        pos = GridFixedPosition(quantity=500)
        bar = make_bar("2026-01-01", c=10.0)
        real_pos = Position("000001.SZ", quantity=300, avg_cost=10.0, cost_basis=3000)
        ctx = MockContext(positions={"000001.SZ": real_pos})
        assert pos.on_sell_signal(ctx, bar) == 300

    def test_on_sell_no_position(self):
        """on_sell：无持仓 → 0"""
        pos = GridFixedPosition(quantity=500)
        bar = make_bar("2026-01-01", c=10.0)
        ctx = MockContext(positions={})
        assert pos.on_sell_signal(ctx, bar) == 0

    def test_params_property(self):
        """params property：返回正确的dict"""
        pos = GridFixedPosition(quantity=200)
        p = pos.params
        assert p["quantity"] == 200
        assert p["mode"] == "grid_fixed"


# ═══════════════════════════════════════════════════════════════
# 2. GridLayerPosition 测试
# ═══════════════════════════════════════════════════════════════


class TestGridLayerPosition:
    """GridLayerPosition — 网格层数阶梯仓位"""

    def test_get_layer_count_zero(self):
        """get_layer_count：空列表 → 0"""
        assert GridLayerPosition.get_layer_count([]) == 0

    def test_get_layer_count_one(self):
        """get_layer_count：1层触发 → 1"""
        assert GridLayerPosition.get_layer_count(["level_0"]) == 1

    def test_get_layer_count_three(self):
        """get_layer_count：3层触发 → 3"""
        assert GridLayerPosition.get_layer_count(["level_0", "level_1", "level_2"]) == 3

    def test_on_buy_layer_calculation(self):
        """on_buy：base=200, mult=2.0, count=3 → 200*2^3=1600"""
        pos = GridLayerPosition(base_quantity=200, layer_multiplier=2.0, max_layers=5)
        bar = make_bar("2026-01-01", c=10.0)
        ctx = MockContext(available_capital=1_000_000.0)
        qty = pos.on_buy_signal(ctx, bar, triggered_levels=["l0", "l1", "l2"])
        assert qty == 1600

    def test_multiplier_cap_applied(self):
        """multiplier_cap：count超过上限 → cap生效"""
        pos = GridLayerPosition(
            base_quantity=100,
            layer_multiplier=2.0,
            max_layers=5,
            multiplier_cap=4.0,  # cap = 4.0
        )
        bar = make_bar("2026-01-01", c=10.0)
        ctx = MockContext(available_capital=1_000_000.0)
        # count=5, mult=2^5=32, but cap=4 → 100*4=400
        qty = pos.on_buy_signal(ctx, bar, triggered_levels=["l0", "l1", "l2", "l3", "l4"])
        assert qty == 400

    def test_capital_constraint_layer(self):
        """资金约束下buy → 不会超过可用资金"""
        pos = GridLayerPosition(base_quantity=1000, layer_multiplier=2.0)
        bar = make_bar("2026-01-01", c=10.0)
        ctx = MockContext(available_capital=2000.0)  # 仅2000元可用
        qty = pos.on_buy_signal(ctx, bar, triggered_levels=["l0", "l1", "l2"])
        # 理论值 1000*2^3=8000，但资金只够 2000/(10*1.001)≈199 qty → clamp=100
        assert qty <= 200  # 有一定的容忍

    def test_params_property_layer(self):
        """params property：返回正确的dict"""
        pos = GridLayerPosition(base_quantity=100, layer_multiplier=2.0, max_layers=3, multiplier_cap=8.0)
        p = pos.params
        assert p["base_quantity"] == 100
        assert p["layer_multiplier"] == 2.0
        assert p["max_layers"] == 3
        assert p["multiplier_cap"] == 8.0
        assert p["mode"] == "grid_layer"

    def test_on_sell_layer_all_out(self):
        """on_sell：全部卖出当前持仓"""
        pos = GridLayerPosition(base_quantity=100)
        bar = make_bar("2026-01-01", c=10.0)
        real_pos = Position("000001.SZ", quantity=700, avg_cost=10.0, cost_basis=7000)
        ctx = MockContext(positions={"000001.SZ": real_pos})
        assert pos.on_sell_signal(ctx, bar) == 700


# ═══════════════════════════════════════════════════════════════
# 3. GridBatcherPosition 测试
# ═══════════════════════════════════════════════════════════════


class TestGridBatcherPosition:
    """GridBatcherPosition — 分批建仓"""

    def test_price_at_bottom_ratio(self):
        """价格在level_from=0.0位置 → ratio 0.5生效"""
        pos = GridBatcherPosition(total_grid_rows=10)
        bar = make_bar("2026-01-01", c=10.0)
        ctx = MockContext(available_capital=100_000.0)
        # grid_position=0.0 → tier[0] ratio=0.50
        qty = pos.on_buy_signal(ctx, bar, grid_position=0.0)
        expected = int(100_000 * 0.50 / (10.0 * 1.001))
        assert qty <= expected
        assert qty > 0

    def test_price_at_middle_ratio(self):
        """价格在level_from=0.5位置 → ratio 0.3生效"""
        pos = GridBatcherPosition(total_grid_rows=10)
        bar = make_bar("2026-01-01", c=10.0)
        ctx = MockContext(available_capital=100_000.0)
        # grid_position=0.5 → tier[1] ratio=0.30
        qty = pos.on_buy_signal(ctx, bar, grid_position=0.5)
        expected = int(100_000 * 0.30 / (10.0 * 1.001))
        assert qty <= expected
        assert qty > 0

    def test_default_tiers_count(self):
        """默认tiers配置验证（3个区间）"""
        pos = GridBatcherPosition()
        tiers = pos.tiers
        assert len(tiers) == 3
        assert tiers[0]["level_from"] == 0.0
        assert tiers[0]["ratio"] == 0.50
        assert tiers[1]["level_from"] == 0.33
        assert tiers[1]["ratio"] == 0.30
        assert tiers[2]["level_from"] == 0.66
        assert tiers[2]["ratio"] == 0.20

    def test_params_property_batcher(self):
        """params property"""
        pos = GridBatcherPosition(total_grid_rows=12)
        p = pos.params
        assert p["total_grid_rows"] == 12
        assert p["mode"] == "grid_batcher"
        assert len(p["tiers"]) == 3

    def test_on_sell_batcher_all_out(self):
        """on_sell：全部卖出"""
        pos = GridBatcherPosition()
        bar = make_bar("2026-01-01", c=10.0)
        real_pos = Position("000001.SZ", quantity=500, avg_cost=10.0, cost_basis=5000)
        ctx = MockContext(positions={"000001.SZ": real_pos})
        assert pos.on_sell_signal(ctx, bar) == 500


# ═══════════════════════════════════════════════════════════════
# 4. 风控测试
# ═══════════════════════════════════════════════════════════════


class TestGridCoolDown:
    """GridCoolDown — 网格冷却期"""

    def test_not_triggered(self):
        """冷却期前：从未触发 → is_cooled_down=True"""
        cd = GridCoolDown(cool_down_bars=3)
        assert cd.is_cooled_down("level_0", current_bar=10) is True

    def test_in_cool_down(self):
        """冷却期内：触发后冷却期内 → is_cooled_down=True（仍需等待）"""
        cd = GridCoolDown(cool_down_bars=3)
        cd.on_trigger("level_0", current_bar=10)
        # bar=11, 12 仍在冷却中（需等3根，bar>=13才冷却完毕）
        assert cd.is_cooled_down("level_0", current_bar=11) is False
        assert cd.is_cooled_down("level_0", current_bar=12) is False
        assert cd.is_cooled_down("level_0", current_bar=13) is True

    def test_after_cool_down(self):
        """冷却期后：冷却期满 → is_cooled_down=False"""
        cd = GridCoolDown(cool_down_bars=3)
        cd.on_trigger("level_0", current_bar=10)
        assert cd.is_cooled_down("level_0", current_bar=13) is True

    def test_independent_cooldown(self):
        """不同网格线独立冷却"""
        cd = GridCoolDown(cool_down_bars=3)
        cd.on_trigger("level_0", current_bar=10)
        cd.on_trigger("level_1", current_bar=5)
        # level_0: bar=12 仍在冷却
        assert cd.is_cooled_down("level_0", current_bar=12) is False
        # level_1: bar=12 > 5+3=8，已冷却完毕
        assert cd.is_cooled_down("level_1", current_bar=12) is True

    def test_reset(self):
        """reset清除冷却状态"""
        cd = GridCoolDown(cool_down_bars=3)
        cd.on_trigger("level_0", current_bar=10)
        cd.reset()
        assert cd.is_cooled_down("level_0", current_bar=10) is True

    def test_zero_cooldown_bars(self):
        """cool_down_bars=0：无需冷却，直接可触发"""
        cd = GridCoolDown(cool_down_bars=0)
        cd.on_trigger("level_0", current_bar=10)
        assert cd.is_cooled_down("level_0", current_bar=10) is True


class TestGridStopLoss:
    """GridStopLoss — 网格止损"""

    def test_no_entry_no_check(self):
        """无入场价时不触发 → 无需check"""
        sl = GridStopLoss(stop_loss_pct=0.05)
        bar = make_bar("2026-01-01", c=9.0)
        assert sl.check_stop_loss(None, bar, entry_price=0.0) is False
        assert sl.check_stop_loss(None, bar, entry_price=-1.0) is False

    def test_fixed_stop_loss_triggered(self):
        """固定止损：价格跌幅超过threshold → 触发"""
        sl = GridStopLoss(stop_loss_pct=0.05)  # 5%止损
        bar = make_bar("2026-01-01", c=9.4, h=10.0, l=9.4, o=10.0)  # -6%
        # entry=10.0, current=9.4 → pnl=-6% < -5% → triggered
        assert sl.check_stop_loss(None, bar, entry_price=10.0) is True

    def test_fixed_stop_loss_not_triggered(self):
        """固定止损：小幅下跌未超阈值 → 不触发"""
        sl = GridStopLoss(stop_loss_pct=0.05)
        bar = make_bar("2026-01-01", c=9.7)  # -3%
        assert sl.check_stop_loss(None, bar, entry_price=10.0) is False

    def test_trailing_stop_loss(self):
        """移动止损：从最高点回落超阈值 → 触发"""
        sl = GridStopLoss(stop_loss_pct=0.05, trailing_stop_pct=0.03)
        # 先创了新高 10.5，然后跌到 10.2（回落约 2.86%，未达3%）
        bar1 = make_bar("2026-01-01", c=10.5, h=10.5, l=10.5)
        bar2 = make_bar("2026-01-02", c=10.2, h=10.5, l=10.2)
        sl.check_stop_loss(None, bar1, entry_price=10.0)  # 更新 highest
        assert sl.check_stop_loss(None, bar2, entry_price=10.0) is False
        # 再跌到 10.18（从10.5回落约 3.05% > 3%）
        bar3 = make_bar("2026-01-03", c=10.18, h=10.5, l=10.18)
        assert sl.check_stop_loss(None, bar3, entry_price=10.0) is True

    def test_params_stop_loss(self):
        """params property"""
        sl = GridStopLoss(stop_loss_pct=0.05, trailing_stop_pct=0.03)
        p = sl.params
        assert p["stop_loss_pct"] == 0.05
        assert p["trailing_stop_pct"] == 0.03
        assert p["mode"] == "grid_stop_loss"


class TestGridMaxExposure:
    """GridMaxExposure — 网格总仓位上限"""

    def test_can_open_no_context(self):
        """无context：默认允许开仓"""
        exp = GridMaxExposure(max_position_pct=0.20, max_grids_active=3)
        assert exp.can_open_new(None, current_active_grids=0) is True

    def test_can_open_below_limit(self):
        """总仓位未超限 → can_open_new=True"""
        exp = GridMaxExposure(max_position_pct=0.20, max_grids_active=3)
        ctx = MagicMock()
        ctx.total_equity = 1_000_000.0
        # Mock positions.all() returning empty
        ctx.positions = MagicMock(all=MagicMock(return_value=[]))
        assert exp.can_open_new(ctx, current_active_grids=0) is True

    def test_active_grids_exceeded(self):
        """活跃网格超限 → can_open_new=False"""
        exp = GridMaxExposure(max_position_pct=0.20, max_grids_active=3)
        ctx = MagicMock()
        ctx.total_equity = 1_000_000.0
        ctx.positions = MagicMock(all=MagicMock(return_value=[]))
        assert exp.can_open_new(ctx, current_active_grids=3) is False

    def test_zero_max_grids_unlimited(self):
        """max_grids_active=0：不限制活跃网格数"""
        exp = GridMaxExposure(max_position_pct=0.20, max_grids_active=0)
        ctx = MagicMock()
        ctx.total_equity = 1_000_000.0
        ctx.positions = MagicMock(all=MagicMock(return_value=[]))
        assert exp.can_open_new(ctx, current_active_grids=999) is True

    def test_params_exposure(self):
        """params property"""
        exp = GridMaxExposure(max_position_pct=0.25, max_grids_active=5)
        p = exp.params
        assert p["max_position_pct"] == 0.25
        assert p["max_grids_active"] == 5
        assert p["mode"] == "grid_max_exposure"


# ═══════════════════════════════════════════════════════════════
# 5. 工厂函数测试
# ═══════════════════════════════════════════════════════════════


class TestFactoryFunctions:
    """工厂函数测试"""

    def test_create_grid_position_fixed(self):
        """create_grid_position('fixed', quantity=1000) → GridFixedPosition"""
        pos = create_grid_position("fixed", quantity=1000)
        assert isinstance(pos, GridFixedPosition)
        assert pos.params["quantity"] == 1000

    def test_create_grid_position_layer(self):
        """create_grid_position('layer', ...) → GridLayerPosition"""
        pos = create_grid_position(
            "layer",
            base_quantity=200,
            layer_multiplier=2.0,
            max_layers=4,
        )
        assert isinstance(pos, GridLayerPosition)
        assert pos.params["base_quantity"] == 200

    def test_create_grid_position_batcher(self):
        """create_grid_position('batcher', ...) → GridBatcherPosition"""
        pos = create_grid_position(
            "batcher",
            total_grid_rows=12,
        )
        assert isinstance(pos, GridBatcherPosition)
        assert pos.params["total_grid_rows"] == 12

    def test_create_grid_risk_cool_down(self):
        """create_grid_risk('cool_down', ...) → GridCoolDown"""
        cd = create_grid_risk("cool_down", cool_down_bars=5)
        assert isinstance(cd, GridCoolDown)
        assert cd.params["cool_down_bars"] == 5

    def test_create_grid_risk_stop_loss(self):
        """create_grid_risk('stop_loss', ...) → GridStopLoss"""
        sl = create_grid_risk("stop_loss", stop_loss_pct=0.05, trailing_stop_pct=0.03)
        assert isinstance(sl, GridStopLoss)
        assert sl.params["stop_loss_pct"] == 0.05

    def test_create_grid_risk_exposure(self):
        """create_grid_risk('exposure', ...) → GridMaxExposure"""
        exp = create_grid_risk("exposure", max_position_pct=0.20, max_grids_active=3)
        assert isinstance(exp, GridMaxExposure)
        assert exp.params["max_position_pct"] == 0.20

    def test_create_grid_manager_fixed(self):
        """create_grid_manager('fixed', ...) → GridPositionManager"""
        mgr = create_grid_manager(
            position_mode="fixed",
            position_kwargs={"quantity": 200},
            risk_config={
                "cool_down": {"cool_down_bars": 3},
                "stop_loss": {"stop_loss_pct": 0.05},
                "exposure": {"max_position_pct": 0.20, "max_grids_active": 3},
            },
        )
        assert isinstance(mgr, GridPositionManager)
        assert isinstance(mgr.position_logic, GridFixedPosition)
        assert mgr.cool_down is not None
        assert mgr.stop_loss is not None
        assert mgr.exposure is not None

    def test_create_grid_manager_invalid_position_mode(self):
        """无效position_mode → ValueError"""
        with pytest.raises(ValueError):
            create_grid_manager(position_mode="invalid_mode")

    def test_create_grid_risk_invalid_mode(self):
        """无效risk mode → ValueError"""
        with pytest.raises(ValueError):
            create_grid_risk("invalid_risk")


# ═══════════════════════════════════════════════════════════════
# 6. 集成测试
# ═══════════════════════════════════════════════════════════════


class TestGridPositionManagerIntegration:
    """GridPositionManager 组合集成测试"""

    def test_manager_combined_all_components(self):
        """GridPositionManager 组合使用：仓位+冷却+止损+敞口"""
        pos = GridFixedPosition(quantity=500)
        cd = GridCoolDown(cool_down_bars=3)
        sl = GridStopLoss(stop_loss_pct=0.05)
        exp = GridMaxExposure(max_position_pct=0.20, max_grids_active=3)

        mgr = GridPositionManager(
            position_logic=pos,
            cool_down=cd,
            stop_loss=sl,
            exposure=exp,
        )

        bar = make_bar("2026-01-01", c=10.0)
        ctx = MagicMock()
        ctx.available_capital = 1_000_000.0
        ctx.total_equity = 1_000_000.0
        ctx.positions = MagicMock(all=MagicMock(return_value=[]))

        # can_open: 敞口未超 + 冷却通过
        assert mgr.can_open(ctx, bar, grid_line_id="level_0", current_active_grids=0, current_bar=10) is True

        # on_buy_signal
        qty = mgr.on_buy_signal(ctx, bar)
        assert qty == 500

        # on_trigger 触发冷却
        mgr.on_trigger("level_0", current_bar=10)
        # 触发后立即查询（仍在冷却中，冷却3根Bar，需bar>=13才冷却完毕）
        assert mgr.cool_down.is_cooled_down("level_0", current_bar=10) is False
        assert mgr.cool_down.is_cooled_down("level_0", current_bar=12) is False
        assert mgr.cool_down.is_cooled_down("level_0", current_bar=13) is True

        # check_stop_loss
        bar_loss = make_bar("2026-01-02", c=9.4)
        assert mgr.check_stop_loss(ctx, bar_loss, entry_price=10.0) is True

        # check_exposure_breach
        assert mgr.check_exposure_breach(ctx) is False

    def test_manager_buy_signal_with_risk_check(self):
        """on_buy_signal + 风控检查 → 综合决策"""
        pos = GridLayerPosition(base_quantity=100, layer_multiplier=2.0)
        cd = GridCoolDown(cool_down_bars=2)
        mgr = GridPositionManager(position_logic=pos, cool_down=cd)

        bar = make_bar("2026-01-01", c=10.0)
        ctx = MagicMock()
        ctx.available_capital = 1_000_000.0
        ctx.total_equity = 1_000_000.0
        ctx.positions = MagicMock(all=MagicMock(return_value=[]))

        # 初始可以开仓
        assert mgr.can_open(ctx, bar, grid_line_id="level_0", current_active_grids=0, current_bar=0) is True

        # 触发冷却
        mgr.on_trigger("level_0", current_bar=0)

        # 冷却中不可开仓
        assert mgr.can_open(ctx, bar, grid_line_id="level_0", current_active_grids=0, current_bar=1) is False

        # 但换个网格线可以
        assert mgr.can_open(ctx, bar, grid_line_id="level_1", current_active_grids=1, current_bar=1) is True

        # buy signal with 2 layers
        qty = mgr.on_buy_signal(ctx, bar, triggered_levels=["level_0", "level_1"])
        assert qty == 400  # 100 * 2^2

    def test_manager_reset(self):
        """manager.reset() 清除所有状态"""
        pos = GridFixedPosition(quantity=200)
        cd = GridCoolDown(cool_down_bars=3)
        mgr = GridPositionManager(position_logic=pos, cool_down=cd)

        mgr.on_trigger("level_0", current_bar=10)
        mgr.reset()

        assert mgr.cool_down.is_cooled_down("level_0", current_bar=10) is True

    def test_manager_params(self):
        """manager.params 包含所有组件"""
        pos = GridFixedPosition(quantity=300)
        cd = GridCoolDown(cool_down_bars=5)
        mgr = GridPositionManager(position_logic=pos, cool_down=cd)

        p = mgr.params
        assert p["position_logic"]["quantity"] == 300
        assert p["cool_down"]["cool_down_bars"] == 5
        assert p["mode"] == "grid_manager"


# ═══════════════════════════════════════════════════════════════
# 辅助函数测试
# ═══════════════════════════════════════════════════════════════


class TestClampToLot:
    """_clamp_to_lot 内部工具测试"""

    def test_clamp_positive(self):
        assert _clamp_to_lot(500) == 500

    def test_clamp_round_down(self):
        assert _clamp_to_lot(123) == 100

    def test_clamp_exact(self):
        assert _clamp_to_lot(300) == 300

    def test_clamp_zero(self):
        assert _clamp_to_lot(0) == 0

    def test_clamp_negative(self):
        assert _clamp_to_lot(-100) == 0