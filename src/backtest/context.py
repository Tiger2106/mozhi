"""
mozhi_platform.src.backtest.context — 合约四件套之 StrategyContext / RuntimeState

======================================================================
StrategyContext:
  只读（frozen）上下文，承载回测/交易的环境配置。
  通过 get_config() 提供双层配置查找（config → global_config）。

RuntimeState:
  可变状态容器，承载运行时动态数据（现金/持仓/日志）。
======================================================================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ──────────────────────────────────────────────────────────────────────
# B9: StrategyContext frozen dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyContext:
    """策略上下文 — 合约四件套之三（不可变）。

    为 BaseMethod / BaseFactor 提供执行时所需的全部环境配置。
    实例化后不可修改（frozen=True）。
    """

    # ─── 标识 ──────────────────────────────────────────────────────

    symbol: str = ""
    """交易标的代码（如 "601857.SH"）。"""

    method_name: str = ""
    """当前执行的信号方法名称。"""

    # ─── 标的规则 ─────────────────────────────────────────────────

    tick_size: float = 0.01
    """最小价格变动单位（tick）。"""

    lot_size: int = 100
    """每手股数。"""

    # ─── 回测配置 ─────────────────────────────────────────────────

    config: Dict[str, Any] = field(default_factory=dict)
    """方法级本地配置（优先级高）。"""

    global_config: Dict[str, Any] = field(default_factory=dict)
    """全局配置（优先级低，B11 双层查找后备）。"""

    initial_cash: float = 1_000_000.0
    """初始资金。"""

    benchmark: str = "000300.SH"
    """基准标的代码（用于超额收益计算）。"""

    data_frequency: str = "daily"
    """数据频率 ("daily" / "minute")。"""

    date_range: Optional[tuple[str, str]] = None
    """回测日期范围 (start_date, end_date)，如 ("2020-01-01", "2025-12-31")。"""

    verbose: bool = False
    """是否输出详细日志。"""

    debug_mode: bool = False
    """是否启用调试模式（输出额外诊断信息）。"""

    # ─── 预留字段 ─────────────────────────────────────────────────

    meta: Dict[str, Any] = field(default_factory=dict)
    """扩展元数据（预留，可自定义挂载任意信息）。"""

    # ─── 运行时引用（非 frozen 对象，通过 getter 访问） ───────────

    runtime: "RuntimeState" = field(default_factory=lambda: RuntimeState())
    """运行时可变状态引用。本身是可变对象，与 frozen 约束不冲突。"""

    # ─── B11: get_config() 双层查找 ────────────────────────────────

    def get_config(self, key: str, default: Any = None) -> Any:
        """双层配置查找：优先方法级 config，后备 global_config。

        Args:
            key: 配置键名。
            default: 两层均未找到时返回的默认值。

        Returns:
            配置值（若存在）或 default。
        """
        if key in self.config:
            return self.config[key]
        return self.global_config.get(key, default)

    # ─── B12: get_logger() 懒加载 ──────────────────────────────────

    def get_logger(self) -> logging.Logger:
        """获取当前方法名对应的 logger（懒加载）。

        首次调用时创建，后续复用 RuntimeState 中缓存的实例。

        Returns:
            配置好的 logging.Logger 实例。
        """
        logger = self.runtime.logger
        if logger is None:
            logger = logging.getLogger(
                f"mozhi.backtest.{self.method_name or 'unknown'}"
            )
            self.runtime.logger = logger
        return logger


# ──────────────────────────────────────────────────────────────────────
# B10: RuntimeState mutable dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass
class RuntimeState:
    """运行时可变状态 — 合约四件套之四（可变）。

    承载每次回测执行过程中动态变化的状态。

    ⚠️  非 frozen：字段可直接修改。
    """

    current_cash: Optional[float] = None
    """当前可用现金（初始为 initial_cash 的副本）。"""

    positions: Optional[Dict[str, float]] = None
    """当前持仓字典 {symbol: quantity}。"""

    logger: Optional[logging.Logger] = None
    """缓存的 logger 实例（由 lazy-init 填充，B12）。"""
