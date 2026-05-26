"""
墨枢 - P2-01 / P2-02 趋势策略

P2-01 TrendStrategy 基类
    - 继承 SignalStrategy，内嵌 SignalBridge
    - 参数化配置（ma_fast / ma_slow / stop_loss / take_profit 等）
    - 可序列化的 params 接口

P2-02 MA 金叉死叉信号
    - generate_signals(bars) → 信号 DataFrame
    - MA(ma_fast) 上穿 MA(ma_slow) → BUY (signal=1)
    - MA(ma_fast) 下穿 MA(ma_slow) → SELL (signal=-1)
    - 基于内置 Bar.close 计算简单移动平均 (SMA)

用法::

    from backtest.strategies import TrendStrategy

    strategy = TrendStrategy(ma_fast=5, ma_slow=20, stop_loss=0.05)
    signals = strategy.generate_signals(bars)
    strategy.bridge.load_signals(signals)

    result = engine.run(bars)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from backtest.backtest_engine import Bar
from backtest.signal_bridge import SignalStrategy, SignalBridgeConfig
from src.signals.signal_protocol_v1 import Signal

# 时区
_TZ_CN = timezone(timedelta(hours=8))

# P2-05: 趋势因子计算器
from backtest.strategies.factor_calculator import compute_trend_score


# ============================================================
# P2-01: 趋势策略基类
# ============================================================


class TrendStrategy(SignalStrategy):
    """
    趋势策略基类（P2-01）。

    继承自 SignalStrategy，增加趋势策略专有参数：
      - ma_fast / ma_slow: 快慢均线周期
      - stop_loss / take_profit: 止损止盈比例（正值）
      - signal_type: 信号模式（"crossover" = 金叉死叉）

    生成信号：通过 generate_signals() 产生，然后由 SignalBridge
    将信号转换为 OrderRequest。也可在子类中覆写 on_bar() 实现
    更复杂的多过滤逻辑。
    """

    def __init__(
        self,
        ma_fast: int = 5,
        ma_slow: int = 20,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        signal_type: str = "crossover",
        bridge_config: Optional[SignalBridgeConfig] = None,
    ):
        """
        参数
        ----------
        ma_fast : int
            快线周期（默认 5）。
        ma_slow : int
            慢线周期（默认 20）。
        stop_loss : float, optional
            止损比例，如 0.05 表示 -5% 止损（相对于开仓均价）。
        take_profit : float, optional
            止盈比例，如 0.10 表示 +10% 止盈。
        signal_type : str
            信号类型。当前支持 "crossover"（金叉死叉）。
        bridge_config : SignalBridgeConfig, optional
            SignalBridge 配置。
        """
        super().__init__(bridge_config=bridge_config)

        # ── 有效性校验 ──────────────────────────────────────
        if ma_fast >= ma_slow:
            raise ValueError(
                f"ma_fast ({ma_fast}) 必须小于 ma_slow ({ma_slow})"
            )
        if stop_loss is not None and not (0 < stop_loss < 1):
            raise ValueError(f"stop_loss 应在 (0, 1) 区间，收到 {stop_loss}")
        if take_profit is not None and not (0 < take_profit < 1):
            raise ValueError(f"take_profit 应在 (0, 1) 区间，收到 {take_profit}")

        self.ma_fast = ma_fast
        self.ma_slow = ma_slow
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.signal_type = signal_type

    # ═══════════════════════════════════════════════════════════
    # 参数配置接口（可序列化保存）
    # ═══════════════════════════════════════════════════════════

    @property
    def params(self) -> Dict[str, Any]:
        """
        返回当前策略参数的字典，可用于序列化（JSON / Feishu Bitable 等）。

        返回值示例::

            {
                "ma_fast": 5,
                "ma_slow": 20,
                "stop_loss": 0.05,
                "take_profit": 0.10,
                "signal_type": "crossover",
            }
        """
        return {
            "ma_fast": self.ma_fast,
            "ma_slow": self.ma_slow,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "signal_type": self.signal_type,
        }

    def set_params(self, **kwargs) -> None:
        """
        批量更新策略参数，并做有效性校验。

        用法::

            strategy.set_params(ma_fast=10, stop_loss=0.03)
        """
        valid_keys = {"ma_fast", "ma_slow", "stop_loss", "take_profit", "signal_type"}

        for key, value in kwargs.items():
            if key not in valid_keys:
                raise KeyError(f"未知参数: {key}，有效参数: {valid_keys}")

            # 校验具体值
            if key in ("ma_fast", "ma_slow"):
                if not isinstance(value, int) or value <= 0:
                    raise ValueError(f"{key} 必须为正整数")
            elif key in ("stop_loss", "take_profit"):
                if value is not None and not (0 < value < 1):
                    raise ValueError(f"{key} 应在 (0, 1) 区间")
            setattr(self, key, value)

        # 重新校验快慢线关系
        if self.ma_fast >= self.ma_slow:
            raise ValueError(
                f"更新后 ma_fast ({self.ma_fast}) 必须小于 ma_slow ({self.ma_slow})"
            )

    # ═══════════════════════════════════════════════════════════
    # on_bar — 整合止损止盈（可选）
    # ═══════════════════════════════════════════════════════════

    def on_bar(
        self, context: Any, bar: Bar
    ) -> Optional[List[Signal]]:
        """
        对 on_bar 的增强：
        1. 如果启用了 stop_loss / take_profit，先检查持仓是否需要平仓
        2. 再调用父类 SignalStrategy.on_bar 处理信号
        3. 产出 Signal Protocol v1 统一信号

        子类覆写时记得调用 super().on_bar() 或自行实现止损逻辑。
        """
        signals: List[Signal] = []

        def _make_signal(direction: str, quantity: int) -> Signal:
            return Signal(
                signal_id=str(uuid.uuid4()),
                symbol=bar.symbol,
                direction=direction,
                confidence=1.0,
                horizon="short",
                signal_type="trend",
                timestamp=datetime.now(_TZ_CN),
                protocol_version="1.0",
                extras={"quantity": quantity},
            )

        # ── 止损止盈检查 ──────────────────────────────────
        if (self.stop_loss or self.take_profit) and context.positions.has_position(
            bar.symbol
        ):
            pos = context.positions.get(bar.symbol)
            avg_price = pos.avg_price
            pnl_pct = (bar.close - avg_price) / avg_price

            if self.stop_loss and pnl_pct <= -self.stop_loss:
                signals.append(_make_signal("SELL", pos.quantity))
                return signals if signals else None

            if self.take_profit and pnl_pct >= self.take_profit:
                signals.append(_make_signal("SELL", pos.quantity))
                return signals if signals else None

        # ── 正常信号处理 ──────────────────────────────────
        parent_signals = super().on_bar(context, bar)
        if parent_signals:
            signals.extend(parent_signals)

        return signals if signals else None


# ============================================================
# P2-02: MA 金叉死叉信号生成
# ============================================================


# ============================================================
# P2-03: MACD 信号生成
# ============================================================


# ============================================================
# ⚠️ DEPRECATED (2026-05-24): 已由 src.core.ema_nan_safe 的 ema_nan_safe()
# 统一替代。保留仅用于兼容旧代码，新代码应直接使用 ema_nan_safe。
# _ema_py_naive (trend_strategy._ema) — 保留期至下个大版本清理
# ============================================================
def _ema(values: List[float], period: int) -> List[Optional[float]]:
    """
    指数移动平均（纯 Python 实现，带NaN隔离防护）。

    公式:
      alpha = 2 / (period + 1)
      EMA(0) = SMA(period)  # 初始值用简单均值
      EMA(t) = alpha * price(t) + (1 - alpha) * EMA(t-1)
    """
    from src.core.ema_nan_safe import ema_nan_safe
    return ema_nan_safe(values, period, min_periods=period, use_pandas=False)


def generate_macd_signals(
    bars: List[Bar],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> List[Dict[str, Any]]:
    """
    基于 MACD 金叉/死叉生成信号列表（纯 Python 实现）。

    MACD 计算:
      DIF = EMA(close, fast_period) - EMA(close, slow_period)
      DEA = EMA(DIF, signal_period)
      MACD 柱 = (DIF - DEA) * 2

    信号规则:
      - DIF 上穿 DEA → BUY  (signal=1)
      - DIF 下穿 DEA → SELL (signal=-1)

    参数
    ----------
    fast_period : int
        MACD 快线周期（默认 12）。
    slow_period : int
        MACD 慢线周期（默认 26）。
    signal_period : int
        MACD 信号线周期（默认 9）。

    返回
    -------
    List[Dict[str, Any]]
        每条记录含: date / symbol / signal / dif / dea / macd_hist
        signal: 1=BUY, -1=SELL, 0=无操作
    """
    if not bars:
        return []

    closes = [b.close for b in bars]
    n = len(bars)

    # ── 1. 计算两条 EMA ─────────────────────────────
    ema_fast = _ema(closes, fast_period)
    ema_slow = _ema(closes, slow_period)

    # ── 2. 计算 DIF ──────────────────────────────────
    dif: List[Optional[float]] = [None] * n
    dif_start = max(fast_period, slow_period) - 1
    for i in range(dif_start, n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif[i] = ema_fast[i] - ema_slow[i]

    # ── 3. 计算 DEA（对有效 DIF 序列做 EMA）──────────
    valid_dif_values: List[float] = []
    valid_dif_indices: List[int] = []
    for i in range(n):
        if dif[i] is not None:
            valid_dif_values.append(dif[i])
            valid_dif_indices.append(i)

    if not valid_dif_values:
        return [_empty_record(b) for b in bars]

    dea_raw = _ema(valid_dif_values, signal_period)

    # ── 4. 重建完整长度 DEA ─────────────────────────
    dea: List[Optional[float]] = [None] * n
    dea_first_valid = None
    for j, idx in enumerate(valid_dif_indices):
        dea[idx] = dea_raw[j]
        if dea_raw[j] is not None and dea_first_valid is None:
            dea_first_valid = idx

    # dea 有效起始 = DEA 首次非空索引
    first_valid_idx = dea_first_valid if dea_first_valid is not None else n
    if first_valid_idx >= n:
        return [_empty_record(b) for b in bars]

    # ── 5. 遍历检测 DIF / DEA 交叉 ──────────────────
    prev_state = 0
    signals: List[Dict[str, Any]] = []

    for i in range(n):
        cur_dif = dif[i]
        cur_dea = dea[i]

        if cur_dif is None or cur_dea is None:
            signal = 0
        else:
            cur_state = 1 if cur_dif > cur_dea else (-1 if cur_dif < cur_dea else 0)
            if cur_state == 1 and prev_state == -1:
                signal = 1   # DIF 上穿 DEA → BUY
            elif cur_state == -1 and prev_state == 1:
                signal = -1  # DIF 下穿 DEA → SELL
            else:
                signal = 0
            prev_state = cur_state

        macd_hist = (cur_dif - cur_dea) * 2 if (cur_dif is not None and cur_dea is not None) else None

        signals.append({
            "date": bars[i].date,
            "symbol": bars[i].symbol,
            "signal": signal,
            "dif": cur_dif,
            "dea": cur_dea,
            "macd_hist": macd_hist,
        })

    return signals


# ============================================================
# P2-04: 布林带突破信号生成
# ============================================================


def _rolling_stddev(values: List[float], period: int) -> List[Optional[float]]:
    """
    滚动标准差（总体标准差 ddof=0）。
    """
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result

    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        mean = sum(window) / period
        variance = sum((v - mean) ** 2 for v in window) / period
        result[i] = variance ** 0.5

    return result


def generate_bollinger_signals(
    bars: List[Bar],
    period: int = 20,
    std_dev: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    基于布林带突破生成信号列表（纯 Python 实现）。

    布林带计算:
      MIDDLE = SMA(close, period)
      STD    = 滚动标准差(close, period)
      UPPER  = MIDDLE + std_dev * STD
      LOWER  = MIDDLE - std_dev * STD

    信号规则（Breakout 策略）:
      - 价格上穿上轨 → BUY  (signal=1)  — 向上突破追涨
      - 价格下穿下轨 → SELL (signal=-1) — 向下突破追跌
      - 价格回归中轨 → 平仓
        * 从中轨下方回到中轨 → BUY (signal=1)  — 平空仓
        * 从中轨上方回到中轨 → SELL (signal=-1) — 平多仓

    参数
    ----------
    period : int
        布林带周期（默认 20）。
    std_dev : float
        标准差倍数（默认 2.0）。

    返回
    -------
    List[Dict[str, Any]]
        每条记录含: date / symbol / signal / upper / middle / lower / bandwidth
        signal: 1=BUY, -1=SELL, 0=无操作
    """
    if not bars:
        return []

    closes = [b.close for b in bars]
    n = len(bars)

    # ── 1. 计算中轨（SMA）和标准差 ──────────────────
    middle = _sma(closes, period)        # 中轨
    std = _rolling_stddev(closes, period)  # 滚动标准差

    # ── 2. 计算上下轨 ───────────────────────────────
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n
    for i in range(n):
        if middle[i] is not None and std[i] is not None:
            upper[i] = middle[i] + std_dev * std[i]
            lower[i] = middle[i] - std_dev * std[i]

    # ── 3. 检测突破 / 回归 ──────────────────────────
    first_valid = period - 1
    if first_valid >= n:
        return [_empty_record(b) for b in bars]

    # prev_zone: 1=price>upper, 0=price in bands, -1=price<lower
    prev_close = closes[first_valid]
    prev_upper = upper[first_valid]
    prev_lower = lower[first_valid]
    if prev_upper is not None and prev_close > prev_upper:
        prev_zone = 1
    elif prev_lower is not None and prev_close < prev_lower:
        prev_zone = -1
    else:
        prev_zone = 0

    signals: List[Dict[str, Any]] = []

    for i in range(first_valid):
        signals.append({
            "date": bars[i].date,
            "symbol": bars[i].symbol,
            "signal": 0,
            "upper": upper[i],
            "middle": middle[i],
            "lower": lower[i],
            "bandwidth": (
                (upper[i] - lower[i]) / middle[i]
                if (upper[i] is not None and lower[i] is not None and middle[i] is not None and middle[i] != 0)
                else None
            ),
        })

    for i in range(first_valid, n):
        cur_close = closes[i]
        cur_upper = upper[i]
        cur_lower = lower[i]

        # 确定当前价格所在的区域
        if cur_upper is not None and cur_close > cur_upper:
            cur_zone = 1
        elif cur_lower is not None and cur_close < cur_lower:
            cur_zone = -1
        else:
            cur_zone = 0

        # 检测转换事件
        if prev_zone == 0 and cur_zone == 1:
            signal = 1   # 上穿上轨 → BUY
        elif prev_zone == 0 and cur_zone == -1:
            signal = -1  # 下穿下轨 → SELL
        elif prev_zone == 1 and cur_zone == 0:
            signal = -1  # 从上轨回归中轨 → 平多（SELL）
        elif prev_zone == -1 and cur_zone == 0:
            signal = 1   # 从下轨回归中轨 → 平空（BUY）
        else:
            signal = 0   # 无显著转换

        prev_zone = cur_zone

        bandwidth = (
            (upper[i] - lower[i]) / middle[i]
            if (upper[i] is not None and lower[i] is not None and middle[i] is not None and middle[i] != 0)
            else None
        )

        signals.append({
            "date": bars[i].date,
            "symbol": bars[i].symbol,
            "signal": signal,
            "upper": cur_upper,
            "middle": middle[i],
            "lower": cur_lower,
            "bandwidth": bandwidth,
        })

    return signals


