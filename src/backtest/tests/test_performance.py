"""
墨枢 - Performance 单元测试
覆盖：收益率、最大回撤、夏普比率、VaR、交易统计、边界场景
"""
import pytest
import math
from backtest.performance import PerformanceCalculator, Performance


# Fixtures

@pytest.fixture
def calc():
    return PerformanceCalculator()


def eq_curve(values):
    """构造 equity curve，date 从 1 递增。"""
    return [{"date": i + 1, "total_equity": v} for i, v in enumerate(values)]


def trades_from_pnls(pnls):
    """依据 realized_pnl 列表生成 trades。"""
    return [{"realized_pnl": p} for p in pnls]


# 1. 收益率测试

class TestTotalReturn:
    def test_simple_growth(self, calc):
        """初始100 -> 110，总收益 10%"""
        curve = eq_curve([100.0, 110.0])
        assert calc.calc_total_return_pct(curve, 100.0) == pytest.approx(10.0)

    def test_decline(self, calc):
        """初始100 -> 80，总收益 -20%"""
        curve = eq_curve([100.0, 80.0])
        assert calc.calc_total_return_pct(curve, 100.0) == pytest.approx(-20.0)

    def test_zero_initial_capital(self, calc):
        """初始资金为0，应返回0"""
        curve = eq_curve([0.0, 10.0])
        assert calc.calc_total_return_pct(curve, 0.0) == 0.0

    def test_flat_equity(self, calc):
        """equity 不变，收益为 0"""
        curve = eq_curve([100.0, 100.0, 100.0])
        assert calc.calc_total_return_pct(curve, 100.0) == pytest.approx(0.0)


class TestAnnualReturn:
    def test_single_period(self, calc):
        """仅一个周期，年化 = 总收益"""
        curve = eq_curve([100.0, 100.0])
        total = calc.calc_total_return_pct(curve, 100.0)
        assert calc.calc_annual_return_pct(curve, total) == pytest.approx(total)

    def test_one_year(self, calc):
        """250个交易日，总收益复利后年化应为约21%"""
        curve = eq_curve([100.0] + [100.0 * (1.21 ** (1 / 249)) ** i for i in range(1, 250)])
        total = calc.calc_total_return_pct(curve, 100.0)
        ar = calc.calc_annual_return_pct(curve, total)
        assert ar == pytest.approx(21.0, abs=0.01)

    def test_empty_curve(self, calc):
        """空曲线返回 0"""
        assert calc.calc_annual_return_pct([], 10.0) == 0.0


# 2. 最大回撤测试

class TestMaxDrawdown:
    def test_no_drawdown(self, calc):
        """单调递增，无回撤"""
        curve = eq_curve([100.0, 110.0, 120.0])
        assert calc.calc_max_drawdown_pct(curve) == pytest.approx(0.0)
        assert calc.calc_max_drawdown(curve) == 0.0

    def test_simple_drawdown(self, calc):
        """100 -> 120 -> 90，回撤 = (120-90)/120 = 25%"""
        curve = eq_curve([100.0, 120.0, 90.0])
        assert calc.calc_max_drawdown_pct(curve) == pytest.approx(25.0, abs=0.01)
        assert calc.calc_max_drawdown(curve) == pytest.approx(30.0, abs=0.01)

    def test_multi_peak(self, calc):
        """100->110->105->115->95，峰值 115，回撤 = (115-95)/115"""
        curve = eq_curve([100.0, 110.0, 105.0, 115.0, 95.0])
        mdd = calc.calc_max_drawdown_pct(curve)
        assert mdd == pytest.approx((115.0 - 95.0) / 115.0 * 100.0, abs=0.01)

    def test_decline_only(self, calc):
        """持续下跌，回撤 = (100-60)/100 = 40%"""
        curve = eq_curve([100.0, 80.0, 60.0])
        assert calc.calc_max_drawdown_pct(curve) == pytest.approx(40.0, abs=0.01)

    def test_empty_curve(self, calc):
        """空曲线返回 0"""
        assert calc.calc_max_drawdown_pct([]) == 0.0
        assert calc.calc_max_drawdown([]) == 0.0


class TestCalmarRatio:
    def test_positive(self, calc):
        """年化 30%，回撤 15%，Calmar = 2.0"""
        assert calc.calc_calmar_ratio(30.0, 15.0) == pytest.approx(2.0, abs=0.01)

    def test_zero_drawdown(self, calc):
        """回撤为 0 时返回 0"""
        assert calc.calc_calmar_ratio(30.0, 0.0) == 0.0


# 3. 夏普比率测试

