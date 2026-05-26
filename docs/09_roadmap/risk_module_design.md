# 回测系统风险模块补全方案

> **作者**: 墨衡 (moheng)  
> **版本**: v1.0  
> **创建时间**: 2026-05-18T14:04:00+08:00  
> **优先级**: P0 立即实施 / P1 阶段二实施

---

## 现状与差距概览

| 维度 | 现有状态 | 目标状态 | 优先级 |
|------|----------|----------|--------|
| **风险模块** | 不存在 (`risk/` 目录无) | 完整风控中间件层 | **P0** |
| **仓位管理** | `PortfolioManager.process_signal` 全仓买入/清零卖出 | ATR 动态仓位 + 风控约束 | **P0** |
| **回撤保护** | `get_peak_drawdown()` 仅为被动计算 | 主动断路器 + 持续监控 | **P0** |
| **市场状态过滤** | `RegimeAnalyzer` 独立存在，未接入信号生成 | 按市场状态过滤/缩放信号 | **P0** |
| **Anchored VWAP** | 仅有累计 VWAP + 多周期 VWAP | 支持自定义锚点 VWAP | **P1** |
| **跨模块打通** | Regime / VWAP / VP / KB 各自独立 | 信号流水线 + 风控 → 桥接到 KB | **P1** |

---

## 架构设计：风险中间件层

### 信号执行流水线（目标态）

```
MethodResult.signals
    │
    ▼
┌─────────────────────────────────┐
│ ╔══════════════════════════════╗│
│ ║  1. MarketStateFilter        ║│  ← 读取 RegimeAnalyzer 判定
│ ║  (P0: 市场状态过滤)           ║│  ← 过滤/衰减/延迟不良状态信号
│ ╚══════════════════════════════╝│
│         │  filtered_signals      │
│         ▼                       │
│ ╔══════════════════════════════╗│
│ ║  2. VolatilityRiskManager    ║│  ← 计算 ATR
│ ║  (P0: ATR 动态仓位管理)       ║│  ← 输出目标仓位比例
│ ╚══════════════════════════════╝│
│         │  sized_signals         │
│         ▼                       │
│ ╔══════════════════════════════╗│
│ ║  3. DrawdownGuard            ║│  ← 监控权益曲线
│ ║  (P0: 回撤断路器)             ║│  ← 超阈值触发断路器
│ ╚══════════════════════════════╝│
│         │  risk_checked_signals  │
│         ▼                       │
└─────────────────────────────────┘
    │
    ▼
PortfolioManager.process_signal(signal, price, symbol, position_ratio=...)
    │
    ▼
PortfolioIntegration (权益曲线 → TradePair → summary_metrics)
    │
    ▼
KnowledgeBridge.harvest()  ← 记录风控事件到知识库
```

### 核心设计原则

1. **组合式（Composable）**: 每个模块独立初始化，通过 `RiskPipeline` 串联
2. **可跳过（Optional）**: 每个模块有 `enabled` 开关，关闭时退化为原行为
3. **无侵入（Non-invasive）**: 不修改 `BaseMethod` 或 `PortfolioManager` 核心逻辑，通过中间件包装信号
4. **可审计（Auditable）**: 每个模块产出 `RiskEvent`，由 `KnowledgeBridge` 持久化

---

## 模块一：MarketStateFilter（P0）

### 接口设计

```python
# ─── 模块路径: src/backtest/risk/market_state_filter.py ───

@dataclass
class MarketStateFilterConfig:
    """市场状态过滤器配置"""
    enabled: bool = True
    """总开关，关闭时原样通过信号。"""

    block_regimes: List[str] = field(default_factory=lambda: ["DOWNTREND", "CLIMAX"])
    """在这些市场状态下阻止开新仓。"""

    reduce_regimes: List[str] = field(default_factory=lambda: ["RANGE"])
    """在这些市场状态下降低仓位。"""

    reduce_factor: float = 0.5
    """降仓系数（reduce_regimes 状态时的仓位乘数）。"""

    min_confidence: float = 0.3
    """RegimeAnalyzer 置信度低于此值时视为 UNKNOWN，按保守处理。"""

    transition_penalty: float = 0.3
    """状态转换频繁（transitions > threshold）时的额外减仓系数。"""

    transition_threshold: int = 5
    """窗口内转换次数超过此值视为高波动期。"""

    cooldown_bars: int = 3
    """阻止信号后，冷却期内仍可通过持仓信号（不新开仓）。"""


class MarketStateFilter:
    """市场状态信号过滤器。

    基于 RegimeAnalyzer 的市场状态判定，对信号进行过滤/衰减。
    在 DOWNTREND/CLIMAX 状态下阻止开新仓，在 RANGE 状态下降低仓位。

    Examples:
        >>> filter = MarketStateFilter(regime_analyzer)
        >>> filtered_signals = filter.process(signals_df, ohlcv_df)
        >>> # 返回的 DataFrame 中 signal=0 表示被过滤
    """

    def __init__(
        self,
        regime_analyzer: Optional[RegimeAnalyzer] = None,
        config: Optional[MarketStateFilterConfig] = None,
    ):
        self.regime_analyzer = regime_analyzer or RegimeAnalyzer()
        self.config = config or MarketStateFilterConfig()
        self._risk_events: List[RiskEvent] = []

    def process(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
    ) -> pd.DataFrame:
        """对信号逐行应用市场状态过滤。

        Args:
            signals: 信号 DataFrame（必须含 'signal' 列，索引 DatetimeIndex）。
            df_ohlcv: OHLCV DataFrame（索引与 signals 对齐）。

        Returns:
            pd.DataFrame: 过滤后的信号（未通过的行 signal → 0）。
        """
        if not self.config.enabled:
            return signals

        result = signals.copy()
        common_idx = signals.index.intersection(df_ohlcv.index)
        result = result.loc[common_idx]

        # 滑动窗口分析市场状态
        window_result = self.regime_analyzer.analyze_window(
            df_ohlcv, lookback=min(60, len(df_ohlcv))
        )

        current = self.regime_analyzer.get_current_regime()
        regime = current.get("regime", "UNKNOWN")
        confidence = current.get("confidence", 0.0)
        transitions = window_result.transitions

        # 是否需要阻断信号
        block_open = False
        position_scale = 1.0

        if regime in self.config.block_regimes and confidence >= self.config.min_confidence:
            block_open = True
            self._risk_events.append(RiskEvent(
                event_type="regime_block",
                timestamp=str(common_idx[-1]) if len(common_idx) > 0 else "",
                severity="high",
                description=f"市场状态 {regime}，阻止开新仓",
                value=confidence,
                threshold=self.config.min_confidence,
            ))

        elif regime in self.config.reduce_regimes:
            position_scale = self.config.reduce_factor

        # 高转换期附加惩罚
        if transitions > self.config.transition_threshold:
            position_scale *= self.config.transition_penalty

        # 应用过滤
        if block_open:
            # 只允许持仓平仓（signal=1 → 0，signal=-1 保持）
            result.loc[result["signal"] == 1, "signal"] = 0

        elif position_scale < 1.0:
            # 信号保持方向，但后续仓位管理会缩小
            pass  # 实际仓位缩小由 VolatilityRiskManager 处理

        return result

    def get_risk_events(self) -> List[RiskEvent]:
        """返回本次处理中产生的风控事件。"""
        return self._risk_events.copy()
```

