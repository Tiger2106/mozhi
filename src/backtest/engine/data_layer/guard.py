"""
TimeAlignmentGuard — 前视偏差运行时检测 (BT-006/BT-007)
========================================================
在 DataLayer → ComputeLayer 之间注入，确保：
1. 日期升序（TimeAlignmentGuard 已有）
2. t-1 契约：信号在 bar[t] 只能引用 bar[0..t] 的数据
3. P0-FIX-002: 前视偏差运行时钩子

实现:
    基于 contracts.backtest_data_contract.TimeAlignmentGuard
    扩展增加 LookaheadRuntimeGuard（P0-FIX-002）

用法:
    from engine.data_layer.guard import LookaheadRuntimeGuard
    guard = LookaheadRuntimeGuard()
    guard.check(data)

作者: moheng
版本: v1.0
"""
from typing import List, Optional
from ...contracts.backtest_data_contract import (
    TimeAlignmentGuard,
    BacktestData,
    BacktestBar,
)
from ...p0_fixes.lookahead_guard import LookaheadGuard


class LookaheadRuntimeGuard:
    """前视偏差运行时检测器（集成 P0-FIX-002）

    同时运行:
    1. TimeAlignmentGuard — 日期升序检查（数据合约层）
    2. LookaheadGuard — 静态/动态偏差检测（P0-FIX-002）
    """

    def __init__(self):
        self._tag = TimeAlignmentGuard()
        self._lag = LookaheadGuard()

    def check(self, data: BacktestData) -> List[str]:
        """运行全部前视偏差检测

        Args:
            data: BacktestData 合约

        Returns:
            警告列表（空列表 = 通过）
        """
        warnings: List[str] = []

        # 1. 日期升序检查
        date_errors = TimeAlignmentGuard.check_bars_ascending(data.bars)
        if date_errors:
            warnings.extend([f"[DATE_ORDER] {e}" for e in date_errors])

        # 2. 前视偏差静态检测
        self._lag.check_data_contract(data)
        self._lag.check_static_bias(data, [])

        # 3. 汇总
        for f in self._lag.findings:
            warnings.append(f"[{f.severity}] {f.rule}: {f.description}")

        return warnings

    @property
    def passed(self) -> bool:
        return len(self._lag.findings) == 0


__all__ = ["TimeAlignmentGuard", "LookaheadRuntimeGuard"]
