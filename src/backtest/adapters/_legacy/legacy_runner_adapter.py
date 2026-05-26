"""
[LEGACY] backtest.adapters._legacy.legacy_runner_adapter — LegacyRunnerAdapter

DEPRECATED: 已归档至 adapters._legacy 子包。
R1 阶段四清理: 2026-05-18
新系统请使用 backtest.adapter（单数）进行红蓝并行信号对齐。

原用途：适配旧系统（run_trend.py、run_reversal.py、run_grid.py）输出至 MethodResult
Phase 4 — 适配器模式（设计方案 §7）。

迁移方针:
  1. 旧系统继续跑（run_trend.py、run_reversal.py、run_grid.py）
  2. 新系统（MethodBacktestRunner）并行验证
  3. 新系统运行稳定后，老运行器逐一替换为新 Runner 包装调用
  4. 老文件标注 DEPRECATED

使用示例:
    >>> from backtest.adapters._legacy.legacy_runner_adapter import LegacyRunnerAdapter
    >>> from backtest.strategies import run_trend
    ...
    >>> adapter = LegacyRunnerAdapter(run_trend, method_name="ma_cross")
    >>> result = adapter.run("601857", {"signal_type": "ma"})
    >>> result.method_name
    'ma_cross'
    >>> result.n_bars > 0
    True

作者: 墨衡
创建时间: 2026-05-17
归档时间: 2026-05-18
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from backtest.methods.base import MethodResult

logger = logging.getLogger(__name__)


class LegacyRunnerAdapter:
    """适配器：让老系统输出迁移到新 MethodResult 结构

    Args:
        runner_module: 旧运行器模块 (run_trend, run_reversal, run_grid)
        method_name: 方法名称
        runner_func_name: 旧系统运行函数名称（默认 "main"）
        config_cls_name: 旧系统配置类名称（可选，用于提取默认参数）

    Examples:
        >>> import backtest.runners.run_trend as rt
        >>> adapter = LegacyRunnerAdapter(rt, "ma_cross")
        >>> result = adapter.run("601857", {"ma_fast": 5, "ma_slow": 20})
        >>> result.method_name
        'ma_cross'
    """

    def __init__(
        self,
        runner_module: Any,
        method_name: str,
        runner_func_name: str = "main",
        config_cls_name: Optional[str] = None,
    ):
        self.runner = runner_module
        self.method_name = method_name
        self.runner_func_name = runner_func_name
        self.config_cls_name = config_cls_name

    def _get_runner_func(self):
        """从旧模块中获取运行函数"""
        if not hasattr(self.runner, self.runner_func_name):
            raise AttributeError(
                f"旧运行器 {getattr(self.runner, '__name__', '?')} 没有 "
                f"{self.runner_func_name}() 函数"
            )
        return getattr(self.runner, self.runner_func_name)

    def run(self, symbol: str, config: dict) -> MethodResult:
        """调用旧系统运行函数并转换为 MethodResult

        Args:
            symbol: 股票代码
            config: 策略参数字典

        Returns:
            MethodResult: 统一格式的回测结果
        """
        runner_func = self._get_runner_func()

        # 调用旧系统函数
        old_result = runner_func(symbol, config)

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

        # 保留 duration_ms
        duration = self._extract_duration(old_result)
        if duration is not None:
            result.duration_ms = duration

        return result

    def _extract_signals(self, old_result: Any) -> pd.DataFrame:
        """从旧系统输出中提取 signals DataFrame（索引必须为 DatetimeIndex）"""
        from datetime import datetime, timedelta

        def _ensure_dtindex(df: pd.DataFrame) -> pd.DataFrame:
            """确保 DataFrame 索引为 DatetimeIndex"""
            if isinstance(df.index, pd.DatetimeIndex):
                return df
            if len(df) == 0:
                df.index = pd.DatetimeIndex([])
                return df
            # 尝试从 signal 值构造日期
            if hasattr(old_result, "trades"):
                trades = old_result.trades
                if trades:
                    dates = []
                    for t in trades:
                        d = getattr(t, "date", None) or getattr(t, "entry_date", None)
                        if d:
                            dates.append(pd.Timestamp(d))
                    if len(dates) == len(df):
                        df.index = pd.DatetimeIndex(dates)
                        return df
                    if len(dates) < len(df) and dates:
                        # 用最后一个日期填充剩余
                        last = dates[-1]
                        while len(dates) < len(df):
                            last += timedelta(days=1)
                            dates.append(last)
                        if len(dates) == len(df):
                            df.index = pd.DatetimeIndex(dates)
                            return df
            if hasattr(old_result, "fill_reports"):
                freps = old_result.fill_reports
                if freps:
                    dates = []
                    for fr in freps:
                        t = getattr(fr, "trade", None)
                        if t:
                            d = getattr(t, "date", None)
                            if d:
                                dates.append(pd.Timestamp(d))
                    if len(dates) == len(df):
                        df.index = pd.DatetimeIndex(dates)
                        return df
            # 兜底：生成连续的交易日
            end = datetime.now()
            start = end - timedelta(days=len(df) * 1)
            df.index = pd.bdate_range(start=start, periods=len(df))
            return df

        # dict 格式
        if isinstance(old_result, dict):
            sig = old_result.get("signals", old_result.get("signal", []))
            if isinstance(sig, pd.DataFrame):
                return _ensure_dtindex(sig)
            if isinstance(sig, pd.Series):
                return _ensure_dtindex(sig.to_frame("signal"))
            if isinstance(sig, list) and sig:
                return _ensure_dtindex(pd.DataFrame({"signal": [1] * len(sig)}))
            return _ensure_dtindex(pd.DataFrame({"signal": [0]}))

        # namespace / object 格式
        if hasattr(old_result, "signals"):
            sig = old_result.signals
            if isinstance(sig, pd.DataFrame):
                return _ensure_dtindex(sig)
            if isinstance(sig, pd.Series):
                return _ensure_dtindex(sig.to_frame("signal"))
            if isinstance(sig, list) and sig:
                return _ensure_dtindex(pd.DataFrame({"signal": [1] * len(sig)}))

        # fill_reports → 信号
        fill_reports = self._safe_get(old_result, "fill_reports", [])
        if fill_reports:
            n = len(fill_reports)
            df = pd.DataFrame({"signal": [1] * n})
            return _ensure_dtindex(df)

        # trades → 信号
        trades = self._safe_get(old_result, "trades", [])
        if trades:
            n = len(trades)
            df = pd.DataFrame({"signal": [1] * n})
            return _ensure_dtindex(df)

        # equity_curve → 全 0 信号
        equity_curve = self._safe_get(old_result, "equity_curve", None)
        if equity_curve is not None and isinstance(equity_curve, (pd.DataFrame, pd.Series)):
            if isinstance(equity_curve, pd.Series):
                n = len(equity_curve)
                df = pd.DataFrame({"signal": [0] * n})
            else:
                n = len(equity_curve)
                df = pd.DataFrame({"signal": [0] * n}, index=equity_curve.index)
            if isinstance(df.index, pd.DatetimeIndex):
                return df
            return _ensure_dtindex(df)

        # total_bars → 全 0
        total_bars = self._safe_get(old_result, "total_bars", 0)
        if total_bars > 0:
            df = pd.DataFrame({"signal": [0] * total_bars})
            return _ensure_dtindex(df)

        # 兜底：返回空 DataFrame
        return _ensure_dtindex(pd.DataFrame({"signal": pd.Series(dtype="int64")}))

    def _extract_indicators(self, old_result: Any) -> Dict[str, pd.Series]:
        """从旧系统输出中提取 indicators"""
        if isinstance(old_result, dict):
            return {
                k: v for k, v in old_result.items()
                if isinstance(v, (pd.Series, list)) and k not in ("signals", "signal")
            }
        if hasattr(old_result, "__dict__"):
            return {
                k: v for k, v in old_result.__dict__.items()
                if isinstance(v, (pd.Series, list)) and k not in ("signals", "signal",
                                                                   "trades", "fill_reports",
                                                                   "metrics", "equity_curve")
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
        # namespace / object → 取 metrics 字典
        metrics = self._safe_get(old_result, "metrics", {})
        if isinstance(metrics, dict):
            return metrics

        # 从 __dict__ 收集非序列字段
        if hasattr(old_result, "__dict__"):
            return {
                k: v for k, v in old_result.__dict__.items()
                if not isinstance(v, (pd.Series, pd.DataFrame, list))
                and k not in ("signals", "signal", "trades", "fill_reports",
                              "equity_curve", "config")
            }

        return {"total_return_pct": 0.0}

    def _extract_duration(self, old_result: Any) -> Optional[float]:
        """提取 duration_ms"""
        if isinstance(old_result, dict):
            return old_result.get("duration_ms")
        return self._safe_get(old_result, "duration_ms", None)

    @staticmethod
    def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
        """安全获取 attribute，兼容 dict 和 namespace"""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)


# ── MethodResult 的 n_bars 属性补充 ───────────────────────────
# (MethodResult 已有 @property n_bars 返回 len(signals))
