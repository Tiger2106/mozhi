"""
墨枢 - P2-13 趋势回测运行器

集成管线：数据加载 → 信号生成 → 仓位管理 → 引擎执行 → 结果持久化。

用法::

    from backtest.strategies.run_trend import run_trend_backtest, TrendBacktestConfig

    # 默认配置（601857, MA金叉, 固定仓位30%, 固定止损5%）
    result = run_trend_backtest()

    # 自定义配置
    cfg = TrendBacktestConfig(
        symbol="601857",
        signal_type="macd",
        position_mode="pyramid",
        risk_params={"fixed_stop_loss": 0.05, "take_profit_atr_multiple": 2.0},
    )
    result = run_trend_backtest(cfg)
    print(result.metrics)
"""

from __future__ import annotations

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backtest.pipeline.knowledge_db import KnowledgeDB

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

# 信号生成器
from backtest.strategies.trend_strategy import (
    generate_ma_cross_signals,
    generate_macd_signals,
    generate_bollinger_signals,
    generate_trend_score_signals,
    compute_voted_signal,
)

# 仓位管理
from backtest.strategies.trend_position import (
    TrendPositionManager,
    StopLossTakeProfit,
    ExitSignal,
    create_position_manager,
)
from backtest.data_loader import load_stock_bars

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ═══════════════════════════════════════════════════════════════
# 持久化目录
# ═══════════════════════════════════════════════════════════════

_RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "backtest_results"
)


# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════


