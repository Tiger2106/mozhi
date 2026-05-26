"""
墨枢 - SlippageModel 单元测试
覆盖：零滑点、固定滑点、比例滑点、极端滑点、固定+比例混合
"""
import pytest
import sys

sys.path.insert(0, "../..")
from backtest.slippage_model import NoSlippage, FixedSlippage, RatioSlippage, SlippageModel


# ═══════════════════════════════════════════════════════════════
# 1. 零滑点：买入/卖出价格不变
# ═══════════════════════════════════════════════════════════════

class TestNoSlippage:
    """零滑点模式：成交价 = 市场价，任何情况下不变"""

    def test_buy_price_unchanged(self):
        model = NoSlippage()
        assert model.calc_buy_price(10.0) == 10.0
        assert model.calc_buy_price(100.0) == 100.0

    def test_sell_price_unchanged(self):
        model = NoSlippage()
        assert model.calc_sell_price(10.0) == 10.0
        assert model.calc_sell_price(100.0) == 100.0

    def test_zero_price(self):
        model = NoSlippage()
        assert model.calc_buy_price(0.0) == 0.0
        assert model.calc_sell_price(0.0) == 0.0

    def test_very_large_price(self):
        model = NoSlippage()
        assert model.calc_buy_price(1e9) == 1e9
        assert model.calc_sell_price(1e9) == 1e9

    def test_very_small_price(self):
        model = NoSlippage()
        assert model.calc_buy_price(0.01) == 0.01
        assert model.calc_sell_price(0.01) == 0.01


# ═══════════════════════════════════════════════════════════════
# 2. 固定滑点：±固定值的价格调整
# ═══════════════════════════════════════════════════════════════

class TestFixedSlippage:
    """固定滑点模式：买入上浮、卖出下浮"""

    def test_buy_price_increased(self):
        model = FixedSlippage(slippage=0.01)
        # 买入：市场价 + 固定滑点
        assert model.calc_buy_price(10.0) == 10.01
        assert model.calc_buy_price(100.0) == 100.01

    def test_sell_price_decreased(self):
        model = FixedSlippage(slippage=0.01)
        # 卖出：市场价 - 固定滑点
        assert model.calc_sell_price(10.0) == 9.99
        assert model.calc_sell_price(100.0) == 99.99

    def test_spread_consistency(self):
        model = FixedSlippage(slippage=0.02)
        price = 50.0
        buy = model.calc_buy_price(price)
        sell = model.calc_sell_price(price)
        # 买卖价差 = 2 * slippage
        assert buy - sell == pytest.approx(0.04)

    def test_different_slippage_values(self):
        for slip in [0.001, 0.005, 0.1, 1.0, 10.0]:
            model = FixedSlippage(slippage=slip)
            assert model.calc_buy_price(100.0) == 100.0 + slip
            assert model.calc_sell_price(100.0) == 100.0 - slip

    def test_default_slippage(self):
        model = FixedSlippage()
        assert model.slippage == 0.01
        assert model.calc_buy_price(100.0) == 100.01
        assert model.calc_sell_price(100.0) == 99.99


# ═══════════════════════════════════════════════════════════════
# 3. 比例滑点：±比例的价格调整（买入上浮/卖出下浮）
# ═══════════════════════════════════════════════════════════════

class TestRatioSlippage:
    """比例滑点模式：按比例上浮/下浮"""

    def test_buy_price_increased(self):
        model = RatioSlippage(slippage_rate=0.001)  # 千分之一
        # 买入：市场价 * (1 + rate)
        assert model.calc_buy_price(100.0) == 100.1

    def test_sell_price_decreased(self):
        model = RatioSlippage(slippage_rate=0.001)
        # 卖出：市场价 * (1 - rate)
        assert model.calc_sell_price(100.0) == 99.9

    def test_spread_consistency(self):
        model = RatioSlippage(slippage_rate=0.002)  # 千分之二
        price = 100.0
        buy = model.calc_buy_price(price)
        sell = model.calc_sell_price(price)
        # 买卖价差比例 = 2 * rate / (1 - rate^2) ≈ 2 * rate
        spread_ratio = (buy - sell) / price
        assert spread_ratio == pytest.approx(0.004, rel=1e-6)

    def test_different_rates(self):
        for rate in [0.0001, 0.001, 0.005, 0.01, 0.05]:
            model = RatioSlippage(slippage_rate=rate)
            price = 50.0
            assert model.calc_buy_price(price) == price * (1.0 + rate)
            assert model.calc_sell_price(price) == price * (1.0 - rate)

    def test_default_rate(self):
        model = RatioSlippage()
        assert model.slippage_rate == 0.001

    def test_rate_1_percent(self):
        model = RatioSlippage(slippage_rate=0.01)  # 1%
        assert model.calc_buy_price(1000.0) == 1010.0
        assert model.calc_sell_price(1000.0) == 990.0


