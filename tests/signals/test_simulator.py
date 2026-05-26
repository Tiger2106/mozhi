"""
测试：SignalSimulator — 独立 Signal 效果模拟器

覆盖场景：
  1. BUY 方向的正收益模拟
  2. SELL 方向的负收益模拟
  3. HOLD 方向返回空结果
  4. 数据不足/无效价格返回空结果
  5. 自定义持有周期
  6. 自定义入场索引
  7. 批量模拟多个信号
  8. 边缘情况：平稳价格、极端波动

author: 墨衡
created_time: 2026-05-20
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import pytest

from src.signals.signal_protocol_v1 import (
    Signal,
    CURRENT_PROTOCOL_VERSION,
    generate_signal_id,
)
from src.signals.simulator import SignalSimulator, SimResult


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


_TZ_EAST8 = timezone(timedelta(hours=8))


def _make_signal(
    direction: str = "BUY",
    symbol: str = "601857",
    confidence: float = 0.85,
    extras: Optional[Dict[str, Any]] = None,
) -> Signal:
    """创建一个标准的测试 Signal 对象。"""
    return Signal(
        signal_id=generate_signal_id(),
        symbol=symbol,
        direction=direction,        # type: ignore[arg-type]
        confidence=confidence,
        horizon="short",
        signal_type="trend",
        timestamp=datetime.now(_TZ_EAST8),
        protocol_version=CURRENT_PROTOCOL_VERSION,
        extras=extras or {},
    )


def _make_price_data(length: int = 20, start_price: float = 100.0) -> pd.DataFrame:
    """生成单调上涨的价格序列（方便验证 BUY 收益为正）。"""
    closes = np.linspace(start_price, start_price * 1.1, length)
    return pd.DataFrame({"close": closes})


def _make_falling_price(length: int = 20, start_price: float = 100.0) -> pd.DataFrame:
    """生成单调下跌的价格序列（方便验证 SELL 收益为正）。"""
    closes = np.linspace(start_price, start_price * 0.9, length)
    return pd.DataFrame({"close": closes})


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def simulator() -> SignalSimulator:
    return SignalSimulator(holding_periods=10)


@pytest.fixture
def rising_prices() -> pd.DataFrame:
    return _make_price_data(30, 100.0)


@pytest.fixture
def falling_prices() -> pd.DataFrame:
    return _make_falling_price(30, 100.0)


# ═══════════════════════════════════════════════════════════════
# 基本路径
# ═══════════════════════════════════════════════════════════════


class TestEvaluateBasic:
    """evaluate() 基本功能。"""

    def test_buy_rising_positive_return(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """BUY + 上涨行情 → expected_return > 0"""
        signal = _make_signal(direction="BUY")
        result = simulator.evaluate(signal, rising_prices)

        assert result.expected_return > 0
        assert result.symbol == "601857"
        assert result.direction == "BUY"
        assert result.total_trades == 1
        assert result.note == "模拟完成"

    def test_sell_falling_positive_return(self, simulator: SignalSimulator, falling_prices: pd.DataFrame):
        """SELL + 下跌行情 → expected_return > 0（做空收益为正）"""
        signal = _make_signal(direction="SELL")
        result = simulator.evaluate(signal, falling_prices)

        assert result.expected_return > 0
        assert result.direction == "SELL"

    def test_buy_falling_negative_return(self, simulator: SignalSimulator, falling_prices: pd.DataFrame):
        """BUY + 下跌行情 → expected_return < 0"""
        signal = _make_signal(direction="BUY")
        result = simulator.evaluate(signal, falling_prices)

        assert result.expected_return < 0

    def test_sell_rising_negative_return(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """SELL + 上涨行情 → expected_return < 0（做空赔钱）"""
        signal = _make_signal(direction="SELL")
        result = simulator.evaluate(signal, rising_prices)

        assert result.expected_return < 0

    def test_hold_returns_empty(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """HOLD → empty result（模拟无意义）"""
        signal = _make_signal(direction="HOLD")
        result = simulator.evaluate(signal, rising_prices)

        assert result.expected_return == 0.0
        assert result.total_trades == 0
        assert "HOLD" in result.note

    def test_confidence_preserved(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """信号的 confidence 传递到结果"""
        signal = _make_signal(direction="BUY", confidence=0.75)
        result = simulator.evaluate(signal, rising_prices)

        assert result.confidence == 0.75


# ═══════════════════════════════════════════════════════════════
# 边界情况
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界与异常。"""

    def test_empty_price_data(self, simulator: SignalSimulator):
        """空 price_data → empty result"""
        signal = _make_signal(direction="BUY")
        empty_df = pd.DataFrame()
        result = simulator.evaluate(signal, empty_df)

        assert result.expected_return == 0.0
        assert result.total_trades == 0
        assert "为空" in result.note

    def test_missing_close_column(self, simulator: SignalSimulator):
        """缺少 close 列 → empty result"""
        signal = _make_signal(direction="BUY")
        bad_df = pd.DataFrame({"open": [100, 101]})
        result = simulator.evaluate(signal, bad_df)

        assert result.expected_return == 0.0
        assert "缺少" in result.note

    def test_single_bar(self, simulator: SignalSimulator):
        """只有 1 根 bar（不足 2 周期）→ empty result"""
        signal = _make_signal(direction="BUY")
        single = pd.DataFrame({"close": [100.0]})
        result = simulator.evaluate(signal, single)

        assert result.expected_return == 0.0
        assert "不足" in result.note

    def test_zero_entry_price(self, simulator: SignalSimulator):
        """入场价格为 0 → empty result"""
        signal = _make_signal(direction="BUY")
        data = pd.DataFrame({"close": [0.0, 1.0, 2.0]})
        result = simulator.evaluate(signal, data)

        assert result.expected_return == 0.0
        assert "无效" in result.note or "为空" in result.note


