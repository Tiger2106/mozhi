"""
墨枢 - Trend Lifecycle 趋势生命周期阶段判定器（Phase 1-C）

基于 TrendQuality + VWAP 偏离 + Volume + Regime 序列，
使用状态机标注每个交易日所处的趋势阶段。

5 阶段模型:
  1. INIT     启动期   — TrendQuality 从低转中，放量突破 VWAP
  2. ACCEL    加速期   — TrendQuality > 0.7，VWAP 偏离 > 3%，Vol > 1.5x ma
  3. MAIN     主升期   — TrendQuality > 0.6，VWAP 偏离 2~8%，Regime 稳定
  4. EXHAUST  衰竭期   — TrendQuality 下降，VWAP 偏离 > 8% 或收窄，Vol 背离
  5. DISTRIB  分配期   — TrendQuality < 0.4，VWAP 偏离 < 1%，Regime 转 RANGE，OBV 背离

允许跨级前进，不允许后退。

与 False Breakout 协同:
  - 分析假突破事件在生命周期各阶段的分布
  - 输出各阶段假突破比例

设计参考:
  - report_upgrade_v2_design.md §2.6
  - backtest_report_20260518_research_v2.md

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 阶段定义
# ═══════════════════════════════════════════════════════════════


class TrendPhase:
    """趋势生命周期阶段常量。"""
    PRE_INIT = "PRE_INIT"    # 启动前（非趋势）
    INIT = "INIT"            # 启动期
    ACCEL = "ACCEL"          # 加速期
    MAIN = "MAIN"            # 主升期
    EXHAUST = "EXHAUST"      # 衰竭期
    DISTRIB = "DISTRIB"      # 分配期

    ALL_PHASES = [PRE_INIT, INIT, ACCEL, MAIN, EXHAUST, DISTRIB]

    @classmethod
    def phase_index(cls, phase: str) -> int:
        if phase in cls.ALL_PHASES:
            return cls.ALL_PHASES.index(phase)
        return 0


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════


@dataclass
class Transition:
    """阶段切换事件。"""
    from_phase: str
    to_phase: str
    trigger_reason: str
    timestamp: str           # ISO8601
    bar_index: int           # 在 DataFrame 中的行索引
    confidence: float = 1.0  # 切换置信度 [0, 1]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PhasePeriod:
    """单个阶段的连续区间。"""
    phase: str
    start_bar: int
    end_bar: int
    start_date: str
    end_date: str
    duration_bars: int = 0
    avg_trend_quality: float = 0.0
    max_vwap_deviation: float = 0.0
    total_return: float = 0.0
    breakout_count: int = 0
    false_breakout_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LifecycleResult:
    """生命周期判定结果。"""
    per_bar_phase: pd.Series         # 每个 bar 的阶段（index=date, value=phase str）
    transitions: List[Transition]    # 切换事件列表
    periods: List[PhasePeriod]       # 各阶段的连续区间
    phase_stats: Dict[str, Dict[str, Any]]  # 各阶段统计

    def get_phase_at(self, bar_index: int) -> str:
        """获取指定 bar 的阶段。"""
        if 0 <= bar_index < len(self.per_bar_phase):
            return self.per_bar_phase.iloc[bar_index]
        return TrendPhase.PRE_INIT

    def get_phase_at_date(self, date_str: str) -> str:
        """获取指定日期的阶段。"""
        if date_str in self.per_bar_phase.index:
            return self.per_bar_phase.loc[date_str]
        # 尝试模糊匹配
        matches = self.per_bar_phase.index[self.per_bar_phase.index.astype(str).str.contains(date_str)]
        if len(matches) > 0:
            return self.per_bar_phase.loc[matches[0]]
        return TrendPhase.PRE_INIT

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可 JSON 序列化的字典。"""
        return {
            "bar_count": len(self.per_bar_phase),
            "transitions": [t.to_dict() for t in self.transitions],
            "periods": [p.to_dict() for p in self.periods],
            "phase_stats": self.phase_stats,
        }


