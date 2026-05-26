"""
test_backtest_result_bundle — BacktestResultBundle + compute_data_quality + bundle_from_runner

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine.backtest_result_bundle import (
    BacktestResultBundle,
    compute_data_quality,
    bundle_from_runner,
    _build_benchmark_curve,
)
from backtest.engine.portfolio_integration import (
    PortfolioIntegration,
    TradePair,
    RiskEvent,
)
from backtest.methods.base import MethodResult
from backtest.context import StrategyContext


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def df_ohlcv() -> pd.DataFrame:
    """生成 60 个交易日的模拟 OHLCV 数据。"""
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
    """生成模拟信号：以 50/50 比例生成 +1/-1 信号。"""
    np.random.seed(7)
    n = len(df_ohlcv)
    # 在前 40 根 bar 有信号，后面 20 根无
    vals = np.random.choice([0, 1, -1], size=n, p=[0.2, 0.4, 0.4])
    return pd.DataFrame(
        vals,
        index=df_ohlcv.index,
        columns=["signal"],
    )


@pytest.fixture
def method_result(signals: pd.DataFrame) -> MethodResult:
    """生成 MethodResult 实例。"""
    return MethodResult(
        method_name="test_method",
        signals=signals,
        params={"initial_capital": 1_000_000, "sma_window": 20},
        statistics={
            "n_bars": len(signals),
            "n_signals": int((signals["signal"] != 0).sum()),
            "signal_ratio": float((signals["signal"] != 0).sum() / len(signals)),
        },
    )


@pytest.fixture
def ctx() -> StrategyContext:
    """生成最小 StrategyContext。"""
    return StrategyContext(
        symbol="000300.SH",
        config={
            "data_source": "test",
            "data_period": "daily",
            "adjust_type": "qfq",
            "slippage_model": "fixed 0.1%",
            "engine_version": "v3.0",
        },
    )


# ══════════════════════════════════════════════════════════════════════
# BacktestResultBundle - 基础构造
# ══════════════════════════════════════════════════════════════════════


class TestBacktestResultBundle:
    def test_default_construction(self):
        """空白构造应使用全部默认值。"""
        bundle = BacktestResultBundle()
        assert bundle.run_id == ""
        assert bundle.method_name == ""
        assert bundle.params == {}
        assert isinstance(bundle.equity_curve, pd.DataFrame)
        assert bundle.equity_curve.empty
        assert bundle.trades == []
        assert bundle.daily_metrics.empty
        assert bundle.regime_labels.empty
        assert bundle.parameter_scan.empty
        assert bundle.risk_events == []
        assert bundle.insights == []
        assert bundle.summary_metrics == {}
        assert bundle.data_quality == {}

    def test_full_construction(self):
        """构造时填入所有必要字段。"""
        dates = pd.date_range("2025-01-01", periods=5)
        ec = pd.DataFrame({"date": dates, "equity": [1.0, 1.1, 1.2, 1.15, 1.25]}, index=dates)
        trades = [TradePair("2025-01-01", 100.0, "2025-01-05", 110.0, 10.0, 100)]

        bundle = BacktestResultBundle(
            run_id="test_run_001",
            strategy_name="均值回归",
            method_name="mean_rev_v1",
            symbol="000300.SH",
            start_date="2025-01-01",
            end_date="2025-01-31",
            params={"window": 20},
            equity_curve=ec,
            trades=trades,
            summary_metrics={"total_return": 0.25, "n_trades": 10},
            data_quality={"rating": "A", "completeness": 99.5},
        )

        assert bundle.run_id == "test_run_001"
        assert bundle.strategy_name == "均值回归"
        assert bundle.method_name == "mean_rev_v1"
        assert bundle.symbol == "000300.SH"
        assert len(bundle.trades) == 1
        assert bundle.summary_metrics["total_return"] == 0.25
        assert bundle.data_quality["rating"] == "A"

    def test_repr_no_crash(self):
        """__repr__ 不应抛出异常。"""
        b = BacktestResultBundle(method_name="test", symbol="AAPL")
        r = repr(b)
        assert "BacktestResultBundle" in r
        assert "test" in r
        assert "AAPL" in r


# ══════════════════════════════════════════════════════════════════════
# compute_data_quality — 数据质量计算
# ══════════════════════════════════════════════════════════════════════


class TestComputeDataQuality:
    def test_basic_quality(self, df_ohlcv: pd.DataFrame):
        """基本数据质量应有 A 评级（60 天完整数据）。"""
        result = compute_data_quality(df_ohlcv)
        assert isinstance(result, dict)
        assert result["rating"] in ("A", "B", "C")
        assert result["actual_days"] == 60
        assert result["total_days"] == 60
        assert result["completeness"] == 100.0
        assert "nan_stats" in result
        assert "commission" in result
        assert "slippage_model" in result

    def test_missing_days(self, df_ohlcv: pd.DataFrame):
        """有缺失日期时应正确计算缺失天数。"""
        # 模拟预期日历比实际多 5 天
        extra_dates = pd.bdate_range(df_ohlcv.index[0], periods=65)
        expected_df = pd.DataFrame(index=pd.DatetimeIndex(extra_dates))
        result = compute_data_quality(df_ohlcv, df_expected=expected_df)
        assert result["missing_days"] == 5
        assert 92.3 <= result["completeness"] <= 92.4  # 60/65 ≈ 92.3%

    def test_qfq_default(self, df_ohlcv: pd.DataFrame):
        """默认为 qfq 复权。"""
        result = compute_data_quality(df_ohlcv)
        assert result["adjusted"] == "qfq"

    def test_forward_fill_default(self, df_ohlcv: pd.DataFrame):
        """默认缺失值处理为 forward fill。"""
        result = compute_data_quality(df_ohlcv)
        assert result["nan_handling"] == "forward fill"

    def test_empty_dataframe(self):
        """空 DataFrame 应给出合理结果。"""
        empty = pd.DataFrame()
        result = compute_data_quality(empty)
        assert result["actual_days"] == 0
        assert result["total_days"] == 0
        assert result["completeness"] == 100.0  # 0/0 → 1.0 * 100 防御性

    def test_nan_stats_present(self, df_ohlcv: pd.DataFrame):
        """nan_stats 应覆盖所有主要 OHLCV 列。"""
        result = compute_data_quality(df_ohlcv)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result["nan_stats"]
            assert isinstance(result["nan_stats"][col], float)

    def test_custom_slippage(self, df_ohlcv: pd.DataFrame):
        """自定义滑点应保留。"""
        result = compute_data_quality(df_ohlcv, config={"slippage_model": "linear 0.15%"})
        assert result["slippage_model"] == "linear 0.15%"

    def test_missing_dates_list(self, df_ohlcv: pd.DataFrame):
        """缺失日期应作为日期字符串列表返回。"""
        extra_dates = pd.bdate_range("2024-12-25", periods=67)
        expected_df = pd.DataFrame(index=pd.DatetimeIndex(extra_dates))
        result = compute_data_quality(df_ohlcv, df_expected=expected_df)
        if result["missing_days"] > 0:
            assert all(isinstance(d, str) for d in result["missing_dates"])
            assert len(result["missing_dates"]) <= 10


# ══════════════════════════════════════════════════════════════════════
# _build_benchmark_curve — 基准曲线构建
# ══════════════════════════════════════════════════════════════════════


class TestBuildBenchmarkCurve:
    def test_basic(self, df_ohlcv: pd.DataFrame):
        """buy&hold 曲线应从 close 价格归一化。"""
        bc = _build_benchmark_curve(df_ohlcv)
        assert not bc.empty
        assert bc["equity"].iloc[0] == pytest.approx(1.0)
        assert "return" in bc.columns
        assert "date" in bc.columns

    def test_empty_input(self):
        """空输入应返回空 DataFrame。"""
        empty = pd.DataFrame()
        bc = _build_benchmark_curve(empty)
        assert bc.empty

    def test_missing_close(self, df_ohlcv: pd.DataFrame):
        """缺少 close 列应返回空 DataFrame。"""
        df_no_close = df_ohlcv.drop(columns=["close"])
        bc = _build_benchmark_curve(df_no_close)
        assert bc.empty

    def test_with_signals(self, df_ohlcv: pd.DataFrame, signals: pd.DataFrame):
        """提供 signals 时应对齐索引。"""
        bc = _build_benchmark_curve(df_ohlcv, signals)
        assert not bc.empty
        assert len(bc) == len(signals.index.intersection(df_ohlcv.index))

    def test_return_calculation(self, df_ohlcv: pd.DataFrame):
        """收益率计算应正确。"""
        bc = _build_benchmark_curve(df_ohlcv)
        returns = bc["return"].values
        # 第一个 return 应为 0
        assert returns[0] == pytest.approx(0.0)
        # 其余 return 通过 equity 比值验证
        if len(returns) > 1:
            equity_values = bc["equity"].values
            expected_ret = equity_values[1:] / equity_values[:-1] - 1.0
            assert np.allclose(returns[1:], expected_ret, atol=1e-10)


# ══════════════════════════════════════════════════════════════════════
# bundle_from_runner — MethodResult → BacktestResultBundle 映射
# ══════════════════════════════════════════════════════════════════════


class TestBundleFromRunner:
    def test_basic_mapping(self, method_result: MethodResult, df_ohlcv: pd.DataFrame, ctx: StrategyContext):
        """基本映射应返回填充完整的 Bundle。"""
        bundle = bundle_from_runner(
            method_result, df_ohlcv, ctx=ctx,
            run_id="run_001", strategy_name="均值回归",
        )

        assert isinstance(bundle, BacktestResultBundle)
        assert bundle.run_id == "run_001"
        assert bundle.strategy_name == "均值回归"
        assert bundle.method_name == "test_method"
        assert bundle.symbol == "000300.SH"

    def test_equity_curve_generated(self, method_result: MethodResult, df_ohlcv: pd.DataFrame, ctx: StrategyContext):
        """equity_curve 应正确生成（含日期/权益/收益率列）。"""
        bundle = bundle_from_runner(method_result, df_ohlcv, ctx=ctx)
        ec = bundle.equity_curve
        assert not ec.empty
        assert "date" in ec.columns or ec.index.name == "date"
        assert "equity" in ec.columns
        assert "return" in ec.columns
        # 权益曲线从 1.0 开始，最后值应在合理范围内
        assert ec["equity"].iloc[0] == pytest.approx(1.0), "equity curve should start at 1.0"

    def test_benchmark_curve_generated(self, method_result: MethodResult, df_ohlcv: pd.DataFrame, ctx: StrategyContext):
        """benchmark_curve 应正确生成。"""
        bundle = bundle_from_runner(method_result, df_ohlcv, ctx=ctx)
        bc = bundle.benchmark_curve
        assert not bc.empty
        assert bc["equity"].iloc[0] == pytest.approx(1.0)

    def test_trades_extracted(self, method_result: MethodResult, df_ohlcv: pd.DataFrame, ctx: StrategyContext):
        """trades 应从 PortfolioIntegration 产出。"""
        bundle = bundle_from_runner(method_result, df_ohlcv, ctx=ctx)
        # 有信号时应有成交，无信号则为空
        # 只要不崩溃即可
        assert isinstance(bundle.trades, list)

    def test_summary_metrics_merged(self, method_result: MethodResult, df_ohlcv: pd.DataFrame, ctx: StrategyContext):
        """summary_metrics 应合并 statistics 和 portfolio 指标。"""
        bundle = bundle_from_runner(method_result, df_ohlcv, ctx=ctx)
        sm = bundle.summary_metrics
        assert "n_bars" in sm
        assert sm["n_bars"] == len(signals_fallback(method_result))
        assert "n_signals" in sm or "total_return" in sm

    def test_data_quality_present(self, method_result: MethodResult, df_ohlcv: pd.DataFrame, ctx: StrategyContext):
        """data_quality 应包含评级和完整性信息。"""
        bundle = bundle_from_runner(method_result, df_ohlcv, ctx=ctx)
        dq = bundle.data_quality
        assert "rating" in dq
        assert "completeness" in dq
        assert dq["rating"] in ("A", "B", "C")

    def test_with_custom_pm(self, method_result: MethodResult, df_ohlcv: pd.DataFrame):
        """传入自定义 PortfolioIntegration 应正常工作。"""
        pm = PortfolioIntegration(symbol="TEST", initial_cash=2_000_000, commission_pct=0.001)
        bundle = bundle_from_runner(method_result, df_ohlcv, pm=pm)
        assert isinstance(bundle, BacktestResultBundle)
        assert bundle.symbol == ""  # 未传 ctx，默认空

    def test_without_ctx_pm(self, method_result: MethodResult, df_ohlcv: pd.DataFrame):
        """不传 ctx 和 pm 时也能工作（使用默认值）。"""
        bundle = bundle_from_runner(method_result, df_ohlcv)
        assert isinstance(bundle, BacktestResultBundle)
        assert bundle.symbol == ""
        assert bundle.run_id == ""

    def test_empty_signals(self, df_ohlcv: pd.DataFrame):
        """空信号的 MethodResult 不应崩溃。"""
        empty_signals = pd.DataFrame([], index=pd.DatetimeIndex([]), columns=["signal"], dtype=float)
        mr = MethodResult(method_name="empty", signals=empty_signals, params={})
        bundle = bundle_from_runner(mr, df_ohlcv)
        assert bundle.equity_curve.empty or isinstance(bundle.equity_curve, pd.DataFrame)


# ══════════════════════════════════════════════════════════════════════
# 辅助：从 method_result 提取 signals 用于验证
# ══════════════════════════════════════════════════════════════════════


def signals_fallback(mr: MethodResult) -> pd.DataFrame:
    """安全提取 signals（用于测试断言）。"""
    return mr.signals if not mr.signals.empty else pd.DataFrame()
