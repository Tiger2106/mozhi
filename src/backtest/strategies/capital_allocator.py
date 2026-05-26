"""
墨枢 - P5-04 / P5-05 资金分配器 + 动态资金调配

P5-04 CapitalAllocator — 资金分配器
  - allocate(total_capital, strategy_configs, allocation_mode) → dict[str, float]
  - 支持三种分配模式：等分 / 加权 / 历史夏普比例

P5-05 DynamicCapitalAllocator — 动态资金调配
  - update_weights(sharpe_30d: dict[str, float]) 基于近期夏普调整权重
  - 使用 softmax 归一化权重
  - 夏普为负时权重保底 0.05
  - 全部负夏普时回退等分配

Author: 墨衡
Created: 2026-05-15
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

DEFAULT_STRATEGY_NAMES = ("trend", "reversal", "grid")
NEGATIVE_SHARPE_FLOOR = 0.05
SOFTMAX_TEMPERATURE = 1.0

# ═══════════════════════════════════════════════════════════════
# P5-04: CapitalAllocator
# ═══════════════════════════════════════════════════════════════


@dataclass
class AllocationResult:
    """
    资金分配结果。

    Attributes
    ----------
    allocations : dict[str, float]
        策略名称 → 分配金额。
    weights : dict[str, float]
        策略名称 → 权重（和为 1.0）。
    mode : str
        使用的分配模式名称。
    remainder : float
        因取整剩余未分配的资金。
    """

    allocations: Dict[str, float]
    weights: Dict[str, float]
    mode: str
    remainder: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allocations": self.allocations,
            "weights": self.weights,
            "mode": self.mode,
            "remainder": self.remainder,
        }


class CapitalAllocator:
    """
    资金分配器（P5-04）。

    根据总资金和策略配置，分配资金到各个策略。

    用法::

        allocator = CapitalAllocator()
        result = allocator.allocate(
            total_capital=1_000_000.0,
            strategy_names=["trend", "reversal", "grid"],
            allocation_mode="equal",
        )
        print(result.allocations)
        # {"trend": 333333.33, "reversal": 333333.33, "grid": 333333.34}
    """

    def allocate(
        self,
        total_capital: float,
        strategy_names: Optional[List[str]] = None,
        allocation_mode: str = "equal",
        weights: Optional[Dict[str, float]] = None,
        sharpe_history: Optional[Dict[str, float]] = None,
    ) -> AllocationResult:
        """
        分配资金到各策略。

        参数
        ----------
        total_capital : float
            总可用资金（> 0）。
        strategy_names : list[str], optional
            策略名称列表。默认 ["trend", "reversal", "grid"]。
        allocation_mode : str
            分配模式：
            - "equal"      : 等分配，每策略获均等份额
            - "weighted"   : 按给定权重分配（需提供 weights）
            - "ratio_historical" : 按历史夏普比例分配（需提供 sharpe_history）
        weights : dict[str, float], optional
            自定义权重（仅 "weighted" 模式使用）。
        sharpe_history : dict[str, float], optional
            各策略历史夏普比率（仅 "ratio_historical" 模式使用）。

        返回
        -------
        AllocationResult
            包含分配金额、权重和模式的命名元组。

        抛出
        ------
        ValueError
            total_capital <= 0 或模式参数缺失时。
        """
        # ── 校验 ──────────────────────────────────────────
        if total_capital <= 0:
            raise ValueError(f"总资金必须 > 0: {total_capital}")

        names = list(strategy_names) if strategy_names else list(DEFAULT_STRATEGY_NAMES)
        if not names:
            raise ValueError("策略名称列表不能为空")

        n = len(names)

        # ── 计算权重 ──────────────────────────────────────
        if allocation_mode == "equal":
            raw_weights = {name: 1.0 / n for name in names}

        elif allocation_mode == "weighted":
            if not weights:
                raise ValueError("weighted 模式需要提供 weights 字典")
            raw_weights = self._validate_weights(names, weights)

        elif allocation_mode == "ratio_historical":
            if not sharpe_history:
                raise ValueError("ratio_historical 模式需要提供 sharpe_history 字典")
            raw_weights = self._sharpe_ratio_weights(names, sharpe_history)

        else:
            raise ValueError(f"未知分配模式: {allocation_mode}，可选: equal/weighted/ratio_historical")

        # ── 金额计算 ──────────────────────────────────────
        allocations: Dict[str, float] = {}
        assigned = 0.0
        for i, name in enumerate(names):
            if i == n - 1:
                # 最后一项：兜底确保总和 = total_capital（避免浮点误差）
                alloc = round(total_capital - assigned, 2)
            else:
                alloc = round(total_capital * raw_weights[name], 2)
            allocations[name] = alloc
            assigned += alloc

        remainder = round(total_capital - sum(allocations.values()), 2)

        return AllocationResult(
            allocations=allocations,
            weights=raw_weights,
            mode=allocation_mode,
            remainder=remainder,
        )

    # ── 工具方法 ─────────────────────────────────────────

    @staticmethod
    def _validate_weights(
        names: List[str], weights: Dict[str, float]
    ) -> Dict[str, float]:
        """
        验证并归一化用户提供的权重。

        检查：
          - 所有策略名称都有权重
          - 所有权重 >= 0
          - 权重和 > 0
        """
        missing = [n for n in names if n not in weights]
        if missing:
            raise ValueError(f"以下策略缺少权重: {missing}")

        neg = [n for n in names if weights[n] < 0]
        if neg:
            raise ValueError(f"权重不能为负: {neg}")

        total = sum(weights[n] for n in names)
        if total <= 0:
            raise ValueError("权重之和必须 > 0")

        return {n: weights[n] / total for n in names}

    @staticmethod
    def _sharpe_ratio_weights(
        names: List[str], sharpe_history: Dict[str, float]
    ) -> Dict[str, float]:
        """
        基于历史夏普比率计算权重。

        规则：
          - 夏普为 0 或缺失 → 权重为 0.05 保底
          - 夏普为负 → 权重为 0.05 保底
          - 夏普为正 → 与夏普值成比例
          - 全部为 0 或负 → 等分配
        """
        adjusted = {}
        for name in names:
            s = sharpe_history.get(name, 0.0)
            adjusted[name] = max(s, NEGATIVE_SHARPE_FLOOR) if s > 0 else NEGATIVE_SHARPE_FLOOR

        total = sum(adjusted.values())

        # 全部保底 → 回退等分配
        if all(v == NEGATIVE_SHARPE_FLOOR for v in adjusted.values()):
            n = len(names)
            return {name: 1.0 / n for name in names}

        return {name: adjusted[name] / total for name in names}


# ═══════════════════════════════════════════════════════════════
# P5-05: DynamicCapitalAllocator
# ═══════════════════════════════════════════════════════════════


class DynamicCapitalAllocator(CapitalAllocator):
    """
    动态资金调配（P5-05）。

    在静态分配器基础上增加基于近期表现（30 日夏普比率）的权重动态调整。

    用法::

        allocator = DynamicCapitalAllocator()
        # 初始分配
        result = allocator.allocate(total_capital=1_000_000.0)

        # 基于近期表现更新权重
        sharpe_30d = {
            "trend": 1.5,
            "reversal": 0.8,
            "grid": -0.3,
        }
        weights = allocator.update_weights(sharpe_30d)
        # → {"trend": 0.65, "reversal": 0.30, "grid": 0.05}

        # 使用新权重分配
        result = allocator.allocate(
            total_capital=1_000_000.0,
            weights=weights,
            allocation_mode="weighted",
        )
    """

    def __init__(self) -> None:
        super().__init__()
        self._latest_weights: Dict[str, float] = {}
        self._weight_history: List[Dict[str, float]] = []

    def update_weights(
        self,
        sharpe_30d: Dict[str, float],
        strategy_names: Optional[List[str]] = None,
        temperature: float = SOFTMAX_TEMPERATURE,
    ) -> Dict[str, float]:
        """
        基于 30 日夏普比率更新各策略权重。

        流程：
          1. 夏普为负 → 权重设为 NEGATIVE_SHARPE_FLOOR (0.05) 保底
          2. 全部为 0 或负 → 回退等分配
          3. 否则 → softmax 归一化
          4. 更新 self._latest_weights

        参数
        ----------
        sharpe_30d : dict[str, float]
            策略名 → 30 日夏普比率。
        strategy_names : list[str], optional
            需要更新权重的策略列表。默认使用 sharpe_30d 的键。
        temperature : float
            Softmax 温度参数。温度 > 1 使分布更均匀，
            温度 < 1 使分布更极端。默认 1.0。

        返回
        -------
        dict[str, float]
            策略名 → 更新后权重（和为 1.0）。
        """
        names = list(strategy_names) if strategy_names else list(sharpe_30d.keys())
        if not names:
            raise ValueError("策略名称列表不能为空")

        # ── 1. 夏普截断保底 ──────────────────────────────
        adjusted = {}
        all_non_positive = True
        for name in names:
            s = sharpe_30d.get(name, 0.0)
            if s > 0:
                adjusted[name] = s
                all_non_positive = False
            else:
                adjusted[name] = NEGATIVE_SHARPE_FLOOR

        # ── 2. 全部非正 → 等分配 ─────────────────────────
        if all_non_positive:
            n = len(names)
            weights = {name: 1.0 / n for name in names}
            self._latest_weights = dict(weights)
            self._weight_history.append(dict(weights))
            return weights

        # ── 3. Softmax 归一化 ─────────────────────────────
        exp_vals = {}
        max_val = max(adjusted.values())
        for name in names:
            # 数值稳定：减去最大值
            exp_vals[name] = math.exp((adjusted[name] - max_val) / temperature)

        exp_sum = sum(exp_vals.values())
        weights = {name: exp_vals[name] / exp_sum for name in names}

        self._latest_weights = dict(weights)
        self._weight_history.append(dict(weights))
        return weights

    # ── 属性 ─────────────────────────────────────────────

    @property
    def latest_weights(self) -> Dict[str, float]:
        """最近一次 update_weights 计算的权重。"""
        return dict(self._latest_weights)

    @property
    def weight_history(self) -> List[Dict[str, float]]:
        """权重更新历史。"""
        return list(self._weight_history)

    def reset(self) -> None:
        """复位状态（清除历史权重记录）。"""
        self._latest_weights = {}
        self._weight_history.clear()

    def get_allocation(
        self,
        total_capital: float,
        sharpe_30d: Dict[str, float],
        strategy_names: Optional[List[str]] = None,
        temperature: float = SOFTMAX_TEMPERATURE,
    ) -> AllocationResult:
        """
        一键动态分配：根据夏普更新权重 → 按权重分配资金。

        参数
        ----------
        total_capital : float
            总资金。
        sharpe_30d : dict[str, float]
            各策略 30 日夏普比率。
        strategy_names : list[str], optional
            策略名称列表。默认使用 sharpe_30d 的键。
        temperature : float
            Softmax 温度参数。

        返回
        -------
        AllocationResult
            分配结果。
        """
        weights = self.update_weights(sharpe_30d, strategy_names, temperature)
        names = strategy_names or list(sharpe_30d.keys())
        return self.allocate(
            total_capital=total_capital,
            strategy_names=names,
            allocation_mode="weighted",
            weights=weights,
        )