# ═══════════════════════════════════════════════════════════════
# 自定义参数
# ═══════════════════════════════════════════════════════════════


class TestCustomParameters:
    """自定义 Entry Index 和 Holding Periods。"""

    def test_custom_entry_index(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """从 extras["entry_index"] 指定入场位置"""
        signal = _make_signal(
            direction="BUY",
            extras={"entry_index": 10},
        )
        result = simulator.evaluate(signal, rising_prices)

        # entry_index=10, 从第 11 根 bar 入场
        assert result.holding_periods > 0
        assert result.expected_return > 0  # 仍然是上涨

    def test_custom_holding_periods(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """从 extras["holding_periods"] 覆盖持有周期"""
        signal = _make_signal(
            direction="BUY",
            extras={"holding_periods": 3},
        )
        result = simulator.evaluate(signal, rising_prices)

        assert result.holding_periods == 4  # entry + 3 periods = 4 bars

    def test_custom_holding_via_constructor(self):
        """构造器 holding_periods 参数"""
        sim = SignalSimulator(holding_periods=20)
        signal = _make_signal(direction="BUY")
        data = _make_price_data(50, 100.0)
        result = sim.evaluate(signal, data)

        assert result.holding_periods >= 1

    def test_entry_index_beyond_length(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """entry_index 超出数据长度 → 兜底为索引 0"""
        n = len(rising_prices)
        signal = _make_signal(
            direction="BUY",
            extras={"entry_index": n + 100},
        )
        result = simulator.evaluate(signal, rising_prices)

        # 兜底为 0（实际 cap 到 n-1），仅剩 1 条 bar → 持有期过短
        assert result.expected_return == 0.0
        assert "持有期过短" in result.note or "无效" in result.note


# ═══════════════════════════════════════════════════════════════
# 平稳 / 噪声价格
# ═══════════════════════════════════════════════════════════════


class TestFlatAndNoise:
    """平稳价格与噪声价格场景。"""

    def test_flat_price(self, simulator: SignalSimulator):
        """价格完全不变 → return ≈ 0"""
        signal = _make_signal(direction="BUY")
        flat = pd.DataFrame({"close": [100.0] * 20})
        result = simulator.evaluate(signal, flat)

        assert abs(result.expected_return) < 0.01

    def test_noisy_price(self, simulator: SignalSimulator):
        """噪声价格 → 仍返回有效统计"""
        rng = np.random.default_rng(42)
        noisy = 100.0 + rng.normal(0, 1, 50)
        noisy = np.maximum(noisy, 1.0)  # 确保正数
        data = pd.DataFrame({"close": noisy})

        signal = _make_signal(direction="BUY")
        result = simulator.evaluate(signal, data)

        assert isinstance(result.expected_return, float)
        assert isinstance(result.sharpe_approx, float)
        assert isinstance(result.win_rate, float)
        assert result.total_trades == 1


# ═══════════════════════════════════════════════════════════════
# SimResult 数据类型
# ═══════════════════════════════════════════════════════════════


class TestSimResultStructure:
    """SimResult 字段完备性验证。"""

    def test_result_has_all_required_fields(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """SimResult 包含所有必需字段"""
        signal = _make_signal(direction="BUY")
        result = simulator.evaluate(signal, rising_prices)

        assert hasattr(result, "signal_id")
        assert hasattr(result, "symbol")
        assert hasattr(result, "direction")
        assert hasattr(result, "expected_return")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "holding_periods")
        assert hasattr(result, "win_rate")
        assert hasattr(result, "sharpe_approx")
        assert hasattr(result, "total_trades")
        assert hasattr(result, "confidence")
        assert hasattr(result, "note")

    def test_result_drawdown_not_positive(self, simulator: SignalSimulator, rising_prices: pd.DataFrame):
        """max_drawdown 为负或零（表示亏损）"""
        signal = _make_signal(direction="BUY")
        result = simulator.evaluate(signal, rising_prices)

        # 上涨行情的回撤应接近 0 或为负
        assert result.max_drawdown <= 0
