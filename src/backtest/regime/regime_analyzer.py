"""
墨枢 - RegimeAnalyzer 市场状态分析器（R1 阶段三：任务3）

功能：
  - 使用 Phase 1 Regime 因子（classify_regime）实时判定市场状态
  - analyze_window(df, lookback=60) — 窗口内状态变化序列
  - get_current_regime() — 当前状态 + 持续时间 + 置信度
  - regime_transition_score() — 状态转换概率矩阵
  - 对接 pipeline_paths.knowledge_file() 输出知识沉淀

依赖:
  - src.backtest.factors.regime.regime_factor — classify_regime
  - pipeline_paths — knowledge_file()
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.factors.regime.regime_factor import classify_regime
from pipeline_paths import knowledge_file, research_date_dir, today_str

# ─── 时区 ───
TZ = timezone(timedelta(hours=8))


# ─── 结果类型 ──────────────────────────────────────────────────


@dataclass
class RegimeWindowResult:
    """窗口分析结果"""
    sequence: List[Dict[str, Any]]      # 状态变化序列 [{bar_index, regime, confidence, timestamp}]
    regime_counts: Dict[str, int]       # 各状态出现次数
    regime_durations: Dict[str, int]    # 各状态连续持续时长
    dominant_regime: str                # 窗口内主导状态
    transitions: int                    # 状态转换次数
    stability: float                    # 稳定性评分 [0, 1]


@dataclass
class RegimeDurationInfo:
    """当前状态持续时间信息"""
    regime: str
    duration_bars: int          # 连续持仓 K 线数
    confidence: float           # 当前置信度
    first_seen_index: int       # 首次出现的 K 线索引


@dataclass
class KnowledgePayload:
    """知识沉淀负载，对接 pipeline_paths.knowledge_file()"""
    timestamp: str
    regime: str
    confidence: float
    duration_bars: int
    transition_probabilities: Dict[str, Dict[str, float]]
    summary: str


# ─── RegimeAnalyzer ────────────────────────────────────────────


class RegimeAnalyzer:
    """市场状态分析器。

    封装 classify_regime，提供窗口分析、状态跟踪、转换概率计算。

    Examples:
        >>> analyzer = RegimeAnalyzer()
        >>> result = analyzer.analyze_window(df)
        >>> current = analyzer.get_current_regime()
        >>> transitions = analyzer.regime_transition_score()
    """

    def __init__(self) -> None:
        # 历史状态记录
        self._history: List[Dict[str, Any]] = []
        self._state_sequence: List[str] = []
        self._current_regime: str = "UNKNOWN"
        self._current_confidence: float = 0.0
        self._current_evidence: Dict[str, Any] = {}

        # 状态计数
        self._state_counts: Dict[str, int] = {
            "UPTREND": 0, "DOWNTREND": 0, "RANGE": 0,
            "BREAKOUT": 0, "CLIMAX": 0, "UNKNOWN": 0,
        }

        # 转换计数
        self._transition_counts: Dict[str, Dict[str, int]] = {
            from_s: {to_s: 0 for to_s in ["UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX", "UNKNOWN"]}
            for from_s in ["UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX", "UNKNOWN"]
        }

        # 当前状态持续时间跟踪
        self._current_start_index: int = 0

    # ─── 核心接口 ────────────────────────────────────────────

    def analyze_window(
        self,
        df: pd.DataFrame,
        lookback: int = 60,
    ) -> RegimeWindowResult:
        """分析窗口内的市场状态变化序列。

        Args:
            df: OHLCV DataFrame
            lookback: 分析窗口大小（K 线数）

        Returns:
            RegimeWindowResult: 窗口分析结果
        """
        if len(df) < lookback:
            lookback = len(df)

        window = df.iloc[-lookback:].copy().reset_index(drop=True)

        sequence: List[Dict[str, Any]] = []
        current_state = "UNKNOWN"
        current_duration = 0

        # 滑动窗口状态判定
        for i in range(lookback):
            sub_df = window.iloc[:i + 1]
            if len(sub_df) < 10:
                continue

            try:
                result = classify_regime(sub_df)
            except Exception:
                result = {"regime": "UNKNOWN", "confidence": 0.0, "evidence": {}}

            regime = result.get("regime", "UNKNOWN")
            confidence = result.get("confidence", 0.0)

            timestamp = ""
            if isinstance(df.index, pd.DatetimeIndex):
                idx = len(df) - lookback + i
                if 0 <= idx < len(df):
                    timestamp = str(df.index[idx])

            record = {
                "bar_index": i,
                "regime": regime,
                "confidence": confidence,
                "timestamp": timestamp,
            }
            sequence.append(record)

            # 更新内部状态
            self._update_state(regime, confidence, result.get("evidence", {}))

            # 统计持续时间
            if regime == current_state:
                current_duration += 1
            else:
                current_state = regime
                current_duration = 1

        # 统计
        regime_counts: Dict[str, int] = {}
        regimes_insert = [r["regime"] for r in sequence]
        for r in regimes_insert:
            regime_counts[r] = regime_counts.get(r, 0) + 1

        transitions = sum(
            1 for i in range(1, len(regimes_insert))
            if regimes_insert[i] != regimes_insert[i - 1]
        )

        # 稳定性评分：转换越少越稳定
        stability = 1.0 - (transitions / max(len(regimes_insert) - 1, 1))

        # 主导状态
        dominant = max(regime_counts, key=regime_counts.get) if regime_counts else "UNKNOWN"

        # 持续时间
        regime_durations: Dict[str, int] = {}
        dur_current = 0
        dur_prev_state = regimes_insert[0] if regimes_insert else ""
        for r in regimes_insert:
            if r == dur_prev_state:
                dur_current += 1
            else:
                regime_durations[dur_prev_state] = max(
                    regime_durations.get(dur_prev_state, 0), dur_current
                )
                dur_prev_state = r
                dur_current = 1
        if dur_prev_state:
            regime_durations[dur_prev_state] = max(
                regime_durations.get(dur_prev_state, 0), dur_current
            )

        return RegimeWindowResult(
            sequence=sequence,
            regime_counts=regime_counts,
            regime_durations=regime_durations,
            dominant_regime=dominant,
            transitions=transitions,
            stability=round(stability, 4),
        )

    def get_current_regime(self) -> Dict[str, Any]:
        """返回当前市场状态 + 持续时间 + 置信度。

        Returns:
            Dict[str, Any]: {
                "regime": str,
                "confidence": float,
                "duration_bars": int,
                "evidence": dict,
            }
        """
        return {
            "regime": self._current_regime,
            "confidence": round(self._current_confidence, 4),
            "duration_bars": self._calc_duration(),
            "evidence": self._current_evidence,
        }

    def regime_transition_score(self) -> Dict[str, Dict[str, float]]:
        """计算状态转换概率矩阵。

        Returns:
            Dict[str, Dict[str, float]]:
                {from_state: {to_state: probability}}  # 每行之和为 1.0
        """
        prob_matrix: Dict[str, Dict[str, float]] = {}

        all_states = ["UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX", "UNKNOWN"]

        for from_s in all_states:
            total = sum(self._transition_counts[from_s].values())
            prob_matrix[from_s] = {}
            for to_s in all_states:
                if total > 0:
                    prob_matrix[from_s][to_s] = round(
                        self._transition_counts[from_s][to_s] / total, 4
                    )
                else:
                    prob_matrix[from_s][to_s] = 0.0

        return prob_matrix

    def get_history(self) -> List[Dict[str, Any]]:
        """返回完整分析历史。"""
        return self._history.copy()

    def knowledge_entry(self) -> KnowledgePayload:
        """生成知识沉淀条目，对接 pipeline_paths.knowledge_file()。"""
        current = self.get_current_regime()
        transitions = self.regime_transition_score()

        summary = (
            f"当前市场状态: {current['regime']} "
            f"(置信度: {current['confidence']:.2f}, "
            f"持续 {current['duration_bars']} 根K线). "
            f"稳定状态概率: "
            f"{transitions.get(current['regime'], {}).get(current['regime'], 0):.1%}"
        )

        return KnowledgePayload(
            timestamp=datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            regime=current["regime"],
            confidence=current["confidence"],
            duration_bars=current["duration_bars"],
            transition_probabilities=transitions,
            summary=summary,
        )

    # ─── 知识沉淀持久化 ──────────────────────────────────────

    def save_knowledge(
        self,
        method_name: str = "regime_analyzer",
        date_str: str = "",
    ) -> str:
        """将当前知识沉淀写入 reports/research/{date}/knowledge_{method_name}.md。

        Args:
            method_name: 方法名（默认 regime_analyzer）
            date_str: 日期 YYYYMMDD（默认今天）

        Returns:
            str: 写入文件的路径
        """
        if not date_str:
            date_str = today_str()

        payload = self.knowledge_entry()

        # 构建 Markdown 内容
        transitions_str = ""
        for from_s, to_map in payload.transition_probabilities.items():
            to_strs = [f"  → {to_s}: {p:.1%}" for to_s, p in to_map.items() if p > 0]
            if to_strs:
                transitions_str += f"- {from_s}:\n" + "\n".join(to_strs) + "\n"

        content = f"""# 市场状态分析 - {payload.timestamp}

