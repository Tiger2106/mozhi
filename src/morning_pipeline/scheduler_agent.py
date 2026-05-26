#!/usr/bin/env python3
"""
早报管线调度器 — 供墨涵在 cron isolated session 中调用
================================================================

墨涵执行流程（快速上手指南）:
1. 收到 cron 启动消息 → 确认 task_id 和日期
2. 加载 MorningPipeline(task_id, date)
3. 调用 pipeline.run() — 自动串行执行 7 步
4. 每步完成后校验 .done 文件
5. 7 步完成后执行飞书推送 (Step5 内部完成)
6. 写 pipeline.done 标记全流程完成

用法示例:
    >>> from morning_pipeline.scheduler_agent import MorningPipeline
    >>> pipeline = MorningPipeline()
    >>> pipeline.run()
    # 或指定 task_id:
    >>> pipeline = MorningPipeline(task_id="morning_report_20260516")
    >>> pipeline.run()

auth: moheng
created_time: 2026-05-16T15:00+08:00
version: 1.0
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from pathlib import Path
from src.config import SHARED_REPORTS, PROJECT_ROOT, SHANGHAI_TZ, MARKET_DATA_DB, PIPELINE_CACHE_DB  # DB_UNIFY_0525

TZ = SHANGHAI_TZ

# ── 路径常量 ───────────────────────────────────────────────────
SIGNALS_DIR        = SHARED_REPORTS / "signals"
TASKS_DIR          = SIGNALS_DIR / "tasks"
TRIGGERS_DIR       = SIGNALS_DIR / "triggers"        # 仍在试验信息库下
CHECKPOINTS_DIR    = SIGNALS_DIR / "checkpoints"
REPORTS_DIR        = SHARED_REPORTS / "reports" / "morning"
HEARTBEAT_DIR      = SIGNALS_DIR / "consensus" / "heartbeat"
REPORTS_MORNING    = SHARED_REPORTS / "reports" / "morning"  # reports/morning/{date}/

# 试验信息库 trigger 路径（兼容旧路径）
_EXPERIMENT_TRIGGERS = SHARED_REPORTS / "试验信息库" / "signals" / "triggers"

# 路径兼容: 如果实验信息库 trigger 目录不存在，回退到 SIGNALS_DIR/triggers
if not _EXPERIMENT_TRIGGERS.exists():
    _EXPERIMENT_TRIGGERS = SIGNALS_DIR / "triggers"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MorningPipeline")


# ═══════════════════════════════════════════════════════════════
# Helper: 写入 + read 验证（SOUL.md §3 写入验证规范）
# ═══════════════════════════════════════════════════════════════
def write_with_verify(path: Path, data: dict, max_retries: int = 3) -> bool:
    """写入 JSON 文件后立即读回验证关键字段存在"""
    for attempt in range(1, max_retries + 1):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            # 读回验证
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if "status" in loaded:
                return True
            logger.warning(f"[verify] 第 {attempt} 次验证失败: status 字段不存在 — {path.name}")
        except Exception as e:
            logger.warning(f"[verify] 第 {attempt} 次写入失败: {e} — {path.name}")
        time.sleep(0.3)
    return False


def write_text_with_verify(path: Path, content: str, marker: str, max_retries: int = 3) -> bool:
    """写入文本文件后读回验证标记行"""
    for attempt in range(1, max_retries + 1):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            first_line = path.read_text(encoding="utf-8").splitlines()[0] if path.read_text(encoding="utf-8").splitlines() else ""
            if marker in first_line:
                return True
            logger.warning(f"[verify] 第 {attempt} 次验证失败: 未找到标记 '{marker}' — {path.name}")
        except Exception as e:
            logger.warning(f"[verify] 第 {attempt} 次写入失败: {e} — {path.name}")
        time.sleep(0.3)
    return False


# ═══════════════════════════════════════════════════════════════
# Checkpoint 管理器
# ═══════════════════════════════════════════════════════════════
@dataclass
class StepRecord:
    """单步执行记录"""
    step_id: str          # e.g. "step0"
    agent: str            # e.g. "xuanzhi"
    status: str           # "PENDING" | "RUNNING" | "SUCCESS" | "FAIL" | "SKIPPED"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    done_file: Optional[str] = None
    verdict: Optional[str] = None  # PASS / WARN / FAIL (审查步骤)
    error: Optional[str] = None


class CheckpointManager:
    """
    管线 checkpoint 管理器

    功能:
    - 写入 signals/checkpoints/{task_id}_step{N}_{status}.json
    - 启动时扫描已有 checkpoint，跳过已完成步骤
    - 支持 resume() 从上次中断处继续
    """

    CHECKPOINT_ROOT: Path = CHECKPOINTS_DIR

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)

    # ── 文件名规则 ──
    def _done_checkpoint_path(self, step_id: str) -> Path:
        return self.CHECKPOINT_ROOT / f"{self.task_id}_{step_id}_done.json"

    def _progress_checkpoint_path(self, step_id: str) -> Path:
        return self.CHECKPOINT_ROOT / f"{self.task_id}_{step_id}_progress.json"

    def _abort_checkpoint_path(self) -> Path:
        return self.CHECKPOINT_ROOT / f"{self.task_id}_ABORT.json"

    # ── 写入 checkpoint ──
    def mark_step_done(self, step_id: str, record: StepRecord):
        """标记某步完成"""
        cp = {
            "task_id": self.task_id,
            "step_id": step_id,
            "status": record.status,
            "agent": record.agent,
            "started_at": record.started_at,
            "completed_at": record.completed_at or datetime.now(TZ).isoformat(),
            "done_file": record.done_file,
            "verdict": record.verdict,
            "error": record.error,
        }
        path = self._done_checkpoint_path(step_id)
        ok = write_with_verify(path, cp)
        if ok:
            logger.info(f"[checkpoint] ✓ {step_id} → {path.name}")
        else:
            logger.error(f"[checkpoint] ✗ {step_id} 写入验证失败 → {path.name}")

    def mark_step_progress(self, step_id: str, progress_pct: float, note: str = ""):
        """标记某步进行中进度"""
        cp = {
            "task_id": self.task_id,
            "step_id": step_id,
            "progress_pct": progress_pct,
            "timestamp": datetime.now(TZ).isoformat(),
            "note": note,
        }
        path = self._progress_checkpoint_path(step_id)
        path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark_abort(self, failed_step: str, reason: str):
        """标记整条管线熔断终止"""
        cp = {
            "task_id": self.task_id,
            "status": "ABORTED",
            "failed_step": failed_step,
            "reason": reason,
            "timestamp": datetime.now(TZ).isoformat(),
        }
        path = self._abort_checkpoint_path()
        ok = write_with_verify(path, cp)
        if ok:
            logger.warning(f"[checkpoint] ■ ABORT → {path.name}: {reason}")
        else:
            logger.error(f"[checkpoint] ✗ ABORT 写入验证失败")

    # ── 恢复扫描 ──
    def get_completed_steps(self) -> set:
        """返回已完成的 step_id 集合（基于 checkpoint 文件）"""
        completed = set()
        pattern = f"{self.task_id}_*_done.json"
        for f in self.CHECKPOINT_ROOT.glob(pattern):
            try:
                cp = json.loads(f.read_text(encoding="utf-8"))
                if cp.get("status") in ("SUCCESS", "SKIPPED"):
                    completed.add(cp["step_id"])
            except (json.JSONDecodeError, KeyError):
                continue
        return completed

    def get_abort_info(self) -> Optional[dict]:
        """返回熔断信息（若管线已被熔断）"""
        path = self._abort_checkpoint_path()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None

    def resume_step_order(self, step_ids: list[str]) -> list[str]:
        """
        根据已有 checkpoint 跳过已完成步骤，返回仍需执行的步骤列表
        """
        completed = self.get_completed_steps()
        abort_info = self.get_abort_info()
        if abort_info:
            logger.warning(f"[resume] 管线已被熔断: {abort_info['reason']} (终止步骤: {abort_info['failed_step']})")
            return []  # 熔断后不再执行
        remaining = [s for s in step_ids if s not in completed]
        skipped = [s for s in step_ids if s in completed]
        if skipped:
            logger.info(f"[resume] 跳过已完成步骤: {', '.join(skipped)}")
        if remaining:
            logger.info(f"[resume] 待执行步骤: {', '.join(remaining)}")
        return remaining


# ═══════════════════════════════════════════════════════════════
# 交易日判断
# ═══════════════════════════════════════════════════════════════
def is_trade_day(check_date: Optional[str] = None) -> bool:
    """
    交易日判断: 周一~周五
    可选: 提供 YYYYMMDD 格式日期字符串
    """
    if check_date:
        dt = datetime.strptime(check_date, "%Y%m%d").replace(tzinfo=TZ)
    else:
        dt = datetime.now(TZ)
    return dt.weekday() < 5


# ═══════════════════════════════════════════════════════════════
# 心跳写入
# ═══════════════════════════════════════════════════════════════
def write_heartbeat(status: str = "active", current_task: Optional[dict] = None):
    """写入墨涵心跳文件"""
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    seq = len(list(HEARTBEAT_DIR.glob("mochen_hb_*.json"))) + 1
    hb = {
        "agent": "mochen",
        "status": status,
        "timestamp": datetime.now(TZ).isoformat(),
    }
    if current_task:
        hb["current_task"] = current_task
    path = HEARTBEAT_DIR / f"mochen_hb_{seq:04d}.json"
    path.write_text(json.dumps(hb, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[heartbeat] {status} → {path.name}")

    # 清理旧心跳: 只保留最近 20 个
    all_hb = sorted(HEARTBEAT_DIR.glob("mochen_hb_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in all_hb[20:]:
        old.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# 步骤定义
# ═══════════════════════════════════════════════════════════════
@dataclass
class StepDef:
    """单步定义"""
    step_id: str                    # e.g. "step0"
    agent: str                      # e.g. "xuanzhi"
    description: str                # 人类可读描述
    estimate_minutes: int           # 预估耗时
    timeout_seconds: int            # 超时阈值（含 3min 缓冲）
    can_skip_on_timeout: bool       # 超时后是否可以跳过
    retry_count: int                # 最大重试次数
    abort_on_fail: bool             # 失败后是否终止管线
    depends_on: list[str] = field(default_factory=list)  # 前置步骤

    def task_id(self, base_task_id: str) -> str:
        """生成带 step 前缀的 task_id"""
        return f"{base_task_id}_{self.step_id}"

    def agent_task_id(self, base_task_id: str) -> str:
        return f"{self.task_id(base_task_id)}_{self.agent}"


# ═══════════════════════════════════════════════════════════════
# Pipeline 步骤定义表（共 7 步）
# ═══════════════════════════════════════════════════════════════
STEPS: list[StepDef] = [
    StepDef(
        step_id="step0", agent="xuanzhi", description="市场扫描",
        estimate_minutes=5, timeout_seconds=480, can_skip_on_timeout=False,
        retry_count=1, abort_on_fail=True, depends_on=[],
    ),
    StepDef(
        step_id="step0_5", agent="mochen", description="知识库查询增强",
        estimate_minutes=1, timeout_seconds=120, can_skip_on_timeout=True,
        retry_count=1, abort_on_fail=False, depends_on=["step0"],
    ),
    StepDef(
        step_id="step1", agent="moheng", description="结构化分析",
        estimate_minutes=10, timeout_seconds=780, can_skip_on_timeout=False,
        retry_count=1, abort_on_fail=True, depends_on=["step0"],
    ),
    StepDef(
        step_id="step2", agent="moxuan", description="报告草稿",
        estimate_minutes=5, timeout_seconds=480, can_skip_on_timeout=True,
        retry_count=1, abort_on_fail=True, depends_on=["step1"],
    ),
    StepDef(
        step_id="step3", agent="moheng", description="质量审查",
        estimate_minutes=5, timeout_seconds=480, can_skip_on_timeout=False,
        retry_count=1, abort_on_fail=True, depends_on=["step2"],
    ),
    StepDef(
        step_id="step3_5", agent="xuanzhi", description="战略复核",
        estimate_minutes=5, timeout_seconds=480, can_skip_on_timeout=True,
        retry_count=1, abort_on_fail=True, depends_on=["step1"],   # 依赖原始分析，非审查后
    ),
    StepDef(
        step_id="step4", agent="moxuan", description="汇总定稿",
        estimate_minutes=5, timeout_seconds=480, can_skip_on_timeout=False,
        retry_count=1, abort_on_fail=True, depends_on=["step3", "step3_5"],
    ),
    # P9: Step4_5 — 仅生成 HTML，30s 硬超时
    # PDF 通过 async_pdf_task 异步生成，不阻塞管线
    StepDef(
        step_id="step4_5", agent="mochen", description="HTML渲染 (PDF异步)",
        estimate_minutes=1, timeout_seconds=30, can_skip_on_timeout=True,
        retry_count=0, abort_on_fail=False, depends_on=["step4"],
    ),
    StepDef(
        step_id="step5", agent="mochen", description="飞书推送",
        estimate_minutes=2, timeout_seconds=180, can_skip_on_timeout=False,
        retry_count=2, abort_on_fail=True, depends_on=["step4_5"],
    ),
]

STEPS_BY_ID: dict[str, StepDef] = {s.step_id: s for s in STEPS}


def get_spawn_step5_prompt(task_id: str, date: str, date_dir: str) -> str:
    """生成 Step5 推送 prompt − 供墨涵自执行"""
    return f"""