# ═══════════════════════════════════════════════════════════════
# 4. 极端滑点：滑点超过价格自身的边界行为
# ═══════════════════════════════════════════════════════════════

class TestExtremeSlippage:
    """极端滑点边界测试"""

    # 4a. 固定滑点超过价格
    def test_fixed_slippage_greater_than_price(self):
        model = FixedSlippage(slippage=5.0)
        price = 3.0
        # 卖出价变为负数（数学上合法，实际业务需注意）
        sell = model.calc_sell_price(price)
        assert sell == -2.0
        buy = model.calc_buy_price(price)
        assert buy == 8.0

    def test_fixed_slippage_equals_price(self):
        model = FixedSlippage(slippage=10.0)
        price = 10.0
        assert model.calc_sell_price(price) == 0.0
        assert model.calc_buy_price(price) == 20.0

    # 4b. 比例滑点超过100%
    def test_ratio_slippage_near_100_percent(self):
        model = RatioSlippage(slippage_rate=0.5)  # 50%
        price = 100.0
        assert model.calc_buy_price(price) == 150.0
        assert model.calc_sell_price(price) == 50.0

    def test_ratio_slippage_100_percent(self):
        model = RatioSlippage(slippage_rate=1.0)  # 100%
        price = 100.0
        assert model.calc_buy_price(price) == 200.0
        assert model.calc_sell_price(price) == 0.0

    # 4c. 极小价格
    def test_fixed_slippage_on_penny_price(self):
        model = FixedSlippage(slippage=0.001)
        price = 0.001
        buy = model.calc_buy_price(price)
        sell = model.calc_sell_price(price)
        assert buy == pytest.approx(0.002)
        assert sell == 0.0  # 精确为0

    # 4d. 极大滑点
    def test_fixed_very_large_slippage(self):
        model = FixedSlippage(slippage=1e6)
        price = 100.0
        assert model.calc_buy_price(price) == 1_000_100.0
        assert model.calc_sell_price(price) == -999_900.0

    # 4e. 零价格（Fixed）
    def test_fixed_slippage_zero_price(self):
        model = FixedSlippage(slippage=0.01)
        assert model.calc_buy_price(0.0) == 0.01
        assert model.calc_sell_price(0.0) == -0.01


# ═══════════════════════════════════════════════════════════════
# 5. 固定+比例混合：两种滑点叠加时行为
# ═══════════════════════════════════════════════════════════════