## 当前状态
- **Regime**: {payload.regime}
- **置信度**: {payload.confidence:.2%}
- **持续 K 线数**: {payload.duration_bars}

## 摘要
{payload.summary}

## 状态转换概率矩阵
{transitions_str}
---
*自动生成于 {payload.timestamp}*
"""

        path = knowledge_file(method_name, date_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    # ─── 内部方法 ────────────────────────────────────────────

    def _update_state(
        self,
        regime: str,
        confidence: float,
        evidence: Dict[str, Any],
    ) -> None:
        """内部状态更新。"""
        previous = self._current_regime

        self._current_regime = regime
        self._current_confidence = confidence
        self._current_evidence = evidence

        # 记录历史
        record = {
            "regime": regime,
            "confidence": confidence,
            "evidence": evidence,
            "timestamp": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }
        self._history.append(record)
        self._state_sequence.append(regime)

        # 更新计数
        self._state_counts[regime] = self._state_counts.get(regime, 0) + 1

        # 跟踪转换
        if previous != regime and len(self._state_sequence) > 1:
            if previous in self._transition_counts:
                self._transition_counts[previous][regime] += 1

    def _calc_duration(self) -> int:
        """计算当前状态的持续时间（K 线数）。"""
        duration = 0
        for s in reversed(self._state_sequence):
            if s == self._current_regime:
                duration += 1
            else:
                break
        return duration
