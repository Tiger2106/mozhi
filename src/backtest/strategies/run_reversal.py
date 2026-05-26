"""
墨枢 - P3-14 / P3-15 / P3-16 反转回测运行器

集成管线：数据加载 → 反转信号生成 → 仓位管理 → 引擎执行 → 结果持久化。

用法::

    from backtest.strategies.run_reversal import run_reversal_backtest, ReversalBacktestConfig

    # 默认配置（601857, RSI, 固定仓位20%, 固定止损5%）
    result = run_reversal_backtest()

    # 自定义配置
    cfg = ReversalBacktestConfig(
        symbol="601857",
        signal_type="rsi",
        position_mode="fixed",
        risk_params={"atr_multiple": 2.0, "fixed_stop_pct": 0.05},
    )
    result = run_reversal_backtest(cfg)
    print(result.metrics)
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

_TZ_CN = timezone(timedelta(hours=8))
from typing import Any, Dict, List, Optional

# 新版统一运行器
from backtest.runners.method_backtest_runner import MethodBacktestRunner
from backtest.context import StrategyContext
from backtest.methods.base import MethodResult

from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Bar,
    Strategy,
)
from src.signals.signal_protocol_v1 import Signal
from backtest.signal_bridge import SignalBridge, SignalBridgeConfig
from backtest.pipeline.knowledge_db import KnowledgeDB

# 反转信号生成
from backtest.strategies.reversal_strategy import (
    generate_rsi_signals,
    generate_kdj_signals,
    generate_bollinger_reversal_signals,
    generate_bias_signals,
    voted_reversal_signal,
    ReversalCooler,
)

# 反转仓位管理
from backtest.strategies.reversal_position import (
    ReversalPositionManager,
    create_reversal_position_manager,
)
from backtest.data_loader import load_stock_bars

# ═══════════════════════════════════════════════════════════════
# 持久化目录
# ═══════════════════════════════════════════════════════════════

_RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "backtest_results"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════


@dataclass
class ReversalBacktestConfig:
    """
    反转回测完整配置。

    参数说明
    ----------
    symbol : str
        股票代码，如 "601857"。
    start_date / end_date : str
        日期范围（YYYYMMDD 格式，留空表示全部数据）。
    signal_type : str
        信号类型，可选：
          - "rsi"                 RSI 超卖超买
          - "kdj"                 KDJ 超卖超买
          - "bollinger_reversal"  布林带反转
          - "bias"                短期乖离率
          - "voted"               多规则投票
    signal_params : dict
        信号生成参数。
    position_mode : str
        仓位模式，可选 "fixed" / "oversold_depth" / "batch"。
    position_params : dict
        仓位模式参数。
    risk_params : dict or None
        风控参数，传给 ReversalStopLoss。
        如 {"atr_multiple": 2.0, "fixed_stop_pct": 0.05}。
        传 None 表示不启用风控。
    cooler_days : int
        反转冷却期天数（默认 2），0 表示不启用冷却。
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

    symbol: str = "601857"
    start_date: str = ""
    end_date: str = ""
    signal_type: str = "rsi"
    signal_params: Dict[str, Any] = field(default_factory=dict)
    position_mode: str = "fixed"
    position_params: Dict[str, Any] = field(default_factory=dict)
    risk_params: Optional[Dict[str, Any]] = None
    cooler_days: int = 2
    initial_capital: float = 1_000_000.0
    fee_rate: float = 0.0003
    slippage_rate: float = 0.001
    db_path: Optional[str] = None
    tag: str = "default"

    def __post_init__(self):
        # 信号参数默认值
        sig_defaults = {
            "rsi": {"period": 14, "oversold": 30, "overbought": 70},
            "kdj": {"period": 9, "k_buy": 20, "k_sell": 80},
            "bollinger_reversal": {"period": 20, "std_dev": 2.0},
            "bias": {"ma_period": 5, "bias_buy": -0.05, "bias_sell": 0.05},
            "voted": {"min_votes": 2},
        }
        if not self.signal_params:
            self.signal_params = sig_defaults.get(self.signal_type, {})

        # 仓位参数默认值
        pos_defaults = {
            "fixed": {"position_ratio": 0.20},
            "oversold_depth": {},
            "batch": {"first_ratio": 0.10, "second_ratio": 0.15, "confirm_days": 1},
        }
        if not self.position_params:
            self.position_params = pos_defaults.get(self.position_mode, {})

    def to_params_dict(self) -> Dict[str, Any]:
        """
        将回测配置导出为统一参数字典（跨系统对接）。

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
                    "oversold_threshold": float,
                    "overbought_threshold": float,
                    "lookback_period": int,
                    "signal_type": str,
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

        # ── 信号类型映射 ──────────────────────────────────
        _signal_type_map = {
            "rsi": "rsi",
            "kdj": "kdj",
            "bollinger_reversal": "bollinger",
            "bias": "bias",
            "voted": "voted",
        }

        # ═══════════════════════════════════════════════════
        # 1. 信号参数（signal）
        # ═══════════════════════════════════════════════════
        result["signal"]["signal_type"] = _signal_type_map.get(
            self.signal_type, self.signal_type
        )

        if self.signal_params:
            # lookback_period ← period / ma_period
            period = self.signal_params.get("period")
            if period is None:
                period = self.signal_params.get("ma_period")
            if period is not None and isinstance(period, (int, float)):
                result["signal"]["lookback_period"] = int(period)
            else:
                missing_keys.append("signal.lookback_period")
                result["signal"]["lookback_period"] = 14

            # oversold_threshold ← oversold / k_buy / bias_buy（取绝对值）
            oversold = self.signal_params.get("oversold")
            if oversold is None:
                oversold = self.signal_params.get("k_buy")
            if oversold is None:
                bias_buy = self.signal_params.get("bias_buy")
                if bias_buy is not None:
                    oversold = abs(bias_buy) * 100  # 乖离率 → 百分比
            if oversold is not None:
                result["signal"]["oversold_threshold"] = float(oversold)
            else:
                missing_keys.append("signal.oversold_threshold")
                result["signal"]["oversold_threshold"] = 30.0

            # overbought_threshold ← overbought / k_sell / bias_sell（取绝对值）
            overbought = self.signal_params.get("overbought")
            if overbought is None:
                overbought = self.signal_params.get("k_sell")
            if overbought is None:
                bias_sell = self.signal_params.get("bias_sell")
                if bias_sell is not None:
                    overbought = abs(bias_sell) * 100  # 乖离率 → 百分比
            if overbought is not None:
                result["signal"]["overbought_threshold"] = float(overbought)
            else:
                missing_keys.append("signal.overbought_threshold")
                result["signal"]["overbought_threshold"] = 70.0
        else:
            missing_keys.extend([
                "signal.lookback_period",
                "signal.oversold_threshold",
                "signal.overbought_threshold",
            ])
            result["signal"].update({
                "lookback_period": 14,
                "oversold_threshold": 30.0,
                "overbought_threshold": 70.0,
            })

        # ═══════════════════════════════════════════════════
        # 2. 仓位参数（position）
        # ═══════════════════════════════════════════════════
        # position_sizing ← position_mode
        result["position"]["position_sizing"] = self.position_mode

        # max_positions — 根据模式推导
        if self.position_mode == "batch":
            result["position"]["max_positions"] = 2  # 首仓 + 加仓
        elif self.position_mode == "oversold_depth":
            result["position"]["max_positions"] = 1
        else:
            result["position"]["max_positions"] = 1  # fixed 及其他模式

        # stop_loss_pct ← risk_params.fixed_stop_pct
        if self.risk_params:
            sl_pct = self.risk_params.get("fixed_stop_pct")
            if sl_pct is not None:
                result["position"]["stop_loss_pct"] = float(sl_pct)
            else:
                # 尝试 atr_multiple 作为替代（无精确百分比）
                atr_mult = self.risk_params.get("atr_multiple")
                if atr_mult is not None:
                    result["position"]["stop_loss_pct"] = float(atr_mult) * 0.02  # 粗略估算
                else:
                    result["position"]["stop_loss_pct"] = 0.0
        else:
            result["position"]["stop_loss_pct"] = 0.0
            if "position.max_positions" not in missing_keys:
                missing_keys.append("position.stop_loss_pct")

        # ═══════════════════════════════════════════════════
        # 3. Meta：完整性标记
        # ═══════════════════════════════════════════════════
        result["meta"] = {"has_full_params": len(missing_keys) == 0}

        return result


# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════
# 信号生成
# ═══════════════════════════════════════════════════════════════


def _build_signal_df(records: List[Dict[str, Any]]) -> Any:
    """
    将信号记录列表转换为 SignalBridge 可用的 DataFrame 对象。

    构造一个类似 pandas DataFrame 的简单包装，支持 .iterrows() 和 [] 访问，
    避免对 pandas 的硬依赖。
    """
    try:
        import pandas as pd

        return pd.DataFrame(records)
    except ImportError:
        pass

    # 降级：纯 Python 包装
    class _SignalFrame:
        def __init__(self, records: List[Dict[str, Any]]):
            self._records = records
            self._index = 0

        def iterrows(self):
            for i, rec in enumerate(self._records):
                yield i, rec

        def __getitem__(self, key):
            if isinstance(key, str):
                return [r.get(key) for r in self._records]
            return self._records[key]

        def __len__(self):
            return len(self._records)

        def __repr__(self):
            return f"<SignalFrame {len(self._records)} rows>"

        def to_dict(self):
            return {"records": self._records}

    return _SignalFrame(records)


def generate_signals(
    bars: List[Bar],
    signal_type: str,
    params: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    根据 signal_type 生成反转信号列表。

    返回 List[Dict]，每项至少含 "date" / "symbol" / "signal" 字段。
    """
    generators = {
        "rsi": lambda: generate_rsi_signals(
            bars,
            period=params.get("period", 14),
            oversold=params.get("oversold", 30),
            overbought=params.get("overbought", 70),
        ),
        "kdj": lambda: generate_kdj_signals(
            bars,
            period=params.get("period", 9),
            k_buy=params.get("k_buy", 20),
            k_sell=params.get("k_sell", 80),
        ),
        "bollinger_reversal": lambda: generate_bollinger_reversal_signals(
            bars,
            period=params.get("period", 20),
            std_dev=params.get("std_dev", 2.0),
        ),
        "bias": lambda: generate_bias_signals(
            bars,
            ma_period=params.get("ma_period", 5),
            bias_buy=params.get("bias_buy", -0.05),
            bias_sell=params.get("bias_sell", 0.05),
        ),
        "voted": lambda: _generate_voting_signals(bars, params),
    }

    gen = generators.get(signal_type)
    if gen is None:
        raise ValueError(
            f"未知 signal_type: {signal_type}，"
            f"可选: {list(generators.keys())}"
        )

    return gen()