@dataclass
class TrendBacktestConfig:
    """
    趋势回测完整配置。

    参数说明
    ----------
    symbol : str
        股票代码，如 "601857"。
    start_date / end_date : str
        日期范围（YYYYMMDD 格式，留空表示全部数据）。
    signal_type : str
        信号类型，可选：
          - "ma"         MA 金叉/死叉
          - "macd"       MACD 金叉/死叉
          - "bollinger"  布林带突破
          - "trend_score" 趋势强度过滤
          - "voting"     多信号投票（MA+MACD+布林带）
    signal_params : dict
        信号生成参数（如 {"ma_fast": 5, "ma_slow": 20}）。
    position_mode : str
        仓位模式，可选 "fixed" / "trend_score" / "pyramid"。
    position_params : dict
        仓位模式参数（如 {"position_ratio": 0.3}）。
    risk_params : dict or None
        风控参数，传给 StopLossTakeProfit。
        如 {"fixed_stop_loss": 0.05, "trailing_stop_ma_period": 20,
            "take_profit_atr_multiple": 2.0}。
        传 None 表示不启用风控。
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
    signal_type: str = "ma"
    signal_params: Dict[str, Any] = field(default_factory=dict)
    position_mode: str = "fixed"
    position_params: Dict[str, Any] = field(default_factory=dict)
    risk_params: Optional[Dict[str, Any]] = None
    initial_capital: float = 1_000_000.0
    fee_rate: float = 0.0003
    slippage_rate: float = 0.001
    db_path: Optional[str] = None
    tag: str = "default"

    def __post_init__(self):
        # 信号参数默认值
        sig_defaults = {
            "ma": {"ma_fast": 5, "ma_slow": 20},
            "macd": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
            "bollinger": {"period": 20, "std_dev": 2.0},
            "trend_score": {"threshold": 0.35},
            "voting": {"min_votes": 2},
        }
        if not self.signal_params:
            self.signal_params = sig_defaults.get(self.signal_type, {})

        # 仓位参数默认值
        pos_defaults = {
            "fixed": {"position_ratio": 0.3},
            "trend_score": {},
            "pyramid": {"initial_ratio": 0.3, "add_wait_days": 5, "max_adds": 3},
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
                    "ma_fast": int,
                    "ma_slow": int,
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
            "ma": "ma_cross",
            "macd": "macd",
            "bollinger": "bollinger_breakout",
            "trend_score": "momentum",
            "voting": "ensemble_voting",
        }

        # ═══════════════════════════════════════════════════
        # 1. 信号参数（signal）
        # ═══════════════════════════════════════════════════
        result["signal"]["signal_type"] = _signal_type_map.get(
            self.signal_type, self.signal_type
        )

        if self.signal_params:
            # ma_fast
            ma_fast = self.signal_params.get("ma_fast")
            if ma_fast is not None and isinstance(ma_fast, (int, float)):
                result["signal"]["ma_fast"] = int(ma_fast)
            else:
                missing_keys.append("signal.ma_fast")
                result["signal"]["ma_fast"] = 5

            # ma_slow
            ma_slow = self.signal_params.get("ma_slow")
            if ma_slow is not None and isinstance(ma_slow, (int, float)):
                result["signal"]["ma_slow"] = int(ma_slow)
            else:
                missing_keys.append("signal.ma_slow")
                result["signal"]["ma_slow"] = 20
        else:
            missing_keys.extend(["signal.ma_fast", "signal.ma_slow"])
            result["signal"].update({"ma_fast": 5, "ma_slow": 20})

        # ═══════════════════════════════════════════════════
        # 2. 仓位参数（position）
        # ═══════════════════════════════════════════════════
        # position_sizing ← position_mode
        result["position"]["position_sizing"] = self.position_mode

        # max_positions — 根据模式推导
        if self.position_mode == "pyramid":
            max_adds = self.position_params.get("max_adds")
            if max_adds is not None and isinstance(max_adds, (int, float)):
                result["position"]["max_positions"] = int(max_adds) + 1
            else:
                missing_keys.append("position.max_positions")
                result["position"]["max_positions"] = 4  # 初始 + 3次加仓
        else:
            result["position"]["max_positions"] = 1  # 固定 / 趋势强度模式仅单次开仓

        # stop_loss_pct ← risk_params.fixed_stop_loss
        if self.risk_params:
            sl_pct = self.risk_params.get("fixed_stop_loss")
            if sl_pct is not None:
                result["position"]["stop_loss_pct"] = float(sl_pct)
            else:
                # 尝试 trailing_stop
                trailing_pct = self.risk_params.get("trailing_stop_ma_period")
                if trailing_pct is not None:
                    result["position"]["stop_loss_pct"] = float(trailing_pct) * 0.01  # 粗略估计
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
    根据 signal_type 生成信号列表。

    返回 List[Dict]，每项至少含 "date" / "symbol" / "signal" 字段。
    """
    generators = {
        "ma": lambda: generate_ma_cross_signals(
            bars,
            ma_fast=params.get("ma_fast", 5),
            ma_slow=params.get("ma_slow", 20),
        ),
        "macd": lambda: generate_macd_signals(
            bars,
            fast_period=params.get("fast_period", 12),
            slow_period=params.get("slow_period", 26),
            signal_period=params.get("signal_period", 9),
        ),
        "bollinger": lambda: generate_bollinger_signals(
            bars,
            period=params.get("period", 20),
            std_dev=params.get("std_dev", 2.0),
        ),
        "trend_score": lambda: generate_trend_score_signals(
            bars,
            threshold=params.get("threshold", 0.35),
            adx_period=params.get("adx_period", 14),
            ma_period=params.get("ma_period", 20),
            slope_period=params.get("slope_period", 5),
        ),
        "voting": lambda: _generate_voting_signals(bars, params),
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
    """多信号投票：融合 MA + MACD + 布林带。"""
    ma_signals = generate_ma_cross_signals(
        bars, ma_fast=params.get("ma_fast", 5), ma_slow=params.get("ma_slow", 20)
    )
    macd_signals = generate_macd_signals(
        bars,
        fast_period=params.get("fast_period", 12),
        slow_period=params.get("slow_period", 26),
        signal_period=params.get("signal_period", 9),
    )
    boll_signals = generate_bollinger_signals(
        bars, period=params.get("period", 20), std_dev=params.get("std_dev", 2.0)
    )

    weights = params.get("weights", None)
    min_votes = params.get("min_votes", 2)

    voted = compute_voted_signal(
        [ma_signals, macd_signals, boll_signals],
        min_votes=min_votes,
        weights=weights,
    )
    return voted


# ═══════════════════════════════════════════════════════════════
# 内部策略：整合 TrendPositionManager + SignalBridge
# ═══════════════════════════════════════════════════════════════


class _TrendRunnerStrategy(Strategy):
    """
    回测运行器专用的内部策略。

    职责：
      1. 通过 SignalBridge 消费预生成的信号
      2. 通过 TrendPositionManager 管理仓位和风控
      3. 支持 PyramidPosition 的加仓逻辑
    """

    def __init__(
        self,
        bridge: SignalBridge,
        pos_manager: TrendPositionManager,
        signal_df: Any = None,
    ):
        super().__init__()
        self.bridge = bridge
        self.pos_manager = pos_manager
        self._signal_df = signal_df

        # 运行时状态
        self._bars: List[Bar] = []
        self._bar_index: int = -1

    def on_start(self, context: Any) -> None:
        # 重置运行时状态（保留信号缓存）
        self._bars = []
        self._bar_index = -1

        # 复位金字塔状态（如果有）
        pos_logic = self.pos_manager.position_logic
        if hasattr(pos_logic, "reset"):
            pos_logic.reset()

        # 信号缓存：如果 on_start 前已加载，则跳过 reset
        # 仅在未缓存时重载
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

        # ── 1. 检查止损止盈退出 ───────────────────────────
        if pos is not None and not pos.is_empty:
            exit_sig = self.pos_manager.check_exit(
                pos, bar, self._bars, self._bar_index
            )
            if exit_sig.should_exit:
                qty = self.pos_manager.calc_close_quantity(pos)
                orders.append(
                    Signal(
                        symbol=bar.symbol,
                        direction="SELL",
                        confidence=1.0,
                        horizon="short",
                        signal_type="trend",
                        extras={"quantity": qty},
                    )
                )
                # 复位金字塔（如有）
                pos_logic = self.pos_manager.position_logic
                if hasattr(pos_logic, "on_close_all"):
                    pos_logic.on_close_all()
                return orders

        # ── 2. 信号处理 ──────────────────────────────────
        if signal > 0:  # BUY
            if pos is None or pos.is_empty:
                # 开新仓
                qty = self.pos_manager.calc_open_quantity(
                    capital=context.available_capital,
                    price=bar.close,
                    min_shares=100,
                )
                if qty > 0:
                    orders.append(
                        Signal(
                            symbol=bar.symbol,
                            direction="BUY",
                            confidence=1.0,
                            horizon="short",
                            signal_type="trend",
                            extras={"quantity": qty},
                        )
                    )
                    # 记录开仓（金字塔用）
                    pos_logic = self.pos_manager.position_logic
                    if hasattr(pos_logic, "on_open"):
                        pos_logic.on_open(self._bar_index)
            else:
                # 已有仓位 → 检查是否可加仓（金字塔模式）
                pos_logic = self.pos_manager.position_logic
                if hasattr(pos_logic, "should_add") and hasattr(pos_logic, "commit_add"):
                    if pos_logic.can_add_more:
                        has_signal = abs(signal) > 0 and signal > 0
                        if pos_logic.should_add(self._bar_index, has_signal):
                            add_qty = pos_logic.calc_add_quantity(
                                capital=context.available_capital,
                                price=bar.close,
                                min_shares=100,
                            )
                            if add_qty > 0:
                                orders.append(
                                    Signal(
                                        symbol=bar.symbol,
                                        direction="BUY",
                                        confidence=1.0,
                                        horizon="short",
                                        signal_type="trend",
                                        extras={"quantity": add_qty},
                                    )
                                )
                                pos_logic.commit_add(self._bar_index)

        elif signal < 0:  # SELL
            if pos is not None and not pos.is_empty:
                qty = self.pos_manager.calc_close_quantity(pos)
                if qty > 0:
                    orders.append(
                        Signal(
                            symbol=bar.symbol,
                            direction="SELL",
                            confidence=1.0,
                            horizon="short",
                            signal_type="trend",
                            extras={"quantity": qty},
                        )
                    )
                    # 平仓后复位金字塔
                    pos_logic = self.pos_manager.position_logic
                    if hasattr(pos_logic, "on_close_all"):
                        pos_logic.on_close_all()

        return orders if orders else None


# ═══════════════════════════════════════════════════════════════
# 辅助函数：Bars → DataFrame 转换
# ═══════════════════════════════════════════════════════════════


def _bars_to_dataframe(bars: List[Bar]) -> "pd.DataFrame":
    """将 List[Bar] 转换为 MethodBacktestRunner 可用的 OHLCV DataFrame。

    返回的 DataFrame 索引为 DatetimeIndex，列为 OHLCV + vwap。
    """
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
    """新版调用 — 通过 MethodBacktestRunner 运行趋势信号方法。

    使用新 MethodBacktestRunner 替代旧 BacktestEngine 管线。
    保留旧 run_trend_backtest() 不变（下兼容）。

    参数
    ----------
    symbol : str
        股票代码。
    config : dict, optional
        配置字典，可包含:
          - method_name: 方法标识 ("ma_cross", "macd", "bollinger", 默认 "ma_cross")
          - start_date / end_date: 日期范围
          - db_path: 数据库路径
          - 以及其他信号方法参数

    返回
    -------
    MethodResult

    用法::

        from backtest.strategies.run_trend import run_new

        result = run_new("601857", {"method_name": "ma_cross", "ma_fast": 10, "ma_slow": 30})
        print(result.method_name, result.n_signals)
    """
    if config is None:
        config = {}

    cfg = dict(config)  # 不修改原始入参
    method_name = cfg.pop("method_name", "ma_cross")
    start_date = cfg.pop("start_date", "")
    end_date = cfg.pop("end_date", "")
    db_path = cfg.pop("db_path", None)

    print(f"[run_trend.run_new] symbol={symbol}, method={method_name}")

    # 1. 加载数据（复用原有 load_stock_bars）
    bars = load_stock_bars(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        db_path=db_path,
    )
    df = _bars_to_dataframe(bars)
    print(f"[run_trend.run_new] 数据加载完成: {bars[0].date} ~ {bars[-1].date}, {len(bars)} 条")

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
def run_trend_backtest(
    config: Optional[TrendBacktestConfig] = None,
) -> BacktestResult:
    """
    趋势回测主入口。

    流程：
      1. 加载 601857（或指定标的）日线数据
      2. 按 signal_type 生成信号
      3. 创建 TrendPositionManager（仓位 + 风控）
      4. 创建内部策略并注入信号
      5. 配置并运行 BacktestEngine
      6. 持久化结果到 backtest_results/ 目录
      7. 返回 BacktestResult

    参数
    ----------
    config : TrendBacktestConfig, optional
        回测配置。默认使用 MA 金叉死叉 + 固定仓位 30%。

    返回
    -------
    BacktestResult

    用法::

        from backtest.strategies.run_trend import run_trend_backtest

        # 默认运行
        result = run_trend_backtest()

        # MACD + 趋势强度仓位
        cfg = TrendBacktestConfig(
            signal_type="macd",
            position_mode="trend_score",
            position_params={"score_map": [(50, 0.1), (70, 0.25), (90, 0.4)]},
            risk_params={"fixed_stop_loss": 0.05},
        )
        result = run_trend_backtest(cfg)
        print(f"年化收益: {result.metrics.get('annual_return', 'N/A')}")
    """
    if config is None:
        config = TrendBacktestConfig()

    # ── 1. 加载数据 ──────────────────────────────────────
    bars = load_stock_bars(
        symbol=config.symbol,
        start_date=config.start_date,
        end_date=config.end_date,
        db_path=config.db_path,
    )
    print(
        f"[run_trend] 数据加载完成: {config.symbol}, "
        f"{bars[0].date} ~ {bars[-1].date}, {len(bars)} 条"
    )

    # ── 2. 生成信号 ──────────────────────────────────────
    signal_records = generate_signals(bars, config.signal_type, config.signal_params)
    signal_df = _build_signal_df(signal_records)
    print(
        f"[run_trend] 信号生成: {config.signal_type}, "
        f"共 {len(signal_records)} 条"
    )

    # ── 3. 创建仓位管理器 ──────────────────────────────────
    pos_manager = create_position_manager(
        mode=config.position_mode,
        position_ratio=config.position_params.get("position_ratio", 0.3),
        risk_config=config.risk_params,
        **{
            k: v
            for k, v in config.position_params.items()
            if k != "position_ratio"
        },
    )

    # ── 4. 创建策略并加载信号 ──────────────────────────────
    bridge = SignalBridge(
        config=SignalBridgeConfig(
            default_quantity=1000,  # 默认数量，将被仓位管理器覆盖
            max_position_pct=1.0,   # 不使用桥上限制（由仓位管理器控制）
        )
    )
    bridge.load_signals(signal_df)

    strategy = _TrendRunnerStrategy(
        bridge=bridge,
        pos_manager=pos_manager,
        signal_df=signal_df,
    )

    # ── 5. 配置并运行引擎 ──────────────────────────────────
    # 注意：DateAligner.align 在处理空字符串 end_date 时有 Python
    # 字符串比较缺陷（"" <= "20260514" 为 True），因此显式确定日期范围
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
        f"[run_trend] 回测完成: "
        f"交易次数={result.total_trades}, "
        f"年化收益={ann_str}, "
        f"指标keys={list(result.metrics.keys())}"
    )

    # ── 6. 持久化结果 ──────────────────────────────────────
    _persist_result(result, config)

    return result


