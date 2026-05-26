"""
墨枢 - P5-01 / P5-02 / P5-03 / P5-06 / P5-07 多策略统一框架

P5-01 MultiStrategyRunner — 三策略统一调度器
P5-02 ConflictDetector — 信号冲突检测
P5-03 resolve_conflicts — 冲突处理策略
P5-06 MultiStrategyReplay — 多策略同步回放（逐Bar）
P5-07 merge_equity — 多策略净值合并

用法::

    from backtest.strategies.multi_runner import (
        MultiStrategyRunner, MultiStrategyConfig,
        ConflictDetector, ConflictEvent, resolve_conflicts,
        MultiStrategyReplay, MultiStrategyReplayConfig,
        merge_equity,
    )

    从 P2-11 导入:
        from backtest.strategies.trend_strategy import TrendStrategy
        from backtest.strategies.reversal_strategy import (
            generate_rsi_signals, voted_reversal_signal
        )
        from backtest.strategies.grid_strategy import StaticGridSignal, GridConfig

Author: 墨衡
Created: 2026-05-15
"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

_TZ_CN = timezone(timedelta(hours=8))

import numpy as np
import pandas as pd

from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Bar,
    Strategy,
)
from src.signals.signal_protocol_v1 import Signal
from backtest.signal_bridge import SignalBridge, SignalBridgeConfig, SignalStrategy
from backtest.strategies.trend_strategy import TrendStrategy
from backtest.strategies.capital_allocator import (
    CapitalAllocator,
    DynamicCapitalAllocator,
    AllocationResult,
)


# ═══════════════════════════════════════════════════════════════
# 类型常量
# ═══════════════════════════════════════════════════════════════

DEFAULT_STRATEGY_NAMES = ("trend", "reversal", "grid")
CONFLICT_PRIORITY = {"trend": 3, "reversal": 2, "grid": 1}


# ═══════════════════════════════════════════════════════════════
# P5-01: 数据模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class StrategyConfig:
    """
    单策略配置（P5-01）。

    用于 MultiStrategyRunner.run_multi() 的 configs 字典值。

    Attributes
    ----------
    strategy : Strategy
        策略实例（TrendStrategy 或其配置推导出的实例，由调用方提供）。
    bridge_config : SignalBridgeConfig, optional
        信号桥接配置。不提供时使用默认值。
    capital_share : float, optional
        该策略可用的资金比例或金额。在 run_multi 中通常由
        CapitalAllocator 确定，此处仅作默认值。
    tag : str, optional
        策略标签（用于标识）。
    params : dict, optional
        策略参数覆盖。
    """

    strategy: Strategy
    bridge_config: Optional[SignalBridgeConfig] = None
    capital_share: float = 0.0
    tag: str = ""
    params: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.tag:
            self.tag = type(self.strategy).__name__


@dataclass
class PerBarSignal:
    """
    单策略在某根Bar上的信号快照（P5-01）。

    Attributes
    ----------
    date : str
        日期（YYYYMMDD）。
    strategy_name : str
        策略名称标识。
    signal : int
        信号值：1=做多, -1=做空, 0=空仓。
    strength : float
        信号强度（0.0~1.0）。
    price : float
        Bar 的收盘价（用于冲突检测参考）。
    quantity : int
        建议交易数量。
    orders : list[Signal], optional
        原始信号列表。
    meta : dict, optional
        额外元信息。
    """

    date: str
    strategy_name: str
    signal: int
    strength: float = 0.0
    price: float = 0.0
    quantity: int = 0
    orders: Optional[List[Signal]] = None
    meta: Optional[Dict[str, Any]] = None


@dataclass
class ConflictEvent:
    """
    冲突事件（P5-02）。

    Attributes
    ----------
    date : str
        冲突日期（YYYYMMDD）。
    pair : tuple[str, str]
        冲突策略对，如 ("trend", "reversal")。
    direction_1 : int
        pair[0] 方向：1=做多, -1=做空, 0=空仓。
    direction_2 : int
        pair[1] 方向：1=做多, -1=做空, 0=空仓。
    price : float
        冲突时的价格。
    resolved : bool
        是否已被解决。
    resolved_direction : int
        解决后的最终方向。
    """

    date: str
    pair: Tuple[str, str]
    direction_1: int
    direction_2: int
    price: float = 0.0
    resolved: bool = False
    resolved_direction: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "pair": list(self.pair),
            "direction_1": self.direction_1,
            "direction_2": self.direction_2,
            "price": self.price,
            "resolved": self.resolved,
            "resolved_direction": self.resolved_direction,
        }


@dataclass
class CombinedResult:
    """
    合并净值结果（P5-07）。

    Attributes
    ----------
    equity_curve : pd.DataFrame
        合并净值曲线，列：
        date | trend_equity | reversal_equity | grid_equity | combined_equity
        | daily_return | cumulative_return
        | benchmark_equity（可选，传入时）
    weights : dict[str, float]
        各策略权重。
    initial_capital : float
        初始资金。
    final_equity : float
        最终合并净值。
    total_return : float
        总收益率。
    annualized_return : float
        年化收益率。
    sharpe_ratio : float
        夏普比率。
    max_drawdown : float
        最大回撤。
    benchmark_total_return : float
        买入持有基准总收益率（benchmark_equity 传入时计算）。
    benchmark_name : str
        基准名称，如 "中国石油" / "沪深300"。
    """

    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    weights: Dict[str, float] = field(default_factory=dict)
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    benchmark_total_return: float = 0.0
    benchmark_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "weights": self.weights,
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "benchmark_total_return": self.benchmark_total_return,
            "benchmark_name": self.benchmark_name,
        }


@dataclass
class MultiStrategyResult:
    """
    多策略统一运行结果（P5-01）。

    Attributes
    ----------
    symbol : str
        股票代码。
    backtest_results : dict[str, BacktestResult]
        各策略独立回测结果。
    strategies : dict[str, Strategy]
        各策略实例。
    signals : list[PerBarSignal]
        逐策略逐 Bar 的信号记录。
    combined : CombinedResult
        合并净值结果。
    conflicts : list[ConflictEvent]
        冲突事件列表。
    allocation : AllocationResult, optional
        资金分配结果。
    benchmark_info : dict, optional
        基准元信息：{name, symbol, start_date, end_date, total_return, data_source}
    """

    symbol: str = ""
    backtest_results: Dict[str, BacktestResult] = field(default_factory=dict)
    strategies: Dict[str, Strategy] = field(default_factory=dict)
    signals: List[PerBarSignal] = field(default_factory=list)
    combined: CombinedResult = field(default_factory=CombinedResult)
    conflicts: List[ConflictEvent] = field(default_factory=list)
    allocation: Optional[AllocationResult] = None
    benchmark_info: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategies": list(self.strategies.keys()),
            "backtest_results": {
                name: r.to_dict() for name, r in self.backtest_results.items()
            },
            "n_signals": len(self.signals),
            "n_conflicts": len(self.conflicts),
            "combined": self.combined.to_dict(),
            "allocation": self.allocation.to_dict() if self.allocation else None,
            "benchmark_info": self.benchmark_info,
        }


# ═══════════════════════════════════════════════════════════════
# P5-01: MultiStrategyRunner
# ═══════════════════════════════════════════════════════════════


@dataclass
class MultiStrategyConfig:
    """
    多策略统一调度配置（P5-01）。

    Parameters
    ----------
    symbol : str
        股票代码。
    start_date : str
        回测起始日期（YYYYMMDD）。
    end_date : str
        回测结束日期（YYYYMMDD）。
    initial_capital : float
        初始总资金。
    fee_rate : float
        手续费率。
    slippage_rate : float
        滑点率。
    db_path : str, optional
        数据库路径。
    """

    symbol: str = "000001.SZ"
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1_000_000.0
    fee_rate: float = 0.0003
    slippage_rate: float = 0.001
    db_path: Optional[str] = None


class MultiStrategyRunner:
    """
    多策略统一调度器（P5-01）。

    同一标的、同一资金池，并行运行趋势/反转/网格三策略。

    用法::

        runner = MultiStrategyRunner(config=MultiStrategyConfig(
            symbol="000001.SZ",
            start_date="20250101",
            end_date="20250501",
            initial_capital=1_000_000.0,
        ))

        # 先由 CapitalAllocator 分配资金
        allocator = CapitalAllocator()
        allocation = allocator.allocate(
            total_capital=1_000_000.0,
            strategy_names=["trend", "reversal", "grid"],
            allocation_mode="equal",
        )

        # 运行各策略（带资金限制）
        result = runner.run_multi(
            strategies={
                "trend": StrategyConfig(strategy=TrendStrategy(ma_fast=5, ma_slow=20)),
                "reversal": StrategyConfig(strategy=ReversalStrategyWrapper(bars=bars)),
                "grid": StrategyConfig(strategy=grid_strategy_instance),
            },
            bars=bars,
            allocation=allocation,
        )
    """

    def __init__(self, config: Optional[MultiStrategyConfig] = None):
        self.config = config or MultiStrategyConfig()
        self._allocator = CapitalAllocator()

    def run_multi(
        self,
        strategies: Dict[str, StrategyConfig],
        bars: List[Bar],
        allocation: Optional[AllocationResult] = None,
        enable_conflict_detection: bool = True,
        benchmark_equity: Optional[List[float]] = None,
        benchmark_name: str = "",
    ) -> MultiStrategyResult:
        """
        执行多策略回测。

        流程：
          1. 对每个策略创建 BacktestEngine，使用 allocation 中的分配资金
          2. 分别 run() 各策略
          3. 提取各策略逐Bar信号
          4. 检测冲突（可选）
          5. 合并净值

        参数
        ----------
        strategies : dict[str, StrategyConfig]
            策略名 → 策略配置。
        bars : list[Bar]
            K线数据列表。
        allocation : AllocationResult, optional
            资金分配结果。不提供则等分配。
        enable_conflict_detection : bool
            是否检测信号冲突。

        返回
        -------
        MultiStrategyResult
            统一运行结果。
        """
        if not strategies:
            raise ValueError("至少需要一个策略")
        if not bars:
            raise ValueError("K线数据不能为空")

        # ── 1. 资金分配 ──────────────────────────────────
        if allocation is None:
            allocation = self._allocator.allocate(
                total_capital=self.config.initial_capital,
                strategy_names=list(strategies.keys()),
                allocation_mode="equal",
            )

        # ── 2. 各策略独立运行 ────────────────────────────
        backtest_results: Dict[str, BacktestResult] = {}
        strategy_instances: Dict[str, Strategy] = {}

        for name, sc in strategies.items():
            capital = allocation.allocations.get(name, self.config.initial_capital / max(len(strategies), 1))

            bt_config = BacktestConfig(
                start_date=self.config.start_date,
                end_date=self.config.end_date,
                initial_capital=capital,
                fee_rate=self.config.fee_rate,
                slippage_rate=self.config.slippage_rate,
            )

            engine = BacktestEngine(config=bt_config, strategy=sc.strategy)
            result = engine.run(bars)
            backtest_results[name] = result
            strategy_instances[name] = sc.strategy

        # ── 3. 提取逐Bar信号 ────────────────────────────
        signals = self._extract_signals(bars, backtest_results, list(strategies.keys()))

        # ── 4. 冲突检测 ──────────────────────────────────
        conflicts: List[ConflictEvent] = []
        if enable_conflict_detection:
            conflict_signals = self._build_conflict_signal_map(signals)
            detector = ConflictDetector()
            for date, sig_map in conflict_signals.items():
                date_conflicts = detector.detect(sig_map, date=date)
                conflicts.extend(date_conflicts)

        # ── 5. 合并净值 ──────────────────────────────────
        weights = allocation.weights
        equity_df = self._build_strategy_equity_dfs(backtest_results)
        combined = self._compute_combined(equity_df, weights, self.config.initial_capital, benchmark_equity=benchmark_equity, benchmark_name=benchmark_name)

        return MultiStrategyResult(
            symbol=self.config.symbol,
            backtest_results=backtest_results,
            strategies=strategy_instances,
            signals=signals,
            combined=combined,
            conflicts=conflicts,
            allocation=allocation,
            benchmark_info={
                "name": benchmark_name,
                "has_data": benchmark_equity is not None,
                "total_return": combined.benchmark_total_return,
            } if benchmark_equity is not None else None,
        )

    def run_multi_batch(
        self,
        symbols_strategies: Dict[str, Dict[str, StrategyConfig]],
        bars_map: Dict[str, List[Bar]],
        allocation_map: Optional[Dict[str, AllocationResult]] = None,
    ) -> Dict[str, MultiStrategyResult]:
        """
        批量运行多策略回测。

        参数
        ----------
        symbols_strategies : dict
            {symbol: {strategy_name: StrategyConfig}}
        bars_map : dict
            {symbol: [Bar]}
        allocation_map : dict, optional
            {symbol: AllocationResult}

        返回
        -------
        dict[str, MultiStrategyResult]
            每个标的的运行结果。
        """
        results: Dict[str, MultiStrategyResult] = {}
        for symbol, strategies in symbols_strategies.items():
            bars = bars_map.get(symbol, [])
            allocation = allocation_map.get(symbol) if allocation_map else None
            if not bars:
                continue
            # 临时替换 config.symbol
            original_symbol = self.config.symbol
            self.config.symbol = symbol
            results[symbol] = self.run_multi(
                strategies=strategies,
                bars=bars,
                allocation=allocation,
            )
            self.config.symbol = original_symbol
        return results

    # ── 内部辅助 ─────────────────────────────────────────

    @staticmethod
    def _extract_signals(
        bars: List[Bar],
        backtest_results: Dict[str, BacktestResult],
        strategy_names: List[str],
    ) -> List[PerBarSignal]:
        """
        从回测结果中提取逐Bar信号。

        从各策略的 trade history + equity curve 推算每日信号。
        若策略提供 bridge，优先从 bridge._signal_cache 读取。
        """
        # 按日期构建信号索引
        date_signals: Dict[str, Dict[str, PerBarSignal]] = {}

        # 从 equity_curve 获取日期序列
        dates = set()
        for result in backtest_results.values():
            for point in result.equity_curve:
                dates.add(point["date"])
        sorted_dates = sorted(dates)

        for name in strategy_names:
            result = backtest_results.get(name)
            if not result:
                continue

            # 从 trade history 提取交易信号
            for trade in result.trades:
                trade_date = trade.get("date", "")
                side = trade.get("side", "")
                price = trade.get("price", 0.0)
                quantity = trade.get("quantity", 0)
                signal_val = 1 if side.upper() == "BUY" else -1

                if trade_date not in date_signals:
                    date_signals[trade_date] = {}
                date_signals[trade_date][name] = PerBarSignal(
                    date=trade_date,
                    strategy_name=name,
                    signal=signal_val,
                    strength=1.0,
                    price=float(price),
                    quantity=int(quantity),
                )

        # 平铺为列表
        all_signals: List[PerBarSignal] = []
        for d in sorted_dates:
            for name in strategy_names:
                sig = date_signals.get(d, {}).get(name)
                if sig:
                    all_signals.append(sig)

        return all_signals

    @staticmethod
    def _build_conflict_signal_map(
        signals: List[PerBarSignal],
    ) -> Dict[str, Dict[str, int]]:
        """将信号列表转为 {date: {strategy_name: signal_value}}。"""
        sig_map: Dict[str, Dict[str, int]] = {}
        for s in signals:
            if s.date not in sig_map:
                sig_map[s.date] = {}
            sig_map[s.date][s.strategy_name] = s.signal
        return sig_map

    @staticmethod
    def _build_strategy_equity_dfs(
        backtest_results: Dict[str, BacktestResult],
    ) -> Dict[str, pd.DataFrame]:
        """
        从各策略的 equity_curve 提取净值 DataFrame。
        返回 {strategy_name: pd.DataFrame(date, equity)}。
        """
        dfs: Dict[str, pd.DataFrame] = {}
        for name, result in backtest_results.items():
            records = [
                {"date": pt["date"], "equity": pt["total_equity"]}
                for pt in result.equity_curve
            ]
            if records:
                dfs[name] = pd.DataFrame(records)
        return dfs

    @staticmethod
    def _compute_combined(
        equity_dfs: Dict[str, pd.DataFrame],
        weights: Dict[str, float],
        initial_capital: float,
        benchmark_equity: Optional[List[float]] = None,
        benchmark_name: str = "",
    ) -> CombinedResult:
        """
        合并各策略净值。

        各策略 equity 按权重加权求和得到 combined_equity。
        若提供了 benchmark_equity，则将其加入 equity_curve 作为基准曲线。
        """
        if not equity_dfs:
            return CombinedResult(initial_capital=initial_capital, benchmark_name=benchmark_name)

        # 合并所有净值到一张 DataFrame
        merged = None
        for name, df in equity_dfs.items():
            df = df.copy()
            df = df.rename(columns={"equity": f"{name}_equity"})
            if merged is None:
                merged = df
            else:
                merged = pd.merge(merged, df, on="date", how="outer")

        if merged is None or merged.empty:
            return CombinedResult(initial_capital=initial_capital, benchmark_name=benchmark_name)

        merged = merged.sort_values("date").reset_index(drop=True)

        # 前向填充缺额
        equity_cols = [c for c in merged.columns if c.endswith("_equity")]
        for col in equity_cols:
            merged[col] = merged[col].ffill()

        # 计算 combined_equity
        merged["combined_equity"] = 0.0
        for name, w in weights.items():
            col = f"{name}_equity"
            if col in merged.columns:
                merged["combined_equity"] += merged[col] * w

        # ── 基准净值（可选） ────────────────────────────
        benchmark_total_return = 0.0
        benchmark_name_out = ""
        if benchmark_equity is not None:
            benchmark_name_out = benchmark_name or "基准"
            # 注入基准净值列（长度不匹配时通过截断/填充对齐）
            if len(benchmark_equity) == len(merged):
                merged["benchmark_equity"] = benchmark_equity
            elif len(benchmark_equity) < len(merged):
                # 短于 merged，NaN 填充后 ffill
                padded = list(benchmark_equity) + [np.nan] * (len(merged) - len(benchmark_equity))
                merged["benchmark_equity"] = padded
            else:
                # 长于 merged，截断
                merged["benchmark_equity"] = benchmark_equity[:len(merged)]
            merged["benchmark_equity"] = merged["benchmark_equity"].ffill()
            if benchmark_equity[0] > 0:
                benchmark_total_return = (benchmark_equity[-1] / benchmark_equity[0] - 1)

        # 收益率
        merged["daily_return"] = merged["combined_equity"].pct_change().fillna(0.0)
        merged["cumulative_return"] = merged["daily_return"].add(1).cumprod().sub(1)

        final_equity = float(merged["combined_equity"].iloc[-1]) if len(merged) > 0 else 0.0
        total_return = float(merged["cumulative_return"].iloc[-1]) if len(merged) > 0 else 0.0

        # 年化收益率
        n_days = len(merged)
        if n_days > 1 and initial_capital > 0:
            total_ret = final_equity / initial_capital - 1
            annual_return = (1 + total_ret) ** (252 / n_days) - 1

            # 夏普
            daily_returns = merged["daily_return"].values
            if daily_returns.std() > 0:
                sharpe = float(
                    daily_returns.mean() / daily_returns.std() * math.sqrt(252)
                )
            else:
                sharpe = 0.0

            # 最大回撤
            cumulative = merged["combined_equity"].values
            peak = np.maximum.accumulate(cumulative)
            drawdown = (cumulative - peak) / peak
            max_dd = float(abs(drawdown.min()))
        else:
            annual_return = 0.0
            sharpe = 0.0
            max_dd = 0.0

        return CombinedResult(
            equity_curve=merged,
            weights=weights,
            initial_capital=initial_capital,
            final_equity=final_equity,
            total_return=total_return,
            annualized_return=annual_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            benchmark_total_return=benchmark_total_return,
            benchmark_name=benchmark_name_out,
        )

    # ── 基准辅助方法 ─────────────────────────────────────

    @staticmethod
    def compute_benchmark_equity(
        bars: List[Bar],
        initial_capital: float = 1_000_000.0,
    ) -> List[float]:
        """
        从 K 线数据计算买入持有净值序列。

        使用 Bar.close 价格序列，假设期初以初始资金全仓买入并持有至期末。
        可用于生成 benchmark_equity 传入 run_multi() 以实现图表叠加和对比。

        参数
        ----------
        bars : list[Bar]
            K线数据列表，需包含 close 字段。
        initial_capital : float
            初始资金（默认 1,000,000）。

        返回
        -------
        list[float]
            与 bars 等长的每日净值序列，首日为 initial_capital。

        用法::

            bars = DataLoader.load_bars(symbol="601857", ...)
            benchmark_eq = MultiStrategyRunner.compute_benchmark_equity(bars)
            result = runner.run_multi(
                strategies=..., bars=bars,
                benchmark_equity=benchmark_eq,
                benchmark_name="中国石油",
            )
        """
        if not bars:
            return []

        closes = [b.close for b in bars]
        if closes[0] == 0:
            return [initial_capital] * len(closes)

        ratio = initial_capital / closes[0]
        return [c * ratio for c in closes]


# ═══════════════════════════════════════════════════════════════
# P5-02: ConflictDetector
# ═══════════════════════════════════════════════════════════════


class ConflictDetector:
    """
    信号冲突检测器（P5-02）。

    同一日两个策略方向相反 → 标记为冲突。

    用法::

        detector = ConflictDetector()
        # signal_map: {"trend": 1, "reversal": -1, "grid": 0}
        conflicts = detector.detect(signal_map, date="20250501")
        # → [ConflictEvent(date="20250501", pair=("trend","reversal"), ...)]
    """

    def __init__(self, strategy_names: Optional[List[str]] = None):
        """
        参数
        ----------
        strategy_names : list[str], optional
            待检测的策略名称列表。默认 ("trend", "reversal", "grid")。
        """
        self._strategy_names = (
            list(strategy_names) if strategy_names else list(DEFAULT_STRATEGY_NAMES)
        )

    def detect(
        self,
        signal_map: Dict[str, int],
        date: str = "",
        price: float = 0.0,
    ) -> List[ConflictEvent]:
        """
        检测信号冲突。

        参数
        ----------
        signal_map : dict[str, int]
            {策略名: 信号值}，1=做多, -1=做空, 0=空仓。
        date : str
            日期（YYYYMMDD），用于标注冲突发生日。
        price : float
            当前价格，用于参考。

        返回
        -------
        list[ConflictEvent]
            冲突事件列表。无冲突时返回空列表。
        """
        conflicts: List[ConflictEvent] = []
        names = self._strategy_names

        # 两两比较
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                name_i = names[i]
                name_j = names[j]

                sig_i = signal_map.get(name_i, 0)
                sig_j = signal_map.get(name_j, 0)

                # 方向相反：一个为正且另一个为负
                if (sig_i > 0 and sig_j < 0) or (sig_i < 0 and sig_j > 0):
                    conflicts.append(
                        ConflictEvent(
                            date=date,
                            pair=(name_i, name_j),
                            direction_1=sig_i,
                            direction_2=sig_j,
                            price=price,
                        )
                    )

        return conflicts

    def detect_all(
        self,
        signals_by_date: Dict[str, Dict[str, int]],
        price_map: Optional[Dict[str, float]] = None,
    ) -> List[ConflictEvent]:
        """
        批量检测所有日期的冲突。

        参数
        ----------
        signals_by_date : dict
            {date: {strategy_name: signal_value}}
        price_map : dict, optional
            {date: price}，各交易日的价格。

        返回
        -------
        list[ConflictEvent]
            所有日期检测到的冲突。
        """
        all_conflicts: List[ConflictEvent] = []
        for date, sig_map in signals_by_date.items():
            price = price_map.get(date, 0.0) if price_map else 0.0
            conflicts = self.detect(sig_map, date=date, price=price)
            all_conflicts.extend(conflicts)
        return all_conflicts


# ═══════════════════════════════════════════════════════════════
# P5-03: 冲突处理策略
# ═══════════════════════════════════════════════════════════════


def resolve_conflicts(
    signal_map: Dict[str, int],
    conflict_events: Optional[List[ConflictEvent]] = None,
    strategy: str = "priority",
    priority: Optional[Dict[str, int]] = None,
    signal_strengths: Optional[Dict[str, float]] = None,
) -> Dict[str, int]:
    """
    冲突处理（P5-03）。

    根据选定的冲突处理策略，返回修正后的信号字典。

    策略说明：
    - "priority" : 优先级规则。默认趋势 > 反转 > 网格。
       优先级更高的策略的信号覆盖低优先级策略的冲突信号。
    - "vote" : 多数投票。所有策略信号求和取符号。
       正和 → 做多，负和 → 做空，和为 0 → 全部信号归零。
    - "neutral" : 保守模式。冲突日所有涉及冲突的策略信号归零（不交易）。
       其余未冲突策略信号保留。

    参数
    ----------
    signal_map : dict[str, int]
        原始信号字典 {策略名: 信号值}。不会被修改。
    conflict_events : list[ConflictEvent], optional
        已检测到的冲突事件列表。若提供，仅对有冲突的策略对
        进行修正（"priority" 和 "neutral" 模式下可提高效率）。
        不提供时，函数会重新检测冲突。
    strategy : str
        冲突处理策略： "priority" | "vote" | "neutral"。
        默认 "priority"。
    priority : dict[str, int], optional
        自定义优先级字典。默认 CONFLICT_PRIORITY
        (trend=3, reversal=2, grid=1)。
    signal_strengths : dict[str, float], optional
        各策略信号强度（0~1）。仅在 "vote" 模式下使用时，
        投票时按强度加权。不提供时使用等权重。

    返回
    -------
    dict[str, int]
        修正后的信号字典（原字典的副本）。
    """
    resolved = dict(signal_map)

    if strategy == "vote":
        return _resolve_by_vote(signal_map, signal_strengths)

    if strategy == "neutral":
        return _resolve_by_neutral(signal_map, conflict_events)

    # ── "priority" 模式（默认） ──────────────────────────
    return _resolve_by_priority(signal_map, conflict_events, priority)


def _resolve_by_priority(
    signal_map: Dict[str, int],
    conflict_events: Optional[List[ConflictEvent]] = None,
    priority: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """
    优先级模式：高优先级覆盖低优先级。
    """
    resolved = dict(signal_map)
    prio = priority or dict(CONFLICT_PRIORITY)

    # 确定需要检查的策略对
    pairs_to_check: List[Tuple[str, str]] = []

    if conflict_events:
        for ce in conflict_events:
            a, b = ce.pair
            if (a, b) not in pairs_to_check and (b, a) not in pairs_to_check:
                pairs_to_check.append(ce.pair)
    else:
        names = list(signal_map.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pairs_to_check.append((names[i], names[j]))

    for name_a, name_b in pairs_to_check:
        sig_a = signal_map.get(name_a, 0)
        sig_b = signal_map.get(name_b, 0)

        # 只有方向相反才处理
        if not ((sig_a > 0 and sig_b < 0) or (sig_a < 0 and sig_b > 0)):
            continue

        prio_a = prio.get(name_a, 1)
        prio_b = prio.get(name_b, 1)

        if prio_a > prio_b:
            # A 保留信号，B 归零
            resolved[name_b] = 0
        elif prio_b > prio_a:
            resolved[name_a] = 0
        else:
            # 同优先级 → 都归零
            resolved[name_a] = 0
            resolved[name_b] = 0

    return resolved


def _resolve_by_vote(
    signal_map: Dict[str, int],
    signal_strengths: Optional[Dict[str, float]] = None,
) -> Dict[str, int]:
    """
    投票模式：信号求和取符号。
    """
    resolved = dict(signal_map)

    if signal_strengths:
        # 加权投票
        weighted_sum = 0.0
        for name, sig in signal_map.items():
            strength = signal_strengths.get(name, 1.0)
            weighted_sum += sig * strength
    else:
        weighted_sum = sum(signal_map.values())

    if weighted_sum > 0:
        final_signal = 1
    elif weighted_sum < 0:
        final_signal = -1
    else:
        final_signal = 0

    # 全部策略采用一致方向
    for name in resolved:
        resolved[name] = final_signal

    return resolved


def _resolve_by_neutral(
    signal_map: Dict[str, int],
    conflict_events: Optional[List[ConflictEvent]] = None,
) -> Dict[str, int]:
    """
    保守模式：冲突策略全部归零。

    仅将产生冲突的策略信号归零，未冲突的策略保留原信号。
    """
    resolved = dict(signal_map)

    if not conflict_events:
        return resolved

    involved: set = set()
    for ce in conflict_events:
        involved.add(ce.pair[0])
        involved.add(ce.pair[1])

    for name in involved:
        resolved[name] = 0

    return resolved


# ═══════════════════════════════════════════════════════════════
# P5-06: MultiStrategyReplay
# ═══════════════════════════════════════════════════════════════


@dataclass
class MultiStrategyReplayConfig:
    """
    多策略同步回放配置（P5-06）。

    用于 MultiStrategyReplay 的运行配置。

    Parameters
    ----------
    symbol : str
        股票代码。
    initial_capital : float
        初始总资金。
    fee_rate : float
        手续费率。
    slippage_rate : float
        滑点率。
    allocation_mode : str
        资金分配模式： "equal" | "weighted" | "dynamic"。
    conflict_resolve_strategy : str
        冲突处理策略： "priority" | "vote" | "neutral"。
    dynamic_sharpe_period : int
        动态分配时使用的夏普计算周期（Bar数）。默认 30。
    allocator_temperature : float
        DynamicCapitalAllocator 的温度参数。默认 1.0。
    use_dynamic_allocator : bool
        是否使用动态资金分配（默认 False）。
    """

    symbol: str = "000001.SZ"
    initial_capital: float = 1_000_000.0
    fee_rate: float = 0.0003
    slippage_rate: float = 0.001
    allocation_mode: str = "equal"
    conflict_resolve_strategy: str = "priority"
    dynamic_sharpe_period: int = 30
    allocator_temperature: float = 1.0
    use_dynamic_allocator: bool = False


class ReplayBarContext:
    """
    单Bar回放上下文。

    在逐Bar回放过程中传递各策略的实时状态。
    """

    def __init__(self, strategy_names: List[str]):
        self.strategy_names = strategy_names
        self.signals: Dict[str, PerBarSignal] = {}
        self.conflicts: List[ConflictEvent] = []
        self.resolved_signals: Dict[str, int] = {}
        self.allocations: Dict[str, float] = {}
        self.equity: float = 0.0
        self.capital_remaining: Dict[str, float] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signals": {
                n: {"signal": s.signal, "strength": s.strength}
                for n, s in self.signals.items()
            },
            "conflicts": [c.to_dict() for c in self.conflicts],
            "resolved_signals": self.resolved_signals,
            "allocations": self.allocations,
            "equity": self.equity,
        }


class MultiStrategyReplay:
    """
    多策略同步回放（P5-06）。

    逐Bar同步执行三策略回放：
    1. K线数据 → 三策略各 on_bar
    2. 各自生成买卖信号
    3. ConflictDetector 检测冲突
    4. resolve_conflicts 处理
    5. CapitalAllocator 分配资金
    6. 按分配资金执行交易
    7. 记录到 MultiStrategyResult

    用法::

        replay = MultiStrategyReplay(config=MultiStrategyReplayConfig(
            symbol="000001.SZ",
            initial_capital=1_000_000.0,
            allocation_mode="equal",
            conflict_resolve_strategy="priority",
        ))
        result = replay.run(strategies={
            "trend": trend_strategy,
            "reversal": reversal_strategy,
            "grid": grid_strategy,
        }, bars=bars)
    """

    def __init__(self, config: Optional[MultiStrategyReplayConfig] = None):
        self.config = config or MultiStrategyReplayConfig()
        self._allocator = CapitalAllocator()
        self._dynamic_allocator = DynamicCapitalAllocator() if config and config.use_dynamic_allocator else None
        self._detector = ConflictDetector()

        # ── 运行时状态 ──────────────────────────────────
        self._strategy_names: List[str] = []
        self._strategies: Dict[str, Strategy] = {}
        self._equity_curves: Dict[str, List[float]] = {}
        self._all_signals: List[PerBarSignal] = []
        self._all_conflicts: List[ConflictEvent] = []
        self._bar_contexts: List[ReplayBarContext] = []
        self._capital_available: Dict[str, float] = {}
        self._sharpe_buffer: Dict[str, List[float]] = {}

    def run(
        self,
        strategies: Dict[str, Strategy],
        bars: List[Bar],
        weights: Optional[Dict[str, float]] = None,
    ) -> MultiStrategyResult:
        """
        执行多策略逐Bar同步回放。

        参数
        ----------
        strategies : dict[str, Strategy]
            {策略名: 策略实例}。至少需要 1 个策略。
        bars : list[Bar]
            按日期升序排列的 K 线数据。
        weights : dict[str, float], optional
            各策略权重。不提供时等分配。

        返回
        -------
        MultiStrategyResult
            逐Bar同步回放结果（含逐Bar上下文）。
        """
        if not strategies:
            raise ValueError("至少需要一个策略")
        if not bars:
            raise ValueError("K线数据不能为空")

        self._strategy_names = list(strategies.keys())
        self._strategies = dict(strategies)
        n = len(self._strategy_names)

        # ── 初始化 ──────────────────────────────────────
        # 初始资金分配
        if weights is None:
            if self.config.use_dynamic_allocator and self._dynamic_allocator:
                # 初始等分配
                weights = {name: 1.0 / n for name in self._strategy_names}
            else:
                alloc_result = self._allocator.allocate(
                    total_capital=self.config.initial_capital,
                    strategy_names=self._strategy_names,
                    allocation_mode=self.config.allocation_mode,
                )
                weights = alloc_result.weights

        # 各策略初始可用资金
        self._capital_available = {
            name: self.config.initial_capital * weights[name]
            for name in self._strategy_names
        }

        self._equity_curves = {name: [] for name in self._strategy_names}
        self._all_signals = []
        self._all_conflicts = []
        self._bar_contexts = []
        self._sharpe_buffer = {name: [] for name in self._strategy_names}

        # ── 遍历每一根 Bar ──────────────────────────────
        for bar_idx, bar in enumerate(bars):
            ctx = ReplayBarContext(self._strategy_names)
            bar_signal_map: Dict[str, int] = {}
            bar_strength_map: Dict[str, float] = {}

            # ── 1. 各策略 on_bar ────────────────────────
            for name, strategy in self._strategies.items():
                order_list = strategy.on_bar(None, bar)  # type: ignore[arg-type]
                signal_val, strength = self._extract_bar_signal(order_list)

                bar_signal_map[name] = signal_val
                bar_strength_map[name] = strength

                sig = PerBarSignal(
                    date=bar.date,
                    strategy_name=name,
                    signal=signal_val,
                    strength=strength,
                    price=bar.close,
                    quantity=0,
                    orders=order_list,
                )
                ctx.signals[name] = sig
                self._all_signals.append(sig)

            # ── 2. 冲突检测 ────────────────────────────
            ctx.conflicts = self._detector.detect(
                bar_signal_map, date=bar.date, price=bar.close
            )
            self._all_conflicts.extend(ctx.conflicts)

            # ── 3. 冲突处理 ────────────────────────────
            ctx.resolved_signals = resolve_conflicts(
                bar_signal_map,
                conflict_events=ctx.conflicts,
                strategy=self.config.conflict_resolve_strategy,
            )

            # ── 4. 资金分配 ────────────────────────────
            if self.config.use_dynamic_allocator and self._dynamic_allocator and bar_idx > 0:
                # 动态分配：基于近期夏普
                sharpe_30d = self._compute_recent_sharpes(bar_idx)
                if sharpe_30d:
                    weights = self._dynamic_allocator.update_weights(
                        sharpe_30d,
                        strategy_names=self._strategy_names,
                        temperature=self.config.allocator_temperature,
                    )
                    available = self._get_current_total_equity()
                    current_alloc = self._allocator.allocate(
                        total_capital=available,
                        strategy_names=self._strategy_names,
                        allocation_mode="weighted",
                        weights=weights,
                    )
                    self._capital_available = dict(current_alloc.allocations)
            else:
                # 静态分配
                total_equity = self._get_current_total_equity()
                current_alloc = self._allocator.allocate(
                    total_capital=total_equity if total_equity > 0 else self.config.initial_capital,
                    strategy_names=self._strategy_names,
                    allocation_mode="weighted",
                    weights=weights,
                )
                self._capital_available = dict(current_alloc.allocations)

            ctx.allocations = dict(self._capital_available)

            # ── 5 & 6. 按分配资金执行 ──────────────────
            for name in self._strategy_names:
                sig = ctx.signals.get(name)
                if sig is None:
                    continue
                resolved_signal = ctx.resolved_signals.get(name, 0)
                if resolved_signal == 0:
                    # 冲突归零或无信号，不执行
                    continue

                order_list = sig.orders
                if not order_list:
                    continue

                # 根据可用资金调整下单量
                capital_limit = self._capital_available.get(name, 0.0)
                adjusted_orders = self._adjust_orders_by_capital(
                    order_list, capital_limit, bar.close
                )

                # 记录调整后的数量
                buy_qty = sum(
                    o.extras.get("quantity", 0) for o in adjusted_orders if o.direction == "BUY"
                )
                sell_qty = sum(
                    o.extras.get("quantity", 0) for o in adjusted_orders if o.direction == "SELL"
                )
                sig.quantity = buy_qty if buy_qty > 0 else -sell_qty

                # 更新可用资金（买入扣除、卖出释放，简化模型）
                if buy_qty > 0:
                    cost = buy_qty * bar.close
                    self._capital_available[name] -= cost
                elif sell_qty > 0:
                    revenue = sell_qty * bar.close
                    self._capital_available[name] += revenue

                # 记录 equity 变动
                self._update_equity(name, bar.close, adjusted_orders)

            # ── 7. 记录总净值 ──────────────────────────
            bar_equity = 0.0
            for name in self._strategy_names:
                if self._equity_curves[name]:
                    bar_equity += self._equity_curves[name][-1]
            ctx.equity = bar_equity
            self._bar_contexts.append(ctx)

            # ── 记录夏普缓冲区 ──────────────────────────
            for name in self._strategy_names:
                if self._equity_curves[name]:
                    recent = self._equity_curves[name]
                    if len(recent) >= 2:
                        daily_ret = (recent[-1] - recent[-2]) / recent[-2]
                        self._sharpe_buffer[name].append(daily_ret)

        # ── 构建结果 ──────────────────────────────────
        return self._build_result(bars)

    # ── 内部辅助 ─────────────────────────────────────────

    @staticmethod
    def _extract_bar_signal(
        orders: Optional[List[Signal]],
    ) -> Tuple[int, float]:
        """
        从策略 on_bar 返回的信号列表提取信号值和强度。

        返回 (signal_value, strength)：
          - 买入信号多 → 1
          - 卖出信号多 → -1
          - 无信号 → 0
        """
        if not orders:
            return (0, 0.0)

        buy_qty = sum(o.extras.get("quantity", 0) for o in orders if o.direction == "BUY")
        sell_qty = sum(o.extras.get("quantity", 0) for o in orders if o.direction == "SELL")

        if buy_qty > 0 and sell_qty == 0:
            return (1, 1.0)
        elif sell_qty > 0 and buy_qty == 0:
            return (-1, 1.0)
        elif buy_qty > sell_qty:
            return (1, min(1.0, buy_qty / (buy_qty + sell_qty)))
        elif sell_qty > buy_qty:
            return (-1, min(1.0, sell_qty / (buy_qty + sell_qty)))
        return (0, 0.0)

    @staticmethod

    def _adjust_orders_by_capital(
        orders: List[Signal],
        capital_limit: float,
        price: float,
    ) -> List[Signal]:
        """
        根据可用资金调整信号数量。

        如果买入金额超过 capital_limit，等比例缩减。
        """
        if capital_limit <= 0:
            return []

        buy_total = sum(
            o.extras.get("quantity", 0) * price for o in orders if o.direction == "BUY"
        )
        if buy_total <= capital_limit:
            return orders

        scale = capital_limit / buy_total
        adjusted: List[Signal] = []
        for o in orders:
            scaled_qty = max(1, int(o.extras.get("quantity", 0) * scale))
            adjusted.append(
                Signal(
                    signal_id=str(uuid.uuid4()),
                    symbol=o.symbol,
                    direction=o.direction,
                    confidence=getattr(o, "confidence", 1.0),
                    horizon=getattr(o, "horizon", "short"),
                    signal_type=getattr(o, "signal_type", "trend"),
                    timestamp=datetime.now(_TZ_CN),
                    protocol_version="1.0",
                    extras={"quantity": scaled_qty},
                )
            )
        return adjusted

    def _update_equity(
        self,
        strategy_name: str,
        price: float,
        adjusted_orders: List[Signal],
    ) -> None:
        """更新某策略的当前净值。"""
        current = self._equity_curves[strategy_name]
        capital = self._capital_available.get(strategy_name, 0.0)
        position_value = 0.0
        for o in adjusted_orders:
            qty = o.extras.get("quantity", 0)
            if o.direction == "BUY":
                position_value += qty * price
            else:
                position_value -= qty * price
        equity = capital + position_value
        current.append(equity if equity > 0 else capital)

    def _get_current_total_equity(self) -> float:
        """计算当前总净值。"""
        total = 0.0
        for name in self._strategy_names:
            curve = self._equity_curves[name]
            if curve:
                total += curve[-1]
            else:
                total += self._capital_available.get(name, 0.0)
        return total if total > 0 else self.config.initial_capital

    def _compute_recent_sharpes(
        self, current_bar_idx: int
    ) -> Optional[Dict[str, float]]:
        """
        基于缓冲区计算各策略近期夏普比率。

        返回 {strategy_name: sharpe_ratio}。
        数据不足时返回 None。
        """
        period = self.config.dynamic_sharpe_period
        sharpes: Dict[str, float] = {}
        all_have_data = True

        for name in self._strategy_names:
            buffer = self._sharpe_buffer.get(name, [])
            if len(buffer) < min(period, 5):
                all_have_data = False
                continue

            recent = buffer[-period:] if len(buffer) >= period else buffer
            returns_arr = np.array(recent)
            std = returns_arr.std()
            if std > 0:
                sharpe = float(returns_arr.mean() / std * math.sqrt(252))
            else:
                sharpe = 0.0
            sharpes[name] = sharpe

        return sharpes if all_have_data and sharpes else None

    def _build_result(self, bars: List[Bar]) -> MultiStrategyResult:
        """将回放过程构建为多策略结果。"""
        equity_df_list = []
        for i, ctx in enumerate(self._bar_contexts):
            row = {"date": bars[i].date, "combined_equity": ctx.equity}
            for name in self._strategy_names:
                curve = self._equity_curves[name]
                if i < len(curve):
                    row[f"{name}_equity"] = curve[i]
            equity_df_list.append(row)

        equity_df = pd.DataFrame(equity_df_list) if equity_df_list else pd.DataFrame()

        # 计算收益率
        if not equity_df.empty and "combined_equity" in equity_df.columns:
            equity_df["daily_return"] = equity_df["combined_equity"].pct_change().fillna(0.0)
            equity_df["cumulative_return"] = equity_df["daily_return"].add(1).cumprod().sub(1)
            final_eq = float(equity_df["combined_equity"].iloc[-1])
            total_ret = float(equity_df["cumulative_return"].iloc[-1])

            n_days = len(equity_df)
            if n_days > 1:
                annual_ret = (1 + total_ret) ** (252 / n_days) - 1
                daily_rets = equity_df["daily_return"].values
                std = daily_rets.std()
                sharpe = float(daily_rets.mean() / std * math.sqrt(252)) if std > 0 else 0.0
                peak = np.maximum.accumulate(equity_df["combined_equity"].values)
                dd = (equity_df["combined_equity"].values - peak) / peak
                mdd = float(abs(dd.min()))
            else:
                annual_ret = 0.0
                sharpe = 0.0
                mdd = 0.0
        else:
            final_eq = 0.0
            total_ret = 0.0
            annual_ret = 0.0
            sharpe = 0.0
            mdd = 0.0

        combined = CombinedResult(
            equity_curve=equity_df,
            weights={name: 1.0 / len(self._strategy_names) for name in self._strategy_names},
            initial_capital=self.config.initial_capital,
            final_equity=final_eq,
            total_return=total_ret,
            annualized_return=annual_ret,
            sharpe_ratio=sharpe,
            max_drawdown=mdd,
        )

        return MultiStrategyResult(
            symbol=self.config.symbol,
            strategies=self._strategies,
            signals=self._all_signals,
            combined=combined,
            conflicts=self._all_conflicts,
        )


# ═══════════════════════════════════════════════════════════════
# P5-07: merge_equity
# ═══════════════════════════════════════════════════════════════


def merge_equity(
    strategies: Dict[str, Any],
    equity_data: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
    initial_capital: float = 1_000_000.0,
) -> pd.DataFrame:
    """
    多策略净值合并（P5-07）。

    将各策略的净值曲线按权重加权组合，得到合并净值。

    参数
    ----------
    strategies : dict
        策略名称 → 策略对象（用于元信息）。
    equity_data : dict[str, pd.DataFrame]
        策略名称 → 净值 DataFrame，需包含 "date" 和 "equity" 列。
    weights : dict[str, float]
        策略名称 → 权重（和为 1.0）。
    initial_capital : float
        初始资金（用于收益率计算）。

    返回
    -------
    pd.DataFrame
        合并净值表，列：
          date | trend_equity | reversal_equity | grid_equity
          | combined_equity | daily_return | cumulative_return
        未运行的策略列为 0。
    """
    if not strategies or not equity_data:
        return pd.DataFrame()

    strategy_names = list(strategies.keys())

    # ── 合并净值到一张表 ──────────────────────────────
    merged: Optional[pd.DataFrame] = None
    for name in strategy_names:
        df = equity_data.get(name)
        if df is None or df.empty:
            continue

        df = df.copy()
        if "date" not in df.columns or "equity" not in df.columns:
            continue

        df = df.rename(columns={"equity": f"{name}_equity"})
        df = df[["date", f"{name}_equity"]]

        if merged is None:
            merged = df
        else:
            merged = pd.merge(merged, df, on="date", how="outer")

    if merged is None or merged.empty:
        return pd.DataFrame()

    merged = merged.sort_values("date").reset_index(drop=True)

    # ── 填充缺失值 ──────────────────────────────────
    equity_cols = [c for c in merged.columns if c.endswith("_equity")]
    for col in equity_cols:
        merged[col] = merged[col].ffill().fillna(initial_capital)

    # ── 添加缺失策略列（权重为 0 的策略） ──────────
    for name in strategy_names:
        col = f"{name}_equity"
        if col not in merged.columns:
            merged[col] = initial_capital

    # ── 计算合并净值 ────────────────────────────────
    merged["combined_equity"] = 0.0
    for name in strategy_names:
        col = f"{name}_equity"
        w = weights.get(name, 0.0)
        merged["combined_equity"] += merged[col] * w

    # ── 收益率计算 ──────────────────────────────────
    merged["daily_return"] = merged["combined_equity"].pct_change().fillna(0.0)
    merged["cumulative_return"] = merged["daily_return"].add(1).cumprod().sub(1)

    return merged
