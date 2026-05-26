"""
S004 Phase2: 灰名单渠道表动态更新
玄知 | 2026-05-25
Phase2 v1

基于变形跟踪结果，自动扩充/降级灰名单条目。
"""

import json
from datetime import date, datetime
from typing import Dict, List, Optional
from pathlib import Path

from .deformation_tracker import DeformationTracker, DeformationScore


class GrayListManager:
    """
    灰名单渠道表管理器
    功能：
    - 自动扩充：新增变形渠道加入灰名单
    - 自动降级：持续无异常的渠道降低监控等级
    - 过期清理：超期未更新渠道进入归档
    """

    def __init__(self, gray_list_path: Optional[str] = None):
        self._gray_list_path = gray_list_path
        self._gray_list: Dict[str, Dict] = {}  # channel_id -> entry
        self._tracker = DeformationTracker()

        if gray_list_path:
            self._load()

    def _load(self):
        """从文件加载灰名单"""
        try:
            with open(self._gray_list_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data:
                self._gray_list[entry["channel_id"]] = entry
        except (FileNotFoundError, json.JSONDecodeError):
            self._gray_list = {}

    def save(self, path: Optional[str] = None):
        """保存至文件"""
        save_path = path or self._gray_list_path
        if not save_path:
            return
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        data = list(self._gray_list.values())
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_channel(
        self,
        channel_id: str,
        channel_type: str,
        source: str,
        metadata: Optional[Dict] = None,
        auto_monitor: bool = True
    ) -> str:
        """
        新增灰名单渠道条目
        返回监控等级: HIGH | MEDIUM | LOW
        """
        level = "HIGH" if source == "deformation_alert" else "MEDIUM"

        self._gray_list[channel_id] = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "added_date": str(date.today()),
            "last_updated": str(date.today()),
            "monitor_level": level,
            "source": source,
            "alert_count": 0,
            "metadata": metadata or {},
            "status": "active"
        }

        return level

    def escalate(self, channel_id: str, reason: str) -> bool:
        """提升渠道监控等级"""
        if channel_id not in self._gray_list:
            return False

        entry = self._gray_list[channel_id]
        current_level = entry["monitor_level"]
        if current_level == "HIGH":
            return False  # 已在最高级

        levels = ["LOW", "MEDIUM", "HIGH"]
        current_idx = levels.index(current_level)
        if current_idx < len(levels) - 1:
            entry["monitor_level"] = levels[current_idx + 1]
        entry["alert_count"] = entry.get("alert_count", 0) + 1
        entry["last_updated"] = str(date.today())
        entry["last_alert_reason"] = reason
        return True

    def downgrade(self, channel_id: str, reason: str = "持续无异常") -> bool:
        """降低渠道监控等级"""
        if channel_id not in self._gray_list:
            return False

        entry = self._gray_list[channel_id]
        current_level = entry["monitor_level"]
        if current_level == "LOW":
            return False  # 已在最低级

        levels = ["LOW", "MEDIUM", "HIGH"]
        current_idx = levels.index(current_level)
        if current_idx > 0:
            entry["monitor_level"] = levels[current_idx - 1]
        entry["last_updated"] = str(date.today())
        entry["last_downgrade_reason"] = reason
        return True

    def archive_stale(self, days_no_update: int = 30) -> List[str]:
        """归档超期未更新渠道"""
        archived = []
        today = date.today()
        for cid, entry in list(self._gray_list.items()):
            last_date = datetime.strptime(entry["last_updated"], "%Y-%m-%d").date()
            if (today - last_date).days > days_no_update:
                entry["status"] = "archived"
                archived.append(cid)
        return archived

    def get_active_list(self) -> List[Dict]:
        """获取活跃灰名单"""
        return [
            v for v in self._gray_list.values()
            if v.get("status", "active") == "active"
        ]

    def get_alert_summary(self) -> Dict:
        """获取灰名单概览"""
        levels = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for entry in self._gray_list.values():
            if entry.get("status", "active") == "active":
                lv = entry.get("monitor_level", "LOW")
                levels[lv] = levels.get(lv, 0) + 1

        return {
            "total_active": sum(levels.values()),
            "by_level": levels,
            "archived_count": sum(
                1 for v in self._gray_list.values()
                if v.get("status") == "archived"
            )
        }

    def process_deformation_results(
        self,
        alerts: List[DeformationScore]
    ) -> Dict:
        """
        根据变形检测结果更新灰名单
        自动扩充/升级/降级
        """
        upgrades = 0
        downgrades = 0
        additions = 0

        for alert in alerts:
            if alert.flagged:
                if alert.channel_id in self._gray_list:
                    # 已有渠道：升级监控
                    self.escalate(alert.channel_id, f"变形警报: {alert.deformation_type}")
                    upgrades += 1
                else:
                    # 新渠道：自动加入灰名单
                    self.add_channel(
                        alert.channel_id,
                        "unknown",
                        "deformation_alert",
                        {"deformation_score": alert.composite_score}
                    )
                    additions += 1

        return {
            "upgrades": upgrades,
            "downgrades": downgrades,
            "additions": additions,
            "total_active": len(self.get_active_list())
        }
