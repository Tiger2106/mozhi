"""
mozhi_platform.src.backtest.methods.base — 合约四件套之 BaseMethod / MethodResult

======================================================================
⚠️ 线程安全声明 (B2)
─────────────────────
BaseMethod 及其子类 NOT thread-safe。
每个方法实例应在单一线程内使用；跨线程共享须由调用方加锁。

所有 async def 实现的钩子方法将在运行时被 detect 并抛 DeprecationWarning
（参见 methods.discover 中的 async 检查逻辑）。
======================================================================
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ──────────────────────────────────────────────────────────────────────
# B1, B2: BaseMethod ABC
# ──────────────────────────────────────────────────────────────────────


class BaseMethod(ABC):
    """信号方法抽象基类 — 合约四件套之一。

    所有交易信号方法必须继承此类并实现抽象方法。

    ⚠️ NOT thread-safe: 每个实例必须在单一线程内使用。
    """

    # ─── 生命周期 ──────────────────────────────────────────────────

    @abstractmethod
    def setup(self, ctx: "StrategyContext") -> None:
        """初始化方法实例。

        Args:
            ctx: 策略上下文（StrategyContext frozen 实例）。

        Raises:
            TypeError: 如果 ctx 类型不匹配。
            ValueError: 如果必要配置缺失。
        """
        ...

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """从行情数据生成交易信号。

        Args:
            df: 包含 OHLCV 等必要列的 DataFrame，索引应为 DatetimeIndex。

        Returns:
            pd.DataFrame: 必须包含 'signal' 列，值域 {-1, 0, 1}。
                          -1=做空信号, 0=无信号, 1=做多信号。

        Raises:
            TypeError: 输入不是 pd.DataFrame。
            ValueError: 必要列缺失或数据不合法。
        """
        ...

    def cleanup(self) -> None:
        """资源清理（可选覆盖）。

        默认实现为空操作（no-op）。
        子类可覆盖以释放文件句柄、网络连接等资源。
        """
        pass

    # ─── 事件驱动钩子 ──────────────────────────────────────────────

    def on_bar(self, row: pd.Series) -> Optional[Dict[str, Any]]:
        """逐 Bar 事件回调（可选覆盖）。

        在事件驱动回测中每根 K 线到达时触发。
        默认返回 None（不产生附加信号）。

        Args:
            row: 当前 K 线数据（pd.Series）。

        Returns:
            - None: 无附加信号。
            - Dict: 附加信号字典（如 {"action": "buy", "price": row["close"]}）。

        ⚠️ 若子类以 ``async def on_bar(...)`` 实现，将在 discover 阶段
           被检测并抛出 DeprecationWarning：回测引擎当前不支持异步钩子。
        """
        return None

    # ─── 状态持久化 ────────────────────────────────────────────────

    def on_state_restore(self, state: Dict[str, Any]) -> None:
        """恢复持久化状态。

        Args:
            state: 由 :meth:`on_state_save` 保存的字典快照。

        默认实现为空操作。
        """
        pass

    def on_state_save(self) -> Dict[str, Any]:
        """保存当前状态快照。

        Returns:
            Dict[str, Any]: 可序列化的状态字典。

        默认返回空字典。
        """
        return {}

    # ─── 显示 ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"


# ──────────────────────────────────────────────────────────────────────
# B3, B4, B5, B6: MethodResult dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass
class MethodResult:
    """方法执行结果 — 合约四件套之二。

    承载一次 ``generate_signal()`` 调用的完整输出。
    """

    # ─── 核心输出 ──────────────────────────────────────────────────

    signals: pd.DataFrame
    """信号 DataFrame，必须包含 'signal' 列，索引需为 pd.DatetimeIndex。
    signal 列值域: {-1, 0, 1}。"""

    indicators: Optional[pd.DataFrame] = None
    """中间指标值（可选），用于调试/可视化。"""

    # ─── 元信息 ────────────────────────────────────────────────────

    method_name: str = ""
    """执行该结果的方法名称。"""

    params: Dict[str, Any] = field(default_factory=dict)
    """该次执行所用的参数快照。"""

    statistics: Dict[str, float] = field(default_factory=dict)
    """统计指标字典（所有值必须为 float 或 int）。"""

    # ─── 运行时指标 ────────────────────────────────────────────────

    completed_time: Optional[str] = None
    """计算完成时间的 ISO 格式字符串（可选，墨萱 R9）。"""

    duration_ms: Optional[float] = None
    """计算耗时（毫秒，可选，墨萱 R10）。"""

    errors: List[str] = field(default_factory=list)
    """执行期间产生的非致命错误列表。"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """扩展元数据字典（预留）。"""

    # ─── 自动计算字段 ──────────────────────────────────────────────

    n_bars: int = field(init=False)
    """信号 DataFrame 的行数（自动计算）。"""

    n_signals: int = field(init=False)
    """非零信号的数量（自动计算）。"""

    signal_ratio: float = field(init=False)
    """信号密度 = n_signals / n_bars（自动计算）。"""

    # ─── 空 DataFrame 时无信号时的 guard ──────────────────────────

    def __post_init__(self) -> None:
        """后初始化校验与自动计算。

        B5: 列存在性校验 + n_bars/n_signals/signal_ratio 自动计算 + 空 DF 防御
        B6: signal 列值域 {-1, 0, 1} 校验（墨萱 P1 修复）
        B7: signals.index 为 DatetimeIndex 校验（墨萱 P1 修复）
        B9: statistics 值类型校验（墨萱 P2）
        """
        # ── B5: 空 DataFrame 防御 ──────────────────────────────────
        if not isinstance(self.signals, pd.DataFrame):
            raise TypeError(
                f"signals 必须是 pd.DataFrame，收到 {type(self.signals).__name__}"
            )

        if self.signals.empty:
            self.n_bars = 0
            self.n_signals = 0
            self.signal_ratio = 0.0
            return

        # ── B5: signal 列存在性校验 ──────────────────────────────
        if "signal" not in self.signals.columns:
            raise ValueError(
                "signals DataFrame 必须包含 'signal' 列"
            )

        # ── B6: signal 列值域校验（墨萱 P1 修复） ────────────────
        signal_col = self.signals["signal"]
        if not signal_col.dropna().isin({-1, 0, 1}).all():
            invalid = signal_col[~signal_col.dropna().isin({-1, 0, 1})].unique()
            raise ValueError(
                f"signal 列值域必须为 {{-1, 0, 1}}，发现非法值: {invalid}"
            )

        # ── B7: 索引类型校验（墨萱 P1 修复） ──────────────────────
        if not isinstance(self.signals.index, pd.DatetimeIndex):
            raise ValueError(
                f"signals 索引必须为 pd.DatetimeIndex，"
                f"收到 {type(self.signals.index).__name__}"
            )

        # ── B5: 自动计算统计字段 ──────────────────────────────────
        self.n_bars = len(self.signals)
        self.n_signals = int((signal_col != 0).sum())
        self.signal_ratio = (
            self.n_signals / self.n_bars if self.n_bars > 0 else 0.0
        )

        # ── B9: statistics 值类型校验（墨萱 P2） ──────────────────
        for key, val in self.statistics.items():
            if not isinstance(val, (int, float)):
                warnings.warn(
                    f"statistics['{key}'] 类型为 {type(val).__name__}，"
                    f"期望 int 或 float"
                )
