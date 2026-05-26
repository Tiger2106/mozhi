"""
墨枢 - 红蓝并行执行引擎（R1 阶段二：任务5）

同时运行新旧两个信号系统并对比结果。

旧系统（蓝方）：调用 src.backtest.engine 或 src.backtest.strategies.*
新系统（红方）：调用 methods (breakout_retest / continuation / VPE)

产出：
  DualResult — 包含红蓝双方各时间戳的信号列表及汇总统计
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from src.backtest.models.signal_types import R1Signal
from src.backtest.methods.breakout_retest import run_breakout_retest
from src.backtest.methods.continuation import run_continuation
from src.backtest.methods.volume_price_expansion import run_vpe


# ─── 信号方法映射 ────────────────────────────────────────────

METHOD_REGISTRY: Dict[str, Callable] = {
    "breakout_retest": run_breakout_retest,
    "continuation": run_continuation,
    "volume_price_expansion": run_vpe,
}


@dataclass
class DualResult:
    """红蓝并行结果"""

    # 红方（新系统）信号
    red_signals: List[R1Signal] = field(default_factory=list)

    # 蓝方（旧系统）信号（dict 格式，旧系统输出）
    blue_signals: List[dict] = field(default_factory=list)

    # 运行配置
    red_methods: List[str] = field(default_factory=list)
    symbol: str = ""
    start: str = ""
    end: str = ""

    # 统计信息
    red_count: int = 0
    blue_count: int = 0
    match_count: int = 0
    mismatch_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "red_methods": self.red_methods,
            "red_count": self.red_count,
            "blue_count": self.blue_count,
            "match_count": self.match_count,
            "mismatch_count": self.mismatch_count,
            "red_signals": [
                {
                    "method": s.method,
                    "direction": s.direction,
                    "confidence": s.confidence,
                    "price": s.price,
                    "timestamp": str(s.timestamp),
                    "regime": s.regime,
                }
                for s in self.red_signals
            ],
            "blue_signals": self.blue_signals,
        }


# ─── 旧系统信号适配器 ────────────────────────────────────────

def _call_legacy_signals(df: pd.DataFrame, symbol: str) -> List[dict]:
    """调用旧系统信号生成（模拟）。

    在未直接导入旧系统引擎时，使用内置回退逻辑：
      尝试从 df 指标中提取典型旧信号。

    Args:
        df: OHLCV DataFrame
        symbol: 标的代码

    Returns:
        List[dict]: 旧系统格式的信号列表
            [{"signal_verdict": -1/0/1, "confidence": float, "price": float, "method": str, "timestamp": str}, ...]
    """
    try:
        # 尝试导入旧系统策略
        from src.backtest.strategies.trend_strategy import TrendStrategy
        from src.backtest.backtest_engine import BacktestConfig, Strategy

        class LegacyAdapter(Strategy):
            def __init__(self, symbol: str):
                self.symbol = symbol
                self.signals: List[dict] = []

            def on_bar(self, context, bar):
                # 如果新 bar 触发信号，生成旧格式信号
                pass  # 简化实现

        signals: List[dict] = []
        close = df['close'].values

        # 基础信号检测：简单趋势跟随
        for i in range(20, len(df)):
            ma_short = float(pd.Series(close[:i + 1]).rolling(5).mean().iloc[-1])
            ma_long = float(pd.Series(close[:i + 1]).rolling(20).mean().iloc[-1])

            if ma_short > ma_long * 1.01:
                signals.append({
                    "signal_verdict": 1,
                    "confidence": 0.5,
                    "price": float(close[i]),
                    "method": "legacy_trend",
                    "timestamp": str(df.index[i]) if isinstance(df.index, pd.DatetimeIndex) else str(datetime.now()),
                })
            elif ma_short < ma_long * 0.99:
                signals.append({
                    "signal_verdict": -1,
                    "confidence": 0.4,
                    "price": float(close[i]),
                    "method": "legacy_trend",
                    "timestamp": str(df.index[i]) if isinstance(df.index, pd.DatetimeIndex) else str(datetime.now()),
                })

        return signals

    except ImportError:
        # 旧系统不可用，返回空
        return []


# ─── 红方信号生成 ────────────────────────────────────────────

def _call_red_signals(
    df: pd.DataFrame,
    methods: List[str],
    method_kwargs: Optional[Dict[str, Dict]] = None,
) -> List[R1Signal]:
    """调用新系统各 method 生成红方信号。

    Args:
        df: OHLCV DataFrame
        methods: 方法名列表（来自 METHOD_REGISTRY）
        method_kwargs: 各方法的 kwargs 字典 {method_name: kwargs_dict}

    Returns:
        List[R1Signal]: 红方信号合并列表
    """
    all_signals: List[R1Signal] = []
    if method_kwargs is None:
        method_kwargs = {}

    for method in methods:
        if method not in METHOD_REGISTRY:
            continue
        fn = METHOD_REGISTRY[method]
        kwargs = method_kwargs.get(method, {})
        try:
            signals = fn(df, **kwargs)
            all_signals.extend(signals)
        except Exception:
            # 单个 method 失败不影响其他 method
            continue

    # 按时间排序
    all_signals.sort(key=lambda s: s.timestamp)
    return all_signals


# ─── 并行引擎 ────────────────────────────────────────────────

class ParallelEngine:
    """红蓝并行执行引擎。

    同时运行新旧两个信号系统，产出对比结果。
    """

    def __init__(
        self,
        red_methods: Optional[List[str]] = None,
    ):
        self.red_methods = red_methods or list(METHOD_REGISTRY.keys())

    def run_dual(
        self,
        df: pd.DataFrame,
        symbol: str,
        red_methods: Optional[List[str]] = None,
        blue_fn: Optional[Callable] = None,
        method_kwargs: Optional[Dict[str, Dict]] = None,
    ) -> DualResult:
        """红蓝并行运行。

        Args:
            df: OHLCV DataFrame
            symbol: 标的代码
            red_methods: 红方使用的方法列表（默认 self.red_methods）
            blue_fn: 蓝方信号函数（默认 _call_legacy_signals）
            method_kwargs: 各方法的额外参数

        Returns:
            DualResult: 红蓝结果对比
        """
        methods = red_methods or self.red_methods

        # 红方信号
        red_signals = _call_red_signals(df, methods, method_kwargs)

        # 蓝方信号
        if blue_fn is not None:
            blue_signals = blue_fn(df, symbol)
        else:
            blue_signals = _call_legacy_signals(df, symbol)

        # 简单匹配统计
        match_count = 0
        mismatch_count = 0

        for red in red_signals:
            for blue in blue_signals:
                blue_dir = blue.get("signal_verdict", 0)
                if red.direction == blue_dir:
                    match_count += 1
                else:
                    mismatch_count += 1

        return DualResult(
            red_signals=red_signals,
            blue_signals=blue_signals,
            red_methods=methods,
            symbol=symbol,
            red_count=len(red_signals),
            blue_count=len(blue_signals),
            match_count=match_count,
            mismatch_count=mismatch_count,
        )