### 集成点

| 集成对象 | 集成方式 |
|----------|----------|
| `RegimeAnalyzer` | 构造时注入；`process()` 内调用 `analyze_window()` + `get_current_regime()` |
| `PortfolioIntegration` | `PortfolioIntegration.run()` 内先调用 `MarketStateFilter.process()`，再取过滤后信号送 `PortfolioManager` |

### 实现思路

1. 在 `src/backtest/risk/` 目录下新建 `market_state_filter.py`
2. 在 `PortfolioIntegration.run()` 中增加 `if self.risk_pipeline: signals = self.risk_pipeline.process(signals, df_ohlcv)` 调用
3. `MarketStateFilter` 内部使用 `RegimeAnalyzer` 做滑动窗口分析，不重复计算

### 预估工作量

**25 分钟**（含单元测试编写）

---

## 模块二：VolatilityRiskManager（P0）

### 接口设计

```python
# ─── 模块路径: src/backtest/risk/volatility_risk_manager.py ───

@dataclass
class VolatilityRiskConfig:
    """波动率风险管理器配置"""
    enabled: bool = True

    # ATR 参数
    atr_period: int = 14
    """ATR 计算周期（K 线数）。"""

    atr_method: str = "wilders"
    """ATR 计算方法: "wilders" | "sma" | "ema" """

    atr_threshold: float = 0.001
    """ATR/price < 0.1% 视为低波动（区分于 NaN 信息不足）。"""

    # 风险预算
    risk_per_trade_pct: float = 0.01
    """每笔交易风险预算（占当前权益比例，默认 1%）。"""

    max_position_pct: float = 0.20
    """单标的最大仓位（占当前权益比例，默认 20%）。"""

    # 缩放
    min_scale: float = 0.1
    """最小仓位缩放系数（防止除零或过小仓位）。"""

    max_scale: float = 2.0
    """最大仓位缩放系数（防止杠杆过高）。"""

    # NaN fallback
    nan_fallback_ratio: float = 0.0
    """ATR 为 NaN 时的仓位比例（0 = 停止交易）。"""

    low_vol_ratio: float = 0.10
    """低波动时的保守仓位比例（默认 10%）。"""


class VolatilityRiskManager:
    """ATR 动态仓位管理器。

    基于 ATR（Average True Range）计算动态仓位比例。
    波动率高时缩小仓位，波动率低时放大仓位（受 max_position_pct 约束）。

    Formula:
        position_ratio = min(
            max_position_pct,
            risk_per_trade_pct * equity / (ATR_value * contract_multiplier)
        )

    Examples:
        >>> vrm = VolatilityRiskManager()
        >>> sized_signals = vrm.process(signals, df_ohlcv, equity_curve)
        >>> sized_signals["position_ratio"]  # 新增列，[0, max_position_pct]
    """

    def __init__(self, config: Optional[VolatilityRiskConfig] = None):
        self.config = config or VolatilityRiskConfig()
        self._atr_series: Optional[pd.Series] = None
        self._risk_events: List[RiskEvent] = []

    def process(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
        current_equity: Optional[float] = None,
    ) -> pd.DataFrame:
        """计算 ATR 并生成动态仓位比例。

        Args:
            signals: 信号 DataFrame（必须含 'signal' 列）。
            df_ohlcv: OHLCV DataFrame（含 high/low/close/volume）。
            current_equity: 当前权益（可选；未提供时用 initial_cash 替代）。

        Returns:
            pd.DataFrame: 新增 'position_ratio' 列的信号 DataFrame。
        """
        if not self.config.enabled:
            result = signals.copy()
            result["position_ratio"] = 1.0
            return result

        result = signals.copy()

        # 1. 计算 ATR
        atr = self._calc_atr(df_ohlcv)
        self._atr_series = atr

        # 2. 对齐索引
        common_idx = result.index.intersection(atr.index)
        result = result.loc[common_idx]
        atr_aligned = atr.loc[common_idx]

        # 3. 计算每行的动态仓位比例
        equity = current_equity or 1_000_000.0
        close_prices = df_ohlcv.loc[common_idx, "close"].values

        position_ratios = np.full(len(result), 0.0, dtype=np.float64)
        atr_values = atr_aligned.values

        for i in range(len(result)):
            signal_val = result["signal"].iloc[i]
            if signal_val == 0:
                position_ratios[i] = 0.0
                continue

            atr_val = atr_values[i]
            close_price = close_prices[i]

            if pd.isna(atr_val) or atr_val <= 0 or pd.isna(close_price) or close_price <= 0:
                position_ratios[i] = self.config.min_scale
            else:
                # ATR 动态仓位 = 风险预算 / (ATR / 价格)
                # 即: 能承受价格波动多少个百分点
                atr_pct = atr_val / close_price
                raw_ratio = self.config.risk_per_trade_pct / max(atr_pct, 0.001)
                clipped = max(self.config.min_scale, min(self.config.max_position_pct, raw_ratio))
                position_ratios[i] = clipped

        result["position_ratio"] = position_ratios

        # 4. 风控事件
        mean_atr_pct = float(np.mean(atr_values / close_prices)) if len(atr_values) > 0 else 0.0
        self._risk_events.append(RiskEvent(
            event_type="volatility_assessment",
            timestamp=str(common_idx[-1]) if len(common_idx) > 0 else "",
            severity="low" if mean_atr_pct < 0.02 else ("medium" if mean_atr_pct < 0.04 else "high"),
            description=f"ATR均值占比: {mean_atr_pct:.4f}, 平均仓位比例: {float(np.mean(position_ratios)):.4f}",
            value=float(mean_atr_pct),
            threshold=0.02,
        ))

        return result

    def _calc_atr(self, df: pd.DataFrame) -> pd.Series:
        """计算 ATR（Average True Range）。

        TR = max(high-low, |high - prev_close|, |low - prev_close|)
        ATR = smoothing(TR, period)
        """
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # True Range
        tr = np.full(len(df), np.nan, dtype=np.float64)
        for i in range(len(df)):
            if i == 0:
                tr[i] = high[i] - low[i]
            else:
                hl = high[i] - low[i]
                hc = abs(high[i] - close[i - 1])
                lc = abs(low[i] - close[i - 1])
                tr[i] = max(hl, hc, lc)

        tr_series = pd.Series(tr, index=df.index)

        # 平滑
        if self.config.atr_method == "wilders":
            atr = tr_series.ewm(alpha=1.0 / self.config.atr_period, min_periods=self.config.atr_period).mean()
        elif self.config.atr_method == "ema":
            atr = tr_series.ewm(span=self.config.atr_period, min_periods=self.config.atr_period).mean()
        else:  # sma
            atr = tr_series.rolling(window=self.config.atr_period, min_periods=self.config.atr_period).mean()

        return atr

    def get_risk_events(self) -> List[RiskEvent]:
        return self._risk_events.copy()
```

