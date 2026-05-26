"""
mozhi_platform.src.backtest.engine.portfolio_integration — PortfolioIntegration

将 MethodResult.signals 通过 PortfolioManager 转换为权益曲线、成交记录和日频指标。

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.engine.portfolio.portfolio_manager import PortfolioManager
from backtest.risk.risk_pipeline import RiskPipeline

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# TradePair dataclass（Bundle.trades 的元素类型）
# ──────────────────────────────────────────────────────────────────────


@dataclass
class TradePair:
    """一笔完整交易（买入 → 卖出配对）。

    将 PortfolioManager 中的连续 TradeRecord 合并为买卖配对，
    方便后续交易行为分析。
    """

    entry_time: str = ""
    """入场时间（ISO 格式）。"""

    entry_price: float = 0.0
    """入场价格。"""

    exit_time: str = ""
    """出场时间（ISO 格式）。"""

    exit_price: float = 0.0
    """出场价格。"""

    pnl: float = 0.0
    """盈亏金额（扣除手续费后）。"""

    qty: int = 0
    """成交数量。"""

    return_pct: float = 0.0
    """盈亏百分比（相对入场成本）。"""

    holding_bars: int = 0
    """持仓期数（Bar 数）。"""


# ──────────────────────────────────────────────────────────────────────
# RiskEvent dataclass（Bundle.risk_events 的元素类型，Phase 3 占位）
# ──────────────────────────────────────────────────────────────────────


@dataclass
class RiskEvent:
    """风控事件（Phase 3 实现完整逻辑）。

    当前仅做结构定义，事件检测逻辑在 Phase 3 实现。
    """

    event_type: str = ""
    """事件类型: drawdown_breach / var_breach / concentration_breach。"""

    timestamp: str = ""
    """事件发生时间（ISO 格式）。"""

    severity: str = "low"
    """严重程度: low / medium / high。"""

    description: str = ""
    """事件描述。"""

    value: float = 0.0
    """触发阈值的事件值。"""

    threshold: float = 0.0
    """阈值。"""


# ──────────────────────────────────────────────────────────────────────
# PortfolioIntegration — 信号 → 权益曲线/成交记录的核心桥梁
# ──────────────────────────────────────────────────────────────────────


class PortfolioIntegration:
    """信号 → 权益曲线 + 成交记录转换器。

    遍历 signals DataFrame 的每一行，通过 PortfolioManager 生成订单、
    更新持仓、记录权益曲线，并在退出时将 TradeRecord 合并为 TradePair。

    Examples:
        >>> pi = PortfolioIntegration(initial_cash=1_000_000.0)
        >>> equity_curve, trades, daily_metrics, summary = pi.run(signals_df, df_ohlcv)
        >>> isinstance(equity_curve, pd.DataFrame)
        True
        >>> len(trades) > 0
        True
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission_pct: float = 0.0003,
        slippage_pct: float = 0.001,
        symbol: str = "",
        seed: int = 0,
        risk_pipeline: RiskPipeline | None = None,
    ):
        self.initial_cash = initial_cash
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.symbol = symbol
        self._seed = seed
        self.risk_pipeline = risk_pipeline

    # ─── 主入口 ───────────────────────────────────────────────────

    def run(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
    ) -> tuple[pd.DataFrame, List[TradePair], pd.DataFrame, Dict[str, Any]]:
        """执行完整信号→交易流程。

        Args:
            signals: 信号 DataFrame（必须含 'signal' 列，索引为 DatetimeIndex）。
            df_ohlcv: OHLCV DataFrame（含 open/high/low/close/volume 列，
                      索引为 DatetimeIndex，须与 signals 对齐）。

        Returns:
            tuple: (equity_curve, trades, daily_metrics, summary_metrics)
                - equity_curve: 包含日期列和净值列的 DataFrame（权益归一化到 1.0 起始）
                - trades: TradePair 列表
                - daily_metrics: 逐日指标 DataFrame
                - summary_metrics: 汇总指标字典
        """
        pm = PortfolioManager(
            initial_cash=self.initial_cash,
            commission_pct=self.commission_pct,
            slippage_pct=self.slippage_pct,
        )

        # ── 1. 对齐信号与价格数据 ────────────────────────────────
        common_index = signals.index.intersection(df_ohlcv.index)
        signals_aligned = signals.loc[common_index]
        prices = df_ohlcv.loc[common_index]

        if len(common_index) == 0:
            logger.warning("信号索引与 OHLCV 索引无交集，返回空结果")
            empty_df = pd.DataFrame({"date": [], "equity": []})
            return empty_df, [], empty_df, {"n_trades": 0, "total_return": 0.0}

        # ── Step A: 市场状态过滤（可选）───────────────────────────
        if self.risk_pipeline and self.risk_pipeline.enabled:
            signals_aligned = self.risk_pipeline.process_pre_filter(
                signals_aligned, df_ohlcv
            )

        # ── Step B: ATR 动态仓位计算（可选）───────────────────────
        if self.risk_pipeline and self.risk_pipeline.enabled:
            sized_signals = self.risk_pipeline.process_position_sizing(
                signals_aligned, df_ohlcv, self.initial_cash
            )
        else:
            sized_signals = signals_aligned.copy()
            sized_signals["position_ratio"] = 1.0

        # ── Step C: 回撤守卫（可选，逐行在循环内调用）───────────────
        drawdown_guard = (
            self.risk_pipeline.get_drawdown_guard()
            if self.risk_pipeline and self.risk_pipeline._enable_drawdown_guard
            else None
        )

        # ── 2. 逐交易时点处理信号 ────────────────────────────────
        last_valid_price = 1.0
        for idx in range(len(sized_signals)):
            timestamp = sized_signals.index[idx]
            original_signal = int(sized_signals["signal"].iloc[idx])
            position_ratio = float(sized_signals["position_ratio"].iloc[idx])
            raw_price = prices.loc[timestamp, "close"] if timestamp in prices.index else prices["close"].iloc[idx]
            # ⚠️ NaN/无效价格保护
            if pd.isna(raw_price) or (hasattr(raw_price, "__float__") and float(raw_price) <= 0):
                price = last_valid_price
            else:
                last_valid_price = float(raw_price)
                price = last_valid_price

            # 回撤守卫
            if drawdown_guard:
                safe_signal = drawdown_guard.update(
                    current_equity=pm.get_portfolio_value(price),
                    timestamp=str(timestamp),
                    current_signal=original_signal,
                )
            else:
                safe_signal = original_signal

            pm.process_signal(
                signal=safe_signal,
                price=price,
                symbol=self.symbol,
                bar_info={"timestamp": timestamp, "idx": idx},
                position_ratio=position_ratio,
            )
            pm.record_equity(price)

        # ── 3. 构建权益曲线 DataFrame（归一化到 1.0 起始）──────────
        raw_equity = np.array(pm.equity_curve, dtype=float)
        if len(raw_equity) == 0:
            empty_df = pd.DataFrame({"date": [], "equity": []})
            return empty_df, [], empty_df, {"n_trades": 0, "total_return": 0.0}

        base_val = max(raw_equity[0], 1e-10)
        normalized_equity = raw_equity / base_val

        equity_curve = pd.DataFrame(
            {
                "date": common_index,
                "equity": normalized_equity,
                "return": np.nan,
            },
            index=common_index,
        )
        # 计算逐日收益
        if len(normalized_equity) > 1:
            arr = np.maximum(normalized_equity, 1e-10)
            returns = arr[1:] / arr[:-1] - 1.0
            equity_curve.loc[equity_curve.index[1:], "return"] = returns
        equity_curve.loc[equity_curve.index[0], "return"] = 0.0

        # ── 4. 构建 TradePair 列表 ───────────────────────────────
        trades = self._build_trade_pairs(pm.trades)

        # ── 5. 构建 daily_metrics DataFrame ──────────────────────
        daily_metrics = self._build_daily_metrics(equity_curve, prices)

        # ── 6. 构建 summary_metrics ──────────────────────────────
        summary_metrics = self._build_summary_metrics(
            equity_curve, trades, daily_metrics
        )

        # 补充 max_drawdown
        if len(raw_equity) > 0:
            eq = normalized_equity
            peak = np.maximum.accumulate(eq)
            dd = (eq - peak) / np.maximum(peak, 1e-10)
            summary_metrics["max_drawdown"] = round(float(dd.min()), 6)

        # ── 7. 汇总风控事件 ──────────────────────────────────
        if drawdown_guard:
            risk_events = self.risk_pipeline.get_all_risk_events() if self.risk_pipeline else []
            if risk_events:
                summary_metrics["risk_events"] = risk_events

        return equity_curve, trades, daily_metrics, summary_metrics

    # ─── 内部辅助 ───────────────────────────────────────────────

    @staticmethod
    def _build_trade_pairs(trade_records: list) -> List[TradePair]:
        """将 PortfolioManager 的 TradeRecord 列表合并为买卖配对。

        配对规则：顺序遍历，遇到 buy 开始配对，遇到第一个 sell 结束配对。
        """
        pairs: List[TradePair] = []
        buy_record = None

        for rec in trade_records:
            if rec.action == "buy" and buy_record is None:
                buy_record = rec
            elif rec.action == "sell" and buy_record is not None:
                # 计算盈亏
                cost = buy_record.price * rec.shares
                revenue = rec.price * rec.shares
                commission_buy = cost * 0.0003  # 默认万三
                commission_sell = revenue * 0.0003
                pnl = revenue - cost - commission_buy - commission_sell

                return_pct = (
                    (pnl / cost) * 100 if cost > 0 else 0.0
                )

                pairs.append(TradePair(
                    entry_time=buy_record.timestamp or str(buy_record.price),
                    entry_price=buy_record.price,
                    exit_time=rec.timestamp or str(rec.price),
                    exit_price=rec.price,
                    pnl=round(pnl, 2),
                    qty=rec.shares,
                    return_pct=round(return_pct, 4),
                ))

                # 买入记录可能存在多笔重复，用仓位清零标记重置
                buy_record = None

        return pairs

    @staticmethod
    def _build_daily_metrics(
        equity_curve: pd.DataFrame,
        prices: pd.DataFrame,
    ) -> pd.DataFrame:
        """构建逐日指标 DataFrame。

        包含：日期、权益、收益率、价格、持仓市值占组合比等。
        """
        df = equity_curve.copy()
        # 合并部分行情信息
        for col in ["open", "high", "low", "close", "volume"]:
            if col in prices.columns:
                df[col] = prices[col].values

        return df

    @staticmethod
    def _build_summary_metrics(
        equity_curve: pd.DataFrame,
        trades: List[TradePair],
        daily_metrics: pd.DataFrame,
    ) -> Dict[str, Any]:
        """构建基础汇总指标。"""
        metrics: Dict[str, Any] = {}

        # 交易统计
        metrics["n_trades"] = len(trades)
        metrics["n_signals"] = len(equity_curve)

        # 收益率
        if not equity_curve.empty and "equity" in equity_curve.columns:
            equity = equity_curve["equity"].values
            total_ret = equity[-1] / max(equity[0], 1e-10) - 1.0
            metrics["total_return"] = round(float(total_ret), 6)
        else:
            metrics["total_return"] = 0.0

        # 胜率
        if trades:
            wins = sum(1 for t in trades if t.pnl > 0)
            metrics["win_rate"] = round(wins / len(trades), 4) if trades else 0.0
            total_pnl = sum(t.pnl for t in trades)
            metrics["net_pnl"] = round(total_pnl, 2)
        else:
            metrics["win_rate"] = 0.0
            metrics["net_pnl"] = 0.0

        return metrics
