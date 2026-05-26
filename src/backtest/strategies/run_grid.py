"""
墨枢 - P4-11 网格回测运行器

集成管线：数据加载 → GridStrategy 网格信号 → GridPositionManager 仓位管理
        → BacktestEngine 执行 → 结果持久化 → 批量并行。

用法::

    from backtest.strategies.run_grid import (
        run_grid_backtest, GridRunnerConfig, batch_run_grid,
        GridSignalProvider,
    )
    from backtest.strategies.grid_strategy import (
        StaticGridSignal, GridConfig,
    )
    from backtest.strategies.grid_position import (
        GridPositionManager, GridFixedPosition, GridCoolDown, GridStopLoss,
    )

    signal = StaticGridSignal(
        grid_config=GridConfig(lower_bound=95, upper_bound=105, n_levels=10)
    )
    position = GridPositionManager(
        position_logic=GridFixedPosition(quantity=200),
        cool_down=GridCoolDown(cool_down_bars=3),
    )
    cfg = GridRunnerConfig(
        symbol="000001.SZ",
        signal=signal,
        position=position,
    )
    result = run_grid_backtest(cfg)
    print(result.metrics)

Author: 墨衡
Created: 2026-05-15
"""

from __future__ import annotations

import abc
import csv
import json
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# 新版统一运行器
from backtest.runners.method_backtest_runner import MethodBacktestRunner
from backtest.context import StrategyContext
from backtest.methods.base import MethodResult

# 时区
_TZ_CN = timezone(timedelta(hours=8))

from src.signals.signal_protocol_v1 import Signal
from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Bar,
    Strategy,
)
from backtest.signal_bridge import SignalBridge, SignalBridgeConfig
from backtest.benchmark_data_source import calc_buy_hold_return
from backtest.data_loader import load_stock_bars

# 网格策略信号
from backtest.strategies.grid_strategy import (
    GridStrategy,
    StaticGridSignal,
    DynamicGridSignal,
    GridBreakoutSignal,
    GridReversalSignal,
    GridVotingSignal,
)

# 网格仓位管理
from backtest.strategies.grid_position import (
    GridPositionManager,
    create_grid_position,
    create_grid_risk,
    create_grid_manager,
    GridFixedPosition,
    GridLayerPosition,
    GridBatcherPosition,
    GridCoolDown,
    GridStopLoss,
    GridMaxExposure,
)

from backtest.pipeline.knowledge_db import KnowledgeDB

# ═══════════════════════════════════════════════════════════════
# 结果目录
# ═══════════════════════════════════════════════════════════════

_RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "backtest_results"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ═══════════════════════════════════════════════════════════════
# P4-11: GridSignalProvider — 将 GridStrategy 封装为信号提供者
# ═══════════════════════════════════════════════════════════════


class SignalProvider(abc.ABC):
    """
    信号提供者抽象基类。
    定义统一的 compute_signal 接口，供 SignalBridge 信号管线消费。
    """

    @abc.abstractmethod
    def compute_signal(
        self, context: Any, bar: Bar
    ) -> Dict[str, Any]:
        """
        计算当前 Bar 的信号，返回字典格式。

        返回 Dict 至少包含:
          - "signal": float (1.0 买入, -1.0 卖出, 0.0 无操作)
          - "quantity": int (建议股数)
        """
        ...