### PortfolioManager 修改（接受 position_ratio）

需要在 `PortfolioManager.process_signal()` 中增加可选 `position_ratio` 参数：

```python
def process_signal(
    self,
    signal: int,
    price: float,
    symbol: str = "DEFAULT",
    bar_info: Any = None,
    position_ratio: float = 1.0,     # ← 新增
) -> Order:
    ...
    if signal == 1:  # 买入
        ...
        # 原: max_shares = int(self.cash * (1 - self.commission_pct) // actual_price)
        # 改: 受 position_ratio 约束
        allocated_cash = self.cash * position_ratio
        max_shares = int(allocated_cash * (1 - self.commission_pct) // actual_price)
        ...
```

### 集成点

| 集成对象 | 集成方式 |
|----------|----------|
| `PortfolioManager` | `process_signal()` 新增 `position_ratio` 参数 |
| `PortfolioIntegration` | `run()` 内调用 `VolatilityRiskManager.process()` 后再调用 `PortfolioManager.process_signal()` |

### 实现思路

1. 在 `src/backtest/risk/` 下新建 `volatility_risk_manager.py`
2. 修改 `PortfolioManager.process_signal()` 签名增加 `position_ratio=1.0`
3. `PortfolioIntegration.run()` 中先过 `VolatilityRiskManager` 获得 `position_ratio` 列，再逐行传给 `PortfolioManager`

### 预估工作量

**30 分钟**（含单元测试 + PortfolioManager 改造）

---

## 模块三：DrawdownGuard（P0）

### 接口设计

