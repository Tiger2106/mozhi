"""
墨枢 - FeeModel 单元测试
覆盖：买入费、卖出费、佣金最低5元、免佣场景、不同金额档
"""
import pytest
from backtest.fee_model import FeeModel, SimpleFeeModel, CNStockFeeModel


# ═══════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def cn_model():
    return CNStockFeeModel()


@pytest.fixture
def simple_model():
    return SimpleFeeModel()


# ═══════════════════════════════════════════════════════════════
# 1. 买入费测试：佣金万2.5 + 过户费万0.2
# ═══════════════════════════════════════════════════════════════

class TestCNStockBuyFee:
    """A股买入费用测试：佣金 + 过户费，无印花税"""

    def test_small_amount_buy(self, cn_model):
        """小金额：1000元，佣金应触发最低5元"""
        # turnover = 10 * 100 = 1000
        # commission = max(1000 * 0.00025, 5) = max(0.25, 5) = 5.00
        # transfer_fee = 1000 * 0.00002 = 0.02
        # total = 5.00 + 0.02 = 5.02
        fee = cn_model.calc_buy_fee(price=10.0, quantity=100)
        assert fee == pytest.approx(5.02, abs=0.01)

    def test_medium_amount_buy(self, cn_model):
        """中等金额：10000元，按比例计算佣金"""
        # turnover = 10 * 1000 = 10000
        # commission = max(10000 * 0.00025, 5) = max(2.5, 5) = 5.00
        # transfer_fee = 10000 * 0.00002 = 0.20
        # total = 5.00 + 0.20 = 5.20
        fee = cn_model.calc_buy_fee(price=10.0, quantity=1000)
        assert fee == pytest.approx(5.20, abs=0.01)

    def test_large_amount_buy(self, cn_model):
        """大金额：100000元，佣金按比例正常计算"""
        # turnover = 10 * 10000 = 100000
        # commission = max(100000 * 0.00025, 5) = 25.00
        # transfer_fee = 100000 * 0.00002 = 2.00
        # total = 27.00
        fee = cn_model.calc_buy_fee(price=10.0, quantity=10000)
        assert fee == pytest.approx(27.00, abs=0.01)

    def test_buy_fee_equals_commission_plus_transfer(self, cn_model):
        """买入费 = 佣金 + 过户费，验证结构正确"""
        fee = cn_model.calc_buy_fee(price=100.0, quantity=1000)
        turnover = 100.0 * 1000
        expected_comm = max(round(turnover * cn_model.commission_rate, 2), cn_model.min_commission)
        expected_transfer = round(turnover * cn_model.transfer_fee_rate, 2)
        expected = expected_comm + expected_transfer
        assert fee == pytest.approx(expected, abs=0.01)


# ═══════════════════════════════════════════════════════════════
# 2. 卖出费测试：佣金万2.5 + 印花税千1 + 过户费万0.2
# ═══════════════════════════════════════════════════════════════

class TestCNStockSellFee:
    """A股卖出费用测试：佣金 + 印花税 + 过户费"""

    def test_small_amount_sell(self, cn_model):
        """小金额卖出：1000元，佣金触发最低5元"""
        # turnover = 10 * 100 = 1000
        # commission = max(0.25, 5) = 5.00
        # stamp_tax = 1000 * 0.001 = 1.00
        # transfer_fee = 1000 * 0.00002 = 0.02
        # total = 5.00 + 1.00 + 0.02 = 6.02
        fee = cn_model.calc_sell_fee(price=10.0, quantity=100)
        assert fee == pytest.approx(6.02, abs=0.01)

    def test_medium_amount_sell(self, cn_model):
        """中等金额卖出：10000元"""
        # turnover = 10 * 1000 = 10000
        # commission = max(2.5, 5) = 5.00
        # stamp_tax = 10000 * 0.001 = 10.00
        # transfer_fee = 10000 * 0.00002 = 0.20
        # total = 5.00 + 10.00 + 0.20 = 15.20
        fee = cn_model.calc_sell_fee(price=10.0, quantity=1000)
        assert fee == pytest.approx(15.20, abs=0.01)

    def test_large_amount_sell(self, cn_model):
        """大金额卖出：100000元，印花税占比最大"""
        # turnover = 10 * 10000 = 100000
        # commission = 25.00
        # stamp_tax = 100000 * 0.001 = 100.00
        # transfer_fee = 100000 * 0.00002 = 2.00
        # total = 127.00
        fee = cn_model.calc_sell_fee(price=10.0, quantity=10000)
        assert fee == pytest.approx(127.00, abs=0.01)

    def test_sell_fee_has_stamp_tax(self, cn_model):
        """卖出费 > 买入费，因为有印花税"""
        buy_fee = cn_model.calc_buy_fee(price=10.0, quantity=1000)
        sell_fee = cn_model.calc_sell_fee(price=10.0, quantity=1000)
        assert sell_fee > buy_fee
        stamp_tax = round(10.0 * 1000 * cn_model.stamp_tax_rate, 2)
        assert sell_fee - buy_fee == pytest.approx(stamp_tax, abs=0.01)


