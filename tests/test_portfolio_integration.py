"""
test_portfolio_integration — PortfolioIntegration

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine.portfolio_integration import (
    PortfolioIntegration,
    TradePair,
    RiskEvent,
)


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def df_ohlcv() -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.bdate_range("2025-01-01", periods=60)
    n = len(dates)
    close = 100 * (1 + np.cumsum(np.random.randn(n) * 0.01))
    open_ = close * (1 + np.random.randn(n) * 0.002)
    high = np.maximum(open_, close) * (1 + np.abs(np.random.randn(n)) * 0.005)
    low = np.minimum(open_, close) * (1 - np.abs(np.random.randn(n)) * 0.005)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.random.randint(1_000_000, 10_000_000, size=n),
        },
        index=pd.DatetimeIndex(dates, name="date"),
    )


@pytest.fixture
def signals(df_ohlcv: pd.DataFrame) -> pd.DataFrame:
    np.random.seed(7)
    n = len(df_ohlcv)
    vals = np.random.choice([0, 1, -1], size=n, p=[0.2, 0.4, 0.4])
    return pd.DataFrame(vals, index=df_ohlcv.index, columns=["signal"])


@pytest.fixture
def empty_signals(df_ohlcv: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([0] * len(df_ohlcv), index=df_ohlcv.index, columns=["signal"])


# ══════════════════════════════════════════════════════════════════════
# TradePair
# ══════════════════════════════════════════════════════════════════════


class TestTradePair:
    def test_default_construction(self):
        """TradePair 有默认值的字段应返回默认值。"""
        t = TradePair()
        assert t.entry_time == ""
        assert t.entry_price == 0.0
        assert t.exit_time == ""
        assert t.exit_price == 0.0
        assert t.pnl == 0.0
        assert t.qty == 0

    def test_full_construction(self):
        t = TradePair("2025-01-03", 100.0, "2025-01-10", 110.0, 9.95, 1000)
        assert t.entry_price == 100.0
        assert t.exit_price == 110.0
        assert t.pnl == 9.95
        assert t.qty == 1000

    def test_with_kwargs(self):
        t = TradePair(
            entry_time="2025-01-03", entry_price=100.0,
            exit_time="2025-01-10", exit_price=110.0,
            pnl=10.0, qty=100, return_pct=10.0, holding_bars=5
        )
        assert t.return_pct == 10.0
        assert t.holding_bars == 5

    def test_repr(self):
        t = TradePair("2025-01-03", 100.0, "2025-01-10", 110.0, 10.0, 100)
        r = repr(t)
        assert "TradePair" in r


# ══════════════════════════════════════════════════════════════════════
# RiskEvent
# ══════════════════════════════════════════════════════════════════════


class TestRiskEvent:
    def test_default_construction(self):
        """RiskEvent 使用 event_type 而非 type。"""
        e = RiskEvent()
        assert e.event_type == ""
        assert e.timestamp == ""
        assert e.description == ""

    def test_full_construction(self):
        e = RiskEvent(event_type="max_drawdown", timestamp="2025-01-15", description="回撤超过 20%")
        assert e.event_type == "max_drawdown"
        assert e.description == "回撤超过 20%"

    def test_severity_default(self):
        e = RiskEvent()
        assert e.severity == "low"


# ══════════════════════════════════════════════════════════════════════
# PortfolioIntegration — 基础
# ══════════════════════════════════════════════════════════════════════


class TestPortfolioIntegrationInit:
    def test_default_params(self):
        pm = PortfolioIntegration()
        assert pm.symbol == ""  # 默认 symbol 为空字符串
        assert pm.initial_cash == 1_000_000.0
        assert pm.commission_pct == 0.0003
        assert pm.slippage_pct == 0.001

    def test_custom_params(self):
        pm = PortfolioIntegration(symbol="000300.SH", initial_cash=500_000, commission_pct=0.001)
        assert pm.symbol == "000300.SH"
        assert pm.initial_cash == 500_000.0
        assert pm.commission_pct == 0.001


# ══════════════════════════════════════════════════════════════════════
# PortfolioIntegration — run()
# ══════════════════════════════════════════════════════════════════════


class TestPortfolioIntegrationRun:
    def test_run_returns_tuple(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """run() 应返回 (equity_curve, trades, daily_metrics, summary_metrics)。"""
        pm = PortfolioIntegration()
        ec, trades, dm, sm = pm.run(signals, df_ohlcv)
        assert isinstance(ec, pd.DataFrame)
        assert isinstance(trades, list)
        assert isinstance(dm, pd.DataFrame)
        assert isinstance(sm, dict)

    def test_equity_curve_columns(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """equity_curve 应包含 date, equity, return 列。"""
        ec, *_ = pm_run(signals, df_ohlcv)
        assert "date" in ec.columns or ec.index.name == "date"
        assert "equity" in ec.columns
        assert "return" in ec.columns

    def test_equity_curve_length(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """equity_curve 长度应与对齐后的 OHLCV 一致。"""
        ec, *_ = pm_run(signals, df_ohlcv)
        common_idx = signals.index.intersection(df_ohlcv.index)
        assert len(ec) == len(common_idx)

    def test_equity_starts_at_one(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """权益曲线应从 1.0 开始（归一化）。"""
        ec, *_ = pm_run(signals, df_ohlcv)
        assert ec["equity"].iloc[0] == pytest.approx(1.0)

    def test_trades_is_list_of_tradepair(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """trades 应为 TradePair 列表。"""
        _, trades, *_ = pm_run(signals, df_ohlcv)
        assert isinstance(trades, list)
        if trades:
            assert isinstance(trades[0], TradePair)

    def test_empty_signals_no_trades(self, empty_signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """全零信号不应有成交。"""
        _, trades, *_ = pm_run(empty_signals, df_ohlcv)
        assert len(trades) == 0

    def test_summary_metrics_keys(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """summary_metrics 应包含关键指标。"""
        *_ , sm = pm_run(signals, df_ohlcv)
        assert isinstance(sm, dict)
        # 至少应包含这些
        expected = {"total_return", "n_trades", "win_rate", "max_drawdown"}
        assert expected.issubset(sm.keys()), f"missing keys: {expected - set(sm.keys())}"

    def test_total_return_reasonable_range(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """总收益率应在合理范围内。"""
        *_ , sm = pm_run(signals, df_ohlcv)
        assert -0.5 <= sm["total_return"] <= 1.0

    def test_daily_metrics_columns(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """daily_metrics 应包含基本列。"""
        _, _, dm, _ = pm_run(signals, df_ohlcv)
        if not dm.empty:
            assert "return" in dm.columns or "equity" in dm.columns

    def test_run_deterministic(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """相同输入多次运行应产生相同结果。"""
        pm1 = PortfolioIntegration()
        pm2 = PortfolioIntegration()
        ec1, trades1, *_ = pm1.run(signals, df_ohlcv)
        ec2, trades2, *_ = pm2.run(signals, df_ohlcv)
        assert ec1["equity"].equals(ec2["equity"])
        assert len(trades1) == len(trades2)

    def test_run_with_empty_signals_and_data(self):
        """空信号 + 空数据不应崩溃。"""
        pm = PortfolioIntegration()
        empty_signals = pd.DataFrame([], index=pd.DatetimeIndex([]), columns=["signal"], dtype=float)
        empty_ohlcv = pd.DataFrame()
        ec, trades, dm, sm = pm.run(empty_signals, empty_ohlcv)
        assert ec.empty
        assert trades == []
        assert dm.empty
        assert isinstance(sm, dict)

    def test_run_with_nan_close(self, signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
        """close 列有 NaN 时应 graceful 处理（使用前一个有效价格）。"""
        df_bad = df_ohlcv.copy()
        # 把前 3 个 close 设为 NaN
        df_bad.iloc[:3, df_bad.columns.get_loc("close")] = np.nan
        pm = PortfolioIntegration()
        ec, trades, dm, sm = pm.run(signals, df_bad)
        assert not ec.empty
        # equity 曲线从 1.0 开始
        assert ec["equity"].iloc[0] == pytest.approx(1.0)

    def test_commission_reduces_return(self, df_ohlcv: pd.DataFrame):
        """有手续费时收益率应低于无手续费场景（信号非零时）。"""
        np.random.seed(13)
        n = len(df_ohlcv)
        sig = pd.DataFrame(np.random.choice([0, 1, -1], size=n, p=[0.3, 0.35, 0.35]),
                           index=df_ohlcv.index, columns=["signal"])

        pm_no_comm = PortfolioIntegration(commission_pct=0.0)
        pm_comm = PortfolioIntegration(commission_pct=0.005)

        *_ , sm1 = pm_no_comm.run(sig, df_ohlcv)
        *_ , sm2 = pm_comm.run(sig, df_ohlcv)

        # 有手续费时总收益应 ≤ 无手续费（允许小误差）
        assert sm2["total_return"] <= sm1["total_return"] + 0.01

    def test_no_index_intersection(self, df_ohlcv: pd.DataFrame):
        """信号与 OHLCV 索引无交集时应返回空结果。"""
        wrong_dates = pd.bdate_range("2020-01-01", periods=10)
        sig = pd.DataFrame([1] * 10, index=pd.DatetimeIndex(wrong_dates), columns=["signal"])
        pm = PortfolioIntegration()
        ec, trades, dm, sm = pm.run(sig, df_ohlcv)
        assert ec.empty
        assert trades == []


def pm_run(signals: pd.DataFrame, df_ohlcv: pd.DataFrame):
    """简化运行 PortfolioIntegration.run()。"""
    pm = PortfolioIntegration()
    return pm.run(signals, df_ohlcv)
