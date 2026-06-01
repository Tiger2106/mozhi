"""
SimulateLayer — 模拟执行层 (BT-001/BT-005/BT-008)
=================================================
职责：
1. 接收信号列表 + BacktestData，执行模拟交易
2. BT-008: 约束叠加（停牌 > 涨跌停 > T+1）
3. BT-005: 交易日志完整可审计
4. P0: T+1 延迟处理 + 分红对齐

约束：
- 输入: List[Signal] + BacktestData
- 输出: SimulateResult（含完整交易日志）
- BT-008: 停牌检查 → 涨跌停检查 → T+1 检查（优先级顺序）

作者: moheng
版本: v1.0
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from collections import defaultdict

from ..contracts.backtest_data_contract import BacktestData, BacktestBar
from ..layers.compute_layer import Signal

_TZ_CN = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════
# 执行约束模型 (BT-008)
# ═══════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """BT-005: 完整交易记录"""
    trade_id: int
    symbol: str
    direction: str                    # "BUY" | "SELL"
    price: float                      # 成交价
    quantity: int                     # 成交数量
    amount: float                     # 成交金额
    fee: float                        # 手续费
    signal_date: str                  # 信号日期
    exec_date: str                    # 执行日期
    signal_id: str                    # 关联信号 ID
    delay_days: int = 0               # T+1 延迟天数
    constraint_hit: str = ""           # 触发的约束（涨停/跌停/停牌/T+1）
    status: str = "filled"            # filled | pending | failed


@dataclass
class PositionSnapshot:
    """日终持仓快照"""
    date: str
    total_equity: float
    cash: float
    market_value: float
    position_qty: int
    cumulative_return_pct: float
    unrealized_pnl: float = 0.0


@dataclass
class SimulateResult:
    """模拟层输出"""
    symbol: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    total_trades: int
    trades: List[TradeRecord]       # BT-005: 完整审计日志
    equity_curve: List[PositionSnapshot]
    metrics: Dict[str, float]
    warnings: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# CLOB — 约束感知限价指令簿 (BT-008)
# ═══════════════════════════════════════════════════════════

class ConstraintAwareExecutor:
    """约束感知执行器

    ⚠️ 已标记为 DEPRECATED — 请迁移至 engine.sim_layer.constraints.ConstraintManager
    ============================================================
    BT-008 约束逻辑已统一迁移至:
        engine/sim_layer/constraints.py → ConstraintManager
        engine/sim_layer/simulator.py  → ConstraintAwareExecutor (新)
        engine/sim_layer/logger.py     → TradeLogger

    本类中的约束检查方法 (_is_suspended, _is_limit_up, _is_limit_down, _check_t1_pending)
    均为原始内联实现，不再维护。新约束逻辑请使用:
        from engine.sim_layer.constraints import ConstraintManager
        mgr = ConstraintManager()
        mgr.check_buy(bar, prev_close)
        mgr.check_sell(bar, prev_close, buy_date)

    旧接口保留以兼容现有引用，但不再修复/扩展。
    ============================================================

    BT-008 优先级:
    1. 停牌检查（volume == 0 → 无法交易）
    2. 涨跌停检查（当日涨跌达到20%限制 → 无法交易）
    3. T+1 检查（当日买入 → 次日才可卖出）
    """

    # A 股涨跌停限制
    LIMIT_UP_RATIO = 0.20    # 20%（科创/创业板）— 601857 主板 10%
    LIMIT_DOWN_RATIO = 0.10  # 601857 是主板

    def __init__(self, fee_rate: float = 0.0003,
                 slippage_rate: float = 0.001,
                 min_fee: float = 5.0,
                 stamp_tax_rate: float = 0.0005):
        import warnings
        warnings.warn(
            "layers.simulate_layer.ConstraintAwareExecutor 已废弃，"
            "请使用 engine.sim_layer.constraints.ConstraintManager",
            DeprecationWarning,
            stacklevel=2,
        )
        self._fee_rate = fee_rate
        self._slippage_rate = slippage_rate
        self._min_fee = min_fee
        # P2-2: 印花税（仅卖出方）
        self._stamp_tax_rate = stamp_tax_rate
        # T+1: 买入日期 → 可卖日期
        self._buy_dates: Dict[str, str] = {}  # 买入日期 → 信号 ID 的映射
        self._pending_buys: Dict[str, List[Signal]] = defaultdict(list)  # 挂单
        self._pending_sells: Dict[str, List[Signal]] = defaultdict(list)

    def _is_suspended(self, bar: BacktestBar) -> bool:
        """BT-008: 停牌检查"""
        return bar.volume == 0 or bar.close == 0

    def _is_limit_up(self, bar: BacktestBar, prev_close: float) -> bool:
        """BT-008: 涨停检查"""
        if prev_close <= 0:
            return False
        change_ratio = (bar.close / prev_close) - 1
        return change_ratio >= self.LIMIT_DOWN_RATIO

    def _is_limit_down(self, bar: BacktestBar, prev_close: float) -> bool:
        """BT-008: 跌停检查"""
        if prev_close <= 0:
            return False
        change_ratio = (bar.close / prev_close) - 1
        return change_ratio <= -self.LIMIT_DOWN_RATIO

    def _check_t1_pending(self, direction: str,
                          signal_date: str,
                          exec_date: str) -> bool:
        """BT-008 + P0-FIX-001: T+1 延迟检查

        买入操作：当日可执行
        卖出操作：必须晚于买入日 ≥1 天
        """
        if direction == "BUY":
            return True  # 买入无 T+1 限制
        # SELL: 检查是否是当天买入的
        # 如果信号日期 == 执行日期 且当日还有买入，触达 T+1
        if signal_date == exec_date:
            return False
        return True

    def execute_signals(self, data: BacktestData,
                        signals: List[Signal],
                        initial_capital: float) -> SimulateResult:
        """执行所有信号，返回完整结果"""
        cash = initial_capital
        position_qty = 0
        position_cost = 0.0
        trades: List[TradeRecord] = []
        equity_curve: List[PositionSnapshot] = []
        trade_counter = 0
        warnings: List[str] = []

        # 构建日期→bar 的映射和价格索引
        date_to_idx = {b.date: i for i, b in enumerate(data.bars)}

        # P0-FIX-001: 分时闸门——挂单处理
        pending_buy_signals: List[Tuple[Signal, int]] = []
        pending_sell_signals: List[Tuple[Signal, int]] = []

        for idx, bar in enumerate(data.bars):
            # 检查挂单
            pending_buy_to_exec = [s for s, i in pending_buy_signals if i <= idx]
            for sig in pending_buy_to_exec:
                trade_counter += 1
                qty = sig.extras.get("quantity", 0)
                price = bar.close * (1 + self._slippage_rate)
                amount = qty * price
                fee = max(amount * self._fee_rate, self._min_fee)
                cost = amount + fee

                if cost <= cash:
                    cash -= cost
                    position_qty += qty
                    position_cost = price
                    trades.append(TradeRecord(
                        trade_id=trade_counter,
                        symbol=sig.symbol,
                        direction="BUY",
                        price=price,
                        quantity=qty,
                        amount=amount,
                        fee=fee,
                        signal_date=sig.bar_date,
                        exec_date=bar.date,
                        signal_id=sig.signal_id,
                        delay_days=1,
                        constraint_hit="T+1_pending",
                        status="filled",
                    ))
            pending_buy_signals = [(s, i) for s, i in pending_buy_signals
                                   if i > idx]

            # 当前 bar 产生的信号
            bar_signals = [s for s in signals if s.bar_index == idx]

            for sig in bar_signals:
                if sig.direction == "BUY":
                    qty = sig.extras.get("quantity", 0)
                    if qty <= 0:
                        continue

                    # BT-008: 停牌检查
                    if self._is_suspended(bar):
                        warnings.append(
                            f"Suspended: {sig.symbol} on {bar.date} — signal skipped"
                        )
                        # P0-FIX-001: 挂单（次日再试）
                        pending_buy_signals.append((sig, idx + 1))
                        continue

                    # BT-008: 涨停检查（买入时检查是否已涨停）
                    if idx > 0:
                        prev_close = data.bars[idx - 1].close
                        if self._is_limit_up(bar, prev_close):
                            warnings.append(
                                f"Limit up: {sig.symbol} on {bar.date} — buy skipped"
                            )
                            pending_buy_signals.append((sig, idx + 1))
                            continue

                    # 执行买入
                    trade_counter += 1
                    price = bar.close * (1 + self._slippage_rate)
                    amount = qty * price
                    fee = max(amount * self._fee_rate, self._min_fee)
                    cost = amount + fee

                    if cost <= cash:
                        cash -= cost
                        position_qty += qty
                        position_cost = price
                        trades.append(TradeRecord(
                            trade_id=trade_counter,
                            symbol=sig.symbol,
                            direction="BUY",
                            price=price,
                            quantity=qty,
                            amount=amount,
                            fee=fee,
                            signal_date=bar.date,
                            exec_date=bar.date,
                            signal_id=sig.signal_id,
                            status="filled",
                        ))

                elif sig.direction == "SELL" and position_qty > 0:
                    qty = min(sig.extras.get("quantity", position_qty), position_qty)

                    # BT-008: 停牌检查
                    if self._is_suspended(bar):
                        # P0-FIX-001: 挂单（停牌后恢复交易再卖）
                        warnings.append(
                            f"Suspended: {sig.symbol} on {bar.date} — sell pending"
                        )
                        pending_sell_signals.append((sig, idx + 1))
                        continue

                    # BT-008: 涨跌停检查（卖出时检查是否跌停）
                    if idx > 0:
                        prev_close = data.bars[idx - 1].close
                        if self._is_limit_down(bar, prev_close):
                            warnings.append(
                                f"Limit down: {sig.symbol} on {bar.date} — sell pending"
                            )
                            pending_sell_signals.append((sig, idx + 1))
                            continue

                    # P0-FIX-001: T+1 检查
                    # 找到最近一次买入记录
                    if not self._check_t1_pending("SELL", bar.date, bar.date):
                        # T+1 未满足，挂单到次日
                        pending_sell_signals.append((sig, idx + 1))
                        continue

                    # 执行卖出
                    trade_counter += 1
                    price = bar.close * (1 - self._slippage_rate)
                    amount = qty * price
                    # P2-2: 印花税（仅卖出方，0.1%)
                    fee = max(amount * self._fee_rate, self._min_fee)
                    stamp_tax = amount * self._stamp_tax_rate
                    total_cost = fee + stamp_tax
                    cash += amount - total_cost
                    position_qty -= qty

                    trades.append(TradeRecord(
                        trade_id=trade_counter,
                        symbol=sig.symbol,
                        direction="SELL",
                        price=price,
                        quantity=qty,
                        amount=amount,
                        fee=total_cost,
                        signal_date=bar.date,
                        exec_date=bar.date,
                        signal_id=sig.signal_id,
                        status="filled",
                    ))

            # 执行挂单卖出
            pending_sell_exec = [s for s, i in pending_sell_signals if i <= idx]
            for sig in pending_sell_exec:
                if position_qty <= 0:
                    continue
                qty = min(sig.extras.get("quantity", position_qty), position_qty)
                trade_counter += 1
                price = bar.close * (1 - self._slippage_rate)
                amount = qty * price
                # P2-2: 印花税
                fee = max(amount * self._fee_rate, self._min_fee)
                stamp_tax = amount * self._stamp_tax_rate
                total_cost = fee + stamp_tax
                cash += amount - total_cost
                position_qty -= qty
                trades.append(TradeRecord(
                    trade_id=trade_counter,
                    symbol=sig.symbol,
                    direction="SELL",
                    price=price,
                    quantity=qty,
                    amount=amount,
                    fee=total_cost,
                    signal_date="pending",
                    exec_date=bar.date,
                    signal_id=sig.signal_id,
                    delay_days=1,
                    constraint_hit="T+1_pending",
                    status="filled",
                ))
            pending_sell_signals = [(s, i) for s, i in pending_sell_signals
                                    if i > idx]

            # 日终快照
            market_value = position_qty * bar.close
            total_equity = cash + market_value
            cum_return = (total_equity / initial_capital - 1) * 100
            equity_curve.append(PositionSnapshot(
                date=bar.date,
                total_equity=round(total_equity, 2),
                cash=round(cash, 2),
                market_value=round(market_value, 2),
                position_qty=position_qty,
                cumulative_return_pct=round(cum_return, 4),
                unrealized_pnl=round(market_value - position_qty * position_cost, 2)
                if position_qty > 0 else 0,
            ))

        # 计算结果指标
        final_equity = equity_curve[-1].total_equity if equity_curve else initial_capital
        total_return = (final_equity / initial_capital - 1) * 100
        profit_trades = sum(1 for t in trades
                            if t.direction == "SELL" and t.amount > position_cost * t.quantity * 0.9)
        loss_trades = len(trades) - profit_trades
        win_rate = profit_trades / len(trades) * 100 if trades else 0

        metrics = {
            "total_return_pct": round(total_return, 4),
            "total_trades": len([t for t in trades if t.direction == "SELL"]),
            "buy_trades": len([t for t in trades if t.direction == "BUY"]),
            "sell_trades": len([t for t in trades if t.direction == "SELL"]),
            "profit_trades": profit_trades,
            "loss_trades": loss_trades,
            "win_rate_pct": round(win_rate, 2),
            "final_capital": round(final_equity, 2),
        }

        return SimulateResult(
            symbol=data.symbol,
            initial_capital=initial_capital,
            final_capital=round(final_equity, 2),
            total_return_pct=round(total_return, 4),
            total_trades=len(trades),
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
            warnings=warnings,
        )


# ═══════════════════════════════════════════════════════════
# 简化接口
# ═══════════════════════════════════════════════════════════

def simulate(data: BacktestData, signals: List[Signal],
             initial_capital: float = 1_000_000.0,
             fee_rate: float = 0.0003,
             slippage_rate: float = 0.001,
             min_fee: float = 5.0,
             stamp_tax_rate: float = 0.0005) -> SimulateResult:
    """一站式模拟执行"""
    executor = ConstraintAwareExecutor(
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        min_fee=min_fee,
        stamp_tax_rate=stamp_tax_rate,
    )
    return executor.execute_signals(data, signals, initial_capital)
