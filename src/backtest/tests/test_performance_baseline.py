"""
墨枢 - Performance Baseline Tests (P1-37)
记录不同数据量级的回测执行时间，建立性能基线。

测试场景：
  1. 空数据：0 bar  → 目标 < 0.1s
  2. 小量：  10 bar → 目标 < 0.3s
  3. 中量：  100 bar → 目标 < 1.0s
  4. 三组对比输出：不同数据量级时间对比
"""
from __future__ import annotations

import time
from typing import List, Optional

import pytest

from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    Bar,
    OrderRequest,
    Strategy,
)
from backtest.backtest_context import BacktestContext
from backtest.order_executor import OrderSide


# ═══════════════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════════════


def make_bar(date: str, symbol: str = "000001.SZ", close: float = 10.0) -> Bar:
    return Bar(
        date=date,
        symbol=symbol,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=1_000_000,
        vwap=close,
    )


def make_bars(count: int, symbol: str = "000001.SZ", base_price: float = 10.0) -> List[Bar]:
    """生成指定根数的 K 线，每天上涨 1%。"""
    bars = []
    price = base_price
    for i in range(1, count + 1):
        date = f"2026-01-{i:02d}"
        bars.append(make_bar(date, symbol, close=price))
        price *= 1.01
    return bars


class ZeroSignalStrategy:
    """无信号策略（所有 Bar 返回 None）。"""

    def on_start(self, ctx: BacktestContext) -> None:
        pass

    def on_bar(self, ctx: BacktestContext, bar: Bar) -> Optional[List]:
        return None

    def on_end(self, ctx: BacktestContext) -> None:
        pass


# ═══════════════════════════════════════════════════════════════
# 性能基线测试
# ═══════════════════════════════════════════════════════════════


class TestPerformanceBaseline:
    """记录回测引擎在不同数据量级下的执行时间。"""

    def _run_timed(self, bars: List[Bar]) -> tuple:
        """执行一次回测并返回 (elapsed_seconds, result)。"""
        cfg = BacktestConfig(
            start_date="2026-01-01",
            end_date="2026-12-31",
            initial_capital=1_000_000.0,
            fee_rate=0.0003,
            slippage_rate=0.001,
            min_fee=5.0,
        )
        engine = BacktestEngine(config=cfg, strategy=ZeroSignalStrategy())

        t0 = time.perf_counter()
        result = engine.run(bars)
        t1 = time.perf_counter()
        elapsed = t1 - t0
        return elapsed, result

    def test_0_bars_empty_data(self):
        """空数据：0 bar → 目标 < 0.1s"""
        bars: List[Bar] = []
        elapsed, result = self._run_timed(bars)

        print(f"\n[基线] 空数据 (0 bar): {elapsed*1000:.3f} ms")
        assert elapsed < 0.1, f"0 bar 回测耗时 {elapsed:.4f}s，超过 0.1s 上限"
        assert result.total_bars == 0
        assert result.total_trades == 0

    def test_10_bars_small_data(self):
        """小量数据：10 bar → 目标 < 0.3s"""
        bars = make_bars(10)
        elapsed, result = self._run_timed(bars)

        print(f"\n[基线] 小量数据 (10 bar): {elapsed*1000:.3f} ms")
        assert elapsed < 0.3, f"10 bar 回测耗时 {elapsed:.4f}s，超过 0.3s 上限"
        assert result.total_bars == 10

    def test_100_bars_medium_data(self):
        """中量数据：100 bar → 目标 < 1.0s"""
        bars = make_bars(100)
        elapsed, result = self._run_timed(bars)

        print(f"\n[基线] 中量数据 (100 bar): {elapsed*1000:.3f} ms")
        assert elapsed < 1.0, f"100 bar 回测耗时 {elapsed:.4f}s，超过 1.0s 上限"
        assert result.total_bars == 100

    def test_baseline_comparison_table(self):
        """
        三组对比：输出 0 / 10 / 100 bar 的执行时间对比表。
        主目标是记录基线，不做严格断言。
        """
        results: dict = {}

        for count, label in [(0, "0  bar"), (10, "10 bar"), (100, "100 bar")]:
            bars = make_bars(count) if count > 0 else []
            elapsed, result = self._run_timed(bars)
            results[label] = {
                "elapsed_ms": round(elapsed * 1000, 3),
                "elapsed_s": elapsed,
                "bars": result.total_bars,
            }

        print("\n" + "=" * 55)
        print("  墨枢回测引擎 - 性能基线对比表")
        print("=" * 55)
        print(f"  {'数据量级':<12} {'执行时间(ms)':<14} {'执行时间(s)':<12} {'K线数'}")
        print("-" * 55)
        for label, r in results.items():
            print(f"  {label:<12} {r['elapsed_ms']:<14.3f} {r['elapsed_s']:<12.5f} {r['bars']}")
        print("=" * 55)

        # 基线合理性检查（宽松容差，留足够余量）
        assert results["0  bar"]["elapsed_ms"] < 100,   "0 bar 不应超过 100ms"
        assert results["10 bar"]["elapsed_ms"] < 300,   "10 bar 不应超过 300ms"
        assert results["100 bar"]["elapsed_ms"] < 1000,  "100 bar 不应超过 1000ms"

    def test_repeated_runs_consistency(self):
        """
        验证 10 bar 回测多次执行的稳定性（排除系统噪声干扰）。
        宽松检查：所有运行均在 0.3s 以内即可。
        """
        run_times: List[float] = []
        for _ in range(3):
            bars = make_bars(10)
            elapsed, _ = self._run_timed(bars)
            run_times.append(elapsed)

        print(f"\n[稳定性] 10 bar 三次运行: {[f'{t*1000:.3f}ms' for t in run_times]}")
        assert all(t < 0.3 for t in run_times), f"存在超过 0.3s 的运行: {run_times}"