# ============================================================
# 内部辅助
# ============================================================


def _empty_record(bar: Bar) -> Dict[str, Any]:
    """返回一个空的信号记录（数据不足时的占位）。"""
    return {
        "date": bar.date,
        "symbol": bar.symbol,
        "signal": 0,
        "dif": None,
        "dea": None,
        "macd_hist": None,
    }


def _sma(values: List[float], period: int) -> List[Optional[float]]:
    """
    简单移动平均。

    对输入价格列表逐元素计算 SMA(period)。
    前 period-1 个元素为 None（数据不足），period 开始有值。
    """
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result

    window_sum = sum(values[:period])
    result[period - 1] = window_sum / period

    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        result[i] = window_sum / period

    return result


def generate_ma_cross_signals(
    bars: List[Bar],
    ma_fast: int = 5,
    ma_slow: int = 20,
) -> List[Dict[str, Any]]:
    """
    基于 MA 金叉/死叉生成信号列表（纯 Python 实现，无外部依赖）。

    参数
    ----------
    bars : List[Bar]
        按时间升序排列的 K 线列表。
    ma_fast : int
        快线周期（默认 5）。
    ma_slow : int
        慢线周期（默认 20）。

    返回
    -------
    List[Dict[str, Any]]
        每条记录含 date / symbol / signal / ma_fast_val / ma_slow_val。

        信号取值:
          - 1   = BUY  （金叉：MA_fast 上穿 MA_slow）
          - -1  = SELL （死叉：MA_fast 下穿 MA_slow）
          - 0   = 无操作

    注：信号只在 cross 发生的瞬间生成（不是每 Bar 都有信号）。
    """
    if not bars:
        return []

    closes = [b.close for b in bars]

    # 计算两条 MA
    fast_ma = _sma(closes, ma_fast)
    slow_ma = _sma(closes, ma_slow)

    # 第一个有效 MA 位置
    first_valid = max(ma_fast, ma_slow) - 1
    if first_valid >= len(bars):
        return []

    # 初始状态：取 first_valid 位置的快慢线相对位置
    prev_fast = fast_ma[first_valid]
    prev_slow = slow_ma[first_valid]
    if prev_fast is None or prev_slow is None:
        prev_state = 0
    else:
        prev_state = 1 if prev_fast > prev_slow else (-1 if prev_fast < prev_slow else 0)

    signals: List[Dict[str, Any]] = []

    # ── 前 first_valid 条 Bar 没有完整 MA，标记为 0 ──
    for i in range(first_valid):
        signals.append(
            {
                "date": bars[i].date,
                "symbol": bars[i].symbol,
                "signal": 0,
                "ma_fast_val": fast_ma[i],
                "ma_slow_val": slow_ma[i],
            }
        )

    # ── 从 first_valid 开始检测交叉 ──────────────────────
    for i in range(first_valid, len(bars)):
        cur_fast = fast_ma[i]
        cur_slow = slow_ma[i]

        if cur_fast is None or cur_slow is None:
            signal = 0
        else:
            cur_state = 1 if cur_fast > cur_slow else (-1 if cur_fast < cur_slow else 0)

            if cur_state == 1 and prev_state == -1:
                signal = 1  # 金叉 → BUY
            elif cur_state == -1 and prev_state == 1:
                signal = -1  # 死叉 → SELL
            else:
                signal = 0

            prev_state = cur_state

        signals.append(
            {
                "date": bars[i].date,
                "symbol": bars[i].symbol,
                "signal": signal,
                "ma_fast_val": cur_fast,
                "ma_slow_val": cur_slow,
            }
        )

    return signals


