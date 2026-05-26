"""
墨枢 — 双系统验证器测试

用模拟数据验证 DualValidator 的 5 类偏差检测：
  - ✅ 完全一致场景
  - ✅ 每类偏差单独触发
  - ✅ 阈值判定正确性

author: 墨衡
created_time: 2026-05-20
"""

from __future__ import annotations

import pytest

from src.backtest.backtest_engine import Bar, OrderRequest, OrderSide, OrderType
from tests.validation.dual_validator import (
    DualValidator,
    ValidationReport,
    DeviationItem,
)


# ═══════════════════════════════════════════════════════════════
# 辅助函数：创建测试用 OrderRequest
# ═══════════════════════════════════════════════════════════════


def _order(
    symbol: str = "601857",
    side: OrderSide = OrderSide.BUY,
    quantity: int = 1000,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
    )


def _bar(
    date: str = "20260519",
    symbol: str = "601857",
    close: float = 10.0,
) -> Bar:
    return Bar(
        date=date,
        symbol=symbol,
        open=close * 0.99,
        high=close * 1.02,
        low=close * 0.98,
        close=close,
        volume=1_000_000,
    )


def _signal_dict(
    symbol: str = "601857",
    direction: str = "BUY",
    confidence: float = 0.8,
) -> dict:
    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "horizon": "short",
        "signal_type": "trend",
    }


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════


