# -*- coding: utf-8 -*-
"""
q5_temporal_validator.py — Q5 时间稳定性验证器

检查策略回测收益/IC 在时间维度上的一致性：
将回测期均匀切分为 4 个年度子窗口，检查各子窗口的收益/IC 方向一致性。
若某窗口方向相反且幅度不可忽略 → 标记为 TEMPORAL_INCONSISTENCY。

定位：
  Layer Q — Transverse Governance Layer（横向治理层）
  Q5 Temporal Stability — 时间维度质量审计

输入接口：
  复用 existence_validator.py 的 TradeRecord 数据结构（即 pnl_pct 可表示收益率或 IC 值）。

输出：
  TemporalStabilityResult 包含 pass/fail 判断、各窗口统计量、方向一致性评估。

作者：墨萱 (moxuan)
创建时间：2026-05-19 16:20 GMT+8
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Union

from src.utils.existence_validator import TradeRecord, _to_date


# ============================================================
# 常量
# ============================================================

_N_WINDOWS: int = 4                          # 均匀切分的子窗口数
_DEFAULT_DIRECTION_THRESHOLD: float = 0.01   # 方向相反的"不可忽略"阈值（绝对值 < 此值视为可忽略噪声）
_WINDOW_MIN_RECORDS: int = 1                 # 每个窗口最少需要 1 个记录


# ============================================================
# 结果数据结构
# ============================================================

@dataclass
class WindowStats:
    """单个时间窗口的统计分析"""
    index: int                                    # 窗口序号 (0-based)
    start_date: date                              # 窗口起始日期
    end_date: date                                # 窗口结束日期
    n_records: int                                # 窗口内记录数
    mean_pnl: float                               # 窗口内平均 pnl_pct
    median_pnl: float                             # 窗口内中位数 pnl_pct
    total_pnl: float                              # 窗口内累计 pnl_pct (求和)
    positive_fraction: float                      # 正向记录的占比 (>=0)
    is_positive: bool                             # 窗口整体方向是否为正
    major_direction: str                          # "positive" / "negative" / "neutral"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "n_records": self.n_records,
            "mean_pnl": round(self.mean_pnl, 6),
            "median_pnl": round(self.median_pnl, 6),
            "total_pnl": round(self.total_pnl, 6),
            "positive_fraction": round(self.positive_fraction, 4),
            "is_positive": self.is_positive,
            "major_direction": self.major_direction,
        }


@dataclass
class TemporalStabilityResult:
    """时间稳定性验证结果

    Attributes
    ----------
    is_stable : bool
        是否通过时间稳定性检查（所有窗口方向一致，或反向幅度可忽略）
    confidence : float
        稳定性置信度 (0.0 ~ 1.0)，基于窗口内 pnl_pct 的变异系数和总 N 加权
    windows : list[WindowStats]
        各个子窗口的统计信息
    dominant_direction : str
        整体主导方向 ("positive" / "negative" / "neutral")
    inconsistent_windows : list[int]
        方向相反且不可忽略的窗口索引列表
    inconsistency_severity : float
        不一致严重程度，取不一致窗口平均反向幅度与整体方向幅度的比值。若无不一致则 0.0。
    details : dict
        详细辅助信息
    fail_reason : str | None
        不通过时的原因说明
    """
    is_stable: bool
    confidence: float
    windows: list[WindowStats]
    dominant_direction: str
    inconsistent_windows: list[int]
    inconsistency_severity: float
    details: dict
    fail_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_stable": self.is_stable,
            "confidence": round(self.confidence, 4),
            "n_windows": len(self.windows),
            "dominant_direction": self.dominant_direction,
            "inconsistent_windows": self.inconsistent_windows,
            "inconsistency_severity": round(self.inconsistency_severity, 4),
            "fail_reason": self.fail_reason,
            "windows": [w.to_dict() for w in self.windows],
            "details": self.details,
        }


# ============================================================
# 验证器
# ============================================================

def validate_temporal_stability(
    trades: list[TradeRecord],
    *,
    direction_threshold: float = _DEFAULT_DIRECTION_THRESHOLD,
) -> TemporalStabilityResult:
    """
    对交易/观测记录执行时间稳定性检查（Q5）。

    将全时间范围均匀分成 4 个窗口，检查各窗口的方向一致性。

    Parameters
    ----------
    trades : list[TradeRecord]
        交易/观测记录列表，复用 existence_validator.py 的 TradeRecord 接口。
        pnl_pct 可表示收益率或 IC 值，由调用方决定语义。
    direction_threshold : float
        方向相反判定中"可忽略噪声"的阈值。
        当某个窗口的平均 pnl_pct 绝对值小于此值时(pnl_pct 为小数形式如 0.01=1%)，
        即使方向与主导方向相反，也视为可忽略噪声，不触发 TEMPORAL_INCONSISTENCY。
        默认 0.01（1%）。

    Returns
    -------
    TemporalStabilityResult
    """
    details: dict = {}

    # ---------- 空数据防护 ----------
    if not trades:
        return TemporalStabilityResult(
            is_stable=False,
            confidence=0.0,
            windows=[],
            dominant_direction="neutral",
            inconsistent_windows=[],
            inconsistency_severity=0.0,
            details=details,
            fail_reason="无任何交易/观测记录，无法执行时间稳定性检查",
        )

    n_total = len(trades)

    # ---------- 按日期排序 ----------
    sorted_trades = sorted(trades, key=lambda t: _to_date(t.date))
    dates_sorted = [_to_date(t.date) for t in sorted_trades]
    pnls = [t.pnl_pct for t in sorted_trades]

    start_date = dates_sorted[0]
    end_date = dates_sorted[-1]
    total_span_days = (end_date - start_date).days

    details["date_range"] = (start_date.isoformat(), end_date.isoformat())
    details["total_days"] = total_span_days
    details["n_total_records"] = n_total

    # 所有 pnl_pct 同号的判定（无需分窗口即可确定主导方向）
    all_positive = all(p >= 0 for p in pnls)
    all_negative = all(p <= 0 for p in pnls)

    # ---------- 分窗 ----------
    windows: list[WindowStats] = []

    for i in range(_N_WINDOWS):
        # 窗口起止日期
        w_start_days = int(total_span_days * i / _N_WINDOWS)
        w_end_days = int(total_span_days * (i + 1) / _N_WINDOWS)
        w_start = start_date.toordinal()
        w_end = start_date.toordinal()
        # 使用 ordinal 计算精确日期
        w_start_ord = start_date.toordinal() + w_start_days
        w_end_ord = start_date.toordinal() + w_end_days - 1  # 闭区间
        w_end_ord = max(w_end_ord, w_start_ord)  # 至少包含一天

        # 处理最后一个窗口，确保包含 end_date
        if i == _N_WINDOWS - 1:
            w_end_ord = end_date.toordinal()

        w_start_date = date.fromordinal(w_start_ord)
        w_end_date = date.fromordinal(w_end_ord)

        # 收集本窗口的交易
        window_pnls: list[float] = []
        for j, d in enumerate(dates_sorted):
            d_ord = d.toordinal()
            if w_start_ord <= d_ord <= w_end_ord:
                window_pnls.append(pnls[j])

        n_w = len(window_pnls)

        if n_w == 0:
            # 空窗口 — 标记为 neutral
            windows.append(WindowStats(
                index=i,
                start_date=w_start_date,
                end_date=w_end_date,
                n_records=0,
                mean_pnl=0.0,
                median_pnl=0.0,
                total_pnl=0.0,
                positive_fraction=0.0,
                is_positive=True,
                major_direction="neutral",
            ))
            continue

        # 计算窗口统计量
        mean_pnl = statistics.mean(window_pnls)
        median_pnl = statistics.median(window_pnls)
        total_pnl = sum(window_pnls)
        n_positive = sum(1 for p in window_pnls if p >= 0)
        positive_fraction = n_positive / n_w
        is_positive_candidate = mean_pnl >= 0
        # 判断方向显著性：平均收益绝对值是否超过阈值
        if abs(mean_pnl) < direction_threshold:
            major_dir = "neutral"
        elif mean_pnl > 0:
            major_dir = "positive"
        else:
            major_dir = "negative"

        windows.append(WindowStats(
            index=i,
            start_date=w_start_date,
            end_date=w_end_date,
            n_records=n_w,
            mean_pnl=mean_pnl,
            median_pnl=median_pnl,
            total_pnl=total_pnl,
            positive_fraction=positive_fraction,
            is_positive=mean_pnl >= 0,
            major_direction=major_dir,
        ))

    # ---------- 确定主导方向 ----------
    # 使用非中性窗口的多数决（majority vote），避免正负窗口等量抵消导致 neutral
    # 当出现平局（各半）时，取记录数更多的方向；记录数也相等时取 positive
    non_neutral_windows = [w for w in windows if w.n_records > 0 and w.major_direction != "neutral"]
    if not non_neutral_windows:
        # 所有窗口都是 neutral 或空 → 整体 neutral
        dominant_direction = "neutral"
        overall_mean = 0.0
    else:
        # 加权投票：方向权重 = |mean| * n_records
        pos_weight = sum(abs(w.mean_pnl) * w.n_records for w in non_neutral_windows if w.major_direction == "positive")
        neg_weight = sum(abs(w.mean_pnl) * w.n_records for w in non_neutral_windows if w.major_direction == "negative")
        if pos_weight > neg_weight:
            dominant_direction = "positive"
        elif neg_weight > pos_weight:
            dominant_direction = "negative"
        else:
            # 平局：取记录数更多的方向
            pos_count = sum(w.n_records for w in non_neutral_windows if w.major_direction == "positive")
            neg_count = sum(w.n_records for w in non_neutral_windows if w.major_direction == "negative")
            if pos_count >= neg_count:
                dominant_direction = "positive"
            else:
                dominant_direction = "negative"
        # 同时仍然计算加权均值用于 details
        weighted_dir_sum = sum(w.mean_pnl * w.n_records for w in windows if w.n_records > 0)
        total_weight = sum(w.n_records for w in windows if w.n_records > 0)
        overall_mean = weighted_dir_sum / total_weight if total_weight > 0 else 0.0

    details["overall_weighted_mean"] = round(overall_mean, 6)

    # ---------- 检测不一致窗口 ----------
    inconsistent_indices: list[int] = []
    reverse_magnitudes: list[float] = []

    for w in windows:
        if w.n_records == 0:
            continue  # 空窗口不判定

        # 如果某窗口的方向与主导方向相反，且幅度不可忽略
        is_opposite = (
            (dominant_direction == "positive" and w.major_direction == "negative")
            or (dominant_direction == "negative" and w.major_direction == "positive")
        )

        if is_opposite:
            # 检查幅度是否不可忽略
            # 使用平均绝对偏离的比率作为严重程度
            reverse_magnitudes.append(abs(w.mean_pnl))

            if abs(w.mean_pnl) >= direction_threshold:
                inconsistent_indices.append(w.index)
            # 否则相反但幅度小于阈值 → 视为可忽略噪声

    # 计算不一致严重程度
    if inconsistent_indices:
        # 取全窗口平均绝对收益作为基准
        all_abs_means = [abs(w.mean_pnl) for w in windows if w.n_records > 0]
        avg_abs_mean = statistics.mean(all_abs_means) if all_abs_means else 1.0
        # 不一致窗口的平均反向幅度 / 平均绝对收益基准
        avg_reverse = statistics.mean(reverse_magnitudes) if reverse_magnitudes else 0.0
        inconsistency_severity = avg_reverse / avg_abs_mean if avg_abs_mean > 0 else 1.0
    else:
        inconsistency_severity = 0.0

    details["inconsistent_indices"] = inconsistent_indices

    # ---------- 稳定性判定 ----------
    is_stable = len(inconsistent_indices) == 0

    # ---------- 置信度计算 ----------
    # 基础：窗口一致性比率
    consistent_windows = _N_WINDOWS - len(inconsistent_indices) - sum(1 for w in windows if w.n_records == 0)
    total_nonempty = sum(1 for w in windows if w.n_records > 0)
    if total_nonempty == 0:
        confidence = 0.0
    else:
        consistency_ratio = consistent_windows / total_nonempty  # 0 ~ 1

        # 变异系数惩罚：各窗口 mean_pnl 的变异系数越小越稳定
        nonempty_means = [w.mean_pnl for w in windows if w.n_records > 0]
        if len(nonempty_means) >= 2:
            cv = statistics.stdev(nonempty_means) / abs(statistics.mean(nonempty_means)) if abs(statistics.mean(nonempty_means)) > 1e-12 else 999
            cv_penalty = min(cv / 5.0, 1.0)  # CV 超过 5 倍则完全降权
        else:
            cv_penalty = 0.0  # 只有一个非空窗口不惩罚

        # 样本量修正：记录数越多越可信
        n_factor = min(n_total / 50.0, 1.0)

        confidence = consistency_ratio * (1.0 - cv_penalty * 0.3) * (0.7 + 0.3 * n_factor)
        confidence = max(0.0, min(1.0, confidence))

    details["total_nonempty_windows"] = total_nonempty
    details["consistency_ratio"] = round(consistency_ratio, 4) if total_nonempty > 0 else 0.0
    details["cv_penalty"] = round(cv_penalty, 4) if total_nonempty >= 2 else 0.0
    details["sample_n_factor"] = round(n_factor, 4)

    # ---------- 失败原因 ----------
    fail_reason = None
    if not is_stable:
        inconsistent_desc = []
        for idx in inconsistent_indices:
            w = windows[idx]
            inconsistent_desc.append(
                f"窗口 {idx + 1} ({w.start_date} ~ {w.end_date}): "
                f"方向={w.major_direction}, 均值={w.mean_pnl:.4%}"
            )
        fail_reason = (
            f"TEMPORAL_INCONSISTENCY: 在 {len(inconsistent_indices)}/{_N_WINDOWS} "
            f"个子窗口中方向与主导方向 ({dominant_direction}) 相反且不可忽略。"
            f"不一致窗口: {'; '.join(inconsistent_desc)}"
        )

    return TemporalStabilityResult(
        is_stable=is_stable,
        confidence=round(confidence, 4),
        windows=windows,
        dominant_direction=dominant_direction,
        inconsistent_windows=inconsistent_indices,
        inconsistency_severity=round(inconsistency_severity, 4),
        details=details,
        fail_reason=fail_reason,
    )


# ============================================================
# 便捷函数：快速标签判定
# ============================================================

def is_temporally_consistent(trades: list[TradeRecord], *, threshold: float = _DEFAULT_DIRECTION_THRESHOLD) -> bool:
    """快速判断是否通过时间稳定性检查（布尔值）

    Parameters
    ----------
    trades : list[TradeRecord]
        交易/观测记录
    threshold : float
        方向相反判定阈值

    Returns
    -------
    bool
    """
    return validate_temporal_stability(trades, direction_threshold=threshold).is_stable