class GridSignalProvider(SignalProvider):
    """
    将 GridStrategy 信号封装为 SignalProvider 接口（P4-11）。

    通过调用 grid_strategy.on_bar() 获取 Signal 列表，
    将其转换为统一的 dict 信号格式，兼容 SignalBridge 信号管线。

    参数
    ----------
    grid_strategy : GridStrategy
        任意 GridStrategy 子类实例（StaticGridSignal / DynamicGridSignal /
        GridVotingSignal 等）。
    """

    def __init__(self, grid_strategy: GridStrategy):
        if not isinstance(grid_strategy, GridStrategy):
            raise TypeError(
                f"grid_strategy 须为 GridStrategy 子类，收到 {type(grid_strategy)}"
            )
        self._grid_strategy = grid_strategy
        self._last_signals: Optional[List[Signal]] = None

    @property
    def grid_strategy(self) -> GridStrategy:
        return self._grid_strategy

    def compute_signal(
        self, context: Any, bar: Bar
    ) -> Dict[str, Any]:
        """
        调用 grid_strategy.on_bar() 获取网格信号（ProtocolSignal），转换为统一 Dict 格式。

        返回 Dict:
          {
              "signal": float,   # 1.0=买入, -1.0=卖出, 0.0=无操作
              "quantity": int,   # 建议下单股数
              "strength": float, # 信号强度 (0.0~1.0)
              "detail": dict,    # 原始事件详情（网格级别等）
          }
        """
        signals = self._grid_strategy.on_bar(context, bar)
        self._last_signals = signals

        result: Dict[str, Any] = {
            "signal": 0.0,
            "quantity": 0,
            "strength": 0.0,
            "detail": {},
        }

        if not signals:
            return result

        buy_qty = sum(
            sig.extras.get("quantity", 0) for sig in signals if sig.direction == "BUY"
        )
        sell_qty = sum(
            sig.extras.get("quantity", 0) for sig in signals if sig.direction == "SELL"
        )

        if buy_qty > 0 and sell_qty == 0:
            result["signal"] = 1.0
            result["quantity"] = buy_qty
            result["strength"] = 1.0
        elif sell_qty > 0 and buy_qty == 0:
            result["signal"] = -1.0
            result["quantity"] = sell_qty
            result["strength"] = 1.0

        # 尝试从 GridVotingSignal 获取投票强度
        if hasattr(self._grid_strategy, "latest_vote_detail"):
            vote_detail = getattr(
                self._grid_strategy, "latest_vote_detail", {}
            )
            if vote_detail:
                ns = vote_detail.get("net_strength", 0.0)
                result["strength"] = abs(ns)
                result["detail"] = vote_detail

        return result

    @property
    def last_signals(self) -> Optional[List[Signal]]:
        """最近一次 on_bar 返回的原始信号列表。"""
        return self._last_signals

    def reset(self) -> None:
        """复位状态。"""
        self._last_signals = None


# ═══════════════════════════════════════════════════════════════
# P4-11: GridRunnerConfig & GridRunnerResult
# ═══════════════════════════════════════════════════════════════