# 墨枢任务启动 — {task_id}_step5

## 任务描述
执行早报飞书推送（Step5）。这是整条管线的最后一步。

## 输入文件
reports/morning/{date_dir}/final_report_{task_id}_step4.md

## 执行步骤
1. 读取 final_report 文件，提取核心观点摘要（≤200字）
2. 准备推送格式：核心观点 + 操作建议（三档） + 风险提示
3. 发送到飞书群 oc_72bacde2a63f824bd011718fbe58f48a
4. 写 .done 文件标记完成:
   C:/Users/17699\\mo_zhi_sharereports\\signals\\tasks\\{task_id}_step5_mochen.done

## 注意事项
- 推送格式简洁清晰，优先展示核心判断
- 不使用 markdown 表格（飞书群不友好）
- 如需补充完整报告，可上传文件
"""


# ═══════════════════════════════════════════════════════════════
# Spawn prompt 模板生成
# ═══════════════════════════════════════════════════════════════
def get_spawn_task_prompt(step: StepDef, task_id: str, date: str, date_dir: str) -> str:
    """
    为指定步骤生成 spawn TASK prompt

    格式参考: 墨枢 spawn 双命令模板 v3 (spawn_template_v1.0.md)
    输出: 完整的 TASK 指令字符串
    """
    step_task_id = step.task_id(task_id)

    # 根据步骤定义输入/输出文件
    input_files = _get_input_files(step, task_id, date_dir)
    output_files = _get_output_files(step, task_id, date_dir)

    done_path = str(TASKS_DIR / f"{step_task_id}_{step.agent}.done")

    return f"""# 墨枢任务分配 — {step_task_id}

