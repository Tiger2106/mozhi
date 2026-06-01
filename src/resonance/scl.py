"""
SCL — 信号消费层模块 (Signal Consumption Layer)

接收 SG 产生的共振信号 → 记录/持久化/通知。
Phase 0 简化实现：仅记录信号日志和文件持久化，不涉及实际交易。

核心功能:
  1. consume()       — 信号消费主入口
  2. inquiry()       — 信号转调查询（按标的+日期回查历史信号）
  3. SignalSummaryDict — 信号摘要 TypedDict（各类信号计数+统计）
  4. SCLResult        — 消费结果 TypedDict（summary/recommendation/signals_count/status）

Phase 0 约束:
  - 不涉及实际交易执行（无可交易接口调用）
  - 信号消费仅体现为日志输出和文件持久化
  - 信号历史持久化至 {SCL_HISTORY_DIR}/{ticker}/{date}.json
  - 消费结果持久化至 {SCL_RESULT_DIR}/{ticker}/{date}.json

Usage:
    >>> from src.resonance.models import ResonanceSignal, RSMState
    >>> from src.resonance.scl import consume, inquiry
    >>>
    >>> # 消费 SG 信号
    >>> signals = [
    ...     ResonanceSignal(
    ...         signal_type="BUY", strength=0.75, position_cap=1.0,
    ...         reason="共振确认买入", timestamp="2026-05-29T10:00:00+08:00",
    ...         state=RSMState.ACTIVE, source_module="SG", confidence=0.85,
    ...         symbol="601857.SH", suggested_price=8.50,
    ...     ),
    ... ]
    >>> result = consume("601857.SH", signals)
    >>> result["status"]
    'PASS'
    >>> result["summary"]["buy_signals"]
    1
    >>>
    >>> # 信号转调查询
    >>> q = inquiry("601857.SH", date="20260529")
    >>> q["inquiry_result"]["total_matched"]
    1

依赖:
    - src.resonance.models: ResonanceSignal, ModuleStatus, ModuleResult, RSMState
    - src.resonance.constants: SIGNAL_OUTPUT_DIR, LB_PERSIST_PATH, FULL_PASS_CAP

Author: moheng
Created: 2026-05-29T11:30:00+08:00
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from src.resonance.constants import (
    FULL_PASS_CAP,
    LB_PERSIST_PATH,
    SIGNAL_OUTPUT_DIR,
)
from src.resonance.models import (
    ModuleResult,
    ModuleStatus,
    ResonanceSignal,
    RSMState,
    SignalHistoryEntry,
)

logger = logging.getLogger("resonance.scl")

# ══════════════════════════════════════════════════════════
# SCL 内部路径常量
# ══════════════════════════════════════════════════════════

SCL_HISTORY_DIR: str = "data/signal_history"
"""SCL 信号历史持久化目录（相对项目根）。
按标的和日期组织：{SCL_HISTORY_DIR}/{ticker}/{date}.json"""

SCL_RESULT_DIR: str = "results/scl"
"""SCL 消费结果输出目录（相对项目根）。
输出 SCLResult JSON 文件供上层系统消费。"""


# ══════════════════════════════════════════════════════════
# SCLResult — 信号消费结果 TypedDict
# ══════════════════════════════════════════════════════════


class SignalSummaryDict(TypedDict, total=False):
    """信号摘要 TypedDict。

    统计一次 consume() 或 inquiry() 涉及的信号分布。
    """

    total_signals: int
    """总信号数。"""

    buy_signals: int
    """BUY 类型信号数。"""

    sell_signals: int
    """SELL 类型信号数。"""

    hold_signals: int
    """HOLD 类型信号数。"""

    average_strength: float
    """所有信号的平均共振强度 [0, 1]。"""

    average_confidence: float
    """所有信号的平均置信度 [0, 1]。"""

    latest_signal: Optional[Dict[str, Any]]
    """最新信号的字典表示。None 表示无信号。"""

    period_start: str
    """统计周期起始（ISO8601 +08:00）。"""

    period_end: str
    """统计周期结束（ISO8601 +08:00）。"""


class SCLResult(TypedDict, total=False):
    """信号消费结果 TypedDict。

    由 SCL.consume() 和 SCL.inquiry() 返回。
    使用 TypedDict 确保 JSON 序列化友好，兼容下游消费。

    Fields:
        summary         : 信号摘要（各类信号计数和统计）
        recommendation  : 操作建议文本
        signals_count   : 本次消费/查询的信号总数
        status          : SCL 模块执行状态（PASS | FAILED | SKIPPED）
        inquiry_result  : 信号转调查询详情（仅 inquiry 产生）
    """

    summary: SignalSummaryDict
    """信号摘要。包含 total/buy/sell/hold 计数、平均强度和置信度。"""

    recommendation: str
    """操作建议文本。格式：{信号方向} {强度} — {理由概要}
    Phase 0 仅输出摘要日志，不触发实际交易。"""

    signals_count: int
    """本次消费/查询处理的信号总数。"""

    status: str
    """SCL 模块执行状态。'PASS' | 'FAILED' | 'SKIPPED'。"""

    inquiry_result: Optional[Dict[str, Any]]
    """信号转调查询详情（仅 inquiry() 模式产生）。
    包含 matched_signals 列表和统计信息。未查询时为 None。"""


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


def _signal_to_dict(signal: ResonanceSignal) -> Dict[str, Any]:
    """将 ResonanceSignal 转换为 JSON 友好的字典。

    Args:
        signal: 共振信号 TypedDict。

    Returns:
        dict: JSON 可序列化的信号字典。
    """
    return {
        "signal_type": signal["signal_type"],
        "strength": signal["strength"],
        "position_cap": signal["position_cap"],
        "reason": signal["reason"],
        "timestamp": signal["timestamp"],
        "state": (
            signal["state"].value
            if isinstance(signal["state"], RSMState)
            else signal["state"]
        ),
        "source_module": signal["source_module"],
        "confidence": signal["confidence"],
        "symbol": signal["symbol"],
        "suggested_price": signal["suggested_price"],
    }


def _ensure_dir(path: str) -> str:
    """确保目录存在，返回标准化后的绝对路径。

    Args:
        path: 相对或绝对目录路径。

    Returns:
        str: 标准化后的绝对路径。
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return str(p.resolve())


