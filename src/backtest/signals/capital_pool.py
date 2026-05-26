"""
CapitalPoolAllocator — 资金池分配引擎

职责：
  1. 在多个标的之间分配有限资金
  2. 支持四种分配模式：等分、信号加权、风险平价、动量分配
  3. 动态再平衡功能

用 法::

    from signals.capital_pool import CapitalPoolAllocator

    allocator = CapitalPoolAllocator(total_capital=1_000_000, mode='equal')
    allocation = allocator.allocate(
        signal_scores={"601857": 0.8, "600519": 0.6},
        risk_metrics={"601857": {"drawdown": 0.02}, "600519": {"drawdown": 0.03}}
    )
    # {"601857": 500000, "600519": 500000}

    new_allocation = allocator.rebalance(
        positions={"601857": 480000, "600519": 520000},
        market_data={"601857": {"mom_5d": 0.015}, "600519": {"mom_5d": -0.005}}
    )
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


class CapitalPoolAllocator:
    """
    资金池分配引擎：在多个标的之间分配有限资金。

    Parameters
    ----------
    total_capital : float
        总资金池（默认 100 万）
    mode : str
        分配模式（equal | signal_weighted | risk_parity | momentum）
    max_positions : int
        最大同时持仓数（默认 5）
    safety_margin : float
        安全边际系数 [0,1]，用于 weighted / risk_parity / momentum 模式
    momentum_lookback : int
        动量回溯天数（默认 20）
    """

    # ─── 分配模式常量 ───
    MODE_EQUAL = "equal"              # 等分
    MODE_SIGNAL_WEIGHTED = "signal_weighted"  # 按信号置信度加权
    MODE_RISK_PARITY = "risk_parity"          # 风险平价（回撤倒数）
    MODE_MOMENTUM = "momentum"                # 动量分配

    VALID_MODES = {MODE_EQUAL, MODE_SIGNAL_WEIGHTED, MODE_RISK_PARITY, MODE_MOMENTUM}

    def __init__(
        self,
        total_capital: float = 1_000_000,
        mode: str = "equal",
        max_positions: int = 5,
        safety_margin: float = 0.9,
        momentum_lookback: int = 20,
    ):
        if mode not in self.VALID_MODES:
            raise ValueError(f"无效分配模式: {mode}，可选: {self.VALID_MODES}")
        if total_capital <= 0:
            raise ValueError("total_capital 必须 > 0")
        if max_positions <= 0:
            raise ValueError("max_positions 必须 > 0")
        if not 0 < safety_margin <= 1:
            raise ValueError("safety_margin 必须在 (0, 1] 范围内")

        self.total_capital = total_capital
        self.mode = mode
        self.max_positions = max_positions
        self.safety_margin = safety_margin
        self.momentum_lookback = momentum_lookback

    # ═══════════════════════════════════════════════════════════════
    # 公开接口
    # ═══════════════════════════════════════════════════════════════

    def allocate(
        self,
        signal_scores: Dict[str, float],
        risk_metrics: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, float]:
        """
        根据当前 mode 在多个标的之间分配资金。

        Parameters
        ----------
        signal_scores : dict[str, float]
            {symbol: 信号置信度 (0~1)} — 必填
        risk_metrics : dict[str, dict], optional
            {symbol: {drawdown: float, ...}} — 风险平价/动量模式需要

        Returns
        -------
        dict[str, float]
            {symbol: 分配资金额}
        """
        if not signal_scores:
            return {}

        symbols = list(signal_scores.keys())
        if len(symbols) <= self.max_positions:
            active = symbols
        else:
            # 超出最大持仓数 → 按信号强弱截取
            active = sorted(symbols, key=lambda s: signal_scores.get(s, 0), reverse=True)[:self.max_positions]

        if not active:
            return {}

        if self.mode == self.MODE_EQUAL:
            return self._allocate_equal(active, signal_scores)
        elif self.mode == self.MODE_SIGNAL_WEIGHTED:
            return self._allocate_signal_weighted(active, signal_scores)
        elif self.mode == self.MODE_RISK_PARITY:
            return self._allocate_risk_parity(active, signal_scores, risk_metrics or {})
        elif self.mode == self.MODE_MOMENTUM:
            return self._allocate_momentum(active, signal_scores, risk_metrics or {})
        else:
            raise ValueError(f"未知分配模式: {self.mode}")

    def rebalance(
        self,
        positions: Dict[str, float],
        market_data: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Dict[str, float]:
        """
        动态再平衡：检查当前持仓偏离度，返回调整后的分配方案。

        Parameters
        ----------
        positions : dict[str, float]
            {symbol: 当前持仓市值}
        market_data : dict[str, dict], optional
            {symbol: {当前价, 动量...}} — 可选的市场数据

        Returns
        -------
        dict[str, float]
            调整后的分配方案（保持总分配不变）
        """
        if not positions:
            return {}

        current_total = sum(positions.values())
        if current_total <= 0:
            return {}

        # 计算目标比例
        total_used = current_total
        signal_scores = {s: 1.0 for s in positions}  # 默认均有权重

        # 从 market_data 中提取信号置信度（如果有）
        if market_data:
            for s in positions:
                md = market_data.get(s, {})
                score = md.get("signal_score", 1.0)
                signal_scores[s] = score

        # 如果总持仓低于 total_capital * 0.5，不触发再平衡（资金还在入场中）
        min_trigger = self.total_capital * 0.5
        if total_used < min_trigger:
            return dict(positions)

        # 用当前持仓标的作为 active 列表，重新计算目标分配
        active = list(positions.keys())

        if self.mode == self.MODE_EQUAL:
            target = self._allocate_equal(active, signal_scores)
        elif self.mode == self.MODE_SIGNAL_WEIGHTED:
            target = self._allocate_signal_weighted(active, signal_scores)
        elif self.mode == self.MODE_RISK_PARITY:
            risk_metrics = {}
            if market_data:
                for s in active:
                    md = market_data.get(s, {})
                    risk_metrics[s] = {"drawdown": md.get("drawdown", 0.0)}
            target = self._allocate_risk_parity(active, signal_scores, risk_metrics)
        elif self.mode == self.MODE_MOMENTUM:
            target = self._allocate_momentum(active, signal_scores, market_data or {})
        else:
            return dict(positions)

        # 按 target 缩放使得总和 = current_total（资金池不变）
        target_total = sum(target.values())
        if target_total > 0:
            scale = current_total / target_total
            scaled = {s: round(v * scale, 2) for s, v in target.items()}
        else:
            scaled = dict(positions)

        return scaled

    # ═══════════════════════════════════════════════════════════════
    # 分配算法实现
    # ═══════════════════════════════════════════════════════════════

    def _allocate_equal(
        self, active: List[str], signal_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """
        等分模式：total_capital ÷ max_positions
        如果 active < max_positions，则按实际 active 数量等分。
        """
        count = len(active)
        if count == 0:
            return {}

        per_position = self.total_capital / min(count, self.max_positions)
        # 确保总和不超出 total_capital
        result: Dict[str, float] = {}
        total_allocated = 0.0

        for i, symbol in enumerate(active):
            if i >= self.max_positions:
                break
            alloc = per_position
            if total_allocated + alloc > self.total_capital:
                alloc = self.total_capital - total_allocated
            result[symbol] = round(alloc, 2)
            total_allocated += alloc

        return result

    def _allocate_signal_weighted(
        self, active: List[str], signal_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """
        信号加权模式：
          - 信号置信度归一化后 × total_capital × safety_margin
          - 剩余资金按等分分配（或留空）
        """
        # 提取 active 标的的信号权重
        weights = []
        for s in active:
            w = max(signal_scores.get(s, 0.0), 0.0)
            weights.append(w)

        weight_sum = sum(weights)
        if weight_sum <= 0:
            # 退化为等分
            return self._allocate_equal(active, signal_scores)

        # 归一化
        normalized = [w / weight_sum for w in weights]

        # 安全边际
        usable_capital = self.total_capital * self.safety_margin
        result: Dict[str, float] = {}
        allocated_sum = 0.0

        for i, symbol in enumerate(active):
            raw = normalized[i] * usable_capital
            if raw < 0:
                raw = 0.0
            # 保持总和检查
            if allocated_sum + raw > self.total_capital:
                raw = self.total_capital - allocated_sum
            result[symbol] = round(raw, 2)
            allocated_sum += raw

        # 如果还有未分配资金 (剩余 ≈ total_capital * (1-safety_margin))
        # 等分给所有 active 标的（微量调整）
        remaining = self.total_capital - allocated_sum
        if remaining > 0 and active:
            bonus = remaining / len(active)
            for s in active:
                result[s] = round(result.get(s, 0) + bonus, 2)

        return result

    def _allocate_risk_parity(
        self,
        active: List[str],
        signal_scores: Dict[str, float],
        risk_metrics: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """
        风险平价模式：
          - 权重 = 1/回撤的倒数作为权重（回撤越大，仓位越小）
          - 无回撤数据时退化为等分
        """
        # 计算每个标的的原始风险权重
        raw_weights = []
        has_risk = False

        for s in active:
            metrics = risk_metrics.get(s, {})
            dd = metrics.get("drawdown", 0.0)
            sig = max(signal_scores.get(s, 0.5), 0.1)

            if dd is not None and dd > 0:
                has_risk = True
                # 风险平价：权重与回撤成反比，用 sig 微调
                raw_w = sig / max(dd, 1e-6)
            else:
                # 无回撤数据，使用 signal_score 作为参考
                raw_w = sig

            raw_weights.append(max(raw_w, 0.0))

        # 对应风险最小/回撤为0的极端情况，用信号加权兜底
        if not has_risk:
            return self._allocate_signal_weighted(active, signal_scores)

        weight_sum = sum(raw_weights)
        if weight_sum <= 0:
            return self._allocate_equal(active, signal_scores)

        normalized = [w / weight_sum for w in raw_weights]
        result: Dict[str, float] = {}
        allocated_sum = 0.0

        usable_capital = self.total_capital * self.safety_margin

        for i, symbol in enumerate(active):
            raw = normalized[i] * usable_capital
            if allocated_sum + raw > self.total_capital:
                raw = self.total_capital - allocated_sum
            result[symbol] = round(raw, 2)
            allocated_sum += raw

        remaining = self.total_capital - allocated_sum
        if remaining > 0 and active:
            bonus = remaining / len(active)
            for s in active:
                result[s] = round(result.get(s, 0) + bonus, 2)

        return result

    def _allocate_momentum(
        self,
        active: List[str],
        signal_scores: Dict[str, float],
        market_data: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """
        动量分配模式：
          - 使用近 N 日收益作为调整因子
          - 动量快的标的获得更大仓位
          - 动量 < 0 的标的获得最小仓位
        """
        # 准备计算原始动量权重
        raw_weights = []
        has_momentum = False

        for s in active:
            sig = max(signal_scores.get(s, 0.5), 0.1)
            md = market_data.get(s, {})
            # 按优先级查找动量数据
            momentum = md.get("mom_5d") or md.get("mom_10d") or md.get(f"mom_{self.momentum_lookback}d") or md.get("momentum", 0.0)

            if momentum != 0:
                has_momentum = True

            # 动量因子: 正的动量放量，负的动量缩量
            mom_factor = 1.0 + max(momentum, -0.5)
            raw = sig * max(mom_factor, 0.1)
            raw_weights.append(raw)

        if not has_momentum:
            return self._allocate_signal_weighted(active, signal_scores)

        weight_sum = sum(raw_weights)
        if weight_sum <= 0:
            return self._allocate_equal(active, signal_scores)

        normalized = [w / weight_sum for w in raw_weights]
        result: Dict[str, float] = {}
        allocated_sum = 0.0

        usable_capital = self.total_capital * self.safety_margin

        for i, symbol in enumerate(active):
            raw = normalized[i] * usable_capital
            if allocated_sum + raw > self.total_capital:
                raw = self.total_capital - allocated_sum
            result[symbol] = round(raw, 2)
            allocated_sum += raw

        remaining = self.total_capital - allocated_sum
        if remaining > 0 and active:
            bonus = remaining / len(active)
            for s in active:
                result[s] = round(result.get(s, 0) + bonus, 2)

        return result

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    def total_allocated(self, allocation: Dict[str, float]) -> float:
        """计算分配总额"""
        return round(sum(allocation.values()), 2)

    def utilization_rate(self, allocation: Dict[str, float]) -> float:
        """计算资金利用率（已分配 / 总资金）"""
        if self.total_capital <= 0:
            return 0.0
        return round(self.total_allocated(allocation) / self.total_capital, 4)

    def change_mode(self, new_mode: str) -> None:
        """
        运行时切换分配模式。

        Parameters
        ----------
        new_mode : str
        """
        if new_mode not in self.VALID_MODES:
            raise ValueError(f"无效分配模式: {new_mode}，可选: {self.VALID_MODES}")
        self.mode = new_mode
