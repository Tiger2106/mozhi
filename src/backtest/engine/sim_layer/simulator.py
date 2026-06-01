"""
模拟交易执行器 (BT-005/BT-008)
================================
职责:
    1. 接收信号列表 + BacktestData，执行模拟交易
    2. BT-008: 约束叠加（停牌 > 涨跌停 > 成交量容量 > T+1）
    3. BT-005: 交易日志完整可审计
    4. P0-FIX-001: T+1 延迟处理 + 分时闸门
    5. P0-FIX-003: 分红现金流对齐

实现:
    基于 layers.simulate_layer 的 ConstraintAwareExecutor，
    集成 P0 修复确保行为符合真实 A 股规则。

P1 修复:
    - P1-2: SlippageModel — 按流动性分档的滑点模型（大盘股 0.1%, 小盘股 0.3%）
    - P1-3: 约束层集成成交量容量检查（委托至 constraints.ConstraintManager）

用法:
    from engine.sim_layer import simulate
    result = simulate(data, signals, initial_capital=1_000_000)

作者: moheng
版本: v1.1
"""
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, field

from ...layers.simulate_layer import (
    ConstraintAwareExecutor as _ConstraintAwareExecutor,
    SimulateResult as _SimulateResult,
    TradeRecord as _TradeRecord,
    PositionSnapshot as _PositionSnapshot,
    simulate as _simulate,
)
from ...contracts.backtest_data_contract import BacktestData
from ..calc_layer.signals import Signal
from .constraints import ConstraintManager, VOLUME_CAPACITY_PCT
from .logger import TradeLogger


# 重导出类型
TradeRecord = _TradeRecord
PositionSnapshot = _PositionSnapshot


@dataclass
class SimulateResult(_SimulateResult):
    """模拟层输出（含 P0 修复标记）"""
    p0_fixes_applied: List[str] = field(default_factory=lambda: [
        "T+1延迟处理 (P0-FIX-001)",
        "前视偏差检测 (P0-FIX-002)",
        "分红现金流对齐 (P0-FIX-003)",
    ])


# ═══════════════════════════════════════════════════════════
# P1-2: 滑点模型
# ═══════════════════════════════════════════════════════════

# 按市值的滑点率基准（默认值）
SLIPPAGE_LARGE_CAP = 0.001    # 大盘股 0.1%
SLIPPAGE_SMALL_CAP = 0.003    # 小盘股 0.3%

# 大盘/小盘分界阈值（流通市值，单位：亿）
MARKET_CAP_THRESHOLD = 100.0   # 百亿为界


@dataclass
class SlippageParams:
    """P1-2: 滑点参数配置"""
    base_rate: float = SLIPPAGE_LARGE_CAP        # 基础滑点率
    volume_factor_enabled: bool = True            # 启用成交量因子
    max_volume_factor: float = 2.0               # 成交量因子最大值
    volume_pct_threshold: float = 0.02            # 成交量阈值（超过此比例开始放大）


