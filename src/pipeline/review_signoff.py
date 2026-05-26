# -*- coding: utf-8 -*-
"""
review_signoff.py — G3 Multi-Sign Gate 三方会签门控流程

实现串行会签模式：墨萱(技术确认) → 墨涵(知识确认) → Owner(业务确认)。
每个确认步骤记录会签意见 + 时间戳 + 签署方身份，后一个步骤需前一个通过后才触发。

流程定义：
  墨萱 (moxuan) 技术确认  →  tech_review
  墨涵 (mochen) 知识确认  →  knowledge_audit
  Owner         业务确认  →  business_approval

Gate 触发：G3 Gate 在所有 Q1~Q8 验证通过后启动三方会签。
若任一环节结果为 False（需修订），流程中止并写入 Q9a Q_FAILURES。

设计原则（ADR-001, ADR-007）：
  - 双账本系统：G3 是账本B（可信度审计）的人工复核节点
  - 研究者不给自己盖章 → G3 由独立第三方（墨萱）启动技术审查
  - 串行模式确保每一步都基于前一步的审查结论

作者：墨萱 (moxuan)
创建时间：2026-05-19 16:20 GMT+8
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Optional

# ============================================================
# 时区
# ============================================================
_TZ_CST = timezone(timedelta(hours=8), "CST")


def _now_cst() -> str:
    """返回当前 CST (+08:00) ISO8601 字符串"""
    return datetime.now(_TZ_CST).isoformat()


# ============================================================
# 常量定义
# ============================================================

# 会签流程步骤定义（严格串行顺序）
SIGNOFF_STEPS: list[str] = [
    "tech_review",        # 墨萱 — 技术确认
    "knowledge_audit",    # 墨涵 — 知识确认
    "business_approval",  # Owner — 业务确认
]

# 会签步骤说明映射
SIGNOFF_STEP_LABELS: dict[str, str] = {
    "tech_review":        "技术确认 — 墨萱",
    "knowledge_audit":    "知识确认 — 墨涵",
    "business_approval":  "业务确认 — Owner",
}

# 合法签署方 ID
VALID_SIGNERS: set[str] = {"moxuan", "mochen", "owner"}

# 签署方 → 默认负责步骤
SIGNER_TO_DEFAULT_STEP: dict[str, str] = {
    "moxuan": "tech_review",
    "mochen": "knowledge_audit",
    "owner":  "business_approval",
}


# ============================================================
# 异常类型
# ============================================================

class ReviewSignoffError(Exception):
    """会签流程异常"""
    pass


class InvalidStepOrderError(ReviewSignoffError):
    """步骤顺序异常：前一步骤尚未通过"""
    pass


class InvalidSignerError(ReviewSignoffError):
    """无效的签署方"""
    pass


class DuplicateSignoffError(ReviewSignoffError):
    """重复签署：当前步骤已被签署"""
    pass


class SignoffAlreadyFinalizedError(ReviewSignoffError):
    """会签流程已经结束（通过或中止）"""
    pass


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SignOff:
    """单次会签记录

    Attributes
    ----------
    signer_id : str
        签署方身份："moxuan" / "mochen" / "owner"
    step : str
        会签步骤："tech_review" / "knowledge_audit" / "business_approval"
    result : bool
        True = 通过, False = 需修订
    comment : str
        会签意见
    timestamp : str
        ISO8601 格式时间戳 (CST +08:00)
    """
    signer_id: str
    step: str
    result: bool
    comment: str
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _now_cst()

    def to_dict(self) -> dict[str, Any]:
        return {
            "signer_id": self.signer_id,
            "step": self.step,
            "result": self.result,
            "comment": self.comment,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SignOff":
        return cls(
            signer_id=d["signer_id"],
            step=d["step"],
            result=d["result"],
            comment=d["comment"],
            timestamp=d.get("timestamp", ""),
        )


@dataclass
class ReviewSession:
    """一次完整的 G3 三方会签会话

    记录整条策略的会签状态和签署历史。

    Attributes
    ----------
    session_id : str
        会签会话唯一标识
    strategy_id : str
        被审计的策略 ID
    status : str
        当前状态："pending" / "in_progress" / "passed" / "failed" / "aborted"
    signoffs : list[SignOff]
        已完成签署的历史记录
    current_step : str | None
        当前待完成步骤（None 表示未开始或已完成）
    created_at : str
        会话创建时间
    updated_at : str
        最后更新时间
    notes : str
        整体备注（可选）
    """
    session_id: str
    strategy_id: str
    status: str = "pending"
    signoffs: list[SignOff] = field(default_factory=list)
    current_step: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        now = _now_cst()
        if not self.session_id:
            self.session_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.current_step and self.status == "pending":
            self.current_step = SIGNOFF_STEPS[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "strategy_id": self.strategy_id,
            "status": self.status,
            "current_step": self.current_step,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
            "signoffs": [s.to_dict() for s in self.signoffs],
        }


# ============================================================
# 会签流程管理器
# ============================================================

class ReviewSignoffManager:
    """G3 三方会签流程管理器

    管理一次策略审计的三方会签流程，严格执行串行模式：
    墨萱(tech_review) → 墨涵(knowledge_audit) → Owner(business_approval)

    Example
    -------
    >>> mgr = ReviewSignoffManager()
    >>> session = mgr.create_session("grid_601857")
    >>> # 墨萱签署技术确认
    >>> session = mgr.sign(session.session_id, "moxuan", True,
    ...                    "技术验证全部通过，无瓶颈")
    >>> # 墨涵签署知识确认
    >>> session = mgr.sign(session.session_id, "mochen", True,
    ...                    "策略逻辑符合知识体系")
    >>> # Owner 签署业务确认
    >>> session = mgr.sign(session.session_id, "owner", True,
    ...                    "批准上线")
    >>> session.status
    'passed'
    """

    def __init__(self) -> None:
        # 内存中的会话存储（生产环境应替换为持久化存储）
        self._sessions: dict[str, ReviewSession] = {}

    # ---------- 会话管理 ----------

    def create_session(
        self,
        strategy_id: str,
        session_id: Optional[str] = None,
        notes: str = "",
    ) -> ReviewSession:
        """创建一个新的 G3 会签会话

        Parameters
        ----------
        strategy_id : str
            被审计的策略 ID
        session_id : str | None
            会话 ID（可选，自动生成 UUID）
        notes : str
            整体备注（可选）

        Returns
        -------
        ReviewSession
            创建的会签会话
        """
        session = ReviewSession(
            session_id=session_id or str(uuid.uuid4()),
            strategy_id=strategy_id,
            status="pending",
            signoffs=[],
            current_step=SIGNOFF_STEPS[0],
            notes=notes,
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[ReviewSession]:
        """获取会签会话

        Parameters
        ----------
        session_id : str
            会话 ID

        Returns
        -------
        ReviewSession | None
        """
        return self._sessions.get(session_id)

    def list_sessions(self, strategy_id: Optional[str] = None) -> list[ReviewSession]:
        """列出会签会话（可按策略 ID 筛选）

        Parameters
        ----------
        strategy_id : str | None
            策略 ID 筛选（可选）

        Returns
        -------
        list[ReviewSession]
        """
        sessions = list(self._sessions.values())
        if strategy_id:
            sessions = [s for s in sessions if s.strategy_id == strategy_id]
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    # ---------- 签署操作 ----------

    def sign(
        self,
        session_id: str,
        signer_id: str,
        result: bool,
        comment: str,
        *,
        force_step: Optional[str] = None,
    ) -> ReviewSession:
        """执行一次会签签署

        串行约束：
        - 必须按 tech_review → knowledge_audit → business_approval 顺序
        - 前一步未通过（结果为 False）则流程中止，不允许继续

        Parameters
        ----------
        session_id : str
            会签会话 ID
        signer_id : str
            签署方身份："moxuan" / "mochen" / "owner"
        result : bool
            True = 通过, False = 需修订
        comment : str
            会签意见
        force_step : str | None
            强制指定步骤（可选）。默认为按签署方 ID 映射当前应签步骤。
            仅在测试/重签等特殊场景使用。

        Returns
        -------
        ReviewSession
            签署后的会签会话（已更新状态）

        Raises
        ------
        InvalidSignerError
            签署方 ID 不合法
        SignoffAlreadyFinalizedError
            会签流程已经结束
        InvalidStepOrderError
            步骤顺序错误（非当前步骤）
        DuplicateSignoffError
            当前步骤已被签署
        """
        session = self._get_or_raise(session_id)

        # 校验签署方
        if signer_id not in VALID_SIGNERS:
            raise InvalidSignerError(f"无效的签署方: {signer_id}，合法值: {', '.join(VALID_SIGNERS)}")

        # 校验流程状态
        if session.status in ("passed", "failed", "aborted"):
            raise SignoffAlreadyFinalizedError(
                f"会签流程已{session.status}，无法继续签署"
            )

        # 确定应该签署的步骤
        if force_step:
            expected_step = force_step
        elif session.current_step:
            expected_step = session.current_step
        else:
            expected_step = SIGNER_TO_DEFAULT_STEP.get(signer_id, SIGNOFF_STEPS[0])

        # 校验是否为当前待签步骤
        if expected_step != session.current_step:
            # 检查是否误签了后续步骤
            current_idx = SIGNOFF_STEPS.index(session.current_step) if session.current_step else 0
            try:
                expected_idx = SIGNOFF_STEPS.index(expected_step)
            except ValueError:
                raise InvalidStepOrderError(f"未知步骤: {expected_step}")

            if expected_idx < current_idx:
                raise InvalidStepOrderError(
                    f"步骤 {expected_step} 已被签署或跳过，当前待签步骤为 {session.current_step}"
                )
            elif expected_idx > current_idx:
                raise InvalidStepOrderError(
                    f"步骤顺序错误：当前待签步骤为 {session.current_step}，"
                    f"不能直接签署后续步骤 {expected_step}"
                )

        # 校验签署方是否匹配步骤
        default_signer_for_step = self._get_signer_for_step(expected_step)
        if signer_id != default_signer_for_step and not force_step:
            raise InvalidSignerError(
                f"步骤 {expected_step} 应由 {default_signer_for_step} 签署，当前签署方为 {signer_id}"
            )

        # 检查是否重复签署
        existing = [s for s in session.signoffs if s.step == expected_step]
        if existing:
            raise DuplicateSignoffError(
                f"步骤 {expected_step} 已被 {existing[0].signer_id} "
                f"于 {existing[0].timestamp} 签署"
            )

        # ---------- 创建签署记录 ----------
        signoff = SignOff(
            signer_id=signer_id,
            step=expected_step,
            result=result,
            comment=comment,
        )
        session.signoffs.append(signoff)

        # ---------- 更新会话状态 ----------
        current_idx = SIGNOFF_STEPS.index(expected_step)

        if not result:
            # 当前步骤不通过 → 中止流程
            session.status = "failed"
            session.current_step = None
        elif current_idx == len(SIGNOFF_STEPS) - 1:
            # 最后一步通过 → 全流程通过
            session.status = "passed"
            session.current_step = None
        else:
            # 通过，进入下一步
            session.current_step = SIGNOFF_STEPS[current_idx + 1]
            session.status = "in_progress"

        session.updated_at = _now_cst()
        self._sessions[session.session_id] = session
        return session

    # ---------- 流程控制 ----------

    def abort_session(self, session_id: str, reason: str) -> ReviewSession:
        """强制中止会签流程（非因失败，如策略被撤回）

        Parameters
        ----------
        session_id : str
            会话 ID
        reason : str
            中止原因

        Returns
        -------
        ReviewSession

        Raises
        ------
        SignoffAlreadyFinalizedError
            流程已结束
        """
        session = self._get_or_raise(session_id)
        if session.status in ("passed", "failed"):
            raise SignoffAlreadyFinalizedError(f"会签流程已{session.status}，无法中止")

        session.status = "aborted"
        session.current_step = None
        session.notes = (session.notes + "; " if session.notes else "") + f"中止原因: {reason}"
        session.updated_at = _now_cst()
        self._sessions[session.session_id] = session
        return session

    def reset_session(
        self,
        session_id: str,
        *,
        clear_signoffs: bool = False,
    ) -> ReviewSession:
        """重置会签流程到初始状态

        Parameters
        ----------
        session_id : str
            会话 ID
        clear_signoffs : bool
            是否清除已签署记录（慎用！默认仅重置状态）

        Returns
        -------
        ReviewSession
        """
        session = self._get_or_raise(session_id)
        session.status = "pending"
        session.current_step = SIGNOFF_STEPS[0]
        session.updated_at = _now_cst()
        if clear_signoffs:
            session.signoffs.clear()
        self._sessions[session.session_id] = session
        return session

    # ---------- 查询 ----------

    def get_progress(self, session_id: str) -> dict[str, Any]:
        """获取会签进度详情

        Parameters
        ----------
        session_id : str
            会话 ID

        Returns
        -------
        dict: 包含步骤进度、每个步骤的状态和签署信息
        """
        session = self._get_or_raise(session_id)

        step_progress: list[dict[str, Any]] = []
        for step in SIGNOFF_STEPS:
            existing = [s for s in session.signoffs if s.step == step]
            step_progress.append({
                "step": step,
                "label": SIGNOFF_STEP_LABELS[step],
                "expected_signer": self._get_signer_for_step(step),
                "signed": len(existing) > 0,
                "result": existing[0].result if existing else None,
                "comment": existing[0].comment if existing else None,
                "timestamp": existing[0].timestamp if existing else None,
            })

        return {
            "session_id": session.session_id,
            "strategy_id": session.strategy_id,
            "status": session.status,
            "current_step": session.current_step,
            "completed_count": len(session.signoffs),
            "total_steps": len(SIGNOFF_STEPS),
            "steps": step_progress,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "notes": session.notes,
        }

    # ---------- 内部方法 ----------

    def _get_or_raise(self, session_id: str) -> ReviewSession:
        """获取会话，不存在则抛异常"""
        session = self._sessions.get(session_id)
        if not session:
            raise ReviewSignoffError(f"会签会话不存在: {session_id}")
        return session

    @staticmethod
    def _get_signer_for_step(step: str) -> str:
        """从步骤名称反查签署方"""
        step_to_signer = {v: k for k, v in SIGNER_TO_DEFAULT_STEP.items()}
        return step_to_signer.get(step, "unknown")


# ============================================================
# 快速审核流程（单步直接通过/拒绝）
# ============================================================

class FastReviewPipeline:
    """快速审核流程 — 适用于已知低风险策略的简化会签

    允许从任意步骤开始跳过前面的签署，但会标记为"快速通道"。

    注意：此模式仅适用于低风险/已验证策略，不应成为默认流程。
    """

    def __init__(self, mgr: Optional[ReviewSignoffManager] = None) -> None:
        self._mgr = mgr or ReviewSignoffManager()

    @property
    def manager(self) -> ReviewSignoffManager:
        return self._mgr

    def quick_approve(
        self,
        strategy_id: str,
        tech_comment: str = "快速通道：技术合规",
        knowledge_comment: str = "快速通道：知识体系兼容",
        business_comment: str = "快速通道：业务批准",
    ) -> ReviewSession:
        """一键快速批准所有步骤（适用于低风险重复策略）

        Parameters
        ----------
        strategy_id : str
            策略 ID
        tech_comment : str
            技术确认意见
        knowledge_comment : str
            知识确认意见
        business_comment : str
            业务确认意见

        Returns
        -------
        ReviewSession
        """
        session = self._mgr.create_session(strategy_id)
        session = self._mgr.sign(session.session_id, "moxuan", True, tech_comment)
        session = self._mgr.sign(session.session_id, "mochen", True, knowledge_comment)
        session = self._mgr.sign(session.session_id, "owner", True, business_comment)
        return session