@dataclass
class GridRunnerConfig:
    """
    网格回测运行配置（P4-11）。

    参数说明
    ----------
    symbol : str
        股票代码，如 "000001.SZ"。
    start_date / end_date : str
        日期范围（YYYYMMDD 格式，留空表示全部数据）。
    signal : GridStrategy 子类
        网格策略实例，可以是 StaticGridSignal / DynamicGridSignal /
        GridBreakoutSignal / GridReversalSignal / GridVotingSignal。
    position : GridPositionManager
        网格仓位管理器（组合仓位计算 + 风控）。
    signal_bridge : SignalBridge, optional
        信号桥接实例。如不提供，自动创建默认实例。
    initial_capital : float
        初始资金。
    fee_rate : float
        手续费率。
    slippage_rate : float
        滑点率。
    db_path : str or None
        数据库路径（None 使用默认路径）。
    tag : str or None
        回测标签，用于结果文件名标识。
    """

    symbol: str = "000001.SZ"
    start_date: str = ""
    end_date: str = ""
    signal: Union[
        GridVotingSignal,
        StaticGridSignal,
        DynamicGridSignal,
        GridBreakoutSignal,
        GridReversalSignal,
    ] = None  # type: ignore[assignment]
    position: GridPositionManager = None  # type: ignore[assignment]
    signal_bridge: Optional[SignalBridge] = None
    initial_capital: float = 1_000_000.0
    fee_rate: float = 0.0003
    slippage_rate: float = 0.001
    db_path: Optional[str] = None
    tag: str = "default"

    def __post_init__(self):
        if self.signal is None:
            # 默认：StaticGridSignal 等距 10 级网格
            from backtest.strategies.grid_strategy import (
                StaticGridSignal, GridConfig,
            )

            self.signal = StaticGridSignal(
                grid_config=GridConfig(
                    lower_bound=95.0,
                    upper_bound=105.0,
                    n_levels=10,
                    grid_type="arithmetic",
                )
            )

        if self.position is None:
            # 默认：固定仓位 100 股 + 3Bar 冷却
            self.position = GridPositionManager(
                position_logic=GridFixedPosition(quantity=100),
                cool_down=GridCoolDown(cool_down_bars=3),
            )

    def to_params_dict(self) -> Dict[str, Any]:
        """
        将回测配置导出为统一参数字典（P4-11 跨系统对接）。

        返回统一结构（包含 signal/position/meta 子字典），
        字段不可用时自动降级填充，通过 meta.has_full_params 标记完整性。

        Returns
        -------
        Dict[str, Any]
            {
                "capital": float,
                "fee_rate": float,
                "slippage": float,
                "signal": {
                    "n_layers": int,
                    "step_pct": float,
                    "grid_type": str,
                },
                "position": {
                    "position_sizing": str,
                    "max_positions": int,
                    "stop_loss_pct": float,
                },
                "meta": {"has_full_params": bool},
            }
        """
        result: Dict[str, Any] = {
            "capital": self.initial_capital,
            "fee_rate": self.fee_rate,
            "slippage": self.slippage_rate,
            "signal": {},
            "position": {},
            "meta": {},
        }

        missing_keys: List[str] = []

        # ═══════════════════════════════════════════════════
        # 1. 信号参数（signal）
        # ═══════════════════════════════════════════════════
        if self.signal is not None and hasattr(self.signal, "params"):
            sig = self.signal.params  # type: ignore[union-attr]

            # n_layers ← n_levels
            n_levels = sig.get("n_levels")
            if n_levels is not None and isinstance(n_levels, (int, float)) and n_levels >= 2:
                result["signal"]["n_layers"] = int(n_levels)
            else:
                missing_keys.append("signal.n_layers")
                result["signal"]["n_layers"] = 10

            # grid_type
            raw_type = sig.get("grid_type", "arithmetic")
            result["signal"]["grid_type"] = raw_type if raw_type in ("arithmetic", "geometric") else "arithmetic"

            # step_pct — 从价差推导网格步进百分比
            lower = sig.get("lower_bound")
            upper = sig.get("upper_bound")
            n = result["signal"]["n_layers"]
            if all(x is not None and x > 0 for x in (lower, upper)) and n > 1:
                if result["signal"]["grid_type"] == "geometric":
                    ratio = (float(upper) / float(lower)) ** (1.0 / (n - 1))
                    step_pct = ratio - 1.0
                else:
                    gap = (float(upper) - float(lower)) / (n - 1)
                    step_pct = gap / float(lower)
                result["signal"]["step_pct"] = round(step_pct, 6)
            else:
                missing_keys.append("signal.step_pct")
                result["signal"]["step_pct"] = 0.01
        else:
            missing_keys.extend(["signal.n_layers", "signal.step_pct", "signal.grid_type"])
            result["signal"] = {"n_layers": 10, "step_pct": 0.01, "grid_type": "arithmetic"}

        # ═══════════════════════════════════════════════════
        # 2. 仓位参数（position）
        # ═══════════════════════════════════════════════════
        if self.position is not None and hasattr(self.position, "params"):
            pos = self.position.params  # type: ignore[union-attr]

            # position_sizing ← mode
            pos_logic = pos.get("position_logic", {}) or {}
            mode = pos_logic.get("mode", "")
            if not mode:
                # 降级：从类名推导
                if hasattr(self.position, "position_logic"):
                    _cls_name = type(self.position.position_logic).__name__
                else:
                    _cls_name = ""
                _mode_map = {
                    "GridFixedPosition": "fixed",
                    "GridLayerPosition": "layer",
                    "GridBatcherPosition": "batcher",
                }
                mode = _mode_map.get(_cls_name, "fixed")
            result["position"]["position_sizing"] = mode

            # max_positions ← exposure.max_grids_active
            exposure_cfg = pos.get("exposure", {}) or {}
            max_pos = exposure_cfg.get("max_grids_active")
            if max_pos is not None and isinstance(max_pos, (int, float)):
                result["position"]["max_positions"] = int(max_pos)
            else:
                missing_keys.append("position.max_positions")
                result["position"]["max_positions"] = 3

            # stop_loss_pct ← stop_loss.stop_loss_pct
            sl_cfg = pos.get("stop_loss", {}) or {}
            sl_pct = sl_cfg.get("stop_loss_pct")
            if sl_pct is not None:
                result["position"]["stop_loss_pct"] = float(sl_pct)
            else:
                result["position"]["stop_loss_pct"] = 0.0
                if "position.max_positions" not in missing_keys:
                    missing_keys.append("position.stop_loss_pct")
        else:
            missing_keys.extend(["position.position_sizing", "position.max_positions", "position.stop_loss_pct"])
            result["position"] = {
                "position_sizing": "fixed",
                "max_positions": 3,
                "stop_loss_pct": 0.0,
            }

        # ═══════════════════════════════════════════════════
        # 3. Meta：完整性标记
        # ═══════════════════════════════════════════════════
        result["meta"] = {"has_full_params": len(missing_keys) == 0}

        return result