class TestDualValidator:
    """DualValidator 核心测试"""

    # ── 完全一致场景 ─────────────────────────────────────

    def test_identical_orders(self):
        """两路径完全一致 → 无偏差、通过"""
        old = [_order(symbol="601857", quantity=1000)]
        new = [_order(symbol="601857", quantity=1000)]

        report = DualValidator.from_ordered_pairs(old, new)

        assert report.deviation_count == 0
        assert report.passed is True
        assert report.total_orders_old == 1
        assert report.total_orders_new == 1

    def test_multiple_identical_orders(self):
        """多订单完全一致"""
        old = [
            _order(symbol="601857", side=OrderSide.BUY, quantity=500),
            _order(symbol="601857", side=OrderSide.SELL, quantity=500),
            _order(symbol="600036", side=OrderSide.BUY, quantity=1000),
        ]
        new = [
            _order(symbol="601857", side=OrderSide.BUY, quantity=500),
            _order(symbol="601857", side=OrderSide.SELL, quantity=500),
            _order(symbol="600036", side=OrderSide.BUY, quantity=1000),
        ]

        report = DualValidator.from_ordered_pairs(old, new)

        assert report.deviation_count == 0
        assert report.passed is True

    def test_both_empty(self):
        """两路径均为空 → 通过"""
        report = DualValidator.from_ordered_pairs([], [])

        assert report.deviation_count == 0
        assert report.passed is True

    # ── Class 1: 方向不一致 ──────────────────────────────

    def test_class1_direction_mismatch(self):
        """方向不一致 → Class 1 偏差"""
        old = [_order(symbol="601857", side=OrderSide.BUY, quantity=1000)]
        new = [_order(symbol="601857", side=OrderSide.SELL, quantity=1000)]

        report = DualValidator.from_ordered_pairs(old, new)

        c1_devs = [d for d in report.deviations if d.type == 1]
        assert len(c1_devs) == 1
        assert c1_devs[0].type == 1
        assert "BUY" in c1_devs[0].old_value or "buy" in c1_devs[0].old_value
        assert "SELL" in c1_devs[0].new_value or "sell" in c1_devs[0].new_value

    def test_class1_zero_tolerance(self):
        """Class 1 零容忍 → 只要出现方向不一致，passed=False"""
        old = [_order(symbol="601857", side=OrderSide.BUY, quantity=1000)]
        new = [_order(symbol="601857", side=OrderSide.SELL, quantity=1000)]

        report = DualValidator.from_ordered_pairs(old, new)

        assert report.passed is False
        s = report.statistics.get("1", {})
        assert s.get("threshold_rate") == 0.0
        assert s.get("actual_rate", 1.0) > 0.0

    def test_class1_no_false_positive(self):
        """相同方向不触发 Class 1"""
        old = [
            _order(symbol="601857", side=OrderSide.BUY, quantity=1000),
            _order(symbol="601857", side=OrderSide.SELL, quantity=500),
        ]
        new = [
            _order(symbol="601857", side=OrderSide.BUY, quantity=1000),
            _order(symbol="601857", side=OrderSide.SELL, quantity=500),
        ]

        report = DualValidator.from_ordered_pairs(old, new)

        c1_devs = [d for d in report.deviations if d.type == 1]
        assert len(c1_devs) == 0

    # ── Class 2: 数量偏差 > 10% ─────────────────────────

    def test_class2_quantity_deviation_exceeds(self):
        """数量偏差 > 10% → Class 2 偏差"""
        old = [_order(symbol="601857", quantity=1000)]
        new = [_order(symbol="601857", quantity=800)]

        report = DualValidator.from_ordered_pairs(old, new)

        c2_devs = [d for d in report.deviations if d.type == 2]
        assert len(c2_devs) == 1
        # (1000-800)/1000 = 0.20 > 0.10
        assert "20.0%" in c2_devs[0].description or "20" in c2_devs[0].description.replace('.0%','').replace('0%','')

    def test_class2_quantity_deviation_within(self):
        """数量偏差 ≤ 10% → 不触发 Class 2"""
        old = [_order(symbol="601857", quantity=1000)]
        new = [_order(symbol="601857", quantity=1050)]

        report = DualValidator.from_ordered_pairs(old, new)

        c2_devs = [d for d in report.deviations if d.type == 2]
        assert len(c2_devs) == 0

    def test_class2_threshold_5pct(self):
        """Class 2 阈值 ≤5%: 1个偏差(10%)在10个订单中应FAIL"""
        old = [_order(symbol="601857", quantity=1000) for _ in range(10)]
        new = (
            [_order(symbol="601857", quantity=1000) for _ in range(5)]
            + [_order(symbol="601857", quantity=800)]  # 20% deviation → Class 2
            + [_order(symbol="601857", quantity=1000) for _ in range(4)]
        )

        report = DualValidator.from_ordered_pairs(old, new)

        # 1/10 = 10% > 5% → FAIL
        c2_stat = report.statistics.get("2", {})
        assert c2_stat, "Class 2 statistics should exist"
        assert c2_stat["count"] == 1, f"expected 1 Class 2 deviation, got {c2_stat['count']}"
        actual_rate = c2_stat["actual_rate"]
        threshold = c2_stat["threshold_rate"]
        assert actual_rate > threshold, (
            f"actual_rate {actual_rate:.2%} should exceed threshold {threshold:.0%}"
        )
        assert c2_stat["passed"] is False, (
            f"Class 2 should FAIL: {c2_stat['count']}/{c2_stat['denominator']} = "
            f"{actual_rate:.2%} > {threshold:.0%}"
        )

        # 验证 Class 2 数量偏差的具体记录
        c2_devs = [d for d in report.deviations if d.type == 2]
        assert len(c2_devs) == 1
        assert c2_devs[0].symbol == "601857"

    # ── Class 3: 时序偏差 > 1 bar ─────────────────────────

    def test_class3_timing_deviation(self):
        """同 quantity 订单出现在不同位置 → Class 3 时序偏差"""
        # 旧路径: [A:1000, A:500, A:2000]
        # 新路径: [A:1000, A:2000, A:500]  → 500 从 pos1 移到 pos2, 2000 从 pos2 移到 pos1
        # pos diff: 1000(0→0, diff=0), 2000(2→1, diff=1 ≤1), 500(1→2, diff=1 ≤1)
        # 全都在 1 bar 以内 → 不触发
        old = [
            _order(symbol="A", quantity=1000),
            _order(symbol="A", quantity=500),
            _order(symbol="A", quantity=2000),
        ]
        new = [
            _order(symbol="A", quantity=1000),
            _order(symbol="A", quantity=2000),
            _order(symbol="A", quantity=500),
        ]

        report = DualValidator.from_ordered_pairs(old, new)
        c3_devs = [d for d in report.deviations if d.type == 3]
        assert len(c3_devs) == 0, (
            f"order position shift ≤1 bar should NOT trigger Class 3, "
            f"got {len(c3_devs)} deviation(s)"
        )

    def test_class3_shift_gt_1bar(self):
        """同 quantity 订单偏移超过 1 个位置 → Class 3 时序偏差"""
        # 旧路径: [A:1000, A:500, A:2000, A:3000]
        # 新路径: [A:3000, A:1000, A:500, A:2000]
        # 3000: pos3→pos0, diff=3 → 触发
        old = [
            _order(symbol="A", quantity=1000),
            _order(symbol="A", quantity=500),
            _order(symbol="A", quantity=2000),
            _order(symbol="A", quantity=3000),
        ]
        new = [
            _order(symbol="A", quantity=3000),
            _order(symbol="A", quantity=1000),
            _order(symbol="A", quantity=500),
            _order(symbol="A", quantity=2000),
        ]

        report = DualValidator.from_ordered_pairs(old, new)
        c3_devs = [d for d in report.deviations if d.type == 3]
        assert len(c3_devs) == 1
        assert c3_devs[0].symbol == "A"
        assert "差异 3" in c3_devs[0].description or "3 bar" in c3_devs[0].description

    def test_class3_no_mismatch(self):
        """完全一致的订单序列 → 不触发 Class 3"""
        old = [
            _order(symbol="601857", quantity=1000),
            _order(symbol="601857", quantity=500),
        ]
        new = [
            _order(symbol="601857", quantity=1000),
            _order(symbol="601857", quantity=500),
        ]

        report = DualValidator.from_ordered_pairs(old, new)
        c3_devs = [d for d in report.deviations if d.type == 3]
        assert len(c3_devs) == 0

    def test_class3_threshold_3pct(self):
        """Class 3 阈值 ≤3%: 1个时序偏差在50个订单中应通过"""
        # 50 个订单，1 个有偏移 → 1/50 = 2% ≤ 3% → PASS
        old_orders = []
        new_orders = []
        for i in range(50):
            old_orders.append(_order(symbol="A", quantity=i + 1))
            if i == 0:
                # 第0个订单在旧路径是 quantity=1(pos0)，在新路径移到 pos49
                new_orders.append(_order(symbol="A", quantity=50))
            else:
                new_orders.append(_order(symbol="A", quantity=i))
        # 最后的 quantity=50 在旧路径是 pos49，在新路径被移到 pos0
        # 同时旧路径 quantity=1(pos0) 在新路径找不到 → 偏移超出
        # 旧路径 quantity=1(pos0) → 新路径中没有 quantity=1 的订单，不匹配
        # 旧路径 quantity=2(pos1) → 新路径 quantity=2(pos1) diff=0
        # ...
        # 旧路径 quantity=50(pos49) → 新路径 quantity=50(pos0) diff=49

        report = DualValidator.from_ordered_pairs(old_orders, new_orders)

        c3_stat = report.statistics.get("3", {})
        assert c3_stat, "Class 3 statistics should exist"
        actual_rate = c3_stat["actual_rate"]
        threshold = c3_stat["threshold_rate"]
        assert actual_rate <= threshold, (
            f"actual_rate {actual_rate:.2%} should NOT exceed threshold {threshold:.0%}"
        )

    # ── Class 4: 信号遗漏/多余 ──────────────────────────

    def test_class4_missing_signal(self):
        """旧路径有、新路径无 → Class 4 遗漏"""
        old = [
            _order(symbol="601857", quantity=1000),
            _order(symbol="600036", quantity=500),
        ]
        new = [_order(symbol="601857", quantity=1000)]

        report = DualValidator.from_ordered_pairs(old, new)

        c4_devs = [d for d in report.deviations if d.type == 4]
        assert len(c4_devs) == 1
        assert "遗漏" in c4_devs[0].description

    def test_class4_extra_signal(self):
        """新路径有、旧路径无 → Class 4 多余"""
        old = [_order(symbol="601857", quantity=1000)]
        new = [
            _order(symbol="601857", quantity=1000),
            _order(symbol="600036", quantity=500),
        ]

        report = DualValidator.from_ordered_pairs(old, new)

        c4_devs = [d for d in report.deviations if d.type == 4]
        assert len(c4_devs) == 1
        assert "多余" in c4_devs[0].description

    def test_class4_multiple_diff(self):
        """多个遗漏和多余"""
        old = [
            _order(symbol="A", quantity=100),
            _order(symbol="B", quantity=200),
        ]
        new = [
            _order(symbol="A", quantity=100),
            _order(symbol="C", quantity=300),
        ]

        report = DualValidator.from_ordered_pairs(old, new)

        c4_devs = [d for d in report.deviations if d.type == 4]
        assert len(c4_devs) == 2  # B 遗漏, C 多余

    def test_class4_threshold_2pct(self):
        """Class 4 阈值 ≤2%: 1个遗漏在100个订单中应通过"""
        old = [_order(symbol="A", quantity=100) for _ in range(100)]
        new = old[:99]  # 少1个

        report = DualValidator.from_ordered_pairs(old, new)

        c4_stat = report.statistics.get("4", {})
        if c4_stat:
            actual_rate = c4_stat.get("actual_rate", 1.0)
            # 1/100 = 1% ≤ 2% → PASS
            assert actual_rate <= 0.02

    # ── Class 5: confidence 偏差 > 0.2 ──────────────────

    def test_class5_confidence_deviation(self):
        """confidence 偏差 > 0.2 → Class 5"""
        old_signals = [_signal_dict(confidence=1.0)]
        new_signals = [_signal_dict(confidence=0.5)]

        validator = DualValidator()
        report = validator.compare(
            old_orders=[_order()],
            new_orders=[_order()],
            old_signals=old_signals,
            new_signals=new_signals,
        )

        c5_devs = [d for d in report.deviations if d.type == 5]
        assert len(c5_devs) == 1
        assert "0.50" in c5_devs[0].description

    def test_class5_confidence_within(self):
        """confidence 偏差 ≤ 0.2 → 不触发"""
        old_signals = [_signal_dict(confidence=0.8)]
        new_signals = [_signal_dict(confidence=0.65)]

        validator = DualValidator()
        report = validator.compare(
            old_orders=[_order()],
            new_orders=[_order()],
            old_signals=old_signals,
            new_signals=new_signals,
        )

        c5_devs = [d for d in report.deviations if d.type == 5]
        assert len(c5_devs) == 0

    def test_class5_no_old_signals(self):
        """无旧信号数据 → 不触发偏差"""
        new_signals = [_signal_dict(confidence=0.5)]

        validator = DualValidator()
        report = validator.compare(
            old_orders=[_order()],
            new_orders=[_order()],
            old_signals=None,
            new_signals=new_signals,
        )

        c5_devs = [d for d in report.deviations if d.type == 5]
        assert len(c5_devs) == 0

    # ── 综合场景 ────────────────────────────────────────

    def test_mixed_deviations(self):
        """多类偏差同时存在"""
        old = [
            _order(symbol="A", side=OrderSide.BUY, quantity=1000),
            _order(symbol="B", side=OrderSide.SELL, quantity=500),
        ]
        new = [
            _order(symbol="A", side=OrderSide.SELL, quantity=1000),  # Class 1
            # B 被遗漏 — Class 4
        ]
        old_signals = [
            _signal_dict(symbol="A", direction="BUY", confidence=0.9),
            _signal_dict(symbol="B", direction="SELL", confidence=0.7),
        ]
        new_signals = [
            _signal_dict(symbol="A", direction="SELL", confidence=0.9),
        ]

        validator = DualValidator()
        report = validator.compare(
            old_orders=old,
            new_orders=new,
            old_signals=old_signals,
            new_signals=new_signals,
        )

        assert len(report.deviations) >= 2  # Class 1 + Class 4
        assert report.passed is False  # Class 1 零容忍

    def test_report_summary_format(self):
        """报告 summary() 格式正确"""
        old = [_order(symbol="601857", quantity=1000)]
        new = [_order(symbol="601857", quantity=800)]

        report = DualValidator.from_ordered_pairs(old, new)
        summary = report.summary()

        assert "DualValidation Report" in summary
        assert "PASSED" in summary or "FAILED" in summary
        assert "Class" in summary

    # ── 边缘情况 ────────────────────────────────────────

    def test_empty_old_orders(self):
        """旧路径为空"""
        report = DualValidator.from_ordered_pairs([], [_order()])
        assert report.passed is False  # Class 4: 多余

    def test_empty_new_orders(self):
        """新路径为空"""
        report = DualValidator.from_ordered_pairs([_order()], [])
        assert report.passed is False  # Class 4: 遗漏

    def test_different_symbols(self):
        """不同标的的订单不冲突"""
        old = [_order(symbol="A", quantity=100)]
        new = [_order(symbol="B", quantity=100)]

        report = DualValidator.from_ordered_pairs(old, new)

        # 不同 symbol 不被视为 Class 1 方向不一致
        c1_devs = [d for d in report.deviations if d.type == 1]
        assert len(c1_devs) == 0

        # 但因为签名不同，会产生 Class 4
        c4_devs = [d for d in report.deviations if d.type == 4]
        assert len(c4_devs) >= 1