# ═══════════════════════════════════════════════════════════════
# 结果持久化
# ═══════════════════════════════════════════════════════════════


def _persist_result(result: BacktestResult, config: TrendBacktestConfig) -> str:
    """
    将回测结果写入 backtest_results 目录。

    文件名格式: trend_{symbol}_{signal}_{pos_mode}_{tag}_{timestamp}.json

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
    strategy_name = "trend"
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

    print(f"[run_trend] 结果已保存: {filepath}")

    # 知识库写入（不阻塞，异常不影响主流程）
    try:
        metrics = result.metrics
        config_key = f"{config.signal_type}_{config.position_mode}_{config.tag}"
        with KnowledgeDB() as kdb:
            kdb.store_run(
                strategy="trend",
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
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"KnowledgeDB store failed (non-blocking): {e}")

    return filepath


# ═══════════════════════════════════════════════════════════════
# 便捷函数：批量运行多个配置（并发）
# ═══════════════════════════════════════════════════════════════

# DEPRECATED: 将在 Phase 5 结束后移除
def run_trend_backtest_batch(
    configs: List[TrendBacktestConfig],
    max_workers: int = 4,
) -> List[BacktestResult]:
    """
    并发批量运行多个回测配置。

    参数
    ----------
    configs : List[TrendBacktestConfig]
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
            executor.submit(run_trend_backtest, cfg): i
            for i, cfg in enumerate(configs)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                result = future.result()
                results[idx] = result
                print(f"[batch:concurrent] 回测 {idx+1}/{len(configs)} 完成 (config #{idx+1})")
            except Exception as e:
                print(f"[batch:concurrent] 回测 {idx+1}/{len(configs)} 失败: {e}")
                results[idx] = None
    return results


# ═══════════════════════════════════════════════════════════════
# CLI 快捷运行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # python run_trend.py [symbol] [signal_type] [pos_mode] [start_date] [end_date] [tag]
    # 示例: python run_trend.py 601857 ma fixed 20230101 20260514 my_tag
    symbol = sys.argv[1] if len(sys.argv) > 1 else "601857"
    signal_type = sys.argv[2] if len(sys.argv) > 2 else "ma"
    pos_mode = sys.argv[3] if len(sys.argv) > 3 else "fixed"
    start_date = sys.argv[4] if len(sys.argv) > 4 else ""
    end_date = sys.argv[5] if len(sys.argv) > 5 else ""
    tag = sys.argv[6] if len(sys.argv) > 6 else f"cli_{signal_type}_{pos_mode}"

    print(f"CLI 运行: symbol={symbol}, signal={signal_type}, position={pos_mode}, "
          f"start_date={start_date or '(全部)'}, end_date={end_date or '(最新)'}, tag={tag}")

    cfg = TrendBacktestConfig(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        signal_type=signal_type,
        position_mode=pos_mode,
        tag=tag,
    )
    result = run_trend_backtest(cfg)

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