# ═══════════════════════════════════════════════════════════════
# 状态机 — 只允许前进，禁止后退
# ═══════════════════════════════════════════════════════════════


class TrendLifecycleFSM:
    """趋势生命周期状态机。

    规则:
      - 允许前进（含跳级）
      - 禁止后退
      - 可以停留在当前阶段
    """

    # 阶段顺序映射（数字越大越靠后）
    PHASE_ORDER = {
        TrendPhase.PRE_INIT: 0,
        TrendPhase.INIT: 1,
        TrendPhase.ACCEL: 2,
        TrendPhase.MAIN: 3,
        TrendPhase.EXHAUST: 4,
        TrendPhase.DISTRIB: 5,
    }

    def __init__(self):
        self._current_phase: str = TrendPhase.PRE_INIT
        self._transitions: List[Transition] = []

    @property
    def current_phase(self) -> str:
        return self._current_phase

    @property
    def transitions(self) -> List[Transition]:
        return self._transitions.copy()

    def transition_to(self, new_phase: str, trigger_reason: str,
                      timestamp: str, bar_index: int,
                      confidence: float = 1.0) -> bool:
        """尝试切换到新阶段。

        Args:
            new_phase: 目标阶段。
            trigger_reason: 切换原因描述。
            timestamp: 切换时间（ISO8601）。
            bar_index: 在 DataFrame 中的行索引。
            confidence: 切换置信度。

        Returns:
            True 如果切换成功，False 如果被拒绝（后退或相同阶段）。
        """
        old_idx = self.PHASE_ORDER.get(self._current_phase, 0)
        new_idx = self.PHASE_ORDER.get(new_phase, 0)

        if new_idx < old_idx:
            # 禁止后退
            logger.debug(f"状态机禁止后退: {self._current_phase} → {new_phase}")
            return False

        if new_phase == self._current_phase:
            # 相同阶段，无切换
            return True

        # 记录切换（包括跳级）
        transition = Transition(
            from_phase=self._current_phase,
            to_phase=new_phase,
            trigger_reason=trigger_reason,
            timestamp=timestamp,
            bar_index=bar_index,
            confidence=confidence,
        )
        self._transitions.append(transition)
        self._current_phase = new_phase
        logger.info(
            f"阶段切换: {transition.from_phase} → {transition.to_phase} "
            f"| 原因: {trigger_reason} | 时间: {timestamp}"
        )
        return True

    def reset(self) -> None:
        """重置状态机到初始状态。"""
        self._current_phase = TrendPhase.PRE_INIT
        self._transitions.clear()


# ═══════════════════════════════════════════════════════════════
# C1: TrendLifecycleDetector — 趋势生命周期阶段判定器
# ═══════════════════════════════════════════════════════════════