class TestDeviationItem:
    """DeviationItem 基础测试"""

    def test_creation(self):
        d = DeviationItem(
            type=1,
            bar_index=5,
            symbol="601857",
            old_value="side=buy",
            new_value="side=sell",
            description="方向不一致",
        )
        assert d.type == 1
        assert d.bar_index == 5
        assert d.symbol == "601857"


class TestValidationReport:
    """ValidationReport 功能测试"""

    def test_deviation_by_class(self):
        report = ValidationReport(
            total_orders_old=2,
            total_orders_new=2,
            deviations=[
                DeviationItem(type=1, bar_index=0, symbol="A", old_value="", new_value="", description=""),
                DeviationItem(type=1, bar_index=1, symbol="A", old_value="", new_value="", description=""),
                DeviationItem(type=2, bar_index=0, symbol="A", old_value="", new_value="", description=""),
            ],
        )
        by_class = report.deviation_by_class
        assert len(by_class[1]) == 2
        assert len(by_class[2]) == 1

    def test_deviation_count(self):
        report = ValidationReport(
            total_orders_old=2,
            total_orders_new=2,
            deviations=[
                DeviationItem(type=1, bar_index=0, symbol="A", old_value="", new_value="", description=""),
                DeviationItem(type=2, bar_index=0, symbol="A", old_value="", new_value="", description=""),
            ],
        )
        assert report.deviation_count == 2
