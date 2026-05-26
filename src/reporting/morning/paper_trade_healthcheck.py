"""morning_healthcheck — 晨间执行巡检任务（BS-3）

检查今日晨间 executor 是否正常运行。

触发方式：
  cron 每30分钟触发一次

检查逻辑：
  1. 今日 execution_report_meta_{date}.json 是否存在
  2. 若存在且 status != "started" → 正常（有END标记），跳过
  3. 若存在且 status == "started" → 异常（执行中超过30分钟无END标记），写入告警
  4. 若不存在且当前时间 > 08:05 → 异常（executor 从未启动），写入告警
  5. 若不存在且当前时间 <= 08:05 → 正常（executor 尚未到触发时间），跳过

告警方式：
  写入 signals/alerts/{date}_executor_alert.json

告警幂等：
  若告警文件已存在，不重复写入。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Dict, Optional

from utils import time_utils
from paper_trade.operation_record import OperationRecord

logger = logging.getLogger("paper_trade.morning_healthcheck")

# ============================================================
# 常量
# ============================================================

DEFAULT_BASE = "mo_zhi_sharereports"
EXECUTOR_START_DEADLINE = time_utils.time(8, 5)  # 08:05 后判断为"未启动"
HEALTHCHECK_GRACE_MINUTES = 35                     # 启动后35分钟内无END标记也视为正常

ALERT_DIR_TEMPLATE = "signals/alerts"
ALERT_FILENAME_TEMPLATE = "{date}_executor_alert.json"


class MorningHealthCheck:
    """晨间巡检任务。

    用法：
        hc = MorningHealthCheck()
        report = hc.run()  # 返回巡检报告
    """

    def __init__(self, base_dir: str = DEFAULT_BASE):
        self.base_dir = base_dir
        self.alert_dir = os.path.join(base_dir, ALERT_DIR_TEMPLATE)

    def run(self, check_date: Optional[date] = None) -> Dict[str, Any]:
        """执行晨间巡检。

        参数：
            check_date — 巡检日期（None =当日）

        返回：
            {
                "status": "HEALTHY" | "ALERT" | "NOT_YET",
                "message": "...",
                "alert_written": True/False,
                "check_time": "ISO8601"
            }
        """
        now = time_utils.now()
        dt = check_date or now.date()
        date_str = dt.strftime("%Y%m%d")
        current_time = now.time()

        # 构建 OperationRecord 以读取执行元数据
        rec = OperationRecord(task_id="_healthcheck", base_dir=self.base_dir, record_date=dt)
        meta = rec.read_execution_meta()

        # ---- 判断逻辑 ----

        if meta is not None:
            status = meta.get("status", "unknown")
            if status == "started":
                # executor 曾启动但可能卡住
                begin_at = meta.get("begin_at", "")
                alert = self._check_timeout(date_str, begin_at, rec)
                if alert:
                    return self._write_alert(date_str, "EXECUTOR_STUCK", alert)

                # 还未超时，继续等待
                return {
                    "status": "HEALTHY",
                    "message": f"executor 正在执行中（{begin_at}）",
                    "alert_written": False,
                    "check_time": now.isoformat(),
                }
            else:
                # success / partial / failed → 正常（已有END标记）
                return {
                    "status": "HEALTHY",
                    "message": f"executor 已完成（status={status}）",
                    "alert_written": False,
                    "check_time": now.isoformat(),
                }
        else:
            # 元数据不存在
            if current_time >= EXECUTOR_START_DEADLINE:
                # 08:05 后仍无元数据 → 异常
                msg = f"executor 未在 {EXECUTOR_START_DEADLINE.strftime('%H:%M')} 前启动（execution_report_meta 不存在）"
                return self._write_alert(date_str, "EXECUTOR_MISSING", msg)
            else:
                # 08:05 前，尚未到触发时间
                return {
                    "status": "NOT_YET",
                    "message": f"executor 触发时间未到（当前 {current_time.strftime('%H:%M')}）",
                    "alert_written": False,
                    "check_time": now.isoformat(),
                }

    def _check_timeout(
        self,
        date_str: str,
        begin_at: str,
        rec: OperationRecord,
    ) -> Optional[str]:
        """检查 executor 是否在合理时间内未完成。

        begin_at > (当前时间 - 缓冲分钟数) → 尚在缓冲期内，不告警
        否则 → 超时告警
        """
        try:
            begin_dt = time_utils.datetime.fromisoformat(begin_at)
            deadline = begin_dt + time_utils.timedelta(minutes=HEALTHCHECK_GRACE_MINUTES)

            if time_utils.now() > deadline:
                return (
                    f"executor 已执行超过 {HEALTHCHECK_GRACE_MINUTES} 分钟无 END 标记"
                    f"（begun_at={begin_at}）"
                )
        except (ValueError, TypeError):
            return f"解析 begin_at 失败: {begin_at}"

        return None

    def _write_alert(self, date_str: str, alert_type: str, message: str) -> Dict[str, Any]:
        """写入告警文件（幂等）。"""
        os.makedirs(self.alert_dir, exist_ok=True)
        alert_path = os.path.join(self.alert_dir, ALERT_FILENAME_TEMPLATE.format(date=date_str))

        if os.path.exists(alert_path):
            # 告警已存在，不重复写入
            logger.warning("告警文件已存在（幂等跳过）: %s", alert_path)
            return {
                "status": "ALERT",
                "message": f"[已有告警] {message}",
                "alert_written": False,
                "check_time": time_utils.now().isoformat(),
            }

        data = {
            "alert_type": alert_type,
            "date": date_str,
            "message": message,
            "created_at": time_utils.now().isoformat(),
        }

        with open(alert_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.warning("告警已写入: %s — %s", alert_path, message)
        return {
            "status": "ALERT",
            "message": message,
            "alert_written": True,
            "check_time": time_utils.now().isoformat(),
        }