## 任务描述
执行早报管线 {step.description}（{step.step_id}）。

## 上下文
任务: {task_id}
日期: {date}
前驱步骤: {step.depends_on or "无"}

## 具体要求
1. 根据 {step.agent} 的职责和 SOUL.md 要求执行
2. 遵守 spawn 模板 v3 协议：先写 .done 文件，再回复 Announce
3. 每次产出必须 read 验证
4. 阻塞时写 .blocked 文件（不得空等）
5. 超时前报告进度

## 参考文件
{chr(10).join(f"- {f}" for f in input_files) if input_files else "- 无前置文件（联网采集）"}

## 输出文件
{chr(10).join(f"- {f}" for f in output_files)}
- {done_path} — ⚠️ 必须写入

## 你需要做的事
1. 理解上述任务
2. 评估工作量
3. 回复 Announce（格式: type=estimate, 含 estimate_minutes 字段）
"""


def get_spawn_start_prompt(step: StepDef, task_id: str, date: str, date_dir: str) -> str:
    """
    为指定步骤生成 spawn START prompt（收到 estimate Announce 后发送）
    """
    step_task_id = step.task_id(task_id)
    output_files = _get_output_files(step, task_id, date_dir)
    done_path = str(TASKS_DIR / f"{step_task_id}_{step.agent}.done")

    return f"""# 墨枢任务启动 — {step_task_id}

收到你的 Announce，同意预估时间。请现在开始执行。

## ⚠️ 强制执行块（开始前先读此块）

### 核心认知
"写 .done 文件" ≠ "回复 Announce"
两条通道必须独立走通、互不替代。

### 强制完成声明（v2 原子序列）
[步1] 完成任务主体（产出全部 write + read 验证通过）
[步2] 写入 .done 信号文件（写入后立即 read 验证）
[步3] 从 .done 提取字段生成 Announce
[步4] 回复 Announce(completion)

## 输出文件
{chr(10).join(f"- {f}" for f in output_files)}
- {done_path} — ⚠️ 必须写入

