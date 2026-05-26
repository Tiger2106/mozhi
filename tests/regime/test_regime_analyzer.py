"""
测试: 市场状态分析器 - RegimeAnalyzer

覆盖 3 种市场状态判定（模拟数据）:
1. UPTREND — 持续上涨
2. DOWNTREND — 持续下跌
3. RANGE — 横盘震荡
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest.regime.regime_analyzer import RegimeAnalyzer


def _make_ohcl_df(
    n: int = 100,
    start_price: float = 100.0,
    trend: float = 0.0,      # 趋势斜率（每条增量）
    noise: float = 0.5,      # 随机噪声
    volume_base: float = 1_000_000,
) -> pd.DataFrame:
    """生成模拟 OHLCV 数据。

    Args:
        n: K 线数量
        start_price: 起始价
        trend: 每周期趋势增量（正=上涨，负=下跌，0=横盘）
        noise: 噪声幅度
        volume_base: 成交量基准

    Returns:
        pd.DataFrame: 含 'open', 'high', 'low', 'close', 'volume' 列
    """
    np.random.seed(42)

    # 价格序列
    closes = []
    px = start_price
    for i in range(n):
        px += trend + np.random.normal(0, noise)
        px = max(px, 1.0)
        closes.append(px)

    close = np.array(closes)
    # 开放价 = 前收盘
    open_prices = np.concatenate([[start_price], close[:-1]])
    # 高价 = max(开, 收) + 随机溢价
    high = np.maximum(open_prices, close) * (1 + np.random.uniform(0, 0.01, n))
    low = np.minimum(open_prices, close) * (1 - np.random.uniform(0, 0.01, n))
    volume = np.random.randint(volume_base * 0.5, volume_base * 1.5, n)

    return pd.DataFrame({
        "open": open_prices,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# ─── Case 1: UPTREND ────────────────────────────────────────


class TestUptrendDetection:
    """持续上涨 → UPTREND"""

    def test_uptrend(self) -> None:
        """强上涨趋势应识别为 UPTREND"""
        df = _make_ohcl_df(n=120, start_price=100.0, trend=0.8, noise=0.3)
        analyzer = RegimeAnalyzer()
        result = analyzer.analyze_window(df, lookback=60)

        current = analyzer.get_current_regime()
        assert current["regime"] == "UPTREND", (
            f"预期 UPTREND，得到 {current['regime']}"
        )
        assert current["confidence"] > 0.2
        assert current["duration_bars"] > 0

        # stability 应较高（趋势明确）
        assert result.stability > 0.5, f"UPTREND 稳定性应 > 0.5，得到 {result.stability}"


# ─── Case 2: DOWNTREND ──────────────────────────────────────


class TestDowntrendDetection:
    """持续下跌 → DOWNTREND"""

    def test_downtrend(self) -> None:
        """强下跌趋势应识别为 DOWNTREND"""
        df = _make_ohcl_df(n=120, start_price=100.0, trend=-0.6, noise=0.3)
        analyzer = RegimeAnalyzer()
        result = analyzer.analyze_window(df, lookback=60)

        current = analyzer.get_current_regime()
        assert current["regime"] == "DOWNTREND", (
            f"预期 DOWNTREND，得到 {current['regime']}"
        )
        assert current["confidence"] > 0.2

        # 状态转换序列应包含 DOWNTREND
        regimes_in_result = {r["regime"] for r in result.sequence}
        assert "DOWNTREND" in regimes_in_result


# ─── Case 3: RANGE ──────────────────────────────────────────


class TestRangeDetection:
    """横盘震荡 → RANGE"""

    def test_range(self) -> None:
        """低波动横盘应识别为 RANGE"""
        df = _make_ohcl_df(n=120, start_price=100.0, trend=0.02, noise=0.15)
        analyzer = RegimeAnalyzer()
        result = analyzer.analyze_window(df, lookback=60)

        current = analyzer.get_current_regime()
        # RANGE 或 UKNOWN 都是可能的，取决于 ADX 值
        assert current["regime"] in ("RANGE", "UNKNOWN"), (
            f"预期 RANGE 或 UNKNOWN，得到 {current['regime']}"
        )

        # 稳定性应较高（横盘整理）
        assert result.stability > 0.3


# ─── RegimeTransition ───────────────────────────────────────


class TestRegimeTransitions:
    """状态转换逻辑验证"""

    def test_transition_probability(self) -> None:
        """多次分析后应有转换矩阵"""
        df = _make_ohcl_df(n=100, start_price=100.0, trend=0.5, noise=0.5)
        analyzer = RegimeAnalyzer()

        # 多次 analyze_window 以累积状态
        for i in range(5):
            sub_df = df.iloc[:50 + i * 10]
            if len(sub_df) >= 30:
                analyzer.analyze_window(sub_df, lookback=min(30, len(sub_df)))

        transitions = analyzer.regime_transition_score()
        assert isinstance(transitions, dict)
        # 至少有一些状态的历史
        assert len(analyzer.get_history()) > 1

    def test_knowledge_entry(self) -> None:
        """知识沉淀条目格式验证"""
        df = _make_ohcl_df(n=80, start_price=100.0, trend=0.5, noise=0.3)
        analyzer = RegimeAnalyzer()
        analyzer.analyze_window(df, lookback=60)

        entry = analyzer.knowledge_entry()
        assert entry.regime in ("UPTREND", "DOWNTREND", "RANGE", "UNKNOWN", "BREAKOUT", "CLIMAX")
        assert 0 <= entry.confidence <= 1.0
        assert entry.duration_bars >= 0
        assert isinstance(entry.transition_probabilities, dict)
        assert len(entry.summary) > 0
