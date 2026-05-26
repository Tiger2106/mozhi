"""
test_run_grid_benchmark.py — P0-12 + P0-13 网格回测基准计算测试

覆盖：
1. test_backtest_result_includes_bh_kpi  — 正常情况，验证 buy_hold_kpi 存在
2. test_backtest_result_bh_fails_gracefully — 基准计算异常，验证 buy_hold_kpi=None

约束：
- 全部 mock，不调网络/数据库
- 不破坏已有 run_grid 功能

Author: 墨衡
Created: 2026-05-16
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from backtest.backtest_engine import (
    BacktestConfig,
    BacktestResult,
    Bar,
)
from backtest.strategies.run_grid import (
    GridRunnerConfig,
    GridRunnerResult,
    run_grid_backtest,
)
from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_bars() -> List[Bar]:
    """返回 60 条假 K 线（60 个交易日约 3 个月数据）。"""
    bars: List[Bar] = []
    for i in range(60):
        base_close = 100.0 + i * 0.2
        bars.append(
            Bar(
                date=f"202601{10 + i:02d}" if i < 20 else f"202602{10 + i - 20:02d}",
                symbol="000001.SZ",
                open=base_close - 0.1,
                high=base_close + 0.3,
                low=base_close - 0.3,
                close=base_close,
                volume=1_000_000,
                vwap=base_close,
            )
        )
    return bars


@pytest.fixture
def mock_backtest_result() -> BacktestResult:
    """返回一个基本的回测结果实例。"""
    cfg = BacktestConfig(
        start_date="20260101",
        end_date="20260331",
        initial_capital=1_000_000.0,
    )
    return BacktestResult(
        config=cfg,
        start_date="20260110",
        end_date="20260330",
        total_bars=60,
        trades=[],
        equity_curve=[{"date": "20260110", "equity": 1_000_000}],
        snapshots=[],
        metrics={
            "total_return_pct": 5.2,
            "annual_return_pct": 0.052,
            "sharpe_ratio": 1.2,
            "max_drawdown_pct": -2.1,
        },
        buy_hold_kpi=None,
    )


@pytest.fixture
def mock_bh_kpi() -> dict:
    """模拟的买入持有 KPI。"""
    return {
        "symbol": "000001",
        "name": "000001.SZ",
        "start_date": "2026-01-10",
        "end_date": "2026-03-30",
        "start_close": 100.0,
        "end_close": 112.0,
        "total_return_pct": 12.0,
        "total_return": 0.12,
        "annualized_return_pct": 48.0,
        "max_drawdown_pct": -3.5,
        "max_drawdown_duration": 5,
        "win_rate": 0.55,
        "calmar_ratio": 13.71,
        "trading_days": 60,
    }


@pytest.fixture
def mock_config() -> GridRunnerConfig:
    """测试用回测配置。"""
    from backtest.strategies.grid_position import (
        GridPositionManager,
        GridFixedPosition,
        GridCoolDown,
    )

    signal = StaticGridSignal(
        grid_config=GridConfig(
            lower_bound=95.0,
            upper_bound=105.0,
            n_levels=10,
            grid_type="arithmetic",
        )
    )
    position = GridPositionManager(
        position_logic=GridFixedPosition(quantity=100),
        cool_down=GridCoolDown(cool_down_bars=3),
    )
    return GridRunnerConfig(
        symbol="000001.SZ",
        start_date="20260110",
        end_date="20260330",
        signal=signal,
        position=position,
        tag="test_benchmark",
    )


# ═══════════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════════


def test_backtest_result_includes_bh_kpi(
    mock_config: GridRunnerConfig,
    mock_bars: List[Bar],
    mock_bh_kpi: dict,
) -> None:
    """基准计算正常时，buy_hold_kpi 应填充到 BacktestResult 并透传到 GridRunnerResult。"""
    with (
        patch(
            "backtest.strategies.run_grid.load_stock_bars",
            return_value=mock_bars,
        ),
        patch(
            "backtest.strategies.run_grid.BacktestEngine.run",
        ) as mock_engine_run,
        patch(
            "backtest.strategies.run_grid.calc_buy_hold_return",
            return_value=mock_bh_kpi,
        ),
    ):
        # 构造一个 mock BacktestResult（buy_hold_kpi 将由 our code 填充）
        base_result = BacktestResult(
            config=BacktestConfig(
                start_date="20260101",
                end_date="20260331",
                initial_capital=1_000_000.0,
            ),
            start_date="20260110",
            end_date="20260330",
            total_bars=len(mock_bars),
            trades=[],
            equity_curve=[{"date": "20260110", "equity": 1_000_000}],
            snapshots=[],
            metrics={
                "total_return_pct": 5.2,
                "annual_return_pct": 0.052,
                "sharpe_ratio": 1.2,
            },
            buy_hold_kpi=None,
        )
        mock_engine_run.return_value = base_result

        result = run_grid_backtest(mock_config)

        # GridRunnerResult 应成功
        assert result.status == "SUCCESS", f"回测应成功，实际: {result.status}"
        assert result.backtest_result is not None

        # buy_hold_kpi 应存在且等于 mock 值
        bh = result.backtest_result.buy_hold_kpi
        assert bh is not None, "buy_hold_kpi 不应为 None"
        assert bh["symbol"] == "000001"
        assert bh["total_return_pct"] == 12.0
        assert bh["trading_days"] == 60

        # to_dict 中应包含 buy_hold_kpi
        d = result.backtest_result.to_dict()
        assert "buy_hold_kpi" in d
        assert d["buy_hold_kpi"] == mock_bh_kpi


def test_backtest_result_bh_fails_gracefully(
    mock_config: GridRunnerConfig,
    mock_bars: List[Bar],
    mock_bh_kpi: dict,
) -> None:
    """基准计算异常时，buy_hold_kpi 应为 None，回测本身不受影响。"""
    with (
        patch(
            "backtest.strategies.run_grid.load_stock_bars",
            return_value=mock_bars,
        ),
        patch(
            "backtest.strategies.run_grid.BacktestEngine.run",
        ) as mock_engine_run,
        patch(
            "backtest.strategies.run_grid.calc_buy_hold_return",
            side_effect=ValueError("网络异常"),  # 模拟基准计算失败
        ),
    ):
        base_result = BacktestResult(
            config=BacktestConfig(
                start_date="20260101",
                end_date="20260331",
                initial_capital=1_000_000.0,
            ),
            start_date="20260110",
            end_date="20260330",
            total_bars=len(mock_bars),
            trades=[],
            equity_curve=[{"date": "20260110", "equity": 1_000_000}],
            snapshots=[],
            metrics={
                "total_return_pct": 5.2,
                "annual_return_pct": 0.052,
                "sharpe_ratio": 1.2,
            },
            buy_hold_kpi=None,
        )
        mock_engine_run.return_value = base_result

        result = run_grid_backtest(mock_config)

        # 回测本身应成功（基准失败不影响）
        assert result.status == "SUCCESS", f"回测应仍然成功，实际: {result.status}"
        assert result.backtest_result is not None

        # buy_hold_kpi 应为 None
        assert result.backtest_result.buy_hold_kpi is None, \
            "基准计算失败时 buy_hold_kpi 应为 None"

        # to_dict 中应包含 buy_hold_kpi（值为 None）
        d = result.backtest_result.to_dict()
        assert "buy_hold_kpi" in d
        assert d["buy_hold_kpi"] is None