class TestSharpeRatio:
    def test_zero_returns(self, calc):
        """收益率全为 0，波动率为 0，返回 0"""
        daily = [0.0] * 10
        assert calc.calc_sharpe_ratio(daily) == 0.0

    def test_positive_sharpe(self, calc):
        """正收益序列 -> 夏普 > 0"""
        daily = [0.01, -0.005, 0.015, -0.002, 0.008]
        sharpe = calc.calc_sharpe_ratio(daily)
        assert sharpe > 0.0

    def test_negative_sharpe(self, calc):
        """有波动的负收益序列 -> 夏普 < 0"""
        daily = [-0.01, -0.015, -0.005, -0.02]
        sharpe = calc.calc_sharpe_ratio(daily)
        assert sharpe < 0.0

    def test_single_return(self, calc):
        """仅一个收益率，无法计算波动率，返回 0"""
        assert calc.calc_sharpe_ratio([0.05]) == 0.0

    def test_zero_volatility(self, calc):
        """固定日收益，std=0，函数应保护返回 0"""
        daily = [0.005] * 20
        assert calc.calc_sharpe_ratio(daily) == 0.0


# 4. VaR (95%) 测试

class TestVaR:
    def test_var_95_basic(self, calc):
        """[-0.05, -0.02, 0.01, 0.03, 0.01] -> 5% 分位 = -0.05 -> -5%"""
        daily = [-0.05, -0.02, 0.01, 0.03, 0.01]
        var = calc.calc_var(daily, 0.95)
        assert var == pytest.approx(-5.0, abs=0.01)

    def test_var_99(self, calc):
        """1% 分位 = -0.05"""
        daily = [-0.05, -0.02, 0.01, 0.03, 0.01]
        var = calc.calc_var(daily, 0.99)
        assert var == pytest.approx(-5.0, abs=0.01)

    def test_var_empty(self, calc):
        """空序列返回 0"""
        assert calc.calc_var([], 0.95) == 0.0

    def test_var_all_positive(self, calc):
        """全部正收益，VaR 仍为最小那个"""
        daily = [0.01, 0.02, 0.03]
        var = calc.calc_var(daily, 0.95)
        assert var == pytest.approx(1.0, abs=0.01)

    def test_var_sorted_properties(self, calc):
        """VaR = (1-confidence) 分位点 * 100"""
        daily = [0.05, 0.04, 0.03, 0.02, 0.01, -0.01, -0.02, -0.03]
        var_95 = calc.calc_var(daily, 0.95)
        sorted_ret = sorted(daily)
        expected = sorted_ret[int((1 - 0.95) * len(sorted_ret))]
        assert var_95 == pytest.approx(expected * 100.0, abs=0.001)


# 5. 交易统计测试

class TestWinRate:
    def test_win_rate(self, calc):
        """4赢1亏，胜率 80%"""
        pnls = [100.0, 200.0, -50.0, 150.0, 80.0]
        assert calc.calc_win_rate(trades_from_pnls(pnls)) == pytest.approx(80.0, abs=0.01)

    def test_all_wins(self, calc):
        assert calc.calc_win_rate(trades_from_pnls([10.0, 20.0, 30.0])) == pytest.approx(100.0)

    def test_all_losses(self, calc):
        assert calc.calc_win_rate(trades_from_pnls([-10.0, -20.0])) == pytest.approx(0.0)

    def test_empty_trades(self, calc):
        assert calc.calc_win_rate([]) == 0.0

    def test_no_realized_pnl_fallback(self, calc):
        """无 realized_pnl 时按 side 判断"""
        trades = [
            {"side": "sell", "price": 11.0, "avg_buy_price": 10.0},
            {"side": "buy"},
        ]
        assert calc.calc_win_rate(trades) == pytest.approx(50.0, abs=0.01)


class TestProfitLossRatio:
    def test_basic(self, calc):
        """avg_profit=(10+20)/2=15, avg_loss=5 -> 盈亏比=3.0"""
        pnls = [10.0, 20.0, -5.0]
        assert calc.calc_profit_loss_ratio(trades_from_pnls(pnls)) == pytest.approx(3.0, abs=0.01)

    def test_no_losses(self, calc):
        """无亏损交易，盈亏比 = 0"""
        assert calc.calc_profit_loss_ratio(trades_from_pnls([10.0, 20.0])) == 0.0

    def test_empty_trades(self, calc):
        assert calc.calc_profit_loss_ratio([]) == 0.0


class TestConsecutiveWinsLosses:
    def test_max_consecutive_wins(self, calc):
        pnls = [10.0, 20.0, 30.0, -5.0, 5.0, 40.0, 50.0]
        assert calc.calc_max_consecutive_wins(trades_from_pnls(pnls)) == 3

    def test_max_consecutive_losses(self, calc):
        pnls = [-10.0, -20.0, 5.0, -30.0, -40.0, -50.0]
        assert calc.calc_max_consecutive_losses(trades_from_pnls(pnls)) == 3

    def test_no_realized_pnl(self, calc):
        """无 realized_pnl 字段则连续计数归零"""
        trades = [{"side": "sell", "price": 11.0}] * 3
        assert calc.calc_max_consecutive_wins(trades) == 0
        assert calc.calc_max_consecutive_losses(trades) == 0


