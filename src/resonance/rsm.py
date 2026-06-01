"""
RSM — 共振状态机模块

实现 NONE → WARN → ACTIVE → DECAY 完整状态转换，采用读→判→写闭环：
  read state → compute strength → decide transition → persist

核心逻辑：
  1. compute_strength()：从 ZNM 的 z-score 映射到 [0, 1] 共振强度
  2. _decide_transition()：状态机转换决策（含过期自动归零）
  3. compute()：主入口，读→判→写闭环执行

状态流转：
  NONE  ──(strength > MIN_STRENGTH)──────────────→ WARN
  WARN  ──(连续达标 ≥ CONSECUTIVE_FOR_ACTIVE)───→ ACTIVE
  WARN  ──(违反 + 超期 > WARN_EXPIRY_DAYS)──────→ NONE
  WARN  ──(强度回落)─────────────────────────────→ DECAY
  ACTIVE─(strength > MIN_STRENGTH)──────────────→ ACTIVE（保持）
  ACTIVE─(强度回落)─────────────────────────────→ DECAY
  DECAY ──(强度恢复)─────────────────────────────→ ACTIVE
  DECAY ──(DECAY_EXPIRY_DAYS 到期)──────────────→ NONE
  DECAY ──(强度不足+未到期)──────────────────────→ DECAY（保持）

关键阈值：
  - |z-score| > QUANTILE_THRESHOLD (1.5) → 共振强度增加
  - strength > RESONANCE_MIN_STRENGTH (0.6) → WARN 触发
  - WARN_EXPIRY_DAYS (5日) → WARN 超时自动归零
  - DECAY_EXPIRY_DAYS (10日) → DECAY 超时自动归零

引用：
  - src.resonance.constants: QUANTILE_THRESHOLD, RESONANCE_MIN_STRENGTH,
    WARN_EXPIRY_DAYS, DECAY_EXPIRY_DAYS
  - src.resonance.models: RSMState, RSMPipelineState, ModuleStatus
  - src.resonance.lookback_buffer: LookbackBuffer（状态同步）
  - src.resonance.znm: ZNMResult（输入来源）

Usage:
    >>> from src.resonance.rsm import compute, compute_strength
    >>> from src.resonance.znm import compute as znm_compute
    >>> import numpy as np
    >>> hv = np.array([0.15, 0.18, 0.22, 0.20, 0.25], dtype=np.float64)
    >>> znm_result = znm_compute("601857.SH", hv)
    >>> state = compute("601857.SH", znm_result)
    >>> state.current_state
    <RSMState.NONE: 'NONE'>

    >>> strength = compute_strength(2.0)
    >>> strength
    0.8

Author: moheng
Created: 2026-05-29T10:18:00+08:00
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from numpy.typing import NDArray

from src.resonance.constants import (
    DECAY_EXPIRY_DAYS,
    QUANTILE_THRESHOLD,
    RESONANCE_MIN_STRENGTH,
    WARN_EXPIRY_DAYS,
)
from src.resonance.lookback_buffer import LookbackBuffer
from src.resonance.models import (
    ModuleStatus,
    RSMState,
    RSMPipelineState,
    SignalHistoryEntry,
)
from src.resonance.znm import ZNMResult

logger = logging.getLogger("resonance.rsm")

# ══════════════════════════════════════════════════════════
# 共振强度映射参数
# ══════════════════════════════════════════════════════════

_CONVERSION_FACTOR: float = RESONANCE_MIN_STRENGTH / QUANTILE_THRESHOLD
"""|z-score| → strength 线性转换因子。

公式：strength = min(1.0, |zscore| * RESONANCE_MIN_STRENGTH / QUANTILE_THRESHOLD)

锚点：
  |zscore| = 0                     → strength = 0.0
  |zscore| = QUANTILE_THRESHOLD (1.5) → strength = RESONANCE_MIN_STRENGTH (0.6)
  |zscore| = 1.0 / factor ≈ 2.5    → strength = 1.0（饱和）
"""

CONSECUTIVE_FOR_ACTIVE: int = 3
"""WARN → ACTIVE 所需的最低连续达标天数。

当连续 CONSECUTIVE_FOR_ACTIVE 日 strength > RESONANCE_MIN_STRENGTH 时，
状态从 WARN 升级至 ACTIVE。
"""

_RSM_PERSIST_DIR: str = "data/rsm_state"
"""RSM 状态机专用持久化目录（相对项目根）。