def _generate_voting_signals(
    bars: List[Bar], params: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """多信号投票：融合 RSI + KDJ + 布林带反转 + 乖离率。"""
    rsi_signals = generate_rsi_signals(
        bars,
        period=params.get("period", 14),
        oversold=params.get("oversold", 30),
        overbought=params.get("overbought", 70),
    )
    kdj_signals = generate_kdj_signals(
        bars,
        period=params.get("period", 9),
        k_buy=params.get("k_buy", 20),
        k_sell=params.get("k_sell", 80),
    )
    bb_signals = generate_bollinger_reversal_signals(
        bars,
        period=params.get("period", 20),
        std_dev=params.get("std_dev", 2.0),
    )
    bias_signals = generate_bias_signals(
        bars,
        ma_period=params.get("ma_period", 5),
        bias_buy=params.get("bias_buy", -0.05),
        bias_sell=params.get("bias_sell", 0.05),
    )

    min_votes = params.get("min_votes", 2)

    voted = voted_reversal_signal(
        [rsi_signals, kdj_signals, bb_signals, bias_signals],
        min_votes=min_votes,
    )
    return voted["signal"]


# ═══════════════════════════════════════════════════════════════
# 内部策略：整合 ReversalPositionManager + SignalBridge + 冷却期
# ═══════════════════════════════════════════════════════════════


class _ReversalRunnerStrategy(Strategy):
    """
    反转回测运行器专用的内部策略。

    职责：
      1. 通过 SignalBridge 消费预生成的信号
      2. 通过 ReversalPositionManager 管理仓位和风控
      3. 支持 BatchReversalPosition 的加仓逻辑
      4. 支持 ReversalCooler 冷却期
    """

    def __init__(
        self,
        bridge: SignalBridge,
        pos_manager: ReversalPositionManager,
        cooler: ReversalCooler,
        signal_df: Any = None,
    ):
        super().__init__()
        self.bridge = bridge
        self.pos_manager = pos_manager
        self.cooler = cooler
        self._signal_df = signal_df

        # 运行时状态
        self._bars: List[Bar] = []
        self._bar_index: int = -1

    def on_start(self, context: Any) -> None:
        # 重置运行时状态
        self._bars = []
        self._bar_index = -1

        # 复位仓位状态（分批模式等）
        self.pos_manager.reset()

        # 复位冷却期
        self.cooler.reset()

        # 信号缓存：如果 on_start 前已加载，则跳过 reset
        if not self.bridge._signal_cache and self._signal_df is not None:
            self.bridge.load_signals(self._signal_df)

    def on_bar(
        self, context: Any, bar: Bar
    ) -> Optional[List[Signal]]:
        self._bars.append(bar)
        self._bar_index += 1

        signal = self.bridge.get_signal(bar)
        pos = (
            context.positions.get(bar.symbol)
            if context.positions.has_position(bar.symbol)
            else None
        )

        orders: List[Signal] = []

        def _make_signal(direction: str, qty: int) -> Signal:
            return Signal(
                signal_id=str(uuid.uuid4()),
                symbol=bar.symbol,
                direction=direction,
                confidence=1.0,
                horizon="short",
                signal_type="reversal",
                timestamp=datetime.now(_TZ_CN),
                protocol_version="1.0",
                extras={"quantity": qty},
            )

        # ── 1. 检查止损止盈退出 ───────────────────────────
        if pos is not None and not pos.is_empty:
            exit_sig = self.pos_manager.check_exit(
                pos, bar, self._bars, self._bar_index
            )
            if exit_sig.should_exit:
                qty = self.pos_manager.calc_close_quantity(pos)
                orders.append(_make_signal("SELL", qty))
                # 平仓后复位
                self.pos_manager.on_close_all()
                self.cooler.reset(bar.symbol)
                return orders

        # ── 2. 信号处理 ──────────────────────────────────
        if signal > 0:  # BUY
            if pos is None or pos.is_empty:
                # 冷却期检查
                if not self.cooler.can_open(bar.date, bar.symbol, signal):
                    return None

                # 开新仓
                qty = self.pos_manager.calc_open_quantity(
                    capital=context.available_capital,
                    price=bar.close,
                    min_shares=100,
                )
                if qty > 0:
                    orders.append(_make_signal("BUY", qty))
                    # 记录开仓（分批模式用）
                    self.pos_manager.on_first_open(self._bar_index)
                    # 记录冷却期
                    self.cooler.record(bar.date, bar.symbol, signal)
            else:
                # 已有仓位 → 检查是否可加仓（分批模式）
                if self.pos_manager.should_confirm(self._bar_index, True):
                    confirm_qty = self.pos_manager.calc_confirm_quantity(
                        capital=context.available_capital,
                        price=bar.close,
                        min_shares=100,
                    )
                    if confirm_qty > 0:
                        orders.append(_make_signal("BUY", confirm_qty))
                        self.pos_manager.on_confirm()

        elif signal < 0:  # SELL
            if pos is not None and not pos.is_empty:
                qty = self.pos_manager.calc_close_quantity(pos)
                if qty > 0:
                    orders.append(_make_signal("SELL", qty))
                    # 平仓后复位状态
                    self.pos_manager.on_close_all()
                    self.cooler.reset(bar.symbol)

        return orders if orders else None


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
    symbol: str = "601857",
    config: Optional[Dict[str, Any]] = None,
) -> MethodResult:
    """新版调用 — 通过 MethodBacktestRunner 运行反转信号方法。

    使用新 MethodBacktestRunner 替代旧 BacktestEngine 管线。
    保留旧 run_reversal_backtest() 不变（下兼容）。

    参数
    ----------
    symbol : str
        股票代码。
    config : dict, optional
        配置字典，可包含:
          - method_name: 方法标识 ("rsi", "kdj", "bias", "bollinger", 默认 "rsi")
          - start_date / end_date: 日期范围
          - db_path: 数据库路径
          - 以及其他信号方法参数

    返回
    -------
    MethodResult
    """
    if config is None:
        config = {}

    cfg = dict(config)  # 不修改原始入参
    method_name = cfg.pop("method_name", "rsi")
    start_date = cfg.pop("start_date", "")
    end_date = cfg.pop("end_date", "")
    db_path = cfg.pop("db_path", None)

    print(f"[run_reversal.run_new] symbol={symbol}, method={method_name}")

    # 1. 加载数据（复用原有 load_stock_bars）
    bars = load_stock_bars(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        db_path=db_path,
    )
    df = _bars_to_dataframe(bars)
    print(f"[run_reversal.run_new] 数据加载完成: {bars[0].date} ~ {bars[-1].date}, {len(bars)} 条")

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
# 主运行函数
# ═══════════════════════════════════════════════════════════════

