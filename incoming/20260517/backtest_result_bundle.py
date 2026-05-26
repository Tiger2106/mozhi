"""
mozhi_platform.src.backtest.engine.backtest_result_bundle — 统一数据源

v3.0 核心数据契约：回测引擎输出 → BacktestResultBundle → ReportBuilder。
所有报告章节均从此统一数据源读取，禁止独立计算。

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.context import StrategyContext
from backtest.methods.base import MethodResult
from backtest.engine.portfolio_integration import (
    PortfolioIntegration,
    TradePair,
    RiskEvent,
)
from backtest.engine.knowledge_entry import KnowledgeEntry

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# BacktestResultBundle — 统一数据源 dataclass（17 字段）
# ══════════════════════════════════════════════════════════════════════


@dataclass
class BacktestResultBundle:
    """回测结果统一数据源。

    Engine → MethodBacktestRunner → BacktestResultBundle → ReportBuilder。
    所有报告章节均从此读取数据。

    Attributes:
        run_id: 回测运行唯一 ID。
        strategy_name: 策略名称。
        method_name: 方法名称。
        symbol: 标的代码（如 "601857.SH"）。
        start_date: 回测起始日期（YYYY-MM-DD）。
        end_date: 回测结束日期（YYYY-MM-DD）。
        params: 回测参数字典。
        equity_curve: 净值曲线 DataFrame（含 date, equity, return 列）。
        benchmark_curve: 基准（buy&hold）净值曲线 DataFrame。
        trades: 成交记录列表，元素为 TradePair。
        daily_metrics: 逐日指标 DataFrame。
        regime_labels: 市场状态标签 DataFrame（Phase 3 前为空占位）。
        parameter_scan: 参数扫描结果 DataFrame（Phase 3 前为空占位）。
        risk_events: 风控事件列表（Phase 3 前为空列表占位）。
        insights: 知识条目列表。
        summary_metrics: 汇总指标字典。
        data_quality: 数据质量声明字典。
    """

    # ─── 标识 ──────────────────────────────────────────────────────

    run_id: str = ""
    """回测运行唯一 ID。"""

    strategy_name: str = ""
    """策略名称。"""

    method_name: str = ""
    """方法名称。"""

    symbol: str = ""
    """标的代码（如 "601857.SH"）。"""

    start_date: str = ""
    """回测起始日期（YYYY-MM-DD）。"""

    end_date: str = ""
    """回测结束日期（YYYY-MM-DD）。"""

    # ─── 核心数据 ──────────────────────────────────────────────────

    params: Dict[str, Any] = field(default_factory=dict)
    """回测参数字典。"""

    equity_curve: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    """净值曲线 DataFrame（含 date, equity, return 列）。
    索引/日期列为 DatetimeIndex。"""

    benchmark_curve: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    """基准（buy&hold）净值曲线 DataFrame。"""

    trades: List[TradePair] = field(default_factory=list)
    """成交记录列表，元素为 TradePair。"""

    daily_metrics: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    """逐日指标 DataFrame。"""

    regime_labels: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    """市场状态标签 DataFrame（Phase 3 前为空占位）。"""

    parameter_scan: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    """参数扫描结果 DataFrame（Phase 3 前为空占位）。"""

    # ─── 高级信息 ──────────────────────────────────────────────────

    risk_events: List[RiskEvent] = field(default_factory=list)
    """风控事件列表（Phase 3 前为空列表占位）。"""

    insights: List[KnowledgeEntry] = field(default_factory=list)
    """知识条目列表。"""

    summary_metrics: Dict[str, Any] = field(default_factory=dict)
    """汇总指标字典（含 n_trades, total_return, win_rate, sharpe 等）。"""

    data_quality: Dict[str, Any] = field(default_factory=dict)
    """数据质量声明字典。
    由 compute_data_quality() 生成，包含完整性/NaN 统计/滑点验证等。
    """

    # ─── 显示 ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<BacktestResultBundle run_id={self.run_id!r} "
            f"method={self.method_name!r} symbol={self.symbol!r} "
            f"trades={len(self.trades)}>"
        )


# ══════════════════════════════════════════════════════════════════════
# Data Quality — 数据质量计算
# ══════════════════════════════════════════════════════════════════════


def compute_data_quality(
    df: pd.DataFrame,
    df_expected: Optional[pd.DataFrame] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """计算数据质量指标。

    从回测实际加载的 OHLCV DataFrame 中计算数据完整率、缺失值统计等，
    并结合配置信息构建完整的数据质量声明字典。

    Args:
        df: 实际加载的数据（OHLCV DataFrame，索引为 DatetimeIndex）。
        df_expected: 预期的完整交易日历 DataFrame（可选，若未提供则假设 df 自身完整）。
        config: 回测配置字典（可选）。

    Returns:
        Dict[str, Any]: 填充 BacktestResultBundle.data_quality 的字典。
    """
    config = config or {}
    actual_days = len(df) if isinstance(df, pd.DataFrame) else 0

    # ── 1. 数据完整率 ─────────────────────────────────────────
    total_days = (
        len(df_expected) if df_expected is not None and len(df_expected) > 0
        else actual_days
    )
    completeness = actual_days / total_days if total_days > 0 else 1.0

    # ── 2. 缺失值统计 ─────────────────────────────────────────
    nan_stats: Dict[str, float] = {}
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            nan_count = int(df[col].isna().sum())
            nan_pct = round(nan_count / actual_days * 100, 2) if actual_days > 0 else 0.0
            nan_stats[col] = nan_pct

    # ── 3. 缺失日期明细 ────────────────────────────────────────
    missing_days = total_days - actual_days
    missing_dates: List[str] = []
    if missing_days > 0 and df_expected is not None:
        _missing = sorted(set(df_expected.index) - set(df.index))
        missing_dates = [str(d.date()) for d in _missing[:10]]

    # ── 4. 数据质量评级 ────────────────────────────────────────
    if total_days == 0:
        rating = "D"
    elif completeness >= 0.95:
        rating = "A"
    elif completeness >= 0.90:
        rating = "B"
    else:
        rating = "C"

    return {
        # 静态配置
        "source": config.get("data_source", "akshare"),
        "period": config.get("data_period", "daily"),
        "adjusted": config.get("adjust_type", "qfq"),
        "nan_handling": config.get("nan_handling", "forward fill"),
        "slippage_model": config.get("slippage_model", "fixed 0.1%"),
        "slippage_validated": False,  # ⚠️ Phase 3 前占位
        "slippage_note": "滑点验证尚未关联真实成交数据（Phase 3 待实现）",
        "commission": config.get("commission", "0.03%"),
        "real_trade": False,
        "benchmark": "buy&hold",
        "engine_version": config.get("engine_version", "v3.0"),
        "fill_method": config.get("fill_method", "forward fill"),
        # 真实可计算
        "completeness": round(completeness * 100, 1),
        "total_days": total_days,
        "actual_days": actual_days,
        "missing_days": missing_days,
        "missing_dates": missing_dates,
        "nan_stats": nan_stats,
        "rating": rating,
    }


# ══════════════════════════════════════════════════════════════════════
# bundle_from_runner — MethodResult → BacktestResultBundle 映射函数
# ══════════════════════════════════════════════════════════════════════


def bundle_from_runner(
    runner_result: MethodResult,
    df_ohlcv: pd.DataFrame,
    ctx: Optional[StrategyContext] = None,
    pm: Optional[PortfolioIntegration] = None,
    run_id: str = "",
    strategy_name: str = "",
) -> BacktestResultBundle:
    """将 MethodBacktestRunner.run() 的 MethodResult 映射为 BacktestResultBundle。

    这是 BacktestResultBundle v3.0 的核心映射函数，负责：
    1. 从 MethodResult.signals 提取交易信号
    2. 通过 PortfolioIntegration 生成 equity_curve / trades / daily_metrics
    3. 从 MethodResult.statistics 映射 summary_metrics
    4. 从 df_ohlcv 计算 data_quality

    Args:
        runner_result: MethodBacktestRunner.run() 的输出（MethodResult 实例）。
        df_ohlcv: 原始 OHLCV DataFrame（索引为 DatetimeIndex）。
        ctx: StrategyContext 实例（可选）。
        pm: PortfolioIntegration 实例（可选，未提供则使用默认配置创建）。
        run_id: 回测运行 ID（可选）。
        strategy_name: 策略名称（可选）。

    Returns:
        BacktestResultBundle: 填充完成的统一数据源。
    """
    # ── 1. 提取基本信息 ──────────────────────────────────────────
    method_name = runner_result.method_name
    symbol = ctx.symbol if ctx else ""

    # 日期范围从 signals 索引推算
    signals = runner_result.signals
    if not signals.empty and isinstance(signals.index, pd.DatetimeIndex):
        start_date = str(signals.index[0].date())
        end_date = str(signals.index[-1].date())
    else:
        start_date = ""
        end_date = ""

    params = runner_result.params

    # ── 2. 通过 PortfolioIntegration 生成权益曲线/成交记录 ───────
    if pm is None:
        pm = PortfolioIntegration(
            symbol=symbol,
            initial_cash=params.get("initial_capital", 1_000_000.0),
            commission_pct=params.get("commission_pct", 0.0003),
            slippage_pct=params.get("slippage_pct", 0.001),
        )

    equity_curve, trades, daily_metrics, portfolio_metrics = pm.run(
        signals, df_ohlcv
    )

    # ── 3. 构建 benchmark_curve (buy&hold) ──────────────────────
    benchmark_curve = _build_benchmark_curve(df_ohlcv, signals)

    # ── 4. 合并 summary_metrics ─────────────────────────────────
    summary_metrics: Dict[str, Any] = dict(portfolio_metrics)

    # 从 MethodResult.statistics 映射更多指标
    for key in ["n_bars", "n_signals", "signal_ratio", "n_buy", "n_sell"]:
        if key in runner_result.statistics:
            summary_metrics[key] = runner_result.statistics[key]

    # 从 MethodResult 回填 n_bars/n_signals
    summary_metrics.setdefault("n_bars", runner_result.n_bars)
    summary_metrics.setdefault("n_signals", runner_result.n_signals)
    summary_metrics.setdefault("signal_ratio", runner_result.signal_ratio)

    # ── 5. 计算 data_quality ────────────────────────────────────
    cfg = ctx.config if ctx else {}
    data_quality = compute_data_quality(df_ohlcv, config=cfg)

    # ── 6. 构建 Bundle ──────────────────────────────────────────
    bundle = BacktestResultBundle(
        run_id=run_id,
        strategy_name=strategy_name,
        method_name=method_name,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        params=params,
        equity_curve=equity_curve,
        benchmark_curve=benchmark_curve,
        trades=trades,
        daily_metrics=daily_metrics,
        summary_metrics=summary_metrics,
        data_quality=data_quality,
    )

    return bundle


# ══════════════════════════════════════════════════════════════════════
# 内部辅助
# ══════════════════════════════════════════════════════════════════════


def _build_benchmark_curve(
    df_ohlcv: pd.DataFrame,
    signals: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """从 OHLCV 数据构建 buy&hold 基准净值曲线。

    以第一条数据的 close 为基准价格，归一化到 1.0。
    若未提供 signals，则以 df_ohlcv 的完整时间范围为基准。

    Args:
        df_ohlcv: OHLCV DataFrame。
        signals: 可选，信号 DataFrame（用于对齐时间范围）。

    Returns:
        pd.DataFrame: 包含 date, equity, return 列的基准曲线。
    """
    if signals is not None and not signals.empty:
        common_idx = signals.index.intersection(df_ohlcv.index)
    else:
        common_idx = df_ohlcv.index

    if len(common_idx) == 0 or "close" not in df_ohlcv.columns:
        return pd.DataFrame()

    prices = df_ohlcv.loc[common_idx, "close"].values
    if len(prices) == 0:
        return pd.DataFrame()

    base_price = prices[0]
    if base_price <= 0:
        return pd.DataFrame()

    equity = prices / base_price
    ret = np.zeros(len(prices))
    if len(prices) > 1:
        ret[1:] = equity[1:] / equity[:-1] - 1.0

    return pd.DataFrame(
        {
            "date": common_idx,
            "equity": equity,
            "return": ret,
        },
        index=common_idx,
    )
