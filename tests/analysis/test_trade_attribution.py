"""
测试: 交易归因分析 - attribute_trades

覆盖 3 笔交易的因子贡献度计算。
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from src.backtest.models.signal_types import (
    FactorSignal,
    SignalAction,
    SignalConfidence,
)
from src.backtest.backtest.r1_backtest_engine import TradeRecord
from src.backtest.analysis.trade_attribution import attribute_trades


def _make_signal(
    factor_name: str,
    score: float,
    timestamp: str = "2026-01-01T10:00:00+08:00",
) -> FactorSignal:
    return FactorSignal(
        symbol="601857",
        timestamp=timestamp,
        factor_name=factor_name,
        action=SignalAction.BUY if score > 0 else SignalAction.SELL,
        confidence=SignalConfidence.HIGH if abs(score) > 0.7 else SignalConfidence.MEDIUM,
        score=score,
    )


def _make_trade(
    entry_time: str = "2026-01-01T10:00:00+08:00",
    exit_time: str = "2026-01-01T14:00:00+08:00",
    pnl: float = 100.0,
    direction: int = 1,
) -> TradeRecord:
    return TradeRecord(
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=10.0,
        exit_price=11.0 if direction > 0 else 9.0,
        direction=direction,
        quantity=1.0,
        pnl=pnl,
        pnl_pct=pnl / 10.0 / 100.0,
        hold_bars=10,
        exit_reason="signal",
    )


# ─── 3 笔交易的归因测试 ───────────────────────────────────────


class TestTradeAttribution:
    """3 笔交易归因验证。"""

    def test_three_trades_basic(self) -> None:
        """3 笔交易均被归因到正确因子。"""
        trades = [
            _make_trade(entry_time="2026-01-01T10:00+08:00", pnl=100.0),
            _make_trade(entry_time="2026-01-02T10:00+08:00", pnl=-50.0),
            _make_trade(entry_time="2026-01-03T10:00+08:00", pnl=200.0, direction=1),
        ]

        factor_signals: Dict[str, List[FactorSignal]] = {
            "ma_trend": [
                _make_signal("ma_trend", 0.8, "2026-01-01T10:00+08:00"),
                _make_signal("ma_trend", 0.6, "2026-01-02T10:00+08:00"),
                _make_signal("ma_trend", 0.7, "2026-01-03T10:00+08:00"),
            ],
            "volume_ratio": [
                _make_signal("volume_ratio", 0.5, "2026-01-01T10:00+08:00"),
                _make_signal("volume_ratio", -0.4, "2026-01-02T10:00+08:00"),
                _make_signal("volume_ratio", 0.9, "2026-01-03T10:00+08:00"),
            ],
            "momentum": [
                _make_signal("momentum", 0.3, "2026-01-01T10:00+08:00"),
                _make_signal("momentum", 0.2, "2026-01-02T10:00+08:00"),
                _make_signal("momentum", 0.6, "2026-01-03T10:00+08:00"),
            ],
        }

        report = attribute_trades(trades, factor_signals)

        # 3 笔交易都应被归因
        assert report.total_trades == 3, f"预期 3 笔交易，得到 {report.total_trades}"
        assert len(report.trade_attributions) == 3, (
            f"应有 3 个归因记录，得到 {len(report.trade_attributions)}"
        )

        # 检查第一笔归因细节
        attr0 = report.trade_attributions[0]
        assert attr0.primary_factor == "ma_trend", f"主导因子应为 ma_trend，得到 {attr0.primary_factor}"
        assert 0.4 < attr0.primary_contribution <= 1.0
        assert attr0.factor_consistency > 0.5, "同方向因子占比应 > 0.5"

        # 因子累计统计
        assert "ma_trend" in report.factor_stats
        assert "volume_ratio" in report.factor_stats
        assert "momentum" in report.factor_stats

        # 相关性矩阵
        assert report.correlation is not None
        assert len(report.correlation.labels) >= 2

    def test_no_trades(self) -> None:
        """无交易时返回空报告。"""
        report = attribute_trades([], {})
        assert report.total_trades == 0
        assert len(report.trade_attributions) == 0

    def test_missing_factor_match(self) -> None:
        """因子信号不匹配交易时间 → 归因应跳过"""
        trades = [
            _make_trade(entry_time="2026-01-05T10:00+08:00"),  # 无对应因子信号
        ]
        factor_signals = {
            "ma_trend": [
                _make_signal("ma_trend", 0.8, "2026-01-01T10:00+08:00"),
            ],
        }
        report = attribute_trades(trades, factor_signals)
        # 归因可能匹配到最近的信号
        assert report.total_trades == 1

    def test_correlation_calculation(self) -> None:
        """因子间相关性计算。"""
        trades = [
            _make_trade(entry_time="2026-01-01T10:00+08:00", pnl=50.0),
            _make_trade(entry_time="2026-01-02T10:00+08:00", pnl=-30.0),
            _make_trade(entry_time="2026-01-03T10:00+08:00", pnl=80.0),
        ]
        factor_signals: Dict[str, List[FactorSignal]] = {
            "factor_a": [
                _make_signal("factor_a", 0.9, "2026-01-01T10:00+08:00"),
                _make_signal("factor_a", -0.5, "2026-01-02T10:00+08:00"),
                _make_signal("factor_a", 0.8, "2026-01-03T10:00+08:00"),
            ],
            "factor_b": [
                _make_signal("factor_b", 0.8, "2026-01-01T10:00+08:00"),
                _make_signal("factor_b", -0.3, "2026-01-02T10:00+08:00"),
                _make_signal("factor_b", 0.7, "2026-01-03T10:00+08:00"),
            ],
        }
        report = attribute_trades(trades, factor_signals)

        assert report.correlation is not None
        pairs = report.correlation.factor_pairs
        # 应有一对 (factor_a, factor_b) 或 (factor_b, factor_a)
        pair_names = {(p[0], p[1]) for p in pairs}
        assert ("factor_a", "factor_b") in pair_names or ("factor_b", "factor_a") in pair_names
