"""datasource.py — V3 层数据源读取 + 自动文件发现

P0 MVP: 从 performance_summary 读取 + 自动发现报告文件 + content_hash 计算
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .model import _hash_file


class DataSourceError(Exception):
    """数据源阶段异常"""

    def __init__(self, message: str, phase: str = "datasource", details: dict | None = None):
        super().__init__(message)
        self.phase = phase
        self.details = details or {}


class DataSource:
    """从 V3 层数据库读取回测指标 + 自动发现分析报告文件"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def fetch(self, run_id: str) -> tuple[dict | None, list[dict]]:
        """
        读取 performance_summary + 自动发现分析报告文件。

        Returns:
            perf_row: 从 performance_summary 读取的指标行 (dict), 无记录时返回 None
            doc_files: 自动发现的报告文件列表
                       [{doc_type, file_path, content_hash, file_size_bytes}, ...]
        """
        perf_row = self._fetch_perf_row(run_id)
        doc_files = self._discover_report_files(run_id)
        return perf_row, doc_files

    def _fetch_perf_row(self, run_id: str) -> dict | None:
        """从 performance_summary 读取指标行（仅 SELECT 真实存在的列）"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute("""
                SELECT total_return, annualized_return, benchmark_return, excess_return,
                       max_drawdown, sharpe_ratio, calmar_ratio, sortino_ratio,
                       volatility, var_95_pct, win_rate, total_trades,
                       max_consecutive_wins, max_consecutive_losses, final_equity
                FROM performance_summary
                WHERE run_id = ?
                ORDER BY id DESC LIMIT 1
            """, (run_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.Error as e:
            raise DataSourceError(
                f"读取 performance_summary 失败: {e}",
                details={"run_id": run_id, "sql_error": str(e)},
            ) from e
        finally:
            conn.close()

    def _discover_report_files(self, run_id: str) -> list[dict]:
        """
        目录轮询: 扫描 reports/{run_id}/ 下按 doc_type 约定命名的文件
        （简化实现: 从 reports/ 子目录轮询）
        """
        doc_files: list[dict] = []
        reports_root = self.db_path.parent / "reports"
        if not reports_root.exists():
            return doc_files

        doc_type_map = {
            "summary_report": ["summary", "report"],
            "analysis_report": ["analysis"],
            "tech_review": ["tech", "review"],
            "validation": ["validation"],
            "resolution": ["resolution"],
        }

        # 扫描 reports/ 下所有 md 文件，匹配 run_id 和 doc_type 关键字
        for file_path in reports_root.rglob("*.md"):
            stem = file_path.stem
            if run_id not in stem and run_id.replace("-", "") not in stem:
                continue
            matched_type = None
            for doc_type, keywords in doc_type_map.items():
                if any(kw in stem.lower() for kw in keywords):
                    matched_type = doc_type
                    break
            if matched_type is None:
                continue

            try:
                c_hash = self._compute_content_hash(file_path)
            except Exception:
                c_hash = ""
            f_size = file_path.stat().st_size if file_path.exists() else 0

            doc_files.append({
                "doc_type": matched_type,
                "file_path": str(file_path.resolve()),
                "content_hash": c_hash,
                "file_size_bytes": f_size,
            })

        return doc_files

    def _compute_content_hash(self, file_path: str | Path) -> str:
        """计算 SHA256 文件哈希"""
        return _hash_file(file_path)