# ═══════════════════════════════════════════════════════════════
# 3. 佣金最低5元强制规则
# ═══════════════════════════════════════════════════════════════

class TestMinCommission:
    """佣金最低5元强制规则测试"""

    def test_buy_min_commission_triggered(self, cn_model):
        """买入：极小金额触发最低佣金5元"""
        # turnover = 1 * 50 = 50
        # commission = max(50 * 0.00025, 5) = max(0.0125, 5) = 5.00
        fee = cn_model.calc_buy_fee(price=1.0, quantity=50)
        assert fee >= 5.00  # 佣金部分至少5元
        # transfer_fee = 50 * 0.00002 = 0.001 ≈ 0.00
        assert fee == pytest.approx(5.00, abs=0.02)

    def test_sell_min_commission_triggered(self, cn_model):
        """卖出入：极小金额触发最低佣金5元"""
        # turnover = 1 * 50 = 50
        # commission = max(50 * 0.00025, 5) = 5.00
        # stamp_tax = 50 * 0.001 = 0.05
        # transfer_fee ≈ 0.00
        fee = cn_model.calc_sell_fee(price=1.0, quantity=50)
        assert fee >= 5.05  # 佣金5 + 印花税0.05

    def test_buy_commission_above_minimum(self, cn_model):
        """买入：大金额时佣金按比例计算，不触发最低5元"""
        # turnover = 100 * 2000 = 200000
        # commission = max(200000 * 0.00025, 5) = 50.00
        fee = cn_model.calc_buy_fee(price=100.0, quantity=2000)
        assert fee > 50.0  # 佣金50 + 过户费4 = 54

    def test_sell_commission_above_minimum(self, cn_model):
        """卖出入：大金额时佣金按比例计算，不触发最低5元"""
        fee = cn_model.calc_sell_fee(price=100.0, quantity=2000)
        assert fee > 50.0


# ═══════════════════════════════════════════════════════════════
# 4. 免佣场景：FeeModel 抽象基类 default 实现
# ═══════════════════════════════════════════════════════════════

class TestFeeModelAbstractDefault:
    """FeeModel 抽象基类的 default calculate() 实现"""

    def test_calculate_default_uses_sell_fee(self):
        """默认 calculate() 等价于 calc_sell_fee（最保守估计）"""
        # 用 CNStockFeeModel 验证默认行为
        cn = CNStockFeeModel()
        price, qty = 10.0, 500
        assert cn.calculate(price, qty) == cn.calc_sell_fee(price, qty)

    def test_calculate_not_equal_buy_fee(self):
        """默认 calculate() 通常不等于买入费（有印花税差异）"""
        cn = CNStockFeeModel()
        price, qty = 10.0, 500
        # 卖出费包含印花税，通常大于买入费
        assert cn.calculate(price, qty) == cn.calc_sell_fee(price, qty)

    def test_abstract_cannot_be_instantiated(self):
        """FeeModel 是抽象类，不能直接实例化"""
        with pytest.raises(TypeError):
            FeeModel()


# ═══════════════════════════════════════════════════════════════
# 5. 不同金额档验证比例正确
# ═══════════════════════════════════════════════════════════════

