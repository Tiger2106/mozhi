"""
mozhi_platform.src.backtest.methods.grid.grid_method — GridMethod

网格策略（逐 Bar 事件驱动）。
覆写 on_bar() 逐 Bar 判断网格触发，支持状态序列化。

旧系统源：grid_strategy.py — GridStrategy.on_bar() / DynamicGridSignal
迁移日期：2026-05-17
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from backtest.methods.base import BaseMethod
from backtest.methods.manifest import METHOD_META as _BASE_METHOD_META

# ──────────────────────────────────────────────────────────────────────
# METHOD_META 协议常量
# ──────────────────────────────────────────────────────────────────────

METHOD_META = {
    "name": "grid",
    "version": "1.0.0",
    "author": "墨衡",
    "description": "网格策略：逐 Bar 检测价格穿透网格线，支持状态持久化",
    "capabilities": {
        "long_only": True,
        "intraday_support": True,
        "requires_state": True,
    },
    "default_params": {
        "n_levels": 10,
        "grid_type": "arithmetic",
        "lookback": 20,
        "width_multiplier": 2.0,
    },
    "dependencies": ["atr"],
    "tags": ["grid", "event_driven"],
}


# ──────────────────────────────────────────────────────────────────────
# GridLevel — 网格线数据结构
# ──────────────────────────────────────────────────────────────────────


class GridLevel:
    """单个网格线。

    Args:
        price: 网格线价格。
        is_buy: True=买入线，False=卖出线。
    """

    def __init__(self, price: float, is_buy: bool):
        self.price: float = price
        self.is_buy: bool = is_buy
        self.triggered: bool = False  # 当前Bar是否已触发

    def reset_trigger(self) -> None:
        """重置触发标记（新Bar开始时调用）。"""
        self.triggered = False

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""
        return {"price": self.price, "is_buy": self.is_buy, "triggered": self.triggered}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GridLevel":
        """反序列化。"""
        level = cls(price=data["price"], is_buy=data["is_buy"])
        level.triggered = data.get("triggered", False)
        return level

    def __repr__(self) -> str:
        return (f"GridLevel(price={self.price:.4f}, "
                f"type={'buy' if self.is_buy else 'sell'}, "
                f"triggered={self.triggered})")


# ──────────────────────────────────────────────────────────────────────
# GridMethod
# ──────────────────────────────────────────────────────────────────────


class GridMethod(BaseMethod):
    METHOD_META = METHOD_META
    """网格策略信号方法（事件驱动，requires_state=True）。

    **设计说明**：

    GridMethod 使用事件驱动模式（与 `BaseMethod` 中 ``on_bar()`` 钩子配合），
    而非批量模式（``generate_signal()``）。

    **网格生成逻辑**（与旧系统 ``DynamicGridSignal`` 一致）：
    - 网格中心 = SMA(close, lookback)
    - 网格宽度基于 ATR(lookback) × width_multiplier
    - 网格线在 [center - width/2, center + width/2] 范围内等距分布

    **信号逻辑**（与旧系统 ``GridStrategy.on_bar()`` 一致）：
    - 每根新 Bar 到来时，检测价格是否穿越了任何网格线
    - 价格上穿买入线 → action="buy"（加仓）
    - 价格下穿卖出线 → action="sell"（减仓）
    - 每条网格线每根 Bar 最多触发一次

    **状态持久化**：
    - ``on_state_save()`` 保存当前位置（网格线价格 + 触发状态）
    - ``on_state_restore()`` 恢复持久化状态

    **默认参数**：
        - ``n_levels``：网格线数量（默认 10）
        - ``grid_type``：网格类型（"arithmetic" / "geometric"，默认 "arithmetic"）
        - ``lookback``：SMA 和 ATR 计算窗口（默认 20）
        - ``width_multiplier``：网格宽度倍率（默认 2.0）

    Examples:
        >>> method = GridMethod()
        >>> method.setup(ctx)
        >>> # 事件驱动（Runner 逐 Bar 调用 on_bar）
        >>> result = method.on_bar(row)
        >>> result  # {"action": "buy", "price": 100.0, "level": 101.5}
    """

    def setup(self, ctx) -> None:
        """从上下文装配参数。

        Args:
            ctx: StrategyContext 实例，需提供 ``get_config(key, default)`` 方法。
        """
        self.n_levels: int = ctx.get_config("n_levels", 10)
        self.grid_type: str = ctx.get_config("grid_type", "arithmetic")
        self.lookback: int = ctx.get_config("lookback", 20)
        self.width_multiplier: float = ctx.get_config("width_multiplier", 2.0)

        # ── 运行时状态 ──────────────────────────────────────────
        self._grid_levels: List[GridLevel] = []
        self._prev_close: Optional[float] = None
        self._bar_count: int = 0
        self._bars_history: List[pd.Series] = []

        # ── 信号结果收集 ────────────────────────────────────────
        self._signal_records: List[Dict[str, Any]] = []

    def generate_signal(self, df: pd.DataFrame) -> pd.DataFrame:
        """批量生成网格信号（模式 A 兼容）。

        对于 GridMethod，批量模式模拟事件驱动逻辑：
        逐 Bar 模拟调用 ``on_bar()``，收集所有信号后返回。

        Args:
            df: 包含 ``close``、``high``、``low`` 列的 OHLCV DataFrame。

        Returns:
            pd.DataFrame: 包含 ``signal`` 列的 DataFrame。
        """
        required = {"close", "high", "low"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"输入 DataFrame 缺少列: {missing}")

        n = len(df)
        signal = pd.Series(np.zeros(n, dtype=int), index=df.index)

        # 模拟逐 Bar 调用
        self._grid_levels = []
        self._prev_close = None
        self._bar_count = 0
        self._bars_history = []
        self._signal_records = []

        for i in range(n):
            row = df.iloc[i]
            self.on_bar(row)

            # 收集信号
            for rec in self._signal_records:
                if rec["action"] == "buy":
                    signal.iloc[i] = 1
                elif rec["action"] == "sell":
                    signal.iloc[i] = -1
            self._signal_records = []

        # 重建网格级别指标
        grid_center = pd.Series(np.nan, index=df.index)
        grid_width = pd.Series(np.nan, index=df.index)

        result = pd.DataFrame(
            {
                "signal": signal,
                "grid_center": grid_center,
                "grid_width": grid_width,
            },
            index=df.index,
        )
        return result

    def on_bar(self, row: pd.Series) -> Optional[Dict[str, Any]]:
        """逐 Bar 事件回调 — 检测网格穿透信号。

        Args:
            row: 当前 K 线数据（pd.Series），需包含 ``close``、``high``、``low``。

        Returns:
            - None: 无网格触发。
            - Dict: 触发信号，如 ``{"action": "buy", "price": 100.0, "level": 101.5}``。
        """
        self._bar_count += 1
        self._bars_history.append(row)

        current_close = row.get("close", None)
        if current_close is None:
            return None

        # ── 首次运行：初始化网格 ──────────────────────────────
        if self._prev_close is None or not self._grid_levels:
            self._rebuild_grid()
            self._prev_close = current_close
            return None

        # ── 重置触发标记 ──────────────────────────────────────
        for level in self._grid_levels:
            level.reset_trigger()

        prev_close = self._prev_close
        self._prev_close = current_close

        # ── 检测穿透 ──────────────────────────────────────────
        for level in self._grid_levels:
            if level.triggered:
                continue

            # 价格从一侧穿越到另一侧
            if (prev_close <= level.price and current_close > level.price):
                level.triggered = True
                action = "buy" if level.is_buy else "sell"
                result: Dict[str, Any] = {
                    "action": action,
                    "price": current_close,
                    "level": level.price,
                }
                self._signal_records.append(result)

            elif (prev_close >= level.price and current_close < level.price):
                level.triggered = True
                action = "sell" if level.is_buy else "buy"
                result = {
                    "action": action,
                    "price": current_close,
                    "level": level.price,
                }
                self._signal_records.append(result)

        # ── 定期重建网格（每 lookback 根 Bar） ────────────────
        if self._bar_count % self.lookback == 0:
            self._rebuild_grid()

        if self._signal_records:
            return self._signal_records[-1]  # 返回最新一条
        return None

    def _rebuild_grid(self) -> None:
        """重建网格线。

        网格中心 = SMA(close, lookback)
        网格宽度基于 ATR-lookback
        """
        if len(self._bars_history) < self.lookback:
            return

        window = [b.get("close", 0) for b in self._bars_history[-self.lookback:]]
        highs = [b.get("high", 0) for b in self._bars_history[-self.lookback:]]
        lows = [b.get("low", 0) for b in self._bars_history[-self.lookback:]]

        center = np.mean(window)
        atr_val = self._compute_atr(window, highs, lows)

        width = atr_val * self.width_multiplier
        lower = center - width / 2
        upper = center + width / 2

        # 生成网格线
        self._grid_levels = []
        n = self.n_levels

        if self.grid_type == "arithmetic":
            for i in range(n):
                price = lower + (upper - lower) * i / (n - 1)
                is_buy = (i < n // 2)  # 下半区为买入线，上半区为卖出线
                self._grid_levels.append(GridLevel(price=price, is_buy=is_buy))
        elif self.grid_type == "geometric":
            ratio = (upper / lower) ** (1.0 / (n - 1))
            for i in range(n):
                price = lower * (ratio ** i)
                is_buy = (i < n // 2)
                self._grid_levels.append(GridLevel(price=price, is_buy=is_buy))

    @staticmethod
    def _compute_atr(
        closes: List[float], highs: List[float], lows: List[float]
    ) -> float:
        """估算 ATR（简单实现，用于网格宽度）。

        Args:
            closes: 收盘价列表。
            highs: 最高价列表。
            lows: 最低价列表。

        Returns:
            float: 平均真实波幅。
        """
        if len(closes) < 2:
            return 0.0

        tr_values: List[float] = []
        for i in range(1, len(closes)):
            high = highs[i]
            low = lows[i]
            prev_close = closes[i - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)

        return float(np.mean(tr_values)) if tr_values else 0.0

    # ─── 状态持久化 ────────────────────────────────────────────

    def on_state_save(self) -> Dict[str, Any]:
        """保存当前状态快照。

        Returns:
            Dict[str, Any]: 包含网格线状态、前收盘价、Bar计数的字典。
        """
        return {
            "grid_levels": [level.to_dict() for level in self._grid_levels],
            "prev_close": self._prev_close,
            "bar_count": self._bar_count,
            "method_params": {
                "n_levels": self.n_levels,
                "grid_type": self.grid_type,
                "lookback": self.lookback,
                "width_multiplier": self.width_multiplier,
            },
        }

    def on_state_restore(self, state: Dict[str, Any]) -> None:
        """恢复持久化状态。

        Args:
            state: 由 ``on_state_save()`` 保存的字典。
        """
        if "grid_levels" in state:
            self._grid_levels = [
                GridLevel.from_dict(d) for d in state["grid_levels"]
            ]
        self._prev_close = state.get("prev_close", None)
        self._bar_count = state.get("bar_count", 0)

        # 还原参数（使用默认值回退）
        params = state.get("method_params", {})
        self.n_levels = params.get("n_levels", getattr(self, "n_levels", 10))
        self.grid_type = params.get("grid_type", getattr(self, "grid_type", "arithmetic"))
        self.lookback = params.get("lookback", getattr(self, "lookback", 20))
        self.width_multiplier = params.get("width_multiplier", getattr(self, "width_multiplier", 2.0))
