"""
墨枢 - BacktestEngine
回测引擎核心：配置、模型、策略基类、Bar、迭代器、主循环。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .backtest_context import BacktestContext
from .capital_manager import CapitalManager
from .fee_model import FeeModel, SimpleFeeModel, CNStockFeeModel
from .order_executor import (
    FillReport,
    OrderExecutor,
    OrderSide,
    OrderType,
    TradeRecord,
)
from .performance import Performance, PerformanceCalculator
from .position_manager import CostMethod, Position, PositionManager
from .slippage_model import SlippageModel, NoSlippage, FixedSlippage, RatioSlippage
from .order_executor import OrderSide

# ── P1 预检集成 ───────────────────────────────────────────
from src.backtest.p0_fixes.preflight import check_limit_trade
from src.backtest.p0_fixes.capacity_integration import check_volume_capacity


# ── 涨跌停边界 Helper ───────────────────────────────────


def _get_limit_pct(stock_code: str) -> float:
    """
    根据股票代码判断涨跌停比例。
    - 60xxxx/00xxxx (主板) → 10%
    - 30xxxx (创业板) → 20%
    - 688xxx (科创板) → 20%
    - 8xxxxx (北交所) → 30%
    - ST/*ST (代码未涉及, 默认 10%)
    - 未知 → 10%
    """
    if stock_code.startswith("30"):
        return 0.20
    elif stock_code.startswith("688"):
        return 0.20
    elif stock_code.startswith(("8", "4")):
        return 0.30
    else:
        return 0.10


def _clamp_fill_price(fill_price: float, prev_close: float, stock_code: str, side: OrderSide) -> float:
    """
    涨跌停 clamp：
    - BUY: fill_price <= limit_up
    - SELL: fill_price >= limit_down
    """
    limit_pct = _get_limit_pct(stock_code)
    limit_up = prev_close * (1 + limit_pct)
    limit_down = prev_close * (1 - limit_pct)
    if side == OrderSide.BUY:
        return min(fill_price, limit_up)
    else:
        return max(fill_price, limit_down)

# ═══════════════════════════════════════════════════════════════
# BacktestConfig
# ═══════════════════════════════════════════════════════════════


@dataclass
class BacktestConfig:
    """回测配置"""

    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1_000_000.0
    fee_rate: float = 0.0003
    slippage_rate: float = 0.001
    min_fee: float = 5.0
    cost_method: CostMethod = CostMethod.WEIGHTED_AVG
    snapshot_enabled: bool = True


# FeeModel, SlippageModel, Performance 已迁移到独立模块
# 请参见：
#   - fee_model.py      → FeeModel, SimpleFeeModel, CNStockFeeModel
#   - slippage_model.py → SlippageModel, NoSlippage, FixedSlippage, RatioSlippage
#   - performance.py    → Performance, PerformanceCalculator


# ═══════════════════════════════════════════════════════════════
# Bar
# ═══════════════════════════════════════════════════════════════


@dataclass
class Bar:
    """单根K线数据"""

    date: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0

    def __post_init__(self):
        self.open = float(self.open)
        self.high = float(self.high)
        self.low = float(self.low)
        self.close = float(self.close)
        self.volume = float(self.volume)
        self.vwap = float(self.vwap) if self.vwap else 0.0


# ═══════════════════════════════════════════════════════════════
# OrderRequest   (策略 -> 引擎的下单请求)
# ═══════════════════════════════════════════════════════════════


@dataclass
class OrderRequest:
    """策略发出的下单请求"""

    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float = 0.0

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"下单数量必须为正: {self.quantity}")


# ═══════════════════════════════════════════════════════════════
# Strategy  （抽象基类）
# ═══════════════════════════════════════════════════════════════


class Strategy:
    """
    策略基类。子类应重写 on_start / on_bar / on_end。

    on_bar 应返回 Optional[List[OrderRequest]]，
    引擎会将订单转发给 OrderExecutor。
    """

    def on_start(self, context: BacktestContext) -> None:
        """回测开始时调用，可用于初始化指标。"""
        pass

    def on_bar(
        self, context: BacktestContext, bar: Bar
    ) -> Optional[List[OrderRequest]]:
        """每根K线调用，返回下单请求列表（或 None）。"""
        return None

    def on_end(self, context: BacktestContext) -> None:
        """回测结束时调用。"""
        pass


# ═══════════════════════════════════════════════════════════════
# BarIterator
# ═══════════════════════════════════════════════════════════════


class BarIterator:
    """Bar 迭代器，支持正向遍历。"""

    def __init__(self, bars: List[Bar]):
        self._bars = bars
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self) -> Bar:
        if self._index >= len(self._bars):
            raise StopIteration
        bar = self._bars[self._index]
        self._index += 1
        return bar

    def __len__(self) -> int:
        return len(self._bars)

    @property
    def index(self) -> int:
        return self._index

    @property
    def bars(self) -> List[Bar]:
        return list(self._bars)

    def reset(self) -> None:
        self._index = 0

    def peek(self, offset: int = 0) -> Optional[Bar]:
        """查看未来/过去的Bar（不移动指针）。"""
        idx = self._index + offset
        if 0 <= idx < len(self._bars):
            return self._bars[idx]
        return None


# ═══════════════════════════════════════════════════════════════
# DateAligner
# ═══════════════════════════════════════════════════════════════


class DateAligner:
    """确定实际可用的回测日期范围（对齐数据与配置）。"""

    @staticmethod
    def align(
        config_start: str,
        config_end: str,
        bars: List[Bar],
    ) -> Tuple[str, str]:
        """
        返回 (effective_start, effective_end)。

        如果有 Bar 数据，取 config 与数据的交集；
        数据为空时返回 config 原始值。
        """
        if not bars:
            return config_start, config_end

        dates = sorted({b.date for b in bars})
        data_start = dates[0]
        data_end = dates[-1]

        start = config_start if config_start >= data_start else data_start
        end = config_end if config_end <= data_end else data_end

        # 容错：若 start > end，交换
        if start > end:
            start, end = end, start

        return start, end


# ═══════════════════════════════════════════════════════════════
# BacktestResult
# ═══════════════════════════════════════════════════════════════


@dataclass
class BacktestResult:
    """回测执行结果"""

    config: BacktestConfig
    start_date: str
    end_date: str
    total_bars: int
    trades: List[Dict[str, Any]]
    equity_curve: List[Dict[str, float]]
    snapshots: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    buy_hold_kpi: Optional[dict] = None  # 买入持有KPI（基准对比）

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": {
                "start_date": self.config.start_date,
                "end_date": self.config.end_date,
                "initial_capital": self.config.initial_capital,
                "fee_rate": self.config.fee_rate,
                "slippage_rate": self.config.slippage_rate,
            },
            "actual_range": {"start": self.start_date, "end": self.end_date},
            "total_bars": self.total_bars,
            "total_trades": len(self.trades),
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "snapshots": self.snapshots,
            "metrics": self.metrics,
            "buy_hold_kpi": self.buy_hold_kpi,
        }


# Performance 已迁移到独立模块 (performance.py)
# 保留 Performance.compute 静态方法兼容旧版调用


# ═══════════════════════════════════════════════════════════════
# BacktestEngine
# ═══════════════════════════════════════════════════════════════


@dataclass
class BacktestEngine:
    """
    回测引擎主类。

    用法::

        engine = BacktestEngine(config=cfg, strategy=MyStrategy())
        result = engine.run(bars)
        print(result.metrics)
    """

    config: BacktestConfig
    strategy: Strategy

    # ── 运行时注入 ────────────────────────────────────────────
    context: BacktestContext = field(init=False)
    executor: OrderExecutor = field(init=False)

    # ── 结果缓存 ────────────────────────────────────────────
    trade_history: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[Dict[str, float]] = field(default_factory=list)

    # ── 前收盘价跟踪 ──────────────────────────────────────────
    _prev_close: Dict[str, float] = field(default_factory=dict)  # symbol → last close

    def __post_init__(self):
        """初始化上下文和订单执行器。"""
        self.context = BacktestContext(
            initial_capital=self.config.initial_capital,
            cost_method=self.config.cost_method,
        )
        self.context.enable_snapshot(self.config.snapshot_enabled)

        self.executor = OrderExecutor(
            context=self.context,
            slippage_rate=self.config.slippage_rate,
            fee_rate=self.config.fee_rate,
            min_fee=self.config.min_fee,
        )
        self.trade_history = []
        self.equity_curve = []
        self._prev_close = {}

    # ── 主体 run 方法 ────────────────────────────────────────

    def run(self, bars: List[Bar]) -> BacktestResult:
        """
        执行回测主循环。

        流程:
          1. DateAligner 对齐日期范围
          2. 过滤有效 Bar 列表
          3. 创建 BarIterator
          4. 调用 strategy.on_start()
          5. 逐 Bar:
             - context.on_bar(date, symbol)
             - strategy.on_bar() → 获取下单请求
             - 通过 OrderExecutor 执行订单
             - 记录快照 & 净值曲线
          6. 调用 strategy.on_end()
          7. 计算绩效指标并返回 BacktestResult

        参数
        ----------
        bars : List[Bar]
            全部K线数据列表。

        返回
        -------
        BacktestResult
            包含交易记录、净值曲线、绩效指标的完整结果。
        """
        # ── 1. 日期对齐 ──────────────────────────────────────
        actual_start, actual_end = DateAligner.align(
            self.config.start_date, self.config.end_date, bars
        )

        # ── 2. 过滤 Bar ──────────────────────────────────────
        filtered_bars = [
            b
            for b in bars
            if actual_start <= b.date <= actual_end
        ]
        filtered_bars.sort(key=lambda b: (b.date, b.symbol))

        # ── 3. 创建迭代器 ──────────────────────────────────────
        iterator = BarIterator(filtered_bars)

        # ── 4. on_start ──────────────────────────────────────
        self.strategy.on_start(self.context)

        # ── 5. Bar 主循环 ────────────────────────────────────
        for bar in iterator:
            # 更新上下文指针
            self.context.on_bar(bar.date, bar.symbol)

            # 调用策略
            orders = self.strategy.on_bar(self.context, bar)

            # 执行策略下单
            if orders:
                self._execute_orders(orders, bar)

            # 更新前收盘价（供下一交易日使用）
            self._prev_close[bar.symbol] = bar.close

            # 记录快照 + 净值曲线（使用收盘价估算持仓市值）
            price_map = {bar.symbol: bar.close}
            if self.config.snapshot_enabled:
                self.context.take_snapshot(price_map=price_map)

            equity = self.context.total_equity_with_prices(price_map)
            self.equity_curve.append(
                {"date": bar.date, "total_equity": round(equity, 2)}
            )

        # ── 6. on_end ────────────────────────────────────────
        self.strategy.on_end(self.context)

        # ── 7. 构建结果 ──────────────────────────────────────
        self.trade_history = self.executor.get_trade_history()
        metrics = Performance.compute(
            self.equity_curve,
            self.config.initial_capital,
            self.trade_history,
        )

        return BacktestResult(
            config=self.config,
            start_date=actual_start,
            end_date=actual_end,
            total_bars=len(filtered_bars),
            trades=self.trade_history,
            equity_curve=self.equity_curve,
            snapshots=self.context.get_snapshot_history(),
            metrics=metrics,
        )

    # ── 订单执行 ──────────────────────────────────────────

    def _execute_orders(
        self, orders: List[OrderRequest], bar: Bar
    ) -> List[FillReport]:
        """
        批量执行策略下单请求。

        市价单：按 bar.close 价格执行
        限价单：检查 bar 价格是否触发
        """
        reports: List[FillReport] = []
        for order in orders:
            try:
                # ── P1 预检：涨跌停检查 ──────────────────────
                prev_close = self._prev_close.get(order.symbol, bar.open)
                limit_ok, limit_reason, _ = check_limit_trade(
                    prev_close=prev_close,
                    current_price=bar.close,
                    stock_code=order.symbol,
                    side=order.side,
                )
                if not limit_ok:
                    fill = FillReport(
                        filled=False, fill_price=0.0, fill_quantity=0,
                        fill_fee=0.0, message=f"涨跌停拒绝: {limit_reason}",
                    )
                    reports.append(fill)
                    continue

                # ── P1 预检：成交量容量检查 ──────────────────
                cap_allowed, max_qty, cap_reason = check_volume_capacity(
                    order_qty=order.quantity,
                    bar_volume=bar.volume,
                )
                if not cap_allowed and max_qty == 0:
                    fill = FillReport(
                        filled=False, fill_price=0.0, fill_quantity=0,
                        fill_fee=0.0, message=f"容量拒绝: {cap_reason}",
                    )
                    reports.append(fill)
                    continue
                effective_qty = min(order.quantity, max_qty)

                if order.order_type == OrderType.MARKET:
                    fill = self.executor.execute_market(
                        symbol=order.symbol,
                        side=order.side,
                        quantity=effective_qty,
                        price=bar.close,
                    )
                else:
                    fill = self.executor.execute_limit(
                        symbol=order.symbol,
                        side=order.side,
                        quantity=effective_qty,
                        limit_price=order.limit_price,
                        current_price=bar.close,
                    )
                # ── 涨跌停 clamp ────────────────────────────
                if fill.filled and fill.fill_price > 0:
                    fill.fill_price = _clamp_fill_price(
                        fill_price=fill.fill_price,
                        prev_close=prev_close,
                        stock_code=order.symbol,
                        side=order.side,
                    )
                reports.append(fill)
            except Exception as e:
                reports.append(FillReport(
                    filled=False, fill_price=0.0, fill_quantity=0,
                    fill_fee=0.0, message=f"订单执行异常: {e}",
                ))
        return reports

    # ── 重置 ──────────────────────────────────────────────

    def reset(self) -> None:
        """重置引擎到初始状态（可复用于多次 run）。"""
        self.__post_init__()