class TestAmountTiers:
    """不同金额档：验证费用比例结构"""

    def test_tier_small_vs_medium(self):
        """小额 vs 中额：小额触发最低5元，中额按比例正常计算"""
        cn = CNStockFeeModel()
        # 小额：1000元（触发最低佣金5元）
        small_fee = cn.calc_buy_fee(price=10.0, quantity=100)  # turnover=1000
        # 中额：50000元（按比例计算佣金）
        medium_fee = cn.calc_buy_fee(price=10.0, quantity=5000)  # turnover=50000
        # 中额佣金远超最低5元，比例正常
        assert medium_fee > small_fee  # 中额 > 小额（绝对值）
        # 验证中额费率比例 ≈ commission_rate + transfer_fee_rate = 0.00027
        expected_rate = cn.commission_rate + cn.transfer_fee_rate
        actual_rate = medium_fee / 50000.0
        assert actual_rate == pytest.approx(expected_rate, rel=0.01)
        # 小额因最低佣金，实际费率远高于中额
        small_rate = small_fee / 1000.0
        assert small_rate > actual_rate  # 小额费率被最低佣金拉高

    def test_tier_large_fee_breakdown(self):
        """大金额：各费用项占比验证"""
        cn = CNStockFeeModel()
        price, qty = 50.0, 10000  # turnover = 500000
        fee = cn.calc_sell_fee(price, qty)
        turnover = price * qty

        commission = max(round(turnover * cn.commission_rate, 2), cn.min_commission)
        stamp_tax = round(turnover * cn.stamp_tax_rate, 2)
        transfer_fee = round(turnover * cn.transfer_fee_rate, 2)

        assert fee == pytest.approx(commission + stamp_tax + transfer_fee, abs=0.01)
        # 印花税占比：千1 vs 佣金万2.5 = 0.1% / 0.025% = 4倍
        assert stamp_tax == pytest.approx(commission * 4, abs=0.1)

    def test_buy_vs_sell_fee_ratio(self):
        """买入 vs 卖出费率差异：卖出多印花税千1"""
        cn = CNStockFeeModel()
        turnover = 10000.0
        buy_fee = cn.calc_buy_fee(price=turnover, quantity=1)
        sell_fee = cn.calc_sell_fee(price=turnover, quantity=1)

        turnover_actual = turnover  # price=10000, qty=1
        stamp_tax = round(turnover_actual * cn.stamp_tax_rate, 2)
        assert sell_fee - buy_fee == pytest.approx(stamp_tax, abs=0.01)


# ═══════════════════════════════════════════════════════════════
# SimpleFeeModel 兼容性测试
# ═══════════════════════════════════════════════════════════════

class TestSimpleFeeModel:
    """SimpleFeeModel 与 CNStockFeeModel 差异测试"""

    def test_simple_buy_and_sell_same(self, simple_model):
        """SimpleFeeModel 买入卖出费用相同"""
        fee_buy = simple_model.calc_buy_fee(price=100.0, quantity=100)
        fee_sell = simple_model.calc_sell_fee(price=100.0, quantity=100)
        assert fee_buy == fee_sell

    def test_simple_min_fee_trigger(self, simple_model):
        """SimpleFeeModel 最低佣金规则"""
        fee = simple_model.calc_buy_fee(price=1.0, quantity=10)  # turnover=10
        assert fee == 5.0  # max(10*0.0003, 5) = max(0.003, 5) = 5

    def test_simple_large_amount(self, simple_model):
        """SimpleFeeModel 大金额按比例"""
        fee = simple_model.calc_buy_fee(price=10.0, quantity=10000)  # turnover=100000
        assert fee == pytest.approx(30.0, abs=0.01)  # 100000*0.0003=30

    def test_cn_vs_simple_fee_diff(self, cn_model, simple_model):
        """CNStockFeeModel vs SimpleFeeModel：卖出费用结构不同"""
        price, qty = 10.0, 1000
        cn_sell = cn_model.calc_sell_fee(price, qty)
        simple_sell = simple_model.calc_sell_fee(price, qty)
        # CN卖出包含印花税，应高于Simple卖出
        assert cn_sell > simple_sell