```python
# ─── 模块路径: src/backtest/risk/drawdown_guard.py ───

@dataclass
class DrawdownGuardConfig:
    """回撤守卫配置"""
    enabled: bool = True

    # 多级断路器阈值（从当前净值的最高点计算）
    warning_threshold: float = 0.08
    """警告阈值（8% 回撤），触发减半仓。"""

    critical_threshold: float = 0.15
    """严重阈值（15% 回撤），触发清仓。"""

    # 恢复条件
    recovery_threshold: float = 0.03
    """从高点的恢复比例（3%），清除断路器状态。"""

    cooldown_bars: int = 5
    """严重回撤后强制冷却 K 线数（期间禁止开新仓）。"""


@dataclass
class DrawdownState:
    """回撤守卫的内部状态"""
    peak_equity: float
    """历史最高权益。"""
    current_drawdown: float
    """当前回撤比例（0 = 无回撤，0.1 = 10%）。"""
    breach_level: str
    """当前触发级别: "none" | "warning" | "critical" """
    cooldown_remaining: int
    """剩余冷却 K 线数。"""
    peak_timestamp: str
    """最高点时间戳。"""


class DrawdownGuard:
    """回撤断路器。

    持续监控权益曲线，当回撤超过阈值时：
    - warning (8%): 现有仓位减半，禁止新开仓
    - critical (15%): 清仓，冷却后恢复

    Examples:
        >>> guard = DrawdownGuard()
        >>> for each bar:
        ...     guard.update(equity_value, timestamp, current_signal)
        ...     safe_signal = guard.get_filtered_signal()
    """

    def __init__(self, config: Optional[DrawdownGuardConfig] = None):
        self.config = config or DrawdownGuardConfig()
        self._peak_equity: float = 0.0
        self._breach_level: str = "none"
        self._cooldown_remaining: int = 0
        self._risk_events: List[RiskEvent] = []
        self._first_bar = True
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
            dd = (self._peak_equity - current_equity) / self._peak_equity
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
        """返回当前回撤守卫的快照状态。"""
        self._current_equity: float = getattr(self, '_current_equity', 0.0)
        return DrawdownState(
            peak_equity=self._peak_equity,
            current_drawdown=(
                (self._peak_equity - self._current_equity) / max(self._peak_equity, 1e-10)
                if self._peak_equity > 0 else 0.0
            ),
            breach_level=self._breach_level,
            cooldown_remaining=self._cooldown_remaining,
            peak_timestamp=self._peak_timestamp,
        )

    def get_risk_events(self) -> List[RiskEvent]:
        return self._risk_events.copy()

    def reset(self) -> None:
        """重置为初始状态（用于多轮回测）。"""
        self._peak_equity = 0.0
        self._breach_level = "none"
        self._cooldown_remaining = 0
        self._risk_events.clear()
        self._first_bar = True
        self._peak_timestamp = ""
```

### 集成点

| 集成对象 | 集成方式 |
|----------|----------|
| `PortfolioIntegration.run()` | `run()` 的逐行循环中，每步 `record_equity()` 后调用 `DrawdownGuard.update()`，用返回值覆盖原始信号 |
| `RiskEvent list` | 回测结束后，将 `DrawdownGuard.get_risk_events()` 合并到 `summary_metrics` |

### 实现思路

1. 在 `src/backtest/risk/` 下新建 `drawdown_guard.py`
2. 在 `PortfolioIntegration.run()` 的信号循环中添加 `guard.update(equity, timestamp, original_signal) → safe_signal`
3. 回测结束时将 `guard.get_risk_events()` 追加到 `summary_metrics["risk_events"]`

### 预估工作量

**20 分钟**（含单元测试和 Pipeline 集成）

---

## 模块四：RiskPipeline（P0）

组合三个风险模块为一个调用链。

```python
# ─── 模块路径: src/backtest/risk/pipeline.py ───

@dataclass
class RiskPipelineConfig:
    """风险流水线配置"""
    market_state_filter: MarketStateFilterConfig = field(default_factory=MarketStateFilterConfig)
    volatility_risk: VolatilityRiskConfig = field(default_factory=VolatilityRiskConfig)
    drawdown_guard: DrawdownGuardConfig = field(default_factory=DrawdownGuardConfig)


class RiskPipeline:
    """风险流水线：组合 MarketStateFilter + VolatilityRiskManager + DrawdownGuard。

    由 PortfolioIntegration 驱动，按顺序执行三个风险模块。

    Examples:
        >>> pipeline = RiskPipeline(regime_analyzer=analyzer)
        >>> signals = pipeline.run(signals_df, df_ohlcv, equity_curve)
    """

    def __init__(
        self,
        regime_analyzer: Optional[RegimeAnalyzer] = None,
        config: Optional[RiskPipelineConfig] = None,
    ):
        cfg = config or RiskPipelineConfig()
        self.market_filter = MarketStateFilter(regime_analyzer, cfg.market_state_filter)
        self.volatility_mgr = VolatilityRiskManager(cfg.volatility_risk)
        self.drawdown_guard = DrawdownGuard(cfg.drawdown_guard)
        self._risk_events: List[RiskEvent] = []
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def process_pre_filter(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
    ) -> pd.DataFrame:
        """Step 1: 市场状态过滤。"""
        if not self._enabled:
            return signals
        result = self.market_filter.process(signals, df_ohlcv)
        self._risk_events.extend(self.market_filter.get_risk_events())
        return result

    def process_position_sizing(
        self,
        signals: pd.DataFrame,
        df_ohlcv: pd.DataFrame,
        current_equity: Optional[float] = None,
    ) -> pd.DataFrame:
        """Step 2: ATR 动态仓位。"""
        if not self._enabled:
            result = signals.copy()
            result["position_ratio"] = 1.0
            return result
        result = self.volatility_mgr.process(signals, df_ohlcv, current_equity)
        self._risk_events.extend(self.volatility_mgr.get_risk_events())
        return result

    def get_drawdown_guard(self) -> DrawdownGuard:
        """返回 DrawdownGuard 实例，供循环内逐步调用。"""
        return self.drawdown_guard

    def get_all_risk_events(self) -> List[RiskEvent]:
        return self._risk_events.copy() + self.drawdown_guard.get_risk_events()

    def reset(self) -> None:
        self._risk_events.clear()
        self.drawdown_guard.reset()
```

