"""
legacy_runner_adapter — 旧系统→新 MethodResult 适配器

author: 墨衡
version: 1.0.0

将 run_trend.py / run_reversal.py / run_grid.py 的输出迁移到
新 MethodResult 结构，实现新旧系统并行运行的兼容层。
"""

from __future__ import annotations

import importlib
import types
from typing import Any, Dict, Optional

import pandas as pd

from backtest.methods.base import MethodResult


class LegacyRunnerAdapter:
    """适配器：让老系统输出迁移到新 MethodResult 结构

    Args:
        runner_module: 旧运行器模块 (run_trend, run_reversal, run_grid)
        method_name: 方法名称

    Examples:
        >>> import backtest.runners.run_trend as rt
        >>> adapter = LegacyRunnerAdapter(rt, "ma_cross")
        >>> result = adapter.run("601857", {"ma_fast": 5, "ma_slow": 20})
        >>> result.method_name
        'ma_cross'
    """

    def __init__(self, runner_module: types.ModuleType, method_name: str):
        self.runner = runner_module
        self.method_name = method_name

    def run(self, symbol: str, config: dict) -> MethodResult:
        """调用旧系统 main() 并转换为 MethodResult

        Args:
            symbol: 股票代码
            config: 策略参数字典

        Returns:
            MethodResult: 统一格式的回测结果
        """
        if not hasattr(self.runner, "main"):
            raise AttributeError(
                f"旧运行器 {self.runner.__name__} 没有 main() 函数"
            )

        old_result = self.runner.main(symbol, config)

        # ── 转换为 MethodResult ──────────────────────────────────
        signals_df = self._extract_signals(old_result)
        indicators = self._extract_indicators(old_result)
        statistics = self._extract_statistics(old_result)

        result = MethodResult(
            signals=signals_df,
            indicators=indicators,
            method_name=self.method_name,
            params=config,
            statistics=statistics,
        )

        if isinstance(old_result, dict) and "duration_ms" in old_result:
            result.duration_ms = old_result["duration_ms"]

        return result

    def _extract_signals(self, old_result: Any) -> pd.DataFrame:
        """从旧系统输出中提取 signals DataFrame"""
        if isinstance(old_result, dict):
            sig = old_result.get("signals", old_result.get("signal", []))
        elif hasattr(old_result, "signals"):
            sig = old_result.signals
        else:
            sig = []

        if isinstance(sig, pd.DataFrame):
            return sig
        if isinstance(sig, pd.Series):
            return sig.to_frame("signal")
        if isinstance(sig, list):
            return pd.DataFrame({"signal": sig})
        if isinstance(sig, dict):
            return pd.DataFrame(sig)
        return pd.DataFrame({"signal": [0]})

    def _extract_indicators(self, old_result: Any) -> Dict[str, pd.Series]:
        """从旧系统输出中提取 indicators"""
        if isinstance(old_result, dict):
            return {
                k: v for k, v in old_result.items()
                if isinstance(v, (pd.Series, list)) and k not in ("signals", "signal")
            }
        return {}

    def _extract_statistics(self, old_result: Any) -> Dict[str, Any]:
        """从旧系统输出中提取 statistics"""
        if isinstance(old_result, dict):
            return {
                k: v for k, v in old_result.items()
                if not isinstance(v, (pd.Series, pd.DataFrame, list))
                and k not in ("signals", "signal", "config")
            }
        return {}