def _build_signal_df(signal_records: List[Dict[str, Any]]) -> "DataFrame":
    """
    将信号记录列表转换为 pandas DataFrame（按需导入，非强制依赖）。
    """
    try:
        import pandas as pd

        return pd.DataFrame(signal_records)
    except ImportError:
        # 降级：无 pandas 环境返回简单包装
        import json

        class _Df:
            def __init__(self, records):
                self._records = records
                self.columns = list(records[0].keys()) if records else []

            def __repr__(self):
                return f"<SignalDataFrame {len(self._records)} rows>"

            def to_dict(self):
                return {"records": self._records, "columns": self.columns}

        return _Df(signal_records)


def _generate_signals(
    self: TrendStrategy, bars: List[Bar]
) -> "DataFrame":
    """
    P2-02: 基于 MA 金叉/死叉生成信号 DataFrame。

    输出格式兼容 SignalBridge.load_signals() 期望的 DataFrame：
      - 列: ['date', 'symbol', 'signal', 'ma_fast_val', 'ma_slow_val']
      - signal: 1=BUY, -1=SELL, 0=无操作

    用法::

        strategy = TrendStrategy(ma_fast=5, ma_slow=20)
        signals = strategy.generate_signals(bars)
        strategy.bridge.load_signals(signals)

    Bar 列表按日期升序排列，Engine 内部自动排序。
    """
    records = generate_ma_cross_signals(
        bars=bars,
        ma_fast=self.ma_fast,
        ma_slow=self.ma_slow,
    )
    return _build_signal_df(records)