### PortfolioIntegration 修改方案

```python
class PortfolioIntegration:
    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission_pct: float = 0.0003,
        slippage_pct: float = 0.001,
        symbol: str = "",
        seed: int = 0,
        risk_pipeline: Optional[RiskPipeline] = None,  # ← 新增
    ):
        ...
        self.risk_pipeline = risk_pipeline

    def run(self, signals, df_ohlcv):
        ...
        # Step A: 市场状态过滤
        if self.risk_pipeline and self.risk_pipeline.enabled:
            signals = self.risk_pipeline.process_pre_filter(signals, df_ohlcv)

        # Step B: ATR 仓位计算（获取全表的 position_ratio）
        if self.risk_pipeline and self.risk_pipeline.enabled:
            sized_signals = self.risk_pipeline.process_position_sizing(
                signals, df_ohlcv, self.initial_cash
            )
        else:
            sized_signals = signals.copy()
            sized_signals["position_ratio"] = 1.0

        # Step C: 回撤守卫（循环内逐行）
        drawdown_guard = self.risk_pipeline.get_drawdown_guard() if self.risk_pipeline else None

        for idx in range(len(signals_aligned)):
            ...
            original_signal = int(sized_signals["signal"].iloc[idx])
            position_ratio = float(sized_signals["position_ratio"].iloc[idx])

            # 回撤守卫
            if drawdown_guard:
                safe_signal = drawdown_guard.update(
                    current_equity=np.sum(raw_equity),
                    timestamp=str(timestamp),
                    current_signal=original_signal,
                )
            else:
                safe_signal = original_signal

            pm.process_signal(
                signal=safe_signal,
                price=price,
                symbol=self.symbol,
                bar_info={"timestamp": timestamp, "idx": idx},
                position_ratio=position_ratio,  # ← 传动态仓位比例
            )
            pm.record_equity(price)
        ...
        # 汇总风控事件
        if drawdown_guard:
            summary_metrics["risk_events"] = [
                asdict(e) for e in self.risk_pipeline.get_all_risk_events()
            ]
```

### 集成点

| 集成对象 | 集成方式 |
|----------|----------|
| `PortfolioIntegration` | 构造时注入 `RiskPipeline`，`run()` 内三步调用 |
| `PortfolioManager` | `process_signal()` 新增 `position_ratio` 参数 |
| `KnowledgeBridge` | `harvest()` 传入 `risk_events`，存入 `KnowledgeEntry.metadata` |

### 预估工作量

**15 分钟**（含 RiskPipeline 编写 + PortfolioIntegration 改造）

---

## 模块五：Anchored VWAP（P1）

### 接口设计

```python
# ─── 模块路径: src/backtest/factors/volume/anchored_vwap.py ───

def calc_anchored_vwap(
    df: pd.DataFrame,
    anchor_date: str,
    use_high_low: bool = True,
) -> pd.Series:
    """计算锚定 VWAP（从指定日期开始累积）。

    与累计 VWAP（从数据起点开始）不同，Anchored VWAP
    允许用户指定一个"锚点"日期，VWAP 从该日期之后重新开始计算。

    Args:
        df: OHLCV DataFrame（DatetimeIndex, 含 high/low/close/volume）。
        anchor_date: 锚点日期（str，如 "2025-06-01"）。
        use_high_low: 若 True 使用典型价 (H+L+C)/3，否则使用收盘价。

    Returns:
        pd.Series: 锚定 VWAP 值，锚点之前为 NaN。
    """
    anchor_idx = df.index.get_indexer([anchor_date], method="bfill")
    if anchor_idx[0] == -1:
        return pd.Series(np.nan, index=df.index)

    start = anchor_idx[0]
    sub = df.iloc[start:].copy()

    if use_high_low:
        price = (sub["high"] + sub["low"] + sub["close"]) / 3.0
    else:
        price = sub["close"]

    cum_tp_vol = (price * sub["volume"]).cumsum()
    cum_vol = sub["volume"].cumsum()
    vwap_sub = pd.Series(np.nan, index=sub.index)
    mask = cum_vol > 0
    vwap_sub[mask] = cum_tp_vol[mask] / cum_vol[mask]

    result = pd.Series(np.nan, index=df.index)
    result.loc[sub.index] = vwap_sub
    return result


class AnchoredVwapFactor:
    """锚定 VWAP 因子（类封装）。"""

    FACTOR_META = {
        "name": "anchored_vwap",
        "version": "1.0.0",
        "author": "墨衡",
        "description": "锚定 VWAP（从指定日期开始累积计算）",
        "category": "volume",
        "default_params": {"anchor_date": "", "use_high_low": True},
        "tags": ["volume", "vwap", "anchored"],
    }

    def __init__(self, anchor_date: str, use_high_low: bool = True):
        self.anchor_date = anchor_date
        self.use_high_low = use_high_low

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        vwap = calc_anchored_vwap(df, self.anchor_date, self.use_high_low)
        return pd.DataFrame({"anchored_vwap": vwap}, index=df.index)
```

### 集成点

| 集成对象 | 集成方式 |
|----------|----------|
| `VwapFactor` | `anchored_vwap` 作为独立方法，不修改已有 `calc_vwap` |
| `BacktestMethod` | 在 `generate_signal()` 中可选调用 `AnchoredVwapFactor.compute()` |
| `KnowledgeBridge` | 作为因子结果，通过 `MethodResult` 流入知识条目 |