def _now_iso() -> str:
    """返回当前时间的 ISO8601 +08:00 字符串。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat()


# ══════════════════════════════════════════════════════════
# 摘要构建
# ══════════════════════════════════════════════════════════


def _build_summary(
    signals: List[ResonanceSignal],
    period_start: str,
    period_end: str,
) -> SignalSummaryDict:
    """从信号列表构建 SignalSummaryDict。

    Args:
        signals:       ResonanceSignal 列表（也接受具有同名字段的普通 dict）。
        period_start:  统计周期起始时间 (ISO8601)。
        period_end:    统计周期结束时间 (ISO8601)。

    Returns:
        SignalSummaryDict: 统计摘要。
    """
    if not signals:
        return SignalSummaryDict(
            total_signals=0,
            buy_signals=0,
            sell_signals=0,
            hold_signals=0,
            average_strength=0.0,
            average_confidence=0.0,
            latest_signal=None,
            period_start=period_start,
            period_end=period_end,
        )

    buy_count = sum(1 for s in signals if s.get("signal_type") == "BUY")
    sell_count = sum(1 for s in signals if s.get("signal_type") == "SELL")
    hold_count = sum(1 for s in signals if s.get("signal_type") == "HOLD")

    avg_strength = (
        round(sum(float(s["strength"]) for s in signals) / len(signals), 4)
    )
    avg_confidence = (
        round(sum(float(s["confidence"]) for s in signals) / len(signals), 4)
    )

    # 最新信号（按 timestamp 取最大）
    latest_idx = max(
        range(len(signals)),
        key=lambda i: signals[i].get("timestamp", ""),
    )
    latest_signal = signals[latest_idx]
    latest_dict = {
        k: v
        for k, v in latest_signal.items()
        if k in ("signal_type", "strength", "position_cap", "reason",
                 "timestamp", "state", "source_module", "confidence",
                 "symbol", "suggested_price")
    }
    # 确保 state 是字符串
    if "state" in latest_dict and isinstance(latest_dict["state"], RSMState):
        latest_dict["state"] = latest_dict["state"].value

    return SignalSummaryDict(
        total_signals=len(signals),
        buy_signals=buy_count,
        sell_signals=sell_count,
        hold_signals=hold_count,
        average_strength=avg_strength,
        average_confidence=avg_confidence,
        latest_signal=latest_dict,
        period_start=period_start,
        period_end=period_end,
    )


# ══════════════════════════════════════════════════════════
# 信号日志记录（Phase 0 核心行为）
# ══════════════════════════════════════════════════════════


def _log_signals(signals: List[ResonanceSignal], ticker: str) -> None:
    """在日志中记录信号摘要（Phase 0 核心行为）。

    Phase 0 不涉及实际交易，信号消费的体现形式为结构化日志输出
    和文件持久化。每条信号输出含信号方向/强度/置信度/价格/理由。

    Args:
        signals: 待处理的信号列表。
        ticker:  标的代码。
    """
    if not signals:
        logger.info("SCL [%s]: 无信号需消费", ticker)
        return

    logger.info("SCL [%s]: ══════════ 信号消费 ══════════", ticker)
    logger.info("SCL [%s]: 本次接收信号数: %d", ticker, len(signals))

    for i, sig in enumerate(signals, 1):
        state_str = (
            sig["state"].value
            if isinstance(sig["state"], RSMState)
            else str(sig["state"])
        )
        logger.info(
            "SCL [%s]:   [%d/%d] %s/%s (强度=%.4f, 置信度=%.4f, "
            "价格=%.2f, 仓位上限=%.0f%%) — %s",
            ticker,
            i,
            len(signals),
            sig["signal_type"],
            state_str,
            sig["strength"],
            sig["confidence"],
            sig["suggested_price"],
            sig["position_cap"] * 100,
            sig["reason"],
        )

    buy_count = sum(1 for s in signals if s["signal_type"] == "BUY")
    sell_count = sum(1 for s in signals if s["signal_type"] == "SELL")
    hold_count = sum(1 for s in signals if s["signal_type"] == "HOLD")
    avg_str = sum(s["strength"] for s in signals) / len(signals)

    logger.info(
        "SCL [%s]: 统计 — BUY=%d SELL=%d HOLD=%d | 平均强度=%.4f",
        ticker,
        buy_count,
        sell_count,
        hold_count,
        avg_str,
    )
    logger.info("SCL [%s]: ═══════════════════════════════", ticker)


# ══════════════════════════════════════════════════════════
# 信号持久化
# ══════════════════════════════════════════════════════════


def _persist_signals(
    signals: List[ResonanceSignal],
    ticker: str,
) -> Optional[str]:
    """持久化信号至磁盘文件。

    Phase 0 实现：按标的和日期组织，写入 JSON 数组。
    路径格式：{SCL_HISTORY_DIR}/{ticker}/{YYYYMMDD}.json

    Args:
        signals: 待持久化的信号列表。
        ticker:  标的代码，用于文件组织。

    Returns:
        Optional[str]: 写入成功时返回文件绝对路径，失败返回 None。
    """
    if not signals:
        logger.warning("SCL [%s]: 无信号需持久化", ticker)
        return None

    now = _now_iso()
    date_str = now[:10].replace("-", "")  # YYYYMMDD

    base_dir = _ensure_dir(os.path.join(SCL_HISTORY_DIR, ticker))
    file_path = os.path.join(base_dir, f"{date_str}.json")

    signal_dicts = [_signal_to_dict(s) for s in signals]
    signal_data: Dict[str, Any] = {
        "ticker": ticker,
        "date": date_str,
        "recorded_at": now,
        "signals_count": len(signals),
        "signals": signal_dicts,
    }

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(signal_data, f, ensure_ascii=False, indent=2)
        logger.info(
            "SCL [%s]: 已持久化 %d 条信号 → %s",
            ticker,
            len(signals),
            file_path,
        )
        return file_path
    except OSError as e:
        logger.error("SCL [%s]: 信号持久化失败: %s", ticker, e)
        return None


def _persist_result(result: SCLResult, ticker: str) -> Optional[str]:
    """持久化 SCLResult 至磁盘。

    路径格式：{SCL_RESULT_DIR}/{ticker}/{YYYYMMDD}.json
    供上层系统或下游模块消费。

    Args:
        result: SCL 消费结果 TypedDict。
        ticker: 标的代码。

    Returns:
        Optional[str]: 写入成功返回文件路径，失败返回 None。
    """
    now = _now_iso()
    date_str = now[:10].replace("-", "")

    base_dir = _ensure_dir(os.path.join(SCL_RESULT_DIR, ticker))
    file_path = os.path.join(base_dir, f"{date_str}.json")

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info("SCL [%s]: 已持久化消费结果 → %s", ticker, file_path)
        return file_path
    except OSError as e:
        logger.error("SCL [%s]: 消费结果持久化失败: %s", ticker, e)
        return None


# ══════════════════════════════════════════════════════════
# 操作建议构建
# ══════════════════════════════════════════════════════════


def _build_recommendation(summary: SignalSummaryDict) -> str:
    """基于信号摘要生成操作建议文本。

    Phase 0 建议仅描述信号方向，不附加具体交易指令或仓位配置。

    Args:
        summary: 信号摘要。

    Returns:
        str: 操作建议文本。
    """
    if summary["total_signals"] == 0:
        return "无有效信号，维持当前持仓"

    latest = summary.get("latest_signal")
    if not latest:
        return "信号摘要已生成，无最新信号"

    signal_type = latest.get("signal_type", "HOLD")
    strength = float(latest.get("strength", 0.0))
    reason = latest.get("reason", "")

    strength_label = (
        "强"
        if strength > 0.8
        else ("中" if strength > 0.6 else "弱")
    )

    if signal_type == "BUY":
        return (
            f"买入信号（{strength_label}）: {reason} | "
            f"信号质量{strength_label}等，建议按仓位上限执行"
        )
    elif signal_type == "SELL":
        return f"卖出信号（{strength_label}）: {reason} | 建议减仓或退出"
    elif signal_type == "HOLD":
        return f"持仓信号: {reason} | 保持现有仓位，等待进一步信号"

    return f"未识别信号类型 {signal_type}: {reason}"


# ══════════════════════════════════════════════════════════
# 信号消费主入口：consume
# ══════════════════════════════════════════════════════════


def consume(
    ticker: str,
    signals: List[ResonanceSignal],
    persist: bool = True,
) -> SCLResult:
    """SCL 信号消费主入口。

    接收 SG 生成的信号列表 → 生成摘要 → 记录日志 → 持久化信号。
    Phase 0 不执行实际交易操作。

    处理流程:
      1. 输入验证（类型检查, 空列表 → SKIPPED）
      2. 日志记录（_log_signals）
      3. 构建信号摘要（_build_summary）
      4. 生成操作建议（_build_recommendation）
      5. 持久化信号和消费结果（_persist_signals + _persist_result）
      6. 返回 SCLResult

    Args:
        ticker:  标的代码，如 '601857.SH'。
        signals: 要消费的 ResonanceSignal 列表。
                 通常来自 SG.generate() 的输出。
        persist: 是否持久化信号至磁盘。默认为 True。
                 Phase 0 中建议始终持久化以供 inquiry 查询。

    Returns:
        SCLResult: 信号消费结果。
          - summary:        信号摘要（total/buy/sell/hold 计数等）
          - recommendation: 操作建议文本
          - signals_count:  消费的信号总数
          - status:         SCL 执行状态（PASS | FAILED | SKIPPED）

    状态处理:
      ┌──────────────────────────────┬──────────┬────────────────────────┐
      │ 条件                          │ 状态     │ 行为                   │
      ├──────────────────────────────┼──────────┼────────────────────────┤
      │ 输入 not list                 │ FAILED   │ 类型错误，返回 FAILED  │
      │ 输入为空列表                  │ SKIPPED  │ 无操作，返回空摘要     │
      │ 信号有效且消费成功            │ PASS     │ 正常消费               │
      │ 信号有效但持久化失败          │ PASS     │ 仍标记 PASS（日志优先）│
      └──────────────────────────────┴──────────┴────────────────────────┘

    Example:
        >>> from src.resonance.models import ResonanceSignal, RSMState
        >>>
        >>> signals = [
        ...     ResonanceSignal(
        ...         signal_type="BUY", strength=0.75, position_cap=1.0,
        ...         reason="共振确认", timestamp="2026-05-29T10:00:00+08:00",
        ...         state=RSMState.ACTIVE, source_module="SG", confidence=0.85,
        ...         symbol="601857.SH", suggested_price=8.50,
        ...     ),
        ... ]
        >>> result = consume("601857.SH", signals)
        >>> result["status"]
        'PASS'
        >>> result["summary"]["buy_signals"]
        1
    """
    now = _now_iso()

    # ── Step 1: 输入验证 ──────────────────────────────
    if not isinstance(signals, list):
        logger.error("SCL [%s]: consume 输入无效: 信号列表类型错误", ticker)
        empty_summary = _build_summary([], now, now)
        return SCLResult(
            summary=empty_summary,
            recommendation="信号消费失败：输入无效",
            signals_count=0,
            status=ModuleStatus.FAILED.value,
            inquiry_result=None,
        )

    if not signals:
        logger.info("SCL [%s]: 无信号需消费（SKIPPED）", ticker)
        empty_summary = _build_summary([], now, now)
        return SCLResult(
            summary=empty_summary,
            recommendation="无有效信号，维持当前持仓",
            signals_count=0,
            status=ModuleStatus.SKIPPED.value,
            inquiry_result=None,
        )

    # ── Step 2: 日志记录 ──────────────────────────────
    _log_signals(signals, ticker)

    # ── Step 3: 构建信号摘要 ──────────────────────────
    summary = _build_summary(signals, now, now)
    recommendation = _build_recommendation(summary)

    # ── Step 4: 持久化（可选） ─────────────────────────
    if persist:
        _persist_signals(signals, ticker)
        result_for_persist = SCLResult(
            summary=summary,
            recommendation=recommendation,
            signals_count=len(signals),
            status=ModuleStatus.PASS.value,
            inquiry_result=None,
        )
        _persist_result(result_for_persist, ticker)

    logger.info(
        "SCL [%s]: 信号消费完成 — %d 条信号 | BUY=%d HOLD=%d 平均强度=%.4f",
        ticker,
        len(signals),
        summary["buy_signals"],
        summary["hold_signals"],
        summary["average_strength"],
    )

    # ── Step 5: 构建并返回结果 ──────────────────────
    return SCLResult(
        summary=summary,
        recommendation=recommendation,
        signals_count=len(signals),
        status=ModuleStatus.PASS.value,
        inquiry_result=None,
    )


# ══════════════════════════════════════════════════════════
# 信号转调查询（inquiry 模式）
# ══════════════════════════════════════════════════════════


def inquiry(
    ticker: str,
    date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> SCLResult:
    """信号转调查询。

    按标的和日期范围查询历史信号记录。
    数据源为 SCL 持久化的信号历史文件。

    查询模式:
      - 精确日期模式: date="20260529"
      - 日期范围模式: date_from="20260520", date_to="20260529"

    Args:
        ticker:    标的代码。
        date:      精确日期 (YYYYMMDD)。提供此参数时忽略 date_from/date_to。
        date_from: 起始日期 (YYYYMMDD)。与 date_to 配合使用。
        date_to:   结束日期 (YYYYMMDD)。与 date_from 配合使用。

    Returns:
        SCLResult: 查询结果。
          - summary:        匹配信号的统计摘要
          - recommendation: 基于查询结果的操作建议
          - signals_count:  匹配信号数
          - status:         执行状态
          - inquiry_result: 查询详情（findings, matched_signals, total_matched 等）

    Example:
        >>> # 精确日期查询
        >>> result = inquiry("601857.SH", date="20260529")
        >>> result["signals_count"]
        3
        >>>
        >>> # 日期范围查询
        >>> result = inquiry("601857.SH",
        ...     date_from="20260520", date_to="20260529")
        >>> result["inquiry_result"]["total_matched"]
        5

    Phase 0 实现说明:
      - 查询路径：{SCL_HISTORY_DIR}/{ticker}/
      - 文件命名：{YYYYMMDD}.json
      - 精确模式：读取单文件
      - 范围模式：扫描目录下日期范围内的所有文件
      - 目录不存在时返回 PASS 状态 + 空结果（非错误）
    """
    inquiry_time = _now_iso()
    history_dir = Path(SCL_HISTORY_DIR) / ticker

    # ── 目录检查 ──
    if not history_dir.exists():
        logger.warning(
            "SCL [%s] inquiry: 信号历史目录不存在: %s",
            ticker,
            history_dir,
        )
        empty_summary = _build_summary([], inquiry_time, inquiry_time)
        return SCLResult(
            summary=empty_summary,
            recommendation="无历史信号记录",
            signals_count=0,
            status=ModuleStatus.PASS.value,
            inquiry_result={
                "ticker": ticker,
                "date": date or f"{date_from or '?'}~{date_to or '?'}",
                "findings": "信号历史目录不存在",
                "matched_signals": [],
                "total_matched": 0,
            },
        )

    matched_signals: List[Dict[str, Any]] = []

    # ── 精确日期模式 ──
    if date:
        file_path = history_dir / f"{date}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                matched_signals = data.get("signals", [])
                logger.info(
                    "SCL [%s] inquiry: 读取 %s 共 %d 条信号",
                    ticker,
                    date,
                    len(matched_signals),
                )
            except (json.JSONDecodeError, OSError) as e:
                logger.error(
                    "SCL [%s] inquiry: 读取 %s 失败: %s",
                    ticker,
                    date,
                    e,
                )
        else:
            logger.warning("SCL [%s] inquiry: %s 无信号记录", ticker, date)

    # ── 日期范围模式 ──
    else:
        from_val = int(date_from or "00000000")
        to_val = int(date_to or "99999999")

        try:
            for file in sorted(history_dir.glob("*.json")):
                file_date_str = file.stem
                try:
                    file_date = int(file_date_str)
                except ValueError:
                    continue

                if from_val <= file_date <= to_val:
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    matched_signals.extend(data.get("signals", []))
        except OSError as e:
            logger.error(
                "SCL [%s] inquiry: 扫描信号历史目录失败: %s",
                ticker,
                e,
            )

        logger.info(
            "SCL [%s] inquiry: 范围 %s~%s 共 %d 条信号",
            ticker,
            date_from or "起始",
            date_to or "最新",
            len(matched_signals),
        )

    # ── 构建查询结果 ──
    period_start = date or (date_from or "unknown")
    period_end = date or (date_to or "unknown")

    # matched_signals 是 dict 列表（来自 JSON 反序列化），
    # 直接传递给 _build_summary（其 .get() 方式兼容 dict）
    summary = _build_summary(
        matched_signals,  # type: ignore[arg-type]
        period_start,
        period_end,
    )
    recommendation = _build_recommendation(summary)

    return SCLResult(
        summary=summary,
        recommendation=recommendation,
        signals_count=len(matched_signals),
        status=ModuleStatus.PASS.value,
        inquiry_result={
            "ticker": ticker,
            "date": date or f"{date_from or '?'}~{date_to or '?'}",
            "findings": f"查询到 {len(matched_signals)} 条历史信号",
            "matched_signals": matched_signals,
            "total_matched": len(matched_signals),
            "inquiry_time": inquiry_time,
            "period": {
                "from": date_from or date or "N/A",
                "to": date_to or date or "N/A",
            },
        },
    )