# 将 generate_signals 绑定为 TrendStrategy 的实例方法
TrendStrategy.generate_signals = _generate_signals


# ============================================================
# P2-05: 趋势强度过滤
# ============================================================

# 默认趋势评分阈值（[0, 1] 区间，低于此值视为弱趋势/盘整）
DEFAULT_TREND_THRESHOLD = 0.35

# 默认权重配置（因子权重）
DEFAULT_TREND_WEIGHTS = {
    "adx": 0.5,
    "ma_slope": 0.3,
    "vol_ratio": 0.2,
}


def generate_trend_score_signals(
    bars: List[Bar],
    threshold: float = DEFAULT_TREND_THRESHOLD,
    adx_period: int = 14,
    ma_period: int = 20,
    slope_period: int = 5,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    综合趋势强度评分及信号过滤（P2-05）。

    流程：
      1. 调用 factor_calculator.compute_trend_score 获取各因子和综合评分
      2. composite_score < threshold → 标记为弱趋势，signal=0（不交易）
      3. composite_score >= threshold → 根据趋势方向发信号

    参数
    ----------
    bars : List[Bar]
        按时间升序的 K 线列表。
    threshold : float
        趋势评分阈值（默认 0.35）。低于此值视为盘整/弱趋势。
    adx_period : int
        ADX 计算周期（默认 14）。
    ma_period : int
        均线周期（默认 20）。
    slope_period : int
        斜率计算窗口（默认 5）。
    weights : dict, optional
        因子权重，见 factor_calculator.compute_trend_score。

    返回
    -------
    List[Dict[str, Any]]
        每条记录含:
          - date / symbol
          - signal: 1=BUY（上升趋势）, -1=SELL（下降趋势）, 0=无操作
          - composite_score: 综合评分
          - adx / ma_slope / vol_ratio: 原始因子值
          - filtered: True 表示被评分过滤
    """
    if not bars:
        return []

    # ── 1. 计算趋势评分 ──────────────────────────────
    scores = compute_trend_score(
        bars=bars,
        adx_period=adx_period,
        ma_period=ma_period,
        slope_period=slope_period,
        weights=weights or DEFAULT_TREND_WEIGHTS,
    )

    # ── 2. 根据评分和方向生成信号 ────────────────────
    signals: List[Dict[str, Any]] = []

    for i, bar in enumerate(bars):
        if i >= len(scores):
            signals.append({
                "date": bar.date,
                "symbol": bar.symbol,
                "signal": 0,
                "composite_score": None,
                "adx": None,
                "ma_slope": None,
                "vol_ratio": None,
                "filtered": True,
            })
            continue

        sc = scores[i]
        composite = sc["composite_score"]

        if composite < threshold:
            # 弱趋势 → 过滤，不交易
            signal = 0
            filtered = True
        else:
            # 强趋势 → 按方向发信号
            direction = sc["trend_direction"]
            signal = 1 if direction == 1 else (-1 if direction == -1 else 0)
            filtered = False

        signals.append({
            "date": bar.date,
            "symbol": bar.symbol,
            "signal": signal,
            "composite_score": composite,
            "adx": sc["adx"],
            "ma_slope": sc["ma_slope"],
            "vol_ratio": sc["vol_ratio"],
            "filtered": filtered,
        })

    return signals


# ============================================================
# P2-06: 多信号投票机制
# ============================================================


_DEFAULT_WEIGHTS = {"ma": 1.0, "macd": 1.0, "bollinger": 1.0}


def _normalize_signal(s: int) -> int:
    """归一化信号值：正值→1，负值→-1，0→0。"""
    if s > 0:
        return 1
    if s < 0:
        return -1
    return 0


def compute_voted_signal(
    signals_list: List[List[Dict[str, Any]]],
    min_votes: int = 2,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    多信号投票机制（P2-06）。

    对 N 个独立信号（MA / MACD / 布林带 / 趋势评分）进行投票，
    只有当至少 min_votes 个信号方向一致时才发单。

    支持加权投票：不同信号的投票权重可配置，最终按加权和判决。

    参数
    ----------
    signals_list : List[List[Dict[str, Any]]]
        N 个信号列表，每个列表长度相同且按相同时间顺序排列。
        每个信号记录必须含 "signal" 字段（1=B, -1=S, 0=无操作）。
    min_votes : int
        最少需要的投票数（默认 2）。
        在加权模式下，加权和 >= min_votes 才发单。
    weights : dict, optional
        不同信号的权重，如 {"ma": 1.0, "macd": 1.5, "bollinger": 0.8}。
        长度为 N 时自动按顺序对应；
        N 个信号但 weights 长度不匹配时所有权重为 1.0。

    返回
    -------
    List[Dict[str, Any]]
        每条记录含:
          - date / symbol
          - signal: 最终投票结果（1/-1/0）
          - votes_for: 投票买的数量（加权后）
          - votes_against: 投票卖的数量（加权后）
          - total_votes: 投票总数（加权后）
          - individual_signals: 各信号的原始值
    """
    if not signals_list:
        return []

    N = len(signals_list)
    if N == 0:
        return []

    L = len(signals_list[0])

    # ── 解析权重 ──────────────────────────────────────
    weight_values: List[float]
    if weights is not None:
        # 如果 weights 是 dict，提取值
        weight_values = list(weights.values())
        # 若键是 'ma','macd','bollinger' 但数量不匹配，回退
        if len(weight_values) != N:
            weight_values = [1.0] * N
    else:
        weight_values = [1.0] * N

    # ── 逐 Bar 投票 ──────────────────────────────────
    result: List[Dict[str, Any]] = []

    for i in range(L):
        # 收集各信号在本 Bar 的决策
        raw_signals: List[int] = []
        for sig_list in signals_list:
            if i < len(sig_list):
                raw_signals.append(
                    sig_list[i].get("signal", 0)
                )
            else:
                raw_signals.append(0)

        normalized = [_normalize_signal(s) for s in raw_signals]

        # 计算加权投票
        votes_for = 0.0   # 加权投票 BUY
        votes_against = 0.0  # 加权投票 SELL
        total_active = 0.0

        for j in range(N):
            w = weight_values[j] if j < len(weight_values) else 1.0
            if normalized[j] == 1:
                votes_for += w
                total_active += w
            elif normalized[j] == -1:
                votes_against += w
                total_active += w

        # 判决
        threshold = float(min_votes)
        if votes_for >= threshold and votes_for > votes_against:
            final_signal = 1
        elif votes_against >= threshold and votes_against > votes_for:
            final_signal = -1
        else:
            final_signal = 0

        # 取第一个列表的日期/符号作为参考
        ref = signals_list[0][i] if i < len(signals_list[0]) else {}

        result.append({
            "date": ref.get("date"),
            "symbol": ref.get("symbol"),
            "signal": final_signal,
            "votes_for": round(votes_for, 2),
            "votes_against": round(votes_against, 2),
            "total_active_votes": round(total_active, 2),
            "individual_signals": normalized,
            "individual_raw": raw_signals,
        })

    return result


# ═══════════════════════════════════════════════════════════════
# 向后兼容别名（P3 迁移前旧名称）
# 保留旧版函数签名：接收 np.ndarray 价格序列，返回 Signal 对象
# ═══════════════════════════════════════════════════════════════
from dataclasses import dataclass
import numpy as np
import math


def ma_signal(prices: 'np.ndarray', fast: int = 5, slow: int = 20):
    """
    [旧版兼容] MA 金叉死叉信号。
    接收 numpy 价格序列，返回 _LegacySignal 对象。
    """
    if len(prices) < slow:
        return _LegacySignal(action="HOLD", strength=0.0)

    fast_ma = np.convolve(prices, np.ones(fast) / fast, mode='valid')
    slow_ma = np.convolve(prices, np.ones(slow) / slow, mode='valid')

    align = len(prices) - len(fast_ma)
    slow_aligned = slow_ma[align:] if align > 0 else slow_ma

    if len(fast_ma) < 2 or len(slow_aligned) < 2:
        return _LegacySignal(action="HOLD", strength=0.0)

    prev_fast, curr_fast = fast_ma[-2], fast_ma[-1]
    prev_slow, curr_slow = slow_aligned[-2], slow_aligned[-1]

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return _LegacySignal(action="BUY", strength=1.0)
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        return _LegacySignal(action="SELL", strength=1.0)
    return _LegacySignal(action="HOLD", strength=0.0)


def macd_signal(prices: 'np.ndarray', fast: int = 12, slow: int = 26, signal: int = 9):
    """
    [旧版兼容] MACD 信号。
    接收 numpy 价格序列，返回 _LegacySignal 对象。
    """
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        result = np.zeros_like(data)
        result[0] = data[0]
        alpha = 2.0 / (period + 1)
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    if len(prices) < slow + signal:
        return _LegacySignal(action="HOLD", strength=0.0)

    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)

    if len(dif) < 2 or len(dea) < 2:
        return _LegacySignal(action="HOLD", strength=0.0)

    if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
        return _LegacySignal(action="BUY", strength=1.0)
    elif dif[-2] >= dea[-2] and dif[-1] < dea[-1]:
        return _LegacySignal(action="SELL", strength=1.0)
    return _LegacySignal(action="HOLD", strength=0.0)


