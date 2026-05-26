# -*- coding: utf-8 -*-
"""
existence_validator.py — 策略存在性验证器 (Phase 0a MVP)

验证回测策略或因子分析结果是否具有统计意义的"存在性"。
6项检查覆盖样本量、状态覆盖、时间跨度、收益集中度、信号密度、时间分布。

检查项一览:
  C1 最小交易数   N >= 30   统计显著性门槛
  C2 多Regime覆盖 K >= 2    不在单一市场状态下有效
  C3 多年度覆盖   T >= 2年  跨时间周期验证
  C4 非单段收益   最大单笔占比 < 40%  不依赖极端单次交易
  C5 信号密度     年均 >= 12          低频策略边界标注
  C6 样本分布     非集中于单窗口      时间分布均匀性

设计说明:
  - 通用设计：TradeRecord 接受任意观测（交易/IC值/信号），由调用方决定语义
  - C6 使用等宽分窗法检测时间集中度
  - 置信度采用加权平均，C1 占 30%，其余各占 10%~15%

作者：墨衡 (moheng)
创建时间：2026-05-19 16:00 GMT+8
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Union


# ============================================================
# 数据结构
# ============================================================

@dataclass
class TradeRecord:
    """单笔交易或单次分析观测记录"""
    date: Union[datetime, date, str]  # 交易日期/观测日期
    pnl_pct: float                    # 收益率(%) 或 IC 值
    regime: str                       # 市场状态标签


@dataclass
class ExistenceResult:
    """存在性验证结果"""
    exists: bool              # 全部通过 = True
    confidence: float         # 0.0 ~ 1.0
    fail_reasons: list[str]   # 未通过项的说明
    details: dict             # 每项检查的详细值


# ============================================================
# 内部常量
# ============================================================

_C6_WINDOWS = 10          # 时间分布检测窗口数
_C6_MAX_FRACTION = 0.50   # 单一窗口最大占比（默认）
_CONFIDENCE_WEIGHTS = {   # 各检查项权重（C1 最高）
    "C1": 0.30,
    "C2": 0.15,
    "C3": 0.15,
    "C4": 0.10,
    "C5": 0.15,
    "C6": 0.15,
}


# ============================================================
# 工具函数
# ============================================================

def _to_date(d: Union[datetime, date, str]) -> date:
    """统一转换为 date 对象"""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    raise TypeError(f"不支持的日期类型: {type(d)}")


# ============================================================
# 主验证函数
# ============================================================

def validate_existence(
    trades: list[TradeRecord],
    *,
    c1_min_trades: int = 30,
    c2_min_regimes: int = 2,
    c3_min_years: float = 2.0,
    c4_max_share: float = 0.40,
    c5_min_density: float = 12.0,
    c6_max_fraction: float = 0.50,
) -> ExistenceResult:
    """
    对交易/观测记录执行6项存在性验证。

    Parameters
    ----------
    trades : list[TradeRecord]
        交易或观测记录列表。允许传入任何类型的观测数据
        （回测交易、IC值、信号点等），由调用方决定语义。
    c1_min_trades : int
        C1 阈值：最小交易/观测数。默认 30。
    c2_min_regimes : int
        C2 阈值：最少市场状态覆盖数。默认 2。
    c3_min_years : float
        C3 阈值：最小时间跨度（年）。默认 2.0。
    c4_max_share : float
        C4 阈值：最大单笔收益（绝对值）占总额比例。默认 0.40。
    c5_min_density : float
        C5 阈值：年均最低信号密度。默认 12.0。
    c6_max_fraction : float
        C6 阈值：单时间窗口最大样本占比。默认 0.50。

    Returns
    -------
    ExistenceResult
    """
    fail_reasons: list[str] = []
    details: dict[str, object] = {}

    n = len(trades)

    # ---------- C1: 最小交易数 ----------
    details["C1_n_trades"] = n
    details["C1_threshold"] = c1_min_trades
    c1_pass = n >= c1_min_trades
    if not c1_pass:
        fail_reasons.append(
            f"C1 最小交易数: 当前 {n} < 阈值 {c1_min_trades}"
            "（统计显著性不足）"
        )

    if n == 0:
        return ExistenceResult(
            exists=False,
            confidence=0.0,
            fail_reasons=["无任何交易/观测记录"],
            details=details,
        )

    # 提取字段并排序
    dates = sorted([_to_date(t.date) for t in trades])
    regimes = [t.regime for t in trades]
    pnls_abs = [abs(t.pnl_pct) for t in trades]

    # ---------- C2: 多Regime覆盖 ----------
    unique_regimes = set(regimes)
    details["C2_n_regimes"] = len(unique_regimes)
    details["C2_regimes"] = sorted(unique_regimes)
    details["C2_threshold"] = c2_min_regimes
    c2_pass = len(unique_regimes) >= c2_min_regimes
    if not c2_pass:
        fail_reasons.append(
            f"C2 多Regime覆盖: 当前 {len(unique_regimes)} < 阈值 {c2_min_regimes}"
            f"（仅在 {', '.join(sorted(unique_regimes))} 下有效）"
        )

    # ---------- C3: 多年度覆盖 ----------
    time_span_days = (dates[-1] - dates[0]).days
    time_span_years = time_span_days / 365.25
    details["C3_time_span_days"] = time_span_days
    details["C3_time_span_years"] = round(time_span_years, 2)
    details["C3_threshold_years"] = c3_min_years
    c3_pass = time_span_years >= c3_min_years
    if not c3_pass:
        fail_reasons.append(
            f"C3 多年度覆盖: 当前 {time_span_years:.2f}年 < 阈值 {c3_min_years}年"
            f"（跨度仅 {time_span_days} 天）"
        )

    # ---------- C4: 非单段收益 ----------
    total_pnl_abs = sum(pnls_abs)
    if total_pnl_abs > 0:
        # 使用绝对值计算，避免正负抵消
        max_single_share = max(pnls_abs) / total_pnl_abs
    else:
        max_single_share = 0.0
    details["C4_max_single_share"] = round(max_single_share, 4)
    details["C4_threshold"] = c4_max_share
    c4_pass = max_single_share < c4_max_share
    if not c4_pass:
        fail_reasons.append(
            f"C4 非单段收益: 最大单笔占比 {max_single_share:.1%} >= 阈值 {c4_max_share:.0%}"
            "（收益依赖极端单次交易）"
        )

    # ---------- C5: 信号密度 ----------
    effective_years = max(time_span_years, 1.0 / 365.25)  # 至少 1 天，避免除零
    density = n / effective_years
    details["C5_density"] = round(density, 2)
    details["C5_threshold"] = c5_min_density
    c5_pass = density >= c5_min_density
    if not c5_pass:
        fail_reasons.append(
            f"C5 信号密度: 年均 {density:.1f} 次 < 阈值 {c5_min_density} 次"
            "（信号过稀疏，低频策略边界）"
        )

    # ---------- C6: 样本分布 ----------
    window_counts = [0] * _C6_WINDOWS
    # 起始和结束日期
    start_date = dates[0]
    end_date = dates[-1]
    total_span = (end_date - start_date).days
    if total_span <= 0:
        # 同一天的所有观测视为集中在同一窗口
        window_counts[0] = n
    else:
        for d in dates:
            offset = (d - start_date).days
            idx = min(
                _C6_WINDOWS - 1,
                int(offset / total_span * _C6_WINDOWS),
            )
            window_counts[idx] += 1

    max_window_fraction = max(window_counts) / n
    # 找出最大窗口索引（如果有多个取第一个）
    max_window_idx = window_counts.index(max(window_counts))

    details["C6_n_windows"] = _C6_WINDOWS
    details["C6_window_counts"] = window_counts
    details["C6_max_window_fraction"] = round(max_window_fraction, 4)
    details["C6_max_window_index"] = max_window_idx  # 0-based
    details["C6_threshold"] = c6_max_fraction
    c6_pass = max_window_fraction <= c6_max_fraction
    if not c6_pass:
        fail_reasons.append(
            f"C6 样本分布: 最大窗口占比 {max_window_fraction:.1%} > 阈值 {c6_max_fraction:.0%}"
            f"（样本集中于窗口 {max_window_idx + 1}/{_C6_WINDOWS}）"
        )

    # ---------- 综合判定 ----------
    all_pass = c1_pass and c2_pass and c3_pass and c4_pass and c5_pass and c6_pass
    passes = [c1_pass, c2_pass, c3_pass, c4_pass, c5_pass, c6_pass]
    weights = [_CONFIDENCE_WEIGHTS[f"C{i+1}"] for i in range(6)]
    confidence = sum(w * p for w, p in zip(weights, passes))
    confidence = round(confidence, 4)

    return ExistenceResult(
        exists=all_pass,
        confidence=confidence,
        fail_reasons=fail_reasons,
        details=details,
    )
