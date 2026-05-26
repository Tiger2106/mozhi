"""
mozhi_platform.src.backtest.risk.drawdown_guard — DrawdownGuard 回撤断路器

持续监控权益曲线，当回撤超出阈值时触发断路器动作：
- warning (8%): 禁止开新仓
- critical (15%): 强制清仓 + 冷却期

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class DrawdownState:
    """回撤守卫的内部状态快照"""
    peak_equity: float = 0.0
    """历史最高权益。"""
    current_drawdown: float = 0.0
    """当前回撤比例（0 = 无回撤，0.1 = 10%）。"""
    breach_level: str = "none"
    """当前触发级别: "none" | "warning" | "critical" """
    cooldown_remaining: int = 0
    """剩余冷却 K 线数。"""
    peak_timestamp: str = ""
    """最高点时间戳。"""


@dataclass
class DrawdownGuardConfig:
    """回撤守卫配置"""
    enabled: bool = True
    """总开关，关闭时原样通过信号。"""

    warning_threshold: float = 0.08
    """警告阈值（8% 回撤），触发禁止新开仓。"""

    critical_threshold: float = 0.15
    """严重阈值（15% 回撤），触发清仓。"""

    recovery_threshold: float = 0.03
    """从高点的恢复比例（3%），清除断路器状态。"""

    cooldown_bars: int = 5
    """严重回撤后强制冷却 K 线数（期间禁止开新仓）。"""

    profit_peak_drawdown_threshold: float = 0.10
    """从利润高点的回撤阈值（10%），用于快速止盈。"""


@dataclass
class RiskEvent:
    """风控事件结构"""
    event_type: str = ""
    timestamp: str = ""
    severity: str = "low"
    description: str = ""
    value: float = 0.0
    threshold: float = 0.0


class DrawdownGuard:
    """回撤断路器。

    持续监控权益曲线，当回撤超过阈值时：
    - warning (8%): 禁止新开仓（仅允许平仓）
    - critical (15%): 强制清仓，冷却后恢复

    Examples:
        >>> guard = DrawdownGuard()
        >>> safe_signal = guard.update(current_equity=1_000_000, current_signal=1)
        >>> safe_signal  # 可以开仓
        1
        >>> state = guard.get_state()
        >>> state.breach_level
        'none'
    """

    def __init__(self, config: DrawdownGuardConfig | None = None):
        self.config = config or DrawdownGuardConfig()
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._breach_level: str = "none"
        self._cooldown_remaining: int = 0
        self._risk_events: List[RiskEvent] = []
        self._first_bar: bool = True
        self._peak_timestamp: str = ""

    def update(
        self,
        current_equity: float,
        timestamp: str = "",
        current_signal: int = 0,
    ) -> int:
        """更新回撤状态并返回安全信号。

        Args:
            current_equity: 当前权益。
            timestamp: 当前 bar 的时间戳。
            current_signal: 原始信号（-1/0/1）。

        Returns:
            int: 安全信号（可能被阻断或修改）。
        """
        if not self.config.enabled:
            return current_signal

        if self._first_bar:
            self._current_equity = current_equity
            self._peak_equity = current_equity
            self._peak_timestamp = timestamp
            self._first_bar = False
            return current_signal

        # 更新最高点
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
            self._peak_timestamp = timestamp
            # 如果从回撤中恢复超过 recovery_threshold，清除断路器
            dd = (self._peak_equity - current_equity) / max(self._peak_equity, 1e-10)
            if dd < self.config.recovery_threshold:
                prev = self._breach_level
                self._breach_level = "none"
                if prev != "none":
                    self._risk_events.append(RiskEvent(
                        event_type="drawdown_recovery",
                        timestamp=timestamp,
                        severity="low",
                        description=f"从 {prev} 级别回撤恢复",
                        value=float(dd),
                        threshold=self.config.recovery_threshold,
                    ))

        self._current_equity = current_equity

        # 计算当前回撤
        current_dd = (self._peak_equity - current_equity) / max(self._peak_equity, 1e-10)

        # 冷却计时
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        # 断路器判定
        signal = current_signal

        if current_dd >= self.config.critical_threshold and self._breach_level != "critical":
            self._breach_level = "critical"
            self._cooldown_remaining = self.config.cooldown_bars
            signal = -1  # 强制清仓
            self._risk_events.append(RiskEvent(
                event_type="drawdown_breach",
                timestamp=timestamp,
                severity="high",
                description=f"严重回撤 {current_dd:.2%}，触发清仓",
                value=float(current_dd),
                threshold=self.config.critical_threshold,
            ))

        elif current_dd >= self.config.warning_threshold and self._breach_level == "none":
            self._breach_level = "warning"
            # 只允许平仓（signal=-1）或持有（signal=0），不允许开新仓
            if signal == 1:
                signal = 0
            self._risk_events.append(RiskEvent(
                event_type="drawdown_breach",
                timestamp=timestamp,
                severity="medium",
                description=f"回撤预警 {current_dd:.2%}，禁止新开仓",
                value=float(current_dd),
                threshold=self.config.warning_threshold,
            ))

        elif self._breach_level == "warning" and self._cooldown_remaining > 0:
            # 冷却期: 只允许平仓
            if signal == 1:
                signal = 0

        elif self._breach_level == "warning" and current_dd < self.config.recovery_threshold:
            # 恢复后清除警告
            self._breach_level = "none"

        return signal

    def get_state(self) -> DrawdownState:
        """返回当前回撤守卫的快照状态。

        安全读取 _current_equity（首个 bar 之前可能未设置）。
        """
        current_eq = getattr(self, '_current_equity', 0.0)
        current_dd = (
            (self._peak_equity - current_eq) / max(self._peak_equity, 1e-10)
            if self._peak_equity > 0 else 0.0
        )
        return DrawdownState(
            peak_equity=self._peak_equity,
            current_drawdown=current_dd,
            breach_level=self._breach_level,
            cooldown_remaining=self._cooldown_remaining,
            peak_timestamp=self._peak_timestamp,
        )

    def get_risk_events(self) -> List[RiskEvent]:
        """返回累积的风控事件列表。"""
        return self._risk_events.copy()

    def reset(self) -> None:
        """重置为初始状态（用于多轮回测）。"""
        self._peak_equity = 0.0
        self._current_equity = 0.0
        self._breach_level = "none"
        self._cooldown_remaining = 0
        self._risk_events.clear()
        self._first_bar = True
        self._peak_timestamp = ""
