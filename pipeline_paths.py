#!/usr/bin/env python3
"""
pipeline_paths.py — Pipeline 路径常量模块（v1.0）

统一管理早报/午报管线各步骤的产出路径。
所有引用 pathlib.Path，外部模块通过本模块获取路径，不硬编码。

作者: 墨衡 (moheng)
创建时间: 2026-05-18 08:58 +08:00
版本: v1.0
"""

import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── R1 基准常量 ──
R1_BENCHMARK_SYMBOLS = ["601857", "600036", "000333", "300750", "002594"]
"""R1 标准验证标的（5 只大盘 A50 成分股）"""

# ── 时区 ──
TZ = timezone(timedelta(hours=8))

# ── 根目录定义（from src.config） ──

import sys
# 确保 src/ 在 sys.path 中
_src_root = Path(__file__).resolve().parent / "src"
if str(_src_root.parent) not in sys.path:  # mozhi_platform/
    sys.path.insert(0, str(_src_root.parent))

from src.config import get_mozhihome, PROJECT_ROOT


# 新平台根（主产出目录）
# 逐步迁移到此处，旧路径 mo_zhi_sharereports 保留短期兼容
MOZHI_BASE = PROJECT_ROOT

# 旧共享目录（兼容层）
SHARED_BASE_LEGACY = Path.home() / "mo_zhi_sharereports"

# 旧实验信息库（信号/trigger/task 文件）
EXPERIMENT_BASE_LEGACY = SHARED_BASE_LEGACY / "试验信息库"


# ── 报告路径函数 ──

def reports_base() -> Path:
    """报告产出根目录（新平台）"""
    return MOZHI_BASE / "reports"


def reports_base_legacy() -> Path:
    """报告产出根目录（旧路径，兼容层）"""
    return SHARED_BASE_LEGACY / "reports"


def report_dir(report_type: str, date_str: str) -> Path:
    """struct analysis / review / draft / final 产出目录

    Args:
        report_type: "morning" | "midday"
        date_str: "YYYYMMDD"

    Returns:
        Path: C:/Users/17699/mozhi_platform/reports/{report_type}/{date_str}/
    """
    return reports_base() / report_type / date_str


def report_dir_legacy(report_type: str, date_str: str) -> Path:
    """旧版报告产出目录（兼容层）"""
    return reports_base_legacy() / report_type / date_str


def morning_path(date_str: str) -> Path:
    """早报产出目录快捷方式"""
    return report_dir("morning", date_str)


def midday_path(date_str: str) -> Path:
    """午报产出目录快捷方式"""
    return report_dir("midday", date_str)


def step_output_path(
    step: int,
    task_id: str,
    report_type: str = "morning",
    date_str: Optional[str] = None,
) -> Path:
    """按步骤获取产出文件路径

    Steps 及其文件命名（格式: {action}_{base_task_id}_step{N}.{ext} 一致）:
        Step0  (玄知扫描):   macro_analysis_{task_id}.json
        Step1  (墨衡分析):   structured_analysis_{task_id}.json
        Step2  (墨萱草稿):   morning_draft_{task_id}.md
        Step3  (墨衡审查):   review_feedback_{task_id}.md
        Step3.5(玄知复核):   strategic_review_{task_id}_step35.md
        Step4  (墨萱定稿):   final_report_{task_id}_step4.md
        Step5  (墨涵推送):   (飞书消息)

    Args:
        step: 步骤号 (0, 1, 2, 3, 3.5, 4, 5)
        task_id: 任务 ID（如 morning_report_20260518）
        report_type: "morning" | "midday"
        date_str: 日期 YYYYMMDD（默认从 task_id 提取）

    Returns:
        Path: 文件完整路径
    """
    if date_str is None:
        # 从 task_id 提取日期（正则匹配8位数字 YYYYMMDD）
        date_str = _extract_date(task_id)

    d = report_dir(report_type, date_str)

    step_files = {
        0:   f"macro_analysis_{task_id}.json",
        1:   f"structured_analysis_{task_id}.json",
        2:   f"morning_draft_{task_id}.md",
        3:   f"review_feedback_{task_id}.md",
        3.5: f"strategic_review_{task_id}_step35.md",
        4:   f"final_report_{task_id}_step4.md",
        # Step5 is feishu push — no file output
    }

    filename = step_files.get(step)
    if filename is None:
        raise ValueError(f"未知的步骤号: {step}")

    return d / filename