def bollinger_signal(prices: 'np.ndarray', window: int = 20, num_std: float = 2.0):
    """
    [旧版兼容] 布林带突破信号。
    接收 numpy 价格序列，返回 _LegacySignal 对象。
    """
    if len(prices) < window:
        return _LegacySignal(action="HOLD", strength=0.0)

    recent = prices[-window:]
    mean = np.mean(recent)
    std = np.std(recent, ddof=1)

    # 标准差为零时（如全零或常数数据），无法判断布林带突破
    if std < 1e-10:
        return _LegacySignal(action="HOLD", strength=0.0)

    upper = mean + num_std * std
    lower = mean - num_std * std
    last = prices[-1]

    if last >= upper:
        return _LegacySignal(action="BUY", strength=1.0)
    elif last <= lower:
        return _LegacySignal(action="SELL", strength=1.0)
    return _LegacySignal(action="HOLD", strength=0.0)


def trend_strength(prices: 'np.ndarray', window: int = 20) -> float:
    """
    [旧版兼容] 趋势强度评分。
    返回 0.0 ~ 1.0 之间的强度值。
    """
    if len(prices) < window:
        return 0.0
    data = prices[-window:]
    slope = (data[-1] - data[0]) / data[0]
    strength = min(1.0, abs(slope) * 5)
    return round(strength, 2)


