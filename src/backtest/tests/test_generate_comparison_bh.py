"""Tests for buy-hold column in comparison report (P0-10 + P0-11)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backtest.reports.generate_comparison import add_buy_hold_column

# ═══════════════════════════════════════════════════════════════
# Mock data
# ═══════════════════════════════════════════════════════════════

MOCK_BUY_HOLD_RETURN = {
    "symbol": "601857",
    "name": "中国石油",
    "start_date": "2026-01-05",
    "end_date": "2026-05-14",
    "start_close": 8.88,
    "end_close": 9.84,
    "total_return_pct": 10.81,
    "total_return": 0.1081,
    "annualized_return_pct": 47.43,
    "max_drawdown_pct": -3.21,
    "max_drawdown_duration": 5,
    "win_rate": 0.5714,
    "calmar_ratio": 14.78,
    "trading_days": 84,
}


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════


class TestAddBuyHoldColumn:
    """验证 add_buy_hold_column 函数行为。"""

    def test_add_buy_hold_column(self):
        """mock calc_buy_hold_return，验证数据追加。"""
        comparison_data = [{"name": "trend", "start_date": "2026-01-05", "end_date": "2026-05-14"}]

        with patch(
            "backtest.reports.generate_comparison.calc_buy_hold_return",
            return_value=MOCK_BUY_HOLD_RETURN,
        ):
            result = add_buy_hold_column(comparison_data)

        assert len(result) == 2, "应追加一条买入持有记录"
        entry = result[-1]

        # 核心字段验证
        assert entry["name"] == "中国石油"
        assert entry["symbol"] == "601857"
        assert entry["total_return_pct"] == 10.81
        assert entry["annualized_return_pct"] == 47.43
        assert entry["max_drawdown_pct"] == -3.21
        assert entry["calmar_ratio"] == 14.78
        assert entry["win_rate"] == 0.5714

    def test_add_buy_hold_column_default_dates(self):
        """start_date / end_date 默认从 comparison_data 第一项推。"""
        comparison_data = [{"name": "trend", "start_date": "2026-02-01", "end_date": "2026-05-01"}]

        with patch(
            "backtest.reports.generate_comparison.calc_buy_hold_return",
            return_value=MOCK_BUY_HOLD_RETURN,
        ) as mock_fn:
            result = add_buy_hold_column(comparison_data)

        # 验证传入 calc_buy_hold_return 的日期是从 comparison_data 推断的
        # calc_buy_hold_return(symbol, name, start_date, end_date, ...) 前4个为位置参数
        call_posargs = mock_fn.call_args[0]
        assert call_posargs[2] == "2026-02-01"
        assert call_posargs[3] == "2026-05-01"

    def test_add_buy_hold_column_explicit_dates(self):
        """显式传入日期应覆盖默认推断。"""
        comparison_data = [{"name": "trend"}]

        with patch(
            "backtest.reports.generate_comparison.calc_buy_hold_return",
            return_value=MOCK_BUY_HOLD_RETURN,
        ) as mock_fn:
            result = add_buy_hold_column(
                comparison_data,
                symbol="601857",
                name="中国石油",
                start_date="2026-03-01",
                end_date="2026-04-30",
            )

        call_posargs = mock_fn.call_args[0]
        assert call_posargs[2] == "2026-03-01"
        assert call_posargs[3] == "2026-04-30"

    def test_buy_hold_appears_in_output(self):
        """验证最终数据中包含"中国石油"字符串。"""
        comparison_data = [{"name": "trend", "start_date": "2026-01-05", "end_date": "2026-05-14"}]

        with patch(
            "backtest.reports.generate_comparison.calc_buy_hold_return",
            return_value=MOCK_BUY_HOLD_RETURN,
        ):
            result = add_buy_hold_column(comparison_data)

        output = str(result)
        assert "中国石油" in output, "渲染输出应包含'中国石油'"
        assert "601857" in output, "渲染输出应包含'601857'"