class TestCombinedSlippage:
    """组合滑点测试：使用组合模式（自定义子类）"""

    def test_combined_fixed_plus_ratio_buy(self):
        """
        混合滑点（先比例后固定，或先固定后比例）
        本测试验证组合逻辑：买入价 = (price * (1 + ratio)) + fixed
        """
        price = 100.0
        fixed = 0.01
        ratio = 0.001

        # 模拟组合：先比例后固定
        ratio_buy = price * (1.0 + ratio)  # 100.1
        combined_buy = ratio_buy + fixed     # 100.11

        # 验证单独模型
        ratio_model = RatioSlippage(slippage_rate=ratio)
        fixed_model = FixedSlippage(slippage=fixed)

        # 叠加计算
        step1 = ratio_model.calc_buy_price(price)
        step2 = step1 + fixed  # 手动加固定滑点
        assert step2 == pytest.approx(combined_buy)

    def test_combined_fixed_plus_ratio_sell(self):
        """混合滑点：卖出价 = (price * (1 - ratio)) - fixed"""
        price = 100.0
        fixed = 0.01
        ratio = 0.001

        ratio_sell = price * (1.0 - ratio)  # 99.9
        combined_sell = ratio_sell - fixed    # 99.89

        ratio_model = RatioSlippage(slippage_rate=ratio)
        step1 = ratio_model.calc_sell_price(price)
        step2 = step1 - fixed
        assert step2 == pytest.approx(combined_sell)

    def test_combined_large_values(self):
        """混合滑点大值测试"""
        price = 10000.0
        fixed = 0.5
        ratio = 0.002

        expected_buy = price * (1.0 + ratio) + fixed  # 10020.5
        expected_sell = price * (1.0 - ratio) - fixed  # 9980.5

        ratio_model = RatioSlippage(slippage_rate=ratio)
        fixed_model = FixedSlippage(slippage=fixed)

        buy = ratio_model.calc_buy_price(price) + fixed
        sell = ratio_model.calc_sell_price(price) - fixed

        assert buy == pytest.approx(expected_buy)
        assert sell == pytest.approx(expected_sell)

    def test_combined_both_zero(self):
        """固定0+比例0 = 零滑点"""
        price = 50.0
        fixed = 0.0
        ratio = 0.0

        ratio_model = RatioSlippage(slippage_rate=ratio)
        fixed_model = FixedSlippage(slippage=fixed)

        buy = ratio_model.calc_buy_price(price) + fixed
        sell = ratio_model.calc_sell_price(price) - fixed

        assert buy == price
        assert sell == price


# ═══════════════════════════════════════════════════════════════
# 6. 抽象基类接口测试
# ═══════════════════════════════════════════════════════════════

class TestSlippageModelInterface:
    """验证 SlippageModel 抽象基类接口一致性"""

    def test_all_models_implement_interface(self):
        models = [
            NoSlippage(),
            FixedSlippage(slippage=0.01),
            RatioSlippage(slippage_rate=0.001),
        ]
        for model in models:
            assert isinstance(model, SlippageModel)
            # 接口方法存在且可调用
            assert hasattr(model, "calc_buy_price")
            assert hasattr(model, "calc_sell_price")
            # 验证返回 float
            result = model.calc_buy_price(100.0)
            assert isinstance(result, float)
            result = model.calc_sell_price(100.0)
            assert isinstance(result, float)

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            SlippageModel()


# ═══════════════════════════════════════════════════════════════
# 7. 精度与一致性测试
# ═══════════════════════════════════════════════════════════════

class TestPrecisionConsistency:
    """数值精度与一致性测试"""

    def test_fixed_slippage_precision(self):
        model = FixedSlippage(slippage=0.001)
        # 使用高精度价格
        price = 10.555
        buy = model.calc_buy_price(price)
        sell = model.calc_sell_price(price)
        assert buy == pytest.approx(10.556)
        assert sell == pytest.approx(10.554)

    def test_ratio_slippage_precision(self):
        model = RatioSlippage(slippage_rate=0.001)
        price = 10.555
        buy = model.calc_buy_price(price)
        sell = model.calc_sell_price(price)
        assert buy == pytest.approx(10.565555)
        assert sell == pytest.approx(10.544445)

    def test_symmetry_ratio_slippage(self):
        """比例滑点：相同的比率对买入和卖出是对称的"""
        model = RatioSlippage(slippage_rate=0.01)
        price = 100.0
        buy = model.calc_buy_price(price)
        sell = model.calc_sell_price(price)
        # 买入上浮的比例 == 卖出下浮的比例
        # buy/price + sell/price ≈ 2 (忽略高阶小量)
        assert (buy / price) + (sell / price) == pytest.approx(2.0, rel=1e-6)

    def test_consistent_spread_across_prices_fixed(self):
        """固定滑点：不同价格下买卖价差一致"""
        model = FixedSlippage(slippage=0.5)
        for price in [1.0, 10.0, 100.0, 1000.0]:
            buy = model.calc_buy_price(price)
            sell = model.calc_sell_price(price)
            assert buy - sell == pytest.approx(1.0)  # 2 * slippage = 1.0


# ═══════════════════════════════════════════════════════════════
# 主入口（支持直接运行）
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])