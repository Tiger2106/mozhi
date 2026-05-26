"""
S004 Phase2: 渠道变形警报推送
玄知 | 2026-05-25
Phase2 v1

当 compliance_flag=CRITICAL 或变形检测 score>阈值时触发警报推送。
"""

import json
from datetime import date, datetime
from typing import Dict, List, Optional
from pathlib import Path

from .deformation_tracker import DeformationScore


class DeformationAlertPusher:
    """
    渠道变形警报推送器
    支持多级告警策略：CRITICAL → 立即推送，WARN → 日汇总，INFO → 记录不推送
    """

    SIGNALS_DIR = "C:/Users/17699/mo_zhi_sharereports/试验信息库/signals"
    ALERT_FILE_TPL = "s004_deformation_alert_{date}.json"

    def __init__(self):
        self._alert_history: List[Dict] = []

    def classify_alert(self, score: DeformationScore) -> str:
        """按严重度分类"""
        if score.composite_score >= 0.7 or score.deformation_type in ("壳公司变更", "新渠道出现"):
            return "CRITICAL"
        if score.flagged and score.composite_score >= 0.55:
            return "WARN"
        if score.flagged:
            return "INFO"
        return None

    def push_alert(
        self,
        score: DeformationScore,
        severity: str
    ) -> Optional[str]:
        """
        推送单条警报
        返回推送文件路径（如果触发）
        """
        if severity == "INFO":
            # INFO 级仅记录不推送
            self._alert_history.append({
                "channel_id": score.channel_id,
                "severity": severity,
                "composite_score": score.composite_score,
                "timestamp": datetime.now().isoformat()
            })
            return None

        alert_entry = {
            "alert_id": f"ALT_{date.today().strftime('%Y%m%d')}_{score.channel_id[:8]}",
            "channel_id": score.channel_id,
            "severity": severity,
            "composite_score": score.composite_score,
            "deformation_type": score.deformation_type,
            "jaccard_similarity": score.jaccard_similarity,
            "graph_edit_distance": score.graph_edit_distance,
            "base_date": score.base_date,
            "compare_date": score.compare_date,
            "timestamp": datetime.now().isoformat(),
            "action_required": severity == "CRITICAL"
        }

        self._alert_history.append(alert_entry)

        # 写入对应 alerts 路径
        today = date.today().strftime("%Y%m%d")
        alert_dir = Path(self.SIGNALS_DIR) / "alerts" / "S004" / today
        alert_dir.mkdir(parents=True, exist_ok=True)

        filepath = alert_dir / f"alert_{score.channel_id}_{today}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "status": "READY",
                    "created_time": datetime.now().isoformat(),
                    "author": "xuanzhi",
                    "alert": alert_entry
                },
                f, ensure_ascii=False, indent=2
            )

        return str(filepath)

    def batch_push(self, alerts: List[DeformationScore]) -> Dict:
        """批量推送警报"""
        results = {"CRITICAL": [], "WARN": [], "INFO": []}

        for alert in alerts:
            severity = self.classify_alert(alert)
            if not severity:
                continue
            path = self.push_alert(alert, severity)
            if path:
                results[severity].append(path)

        return {
            "pushed": {
                "CRITICAL": len(results["CRITICAL"]),
                "WARN": len(results["WARN"]),
                "INFO": len(results["INFO"])
            },
            "total_pushed": sum(len(v) for v in results.values())
        }

    def generate_daily_summary(self, date_str: Optional[str] = None) -> Dict:
        """生成日汇总报告"""
        target_date = date_str or str(date.today())
        critical_count = sum(
            1 for a in self._alert_history
            if a.get("severity") == "CRITICAL"
        )
        warn_count = sum(
            1 for a in self._alert_history
            if a.get("severity") == "WARN"
        )

        return {
            "module": "S004",
            "component": "deformation_alert",
            "date": target_date,
            "summary": {
                "critical_alerts": critical_count,
                "warning_alerts": warn_count,
                "total_alerts": len(self._alert_history)
            },
            "all_alerts": self._alert_history[-100:]  # 保留最近100条
        }