def step_output_path_legacy(
    step: int,
    task_id: str,
    report_type: str = "morning",
    date_str: Optional[str] = None,
) -> Path:
    """旧版路径兼容版"""
    if date_str is None:
        date_str = _extract_date(task_id)

    d = report_dir_legacy(report_type, date_str)

    step_files = {
        0:   f"macro_analysis_{task_id}.json",
        1:   f"structured_analysis_{task_id}.json",
        2:   f"morning_draft_{task_id}.md",
        3:   f"review_feedback_{task_id}.md",
        3.5: f"strategic_review_{task_id}_step35.md",
        4:   f"final_report_{task_id}_step4.md",
    }

    filename = step_files.get(step)
    if filename is None:
        raise ValueError(f"未知的步骤号: {step}")

    return d / filename


# ── 信号/trigger/task 目录 ──

def signals_dir() -> Path:
    """信号目录（新平台）"""
    return MOZHI_BASE / "signals"


def triggers_dir() -> Path:
    """触发文件目录"""
    return signals_dir() / "triggers"


def tasks_dir() -> Path:
    """任务完成信号目录（.done / .failed / notify 等）"""
    return signals_dir() / "tasks"


def heartbeat_dir() -> Path:
    """心跳目录（agents 间一致性检测）"""
    return signals_dir() / "consensus" / "heartbeat"


def locks_dir() -> Path:
    """互斥锁目录"""
    return signals_dir() / "locks"


# ── 数据库路径函数 ──

def market_data_db() -> Path:
    """市场行情数据库路径（stock_daily 表专用）

    替代 analysis.db 中的 stock_daily 查询，
    分离市场行情数据与其他数据（oil_daily, tech_indicators, trading_calendar）。
    """
    db_path = MOZHI_BASE / "data" / "market" / "market_data.db"
    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def analysis_db_legacy() -> Path:
    """旧 analysis.db 路径（oil_daily, tech_indicators, trading_calendar 等非行情数据）

    迁移完成后仅保留非 stock_daily 的数据表。
    """
    return SHARED_BASE_LEGACY / "analysis.db"


# ── 旧路径兼容层 ──

def signals_dir_legacy() -> Path:
    """旧信号目录（兼容）"""
    return SHARED_BASE_LEGACY / "signals"


def triggers_dir_legacy() -> Path:
    """旧触发文件目录"""
    return signals_dir_legacy() / "triggers"


def tasks_dir_legacy() -> Path:
    """旧任务完成信号目录（.done / .failed 等）"""
    return signals_dir_legacy() / "tasks"


def heartbeat_dir_legacy() -> Path:
    """旧心跳目录"""
    return signals_dir_legacy() / "consensus" / "heartbeat"


def experiment_signals_dir() -> Path:
    """试验信息库信号目录（旧旧路径，dispatcher 使用的路径）"""
    return EXPERIMENT_BASE_LEGACY / "signals"


def experiment_triggers_dir() -> Path:
    """试验信息库触发文件目录（旧旧路径）"""
    return experiment_signals_dir() / "triggers"


# ── 写入帮助函数 ──