# DEPRECATED: 将在 Phase 5 结束后移除
def run_reversal_backtest(
    config: Optional[ReversalBacktestConfig] = None,
) -> BacktestResult:
    """
    反转回测主入口（P3-14）。

    流程：
      1. 加载 601857（或指定标的）日线数据
      2. 按 signal_type 生成反转信号
      3. 创建 ReversalPositionManager（仓位 + 风控）
      4. 创建 ReversalCooler 冷却期管理器
      5. 创建内部策略并注入信号
      6. 配置并运行 BacktestEngine
      7. 持久化结果到 backtest_results/ 目录
      8. 返回 BacktestResult

    参数
    ----------
    config : ReversalBacktestConfig, optional
        回测配置。默认使用 RSI + 固定仓位 20%。

    返回
    -------
    BacktestResult

    用法::

        from backtest.strategies.run_reversal import run_reversal_backtest

        # 默认运行
        result = run_reversal_backtest()

        # KDJ + 超卖深度仓位 + ATR×2 止损
        cfg = ReversalBacktestConfig(
            signal_type="kdj",
            position_mode="oversold_depth",
            risk_params={"atr_multiple": 2.0, "fixed_stop_pct": 0.05},
        )
        result = run_reversal_backtest(cfg)
        print(f"年化收益: {result.metrics.get('annual_return', 'N/A')}")
    """
    if config is None:
        config = ReversalBacktestConfig()

    # ── 1. 加载数据 ──────────────────────────────────────
    bars = load_stock_bars(
        symbol=config.symbol,
        start_date=config.start_date,
        end_date=config.end_date,
        db_path=config.db_path,
    )
    print(
        f"[run_reversal] 数据加载完成: {config.symbol}, "
        f"{bars[0].date} ~ {bars[-1].date}, {len(bars)} 条"
    )

    # ── 2. 生成信号 ──────────────────────────────────────
    signal_records = generate_signals(bars, config.signal_type, config.signal_params)
    signal_df = _build_signal_df(signal_records)
    print(
        f"[run_reversal] 信号生成: {config.signal_type}, "
        f"共 {len(signal_records)} 条"
    )

    # ── 3. 创建仓位管理器（仓位 + 风控） ──────────────────
    pos_manager = create_reversal_position_manager(
        mode=config.position_mode,
        position_ratio=config.position_params.get("position_ratio", 0.20),
        risk_config=config.risk_params,
        **{
            k: v
            for k, v in config.position_params.items()
            if k != "position_ratio"
        },
    )

    # ── 4. 创建冷却期管理器 ──────────────────────────────
    cooler = ReversalCooler(cooler_days=config.cooler_days)

    # ── 5. 创建策略并加载信号 ──────────────────────────────
    bridge = SignalBridge(
        config=SignalBridgeConfig(
            default_quantity=1000,   # 默认数量，将被仓位管理器覆盖
            max_position_pct=1.0,    # 不使用桥上限制（由仓位管理器控制）
        )
    )
    bridge.load_signals(signal_df)

    strategy = _ReversalRunnerStrategy(
        bridge=bridge,
        pos_manager=pos_manager,
        cooler=cooler,
        signal_df=signal_df,
    )

    # ── 6. 配置并运行引擎 ──────────────────────────────────
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
    result = engine.run(bars)

    ann_ret = result.metrics.get('annual_return_pct', None)
    ann_str = f"{ann_ret:.2%}" if ann_ret is not None else "N/A"
    print(
        f"[run_reversal] 回测完成: "
        f"交易次数={result.total_trades}, "
        f"年化收益={ann_str}, "
        f"指标keys={list(result.metrics.keys())}"
    )

    # ── 7. 持久化结果 ──────────────────────────────────────
    _persist_result(result, config)

    return result