@dataclass
class GridRunnerResult:
    """
    网格回测运行结果（P4-11）。

    属性
    ----------
    symbol : str
        股票代码。
    config_key : str
        配置标识（用于区分参数组合，如 "static_n10_fixed_cd3"）。
    backtest_result : BacktestResult or None
        回测引擎返回的完整结果（失败时为 None）。
    metrics : dict
        提取的绩效摘要。
    status : str
        "SUCCESS" 或 "FAILED"。
    error : str or None
        失败时的错误信息。
    """

    symbol: str
    config_key: str
    backtest_result: Optional[BacktestResult]
    metrics: Dict[str, Any]
    status: str
    error: Optional[str] = None

    def __post_init__(self):
        if self.metrics is None:
            self.metrics = {}

    @classmethod
    def from_backtest_result(
        cls,
        symbol: str,
        config_key: str,
        result: BacktestResult,
    ) -> "GridRunnerResult":
        """从成功的 BacktestResult 构建。"""
        return cls(
            symbol=symbol,
            config_key=config_key,
            backtest_result=result,
            metrics=dict(result.metrics),
            status="SUCCESS",
        )

    @classmethod
    def from_error(
        cls,
        symbol: str,
        config_key: str,
        error: str,
    ) -> "GridRunnerResult":
        """从失败信息构建。"""
        return cls(
            symbol=symbol,
            config_key=config_key,
            backtest_result=None,
            metrics={},
            status="FAILED",
            error=error,
        )


# ═══════════════════════════════════════════════════════════════
# P4-11: 内部策略 — 整合 GridStrategy + GridPositionManager
# ═══════════════════════════════════════════════════════════════