class TrendLifecycleDetector:
    """趋势生命周期阶段判定器。

    基于 TrendQuality + VWAP 偏离 + Volume + Regime 序列，
    使用状态机标注每个交易日所处的趋势阶段。

    用法:
        detector = TrendLifecycleDetector()
        result = detector.detect(df)
        # result.per_bar_phase — 每个 bar 的阶段
        # result.transitions — 切换事件
        # result.periods — 阶段区间
    """

    # 默认参数
    TQ_ACCEL_THRESHOLD = 0.70       # 加速期 TrendQuality 阈值
    TQ_MAIN_THRESHOLD = 0.60        # 主升期 TrendQuality 阈值
    TQ_EXHAUST_THRESHOLD = 0.50     # 衰竭期 TrendQuality 阈值
    TQ_DISTRIB_THRESHOLD = 0.40     # 分配期 TrendQuality 阈值
    VWAP_ACCEL_THRESHOLD = 3.0      # 加速期 VWAP 偏离 (%)
    VWAP_MAIN_MIN = 2.0             # 主升期 VWAP 偏离下限 (%)
    VWAP_MAIN_MAX = 8.0             # 主升期 VWAP 偏离上限 (%)
    VWAP_EXHAUST_THRESHOLD = 8.0    # 衰竭期 VWAP 偏离阈值 (%)
    VOL_ACCEL_RATIO = 1.5           # 加速期量比
    CONSECUTIVE_HIGH_DAYS = 3       # 加速期连续新高天数

    REGIMES_TREND_UP = {"TREND_UP", "UPTREND", "BREAKOUT"}

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        """初始化检测器。

        Args:
            params: 可选参数覆盖字典。
        """
        if params:
            for key, value in params.items():
                if hasattr(self, key.upper()):
                    setattr(self, key.upper(), value)
                elif hasattr(self, key):
                    setattr(self, key, value)

        self._fsm: Optional[TrendLifecycleFSM] = None

    def detect(
        self,
        df: pd.DataFrame,
        trend_quality: Optional[pd.Series] = None,
        vwap_deviation: Optional[pd.Series] = None,
        regime_series: Optional[pd.Series] = None,
        obv_divergence: Optional[pd.Series] = None,
    ) -> LifecycleResult:
        """标记完整的生命周期阶段序列。

        Args:
            df: OHLCV DataFrame（必须含 close, volume, high, low）。
            trend_quality: 可选，TrendQuality 序列（否则自动计算）。
            vwap_deviation: 可选，VWAP 偏离 % 序列（否则自动计算）。
            regime_series: 可选，Regime 序列（否则自动计算）。
            obv_divergence: 可选，OBV 背离信号序列（否则自动计算）。

        Returns:
            LifecycleResult: 包含每 bar 阶段、切换事件、阶段统计。
        """
        n = len(df)
        if n < 60:
            logger.warning(f"数据不足 {n} bars，至少需要 60 bars 才能可靠判定阶段")
            return self._empty_result(df)

        # ── 1. 预计算因子 ──────────────────────────────────
        tq = self._ensure_trend_quality(df, trend_quality)
        vwap_dev = self._ensure_vwap_deviation(df, vwap_deviation)
        regime = self._ensure_regime(df, regime_series)
        obv_div = self._ensure_obv_divergence(df, obv_divergence)

        # 辅助序列
        vol_ma20 = df["volume"].rolling(20, min_periods=5).mean().bfill()
        vol_ratio = df["volume"] / vol_ma20
        close = df["close"]

        # ── 2. 初始化状态机 ──────────────────────────────────
        self._fsm = TrendLifecycleFSM()
        prev_vwap_dev = 0.0

        # 每个 bar 的阶段
        per_bar_phases = pd.Series(
            [TrendPhase.PRE_INIT] * n,
            index=df.index, name="trend_phase"
        )

        # ── 3. 逐 bar 判定阶段 ──────────────────────────────
        for i in range(1, n):
            phase = self._fsm.current_phase
            date_obj = df.index[i]
            date_str = str(date_obj.date()) if hasattr(date_obj, 'date') else str(date_obj)

            # 获取当前 bar 的信号
            tq_i = float(tq.iloc[i]) if i < len(tq) and pd.notna(tq.iloc[i]) else 0.0
            vwap_i = float(vwap_dev.iloc[i]) if i < len(vwap_dev) and pd.notna(vwap_dev.iloc[i]) else 0.0
            reg_i = str(regime.iloc[i]) if i < len(regime) and pd.notna(regime.iloc[i]) else ""
            obv_i = float(obv_div.iloc[i]) if i < len(obv_div) and pd.notna(obv_div.iloc[i]) else 0.0
            vol_r = float(vol_ratio.iloc[i]) if pd.notna(vol_ratio.iloc[i]) else 0.0
            prev_tq = float(tq.iloc[i - 1]) if (i - 1) < len(tq) and pd.notna(tq.iloc[i - 1]) else 0.0

            # ── 判定候选阶段 ──────────────────────────────
            # 从最先进阶段到最不先进阶段依次检查
            new_phase_candidates = []

            # 检查 DISTRIB (分配期)
            if (tq_i < self.TQ_DISTRIB_THRESHOLD
                    and abs(vwap_i) < 1.5
                    and reg_i not in self.REGIMES_TREND_UP
                    and obv_i < 0):
                new_phase_candidates.append(TrendPhase.DISTRIB)

            # 检查 EXHAUST (衰竭期)
            if (tq_i < self.TQ_EXHAUST_THRESHOLD
                    and tq_i < prev_tq  # TrendQuality 开始下降
                    and (vwap_i > self.VWAP_EXHAUST_THRESHOLD
                         or (vwap_i > self.VWAP_MAIN_MAX
                             and abs(vwap_i - prev_vwap_dev) < 0.5  # 收窄信号
                         ))):
                new_phase_candidates.append(TrendPhase.EXHAUST)

            # 检查 MAIN (主升期)
            if (tq_i >= self.TQ_MAIN_THRESHOLD
                    and self.VWAP_MAIN_MIN <= vwap_i <= self.VWAP_MAIN_MAX
                    and reg_i in self.REGIMES_TREND_UP):
                new_phase_candidates.append(TrendPhase.MAIN)

            # 检查 ACCEL (加速期)
            if (tq_i >= self.TQ_ACCEL_THRESHOLD
                    and vwap_i > self.VWAP_ACCEL_THRESHOLD
                    and vol_r >= self.VOL_ACCEL_RATIO
                    and self._check_consecutive_highs(close, i, self.CONSECUTIVE_HIGH_DAYS)):
                new_phase_candidates.append(TrendPhase.ACCEL)

            # 检查 INIT (启动期)
            if (tq_i >= self.TQ_MAIN_THRESHOLD * 0.5   # 趋势质量从低转中
                    and prev_tq < self.TQ_MAIN_THRESHOLD * 0.5
                    and vwap_i > 0.5
                    and vol_r > 1.0
                    and reg_i in self.REGIMES_TREND_UP):
                new_phase_candidates.append(TrendPhase.INIT)

            # ── 选择最先进阶段（从候选列表中取最靠后的） ──
            if new_phase_candidates:
                best_candidate = max(
                    new_phase_candidates,
                    key=lambda p: TrendLifecycleFSM.PHASE_ORDER.get(p, 0)
                )

                # 构建切换原因
                reasons = []
                if tq_i < self.TQ_DISTRIB_THRESHOLD and abs(vwap_i) < 1.5:
                    reasons.append(f"TQ={tq_i:.2f}<0.4")
                    reasons.append(f"VWAP_dev={vwap_i:.1f}%<1%")
                if obv_i < 0:
                    reasons.append("OBV_divergence")
                if tq_i < prev_tq:
                    reasons.append("TQ_dropping")
                if vwap_i > self.VWAP_EXHAUST_THRESHOLD:
                    reasons.append(f"VWAP_dev={vwap_i:.1f}%>8%")
                if vol_r >= self.VOL_ACCEL_RATIO:
                    reasons.append(f"Vol_ratio={vol_r:.2f}")
                if reg_i in self.REGIMES_TREND_UP:
                    reasons.append(f"Regime={reg_i}")

                trigger_reason = "; ".join(reasons) if reasons else "Auto_detection"

                self._fsm.transition_to(
                    new_phase=best_candidate,
                    trigger_reason=trigger_reason,
                    timestamp=date_str,
                    bar_index=i,
                )

            per_bar_phases.iloc[i] = self._fsm.current_phase
            prev_vwap_dev = vwap_i

        # ── 4. 构建阶段区间 ──────────────────────────────────
        periods = self._build_phase_periods(per_bar_phases, df, tq, vwap_dev)

        # ── 5. 阶段统计 ──────────────────────────────────────
        phase_stats = self._compute_phase_stats(per_bar_phases, periods, df)

        return LifecycleResult(
            per_bar_phase=per_bar_phases,
            transitions=self._fsm.transitions,
            periods=periods,
            phase_stats=phase_stats,
        )

    def get_current_phase(self) -> str:
        """获取当前阶段。"""
        if self._fsm:
            return self._fsm.current_phase
        return TrendPhase.PRE_INIT

    def reset(self) -> None:
        """重置检测器。"""
        self._fsm = None

    # ── 因子计算辅助 ────────────────────────────────────────

    def _ensure_trend_quality(self, df: pd.DataFrame,
                               series: Optional[pd.Series] = None) -> pd.Series:
        """确保 TrendQuality 序列就绪。"""
        if series is not None:
            return series
        try:
            from backtest.factors.trend.trend_quality_factor import (
                calc_adx, calc_trend_strength
            )
            adx = calc_adx(df)
            return calc_trend_strength(adx)
        except ImportError:
            logger.warning("无法加载 trend_quality_factor，使用简化版")
            return self._simple_trend_strength(df)

    def _simple_trend_strength(self, df: pd.DataFrame) -> pd.Series:
        """简化版趋势强度计算（当无法导入原有因子时）。"""
        high, low, close = df["high"], df["low"], df["close"]

        # TR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14, min_periods=5).mean()

        # 方向移动
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
            index=df.index
        )
        minus_dm = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
            index=df.index
        )

        safe_atr = atr.replace(0, np.nan)
        plus_di = 100 * plus_dm.rolling(14, min_periods=5).mean() / safe_atr
        minus_di = 100 * minus_dm.rolling(14, min_periods=5).mean() / safe_atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.rolling(14, min_periods=5).mean().fillna(0) / 100.0

        return adx.clip(0, 1).fillna(0)

    def _ensure_vwap_deviation(self, df: pd.DataFrame,
                                series: Optional[pd.Series] = None) -> pd.Series:
        """确保 VWAP 偏离序列就绪。"""
        if series is not None:
            return series
        try:
            from backtest.factors.volume.vwap_factor import calc_vwap_deviation
            return calc_vwap_deviation(df)
        except ImportError:
            logger.warning("无法加载 vwap_factor，使用简化版")
            return self._simple_vwap_deviation(df)

    def _simple_vwap_deviation(self, df: pd.DataFrame) -> pd.Series:
        """简化版 VWAP 偏离计算。"""
        tp = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (df["volume"] * tp).cumsum() / df["volume"].cumsum().replace(0, np.nan)
        return ((df["close"] - vwap) / vwap * 100).fillna(0)

    def _ensure_regime(self, df: pd.DataFrame,
                        series: Optional[pd.Series] = None) -> pd.Series:
        """确保 Regime 序列就绪。"""
        if series is not None:
            return series
        try:
            from backtest.factors.regime.regime_factor import classify_regime
            regimes = []
            for i in range(len(df)):
                try:
                    result = classify_regime(df.iloc[:i + 1])
                    regimes.append(result.get("regime", "UNKNOWN"))
                except Exception:
                    regimes.append("UNKNOWN")
            return pd.Series(regimes, index=df.index)
        except ImportError:
            logger.warning("无法加载 regime_factor，使用简化版")
            return self._simple_regime(df)

    def _simple_regime(self, df: pd.DataFrame) -> pd.Series:
        """简化版 Regime 判定。基于 MA50 斜率。"""
        ma20 = df["close"].rolling(20, min_periods=5).mean()
        ma50 = df["close"].rolling(50, min_periods=10).mean()
        ma200 = df["close"].rolling(200, min_periods=20).mean()

        regimes = []
        for i in range(len(df)):
            if i < 20 or pd.isna(ma20.iloc[i]) or pd.isna(ma50.iloc[i]):
                regimes.append("UNKNOWN")
                continue
            slope_50 = (ma50.iloc[i] - ma50.iloc[max(0, i - 10)]) / ma50.iloc[i] * 100

            if slope_50 > 0.3:
                if not pd.isna(ma200.iloc[i]) and close.iloc[i] > ma200.iloc[i]:
                    regimes.append("UPTREND")
                else:
                    regimes.append("RANGE")
            elif slope_50 < -0.3:
                regimes.append("DOWNTREND")
            else:
                regimes.append("RANGE")
        return pd.Series(regimes, index=df.index)

    def _ensure_obv_divergence(self, df: pd.DataFrame,
                                series: Optional[pd.Series] = None) -> pd.Series:
        """确保 OBV 背离序列就绪。

        返回值:
          >0: OBV 与价格同向（正常）
          <0: OBV 与价格反向（背离信号）
        """
        if series is not None:
            return series
        try:
            from backtest.factors.volume.obv_factor import OBVFactor
            obv_result = OBVFactor(
                params={"signal_period": 20, "ma_type": "sma"}
            ).compute(df)
            obv = obv_result["obv"]
        except ImportError:
            # 简化版 OBV 计算
            shifted_close = df["close"].shift(1).bfill()
            obv = (df["volume"]
                   * np.where(df["close"] > shifted_close, 1,
                              np.where(df["close"] < shifted_close, -1, 0))
                   ).cumsum().fillna(0)

        # OBV 斜率 (5 日)
        obv_slope = obv.diff(5).fillna(0)
        price_slope = df["close"].diff(5).fillna(0)

        # 背离信号: -1=量价背离（价格涨OBV跌）
        divergence = pd.Series(0.0, index=df.index)
        divergence[(price_slope > 0) & (obv_slope < 0)] = -1.0
        divergence[(price_slope < 0) & (obv_slope > 0)] = 1.0
        return divergence

    # ── 辅助方法 ────────────────────────────────────────────

    def _check_consecutive_highs(self, close: pd.Series, idx: int, n: int) -> bool:
        """检查最近 N 日是否连续创新高。"""
        if idx < n - 1:
            return False
        recent = close.iloc[idx - n + 1: idx + 1]
        for j in range(1, n):
            if recent.iloc[j] <= recent.iloc[:j].max():
                return False
        return True

    def _build_phase_periods(
        self, per_bar_phase: pd.Series, df: pd.DataFrame,
        tq: pd.Series, vwap_dev: pd.Series
    ) -> List[PhasePeriod]:
        """从每 bar 阶段序列构建连续区间列表。"""
        periods = []
        n = len(per_bar_phase)
        i = 0

        while i < n:
            current_phase = per_bar_phase.iloc[i]
            start = i
            while i < n and per_bar_phase.iloc[i] == current_phase:
                i += 1
            end = i - 1

            start_price = float(df.iloc[start]["close"]) if start < len(df) else np.nan
            end_price = float(df.iloc[end]["close"]) if end < len(df) else np.nan
            total_return = (end_price / start_price - 1) * 100 if start_price > 0 else 0.0

            period_tq = tq.iloc[start:end + 1].dropna()
            period_vwap = vwap_dev.iloc[start:end + 1].dropna()

            period = PhasePeriod(
                phase=current_phase,
                start_bar=start,
                end_bar=end,
                start_date=str(per_bar_phase.index[start].date())
                    if hasattr(per_bar_phase.index[start], 'date')
                    else str(per_bar_phase.index[start]),
                end_date=str(per_bar_phase.index[end].date())
                    if hasattr(per_bar_phase.index[end], 'date')
                    else str(per_bar_phase.index[end]),
                duration_bars=end - start + 1,
                avg_trend_quality=float(period_tq.mean()) if len(period_tq) > 0 else 0.0,
                max_vwap_deviation=float(period_vwap.max()) if len(period_vwap) > 0 else 0.0,
                total_return=round(total_return, 2),
            )
            periods.append(period)

        return periods

    def _compute_phase_stats(
        self, per_bar_phase: pd.Series,
        periods: List[PhasePeriod],
        df: pd.DataFrame,
    ) -> Dict[str, Dict[str, Any]]:
        """计算各阶段汇总统计。"""
        stats = {}
        for phase in TrendPhase.ALL_PHASES:
            phase_periods = [p for p in periods if p.phase == phase]
            if not phase_periods:
                stats[phase] = {
                    "occurrences": 0,
                    "avg_duration": 0.0,
                    "total_duration": 0,
                    "avg_return": 0.0,
                    "total_return": 0.0,
                }
                continue

            durations = [p.duration_bars for p in phase_periods]
            returns = [p.total_return for p in phase_periods]
            avg_tq_vals = [p.avg_trend_quality for p in phase_periods]

            stats[phase] = {
                "occurrences": len(phase_periods),
                "avg_duration": round(float(np.mean(durations)), 1),
                "total_duration": sum(durations),
                "avg_return": round(float(np.mean(returns)), 2),
                "max_return": round(float(max(returns)), 2),
                "min_return": round(float(min(returns)), 2),
                "total_return": round(float(sum(returns)), 2),
                "avg_tq": round(float(np.mean(avg_tq_vals)), 3),
            }
        return stats

    def _empty_result(self, df: pd.DataFrame) -> LifecycleResult:
        """返回空结果（数据不足时）。"""
        n = len(df)
        per_bar = pd.Series(
            [TrendPhase.PRE_INIT] * n,
            index=df.index, name="trend_phase"
        )
        return LifecycleResult(
            per_bar_phase=per_bar,
            transitions=[],
            periods=[PhasePeriod(
                phase=TrendPhase.PRE_INIT, start_bar=0, end_bar=n - 1,
                start_date=str(df.index[0].date()) if hasattr(df.index[0], 'date') else "0",
                end_date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else "0",
                duration_bars=n,
            )],
            phase_stats={p: {
                "occurrences": 0, "avg_duration": 0.0, "total_duration": 0,
                "avg_return": 0.0, "total_return": 0.0,
            } for p in TrendPhase.ALL_PHASES},
        )