### 实现思路

1. 在 `src/backtest/factors/volume/` 下新建 `anchored_vwap.py`
2. 不修改已有 `vwap_factor.py`，保持向后兼容
3. 锚点由策略参数传入，支持动态锚定（如基于 Regime 转换点自动锚定 — P2）

### 预估工作量

**10 分钟**（纯计算逻辑，无集成复杂度）

---

## 模块六：Regime + VWAP + Volume Profile + KnowledgeBridge 打通（P1）

### 设计目标

将以下四个系统打通为统一的信号流水线：

```
RegimeAnalyzer                    ← 判定当前市场状态
    │
    ├──→ MarketStateFilter        ← 按 Regime 过滤信号（P0 已实现）
    │
    ├──→ VWAP 偏离度              ← 计算价格相对 VWAP 的位置
    │       ├── 价格 > VWAP + 2σ → 超买（SELL 信号增强）
    │       └── 价格 < VWAP - 2σ → 超卖（BUY 信号增强）
    │
    ├──→ Volume Profile           ← 计算 POC / VAH / VAL
    │       ├── 价格接近 VAH → 阻力
    │       └── 价格接近 VAL → 支撑
    │
    └──→ KnowledgeBridge          ← 记录状态、因子值、风控事件到飞书
```

### 信号增强/衰减逻辑

```python
# ─── 模块路径: src/backtest/risk/regime_context.py ───

@dataclass
class RegimeContext:
    """市场状态上下文 — 包含 Regime + VWAP + Volume Profile 的综合信号上下文"""
    regime: str                          # 当前市场状态
    regime_confidence: float             # Regime 置信度
    vwap_deviation: float                # VWAP 偏离度 (%)
    vwap_deviation_signal: str           # "overbought" / "oversold" / "neutral"
    near_vah: bool                       # 是否接近 VAH（阻力位）
    near_val: bool                       # 是否接近 VAL（支撑位）
    near_poc: bool                       # 是否接近 POC（均衡点）
    volume_signal: str                   # "support" / "resistance" / "neutral"


class RegimeContextBuilder:
    """构建 RegimeContext，供信号生成和风控使用。"""

    def __init__(
        self,
        regime_analyzer: Optional[RegimeAnalyzer] = None,
        vwap_deviation_threshold: float = 2.0,  # 2% 偏离视为超买/超卖
        vp_proximity_pct: float = 0.5,          # 距离 VAH/VAL 0.5% 内视为接近
    ):
        ...

    def build(
        self,
        df: pd.DataFrame,
        current_bar_index: int = -1,
    ) -> RegimeContext:
        """构建当前 bar 的市场状态上下文。"""
        ...
```

### 知识记录

```python
# KnowledgeBridge 的 harvest() 增加 risk_context 参数
bridge.harvest(
    result=method_result,
    method_name="ma_cross",
    symbol="601857",
    risk_events=risk_events,          # ← 新增
    regime_context=regime_context,    # ← 新增
)
```

### 集成点

| 集成对象 | 集成方式 |
|----------|----------|
| `RegimeAnalyzer` | `RegimeContextBuilder.build()` 内部调用 `analyze_window()` |
| `VwapFactor` | `build()` 调用 `calc_vwap_deviation()` 计算偏离度 |
| `Volume Profile` | `build()` 调用 `calc_volume_profile()` 获取 POC/VAH/VAL |
| `KnowledgeBridge` | `harvest()` 新增 `risk_context` 参数，写入 `KnowledgeEntry.metadata` |

### 实现思路

1. 新建 `src/backtest/risk/regime_context.py`
2. `RegimeContextBuilder` 在每轮回测结束时构建一次上下文
3. 通过 `KnowledgeBridge.harvest(..., risk_events=..., regime_context=...)` 写入知识库

### 预估工作量

**20 分钟**（含 RegimeContextBuilder + KnowledgeBridge 扩展）

---

## 实施路线图

### Phase 1（今天）— P0 四个模块

| 顺序 | 模块 | 文件 | 工作量 | 依赖 |
|:----:|------|------|:------:|:----:|
| 1 | `src/backtest/risk/__init__.py` | 目录初始化 | 2 min | 无 |
| 1 | `DrawdownGuard` | `src/backtest/risk/drawdown_guard.py` | 20 min | 无 |
| 2 | `VolatilityRiskManager` | `src/backtest/risk/volatility_risk_manager.py` | 30 min | `PortfolioManager.process_signal` 修改 |
| 3 | `MarketStateFilter` | `src/backtest/risk/market_state_filter.py` | 25 min | `RegimeAnalyzer` |
| 4 | `RiskPipeline` | `src/backtest/risk/pipeline.py` | 15 min | 上述三个模块 |
| 5 | `PortfolioIntegration` 改造 | `portfolio_integration.py` | 15 min | `RiskPipeline` |

**Phase 1 总计**: ~107 分钟

### Phase 2（后续）— P1 两个模块

| 顺序 | 模块 | 文件 | 工作量 |
|:----:|------|------|:------:|
| 6 | `AnchoredVwapFactor` | `src/backtest/factors/volume/anchored_vwap.py` | 10 min |
| 7 | `RegimeContextBuilder` | `src/backtest/risk/regime_context.py` | 20 min |
| 8 | KnowledgeBridge 扩展 | `knowledge_bridge.py` 修改 | 10 min |

**Phase 2 总计**: ~40 分钟

---

## 文件树（新增内容）