## deadline
{step.estimate_minutes} 分钟（设内部 timer）
超时 → escalation 申请延期（最多 2 次）
"""


def _get_input_files(step: StepDef, task_id: str, date_dir: str) -> list[str]:
    """获取步骤的输入文件路径"""
    base_path = str(REPORTS_MORNING / date_dir)

    if step.step_id == "step0":
        return []
    elif step.step_id == "step0_5":
        return [f"{base_path}/macro_analysis_*.json"]
    elif step.step_id == "step1":
        return [
            f"{base_path}/macro_analysis_*.json",
            f"{base_path}/knowledge_context_{task_id}_step0_5.json",
        ]
    elif step.step_id == "step2":
        return [
            f"{base_path}/structured_analysis_{task_id}_step1.json",
            f"{base_path}/knowledge_context_{task_id}_step0_5.json",
        ]
    elif step.step_id == "step3":
        return [
            f"{base_path}/morning_draft_{task_id}_step2.md",
            f"{base_path}/structured_analysis_{task_id}_step1.json",
        ]
    elif step.step_id == "step3_5":
        return [f"{base_path}/structured_analysis_{task_id}_step1.json"]
    elif step.step_id == "step4":
        return [
            f"{base_path}/morning_draft_{task_id}_step2.md",
            f"{base_path}/review_feedback_{task_id}_step3.md",
            str(SIGNALS_DIR / f"strategic_review_{task_id}_step3_5.json"),
        ]
    elif step.step_id == "step4_5":
        return [
            f"{base_path}/final_report_{task_id}_step4.md",
        ]
    else:
        return []


def _get_output_files(step: StepDef, task_id: str, date_dir: str) -> list[str]:
    """获取步骤的输出文件路径"""
    base_path = str(REPORTS_MORNING / date_dir)

    if step.step_id == "step0":
        return [f"{base_path}/macro_analysis_{date_dir}_*.json"]
    elif step.step_id == "step0_5":
        return [f"{base_path}/knowledge_context_{task_id}_step0_5.json"]
    elif step.step_id == "step1":
        return [f"{base_path}/structured_analysis_{task_id}_step1.json"]
    elif step.step_id == "step2":
        return [f"{base_path}/morning_draft_{task_id}_step2.md"]
    elif step.step_id == "step3":
        return [f"{base_path}/review_feedback_{task_id}_step3.md"]
    elif step.step_id == "step3_5":
        return [str(SIGNALS_DIR / f"strategic_review_{task_id}_step3_5.json")]
    elif step.step_id == "step4":
        return [f"{base_path}/final_report_{task_id}_step4.md"]
    elif step.step_id == "step4_5":
        return [f"{base_path}/final_report_{task_id}_step4_5.html"]
    else:
        return []


# ═══════════════════════════════════════════════════════════════
# .done 文件查找和读取
# ═══════════════════════════════════════════════════════════════
def find_done_file(step: StepDef, task_id: str) -> Optional[dict]:
    """查找步骤的 .done 文件并解析"""
    step_task_id = step.task_id(task_id)
    done_patterns = [
        TASKS_DIR / f"{step_task_id}_{step.agent}.done",
        TASKS_DIR / f"{step_task_id}_{step.agent}.json",
    ]
    # 也查找旧格式: morning_report_{YYYYMMDD}_step{X}_{agent}.done
    # (已由 step_task_id 覆盖)

    for p in done_patterns:
        if not p.exists():
            continue
        try:
            content = p.read_text(encoding="utf-8").strip()
            # 尝试 JSON 解析
            if content.startswith("{"):
                return json.loads(content)
            # 尝试 [DONE] 文本格式
            if content.startswith("[DONE]"):
                lines = content.splitlines()
                result = {"_format": "text_done"}
                for line in lines:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        result[k.strip()] = v.strip()
                return result
            # 纯 JSON（无标记头）
            return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[done] 解析失败 {p.name}: {e}")
            continue
    return None


def find_failed_file(step: StepDef, task_id: str) -> Optional[dict]:
    """查找步骤的 .failed 文件"""
    step_task_id = step.task_id(task_id)
    failed_path = TASKS_DIR / f"{step_task_id}_{step.agent}.failed"
    if failed_path.exists():
        try:
            return json.loads(failed_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"status": "FAIL", "error": "parse_error"}
    return None


def find_blocked_file(step: StepDef, task_id: str) -> Optional[dict]:
    """查找步骤的 .blocked 文件"""
    step_task_id = step.task_id(task_id)
    blocked_path = TASKS_DIR / f"{step_task_id}_{step.agent}.blocked"
    if blocked_path.exists():
        try:
            return json.loads(blocked_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"status": "BLOCKED"}
    return None


# ═══════════════════════════════════════════════════════════════
# Pipeline 主类
# ═══════════════════════════════════════════════════════════════
class MorningPipeline:
    """
    早报管线调度器 — 墨涵 cron session 主入口

    设计:
    - 串行 spawn 子 agent，每步等 Announce 或 .done 文件
    - .done 文件是单一真相源，Announce 仅作加速信号
    - checkpoint 文件支持 session 重启恢复
    - FAIL 严格传播：任何步骤 FAIL → 终止管线

    用法:
        pipeline = MorningPipeline()
        pipeline.run()

        # 指定 task_id:
        pipeline = MorningPipeline(task_id="morning_report_20260516")
        pipeline.run()

        # 从上次中断恢复:
        pipeline = MorningPipeline()
        pipeline.resume()  # 内部扫描 checkpoint 跳步
    """

    def __init__(
        self,
        task_id: Optional[str] = None,
        date: Optional[str] = None,
        report_type: str = "morning",
    ):
        now = datetime.now(TZ)
        self.date = date or now.strftime("%Y%m%d")
        self.date_dir = self.date  # reports/morning/{date}/
        self.report_type = report_type  # "morning" or "midday"
        self.task_id = task_id or f"{self.report_type}_report_{self.date}"
        self.checkpoints = CheckpointManager(self.task_id)
        self.aborted = False
        self.abort_reason: Optional[str] = None
        self.results: dict[str, StepRecord] = {}  # step_id → StepRecord

    # ── 三合一预检 ──
    def _precheck(self) -> bool:
        """
        DB_UNIFY_0525 四合一预检: 交易日 + market_data.db + pipeline_cache.db + 报告目录可写

        - 非交易日 → 写 skip 标记并返回 False
        - market_data.db 不存在 → 自动创建行情骨架（原 stock_daily 等表移入 market_data.db）
        - pipeline_cache.db 不存在 → 自动创建管线缓存骨架
        - 报告目录不可写 → 返回 False
        """
        checks = []

        # 1. 交易日检查
        checks.append(("trade_day", is_trade_day(self.date)))

        # 2. market_data.db 存在性检查（DB_UNIFY_0525: 行情数据统一存放）
        market_data_db = MARKET_DATA_DB
        if not market_data_db.exists():
            logger.warning(f"[precheck] market_data.db not found at {market_data_db}, creating skeleton...")
            self._ensure_market_data_db()
        checks.append(("market_data_db", market_data_db.exists()))

        # 3. pipeline_cache.db 存在性检查（DB_UNIFY_0525: 管线缓存统一存放）
        pipeline_cache_db = PIPELINE_CACHE_DB
        if not pipeline_cache_db.exists():
            logger.warning(f"[precheck] pipeline_cache.db not found at {pipeline_cache_db}, creating skeleton...")
            self._ensure_pipeline_cache_db()
        checks.append(("pipeline_cache_db", pipeline_cache_db.exists()))

        # 4. 报告目录可写性
        reports_dir = REPORTS_MORNING / self.date_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        checks.append(("reports_dir_writable", reports_dir.is_dir()))

        # 汇总
        all_pass = all(ok for _, ok in checks)
        if not all_pass:
            failed = [name for name, ok in checks if not ok]
            logger.error(f"[precheck] ✗ 预检失败: {failed}")
            write_heartbeat("degraded", {"task_id": self.task_id, "failed_checks": failed})

            # 如果是非交易日，写 skip 标记（兼容旧逻辑）
            if "trade_day" in failed:
                skip_path = TASKS_DIR / "morning_skip.done"
                skip_data = {
                    "task_id": "morning_skip",
                    "agent": "mochen",
                    "date": self.date,
                    "status": "SKIPPED",
                    "reason": "not_trading_day",
                    "timestamp": datetime.now(TZ).isoformat(),
                }
                write_with_verify(skip_path, skip_data)
                logger.warning(f"[precheck] ✗ {self.date} 非交易日，跳过")

            return all_pass

        logger.info(f"[precheck] ✓ 全部预检通过 ({self.date})")
        return True

    # ── market_data.db 骨架生成（DB_UNIFY_0525: 行情骨架） ──
    @staticmethod
    def _ensure_market_data_db():
        """
        DB_UNIFY_0525: 创建 market_data.db 行情骨架（含 stock_daily、oil_daily、stock_minute、trading_calendar）。
        在首次运行时自动调用，保证回测引擎对行情数据的查询不会崩溃。
        """
        import sqlite3

        db_path = MARKET_DATA_DB
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()

        # ── 1. stock_daily（日线数据） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS stock_daily (
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     INTEGER,
                amount     REAL,
                adj_factor REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 2. stock_daily_unadjusted（不复权日线） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS stock_daily_unadjusted (
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     INTEGER,
                amount     REAL,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 3. stock_minute（分钟线数据） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS stock_minute (
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                minute     TEXT NOT NULL,
                freq       TEXT NOT NULL DEFAULT '5min',
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     INTEGER,
                amount     REAL,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (code, date, minute, freq)
            )
        ''')

        # ── 4. oil_daily（原油日线） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS oil_daily (
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     INTEGER,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 5. trading_calendar（交易日历） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS trading_calendar (
                date           TEXT NOT NULL,
                market         TEXT NOT NULL,
                is_trading_day INTEGER NOT NULL DEFAULT 0,
                market_type    TEXT DEFAULT '',
                note           TEXT DEFAULT '',
                created_at     TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (date, market)
            )
        ''')

        # ── 6. tech_indicators（技术指标） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS tech_indicators (
                code         TEXT NOT NULL,
                date         TEXT NOT NULL,
                ma5          REAL,
                ma10         REAL,
                ma20         REAL,
                ma60         REAL,
                rsi14        REAL,
                macd_dif     REAL,
                macd_dea     REAL,
                macd_hist    REAL,
                bb_upper     REAL,
                bb_mid       REAL,
                bb_lower     REAL,
                kdj_k        REAL,
                kdj_d        REAL,
                kdj_j        REAL,
                created_at   TEXT DEFAULT (datetime('now', 'localtime')),
                ma120        REAL,
                trend_score  REAL,
                trend_summary TEXT,
                bb_squeeze   INTEGER DEFAULT 0,
                is_gap_day   INTEGER DEFAULT 0,
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 7. config 表（key-value 配置项） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                note  TEXT DEFAULT ''
            )
        ''')

        c.execute(
            "INSERT OR REPLACE INTO config (key, value, note) VALUES (?, ?, ?)",
            ("db_version", "market_skeleton_1.0", "DB_UNIFY_0525 行情骨架，等待数据填充")
        )
        c.execute(
            "INSERT OR REPLACE INTO config (key, value, note) VALUES (?, ?, ?)",
            ("created_at", datetime.now(TZ).isoformat(), "行情数据库创建时间")
        )

        conn.commit()
        conn.close()

        logger.info(f"[precheck] ✓ market_data.db 行情骨架已创建: {db_path}")

    # ── pipeline_cache.db 骨架生成（DB_UNIFY_0525: 管线缓存骨架） ──
    @staticmethod
    def _ensure_pipeline_cache_db():
        """
        DB_UNIFY_0525: 创建 pipeline_cache.db 管线缓存骨架（含 cache_metadata、pipeline_state 等）。
        在首次运行时自动调用，保证管线缓存查询不会崩溃。
        """
        import sqlite3

        db_path = PIPELINE_CACHE_DB
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()

        # ── 1. cache_metadata（缓存元数据） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS cache_metadata (
                symbol     TEXT NOT NULL,
                cache_date TEXT,
                cache_time TEXT,
                row_count  INTEGER,
                PRIMARY KEY (symbol)
            )
        ''')

        # ── 2. pipeline_state（管线执行状态） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS pipeline_state (
                task_id     TEXT NOT NULL,
                step        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'PENDING',
                started_at  TEXT,
                completed_at TEXT,
                error       TEXT,
                PRIMARY KEY (task_id, step)
            )
        ''')

        # ── 3. factor_cache（因子计算缓存） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS factor_cache (
                symbol    TEXT NOT NULL,
                date      TEXT NOT NULL,
                factor    TEXT NOT NULL,
                value     REAL,
                cached_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (symbol, date, factor)
            )
        ''')

        # ── 4. config 表 ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                note  TEXT DEFAULT ''
            )
        ''')

        c.execute(
            "INSERT OR REPLACE INTO config (key, value, note) VALUES (?, ?, ?)",
            ("db_version", "cache_skeleton_1.0", "DB_UNIFY_0525 管线缓存骨架")
        )
        c.execute(
            "INSERT OR REPLACE INTO config (key, value, note) VALUES (?, ?, ?)",
            ("created_at", datetime.now(TZ).isoformat(), "管线缓存数据库创建时间")
        )

        conn.commit()
        conn.close()

        logger.info(f"[precheck] ✓ pipeline_cache.db 管线缓存骨架已创建: {db_path}")

    # ── old: analysis.db 骨架生成（DB_UNIFY_0525: 已废弃，保留注释） ──
    # @staticmethod
    # def _create_analysis_db_skeleton(db_path: Path):
        """
        创建空的 analysis.db 骨架（含 config 表和基本数据表结构）

        在首次运行时自动调用，保证 step0 对 analysis.db 的查询
        即使返回空结果也不会直接崩溃。
        """
        import sqlite3

        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()

        # ── 1. config 表（key-value 配置项） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                note  TEXT DEFAULT ''
            )
        ''')

        # 写入骨架标记
        c.execute(
            "INSERT OR REPLACE INTO config (key, value, note) VALUES (?, ?, ?)",
            ("db_version", "skeleton_1.0", "自动生成的空骨架，等待数据填充")
        )
        c.execute(
            "INSERT OR REPLACE INTO config (key, value, note) VALUES (?, ?, ?)",
            ("created_at", datetime.now(TZ).isoformat(), "骨架数据库创建时间")
        )

        # ── 2. stock_daily（日线数据） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS stock_daily (
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     INTEGER,
                amount     REAL,
                adj_factor REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 3. oil_daily（原油日线） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS oil_daily (
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     INTEGER,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 4. tech_indicators（技术指标） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS tech_indicators (
                code         TEXT NOT NULL,
                date         TEXT NOT NULL,
                ma5          REAL,
                ma10         REAL,
                ma20         REAL,
                ma60         REAL,
                rsi14        REAL,
                macd_dif     REAL,
                macd_dea     REAL,
                macd_hist    REAL,
                bb_upper     REAL,
                bb_mid       REAL,
                bb_lower     REAL,
                kdj_k        REAL,
                kdj_d        REAL,
                kdj_j        REAL,
                created_at   TEXT DEFAULT (datetime('now', 'localtime')),
                ma120        REAL,
                trend_score  REAL,
                trend_summary TEXT,
                bb_squeeze   INTEGER DEFAULT 0,
                is_gap_day   INTEGER DEFAULT 0,
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 5. trading_calendar（交易日历） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS trading_calendar (
                date           TEXT NOT NULL,
                market         TEXT NOT NULL,
                is_trading_day INTEGER NOT NULL DEFAULT 0,
                market_type    TEXT DEFAULT '',
                note           TEXT DEFAULT '',
                created_at     TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (date, market)
            )
        ''')

        # ── 6. stock_daily_unadjusted（不复权日线） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS stock_daily_unadjusted (
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     INTEGER,
                amount     REAL,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (code, date)
            )
        ''')

        # ── 7. cache_metadata（缓存元数据） ──
        c.execute('''
            CREATE TABLE IF NOT EXISTS cache_metadata (
                symbol     TEXT NOT NULL,
                cache_date TEXT,
                cache_time TEXT,
                row_count  INTEGER,
                PRIMARY KEY (symbol)
            )
        ''')

        conn.commit()
        conn.close()

        logger.info(f"[precheck] ✓ analysis.db 骨架已创建: {db_path} (含 config 等 7 张空表)")

    # ── 等待子 agent 完成 ──
    def _wait_for_step(
        self,
        step: StepDef,
        timeout_s: int,
        poll_interval_s: int = 15,
        on_progress: Optional[Callable] = None,
    ) -> StepRecord:
        """
        等待步骤完成: 轮询 .done / .failed / .blocked 文件
        返回 StepRecord
        """
        record = StepRecord(
            step_id=step.step_id,
            agent=step.agent,
            status="RUNNING",
            started_at=datetime.now(TZ).isoformat(),
        )
        deadline = time.time() + timeout_s
        attempt = 0
        max_attempts = 1 + step.retry_count

        while attempt < max_attempts:
            if attempt > 0:
                logger.info(f"[wait] {step.step_id} 第 {attempt+1} 次尝试（共 {max_attempts} 次）")

            # 循环等待直到 deadline
            while time.time() < deadline:
                elapsed = deadline - time.time()
                # 1. 检查 .done 文件
                done = find_done_file(step, self.task_id)
                if done:
                    status = done.get("status", "SUCCESS")
                    record.status = "SUCCESS" if status in ("SUCCESS", "COMPLETED") else "FAIL"
                    record.completed_at = datetime.now(TZ).isoformat()
                    record.done_file = str(TASKS_DIR / f"{step.task_id(self.task_id)}_{step.agent}.done")
                    record.verdict = done.get("verdict")
                    logger.info(f"[wait] ✓ {step.step_id} 完成 (status={record.status})")
                    return record

                # 2. 检查 .failed 文件
                failed = find_failed_file(step, self.task_id)
                if failed:
                    record.status = "FAIL"
                    record.completed_at = datetime.now(TZ).isoformat()
                    record.error = failed.get("error", "step_failed")
                    logger.warning(f"[wait] ✗ {step.step_id} 失败: {record.error}")
                    return record

                # 3. 检查 .blocked 文件（子 agent 主动标记阻塞）
                blocked = find_blocked_file(step, self.task_id)
                if blocked:
                    logger.warning(f"[wait] ⚠ {step.step_id} 被阻塞: {blocked.get('reason', 'unknown')}")

                # 4. 心跳 + 进度回调
                write_heartbeat("busy", {"task_id": self.task_id, "step": step.step_id, "attempt": attempt + 1})
                if on_progress:
                    on_progress(step, elapsed, deadline)

                time.sleep(poll_interval_s)

            # deadline 到期 — 重试逻辑
            if attempt < max_attempts - 1:
                attempt += 1
                logger.warning(f"[wait] ⏰ {step.step_id} 超时（{timeout_s}s），第 {attempt+1} 次尝试")
                deadline = time.time() + timeout_s
                # 超时后写一个新的 trigger 文件触发重试
                self._write_trigger_file(step)
            else:
                break

        # 最终超时
        if step.can_skip_on_timeout:
            record.status = "SKIPPED"
            record.completed_at = datetime.now(TZ).isoformat()
            record.error = f"timeout_after_{timeout_s}s"
            logger.warning(f"[wait] ⏰ {step.step_id} 超时，跳过（可跳过步骤）")
        else:
            record.status = "FAIL"
            record.completed_at = datetime.now(TZ).isoformat()
            record.error = f"timeout_after_{max_attempts}_attempts"
            logger.error(f"[wait] ⏰ {step.step_id} 超时熔断（不可跳过）")
        return record

    # ── 写 trigger 文件 ──
    def _write_trigger_file(self, step: StepDef):
        """写 trigger_{step.step_id}_{task_id}.json 到实验信息库 triggers 目录"""
        trigger = {
            "task_id": step.task_id(self.task_id),
            "report_type": self.report_type,
            "step": step.step_id.replace("step", "").replace("_", "."),
            "agent": step.agent,
            "priority": "normal",
            "triggered_by": "mochen",
            "depends_on": step.depends_on,
            "expected_duration": step.estimate_minutes * 60,
            "created_at": datetime.now(TZ).isoformat(),
            "version": "2.1",
            "status": "PENDING",
        }
        # 兼容两种路径: 实验信息库目录 和 signals/triggers 目录
        for base_dir in [_EXPERIMENT_TRIGGERS, TRIGGERS_DIR]:
            path = base_dir / f"trigger_{step.step_id}_{self.task_id}.json"
            ok = write_with_verify(path, trigger)
            if ok:
                logger.info(f"[trigger] ✓ {step.step_id} → {path}")
            else:
                logger.error(f"[trigger] ✗ {step.step_id} 写入失败 → {path}")

    # ── 运行单步 ──
    def run_step(self, step: StepDef) -> StepRecord:
        """
        运行管线中的单一步骤

        流程: spawn TASK → 等 estimate → spawn START → 等完成
        对 step5: 不 spawn，直接执行推送逻辑描述（由墨涵在 session 中自行执行）

        返回: StepRecord
        """
        logger.info(f"[run] ▶ {step.step_id}: spawn {step.agent} — {step.description}")

        # Step0.5: 知识库查询增强（内联执行，不 spawn）
        if step.step_id == "step0_5":
            return self._run_step0_5(step)

        # P9: Step4_5 — HTML 渲染（内联执行，30s 硬超时）
        if step.step_id == "step4_5":
            return self._run_step4_5(step)

        # Step5: 墨涵自执行（非 spawn）
        if step.step_id == "step5":
            return self._run_step5(step)

        # 1. 写 trigger 文件（兼容旧轮询系统）
        self._write_trigger_file(step)

        # 2. 生成 spawn task prompt（供墨涵在 session 中发送）
        task_prompt = get_spawn_task_prompt(step, self.task_id, self.date, self.date_dir)
        logger.info(f"[spawn] TASK prompt prepared for {step.agent} ({step.step_id})")
        logger.debug(f"[spawn] TASK:\n{task_prompt[:500]}...")

        # 3. 等待完成
        record = self._wait_for_step(
            step=step,
            timeout_s=step.timeout_seconds,
            poll_interval_s=15,
        )

        # 4. 内容完整性校验
        if record.status == "SUCCESS":
            if not self._validate_step_output(step):
                record.status = "FAIL"
                record.error = "output_validation_failed"
                logger.error(f"[validate] ✗ {step.step_id} 产出文件校验失败")

        # 5. 写入 checkpoint
        self.checkpoints.mark_step_done(step.step_id, record)
        self.results[step.step_id] = record

        return record

    # ── P9: Step4_5 — HTML渲染 (超时仅发HTML, PDF异步) ──
    def _run_step4_5(self, step: StepDef) -> StepRecord:
        """
        将 step4 的 final_report.md 转为 HTML；
        PDF 通过 async_pdf_task 异步生成，不阻塞管线。

        硬超时 30s: 超过则只保留 HTML，PDF 走异步后台。
        """
        import time
        from datetime import datetime as dt

        record = StepRecord(
            step_id=step.step_id,
            agent=step.agent,
            status="RUNNING",
            started_at=dt.now(TZ).isoformat(),
        )

        md_path = REPORTS_MORNING / self.date_dir / f"final_report_{self.task_id}_step4.md"
        html_path = REPORTS_MORNING / self.date_dir / f"final_report_{self.task_id}_step4_5.html"
        pdf_path = REPORTS_MORNING / self.date_dir / f"final_report_{self.task_id}_step4_5.pdf"

        if not md_path.exists():
            record.status = "SKIPPED"
            record.error = f"输入文件不存在: {md_path}"
            logger.warning(f"[step4_5] 跳过: {md_path} 不存在")
            record.completed_at = dt.now(TZ).isoformat()
            return record

        start_ts = time.time()
        logger.info(f"[step4_5] 开始 HTML 渲染: {md_path.name}")

        try:
            # ---- 1. Markdown → HTML（简单包装） ----
            md_content = md_path.read_text(encoding="utf-8")

            html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self.task_id} 晨报</title>
<style>
  body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; max-width: 960px; margin: 0 auto; padding: 2em; line-height: 1.6; color: #333; }}
  h1, h2, h3 {{ color: #1a1a2e; }}
  table {{ border-collapse: collapse; width: 100%%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
  th {{ background-color: #f5f5f5; }}
  code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
  .warning {{ background: #fff3cd; border: 1px solid #ffc107; padding: 1em; border-radius: 4px; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 2em 0; }}
</style>
</head>
<body>
"""

            # 简单 Markdown → HTML 转换（表、标题、链接、加粗）
            import re
            lines = md_content.split("\n")
            in_table = False
            for line in lines:
                elapsed = time.time() - start_ts
                # P9: 30s 硬超时保护
                if elapsed >= 30:
                    logger.warning(f"[step4_5] 30s 硬超时到达，截断转换")
                    break

                # 标题
                h_match = re.match(r"^(#{1,6})\s+(.+)$", line)
                if h_match:
                    level = len(h_match.group(1))
                    html_content += f"<h{level}>{h_match.group(2)}</h{level}>\n"
                    continue

                # 水平线
                if re.match(r"^---+$", line) or re.match(r"^\*\*\*+$", line):
                    html_content += "<hr>\n"
                    continue

                # 表格行
                if line.startswith("|"):
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    if re.match(r"^[|\s:-]+$", line):  # 分隔行
                        if not in_table:
                            html_content += "<table>\n<tr>"
                            for c in cells:
                                html_content += f"<th>{c}</th>"
                            html_content += "</tr>\n"
                        in_table = True
                        continue
                    if in_table:
                        html_content += "<tr>"
                        for c in cells:
                            html_content += f"<td>{c}</td>"
                        html_content += "</tr>\n"
                    continue
                else:
                    if in_table:
                        html_content += "</table>\n"
                        in_table = False

                # 空行
                if not line.strip():
                    html_content += "<br>\n"
                    continue

                # 普通文本（加粗替换）
                text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
                html_content += f"<p>{text}</p>\n"

            if in_table:
                html_content += "</table>\n"

            html_content += "</body>\n</html>"

            # P8: 写入防碰撞
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html_content, encoding="utf-8")

            if html_path.exists() and html_path.stat().st_size > 0:
                logger.info(f"[step4_5] ✅ HTML 生成成功: {html_path.name} ({html_path.stat().st_size} bytes)")
            else:
                raise IOError("HTML 写入验证失败")

            # ---- 2. 异步启动 PDF 生成（不阻塞） ----
            elapsed_t = time.time() - start_ts
            remaining = max(1, 30 - int(elapsed_t))

            try:
                from backtest.pipeline.async_pdf_task import generate_pdf_async

                def _on_pdf_done(success: bool, out: str):
                    if success:
                        logger.info(f"[step4_5] ⏳ PDF 异步完成: {out}")
                    else:
                        logger.warning(f"[step4_5] ⏳ PDF 异步失败（不影响管线）: {out}")

                thread = generate_pdf_async(
                    input_html=str(html_path),
                    output_pdf=str(pdf_path),
                    timeout_seconds=remaining,
                    callback=_on_pdf_done,
                )
                logger.info(f"[step4_5] ⏳ PDF 异步任务已启动 (thread={thread.name})")
            except Exception as e:
                logger.warning(f"[step4_5] ⚠ PDF 异步启动失败（仅发 HTML）: {e}")

            record.status = "SUCCESS"

        except Exception as e:
            record.status = "SKIPPED"
            record.error = str(e)[:200]
            logger.error(f"[step4_5] 渲染失败: {e}")

        record.completed_at = dt.now(TZ).isoformat()

        # 内容完整性校验
        if record.status == "SUCCESS":
            if not self._validate_step_output(step):
                record.status = "SKIPPED"
                record.error = "output_validation_failed"
                logger.warning(f"[validate] ✗ {step.step_id} 产出文件校验失败")

        self.checkpoints.mark_step_done(step.step_id, record)
        self.results[step.step_id] = record
        return record

    # ── Step5 自执行 ──
    def _run_step5(self, step: StepDef) -> StepRecord:
        """
        Step5 执行逻辑: 墨涵在 session 中自行操作

        实际推送动作由墨涵在 session 中手动执行:
        1. 读取 final_report
        2. 准备推送内容
        3. 发送飞书消息
        4. 写 .done 文件
        """
        step_task_id = step.task_id(self.task_id)
        record = StepRecord(
            step_id=step.step_id,
            agent=step.agent,
            status="RUNNING",
            started_at=datetime.now(TZ).isoformat(),
        )

        logger.info("[step5] ⚠ Step5 需要墨涵自行执行飞书推送")
        logger.info(f"[step5] 输入: reports/morning/{self.date_dir}/final_report_{self.task_id}_step4.md")
        logger.info(f"[step5] 推送目标: feishu 群 oc_72bacde2a63f824bd011718fbe58f48a")
        logger.info(f"[step5] .done 目标: {TASKS_DIR / f'{step_task_id}_mochen.done'}")

        # 生成推送 prompt（存储在日志中供墨涵参考）
        push_prompt = get_spawn_step5_prompt(self.task_id, self.date, self.date_dir)
        logger.info(f"[step5] 推送指令:\n{push_prompt}")

        # 等待墨涵手动完成（检查 .done 文件到达或超时）
        record = self._wait_for_step(
            step=step,
            timeout_s=step.timeout_seconds,
            poll_interval_s=10,
        )

        # 写入 checkpoint
        self.checkpoints.mark_step_done(step.step_id, record)
        self.results[step.step_id] = record
        return record

    # ── Step0.5 内联执行 ──
    def _run_step0_5(self, step: StepDef) -> StepRecord:
        """执行知识库查询增强（内联执行，不 spawn）"""
        from morning_pipeline.report_enricher import ReportEnricher

        record = StepRecord(
            step_id=step.step_id,
            agent=step.agent,
            status="RUNNING",
            started_at=datetime.now(TZ).isoformat(),
        )

        try:
            from src.config import normalize_symbol

            # 从 macro_analysis 文件提取标的
            macro_pattern = f"macro_analysis_{self.date_dir}_*.json"
            macro_files = list((REPORTS_MORNING / self.date_dir).glob(macro_pattern))

            # 构建简单的 analysis dict
            analysis = {"task_id": self.task_id, "signal_mapping": {"symbol": "601857"}}

            if macro_files:
                try:
                    macro_data = json.loads(macro_files[0].read_text(encoding="utf-8"))
                    scope = macro_data.get("scope") or macro_data.get("symbol") or macro_data.get("target")
                    if scope:
                        if isinstance(scope, str):
                            analysis["signal_mapping"] = {"symbol": scope}
                        elif isinstance(scope, list) and scope:
                            analysis["signal_mapping"] = {"symbol": scope[0]}
                            analysis["scope"] = scope
                except (json.JSONDecodeError, Exception):
                    pass  # 使用默认标的 601857

            # R3: 统一 symbol 格式 601857 → 601857.SH
            raw_symbol = analysis.get("signal_mapping", {}).get("symbol", "")
            if raw_symbol:
                analysis["signal_mapping"]["symbol"] = normalize_symbol(raw_symbol)

            # 调用 ReportEnricher 生成知识上下文
            enricher = ReportEnricher()
            ctx = enricher.generate_knowledge_context(analysis)

            # 写入 knowledge_context_{task_id}_step0_5.json
            out_path = REPORTS_MORNING / self.date_dir / f"knowledge_context_{self.task_id}_step0_5.json"
            enricher.write_knowledge_context(out_path, ctx)

            # 验证写入
            if out_path.exists():
                record.status = "SUCCESS"
                logger.info(f"[step0_5] ✓ 知识上下文已写入: {out_path.name}")
            else:
                record.status = "SKIPPED"
                record.error = "写入验证失败"
                logger.warning(f"[step0_5] ✗ 写入验证失败: {out_path}")
        except Exception as e:
            record.status = "SKIPPED"
            record.error = str(e)
            logger.warning(f"[step0_5] ⚠ 知识库查询失败，跳过: {e}")

        record.completed_at = datetime.now(TZ).isoformat()

        # 内容完整性校验
        if record.status == "SUCCESS":
            if not self._validate_step_output(step):
                record.status = "FAIL"
                record.error = "output_validation_failed"
                logger.error(f"[validate] ✗ {step.step_id} 产出文件校验失败")

        self.checkpoints.mark_step_done(step.step_id, record)
        self.results[step.step_id] = record
        return record

    # ── 产出文件验证 ──
    def _validate_step_output(self, step: StepDef) -> bool:
        """
        验证步骤产出文件的完整性和正确性

        检查项:
        - 产出文件是否存在
        - 产出文件大小 > 0
        - JSON 文件可正确解析
        """
        import glob as _glob

        output_patterns = _get_output_files(step, self.task_id, self.date_dir)
        if not output_patterns:
            logger.info(f"[validate] {step.step_id}: 无产出文件定义，跳过验证")
            return True

        for pattern in output_patterns:
            if "*" in pattern:
                matches = _glob.glob(pattern)
                if not matches:
                    logger.error(f"[validate] ✗ {step.step_id}: 产出文件不存在 (pattern: {pattern})")
                    return False
                for match in matches:
                    if not self._validate_single_file(Path(match)):
                        return False
            else:
                p = Path(pattern)
                if not self._validate_single_file(p):
                    return False

        logger.info(f"[validate] ✓ {step.step_id}: 所有产出文件验证通过")
        return True

    @staticmethod
    def _validate_single_file(path: Path) -> bool:
        """验证单个文件的完整性和正确性"""
        if not path.exists():
            logger.error(f"[validate] ✗ 文件不存在: {path}")
            return False

        size = path.stat().st_size
        if size == 0:
            logger.error(f"[validate] ✗ 文件为空: {path}")
            return False

        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                logger.error(f"[validate] ✗ JSON 解析失败: {path}: {e}")
                return False

        return True

    # ── 熔断 ──
    def abort(self, reason: str, failed_step: Optional[str] = None):
        """熔断: 标记管线为 ABORTED，写 abort checkpoint"""
        self.aborted = True
        self.abort_reason = reason
        failed_step = failed_step or "unknown"
        self.checkpoints.mark_abort(failed_step, reason)
        write_heartbeat("degraded", {"task_id": self.task_id, "abort_reason": reason})
        logger.error(f"[abort] ■ 管线终止 — 步骤: {failed_step}, 原因: {reason}")

    # ── 全流程 ──
    def run(self) -> dict:
        """
        串行执行全部步骤
        返回: 全流程结果摘要 dict
        """
        write_heartbeat("busy", {"task_id": self.task_id, "step": "precheck"})
        pipeline_start = time.time()

        # 交易日预检
        if not self._precheck():
            write_heartbeat("idle")
            return {
                "task_id": self.task_id,
                "status": "SKIPPED",
                "reason": "not_trading_day",
                "date": self.date,
            }

        # 恢复: 跳过已完成步骤
        remaining_steps = self.checkpoints.resume_step_order([s.step_id for s in STEPS])
        if not remaining_steps:
            logger.info("[run] ✓ 所有步骤已完成，无需执行")
            return self._summary(pipeline_start)

        # 熔断检查
        abort_info = self.checkpoints.get_abort_info()
        if abort_info:
            logger.warning(f"[run] 管线已被熔断: {abort_info['reason']}")
            write_heartbeat("degraded", {"task_id": self.task_id, "abort": abort_info})
            return {
                "task_id": self.task_id,
                "status": "ABORTED",
                "reason": abort_info.get("reason", "pipeline_aborted"),
                "failed_step": abort_info.get("failed_step"),
            }

        # 串行执行
        for step_def in STEPS:
            if step_def.step_id not in remaining_steps:
                continue  # 已完成的跳过

            record = self.run_step(step_def)
            self.results[step_def.step_id] = record

            # 熔断判定
            if record.status == "FAIL":
                # 严重步骤失败写 critical 心跳（即使 abort_on_fail 未触发）
                if step_def.step_id in ("step1", "step2", "step4"):
                    write_heartbeat(
                        "critical",
                        {
                            "task_id": self.task_id,
                            "failed_step": step_def.step_id,
                            "error": record.error,
                            "agent": step_def.agent,
                        },
                    )
                    logger.critical(f"[critical] {step_def.step_id} 严重失败: {record.error}")
                self.abort(f"{step_def.step_id} FAIL: {record.error}", step_def.step_id)
                break
            if record.status == "SKIPPED":
                logger.info(f"[run] → {step_def.step_id} 已跳过，继续下一步")

        # 最终结果
        summary = self._summary(pipeline_start)
        write_heartbeat("active", {"task_id": self.task_id, "status": summary["status"]})

        # 写全流程 .done
        if summary["status"] == "COMPLETED":
            pipeline_done = TASKS_DIR / f"{self.task_id}_pipeline.done"
            write_with_verify(pipeline_done, {
                "task_id": self.task_id,
                "agent": "mochen",
                "status": "COMPLETED",
                "completed_time": datetime.now(TZ).isoformat(),
                "total_minutes": round((time.time() - pipeline_start) / 60, 1),
                "steps": {sid: rec.status for sid, rec in self.results.items()},
            })
            logger.info(f"[run] ✓ 全管线完成 ({summary['total_minutes']}min)")

        return summary

    # ── 恢复 ──
    def resume(self) -> dict:
        """
        从 checkpoint 恢复并继续执行未完成的步骤
        """
        logger.info("[resume] 尝试从 checkpoint 恢复管线...")
        return self.run()

    # ── 摘要 ──
    def _summary(self, start_time: float) -> dict:
        total_seconds = time.time() - start_time
        status = "COMPLETED"
        for rec in self.results.values():
            if rec.status == "FAIL":
                status = "FAILED"
                break
            if rec.status == "RUNNING":
                status = "INCOMPLETE"
        if self.aborted:
            status = "ABORTED"

        results_json = {}
        for sid, rec in self.results.items():
            results_json[sid] = {
                "agent": rec.agent,
                "status": rec.status,
                "verdict": rec.verdict,
                "error": rec.error,
            }

        return {
            "task_id": self.task_id,
            "date": self.date,
            "status": status,
            "total_minutes": round(total_seconds / 60, 1),
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "steps": results_json,
        }


# ═══════════════════════════════════════════════════════════════
# 快捷入口: CLI / import both
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="早报管线调度器")
    parser.add_argument("--task-id", help="task_id（默认自动生成）")
    parser.add_argument("--date", help="日期 YYYYMMDD（默认今天）")
    parser.add_argument("--resume", action="store_true", help="从 checkpoint 恢复")
    parser.add_argument("--dry-run", action="store_true", help="仅打印步骤计划，不执行")
    args = parser.parse_args()

    pipeline = MorningPipeline(task_id=args.task_id, date=args.date)

    if args.dry_run:
        print(f"=== Dry Run: {pipeline.task_id} ===")
        print(f"日期: {pipeline.date}")
        print(f"交易日: {is_trade_day(pipeline.date)}")
        print(f"\n步骤计划:")
        for s in STEPS:
            completed = pipeline.checkpoints.get_completed_steps()
            status = "✓ DONE" if s.step_id in completed else "▶ PENDING"
            print(f"  {status} {s.step_id}: {s.agent} — {s.description} ({s.estimate_minutes}min)")
        sys.exit(0)

    if args.resume:
        result = pipeline.resume()
    else:
        result = pipeline.run()

    print(json.dumps(result, ensure_ascii=False, indent=2))