# 6. 边界场景测试

class TestEdgeCases:
    def test_empty_equity_curve(self, calc):
        result = calc.compute([], 100000.0, [])
        assert result["total_return_pct"] == 0.0
        assert result["sharpe_ratio"] == 0.0
        assert result["final_equity"] == pytest.approx(100000.0, abs=0.01)

    def test_single_data_point(self, calc):
        """仅一个数据点，总收益=0，年化=0"""
        curve = [{"date": 1, "total_equity": 100000.0}]
        result = calc.compute(curve, 100000.0, [])
        assert result["total_return_pct"] == 0.0
        assert result["annual_return_pct"] == 0.0
        assert result["max_drawdown_pct"] == 0.0

    def test_zero_volatility_returns(self, calc):
        """零波动率，Sharpe/Sortino 应返回 0"""
        curve = eq_curve([100.0] * 5)
        daily = calc.calc_daily_returns(curve)
        vol = calc.calc_volatility(daily)
        assert vol == 0.0
        sharpe = calc.calc_sharpe_ratio(daily)
        assert sharpe == 0.0

    def test_downside_volatility_insufficient_samples(self, calc):
        """下行样本不足2个时返回 0"""
        daily = [0.02, -0.01, 0.03]  # 仅1个负收益
        dv = calc.calc_downside_volatility(daily, 0.0)
        assert dv == 0.0

    def test_empty_trades_in_compute(self, calc):
        """有 equity 但无交易，走完全部计算路径"""
        curve = eq_curve([100000.0, 110000.0, 105000.0])
        result = calc.compute(curve, 100000.0, [])
        assert "total_return_pct" in result
        assert "sharpe_ratio" in result
        assert "win_rate_pct" in result
        assert result["total_trades"] == 0

    def test_sortino_zero_downside(self, calc):
        """无下行波动率时 Sortino 返回 0"""
        daily = [0.01, 0.02, 0.03, 0.01]
        assert calc.calc_sortino_ratio(daily) == 0.0


# 7. 完整性集成测试

class TestPerformanceFullCompute:
    def test_full_metrics_shape(self, calc):
        """验证 compute 返回所有必要字段"""
        curve = eq_curve([100000.0, 110000.0, 105000.0, 120000.0])
        trades = trades_from_pnls([1000.0, -200.0, 3000.0, 500.0, -100.0])
        result = calc.compute(curve, 100000.0, trades)

        required_keys = [
            "total_return_pct", "annual_return_pct",
            "max_drawdown", "max_drawdown_pct", "calmar_ratio",
            "sharpe_ratio", "volatility", "sortino_ratio",
            "var_95_pct", "win_rate_pct", "profit_loss_ratio",
            "max_consecutive_wins", "max_consecutive_losses",
            "total_trades", "final_equity",
            "daily_returns", "equity_curve",
        ]
        for k in required_keys:
            assert k in result, f"Missing key: {k}"

    def test_legacy_static_compute(self):
        """验证 Performance.compute 兼容别名行为一致"""
        curve = eq_curve([100000.0, 120000.0])
        result = Performance.compute(curve, 100000.0, [])
        assert result["total_return_pct"] == pytest.approx(20.0, abs=0.01)


# 8. Daily Returns & Volatility 单元

class TestDailyReturns:
    def test_single_point_returns_empty(self, calc):
        """单点曲线返回空列表"""
        curve = [{"date": 1, "total_equity": 100.0}]
        assert calc.calc_daily_returns(curve) == []

    def test_returns_length(self, calc):
        """n 个数据点 -> n-1 个日收益"""
        curve = eq_curve([100.0, 102.0, 98.0, 104.0])
        dr = calc.calc_daily_returns(curve)
        assert len(dr) == 3

    def test_daily_returns_values(self, calc):
        curve = eq_curve([100.0, 110.0, 99.0])
        dr = calc.calc_daily_returns(curve)
        assert dr[0] == pytest.approx(0.10)
        assert dr[1] == pytest.approx(-0.10)


class TestVolatility:
    def test_volatility_two_values(self, calc):
        """两个值可计算波动率"""
        daily = [0.01, -0.01]
        vol = calc.calc_volatility(daily)
        assert vol > 0

    def test_annual_volatility_scaled(self, calc):
        """年化波动率 = 日波动率 * sqrt(250)"""
        daily = [0.01] * 100
        daily_vol = calc.calc_volatility(daily)
        annual_vol = calc.calc_annual_volatility(daily)
        assert annual_vol == pytest.approx(daily_vol * math.sqrt(250), abs=0.001)