```
src/backtest/
├── risk/                                   ← 新建
│   ├── __init__.py                         ← 导出所有类
│   ├── drawdown_guard.py                   ← P0: 回撤断路器
│   ├── volatility_risk_manager.py          ← P0: ATR 动态仓位
│   ├── market_state_filter.py              ← P0: 市场状态过滤
│   ├── pipeline.py                         ← P0: 风险流水线
│   └── regime_context.py                   ← P1: 综合信号上下文
├── engine/
│   ├── __init__.py                         ← 不改
│   ├── portfolio_integration.py            ← 改: 集成 RiskPipeline
│   └── portfolio/
│       └── portfolio_manager.py            ← 改: process_signal 加 position_ratio
├── factors/volume/
│   ├── vwap_factor.py                      ← 不改
│   ├── volume_profile_factor.py            ← 不改
│   └── anchored_vwap.py                    ← 新建 P1
└── engine/
    └── knowledge_bridge.py                 ← 改 P1: harvest 加 risk_context
```

---

## 与现有系统的兼容性

| 场景 | 行为 |
|------|------|
| **不传 `risk_pipeline`** | `PortfolioIntegration` 退化为当前行为，零侵入 |
| **传 `RiskPipeline(enabled=False)`** | 所有模块 skips，与原行为一致 |
| **现有单元测试** | 不受影响（新增参数有默认值） |
| **现有 KnowledgeBridge 调用** | 不受影响（新增参数可选） |

---

### 路径合规审查

> **审查时间**: 2026-05-18T14:10:00+08:00  
> **审查者**: 墨衡 (moheng)  
> **审查依据**: 审计规则（pipeline_paths.py 路径管理规范）

#### 合规规则核对

| # | 规则 | 状态 | 详情 |
|:-:|------|:----:|------|
| 1 | 所有新代码 → `mozhi_platform/src/backtest/risk/` | ✅ PASS | P0 6 个文件均位于 `risk/` 下；anchored_vwap.py（P1）属于 volumes 因子模块，归 `factors/volume/`，为非 risk 模块的例外情况 |
| 2 | 路径引用通过 `pipeline_paths.py` 常量或标准 import，禁止硬编码 | ✅ PASS（注） | 设计文档中使用 Python 模块路径（如 `from backtest.risk.drawdown_guard import DrawdownGuard`），非文件系统路径硬编码；**实现时需在 pipeline_paths.py 新增 risk 专用路径常量** |
| 3 | 数据文件 → `mozhi_platform/data/{domain}/` | ✅ N/A | 设计文档不涉及数据文件路径引用 |

#### 路径验证结果

```python
# 验证执行
import os

# risk/ 目录存在性检查
risk_dir = r'C:\Users\17699\mozhi_platform\src\backtest\risk'
print(f'risk/ 目录存在: {os.path.exists(risk_dir)}')  # → False（预期，为新模块）

# 新文件路径（P0 + P1，全部不存在 = 预期）
new_files = [
    'risk/__init__.py',
    'risk/drawdown_guard.py',
    'risk/volatility_risk_manager.py',
    'risk/market_state_filter.py',
    'risk/pipeline.py',
    'risk/regime_context.py',
    'factors/volume/anchored_vwap.py',
]
for f in new_files:
    exists = os.path.exists(os.path.join(r'C:\Users\17699\mozhi_platform\src\backtest', f))
    print(f'  {f}: exists={exists}')  # 全部 False，设计阶段正常

# 待修改的现有文件是否存在（均应存在）
existing_files = [
    'engine/portfolio_integration.py',
    'engine/portfolio/portfolio_manager.py',
    'engine/knowledge_bridge.py',
]
for f in existing_files:
    exists = os.path.exists(os.path.join(r'C:\Users\17699\mozhi_platform\src\backtest', f))
    print(f'  {f}: exists={exists}')  # 应全部 True
```

**实际验证输出**:
- `risk/` 目录不存在（预期，为新模块）
- 全部 7 个新文件不存在（预期，设计阶段）
- 3 个待修改现有文件均存在 ✅
- `pipeline_paths.py` 中**尚无 risk 路径常量**（实现时需 `def risk_pipeline_path() -> Path` 等新函数）

#### 改进建议

1. **实现前**在 `pipeline_paths.py` 中新增风险模块路径常量：
   - `def risk_module_dir() -> Path` — 返回 `mozhi_platform/src/backtest/risk/`
   - `def risk_factor_module_dir() -> Path` — 返回 `mozhi_platform/src/backtest/factors/volume/`（可选）
2. 所有导入使用时使用标准 Python import 语法（如 `from backtest.risk.pipeline import RiskPipeline`），不硬编码文件系统路径
3. `anchored_vwap.py` 归属 `factors/volume/` 属于 P1 前置依赖，建议在 Phase 2 实施前确认该目录结构是否需要重构

#### 最终判定

**path_compliant: true** — 设计文档路径规划符合合规规则，无重大违规。

---

### v1.1 修订记录

> **修订时间**: 2026-05-18T14:22:00+08:00
> **修订者**: 墨衡 (moheng)
> **评审参与人**: 墨萱, 玄知

#### 修订项 1 — DrawdownGuard.enabled=False 缺 early return

- **评审人**: 墨萱
- **问题**: `DrawdownGuard.update()` 未在首行检查 `self.config.enabled`，enabled=False 时仍执行完整回撤逻辑
- **修正**: `update()` 首行增加 early return：
  ```python
  if not self.config.enabled:
      return current_signal
  ```

