# -*- coding: utf-8 -*-
"""
signal_lifecycle.py — 信号生命周期追踪模块（P1-MX-003）

追踪信号从生成到完成的全生命周期状态变迁。

状态定义：
    PENDING → VALIDATED → RISK_CHECKED → QUANTITY_CALC → SUBMITTED → FILLED / REJECTED

持久化：
    signals/lifecycle/{signal_id}.json

注意：
    "validate_signal" 在 paper_trade_poller.py 的 scan_signals 阶段已完成；
    此处 VALIDATED 状态在 process_signal 的交易日历检查通过后记录。
    REJECTED 可在 RISK_CHECKED 或 SUBMITTED 阶段出现。

作者：墨衡 (moheng)
创建时间：2026-05-12 20:42 GMT+8
任务：P1-MX-003
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Set
from src.config import SHANGHAI_TZ

logger = logging.getLogger("paper_trade.signal_lifecycle")

TZ_CST = SHANGHAI_TZ

_DEFAULT_LIFECYCLE_DIR = r"C:\Users\17699\mo_zhi_sharereports\signals\lifecycle"


# ============================================================
# 状态常量
# ============================================================

class SignalStatus:
    """信号生命周期状态常量。"""
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    RISK_CHECKED = "RISK_CHECKED"
    QUANTITY_CALC = "QUANTITY_CALC"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"

    # 终态集合（到达后不再继续变迁）
    TERMINAL_STATES: Set[str] = {FILLED, REJECTED}

    # 所有有效状态
    ALL_STATES: List[str] = [
        PENDING, VALIDATED, RISK_CHECKED, QUANTITY_CALC, SUBMITTED, FILLED, REJECTED,
    ]


# ============================================================
# 生命周期追踪器
# ============================================================

class SignalLifecycleTracker:
    """信号生命周期追踪器。

    管理每个信号从生成到完成的状态变迁记录，
    持久化到 JSON 文件。

    Attributes:
        lifecycle_dir: 生命周期文件存储目录
    """

    def __init__(self, lifecycle_dir: str = _DEFAULT_LIFECYCLE_DIR):
        self.lifecycle_dir = lifecycle_dir

    # ────────────────────────────────────────────────
    # 核心方法
    # ────────────────────────────────────────────────

    def track(self, signal_id: str, status: str,
              metadata: Optional[Dict[str, Any]] = None) -> bool:
        """记录信号状态变更。

        Args:
            signal_id: 信号 ID（task_id）
            status: 目标状态（SignalStatus 常量）
            metadata: 额外元数据（可选）

        Returns:
            是否记录成功

        Note:
            状态不会降级：如果当前状态在状态列表中位于目标之后，
            则忽略此次调用（幂等保护）。
        """
        os.makedirs(self.lifecycle_dir, exist_ok=True)
        filepath = self._get_filepath(signal_id)

        existing = self._read_record(filepath) or {}
        history: List[Dict[str, Any]] = existing.get("history", [])

        # 幂等：禁止状态降级
        current = existing.get("current_status")
        if current and status in SignalStatus.ALL_STATES and current in SignalStatus.ALL_STATES:
            cur_idx = SignalStatus.ALL_STATES.index(current)
            new_idx = SignalStatus.ALL_STATES.index(status)
            if new_idx < cur_idx:
                logger.warning(
                    "生命周期状态降级被禁止: %s %s→%s (idx %d→%d)",
                    signal_id, current, status, cur_idx, new_idx,
                )
                return False

        # 构建状态变更条目
        entry: Dict[str, Any] = {
            "status": status,
            "timestamp": self._now_iso(),
        }
        if metadata:
            entry["metadata"] = metadata

        history.append(entry)

        record = {
            "signal_id": signal_id,
            "current_status": status,
            "history": history,
            "created_at": existing.get("created_at", self._now_iso()),
            "updated_at": self._now_iso(),
        }

        return self._write_record(filepath, record)

    def get_status(self, signal_id: str) -> Optional[str]:
        """获取信号最新状态。

        Args:
            signal_id: 信号 ID

        Returns:
            最新状态字符串，或 None（不存在）
        """
        record = self._read_record(self._get_filepath(signal_id))
        if record is None:
            return None
        return record.get("current_status")

    def get_history(self, signal_id: str) -> List[Dict[str, Any]]:
        """获取信号完整状态变迁记录。

        Args:
            signal_id: 信号 ID

        Returns:
            状态变迁列表（按时间顺序），空列表表示无记录
        """
        record = self._read_record(self._get_filepath(signal_id))
        if record is None:
            return []
        return record.get("history", [])

    def get_all_active(self) -> List[Dict[str, Any]]:
        """获取所有未进入终态的活跃信号。

        Returns:
            活跃信号记录列表（按 created_at 升序）
        """
        if not os.path.isdir(self.lifecycle_dir):
            return []

        active: List[Dict[str, Any]] = []
        for fname in sorted(os.listdir(self.lifecycle_dir)):
            if not fname.endswith(".json"):
                continue
            fp = os.path.join(self.lifecycle_dir, fname)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    record: Dict[str, Any] = json.load(f)
                if record.get("current_status") not in SignalStatus.TERMINAL_STATES:
                    active.append(record)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("读取生命周期文件失败: %s — %s", fp, e)

        active.sort(key=lambda r: r.get("created_at", ""))
        return active

    # ────────────────────────────────────────────────
    # 内部方法
    # ────────────────────────────────────────────────

    def _get_filepath(self, signal_id: str) -> str:
        """获取信号生命周期文件路径。"""
        return os.path.join(self.lifecycle_dir, f"{signal_id}.json")

    def _read_record(self, filepath: str) -> Optional[Dict[str, Any]]:
        """读取生命周期文件。"""
        if not os.path.isfile(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("读取生命周期文件失败: %s — %s", filepath, e)
            return None

    def _write_record(self, filepath: str, record: Dict[str, Any]) -> bool:
        """写入生命周期文件（含写后验证）。"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        tmp_path = filepath + ".tmp"

        for attempt in range(1, 4):
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(record, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, filepath)

                # 写后 read 验证
                with open(filepath, "r", encoding="utf-8") as f:
                    verify: Dict[str, Any] = json.load(f)

                if verify.get("signal_id") == record["signal_id"] and \
                   verify.get("current_status") == record["current_status"]:
                    logger.debug("生命周期写入验证通过: %s — %s",
                                 record["signal_id"], record["current_status"])
                    return True

                logger.warning("生命周期写入验证失败 (重试 %d/3): %s",
                               attempt, filepath)

            except Exception as e:
                logger.warning("生命周期写入异常 (重试 %d/3): %s — %s",
                               attempt, filepath, e)

        logger.error("生命周期写入 3 次均失败: %s", filepath)
        return False

    @staticmethod
    def _now_iso() -> str:
        """获取当前时间的 ISO8601 格式字符串（+08:00）。"""
        return datetime.now(TZ_CST).isoformat()
