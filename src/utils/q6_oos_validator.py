# -*- coding: utf-8 -*-
"""
q6_oos_validator.py — Q6 OOS Validator 样本外存活验证器

检查策略在样本外（Out-of-Sample）期间的表现是否"存活"。
使用时间序列的前 70% 做训练/参数校准，后 30% 做样本外检验。
对比样本内 vs 样本外的绩效指标衰减程度，评估策略泛化能力。

定位：
  Layer Q — Transverse Governance Layer（横向治理层）
  Q6 OOS — 样本外存活维度质量审计

设计说明：
  - 输入：TradeRecord 列表（需含时间戳）+ 分割比例（默认 70/30）
  - 方法：用 Timestamp 前 70% 做训练/校准，后 30% 检验
  - 参考 P4_walkforward 报告的 walkforward 机制：
    - 训练期（训练/校准）→ 测试期（样本外检验）
    - WFE (WalkForward Efficiency) 概念迁移：decay = (in_sample - out_of_sample) / in_sample
  - 当样本外交易数不足时，仅进行保守评估
  - 输出：OOSResult 包含 is_oos_valid, confidence, 双集指标, decay, fail_reason

数据来源：
  - 回测交易记录列表（TradeRecord）
  - 回测引擎输出的绩效指标（可选，提供替代入口）
  - P4_walkforward 输出的 WFE 数据（可选，提供历史参考）

作者：墨衡 (moheng)
创建时间：2026-05-19 17:13 GMT+8
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional, Union

try:
    from src.utils.existence_validator import TradeRecord, _to_date
except ImportError:
    from existence_validator import TradeRecord, _to_date


# ============================================================
# 常量
# ============================================================

_TZ_CST = timezone(timedelta(hours=8), "CST")

# 默认样本分割比例（前 70% 训练，后 30% 检验）
_DEFAULT_TRAIN_RATIO: float = 0.70

# 绩效衰减阈值
# 夏普衰减超过此值标记为 "可能过拟合"
_OOS_DECAY_THRESHOLD_SHARPE: float = 0.40
# 收益衰减超过此值标记为 "泛化失败"
_OOS_DECAY_THRESHOLD_RETURN: float = 0.50

# 样本外最低要求
_OOS_MIN_TRADES_TEST: int = 3        # 测试期最少交易数
_OOS_MIN_TRADES_TRAIN: int = 10      # 训练期最少交易数

# 置信度计算权重
_CONFIDENCE_DECAY_WEIGHT: float = 0.45
_CONFIDENCE_SAMPLE_WEIGHT: float = 0.25
_CONFIDENCE_DIRECTION_WEIGHT: float = 0.15
_CONFIDENCE_CONSISTENCY_WEIGHT: float = 0.15

# 年化因子
_ANNUALIZATION_FACTOR: float = 252.0


# ============================================================
# 数据结构
# ============================================================

@dataclass
class OOSPerfMetrics:
    """样本内/样本外绩效指标"""
    n_trades: int                          # 交易次数
    start_date: str                        # 起始日期
    end_date: str                          # 结束日期
    total_return: float                    # 总收益率
    annual_return: float                   # 年化收益率
    sharpe: float                          # 夏普比率
    win_rate: float                        # 胜率
    avg_return: float                      # 平均单笔收益
    std_return: float                      # 收益标准差
    max_consecutive_losses: int            # 最大连续亏损
    direction: str                         # "positive" / "negative" / "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_trades": self.n_trades,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_return": round(self.total_return, 6),
            "annual_return": round(self.annual_return, 6),
            "sharpe": round(self.sharpe, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_return": round(self.avg_return, 6),
            "std_return": round(self.std_return, 6),
            "max_consecutive_losses": self.max_consecutive_losses,
            "direction": self.direction,
        }


@dataclass
class OOSResult:
    """样本外存活验证结果

    Attributes
    ----------
    is_oos_valid : bool
        True = 样本外存活（测试期方向与训练期相同且衰减可接受）
    confidence : float
        验证置信度 [0.0, 1.0]
    in_sample_metrics : OOSPerfMetrics | None
        训练期（样本内）绩效
    out_of_sample_metrics : OOSPerfMetrics | None
        测试期（样本外）绩效
    decay : float
        绩效衰减程度 [0.0, ~)，0 = 无衰减，>1 = 完全失效
    decay_sharpe : float
        夏普衰减比例
    decay_return : float
        收益衰减比例
    directional_consistent : bool
        训练期与测试期的收益方向是否一致
    fail_reason : str | None
        不通过时的原因说明
    details : dict
        详细辅助信息
    """
    is_oos_valid: bool
    confidence: float
    in_sample_metrics: Optional[OOSPerfMetrics]
    out_of_sample_metrics: Optional[OOSPerfMetrics]
    decay: float
    decay_sharpe: float
    decay_return: float
    directional_consistent: bool
    fail_reason: Optional[str]
    details: dict[str, Any]


# ============================================================
# 绩效指标计算
# ============================================================

def _compute_metrics(
    trades: list[TradeRecord],
    label: str,
) -> OOSPerfMetrics:
    """从 TradeRecord 列表计算绩效指标

    Parameters
    ----------
    trades : list[TradeRecord]
        交易记录列表（需按日期排序）
    label : str
        标签（"in_sample" / "out_of_sample"），用于日志

    Returns
    -------
    OOSPerfMetrics
    """
    if not trades:
        return OOSPerfMetrics(
            n_trades=0,
            start_date="",
            end_date="",
            total_return=0.0,
            annual_return=0.0,
            sharpe=0.0,
            win_rate=0.0,
            avg_return=0.0,
            std_return=0.0,
            max_consecutive_losses=0,
            direction="neutral",
        )

    dates = [_to_date(t.date) for t in trades]
    pnls = [t.pnl_pct for t in trades]
    n = len(pnls)

    start_str = datetime.combine(dates[0], datetime.min.time(), tzinfo=_TZ_CST).isoformat()
    end_str = datetime.combine(dates[-1], datetime.min.time(), tzinfo=_TZ_CST).isoformat()

    total_return = sum(pnls)
    avg_return = total_return / n

    # 收益标准差
    if n >= 2:
        std_return = statistics.stdev(pnls)
    else:
        std_return = 0.0

    # 年化夏普
    if std_return > 0 and n >= 2:
        daily_sharpe = avg_return / std_return
        sharpe = daily_sharpe * math.sqrt(_ANNUALIZATION_FACTOR)
    else:
        sharpe = total_return if n == 1 else 0.0

    # 年化收益
    if n >= 1:
        # 用交易次数估算天数（简化）
        estimated_days = min(max(n, 2), len(dates))
        if estimated_days >= 2:
            time_span_years = (dates[-1] - dates[0]).days / 365.25 if len(dates) >= 2 else 1.0 / 365.25
            annual_return = total_return / max(time_span_years, 1.0 / 365.25)
        else:
            annual_return = total_return * _ANNUALIZATION_FACTOR
    else:
        annual_return = 0.0

    # 胜率
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n if n > 0 else 0.0

    # 最大连续亏损
    max_consecutive = 0
    current_consecutive = 0
    for p in pnls:
        if p < 0:
            current_consecutive += 1
            max_consecutive = max(max_consecutive, current_consecutive)
        else:
            current_consecutive = 0

    # 方向判断
    if abs(total_return) < 0.001:
        direction = "neutral"
    elif total_return > 0:
        direction = "positive"
    else:
        direction = "negative"

    return OOSPerfMetrics(
        n_trades=n,
        start_date=start_str,
        end_date=end_str,
        total_return=round(total_return, 6),
        annual_return=round(annual_return, 4),
        sharpe=round(sharpe, 4),
        win_rate=round(win_rate, 4),
        avg_return=round(avg_return, 6),
        std_return=round(std_return, 6),
        max_consecutive_losses=max_consecutive,
        direction=direction,
    )


def _split_trades_by_time(
    trades: list[TradeRecord],
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
) -> tuple[list[TradeRecord], list[TradeRecord]]:
    """按时间顺序分割交易记录为训练集和测试集

    Parameters
    ----------
    trades : list[TradeRecord]
        交易记录列表
    train_ratio : float
        训练集比例 [0.0, 1.0]，默认 0.70

    Returns
    -------
    tuple[list[TradeRecord], list[TradeRecord]]
        (训练集记录, 测试集记录)
    """
    sorted_trades = sorted(trades, key=lambda t: _to_date(t.date))
    n = len(sorted_trades)
    split_idx = int(n * train_ratio)

    # 确保至少包含 1 条记录
    split_idx = max(1, min(split_idx, n - 1))

    train_trades = sorted_trades[:split_idx]
    test_trades = sorted_trades[split_idx:]

    return train_trades, test_trades


# ============================================================
# 核心验证函数
# ============================================================

def validate_oos(
    trades: list[TradeRecord],
    *,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    decay_threshold_sharpe: float = _OOS_DECAY_THRESHOLD_SHARPE,
    decay_threshold_return: float = _OOS_DECAY_THRESHOLD_RETURN,
    min_trades_train: int = _OOS_MIN_TRADES_TRAIN,
    min_trades_test: int = _OOS_MIN_TRADES_TEST,
) -> OOSResult:
    """对交易记录执行样本外存活验证

    核心逻辑（参考 P4 WalkForward 机制）：
      1. 按时间排序交易记录
      2. 前 train_ratio 作为训练集（样本内），后 (1-train_ratio) 作为测试集（样本外）
      3. 分别计算绩效指标
      4. 计算衰减：decay = (in_sample - out_of_sample) / in_sample
      5. 检查方向一致性和衰减程度

    Parameters
    ----------
    trades : list[TradeRecord]
        交易记录列表（需含时间戳）
    train_ratio : float
        训练集比例，默认 0.70（前 70% 训练，后 30% 测试）
    decay_threshold_sharpe : float
        夏普衰减阈值，超越此值视为"可能过拟合"。默认 0.40
    decay_threshold_return : float
        收益衰减阈值，超越此值视为"泛化失败"。默认 0.50
    min_trades_train : int
        训练期最少交易数。默认 10
    min_trades_test : int
        测试期最少交易数。默认 3

    Returns
    -------
    OOSResult
    """
    details: dict[str, Any] = {}

    # ---------- 空数据防护 ----------
    if not trades:
        return OOSResult(
            is_oos_valid=False,
            confidence=0.0,
            in_sample_metrics=None,
            out_of_sample_metrics=None,
            decay=0.0,
            decay_sharpe=0.0,
            decay_return=0.0,
            directional_consistent=False,
            fail_reason="无交易记录，无法进行样本外验证",
            details=details,
        )

    # ---------- 数据分割 ----------
    train_trades, test_trades = _split_trades_by_time(trades, train_ratio)

    details["n_total_trades"] = len(trades)
    details["n_train_trades"] = len(train_trades)
    details["n_test_trades"] = len(test_trades)
    details["train_ratio"] = train_ratio

    # ---------- 最低交易数检查 ----------
    if len(train_trades) < min_trades_train:
        return OOSResult(
            is_oos_valid=False,
            confidence=0.0,
            in_sample_metrics=None,
            out_of_sample_metrics=None,
            decay=0.0,
            decay_sharpe=0.0,
            decay_return=0.0,
            directional_consistent=False,
            fail_reason=(
                f"训练期交易数 {len(train_trades)} < "
                f"阈值 {min_trades_train}，统计不足"
            ),
            details=details,
        )

    # ---------- 计算绩效 ----------
    train_metrics = _compute_metrics(train_trades, "in_sample")
    test_metrics = _compute_metrics(test_trades, "out_of_sample")

    details["in_sample"] = train_metrics.to_dict()
    details["out_of_sample"] = test_metrics.to_dict()

    # ---------- 测试期交易数检查 ----------
    if len(test_trades) < min_trades_test:
        # 样本外交易不足，标记为"样本外不可验证"
        # 不是硬性不通过，而是降低置信度
        details["test_insufficient"] = True
        # 返回保守评估
        return OOSResult(
            is_oos_valid=False,
            confidence=0.15,  # 极低置信度
            in_sample_metrics=train_metrics,
            out_of_sample_metrics=test_metrics,
            decay=1.0,
            decay_sharpe=1.0,
            decay_return=1.0,
            directional_consistent=True,
            fail_reason=(
                f"测试期交易数 {len(test_trades)} < "
                f"阈值 {min_trades_test}，样本外统计不足，无法确认存活"
            ),
            details=details,
        )

    # ---------- 方向一致性 ----------
    train_direction = train_metrics.direction
    test_direction = test_metrics.direction
    directional_consistent = (
        (train_direction == test_direction) or
        (train_direction == "neutral") or
        (test_direction == "neutral")
    )
    details["train_direction"] = train_direction
    details["test_direction"] = test_direction
    details["directional_consistent"] = directional_consistent

    # ---------- 衰减计算 ----------
    # 夏普衰减（参考 P4 WFE 概念）
    if train_metrics.sharpe > 0:
        decay_sharpe = max(0.0, (train_metrics.sharpe - test_metrics.sharpe) / train_metrics.sharpe)
    elif train_metrics.sharpe < 0:
        # 训练期夏普为负，测试期越差越衰减
        decay_sharpe = max(0.0, (test_metrics.sharpe - train_metrics.sharpe) / abs(train_metrics.sharpe))
    else:
        decay_sharpe = abs(test_metrics.sharpe) if test_metrics.sharpe != 0 else 0.0

    # 收益衰减
    if abs(train_metrics.total_return) > 1e-12:
        decay_return = max(
            0.0,
            (train_metrics.total_return - test_metrics.total_return) / abs(train_metrics.total_return)
        )
    else:
        decay_return = abs(test_metrics.total_return) if abs(test_metrics.total_return) > 1e-12 else 0.0

    # 综合衰减（参考 P4 WFE 概念的平均值）
    decay = (decay_sharpe + decay_return) / 2.0
    decay = min(max(decay, 0.0), 2.0)  # 限制在合理范围

    details["decay_sharpe"] = round(decay_sharpe, 4)
    details["decay_return"] = round(decay_return, 4)
    details["decay_composite"] = round(decay, 4)

    # ---------- 通过判定 ----------
    # 通过条件：
    #   1. 方向一致
    #   2. 夏普衰减 < 阈值
    #   3. 收益衰减 < 阈值
    #   4. 测试期收益为正（保守约束）
    is_oos_valid = (
        directional_consistent
        and decay_sharpe < decay_threshold_sharpe
        and decay_return < decay_threshold_return
        and test_metrics.total_return > 0  # 样本外至少为正
    )

    # ---------- 置信度计算 ----------
    # 衰减评分：衰减越小，评分越高
    decay_score = max(0.0, 1.0 - decay)

    # 样本量充足度
    n_factor_train = min(len(train_trades) / 30.0, 1.0)
    n_factor_test = min(len(test_trades) / 10.0, 1.0)
    sample_score = (n_factor_train * 0.6 + n_factor_test * 0.4)

    # 方向一致性评分
    direction_score = 1.0 if directional_consistent else 0.3

    # 测试期 Sharpe 正负一致性
    consistency_score = 0.0
    if train_metrics.sharpe > 0 and test_metrics.sharpe > 0:
        consistency_score = 1.0
    elif train_metrics.sharpe < 0 and test_metrics.sharpe < 0:
        consistency_score = 0.8
    elif train_metrics.sharpe < 0 < test_metrics.sharpe:
        consistency_score = 0.5
    else:
        consistency_score = 0.2

    confidence = (
        decay_score * _CONFIDENCE_DECAY_WEIGHT
        + sample_score * _CONFIDENCE_SAMPLE_WEIGHT
        + direction_score * _CONFIDENCE_DIRECTION_WEIGHT
        + consistency_score * _CONFIDENCE_CONSISTENCY_WEIGHT
    )
    confidence = min(max(confidence, 0.0), 1.0)

    # ---------- 失败原因 ----------
    fail_reason: Optional[str] = None
    if not is_oos_valid:
        reasons: list[str] = []
        if not directional_consistent:
            reasons.append(
                f"方向不一致：训练期={train_direction}, 测试期={test_direction}"
            )
        if decay_sharpe >= decay_threshold_sharpe:
            reasons.append(
                f"夏普衰减 {decay_sharpe:.1%} ≥ 阈值 {decay_threshold_sharpe:.0%}"
            )
        if decay_return >= decay_threshold_return:
            reasons.append(
                f"收益衰减 {decay_return:.1%} ≥ 阈值 {decay_threshold_return:.0%}"
            )
        if test_metrics.total_return <= 0:
            reasons.append(
                f"测试期总收益为 {test_metrics.total_return:+.4f}，样本内收益期望为负"
            )
        fail_reason = "; ".join(reasons) if reasons else "样本外存活验证不通过"

    return OOSResult(
        is_oos_valid=is_oos_valid,
        confidence=round(confidence, 4),
        in_sample_metrics=train_metrics,
        out_of_sample_metrics=test_metrics,
        decay=round(decay, 4),
        decay_sharpe=round(decay_sharpe, 4),
        decay_return=round(decay_return, 4),
        directional_consistent=directional_consistent,
        fail_reason=fail_reason,
        details=details,
    )


# ============================================================
# 从 WalkForward 结果构建验证
# ============================================================

def validate_from_walkforward(
    train_sharpe: float,
    test_sharpe: float,
    train_return: float,
    test_return: float,
    *,
    train_n_trades: int = 5,
    test_n_trades: int = 3,
    decay_threshold_sharpe: float = _OOS_DECAY_THRESHOLD_SHARPE,
    decay_threshold_return: float = _OOS_DECAY_THRESHOLD_RETURN,
) -> OOSResult:
    """从 WalkForward 的单个窗格结果构建 OOS 验证

    适用于已有完整回测引擎绩效指标的场景（如 P4 WalkForward 输出）。

    Parameters
    ----------
    train_sharpe : float
        训练期夏普比率
    test_sharpe : float
        测试期夏普比率
    train_return : float
        训练期总收益率
    test_return : float
        测试期总收益率
    train_n_trades : int
        训练期交易数
    test_n_trades : int
        测试期交易数
    decay_threshold_sharpe : float
        夏普衰减阈值
    decay_threshold_return : float
        收益衰减阈值

    Returns
    -------
    OOSResult
    """
    # 构建模拟的 TradeRecord（仅用于指标承载）
    train_sim = [
        TradeRecord(date="2024-01-01", pnl_pct=train_return / max(train_n_trades, 1), regime="TREND_UP")
        for _ in range(train_n_trades)
    ]
    test_sim = [
        TradeRecord(date="2025-01-01", pnl_pct=test_return / max(test_n_trades, 1), regime="TREND_UP")
        for _ in range(test_n_trades)
    ]

    # 注入计算好的 Sharpe / return
    from dataclasses import replace

    combined = train_sim + test_sim
    result = validate_oos(
        combined,
        train_ratio=train_n_trades / max(len(combined), 1),
        decay_threshold_sharpe=decay_threshold_sharpe,
        decay_threshold_return=decay_threshold_return,
        min_trades_train=1,
        min_trades_test=1,
    )

    # 覆盖计算的指标为实际 WalkForward 输出
    in_sample = result.in_sample_metrics
    out_sample = result.out_of_sample_metrics

    if in_sample is not None:
        in_sample.sharpe = train_sharpe
        in_sample.total_return = train_return
    if out_sample is not None:
        out_sample.sharpe = test_sharpe
        out_sample.total_return = test_return

    # 重新计算衰减
    if train_sharpe > 0:
        result.decay_sharpe = max(0.0, (train_sharpe - test_sharpe) / train_sharpe)
    else:
        result.decay_sharpe = 0.0

    if abs(train_return) > 1e-12:
        result.decay_return = max(
            0.0, (train_return - test_return) / abs(train_return)
        )
    else:
        result.decay_return = 0.0

    result.decay = (result.decay_sharpe + result.decay_return) / 2.0
    result.decay = round(result.decay, 4)

    return result


# ============================================================
# 快速 PASS/FAIL 判定
# ============================================================

def is_oos_valid(
    trades: list[TradeRecord],
    *,
    train_ratio: float = _DEFAULT_TRAIN_RATIO,
    decay_threshold_sharpe: float = _OOS_DECAY_THRESHOLD_SHARPE,
    decay_threshold_return: float = _OOS_DECAY_THRESHOLD_RETURN,
) -> bool:
    """快速判定样本外存活是否通过

    Parameters
    ----------
    trades : list[TradeRecord]
        交易记录
    train_ratio : float
        训练集比例
    decay_threshold_sharpe : float
        夏普衰减阈值
    decay_threshold_return : float
        收益衰减阈值

    Returns
    -------
    bool
    """
    return validate_oos(
        trades,
        train_ratio=train_ratio,
        decay_threshold_sharpe=decay_threshold_sharpe,
        decay_threshold_return=decay_threshold_return,
    ).is_oos_valid


def format_oos_summary(result: OOSResult) -> str:
    """格式化 OOS 验证结果为可读字符串"""
    lines: list[str] = [
        "=" * 56,
        "  样本外存活验证报告 (Q6 OOS Validator)",
        "=" * 56,
        f"  OOS 存活:      {'✅ 通过' if result.is_oos_valid else '🔴 不通过'}",
        f"  置信度:        {result.confidence:.1%}",
        f"  方向一致:      {'✅ 一致' if result.directional_consistent else '⚠️ 不一致'}",
        f"  综合衰减:      {result.decay:.2%}",
        f"  夏普衰减:      {result.decay_sharpe:.1%}",
        f"  收益衰减:      {result.decay_return:.1%}",
        f"  失败原因:      {result.fail_reason or '无'}",
        "=" * 56,
    ]

    if result.in_sample_metrics:
        im = result.in_sample_metrics
        lines.extend([
            "  样本内 (In-Sample) 绩效:",
            f"    n={im.n_trades} | 总收益={im.total_return:+.4f} | "
            f"Sharpe={im.sharpe:.2f} | 胜率={im.win_rate:.1%}",
        ])

    if result.out_of_sample_metrics:
        om = result.out_of_sample_metrics
        lines.extend([
            "  样本外 (Out-of-Sample) 绩效:",
            f"    n={om.n_trades} | 总收益={om.total_return:+.4f} | "
            f"Sharpe={om.sharpe:.2f} | 胜率={om.win_rate:.1%}",
        ])

    lines.extend([
        "=" * 56,
        f"  总交易数:      {result.details.get('n_total_trades', 0)}",
        f"  训练/测试分割: {result.details.get('n_train_trades', 0)}"
        f" / {result.details.get('n_test_trades', 0)}",
        "=" * 56,
    ])
    return "\n".join(lines)