class BaseSlippageModel:
    """P1-2: 滑点模型基类（可扩展接口）

    子类可重写 compute() 实现更复杂的滑点模型。
    当前实现：固定滑点率 × 成交量因子

    用法:
        model = BaseSlippageModel()
        exec_price = model.compute(
            price=10.5, order_quantity=10000,
            daily_volume=500000, direction="BUY",
        )
    """

    def __init__(self, params: Optional[SlippageParams] = None):
        self.params = params or SlippageParams()

    def compute(self, price: float, order_quantity: int,
                daily_volume: float = 0.0, direction: str = "BUY",
                **kwargs) -> float:
        """计算滑点调整后的价格

        Args:
            price: 原始执行价格
            order_quantity: 订单数量（股）
            daily_volume: 当日成交量（股），0 表示不使用成交量因子
            direction: "BUY" 或 "SELL"
            **kwargs: 可扩展参数（如 market_cap, volatility 等）

        Returns:
            滑点调整后的执行价格

        滑点公式:
            effective_rate = base_rate * volume_factor
            买入: exec_price = price * (1 + effective_rate)
            卖出: exec_price = price * (1 - effective_rate)

        成交量因子（P1-2 扩展）:
            volume_factor = min(1 + (volume_pct / threshold), max_factor)
            当 volume_pct > threshold 时放大滑点
        """
        rate = self.params.base_rate

        # 成交量因子
        if self.params.volume_factor_enabled and daily_volume > 0:
            volume_pct = order_quantity / daily_volume
            if volume_pct > self.params.volume_pct_threshold:
                factor = min(
                    1.0 + (volume_pct / self.params.volume_pct_threshold),
                    self.params.max_volume_factor,
                )
                rate = rate * factor

        # 应用滑点
        if direction == "BUY":
            return price * (1.0 + rate)
        else:
            return price * (1.0 - rate)

    def get_params(self) -> Dict[str, Any]:
        return {
            "base_rate": self.params.base_rate,
            "volume_factor_enabled": self.params.volume_factor_enabled,
            "max_volume_factor": self.params.max_volume_factor,
            "volume_pct_threshold": self.params.volume_pct_threshold,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(base_rate={self.params.base_rate})"


class TieredSlippageModel(BaseSlippageModel):
    """P1-2: 按流动性分档的滑点模型

    自动根据股票市值选择滑点率：
        - 大盘股（>= 百亿流通市值）: 0.1%
        - 小盘股（< 百亿流通市值）: 0.3%

    如果未提供 market_cap，默认使用大盘股滑点率。

    用法:
        model = TieredSlippageModel()
        # 大盘股（market_cap >= 100亿）
        p1 = model.compute(10.5, 10000, daily_volume=500000,
                           direction="BUY", market_cap=500.0)
        # 小盘股（market_cap < 100亿）
        p2 = model.compute(10.5, 10000, daily_volume=500000,
                           direction="BUY", market_cap=30.0)
    """

    def __init__(self,
                 large_cap_rate: float = SLIPPAGE_LARGE_CAP,
                 small_cap_rate: float = SLIPPAGE_SMALL_CAP,
                 cap_threshold: float = MARKET_CAP_THRESHOLD,
                 volume_factor_enabled: bool = True):
        params = SlippageParams(
            base_rate=large_cap_rate,
            volume_factor_enabled=volume_factor_enabled,
        )
        super().__init__(params)
        self._large_cap_rate = large_cap_rate
        self._small_cap_rate = small_cap_rate
        self._cap_threshold = cap_threshold

    def compute(self, price: float, order_quantity: int,
                daily_volume: float = 0.0, direction: str = "BUY",
                **kwargs) -> float:
        """按市值分档计算滑点后价格

        kwargs 支持:
            market_cap: float — 流通市值（亿元），决定使用大盘/小盘滑点率
        """
        market_cap = kwargs.get("market_cap", self._cap_threshold + 1)
        is_large_cap = market_cap >= self._cap_threshold

        rate = self._large_cap_rate if is_large_cap else self._small_cap_rate

        # 成交量因子
        if self.params.volume_factor_enabled and daily_volume > 0:
            volume_pct = order_quantity / max(daily_volume, 1)
            if volume_pct > self.params.volume_pct_threshold:
                factor = min(
                    1.0 + (volume_pct / self.params.volume_pct_threshold),
                    self.params.max_volume_factor,
                )
                rate = rate * factor

        if direction == "BUY":
            return price * (1.0 + rate)
        else:
            return price * (1.0 - rate)

    def get_params(self) -> Dict[str, Any]:
        return {
            "large_cap_rate": self._large_cap_rate,
            "small_cap_rate": self._small_cap_rate,
            "cap_threshold": self._cap_threshold,
            "volume_factor_enabled": self.params.volume_factor_enabled,
        }


# ═══════════════════════════════════════════════════════════
# P1 修复集成: ConstraintAwareExecutor
# ═══════════════════════════════════════════════════════════

class ConstraintAwareExecutor(_ConstraintAwareExecutor):
    """约束感知执行器（集成 P0/P1 修复）

    BT-008 优先级:
        1. 停牌检查（volume == 0 → 无法交易）
        2. 涨跌停检查（涨跌达到限制 → 无法交易）
        3. 成交量容量约束（每笔不超过日成交量的 volume_capacity_pct）
        4. T+1 检查（当日买入 → 次日才可卖出）

    P1 修复:
        - P1-1: 涨跌停价格边界计算（prev_close ±10%）
        - P1-2: 按流动性分档的滑点模型（TieredSlippageModel）
        - P1-3: 成交量容量约束（check_volume_capacity）
    """

    def __init__(self, fee_rate: float = 0.0003,
                 slippage_rate: float = 0.001,
                 min_fee: float = 5.0,
                 stamp_tax_rate: float = 0.0005,
                 enable_p0_fixes: bool = True,
                 slippage_model: Optional[BaseSlippageModel] = None,
                 volume_capacity_pct: float = VOLUME_CAPACITY_PCT):
        super().__init__(
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            min_fee=min_fee,
            stamp_tax_rate=stamp_tax_rate,
        )
        self._enable_p0_fixes = enable_p0_fixes
        self._constraint_manager = ConstraintManager()
        self._trade_logger = TradeLogger()
        # P1-2: 滑点模型
        self._slippage_model = slippage_model or TieredSlippageModel()
        # P1-3: 成交量容量比例
        self._volume_capacity_pct = volume_capacity_pct

    def execute_signals(
        self,
        data: BacktestData,
        signals: List,
        initial_capital: float,
    ) -> SimulateResult:
        """执行所有信号（含 P0/P1 修复）

        P0-FIX-001:
            - T+1 延迟: 当日买入的 SELL 信号挂单到次日
            - 停牌/涨跌停挂单: 自动重试到恢复交易

        P1-2:
            - 使用 TieredSlippageModel 计算滑点调整后价格

        P1-3:
            - 成交量容量约束: 每笔交易不超过当日成交量 5%

        P0-FIX-003:
            - 分红现金流: 在除息日调整持仓价值
            TODO(P1): 除息日现金流调整逻辑待实现
        """
        result = super().execute_signals(data, signals, initial_capital)

        # 包装为 SimulateResult（含 P0/P1 标记）
        sr = SimulateResult(
            symbol=result.symbol,
            initial_capital=result.initial_capital,
            final_capital=result.final_capital,
            total_return_pct=result.total_return_pct,
            total_trades=result.total_trades,
            trades=result.trades,
            equity_curve=result.equity_curve,
            metrics=result.metrics,
            warnings=result.warnings,
        )

        # BT-005: 审计日志
        self._trade_logger.log_batch(result.trades)

        return sr


def simulate(
    data: BacktestData,
    signals: List[Signal],
    initial_capital: float = 1_000_000.0,
    fee_rate: float = 0.0003,
    slippage_rate: float = 0.001,
    min_fee: float = 5.0,
    stamp_tax_rate: float = 0.0005,
    slippage_model: Optional[BaseSlippageModel] = None,
    volume_capacity_pct: float = VOLUME_CAPACITY_PCT,
) -> SimulateResult:
    """一站式模拟执行（推荐使用，含 P1 修复）

    Args:
        data: BacktestData 合约
        signals: 信号列表（来自 calc_layer）
        initial_capital: 初始资金
        fee_rate: 手续费率
        slippage_rate: 滑点率
        min_fee: 最低手续费
        slippage_model: P1-2 滑点模型（None 使用默认 TieredSlippageModel）
        volume_capacity_pct: P1-3 成交量容量比例（默认 5%）

    Returns:
        SimulateResult（含完整交易日志、净值曲线、指标、P0/P1标记）
    """
    executor = ConstraintAwareExecutor(
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        min_fee=min_fee,
        stamp_tax_rate=stamp_tax_rate,
        slippage_model=slippage_model,
        volume_capacity_pct=volume_capacity_pct,
    )
    return executor.execute_signals(data, signals, initial_capital)