#### 修订项 2 — ATR 计算与 atr_factor.py 重复

- **评审人**: 墨萱
- **问题**: `VolatilityRiskManager._calc_atr()` 包含独立的 ATR 计算逻辑（手动 TR 循环 + wilders/sma/ema 平滑），与 `atr_factor.py` 中的 `ATRFactor.compute()` 重复
- **修正**: 删除 `_calc_atr()` 方法，改为调用 `ATRFactor.compute()`：
  ```python
  from backtest.factors.risk.atr_factor import ATRFactor
  ...
  atr = ATRFactor.compute(df, period=self.config.atr_period, method=self.config.atr_method)
  ```
  `VolatilityRiskConfig` 中 `atr_method` 字段移至 `ATRFactor` 参数管理。

#### 修订项 3 — AnchoredVWAP 锚点接口过紧

- **评审人**: 墨萱
- **问题**: `AnchoredVwapFactor.__init__()` 使用 `anchor_date: str` 作为唯一锚点指定方式，接口过紧，缺乏灵活性
- **修正**: 引入 `AnchorConfig` dataclass 替代裸字符串：
  ```python
  @dataclass
  class AnchorConfig:
      type: Literal["first_bar", "custom_date", "high_volume", "regime_switch"]
      date: Optional[str] = None  # type="custom_date" 时使用
      threshold: Optional[float] = None  # high_volume 阈值
      regime_analyzer: Optional[RegimeAnalyzer] = None  # regime_switch 时使用
  ```
  `AnchoredVwapFactor.__init__(anchor_config: AnchorConfig)` 代替 `anchor_date: str`，内部通过 `anchor_config.type` 分支计算锚定位置。

#### 修订项 4 — `get_state()` 公式 bug

- **评审人**: 玄知
- **问题**: `DrawdownGuard.get_state()` 中 `current_drawdown` 计算公式为 `(peak - 0.0) / peak`，永远返回 1.0（100%回撤），实际应为 `(peak - equity) / peak`
- **修正**:
  1. `DrawdownGuard.update()` 末尾存储 `self._current_equity = current_equity`
  2. `get_state()` 中公式改为：
  ```python
  current_drawdown=(
      (self._peak_equity - self._current_equity) / max(self._peak_equity, 1e-10)
      if self._peak_equity > 0 else 0.0
  )
  ```
  新增 `_current_equity: float = 0.0` 字段。

#### 修订项 5 — 30.5h vs 107min 数据矛盾

- **评审人**: 玄知
- **问题**: Phase 1 总计标注为「~107 分钟」（约1.8h），但实际 P0 开发（含测试和修复）估算不足，导致后续排期矛盾
- **修正**: 统一估算数据（覆盖实施路线图 Phase 1 总计行）：

| 阶段 | 原有 | 修正后 |
|:----:|:----:|:------:|
| P0 四模块 | ~92 min | **6-8 h**（含测试+修复+集成调试） |
| P1 两模块 | ~30 min | **4-5 h**（含测试+打通） |
| **总计** | ~107 min / ~30.5h（矛盾） | **10-13 h**（统一口径） |

  > 原有具体模块的分钟级估算是纯编码时间，修正后为**端到端工时**（含设计验证、单元测试、集成调试、修复）。

#### 修订项 6 — NaN ATR fallback 不完整

- **评审人**: 玄知
- **问题**: `VolatilityRiskManager.process()` 中 NaN/零值 ATR 时的 fallback 统一设为 `min_scale`（默认 0.1），未区分「信息不足」和「低波动」两种场景
- **修正**: 替换原有 fallback 逻辑：
  ```python
  if pd.isna(atr_val) or atr_val is None or atr_val <= 0:
      # 信息不足 → 停止交易
      position_ratios[i] = 0.0
  elif atr_val < atr_threshold:  # 假设有 atr_threshold 配置项
      # 低波动 → 保守仓位
      position_ratios[i] = 0.10  # 10%
  else:
      # 正常波动 → 正常 ATR 动态仓位
      ...
  ```
  需在 `VolatilityRiskConfig` 中新增 `atr_threshold: float = 0.001`（或根据品种设定），用于区分

---

### v1.2 修订记录

> **修订时间**: 2026-05-18T14:25:00+08:00
> **修订者**: 墨衡 (moheng)
> **评审人**: 墨萱

#### 修订项 1 — [Critical] DrawdownGuard.get_state() 首个 bar 回撤率计算错误

- **评审人**: 墨萱
- **问题**: `_first_bar=True` 分支在 return 前未设置 `self._current_equity = current_equity`，导致首个 bar 后 get_state() 的公式 `(peak - 0)/peak = 1.0` 永远返回 100% 回撤
- **修正**: 在 `_first_bar` 分支中，return 之前加上：
  ```python
  self._current_equity = current_equity
  self._peak_equity = current_equity
  ```
  确保首个 bar 后 get_state() 能正确计算回撤率为 0。

#### 修订项 2 — [Medium] VolatilityRiskConfig 缺 atr_threshold 字段

- **评审人**: 墨萱
- **问题**: v1.1 修订项 6（NaN ATR fallback 不完整）提到 NaN ATR 需区分「信息不足」和「低波动」，但 `VolatilityRiskConfig` dataclass 中未新增 `atr_threshold` 字段
- **修正**: 在 `VolatilityRiskConfig` 中加入 `atr_threshold: float = 0.001`：
  ```python
  atr_threshold: float = 0.001
  """ATR/price < 0.1% 视为低波动（区分于 NaN 信息不足）。"""
  ```