# ═══════════════════════════════════════════════════════════════
# C3: 与 False Breakout 的协同分析
# ═══════════════════════════════════════════════════════════════


def analyze_breakout_lifecycle(
    result: LifecycleResult,
    breakout_indices: List[int],
    false_breakout_indices: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """分析假突破事件在生命周期各阶段的分布。

    Args:
        result: TrendLifecycleDetector 的判定结果。
        breakout_indices: 所有突破事件的 bar 索引列表。
        false_breakout_indices: 假突破事件的 bar 索引列表。
            None 表示所有突破都标记为假突破。

    Returns:
        分析结果字典：
          - total_breakouts: 总数
          - total_false_breakouts: 假突破数
          - false_ratio_total: 整体假突破比例
          - phase_distribution: {phase: {total, false, false_ratio}}
          - per_breakout: [{index, date, phase, is_false}]
    """
    phases = TrendPhase.ALL_PHASES
    ph_idx = {p: TrendPhase.phase_index(p) for p in phases}

    breakout_by_phase: Dict[str, int] = {p: 0 for p in phases}
    false_by_phase: Dict[str, int] = {p: 0 for p in phases}

    false_set = set(false_breakout_indices or [])
    per_breakout = []

    for idx in breakout_indices:
        if idx < 0 or idx >= len(result.per_bar_phase):
            continue
        phase = result.per_bar_phase.iloc[idx]
        is_false = idx in false_set
        date_str = str(result.per_bar_phase.index[idx].date()) \
            if hasattr(result.per_bar_phase.index[idx], 'date') \
            else f"idx_{idx}"

        breakout_by_phase[phase] = breakout_by_phase.get(phase, 0) + 1
        if is_false:
            false_by_phase[phase] = false_by_phase.get(phase, 0) + 1

        per_breakout.append({
            "index": idx,
            "date": date_str,
            "phase": phase,
            "is_false": is_false,
        })

    # 用过滤后的索引统计总数
    valid_indices = [i for i in breakout_indices if 0 <= i < len(result.per_bar_phase)]
    total_valid = len(valid_indices)
    total_false_valid = len([i for i in valid_indices if i in false_set])

    # 各阶段假突破比例
    phase_distribution = {}
    for p in phases:
        total = breakout_by_phase.get(p, 0)
        false_cnt = false_by_phase.get(p, 0)
        false_ratio = round(false_cnt / total * 100, 1) if total > 0 else 0.0
        phase_distribution[p] = {
            "total_breakouts": total,
            "false_breakouts": false_cnt,
            "false_ratio": false_ratio,
        }

    return {
        "total_breakouts": total_valid,
        "total_false_breakouts": total_false_valid,
        "false_ratio_total": round(total_false_valid / total_valid * 100, 1) if total_valid > 0 else 0.0,
        "phase_distribution": phase_distribution,
        "per_breakout": per_breakout,
    }