class _GridRunnerStrategy(Strategy):
    """
    网格回测运行器专用内部策略。

    职责：
      1. 通过 GridSignalProvider 获取网格信号
      2. 通过 GridPositionManager 管理仓位和风控（冷却、止损、敞口）
      3. 输出 Signal 给下游引擎
    """

    def __init__(
        self,
        provider: GridSignalProvider,
        pos_manager: GridPositionManager,
    ):
        super().__init__()
        self._provider = provider
        self._pos_manager = pos_manager

        # 运行时状态
        self._bar_index: int = -1
        self._entry_price: Optional[float] = None
        self._has_position: bool = False
        self._active_grid_ids: List[str] = []

    def on_start(self, context: Any) -> None:
        """回测开始时复位状态。"""
        self._bar_index = -1
        self._entry_price = None
        self._has_position = False
        self._active_grid_ids = []
        self._provider.reset()
        self._pos_manager.reset()

    def on_bar(
        self, context: Any, bar: Bar
    ) -> Optional[List[Signal]]:
        self._bar_index += 1

        # ── 1. 获取网格信号 ──────────────────────────────
        signal_dict = self._provider.compute_signal(context, bar)
        signal_val = signal_dict.get("signal", 0.0)

        # ── 2. 检查当前持仓 ──────────────────────────────
        pos = (
            context.positions.get(bar.symbol)
            if context.positions.has_position(bar.symbol)
            else None
        )
        self._has_position = pos is not None and not pos.is_empty

        def _mk_signal(direction: str, qty: int) -> Signal:
            return Signal(
                signal_id=str(uuid.uuid4()),
                symbol=bar.symbol,
                direction=direction,
                confidence=1.0,
                horizon="short",
                signal_type="grid",
                timestamp=datetime.now(_TZ_CN),
                protocol_version="1.0",
                extras={"quantity": qty},
            )

        signals: List[Signal] = []

        # ── 3. 止损检查 ──────────────────────────────────
        if self._has_position and self._entry_price is not None:
            should_stop = self._pos_manager.check_stop_loss(
                context, bar, self._entry_price
            )
            if should_stop:
                # 市价全部卖出
                sell_qty = self._pos_manager.on_sell_signal(context, bar)
                if sell_qty > 0:
                    signals.append(_mk_signal("SELL", sell_qty))
                    # 复位状态
                    self._close_position()
                    return signals

        # ── 4. 检查敞口超限 ────────────────────────────
        if self._pos_manager.check_exposure_breach(context):
            # 超限时减仓一半
            if self._has_position and pos is not None:
                reduce_qty = (pos.quantity // 200) * 100
                if reduce_qty >= 100:
                    signals.append(_mk_signal("SELL", reduce_qty))
                    return signals

        # ── 5. 信号处理 ──────────────────────────────────
        if signal_val > 0:  # BUY
            # 开仓前检查风控
            can_open = self._pos_manager.can_open(
                context, bar,
                grid_line_id=None,  # 由具体信号来源决定
                current_active_grids=len(self._active_grid_ids),
                current_bar=self._bar_index,
            )
            if can_open and not self._has_position:
                qty = self._pos_manager.on_buy_signal(
                    context, bar,
                    triggered_levels=self._active_grid_ids,
                    grid_position=self._calc_grid_position(bar),
                )
                if qty > 0:
                    signals.append(_mk_signal("BUY", qty))
                    self._open_position(bar.close)

        elif signal_val < 0:  # SELL
            if self._has_position:
                qty = self._pos_manager.on_sell_signal(context, bar)
                if qty > 0:
                    signals.append(_mk_signal("SELL", qty))
                    self._close_position()

        return signals if signals else None

    # ── 辅助方法 ──────────────────────────────────────────

    def _open_position(self, price: float) -> None:
        """记录开仓状态。"""
        self._entry_price = price
        self._has_position = True
        grid_id = f"grid_bar_{self._bar_index}"
        self._active_grid_ids.append(grid_id)
        # BUGFIX: 2026-05-16: prevent cooldown/stop-loss reset on open
        # self._pos_manager.reset()  # removed — resets cooldown counter & stop-loss tracking

    def _close_position(self) -> None:
        """复位持仓状态。"""
        self._entry_price = None
        self._has_position = False
        self._active_grid_ids.clear()
        self._pos_manager.reset()

    def _calc_grid_position(self, bar: Bar) -> float:
        """
        计算当前价格在网格中的归一化位置 [0.0, 1.0]。
        """
        strategy = self._provider.grid_strategy
        levels = strategy.grid_levels
        if not levels:
            return 0.5

        lower = levels[0].price
        upper = levels[-1].price
        if upper <= lower:
            return 0.5

        pos = (bar.close - lower) / (upper - lower)
        return max(0.0, min(1.0, pos))


# ═══════════════════════════════════════════════════════════════
# 辅助函数：Bars → DataFrame 转换
# ═══════════════════════════════════════════════════════════════


def _bars_to_dataframe(bars: List[Bar]) -> "pd.DataFrame":
    """将 List[Bar] 转换为 MethodBacktestRunner 可用的 OHLCV DataFrame。"""
    import pandas as _pd

    records = []
    for b in bars:
        records.append({
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "vwap": b.vwap,
        })
    df = _pd.DataFrame(records, index=_pd.to_datetime([str(b.date) for b in bars]))
    df.index.name = "date"
    return df


# ═══════════════════════════════════════════════════════════════
# run_new — 新版调用（MethodBacktestRunner 包装）
# ═══════════════════════════════════════════════════════════════


def run_new(
    symbol: str = "000001.SZ",
    config: Optional[Dict[str, Any]] = None,
) -> MethodResult:
    """新版调用 — 通过 MethodBacktestRunner 运行网格信号方法。

    使用新 MethodBacktestRunner 替代旧 BacktestEngine 管线。
    保留旧 run_grid_backtest() 不变（下兼容）。

    参数
    ----------
    symbol : str
        股票代码。
    config : dict, optional
        配置字典，可包含:
          - method_name: 方法标识 ("grid", 默认 "grid")
          - start_date / end_date: 日期范围
          - db_path: 数据库路径
          - 以及其他网格方法参数

    返回
    -------
    MethodResult
    """
    if config is None:
        config = {}

    cfg = dict(config)  # 不修改原始入参
    method_name = cfg.pop("method_name", "grid")
    start_date = cfg.pop("start_date", "")
    end_date = cfg.pop("end_date", "")
    db_path = cfg.pop("db_path", None)

    print(f"[run_grid.run_new] symbol={symbol}, method={method_name}")

    # 1. 加载数据（复用原有 load_stock_bars）
    bars = load_stock_bars(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        db_path=db_path,
    )
    df = _bars_to_dataframe(bars)
    print(f"[run_grid.run_new] 数据加载完成: {bars[0].date} ~ {bars[-1].date}, {len(bars)} 条")

    # 2. 创建 StrategyContext
    ctx = StrategyContext(
        symbol=symbol,
        method_name=method_name,
        config=cfg,
    )

    # 3. 运行 MethodBacktestRunner
    runner = MethodBacktestRunner(method_name=method_name, ctx=ctx)
    return runner.run(df, symbol=symbol)


# ═══════════════════════════════════════════════════════════════
# P4-11: 主运行函数
# ═══════════════════════════════════════════════════════════════

# DEPRECATED: 将在 Phase 5 结束后移除
def _build_config_key(
    signal: GridStrategy,
    position: GridPositionManager,
) -> str:
    """从信号和仓位管理器生成可读配置标识。"""
    parts: List[str] = []

    # 信号类型
    signal_type = signal.__class__.__name__
    if signal_type == "StaticGridSignal":
        p = signal.params
        parts.append(f"static_n{p.get('n_levels', 10)}_{p.get('grid_type', 'arithmetic')}")
    elif signal_type == "DynamicGridSignal":
        p = signal.params
        parts.append(f"dynamic_lb{p.get('lookback', 20)}_n{p.get('n_levels', 10)}")
    elif signal_type == "GridVotingSignal":
        p = signal.params
        parts.append(f"vote_th{p.get('vote_threshold', 0.5)}_n{p.get('n_sub_grids', 3)}")
    elif signal_type == "GridBreakoutSignal":
        p = signal.params
        parts.append(f"breakout_c{p.get('confirmation_bars', 1)}")
    elif signal_type == "GridReversalSignal":
        p = signal.params
        parts.append(f"reversal_c{p.get('confirmation_bars', 1)}")
    else:
        parts.append(signal_type)

    # 仓位模式
    pos_params = position.params
    pos_logic = pos_params.get("position_logic", {})
    pos_mode = pos_logic.get("mode", "unknown").replace("grid_", "")
    parts.append(pos_mode)

    # 冷却期（如有）
    cd = pos_params.get("cool_down")
    if cd:
        parts.append(f"cd{cd.get('cool_down_bars', 0)}")

    # 止损（如有）
    sl = pos_params.get("stop_loss")
    if sl:
        sl_pct = sl.get("stop_loss_pct", 0)
        parts.append(f"sl{sl_pct:.0%}".replace("%", "pct"))

    return "_".join(parts)


def _compute_runtime_signature(
    signal: GridStrategy, result: BacktestResult,
) -> Dict[str, Any]:
    """
    从回测结果中提取运行时特征摘要。
    """
    return {
        "strategy_type": signal.__class__.__name__,
        "grid_params": signal.params,
        "total_trades": result.total_trades,
        "total_bars": result.total_bars,
    }


def run_grid_backtest(
    config: Optional[GridRunnerConfig] = None,
) -> GridRunnerResult:
    """
    网格回测主入口（P4-11）。

    流程：
      1. 加载指定标的数据
      2. 创建 GridSignalProvider
      3. 创建内部策略 _GridRunnerStrategy
      4. 配置并运行 BacktestEngine
      5. 持久化结果
      6. 返回 GridRunnerResult

    参数
    ----------
    config : GridRunnerConfig, optional
        回测配置。默认使用 StaticGridSignal 等距 10 级网格 + 固定 100 股。

    返回
    -------
    GridRunnerResult

    用法::

        # 默认运行
        result = run_grid_backtest()

        # 自定义：投票信号 + 层数仓位 + 5%止损
        from backtest.strategies.grid_strategy import (
            StaticGridSignal, DynamicGridSignal,
            GridBreakoutSignal, GridVotingSignal, GridConfig,
        )
        from backtest.strategies.grid_position import (
            GridPositionManager, GridLayerPosition, GridStopLoss,
        )

        grid1 = StaticGridSignal(grid_config=GridConfig(95, 105, 10))
        grid2 = DynamicGridSignal(lookback=20, n_levels=10)
        voter = GridVotingSignal(sub_grids=[grid1, grid2], vote_threshold=0.5)

        pos = GridPositionManager(
            position_logic=GridLayerPosition(base_quantity=100),
            stop_loss=GridStopLoss(stop_loss_pct=0.05),
        )

        cfg = GridRunnerConfig(
            symbol="000001.SZ",
            signal=voter,
            position=pos,
            tag="vote_layer_sl5",
        )
        result = run_grid_backtest(cfg)
        print(f"夏普: {result.metrics.get('sharpe_ratio', 'N/A')}")
    """
    if config is None:
        config = GridRunnerConfig()

    config_key = _build_config_key(config.signal, config.position)

    try:
        # ── 1. 加载数据 ──────────────────────────────────
        bars = load_stock_bars(
            symbol=config.symbol,
            start_date=config.start_date,
            end_date=config.end_date,
            db_path=config.db_path,
        )
        print(
            f"[run_grid] 数据加载完成: {config.symbol}, "
            f"{bars[0].date} ~ {bars[-1].date}, {len(bars)} 条"
        )

        # ── 2. 创建信号提供者 ────────────────────────────
        provider = GridSignalProvider(grid_strategy=config.signal)

        # ── 3. 创建内部策略 ──────────────────────────────
        strategy = _GridRunnerStrategy(
            provider=provider,
            pos_manager=config.position,
        )

        # ── 4. 配置并运行引擎 ──────────────────────────────
        engine_start = config.start_date or bars[0].date
        engine_end = config.end_date or bars[-1].date

        engine_config = BacktestConfig(
            start_date=engine_start,
            end_date=engine_end,
            initial_capital=config.initial_capital,
            fee_rate=config.fee_rate,
            slippage_rate=config.slippage_rate,
            min_fee=5.0,
            snapshot_enabled=True,
        )

        engine = BacktestEngine(config=engine_config, strategy=strategy)
        bt_result = engine.run(bars)

        ann_ret = bt_result.metrics.get("annual_return_pct", None)
        ann_str = f"{ann_ret:.2%}" if ann_ret is not None else "N/A"
        print(
            f"[run_grid] 回测完成: "
            f"交易次数={bt_result.total_trades}, "
            f"年化收益={ann_str}, "
            f"夏普={bt_result.metrics.get('sharpe_ratio', 'N/A')}"
        )

        # ── 5. 基准计算（买入持有）──────────────────────
        try:
            # 从 symbol 中提取纯代码部分（如 "000001.SZ" → "000001"）
            raw_symbol = config.symbol.split(".")[0] if "." in config.symbol else config.symbol
            bh_start = config.start_date or bars[0].date.replace("-", "")
            bh_end = config.end_date or bars[-1].date.replace("-", "")
            bt_result.buy_hold_kpi = calc_buy_hold_return(
                symbol=raw_symbol,
                name=config.symbol,
                start_date=bh_start,
                end_date=bh_end,
            )
        except Exception as bh_e:
            print(f"[run_grid] 买入持有基准计算失败（不影响回测）: {bh_e}")
            bt_result.buy_hold_kpi = None

        # ── 6. 构建结果 ──────────────────────────────────
        result = GridRunnerResult.from_backtest_result(
            symbol=config.symbol,
            config_key=config_key,
            result=bt_result,
        )

        # ── 6. 持久化结果 ──────────────────────────────
        _persist_result(bt_result, config, config_key)

        return result

    except Exception as e:
        print(f"[run_grid] 回测失败 [{config_key}]: {e}")
        return GridRunnerResult.from_error(
            symbol=config.symbol,
            config_key=config_key,
            error=str(e),
        )


# ═══════════════════════════════════════════════════════════════
# P4-11: 批量运行（并行）
# ═══════════════════════════════════════════════════════════════

# DEPRECATED: 将在 Phase 5 结束后移除
def batch_run_grid(
    configs: List[GridRunnerConfig],
    max_workers: int = 4,
) -> List[GridRunnerResult]:
    """
    并发批量运行多个网格回测配置（P4-11）。

    错误隔离：单个配置失败不影响其余运行，失败项 status="FAILED"。

    参数
    ----------
    configs : List[GridRunnerConfig]
        回测配置列表。
    max_workers : int
        最大并发数，默认 4。

    返回
    -------
    List[GridRunnerResult]
        结果列表（顺序与 configs 对应）。
    """
    n = len(configs)
    results: List[GridRunnerResult] = [None] * n  # type: ignore[list-item]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_grid_backtest, cfg): i
            for i, cfg in enumerate(configs)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                result = future.result()
                results[idx] = result
                status = result.status
                key = result.config_key
                print(
                    f"[batch:grid] [{idx+1}/{n}] {key} → {status}"
                )
            except Exception as e:
                key = "unknown"
                if configs[idx]:
                    key = _build_config_key(
                        configs[idx].signal, configs[idx].position
                    )
                print(
                    f"[batch:grid] [{idx+1}/{n}] {key} → FAILED: {e}"
                )
                results[idx] = GridRunnerResult.from_error(
                    symbol=configs[idx].symbol if configs[idx] else "unknown",
                    config_key=key,
                    error=str(e),
                )

    return results


# ═══════════════════════════════════════════════════════════════
# 结果持久化
# ═══════════════════════════════════════════════════════════════


def _persist_result(
    result: BacktestResult,
    config: GridRunnerConfig,
    config_key: str,
) -> str:
    """
    将回测结果写入 backtest_results/ 目录。

    文件名格式: grid_{symbol}_{config_key}_{tag}_{date}_{time}.json

    返回保存的文件路径。
    """
    output_dir = os.environ.get("BACKTEST_RESULTS_DIR", _RESULTS_DIR)
    os.makedirs(output_dir, exist_ok=True)

    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    filename = (
        f"grid_{config.symbol}_"
        f"{config_key}_"
        f"{config.tag}_"
        f"{date_part}_{time_part}.json"
    )
    filepath = os.path.join(output_dir, filename)

    payload = {
        "meta": {
            "symbol": config.symbol,
            "signal_type": config.signal.__class__.__name__,
            "signal_params": config.signal.params,
            "position_params": config.position.params,
            "initial_capital": config.initial_capital,
            "fee_rate": config.fee_rate,
            "slippage_rate": config.slippage_rate,
            "tag": config.tag,
            "config_key": config_key,
            "timestamp": f"{date_part}_{time_part}",
        },
        "result": result.to_dict(),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    print(f"[run_grid] 结果已保存: {filepath}")

    # 知识库写入（不阻塞，异常不影响主流程）
    try:
        metrics = result.metrics
        with KnowledgeDB() as kdb:
            run_id = kdb.store_run(
                strategy="grid",
                symbol=config.symbol,
                config_key=config_key,
                strategy_tag=config.tag,
                start_date=str(config.start_date),
                end_date=str(config.end_date),
                data_days=getattr(result, "total_bars", 0),
                param_version=getattr(config, "param_version", "v0_initial"),
                run_by="auto",
                triggered_by="manual",
                report_path=os.path.relpath(filepath, PROJECT_ROOT),
                params_json=config.to_params_dict() if hasattr(config, "to_params_dict") else None,
                metrics={
                    "total_return_pct": metrics.get("total_return_pct", 0.0),
                    "annual_return_pct": metrics.get("annual_return_pct", 0.0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct", 0.0),
                    "win_rate_pct": metrics.get("win_rate_pct", 0.0),
                    "total_trades": getattr(result, "total_trades", 0),
                    "avg_holding_bars": metrics.get("avg_holding_bars", 0),
                    # BUGFIX: 2026-05-16: double-key tolerance for profit_factor/profit_loss_ratio
                    "profit_factor": metrics.get("profit_factor") if "profit_factor" in metrics else metrics.get("profit_loss_ratio", 0.0),
                },
            )
            # 写入净值曲线和交易明细
            equity_curve = getattr(result, "equity_curve", [])
            trades = getattr(result, "trades", [])
            if equity_curve:
                kdb.store_equity_series(run_id, equity_curve)
            if trades:
                kdb.store_trades(run_id, trades)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"KnowledgeDB store failed (non-blocking): {e}")

    return filepath


# ═══════════════════════════════════════════════════════════════
# 便捷函数：从信号创建配置
# ═══════════════════════════════════════════════════════════════


def make_grid_config(
    symbol: str,
    signal: GridStrategy,
    position_mode: str = "fixed",
    position_kwargs: Optional[Dict[str, Any]] = None,
    risk_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> GridRunnerConfig:
    """
    快速创建 GridRunnerConfig。

    参数
    ----------
    symbol : str
        股票代码。
    signal : GridStrategy
        网格策略实例。
    position_mode : str
        仓位模式（"fixed" / "layer" / "batcher"）。
    position_kwargs : dict, optional
        仓位参数。
    risk_config : dict, optional
        风控配置，格式同 create_grid_manager。
    **kwargs :
        传给 GridRunnerConfig 的其他参数（tag, initial_capital 等）。

    返回
    -------
    GridRunnerConfig

    用法::

        signal = StaticGridSignal(
            grid_config=GridConfig(lower_bound=95, upper_bound=105, n_levels=10)
        )
        cfg = make_grid_config(
            symbol="000001.SZ",
            signal=signal,
            position_mode="layer",
            position_kwargs={"base_quantity": 200},
            risk_config={
                "stop_loss": {"stop_loss_pct": 0.05},
                "cool_down": {"cool_down_bars": 3},
            },
            tag="my_grid_test",
        )
    """
    position = create_grid_manager(
        position_mode=position_mode,
        position_kwargs=position_kwargs,
        risk_config=risk_config,
    )

    return GridRunnerConfig(
        symbol=symbol,
        signal=signal,
        position=position,
        **{k: v for k, v in kwargs.items() if k in GridRunnerConfig.__dataclass_fields__},
    )


# ═══════════════════════════════════════════════════════════════
# CLI 快捷运行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # python run_grid.py [symbol] [start_date] [end_date] [tag]
    # 示例: python run_grid.py 601857.SH 20230101 20260514 my_tag
    symbol = sys.argv[1] if len(sys.argv) > 1 else "000001.SZ"
    start_date = sys.argv[2] if len(sys.argv) > 2 else ""
    end_date = sys.argv[3] if len(sys.argv) > 3 else ""
    tag = sys.argv[4] if len(sys.argv) > 4 else f"cli_{symbol}"

    print(f"CLI 运行: symbol={symbol}, start_date={start_date or '(全部)'}, end_date={end_date or '(最新)'}, tag={tag}")

    result = run_grid_backtest(
        GridRunnerConfig(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            tag=tag,
        )
    )

    MI = result.metrics
    print("\n=== 核心指标 ===")
    for key, label in [
        ("annual_return_pct", "年化收益率"),
        ("max_drawdown_pct", "最大回撤"),
        ("sharpe_ratio", "夏普比率"),
        ("total_return_pct", "总收益率"),
        ("win_rate_pct", "胜率"),
        ("total_trades", "交易次数"),
        ("profit_loss_ratio", "盈亏比"),
    ]:
        val = MI.get(key)
        if val is None:
            print(f"  {label}: N/A")
        elif isinstance(val, float):
            print(f"  {label}: {val:.4f}")
        else:
            print(f"  {label}: {val}")