# ═══════════════════════════════════════════════════════════════
# 结果持久化（P3-16）
# ═══════════════════════════════════════════════════════════════


def _persist_result(result: BacktestResult, config: ReversalBacktestConfig) -> str:
    """
    将回测结果写入 backtest_results 目录。

    文件名格式: reversal_{symbol}_{signal}_{pos_mode}_{tag}_{date}_{time}.json

    返回保存的文件路径。
    """
    output_dir = os.environ.get(
        "BACKTEST_RESULTS_DIR", _RESULTS_DIR
    )
    os.makedirs(output_dir, exist_ok=True)

    # 文件名: {strategy}_{symbol}_{signal}_{position}_{tag}_{date}_{time}.json
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    strategy_name = "reversal"
    filename = (
        f"{strategy_name}_{config.symbol}_"
        f"{config.signal_type}_"
        f"{config.position_mode}_"
        f"{config.tag}_"
        f"{date_part}_{time_part}.json"
    )
    filepath = os.path.join(output_dir, filename)

    # 构建持久化数据
    payload = {
        "meta": {
            "symbol": config.symbol,
            "signal_type": config.signal_type,
            "signal_params": config.signal_params,
            "position_mode": config.position_mode,
            "position_params": config.position_params,
            "risk_params": config.risk_params,
            "cooler_days": config.cooler_days,
            "initial_capital": config.initial_capital,
            "fee_rate": config.fee_rate,
            "slippage_rate": config.slippage_rate,
            "tag": config.tag,
            "timestamp": f"{date_part}_{time_part}",
        },
        "result": result.to_dict(),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    print(f"[run_reversal] 结果已保存: {filepath}")

    # 知识库写入（不阻塞，异常不影响主流程）
    try:
        metrics = result.metrics
        with KnowledgeDB() as kdb:
            kdb.store_run(
                strategy="reversal",
                symbol=config.symbol,
                # BUGFIX: 2026-05-16: config_key must be combined key (consistent with run_trend/run_grid)
                config_key=f"{config.signal_type}_{config.position_mode}_{config.tag}",
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
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"KnowledgeDB store failed (non-blocking): {e}")

    return filepath


# ═══════════════════════════════════════════════════════════════
# 便捷函数：批量运行多个配置（并行）（P3-15）
# ═══════════════════════════════════════════════════════════════

# DEPRECATED: 将在 Phase 5 结束后移除
def run_reversal_backtest_batch(
    configs: List[ReversalBacktestConfig],
    max_workers: int = 4,
) -> List[BacktestResult]:
    """
    并发批量运行多个反转回测配置（P3-15）。

    参数
    ----------
    configs : List[ReversalBacktestConfig]
        回测配置列表。
    max_workers : int
        最大并发数，默认 4。

    返回
    -------
    List[BacktestResult]
        对应的结果列表（顺序与 configs 一致，失败项为 None）。
    """
    results: List[BacktestResult] = [None] * len(configs)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_reversal_backtest, cfg): i
            for i, cfg in enumerate(configs)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                result = future.result()
                results[idx] = result
                print(f"[batch:concurrent] 反转回测 {idx+1}/{len(configs)} 完成 (config #{idx+1})")
            except Exception as e:
                print(f"[batch:concurrent] 反转回测 {idx+1}/{len(configs)} 失败: {e}")
                results[idx] = None
    return results


# ═══════════════════════════════════════════════════════════════
# CLI 快捷运行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # python run_reversal.py [symbol] [signal_type] [pos_mode] [start_date] [end_date] [tag]
    # 示例: python run_reversal.py 601857 rsi fixed 20230101 20260514 my_tag
    symbol = sys.argv[1] if len(sys.argv) > 1 else "601857"
    signal_type = sys.argv[2] if len(sys.argv) > 2 else "rsi"
    pos_mode = sys.argv[3] if len(sys.argv) > 3 else "fixed"
    start_date = sys.argv[4] if len(sys.argv) > 4 else ""
    end_date = sys.argv[5] if len(sys.argv) > 5 else ""
    tag = sys.argv[6] if len(sys.argv) > 6 else f"cli_{signal_type}_{pos_mode}"

    print(f"CLI 运行: symbol={symbol}, signal={signal_type}, position={pos_mode}, "
          f"start_date={start_date or '(全部)'}, end_date={end_date or '(最新)'}, tag={tag}")

    cfg = ReversalBacktestConfig(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        signal_type=signal_type,
        position_mode=pos_mode,
        tag=tag,
    )
    result = run_reversal_backtest(cfg)

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
