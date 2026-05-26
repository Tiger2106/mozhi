"""
墨枢 - C1: KnowledgeService
知识库查询层 — 封装从 knowledge.db 读取数据的接口，供日报管线消费。

设计原则：
- 只读：不写入 knowledge.db，仅消费已有数据
- 报告导向：方法按报告消费需求设计，而非通用 ORM
- 零依赖：仅依赖 Python 标准库 + 已存在的 KnowledgeDatabase 类
- 容错：数据异常时优雅降级，不抛未捕获异常

Author: 墨衡
Created: 2026-05-16T15:52+08:00
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from src.config import SHANGHAI_TZ

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

_KB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "knowledge.db")

TZ_CST = SHANGHAI_TZ

_STRATEGY_LABELS = {
    "grid": "网格策略",
    "trend": "趋势策略",
    "reversal": "反转策略",
}

_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


# ═══════════════════════════════════════════════════════════════
# 异常类型
# ═══════════════════════════════════════════════════════════════


class KnowledgeServiceError(Exception):
    """KnowledgeService 运行时异常基类"""


# ═══════════════════════════════════════════════════════════════
# 核心类
# ═══════════════════════════════════════════════════════════════


class KnowledgeService:
    """知识库查询层 — 为日报管线提供 knowledge.db 数据的只读访问。

    用法::

        ks = KnowledgeService()
        stats = ks.get_strategy_stats("601857")
        best = ks.get_best_strategy("601857")
        ctx = ks.get_market_context_summary()
        insights = ks.get_knowledge_insights_for_report(["601857"])
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _KB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    # ── 连接管理 ──────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """延迟打开数据库连接（每次查询打开/关闭，避免跨 session 状态）"""
        if self._conn is None:
            if not os.path.isfile(self.db_path):
                raise KnowledgeServiceError(f"知识库文件不存在: {self.db_path}")
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        """显式关闭连接"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── 元数据 ──────────────────────────────────────

    def summarize(self) -> dict:
        """返回知识库概览统计（适用于 dashboard 或健康检查）"""
        conn = self._get_conn()
        stats = {}
        for table in [
            "backtest_runs",
            "knowledge_entries",
            "market_context",
            "performance_results",
            "params_snapshot",
        ]:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                stats[table] = cnt
            except sqlite3.OperationalError:
                stats[table] = 0

        # 活跃知识条目
        try:
            active = conn.execute(
                "SELECT COUNT(*) FROM knowledge_entries WHERE status='active'"
            ).fetchone()[0]
            stats["active_knowledge_entries"] = active
        except sqlite3.OperationalError:
            stats["active_knowledge_entries"] = 0

        # 去重标的是
        try:
            symbols = conn.execute(
                "SELECT DISTINCT symbol FROM knowledge_entries WHERE status='active' ORDER BY symbol"
            ).fetchall()
            stats["symbols"] = [r["symbol"] for r in symbols]
        except sqlite3.OperationalError:
            stats["symbols"] = []

        # 去重策略
        try:
            strategies = conn.execute(
                "SELECT DISTINCT strategy FROM knowledge_entries WHERE status='active' ORDER BY strategy"
            ).fetchall()
            stats["strategies"] = [r["strategy"] for r in strategies]
        except sqlite3.OperationalError:
            stats["strategies"] = []

        return {
            "db_path": self.db_path,
            "tables_available": len(stats) - 1 if "tables" not in stats else stats.get("tables"),
            **stats,
        }

    # ── 按标的查询 ─────────────────────────────────

    def get_strategy_stats(self, symbol: str) -> List[dict]:
        """获取某标的所有策略知识条目（含绩效统计）

        参数
        ----------
        symbol : str
            证券代码，如 "601857" 或 "000001.SZ"

        返回
        -------
        list[dict]
            [{
                "symbol": str,
                "strategy": str,
                "strategy_label": str,    # 中文策略名
                "confidence": str,
                "sample_size": int,
                "avg_return_pct": float,
                "avg_sharpe": float,
                "avg_max_dd_pct": float,
                "insight_summary": str,
            }, ...]
        """
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT symbol, strategy, confidence, sample_size,
                   avg_return_pct, avg_sharpe, avg_max_dd_pct, insight_summary
            FROM knowledge_entries
            WHERE status='active' AND symbol = ?
            ORDER BY
              CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC,
              sample_size DESC
            """,
            (symbol,),
        ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            d["strategy_label"] = _STRATEGY_LABELS.get(d.get("strategy", ""), d["strategy"])
            results.append(d)
        return results

    def get_best_strategy(self, symbol: str) -> Optional[dict]:
        """获取某标的最优策略（按置信度+样本量加权）

        返回置信度最高、样本量最大的知识条目，或 None。
        """
        stats = self.get_strategy_stats(symbol)
        if not stats:
            return None

        def _score(s: dict) -> float:
            conf = _CONFIDENCE_RANK.get(s.get("confidence", "low"), 0)
            n = s.get("sample_size", 0)
            sharpe = abs(s.get("avg_sharpe", 0) or 0)
            return conf * 10 + n + sharpe

        return max(stats, key=_score)

    def get_strategy_comparison(self, symbol: str) -> dict:
        """返回某标的不同策略对比数据

        返回
        -------
        dict
            {
                "symbol": str,
                "strategies": [...] as from get_strategy_stats,
                "best": ... or None,
                "count": int,
            }
        """
        stats = self.get_strategy_stats(symbol)
        return {
            "symbol": symbol,
            "strategies": stats,
            "best": self.get_best_strategy(symbol),
            "count": len(stats),
        }

    # ── 市场环境查询 ───────────────────────────────

    def get_market_context_summary(self) -> dict:
        """返回市场环境分布汇总

        返回
        -------
        dict
            {
                "regime_distribution": {"sideways": N, "bear": N},
                "volatility_distribution": {"low": N, "medium": N, ...},
                "total_contexts": int,
                "typical_regime": str,       # 最常见市场状态
                "typical_volatility": str,   # 最常见波动等级
            }
        """
        conn = self._get_conn()
        result = {"regime_distribution": {}, "volatility_distribution": {}, "total_contexts": 0}

        try:
            rows = conn.execute(
                "SELECT market_regime, COUNT(*) as cnt FROM market_context GROUP BY market_regime ORDER BY cnt DESC"
            ).fetchall()
            for r in rows:
                result["regime_distribution"][r["market_regime"]] = r["cnt"]
                result["total_contexts"] += r["cnt"]

            # 典型状态
            if rows:
                result["typical_regime"] = rows[0]["market_regime"]
        except sqlite3.OperationalError:
            pass

        try:
            rows = conn.execute(
                "SELECT volatility_level, COUNT(*) as cnt FROM market_context WHERE volatility_level IS NOT NULL GROUP BY volatility_level ORDER BY cnt DESC"
            ).fetchall()
            for r in rows:
                result["volatility_distribution"][r["volatility_level"]] = r["cnt"]
            if rows:
                result["typical_volatility"] = rows[0]["volatility_level"]
        except sqlite3.OperationalError:
            pass

        return result

    def get_market_context_for_date(self, date_key: str) -> List[dict]:
        """获取特定日期的市场上下文记录"""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT mc.*, r.symbol, r.strategy, r.config_key
            FROM market_context mc
            LEFT JOIN backtest_runs r ON mc.run_id = r.run_id
            WHERE mc.date_key = ?
            ORDER BY mc.created_at DESC
            LIMIT 20
            """,
            (date_key,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 综合查询 ──────────────────────────────────

    def get_insights(self, symbols: Optional[List[str]] = None) -> List[dict]:
        """获取知识洞察，支持按标的筛选

        参数
        ----------
        symbols : list[str] | None
            标的列表，如 ["601857"]；None 则返回全部活跃条目

        返回
        -------
        list[dict]
        """
        conn = self._get_conn()
        if symbols:
            placeholders = ",".join("?" * len(symbols))
            sql = f"""
                SELECT ke.*, ke.insight_summary as insight_summary_raw
                FROM knowledge_entries ke
                WHERE ke.status='active' AND ke.symbol IN ({placeholders})
                ORDER BY
                  CASE ke.confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC,
                  ke.sample_size DESC
            """
            rows = conn.execute(sql, symbols).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ke.*, ke.insight_summary as insight_summary_raw
                FROM knowledge_entries ke
                WHERE ke.status='active'
                ORDER BY
                  CASE ke.confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC,
                  ke.sample_size DESC
            """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_knowledge_insights_for_report(self, symbols: List[str]) -> List[dict]:
        """为报告生成知识洞察（精简版，含人类可读摘要）

        参数
        ----------
        symbols : list[str]
            报告涉及的标的列表

        返回
        -------
        list[dict]
            [{
                "symbol": str,
                "strategy": str,
                "confidence": str,
                "sample_size": int,
                "avg_return_pct": float,
                "avg_sharpe": float,
                "insight_text": str,    # 可读性摘要
            }, ...]
        """
        entries = self.get_insights(symbols)
        results = []
        for e in entries:
            symbol = e.get("symbol", "?")
            strategy = e.get("strategy", "?")
            conf = e.get("confidence", "?")
            n = e.get("sample_size", 0)
            ret = e.get("avg_return_pct", 0)
            sharpe = e.get("avg_sharpe", 0)
            dd = e.get("avg_max_dd_pct", 0)

            # 生成可读摘要
            if n > 0 and (ret or sharpe):
                insight_text = (
                    f"{symbol} {_STRATEGY_LABELS.get(strategy, strategy)} "
                    f"在 {n} 次历史回测中，平均收益 {ret:.2f}%，"
                    f"夏普比率 {sharpe:.2f}，"
                    f"最大回撤 {dd:.2f}%"
                    f"（{conf}置信度）"
                )
            else:
                insight_text = (
                    f"{symbol} {_STRATEGY_LABELS.get(strategy, strategy)} "
                    f"样本量不足（n={n}），结论参考价值有限"
                )

            results.append({
                "symbol": symbol,
                "strategy": strategy,
                "confidence": conf,
                "sample_size": n,
                "avg_return_pct": round(ret, 4) if ret else 0,
                "avg_sharpe": round(sharpe, 2) if sharpe else 0,
                "avg_max_dd_pct": round(dd, 4) if dd else 0,
                "insight_text": insight_text,
            })

        return results

    def get_strategy_performance_summary(self, symbol: str) -> Optional[dict]:
        """生成策略绩效总结（用于报告"历史表现"部分）

        参数
        ----------
        symbol : str

        返回
        -------
        dict | None
            {
                "symbol": str,
                "best_strategy": str,
                "best_confidence": str,
                "best_sharpe": float,
                "best_return": float,
                "n_strategies": int,
                "total_trials": int,
                "summary": str,   # 一句话总结
            }
        """
        rows = self.get_knowledge_insights_for_report([symbol])
        if not rows:
            return None

        best = rows[0]  # 已按置信度排序
        total_trials = sum(r.get("sample_size", 0) for r in rows)

        summary = (
            f"{symbol} 历史最佳策略为 {_STRATEGY_LABELS.get(best['strategy'], best['strategy'])}，"
            f"夏普比率 {best['avg_sharpe']:.2f}，"
            f"置信度 {best['confidence']}"
        )

        return {
            "symbol": symbol,
            "best_strategy": best["strategy"],
            "best_strategy_label": _STRATEGY_LABELS.get(best["strategy"], best["strategy"]),
            "best_confidence": best["confidence"],
            "best_sharpe": best["avg_sharpe"],
            "best_return": best["avg_return_pct"],
            "n_strategies": len(rows),
            "total_trials": total_trials,
            "summary": summary,
        }


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def get_service(db_path: Optional[str] = None) -> KnowledgeService:
    """快捷工厂函数"""
    return KnowledgeService(db_path)


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    ks = KnowledgeService()
    summary = ks.summarize()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print()

    print("=== 601857 策略统计 ===")
    stats = ks.get_strategy_stats("601857")
    for s in stats:
        print(
            f"  策略 {s['strategy_label']:>8s} | 置信度: {s['confidence']:6s} "
            f"| 样本量: {s['sample_size']:2d} "
            f"| 平均收益: {s['avg_return_pct']:.2f}% "
            f"| 夏普: {s['avg_sharpe']:.2f}"
        )
    print()

    best = ks.get_best_strategy("601857")
    if best:
        print(f"最优策略: {best['strategy']}（{best['confidence']}）")
    print()

    print("=== 市场环境 ===")
    mc = ks.get_market_context_summary()
    print(json.dumps(mc, ensure_ascii=False, indent=2))
    print()

    print("=== 报告洞察 ===")
    insights = ks.get_knowledge_insights_for_report(["601857", "000001.SZ"])
    for i in insights:
        print(f"  [{i['confidence']}] {i['insight_text']}")

    print("\n知识库查询层初始化成功 ✅")
