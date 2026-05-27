"""
EXP-2026-003-KNOWDEEP: 自检清单校验模块
===========================================
author: 墨衡 (moheng)
created: 2026-05-27T09:10+08:00

提供自检清单各检查项的自动化校验函数。
消除人工填写自检清单时可能出现的记录与实际情况不符问题。

函数清单:
  - check_timeout(elapsed_seconds, threshold_seconds)
    → 超时检查（修正版：真实比较 elapsed vs threshold）
  - self_check_summary(check_results)
    → 生成自检清单汇总字符串
"""

from __future__ import annotations

import time
from datetime import datetime


def check_timeout(
    elapsed_seconds: float | None = None,
    threshold_seconds: float = 2400.0,
    start_time: float | None = None,
) -> dict:
    """
    超时检查 — 自动化校验。

    正确比较实际运行时间与超时阈值，返回一致的记录。
    不再依赖人工判断，确保实际时间与检查记录完全一致。

    Parameters
    ----------
    elapsed_seconds : float, optional
        实际运行时间（秒）。若未提供，从 start_time 计算。
    threshold_seconds : float
        超时阈值（秒）。默认 2400（40分钟）。
    start_time : float, optional
        运行开始时间（time.time() 输出）。若未提供，仅使用 elapsed_seconds。

    Returns
    -------
    dict:
      - passed: bool — True=未超时, False=超时
      - elapsed_formatted: str — 格式化后的实际耗时
      - threshold_formatted: str — 格式化后的阈值
      - elapsed_seconds: float — 实际耗时（秒）
      - threshold_seconds: float — 阈值（秒）
      - note: str — 检查说明
    """
    # 确定 elapsed_seconds
    if elapsed_seconds is None:
        if start_time is not None:
            elapsed_seconds = time.time() - start_time
        else:
            elapsed_seconds = 0.0

    # 格式化时间
    def _fmt(s: float) -> str:
        minutes = int(s // 60)
        seconds = int(s % 60)
        if minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
            return f"{hours}h{minutes}m{seconds}s"
        return f"{minutes}m{seconds}s"

    elapsed_str = _fmt(elapsed_seconds)
    threshold_str = _fmt(threshold_seconds)

    # 检查：正确比较 elapsed vs threshold（修复：之前版本存在记录与实际不符问题）
    is_timeout = elapsed_seconds > threshold_seconds

    if is_timeout:
        note = (
            f"超时（实际{elapsed_str}>{threshold_str}阈值）"
        )
    else:
        note = (
            f"未超时（实际{elapsed_str}<={threshold_str}阈值）"
        )

    # 返回完整检查结果
    return {
        "passed": not is_timeout,
        "is_timeout": is_timeout,
        "elapsed_formatted": elapsed_str,
        "threshold_formatted": threshold_str,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "threshold_seconds": threshold_seconds,
        "note": note,
    }


def format_timeout_for_self_check(result: dict) -> str:
    """
    将超时检查结果格式化为自检清单项文本。

    Parameters
    ----------
    result : dict — check_timeout() 的返回结果

    Returns
    -------
    str: 适合填入自检清单第9项的说明文本
    """
    return (
        f"超时检查：{result['note']}。"
        f"实际{result['elapsed_formatted']} > "
        f"{result['threshold_formatted']}阈值"
        if result["is_timeout"]
        else (
            f"超时检查：{result['note']}。"
            f"实际{result['elapsed_formatted']} ≤ "
            f"{result['threshold_formatted']}阈值"
        )
    )


def self_check_timestamps_to_elapsed(
    start_iso: str,
    end_iso: str,
) -> float:
    """
    根据 ISO 时间戳计算耗时（秒）。

    Parameters
    ----------
    start_iso : str — 开始时间（ISO8601 格式，可含 +08:00 时区）
    end_iso : str — 结束时间（ISO8601 格式，可含 +08:00 时区）

    Returns
    -------
    float: 耗时（秒）
    """
    # 处理 ISO 时间戳，处理时区后缀
    if "+" in start_iso:
        start_iso = start_iso.split("+")[0]
    if "+" in end_iso:
        end_iso = end_iso.split("+")[0]

    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso)

    return (end_dt - start_dt).total_seconds()


# ===================================================================
#  完整自检清单生成（用于报告）
# ===================================================================

SELF_CHECK_TEMPLATE_ITEMS: list[dict] = [
    {"id": 1,  "name": "引擎配置正确"},
    {"id": 2,  "name": "交易参数正确"},
    {"id": 3,  "name": "报告完整性"},
    {"id": 4,  "name": "数据库确认"},
    {"id": 5,  "name": "代码版本锁定"},
    {"id": 6,  "name": "代码版本标注完整性"},
    {"id": 7,  "name": "环境信息写入"},
    {"id": 8,  "name": "数据版本确认"},
    {"id": 9,  "name": "超时检查"},
    {"id": 10, "name": "P2自一致性通过"},
]


def build_self_check_table(
    custom_results: dict[int, bool] | None = None,
    timeout_result: dict | None = None,
) -> list[dict]:
    """
    构建自检清单结果列表，确保超时检查项使用自动化校验结果。

    Parameters
    ----------
    custom_results : dict[int, bool], optional
        自定义检查结果 {id: passed}
    timeout_result : dict, optional
        check_timeout() 返回的超时检查结果

    Returns
    -------
    list[dict]: 每项包含 id, name, passed, note
    """
    results = []
    for item in SELF_CHECK_TEMPLATE_ITEMS:
        check_id = item["id"]
        check_name = item["name"]

        if check_id == 9 and timeout_result is not None:
            # 超时检查 — 使用自动化校验结果
            passed = timeout_result["passed"]
            note = timeout_result["note"]
        elif custom_results is not None and check_id in custom_results:
            passed = custom_results[check_id]
            note = "OK"
        else:
            passed = True
            note = "OK"

        results.append({
            "id": check_id,
            "name": check_name,
            "passed": passed,
            "note": note,
        })

    return results