def write_output(
    file_content: str,
    path: Path,
    encoding: str = "utf-8",
) -> bool:
    """只写指定路径，不自动写旧路径（单写模式）。

    替代 write_new_and_legacy()，用于过渡期结束后只写新路径。

    Args:
        file_content: 文件内容（str）
        path: 目标文件路径
        encoding: 文件编码（默认 utf-8）

    Returns:
        True 写入成功，False 写入失败
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file_content, encoding=encoding)
        return True
    except Exception as e:
        print(f"[pipeline_paths] 写入失败 {path}: {e}")
        return False


def write_new_and_legacy(
    file_content: str,
    new_path: Path,
    legacy_path: Optional[Path] = None,
    encoding: str = "utf-8",
) -> tuple[bool, bool]:
    """⚠️ DEPRECATED: 请使用 write_output() 替代。

    同时写入新旧两个位置，确保过渡期兼容。
    仅在历史兼容场景保留，新代码不要调用。

    Args:
        file_content: 文件内容（str）
        new_path: 新路径（mozhi_platform）
        legacy_path: 旧路径（mo_zhi_sharereports），None 时自动推断

    Returns:
        (new_ok, legacy_ok): 两个写入是否成功
    """
    new_ok = False
    legacy_ok = False

    # 新路径写入
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(file_content, encoding=encoding)
        new_ok = True
    except Exception as e:
        print(f"[pipeline_paths] 新路径写入失败 {new_path}: {e}")

    # 旧路径写入（兼容层）
    if legacy_path is not None:
        try:
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(file_content, encoding=encoding)
            legacy_ok = True
        except Exception as e:
            print(f"[pipeline_paths] 旧路径写入失败 {legacy_path}: {e}")

    return new_ok, legacy_ok


def resolve_path(
    path: Path,
    old_base: Optional[Path] = None,
    new_base: Optional[Path] = None,
) -> Path:
    """将旧路径转换为新路径（如果父路径匹配）

    resolve_path(old_path) -> mozhi_platform equivalent path.
    如果 old_path 不在旧 base 下，返回原 path。
    """
    if old_base is None:
        old_base = SHARED_BASE_LEGACY
    if new_base is None:
        new_base = MOZHI_BASE

    try:
        rel = path.relative_to(old_base)
        return new_base / rel
    except ValueError:
        return path


# ── 日期工具 ──

def today_str() -> str:
    """当前日期 YYYYMMDD"""
    return datetime.now(TZ).strftime("%Y%m%d")


def infer_report_type(task_id: str) -> str:
    """从 task_id 推断 report_type: morning 或 midday"""
    # 优先读 trigger 文件
    from pathlib import Path
    import json

    for step in [1, 2, 3, 4]:
        trigger_file = experiment_triggers_dir() / f"trigger_step{step}_{task_id}.json"
        if trigger_file.exists():
            try:
                data = json.loads(trigger_file.read_text(encoding="utf-8"))
                if "report_type" in data:
                    return data["report_type"]
            except Exception:
                pass

    # 从 task_id 时间推断
    if "_" in task_id:
        parts = task_id.split("_")
        if len(parts) >= 2 and len(parts[1]) >= 2:
            hour = parts[1][:2]
            if hour.isdigit():
                return "morning" if int(hour) < 11 else "midday"

    return "morning"


def _extract_date(task_id: str) -> str:
    """从 task_id 提取日期 YYYYMMDD（正则匹配8位数字，支持多种命名格式）"""
    m = re.search(r'(\d{8})', task_id)
    if m:
        return m.group(1)
    return today_str()


def infer_date(task_id: str) -> str:
    """从 task_id 提取日期 YYYYMMDD（仅保留兼容性）"""
    return _extract_date(task_id)


# ── R1 重构扩展路径 ──
# 以下函数为 R1 架构重构阶段一新增（2026-05-18）


def research_base() -> Path:
    """研究报告根目录"""
    return MOZHI_BASE / "reports" / "research"


def research_date_dir(date_str: str) -> Path:
    """指定日期研究报告目录"""
    return research_base() / date_str


def research_report_dir() -> Path:
    """当日研究报告目录（向后兼容）"""
    return research_date_dir(today_str())


def factors_data_dir(category: str, date_str: str) -> Path:
    """因子数据缓存目录

    Args:
        category: 因子分类（如 vwap, volume_profile, regime）
        date_str: 日期 YYYYMMDD
    """
    return MOZHI_BASE / "data" / "factors" / category / date_str


def checkpoint_file(phase: str, task_id: str) -> Path:
    """流水线检查点文件路径

    Args:
        phase: 阶段标识（如 "2", "3a"）
        task_id: 任务 ID
    """
    return signals_dir() / "checkpoints" / f"phase{phase}_{task_id}.json"


def knowledge_file(method_name: str, date_str: str) -> Path:
    """研究方法知识沉淀文件

    Args:
        method_name: 研究方法名（如 breakout_retest, continuation）
        date_str: 日期 YYYYMMDD
    """
    return research_date_dir(date_str) / f"knowledge_{method_name}.md"


def research_logs_dir(date_str: str) -> Path:
    """研究日志目录"""
    return research_date_dir(date_str) / "logs"


def execution_data_dir(date_str: str) -> Path:
    """回测执行日志目录（通用，与日期无关）"""
    return MOZHI_BASE / "data" / "execution"


def factor_cache_dir(date_str: str = "") -> Path:
    """因子计算缓存目录（带 TTL 的中间计算结果）"""
    d = MOZHI_BASE / "data" / "factors" / "cache"
    if date_str:
        d = d / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def market_data_dir(date_str: str = "") -> Path:
    """市场数据缓存目录

    Args:
        date_str: 日期 YYYYMMDD（可选，省略则返回基础目录）
    """
    base = MOZHI_BASE / "data" / "market"
    if date_str:
        return base / date_str
    return base
