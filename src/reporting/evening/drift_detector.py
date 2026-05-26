#!/usr/bin/env python3
"""drift_detector — 上游行情数据漂移检测 (BS-005)

检测逻辑：
  1. 零值/空值检测：acv=0 或 adj_close=0 → 标记异常
  2. 跳空检测：当天 adj_close 对比前一日 >3% → 标记 drift
  3. 字段缺失检测：预期字段缺失 → 标记异常

数据源：
  analysis.db → stock_daily 表（含 code, date, close, amount, adj_factor）
  acv = amount, adj_close = close * adj_factor

告警集成：
  发现 drift 后调用 alert_pipeline.write_alert()
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, timezone, timedelta

# 确保能找到 paper_trade 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reporting.evening.alert_pipeline import write_alert
from src.config import SHANGHAI_TZ

logger = logging.getLogger("drift_detector")

TZ = SHANGHAI_TZ

# 预期字段（输出时用）
EXPECTED_FIELDS = ["date", "symbol", "acv", "adj_close", "open", "high", "low", "close", "volume"]
DRIFT_THRESHOLD = 0.03  # 3% 跳空阈值

# 默认数据库路径
DEFAULT_DB = r"C:\Users\17699\mo_zhi_sharereports\analysis.db"


class DriftDetector:
    """数据漂移检测器"""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self.drifts = []

    # ---------------------------------------------------------------
    # 检测方法
    # ---------------------------------------------------------------

    def check_acv_adj_close(self, row: dict) -> list:
        """单条零值/空值检测，返回 drift 列表"""
        issues = []

        # acv 检测（原始字段 amount）
        acv = row.get("acv", 0)
        if acv is None or acv <= 0:
            issues.append({
                "type": "zero_acv",
                "severity": "orange",
                "detail": f"acv={acv}",
                "symbol": row.get("symbol", ""),
                "date": row.get("date", ""),
            })

        # adj_close 检测
        adj_close = row.get("adj_close", 0)
        if adj_close is None or adj_close <= 0:
            issues.append({
                "type": "zero_adj_close",
                "severity": "orange",
                "detail": f"adj_close={adj_close}",
                "symbol": row.get("symbol", ""),
                "date": row.get("date", ""),
            })

        # 字段缺失检测
        for field in EXPECTED_FIELDS:
            if field not in row:
                issues.append({
                    "type": "missing_field",
                    "severity": "red",
                    "detail": f"缺少预期字段: {field}",
                    "symbol": row.get("symbol", ""),
                    "date": row.get("date", ""),
                })

        return issues

    def check_gap(self, row: dict, prev: dict) -> list:
        """跳空检测（当天 vs 前一日 adj_close）"""
        issues = []

        cur = row.get("adj_close", 0) or 0
        prv = prev.get("adj_close", 0) or 0

        if cur and prv:
            gap_ratio = abs(cur - prv) / prv
            if gap_ratio > DRIFT_THRESHOLD:
                issues.append({
                    "type": "price_gap",
                    "severity": "orange",
                    "detail": f"跳空 {gap_ratio * 100:.1f}% (cur={cur:.4f}, prev={prv:.4f})",
                    "symbol": row.get("symbol", ""),
                    "date": row.get("date", ""),
                    "cur_price": round(cur, 4),
                    "prev_price": round(prv, 4),
                    "gap_ratio": round(gap_ratio, 4),
                })

        return issues

    # ---------------------------------------------------------------
    # 数据加载 (analysis.db → stock_daily)
    # ---------------------------------------------------------------

    def _load_data(self, limit: int = 200) -> list:
        """从 analysis.db 加载最近 N 条 stock_daily 记录，映射为标准字段"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 从 stock_daily 表取最近 N 条，升序排列（从旧到新）
        cursor.execute(
            """
            SELECT code, date, open, high, low, close, volume, amount, adj_factor
            FROM stock_daily
            ORDER BY date DESC
            LIMIT ?
            """,
            (limit,),
        )
        raw = [dict(r) for r in cursor.fetchall()]
        conn.close()

        # 映射为标准字段
        rows = []
        for r in reversed(raw):  # 反转回升序
            adj_factor = r.get("adj_factor", 1.0) or 1.0
            rows.append({
                "date": r.get("date", ""),
                "symbol": r.get("code", ""),
                "acv": r.get("amount", 0) or 0,
                "adj_close": (r.get("close", 0) or 0) * adj_factor,
                "open": r.get("open", 0) or 0,
                "high": r.get("high", 0) or 0,
                "low": r.get("low", 0) or 0,
                "close": r.get("close", 0) or 0,
                "volume": r.get("volume", 0) or 0,
            })

        return rows

    # ---------------------------------------------------------------
    # 全量扫描
    # ---------------------------------------------------------------

    def run_check(self) -> dict:
        """全量扫描，收集所有 drift 并触发告警

        返回:
            {
                "drift_detected": bool,
                "issues": [...],
                "total_checked": int,
                "alert_count": int,
                "timestamp": str,
            }
        """
        rows = self._load_data(limit=200)
        all_issues = []
        alert_count = 0

        if not rows:
            logger.warning("行情数据为空，跳过漂移检测")
            return {
                "drift_detected": False,
                "issues": [],
                "total_checked": 0,
                "alert_count": 0,
                "timestamp": datetime.now(TZ).isoformat(),
            }

        # 逐条检测
        for i, row in enumerate(rows):
            issues = self.check_acv_adj_close(row)
            if i > 0:
                issues.extend(self.check_gap(row, rows[i - 1]))

            for issue in issues:
                all_issues.append(issue)
                # 通过 alert_pipeline 发送告警
                severity = "WARNING" if issue["severity"] == "orange" else "CRITICAL"
                write_alert(
                    source="drift_detector",
                    severity=severity,
                    message=f"[数据漂移] {issue['type']} — {issue['detail']}",
                    details={
                        "type": issue["type"],
                        "symbol": issue["symbol"],
                        "date": issue["date"],
                    },
                )
                alert_count += 1

        drift_detected = len(all_issues) > 0
        result = {
            "drift_detected": drift_detected,
            "issues": all_issues,
            "total_checked": len(rows),
            "alert_count": alert_count,
            "timestamp": datetime.now(TZ).isoformat(),
        }

        if drift_detected:
            logger.warning(f"发现 {len(all_issues)} 个漂移项 (共检查 {len(rows)} 条)")
            # 打印简要摘要
            for iss in all_issues[:5]:
                print(f"  [DRIFT] {iss['date']} {iss['symbol']:>6s} | {iss['type']:15s} | {iss['detail']}")
            if len(all_issues) > 5:
                print(f"  ... 还有 {len(all_issues)-5} 个漂移项")
        else:
            print(f"[drift_detector] ✅ 未发现漂移 (共检查 {len(rows)} 条)")

        # 写入扫描摘要
        self._write_summary(result)

        return result

    def _write_summary(self, result: dict):
        """写入扫描摘要到 signals/drift/"""
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "signals")
        )
        drift_dir = os.path.join(base, "drift")
        os.makedirs(drift_dir, exist_ok=True)

        summary_path = os.path.join(
            drift_dir,
            f"drift_scan_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.json",
        )
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------

def main():
    """CLI 启动点"""
    print(f"[drift_detector] 启动漂移检测 ({datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')})")
    detector = DriftDetector()
    result = detector.run_check()
    if result["drift_detected"]:
        sys.exit(1)  # drift 存在时非零退出
    sys.exit(0)


if __name__ == "__main__":
    main()