每标的独立 JSON 文件：{ticker}_rsm.json。
独立于 LookbackBuffer 的持久化路径，避免共振状态与滚动窗口数据混存。
"""


# ══════════════════════════════════════════════════════════
# 项目根路径解析
# ══════════════════════════════════════════════════════════


def _resolve_project_root() -> Path:
    """从模块位置向上查找项目根（包含 src/ 目录的父目录）。

    搜索策略：
      1. 从 __file__ 所在目录向上查找
      2. 找到包含 .git 目录的 src/ 父目录
      3. 回退：假设为 src/ 的上两级

    Returns:
        Path: 项目根目录的绝对路径。
    """
    module_dir = Path(__file__).resolve().parent  # src/resonance/
    for parent in [module_dir, *module_dir.parents]:
        if parent.name == "src" and (parent.parent / ".git").is_dir():
            return parent.parent
    return (module_dir / ".." / "..").resolve()


_PROJECT_ROOT: Path = _resolve_project_root()


# ══════════════════════════════════════════════════════════
# 共振强度计算
# ══════════════════════════════════════════════════════════


def compute_strength(zscore: float) -> float:
    """从 z-score 计算共振强度。

    映射 |z-score| 到 [0, 1] 的强度值。

    线性映射策略：
      strength = min(1.0, |zscore| * RESONANCE_MIN_STRENGTH / QUANTILE_THRESHOLD)

    关键锚点：
      - |zscore| = 0                     → strength = 0.0   （无偏离）
      - |zscore| = QUANTILE_THRESHOLD    → strength = 0.6   （达标阈值）
      - |zscore| = 1.0 / _CONVERSION_FACTOR ≈ 2.5 → strength = 1.0 （饱和）

    Args:
        zscore: z-score 值（来自 ZNM 模块）。

    Returns:
        float: 共振强度 [0, 1]。
            非有限值（NaN/Inf）返回 0.0。
    """
    if not np.isfinite(zscore):
        return 0.0
    abs_z = abs(zscore)
    raw = abs_z * _CONVERSION_FACTOR
    return min(1.0, raw)


# ══════════════════════════════════════════════════════════
# RSM 状态持久化
# ══════════════════════════════════════════════════════════


def _get_rsm_persist_dir() -> Path:
    """获取 RSM 状态持久化目录的绝对路径。

    Returns:
        Path: RSM 持久化目录路径。
    """
    return _PROJECT_ROOT / _RSM_PERSIST_DIR


def _ensure_rsm_dir() -> Path:
    """确保持久化目录存在。

    Returns:
        Path: 确保存在的持久化目录路径。
    """
    persist_dir = _get_rsm_persist_dir()
    persist_dir.mkdir(parents=True, exist_ok=True)
    return persist_dir


def _ticker_to_filename(ticker: str) -> str:
    """将标的代码转换为安全的 RSM 状态文件名。

    Args:
        ticker: 标的代码，如 '601857.SH' 或 '600519'。

    Returns:
        str: 安全的文件名（不含扩展名）。
    """
    safe = ticker.replace("/", "_").replace("\\", "_").replace("..", "_")
    return f"{safe}_rsm.json"


def _ticker_filepath(ticker: str) -> Path:
    """获取指定标的的完整 RSM 状态文件路径。

    Args:
        ticker: 标的代码。

    Returns:
        Path: RSM 状态文件的完整路径。
    """
    return _get_rsm_persist_dir() / _ticker_to_filename(ticker)


# ══════════════════════════════════════════════════════════
# RSMPipelineState 序列化 / 反序列化
# ══════════════════════════════════════════════════════════


def _state_to_dict(state: RSMPipelineState) -> Dict:
    """将 RSMPipelineState 转换为 JSON 可序列化字典。

    Args:
        state: RSMPipelineState 实例。

    Returns:
        dict: JSON 兼容字典。
    """
    return {
        "current_state": state.current_state.value,
        "warn_consecutive_strength": state.warn_consecutive_strength,
        "warn_total_days": state.warn_total_days,
        "consecutive_decay_days": state.consecutive_decay_days,
        "run_count": state.run_count,
        "last_signal_date": state.last_signal_date,
        "history": [
            {
                "date": entry.date,
                "signal_type": entry.signal_type,
                "strength": entry.strength,
                "reason": entry.reason,
                "state": entry.state.value,
            }
            for entry in state.history
        ],
    }


def _dict_to_state(d: Dict) -> RSMPipelineState:
    """将字典反序列化为 RSMPipelineState。

    Args:
        d: 包含 RSMPipelineState 字段的字典。

    Returns:
        RSMPipelineState: 恢复的状态实例。
            解析失败的字段使用默认值。
    """
    state_str = d.get("current_state", RSMState.NONE.value)
    try:
        current_state = RSMState(state_str)
    except ValueError:
        current_state = RSMState.NONE

    history: List[SignalHistoryEntry] = []
    for entry in d.get("history", []):
        if not isinstance(entry, dict):
            continue
        try:
            entry_state = RSMState(entry.get("state", RSMState.NONE.value))
        except ValueError:
            entry_state = RSMState.NONE
        history.append(
            SignalHistoryEntry(
                date=str(entry.get("date", "")),
                signal_type=str(entry.get("signal_type", "")),
                strength=float(entry.get("strength", 0.0)),
                reason=str(entry.get("reason", "")),
                state=entry_state,
            )
        )

    return RSMPipelineState(
        current_state=current_state,
        warn_consecutive_strength=int(d.get("warn_consecutive_strength", 0)),
        warn_total_days=int(d.get("warn_total_days", 0)),
        consecutive_decay_days=int(d.get("consecutive_decay_days", 0)),
        run_count=int(d.get("run_count", 0)),
        last_signal_date=str(d.get("last_signal_date", "")),
        history=history,
    )


# ══════════════════════════════════════════════════════════
# 原子写入
# ══════════════════════════════════════════════════════════


def _atomic_write_json(filepath: Path, data: Dict) -> None:
    """原子方式写入 JSON 状态文件。

    先写入临时文件再 rename 到目标路径，
    避免写入过程中 crash 导致文件损坏。

    Args:
        filepath: 目标文件路径。
        data: 要写入的 JSON 数据字典。

    Raises:
        OSError: 目录不可写或写入操作失败。
    """
    temp_path = filepath.with_name(f"._{filepath.name}.{os.getpid()}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(filepath)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════
# 状态加载 / 保存
# ══════════════════════════════════════════════════════════


def load_state(ticker: str) -> RSMPipelineState:
    """加载指定标的的 RSM 管道状态。

    如果持久化文件不存在，返回初始状态（NONE, 无历史）。
    文件损坏时自动重置为初始状态并记录警告。

    Args:
        ticker: 标的代码。

    Returns:
        RSMPipelineState: 加载的持久化状态或初始状态。
    """
    filepath = _ticker_filepath(ticker)
    if not filepath.exists():
        logger.debug("RSM [%s]: 无持久化状态，使用默认 NONE", ticker)
        return RSMPipelineState(
            current_state=RSMState.NONE,
            warn_consecutive_strength=0,
            warn_total_days=0,
            consecutive_decay_days=0,
            run_count=0,
            last_signal_date="",
            history=[],
        )

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
        state = _dict_to_state(raw)
        logger.debug("RSM [%s]: 加载持久化状态 %s (run=%d)",
                     ticker, state.current_state.value, state.run_count)
        return state
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.warning("RSM [%s]: 状态文件损坏 (%s)，重置为 NONE", ticker, e)
        return RSMPipelineState(
            current_state=RSMState.NONE,
            warn_consecutive_strength=0,
            warn_total_days=0,
            consecutive_decay_days=0,
            run_count=0,
            last_signal_date="",
            history=[],
        )


def save_state(ticker: str, state: RSMPipelineState) -> None:
    """持久化指定标的的 RSM 管道状态。

    使用原子写入策略保证数据完整性。
    自动创建持久化目录。

    Args:
        ticker: 标的代码。
        state: 要持久化的 RSMPipelineState 实例。

    Raises:
        ValueError: ticker 为空。
        OSError: 目录创建或文件写入失败。
    """
    if not ticker:
        raise ValueError("ticker must not be empty")

    # 确保目录存在
    _ensure_rsm_dir()

    # 序列化 + 原子写入
    filepath = _ticker_filepath(ticker)
    payload = _state_to_dict(state)
    _atomic_write_json(filepath, payload)

    logger.debug("RSM [%s]: 持久化状态 %s (run=%d, warn_str=%d, warn_total=%d, decay=%d)",
                 ticker, state.current_state.value, state.run_count,
                 state.warn_consecutive_strength, state.warn_total_days,
                 state.consecutive_decay_days)


# ══════════════════════════════════════════════════════════
# 状态机转换决策
# ══════════════════════════════════════════════════════════


def decide_transition(
    current_state: RSMState,
    strength: float,
    warn_consecutive_strength: int,
    warn_total_days: int,
    consecutive_decay_days: int,
) -> Tuple[RSMState, int, int, int, bool]:
    """共振状态机转换决策。

    根据当前状态、共振强度和双计数器决定下一步状态。

    双计数器机制（D1 修复 — 方案A）：
      - warn_consecutive_strength: 进入 WARN 后，强度达标日依次递增；
        强度不达标的日重置为 0。用于 WARN → ACTIVE 升级判断。
      - warn_total_days: 进入 WARN 后的总历日天数（含强度不达标日）。
        每次调用 +1（仅 WARN 状态）。用于超期归零 NONE。
      - 两者并行：谁先满足条件谁触发，互不阻塞。

    状态机规则：
      ┌─────────────────┬─────────────────────────────────────────┬──────────────┐
      │ 当前状态          │ 条件                                     │ 下一状态      │
      ├─────────────────┼─────────────────────────────────────────┼──────────────┤
      │ NONE            │ strength > RESONANCE_MIN_STRENGTH        │ WARN         │
      │ NONE            │ strength ≤ 阈值                          │ NONE（保持）  │
      ├─────────────────┼─────────────────────────────────────────┼──────────────┤
      │ WARN            │ 连续达标 ≥ CONSECUTIVE_FOR_ACTIVE        │ ACTIVE       │
      │ WARN            │ 超 WARN_EXPIRY_DAYS 总历日未达 ACTIVE    │ NONE         │
      │ WARN            │ 强度回落 + 未超期                         │ DECAY        │
      │ WARN            │ 达标但未达条件 + 未超期                    │ WARN（保持）  │
      ├─────────────────┼─────────────────────────────────────────┼──────────────┤
      │ ACTIVE          │ strength > 阈值                           │ ACTIVE（保持）│
      │ ACTIVE          │ strength ≤ 阈值                           │ DECAY        │
      ├─────────────────┼─────────────────────────────────────────┼──────────────┤
      │ DECAY           │ strength > 阈值（恢复）                    │ ACTIVE       │
      │ DECAY           │ 超 DECAY_EXPIRY_DAYS                     │ NONE         │
      │ DECAY           │ 未超期强度不足                             │ DECAY（保持） │
      └─────────────────┴─────────────────────────────────────────┴──────────────┘

    Args:
        current_state:             当前共振状态。
        strength:                  当日共振强度 [0, 1]。
        warn_consecutive_strength: 强度达标连续天数（仅 WARN 状态有效）。
        warn_total_days:           进入 WARN 后的总历日天数（仅 WARN 状态有效）。
        consecutive_decay_days:    已连续处于 DECAY 的天数（含当日）。

    Returns:
        Tuple[RSMState, int, int, int, bool]:
          - new_state:                    转换后的状态
          - new_warn_consecutive_strength: 更新后的达标连续天数
          - new_warn_total_days:           更新后的 WARN 总历日天数
          - new_decay_days:                更新后的连续 DECAY 天数
          - state_changed:                是否发生了状态转换
    """
    strength_ok = strength > RESONANCE_MIN_STRENGTH

    # ── NONE ──────────────────────────────────
    if current_state == RSMState.NONE:
        if strength_ok:
            # 进入 WARN：两个计数器均从 1 开始
            return (RSMState.WARN, 1, 1, 0, True)
        return (RSMState.NONE, 0, 0, 0, False)

    # ── WARN ──────────────────────────────────
    if current_state == RSMState.WARN:
        # 每次调用 WARN，总历日天数 +1（含强度不达标日）
        new_warn_total = warn_total_days + 1

        if strength_ok:
            new_warn_strength = warn_consecutive_strength + 1

            # 优先检查升级 ACTIVE（正信号优先）
            if new_warn_strength >= CONSECUTIVE_FOR_ACTIVE:
                return (RSMState.ACTIVE, new_warn_strength, new_warn_total, 0, True)

            # 达标但未达条件：检查是否超期
            if new_warn_total >= WARN_EXPIRY_DAYS:
                return (RSMState.NONE, 0, 0, 0, True)

            # 仍在 WARN 期限内保持
            return (RSMState.WARN, new_warn_strength, new_warn_total, 0, False)

        # 强度不足：重置达标连续计数
        new_warn_strength = 0

        # 检查是否超期
        if new_warn_total >= WARN_EXPIRY_DAYS:
            return (RSMState.NONE, 0, 0, 0, True)

        # 强度回落，进入 DECAY
        return (RSMState.DECAY, 0, 0, 1, True)

    # ── ACTIVE ────────────────────────────────
    if current_state == RSMState.ACTIVE:
        if strength_ok:
            return (RSMState.ACTIVE, 0, 0, 0, False)
        return (RSMState.DECAY, 0, 0, 1, True)

    # ── DECAY ─────────────────────────────────
    if current_state == RSMState.DECAY:
        if strength_ok:
            # 强度恢复 → 重回 ACTIVE
            return (RSMState.ACTIVE, 0, 0, 0, True)

        new_decay = consecutive_decay_days + 1
        if new_decay >= DECAY_EXPIRY_DAYS:
            # 超期 → 回归 NONE
            return (RSMState.NONE, 0, 0, 0, True)
        return (RSMState.DECAY, 0, 0, new_decay, False)

    # 未知状态 → 安全重置为 NONE
    logger.warning("RSM: 未知状态 %s，安全重置为 NONE", current_state)
    return (RSMState.NONE, 0, 0, 0, True)# ══════════════════════════════════════════════════════════
# 主入口：compute
# ══════════════════════════════════════════════════════════


def compute(
    ticker: str,
    znm_result: ZNMResult,
    *,
    lookback_buffer: Optional[LookbackBuffer] = None,
) -> RSMPipelineState:
    """共振状态机主入口 —— 读→判→写闭环。

    完整执行流程（按顺序）：
      1. 验证 ZNM 输入状态（仅 PASS 时执行共振计算）
      2. 读取或初始化 RSM 持久化状态
      3. 计算当日共振强度
      4. 执行状态转换决策
      5. 更新 RSMPipelineState 字段
      6. 持久化更新后的状态（原子写入）
      7. 同步 LookbackBuffer 中的 resonance_state（如果提供）

    执行规则：
      - ZNM 非 PASS → 仅递增 run_count，不改变状态
      - 标的首次运行 → 自动从 NONE 初始状态开始
      - 状态转换发生时记录 INFO 日志
      - WARN 超期（> WARN_EXPIRY_DAYS 仍未升级）→ 回退 NONE
      - DECAY 超期（> DECAY_EXPIRY_DAYS 仍无恢复）→ 回退 NONE

    Args:
        ticker:         标的代码（如 '601857.SH'）。
        znm_result:     ZNMResult 实例（至少包含 zscore 和 status）。
        lookback_buffer: LookbackBuffer 实例（可选）。提供时会同步更新
                         LookbackData.resonance_state 字段，使下游模块
                         能通过 LookbackBuffer 读取共振状态。

    Returns:
        RSMPipelineState: 更新后的管道状态。
          - current_state:          当前共振状态
          - warn_consecutive_strength:  强度达标连续天数
          - warn_total_days:            进入 WARN 后总历日天数
          - consecutive_decay_days:     连续 DECAY 天数
          - run_count:              运行总次数
          - last_signal_date:       最近信号日期
          - history:                信号历史记录

    Example:
        基础用法（带 LookbackBuffer 同步）:
        >>> from src.resonance.lookback_buffer import LookbackBuffer
        >>> from src.resonance.znm import compute as znm_compute
        >>> import numpy as np
        >>> hv = np.array([0.12, 0.15, 0.18, 0.22, 0.30], dtype=np.float64)
        >>> znm_result = znm_compute("601857.SH", hv)
        >>> buf = LookbackBuffer()
        >>> state = compute("601857.SH", znm_result, lookback_buffer=buf)
        >>> state.current_state
        <RSMState.WARN: 'WARN'>
    """
    # ── Step 1: 验证 ZNM 输入 ────────────────
    if znm_result is None or znm_result.status != ModuleStatus.PASS:
        logger.warning(
            "RSM [%s]: ZNM 状态不可用 (%s)，跳过共振计算（仅递增 run_count）",
            ticker,
            znm_result.status if znm_result is not None else "None",
        )
        state = load_state(ticker)
        state.run_count += 1
        save_state(ticker, state)
        return state

    # ── Step 2: 读取持久化状态 ────────────────
    state = load_state(ticker)
    prev_state = state.current_state

    # ── Step 3: 计算共振强度 ──────────────────
    strength = compute_strength(znm_result.zscore)

    logger.info(
        "RSM [%s]: z-score=%.4f, strength=%.4f, prev_state=%s "
        "(warn_str=%d, warn_total=%d, decay=%d)",
        ticker,
        znm_result.zscore,
        strength,
        prev_state.value,
        state.warn_consecutive_strength,
        state.warn_total_days,
        state.consecutive_decay_days,
    )

    # ── Step 4: 状态转换决策 ──────────────────
    new_state, new_warn_strength, new_warn_total, new_decay_days, state_changed = decide_transition(
        current_state=prev_state,
        strength=strength,
        warn_consecutive_strength=state.warn_consecutive_strength,
        warn_total_days=state.warn_total_days,
        consecutive_decay_days=state.consecutive_decay_days,
    )

    if state_changed:
        logger.info(
            "RSM [%s]: 状态转换 %s → %s (strength=%.4f, warn_str=%d, warn_total=%d, decay=%d)",
            ticker, prev_state.value, new_state.value,
            strength, new_warn_strength, new_warn_total, new_decay_days,
        )

    # ── Step 5: 更新状态对象 ──────────────────
    state.current_state = new_state
    state.warn_consecutive_strength = new_warn_strength
    state.warn_total_days = new_warn_total
    state.consecutive_decay_days = new_decay_days
    state.run_count += 1

    # ── Step 6: 持久化 ────────────────────────
    save_state(ticker, state)

    # ── Step 7: 同步 LookbackBuffer ───────────
    if lookback_buffer is not None:
        try:
            lb_data = lookback_buffer.load(ticker)
            if lb_data is not None:
                lb_data.resonance_state = new_state
                lookback_buffer.save(ticker, lb_data)
        except Exception as e:
            logger.warning(
                "RSM [%s]: LookbackBuffer 同步失败 (%s)，不影响状态机主流程",
                ticker, e,
            )

    return state


# ══════════════════════════════════════════════════════════
# 便捷接口
# ══════════════════════════════════════════════════════════


def get_current_state(ticker: str) -> RSMState:
    """获取指定标的的当前共振状态（便捷接口）。

    仅读取持久化状态，不触发任何计算或写入。
    用于高频查询场景（如策略层每秒读取状态）。

    Args:
        ticker: 标的代码。

    Returns:
        RSMState: 当前共振状态。持久化文件不存在时返回 NONE。
    """
    state = load_state(ticker)
    return state.current_state


def reset_state(ticker: str) -> None:
    """重置指定标的的 RSM 状态为初始值。

    清空所有运行计数、历史记录，状态回归 NONE。
    用于重新初始化或错误恢复场景。

    Args:
        ticker: 标的代码。
    """
    initial_state = RSMPipelineState(
        current_state=RSMState.NONE,
        warn_consecutive_strength=0,
        warn_total_days=0,
        consecutive_decay_days=0,
        run_count=0,
        last_signal_date="",
        history=[],
    )
    save_state(ticker, initial_state)
    logger.info("RSM [%s]: 状态已重置为 NONE", ticker)


def clear_all_states() -> int:
    """清除所有标的的 RSM 持久化状态文件。

    用于全局重置或测试清理场景。

    Returns:
        int: 被删除的状态文件数量。
    """
    persist_dir = _get_rsm_persist_dir()
    if not persist_dir.is_dir():
        return 0

    count = 0
    for fpath in list(persist_dir.iterdir()):
        if fpath.suffix == ".json" and fpath.name != ".gitkeep":
            fpath.unlink()
            count += 1

    logger.info("RSM: 已清除 %d 个状态文件", count)
    return count