def trend_intensity(prices: 'np.ndarray') -> str:
    """
    [旧版兼容] 趋势强度分类。
    返回 "strong" / "moderate" / "weak" / "none"。
    """
    if len(prices) < 5:
        return "none"
    half = len(prices) // 2
    first_half = prices[:half]
    second_half = prices[half:]
    first_change = (first_half[-1] - first_half[0]) / first_half[0] if first_half[0] != 0 else 0
    second_change = (second_half[-1] - second_half[0]) / second_half[0] if second_half[0] != 0 else 0
    total_change = (prices[-1] - prices[0]) / prices[0] if prices[0] != 0 else 0

    abs_change = abs(total_change)
    if abs_change > 0.15:
        return "strong"
    elif abs_change > 0.05:
        return "moderate"
    elif abs_change > 0.01:
        return "weak"
    return "none"


def weighted_vote(
    signals_or_list: 'Any',
    min_votes_or_weights: 'Any' = 2,
    weights: 'Optional[Dict[str, float]]' = None,
):
    """
    [旧版兼容] 加权投票。

    支持两种调用方式：
    1. 旧版：weighted_vote([Signal, Signal, ...], weights) → Signal
    2. 新版：weighted_vote(List[List[Dict]], ...) → List[Dict]

    根据第一个参数类型自动判断。
    """
    # 判断调用约定：若 min_votes_or_weights 是 list，则为旧版 (signals, weights) 调用
    _is_old_style = False
    _weights = None
    _min_votes = 2
    if isinstance(min_votes_or_weights, (list, tuple)):
        _is_old_style = True
        _weights = list(min_votes_or_weights)
    else:
        _min_votes = min_votes_or_weights if isinstance(min_votes_or_weights, int) else 2
        _weights = weights

    # 判断是否为旧版 Signal 对象调用
    if isinstance(signals_or_list, list):
        if len(signals_or_list) == 0:
            return _LegacySignal("HOLD", 0.0)
        first = signals_or_list[0]
        if isinstance(first, _LegacySignal):
            # 旧版调用：投票后返回 Signal
            actions = [s.action for s in signals_or_list]
            if _weights:
                if len(_weights) != len(signals_or_list):
                    raise ValueError("长度必须一致")
                weighted_scores = {}
                for s, w in zip(signals_or_list, _weights):
                    if s.action not in weighted_scores:
                        weighted_scores[s.action] = 0.0
                    weighted_scores[s.action] += s.strength * w

                sorted_actions = sorted(weighted_scores.items(), key=lambda x: -x[1])
                if len(sorted_actions) >= 2 and sorted_actions[0][1] == sorted_actions[1][1]:
                    return _LegacySignal("HOLD", 0.0)
                best_action = sorted_actions[0][0]
                best_strength = weighted_scores[best_action] / sum(_weights)
            else:
                # 无权重时按 strength 加总决策
                score_map: Dict[str, float] = {}
                for s in signals_or_list:
                    score_map[s.action] = score_map.get(s.action, 0.0) + s.strength
                sorted_actions = sorted(score_map.items(), key=lambda x: -x[1])
                if len(sorted_actions) >= 2 and sorted_actions[0][1] == sorted_actions[1][1]:
                    return _LegacySignal("HOLD", 0.0)
                best_action = sorted_actions[0][0]
                total_score = sum(score_map.values())
                best_strength = score_map[best_action] / total_score if total_score > 0 else 0.0

            if best_action == "HOLD":
                return _LegacySignal("HOLD", 0.0)
            return _LegacySignal(best_action, round(best_strength, 2))

    # 新版调用：透传 compute_voted_signal
    if _is_old_style and _weights:
        raise TypeError("weighted_vote: old-style Signal voting requires Signal objects")
    return compute_voted_signal(signals_or_list, min_votes=_min_votes, weights=_weights)


# 旧版 Signal dataclass
@dataclass
class _LegacySignal:
    """旧版信号数据类，用于向后兼容。"""
    action: str = "HOLD"
    strength: float = 0.0


# 旧版别名，供旧代码 from .trend_strategy import Signal 使用
# 新代码应使用 src.signals.signal_protocol_v1.Signal
LegacySignal = _LegacySignal
