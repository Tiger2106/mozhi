"""
墨枢 — 双系统并行验证器

DualValidator 在每次回测运行时同时执行新旧两条路径并比较输出：

  旧路径：Strategy → SignalBridge → OrderRequest（原样）
  新路径：Strategy → Signal → SignalConsumer → OrderRequest

比较两路径的 OrderRequest 列表，按 5 类偏差分类统计。

5 类偏差阈值（Stage 3 D5 定义）：
  Class 1: 方向不一致（BUY vs SELL）         — 0%（零容忍）
  Class 2: 数量偏差 > 10%                     — ≤5% 的订单
  Class 3: 时序偏差 > 1 bar                   — ≤3% 的订单
  Class 4: 信号遗漏/多余                      — ≤2% 的总信号数
  Class 5: confidence 偏差 > 0.2              — ≤10% 的订单

author: 墨衡
created_time: 2026-05-20
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.backtest.backtest_engine import Bar, OrderRequest, OrderSide


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class DeviationItem:
    """单条偏差记录。

    Attributes:
        type: 偏差类别 (1=方向, 2=数量, 3=时序, 4=遗漏/多余, 5=confidence)
        bar_index: 偏差发生的 Bar 序号（-1 表示全局性偏差）
        symbol: 标的代码
        old_value: 旧路径值（字符串适化输出）
        new_value: 新路径值
        description: 偏差描述
    """

    type: int
    bar_index: int
    symbol: str
    old_value: str
    new_value: str
    description: str


@dataclass
class ValidationReport:
    """双系统验证报告。

    Attributes:
        total_orders_old: 旧路径总订单数
        total_orders_new: 新路径总订单数
        deviations: 所有偏差记录列表
        passed: 是否全部通过阈值检查
        statistics: 每类偏差的统计结果字典
    """

    total_orders_old: int = 0
    total_orders_new: int = 0
    deviations: List[DeviationItem] = field(default_factory=list)
    passed: bool = True
    statistics: Dict[str, Any] = field(default_factory=dict)

    @property
    def deviation_count(self) -> int:
        """偏差总数"""
        return len(self.deviations)

    @property
    def deviation_by_class(self) -> Dict[int, List[DeviationItem]]:
        """按类别分组的偏差"""
        by_class: Dict[int, List[DeviationItem]] = {}
        for d in self.deviations:
            by_class.setdefault(d.type, []).append(d)
        return by_class

    def summary(self) -> str:
        """生成简要总结文本"""
        lines = [
            f"DualValidation Report",
            f"  旧路径订单数: {self.total_orders_old}",
            f"  新路径订单数: {self.total_orders_new}",
            f"  偏差总数: {self.deviation_count}",
            f"  ═══ PASSED ═══" if self.passed else f"  ═══ FAILED ═══",
        ]
        for class_id in sorted(self.statistics.keys()):
            s = self.statistics[class_id]
            lines.append(
                f"  Class {class_id}: {s.get('count', 0)} 偏差, "
                f"阈值 {s.get('threshold_display', 'N/A')}, "
                f"实际 {s.get('actual_rate_display', 'N/A')} "
                f"{'✅' if s.get('passed', True) else '❌'}"
            )
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# DualValidator
# ═══════════════════════════════════════════════════════════════


THRESHOLDS = {
    1: {"rate": 0.0, "display": "0%", "description": "方向不一致（BUY vs SELL）"},
    2: {"rate": 0.05, "display": "≤5%", "description": "数量偏差 > 10%"},
    3: {"rate": 0.03, "display": "≤3%", "description": "时序偏差 > 1 bar"},
    4: {"rate": 0.02, "display": "≤2%", "description": "信号遗漏/多余"},
    5: {"rate": 0.10, "display": "≤10%", "description": "confidence 偏差 > 0.2"},
}


class DualValidator:
    """双系统并行验证器。

    比较新旧两条路径输出的 OrderRequest 列表，
    按 5 类偏差检测并生成 ValidationReport。

    使用示例::

        validator = DualValidator()
        old_orders = [OrderRequest(symbol="601857", side=OrderSide.BUY, quantity=1000, ...)]
        new_orders = [OrderRequest(symbol="601857", side=OrderSide.BUY, quantity=800, ...)]

        report = validator.compare(old_orders, new_orders)
        print(report.summary())
        assert report.passed
    """

    def compare(
        self,
        old_orders: List[OrderRequest],
        new_orders: List[OrderRequest],
        old_signals: Optional[List[Any]] = None,
        new_signals: Optional[List[Any]] = None,
        context_bars: Optional[List[Bar]] = None,
    ) -> ValidationReport:
        """比较新旧两条路径的 OrderRequest 输出。

        Args:
            old_orders: 旧路径（SignalBridge）输出的 OrderRequest 列表。
            new_orders: 新路径（Signal+Consumer）输出的 OrderRequest 列表。
            old_signals: 旧路径生成的原生信号（可选，用于 Class 4/5 检测）。
            new_signals: 新路径生成的 Signal 对象列表（可选，用于 Class 5 检测）。
            context_bars: 回测 Bar 列表（可选，用于 Class 3 时序偏差检测）。

        Returns:
            ValidationReport: 包含所有偏差检测结果的报告。
        """
        deviations: List[DeviationItem] = []

        # ── Class 1: 方向不一致 ────────────────────────────────
        c1_devs = self._check_direction(old_orders, new_orders)
        deviations.extend(c1_devs)

        # ── Class 2: 数量偏差 > 10% ────────────────────────────
        c2_devs = self._check_quantity(old_orders, new_orders)
        deviations.extend(c2_devs)

        # ── Class 3: 时序偏差 > 1 bar ──────────────────────────
        c3_devs = self._check_timing(
            old_orders, new_orders, context_bars or []
        )
        deviations.extend(c3_devs)

        # ── Class 4: 信号遗漏/多余 ─────────────────────────────
        c4_devs = self._check_missing_extra(
            old_orders, new_orders,
            old_signals or old_orders, new_signals or new_orders,
        )
        deviations.extend(c4_devs)

        # ── Class 5: confidence 偏差 > 0.2 ─────────────────────
        c5_devs = self._check_confidence(old_signals, new_signals)
        deviations.extend(c5_devs)

        # ── 统计与判定 ─────────────────────────────────────────
        report = self._build_report(
            old_orders, new_orders, deviations,
            old_signals, new_signals,
        )
        return report

    # ═══════════════════════════════════════════════════════════
    # 5 类偏差检测
    # ═══════════════════════════════════════════════════════════

    def _check_direction(
        self, old: List[OrderRequest], new: List[OrderRequest]
    ) -> List[DeviationItem]:
        """Class 1: 方向不一致检测。

        按 symbol 逐批匹配，相同索引位置的订单方向不一致即标记。

        Returns:
            方向偏差列表。
        """
        deviations: List[DeviationItem] = []

        # 按 symbol 分组
        old_by_symbol = self._group_by_symbol(old)
        new_by_symbol = self._group_by_symbol(new)

        all_symbols = set(old_by_symbol.keys()) | set(new_by_symbol.keys())

        for symbol in all_symbols:
            old_list = old_by_symbol.get(symbol, [])
            new_list = new_by_symbol.get(symbol, [])

            max_len = max(len(old_list), len(new_list))
            for i in range(max_len):
                o = old_list[i] if i < len(old_list) else None
                n = new_list[i] if i < len(new_list) else None

                if o is None and n is None:
                    continue
                if o is None or n is None:
                    # 有一方无此订单 — Class 4 会处理，此处跳过
                    continue

                if o.side != n.side:
                    deviations.append(DeviationItem(
                        type=1,
                        bar_index=i,
                        symbol=symbol,
                        old_value=f"side={o.side.value}",
                        new_value=f"side={n.side.value}",
                        description=(
                            f"方向不一致: 旧路径 {o.side.value} "
                            f"vs 新路径 {n.side.value} [symbol={symbol}]"
                        ),
                    ))

        return deviations

    def _check_quantity(
        self, old: List[OrderRequest], new: List[OrderRequest]
    ) -> List[DeviationItem]:
        """Class 2: 数量偏差 > 10% 检测。

        Returns:
            数量偏差列表。
        """
        deviations: List[DeviationItem] = []
        min_total = min(len(old), len(new))

        for i in range(min_total):
            o = old[i]
            n = new[i]
            if o.symbol != n.symbol or o.side != n.side:
                # 非对应订单（Class 1/4 已标记），跳过数量
                continue

            if o.quantity <= 0:
                continue

            deviation_ratio = abs(o.quantity - n.quantity) / o.quantity
            if deviation_ratio > 0.10:
                deviations.append(DeviationItem(
                    type=2,
                    bar_index=i,
                    symbol=o.symbol,
                    old_value=f"qty={o.quantity}",
                    new_value=f"qty={n.quantity}",
                    description=(
                        f"数量偏差 {deviation_ratio:.1%}: "
                        f"旧={o.quantity} 新={n.quantity} [symbol={o.symbol}]"
                    ),
                ))

        return deviations

    def _check_timing(
        self,
        old: List[OrderRequest],
        new: List[OrderRequest],
        context_bars: List[Bar],
    ) -> List[DeviationItem]:
        """Class 3: 时序偏差 > 1 bar 检测。

        对比两个订单列表出现的顺序差异。
        使用 quantity 作为匹配键在同一 symbol+side 组内配对订单，
        然后比较配对订单在各自列表中的位置偏移量。
        若偏移量超过 1（即相差超过 1 bar），标记为时序偏差。

        Args:
            old: 旧路径 OrderRequest 列表。
            new: 新路径 OrderRequest 列表。
            context_bars: 回测 Bar 列表（可选，预留参数）。

        Returns:
            时序偏差列表。
        """
        deviations: List[DeviationItem] = []

        old_by_symbol = self._group_by_symbol(old)
        new_by_symbol = self._group_by_symbol(new)

        all_symbols = set(old_by_symbol.keys()) | set(new_by_symbol.keys())

        for symbol in all_symbols:
            old_list = old_by_symbol.get(symbol, [])
            new_list = new_by_symbol.get(symbol, [])

            for side in (OrderSide.BUY, OrderSide.SELL):
                # 记录每个订单在原始列表中的索引位置
                o_side: List[Tuple[int, OrderRequest]] = [
                    (idx, o) for idx, o in enumerate(old_list) if o.side == side
                ]
                n_side: List[Tuple[int, OrderRequest]] = [
                    (idx, n) for idx, n in enumerate(new_list) if n.side == side
                ]

                # 用 quantity 做匹配键逐对配对（贪心匹配：按旧列表顺序，
                # 在新列表中找第一个相同 quantity 的订单）
                n_remaining: List[Tuple[int, OrderRequest]] = list(n_side)

                for oi, o_order in o_side:
                    # 在新路径剩余订单中寻找同 quantity 的匹配
                    matched_ni: Optional[int] = None
                    for j, (ni, n_order) in enumerate(n_remaining):
                        if n_order.quantity == o_order.quantity:
                            matched_ni = ni
                            n_remaining.pop(j)
                            break

                    if matched_ni is not None:
                        position_diff = abs(oi - matched_ni)
                        if position_diff > 1:
                            deviations.append(DeviationItem(
                                type=3,
                                bar_index=oi,
                                symbol=symbol,
                                old_value=f"pos={oi}",
                                new_value=f"pos={matched_ni}",
                                description=(
                                    f"时序偏差: 旧路径位置 {oi} vs 新路径位置 {matched_ni}, "
                                    f"差异 {position_diff} bar(s) "
                                    f"[symbol={symbol}, side={side.value}]"
                                ),
                            ))

        return deviations

    def _check_missing_extra(
        self,
        old_orders: List[OrderRequest],
        new_orders: List[OrderRequest],
        old_signals: Any,
        new_signals: Any,
    ) -> List[DeviationItem]:
        """Class 4: 信号遗漏/多余检测。

        比较旧路径产生的订单在新路径中是否完全对应。

        Returns:
            遗漏/多余偏差列表。
        """
        deviations: List[DeviationItem] = []

        old_set = self._order_signature_set(old_orders)
        new_set = self._order_signature_set(new_orders)

        # 遗漏：旧路径有但新路径没有
        missing = old_set - new_set
        for sig in missing:
            deviations.append(DeviationItem(
                type=4,
                bar_index=-1,
                symbol=sig.split("|")[0],
                old_value=f"存在订单: {sig}",
                new_value="无对应订单",
                description=f"信号遗漏: 旧路径有此订单但新路径未生成 [{sig}]",
            ))

        # 多余：新路径有但旧路径没有
        extra = new_set - old_set
        for sig in extra:
            deviations.append(DeviationItem(
                type=4,
                bar_index=-1,
                symbol=sig.split("|")[0],
                old_value="无对应订单",
                new_value=f"多余订单: {sig}",
                description=f"信号多余: 新路径生成了旧路径没有的订单 [{sig}]",
            ))

        return deviations

    def _check_confidence(
        self,
        old_signals: Any,
        new_signals: Any,
    ) -> List[DeviationItem]:
        """Class 5: confidence 偏差 > 0.2 检测。

        对比新旧路径信号中的 confidence 值。
        旧路径若无 confidence 概念，默认为 1.0。

        Args:
            old_signals: 旧路径信号数据（可能是 Signal 列表、DataFrame 或 None）
            new_signals: 新路径 Signal 对象列表（可含 confidence 字段）

        Returns:
            confidence 偏差列表。
        """
        deviations: List[DeviationItem] = []

        if new_signals is None or old_signals is None:
            # 缺任意一组信号数据则不检测 confidence 偏差
            return deviations

        new_signal_list = self._normalize_signal_list(new_signals)
        if not new_signal_list:
            return deviations

        old_signal_list = self._normalize_signal_list(old_signals)
        if not old_signal_list:
            return deviations

        max_len = max(len(new_signal_list), len(old_signal_list))
        for i in range(max_len):
            n = new_signal_list[i] if i < len(new_signal_list) else None
            o = old_signal_list[i] if i < len(old_signal_list) else None

            if n is None:
                continue

            new_conf = n.get("confidence", 1.0)
            old_conf = o.get("confidence", 1.0) if o else 1.0

            if abs(new_conf - old_conf) > 0.2:
                deviations.append(DeviationItem(
                    type=5,
                    bar_index=i,
                    symbol=n.get("symbol", "N/A"),
                    old_value=f"confidence={old_conf:.2f}",
                    new_value=f"confidence={new_conf:.2f}",
                    description=(
                        f"confidence 偏差 {abs(new_conf - old_conf):.2f}: "
                        f"旧={old_conf:.2f} 新={new_conf:.2f} [index={i}]"
                    ),
                ))

        return deviations

    # ═══════════════════════════════════════════════════════════
    # 统计与判定
    # ═══════════════════════════════════════════════════════════

    def _build_report(
        self,
        old_orders: List[OrderRequest],
        new_orders: List[OrderRequest],
        deviations: List[DeviationItem],
        old_signals: Any,
        new_signals: Any,
    ) -> ValidationReport:
        """构建验证报告，逐类判定是否通过阈值。"""
        statistics: Dict[str, Any] = {}
        all_passed = True

        de = len(old_signals or old_orders) if old_signals else len(old_orders)

        for class_id in sorted(THRESHOLDS.keys()):
            threshold_info = THRESHOLDS[class_id]
            class_devs = [d for d in deviations if d.type == class_id]
            count = len(class_devs)

            # 分母：Class 1/2/3 用两路径订单数均值，Class 4 用信号总数，Class 5 用信号总数
            if class_id in (1, 2, 3):
                denominator = max(len(old_orders), len(new_orders), 1)
            else:
                denominator = max(de, 1)

            actual_rate = count / denominator
            passed = actual_rate <= threshold_info["rate"]

            if not passed:
                all_passed = False

            statistics[str(class_id)] = {
                "count": count,
                "denominator": denominator,
                "actual_rate": actual_rate,
                "threshold_rate": threshold_info["rate"],
                "threshold_display": threshold_info["display"],
                "actual_rate_display": f"{actual_rate:.2%}",
                "description": threshold_info["description"],
                "passed": passed,
            }

        return ValidationReport(
            total_orders_old=len(old_orders),
            total_orders_new=len(new_orders),
            deviations=deviations,
            passed=all_passed,
            statistics=statistics,
        )

    # ═══════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _group_by_symbol(
        orders: List[OrderRequest],
    ) -> Dict[str, List[OrderRequest]]:
        """按 symbol 对订单列表分组，保持原始顺序。"""
        groups: Dict[str, List[OrderRequest]] = {}
        for o in orders:
            groups.setdefault(o.symbol, []).append(o)
        return groups

    @staticmethod
    def _order_signature_set(
        orders: List[OrderRequest],
    ) -> set:
        """生成订单签名集合（用于 Class 4 比较）。

        签名格式: "symbol|side|quantity"
        注：不包含 order_type 和 limit_price，因为这些不直接影响"信号是否存在"的判断。
        """
        sigs: set = set()
        for o in orders:
            sigs.add(f"{o.symbol}|{o.side.value}|{o.quantity}")
        return sigs

    @staticmethod
    def _normalize_signal_list(signals: Any) -> List[Dict[str, Any]]:
        """将不同格式的信号列表归一化为 dict 列表。

        支持:
          - Signal 对象列表（来自 signal_protocol_v1）
          - 普通 dict 列表
          - 其他兼容格式（尝试通过 .to_dict() 或属性访问）
        """
        result: List[Dict[str, Any]] = []

        if isinstance(signals, list):
            for sig in signals:
                if hasattr(sig, "confidence"):
                    # Signal 对象
                    result.append({
                        "symbol": getattr(sig, "symbol", "N/A"),
                        "direction": getattr(sig, "direction", "HOLD"),
                        "confidence": getattr(sig, "confidence", 0.0),
                        "horizon": getattr(sig, "horizon", "short"),
                        "signal_type": getattr(sig, "signal_type", "trend"),
                    })
                elif isinstance(sig, dict):
                    result.append({
                        "symbol": sig.get("symbol", "N/A"),
                        "direction": sig.get("direction", "HOLD"),
                        "confidence": float(sig.get("confidence", 1.0)),
                        "horizon": sig.get("horizon", "short"),
                        "signal_type": sig.get("signal_type", "trend"),
                    })
        return result

    @staticmethod
    def from_ordered_pairs(
        old_orders: List[OrderRequest],
        new_orders: List[OrderRequest],
    ) -> ValidationReport:
        """便捷方法：直接从新旧订单列表创建验证报告。

        Args:
            old_orders: 旧路径（SignalBridge）OrderRequest 列表。
            new_orders: 新路径（Signal+Consumer）OrderRequest 列表。

        Returns:
            ValidationReport
        """
        validator = DualValidator()
        return validator.compare(old_orders, new_orders)
