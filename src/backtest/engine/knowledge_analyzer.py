"""
knowledge_analyzer.py — 知识分析器：基于统计规则的参数稳定性分析 + 策略聚类 + 规律发现

Phase 3 核心产出：纯计算驱动，无 AI/LLM 依赖。

核心能力：
  1. 参数稳定性分析（同方法同参数键在不同值下的绩效方差）
  2. 策略相似度（基于参数分布重叠度）
  3. 策略聚类（参数分布 + 绩效相关性聚类）
  4. 市场状态分析（不同 regime 下各方法平均表现）
  5. Top-K 最佳组合
  6. 指标相关性矩阵
  7. 结构化总结报告（Markdown 模板）

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from typing import Any, Optional

import numpy as np
import pandas as pd


# ─── 延迟加载 wrapper ──────────────────────────────────────


def _load_entry_module():
    from src.backtest.engine.knowledge_entry import KnowledgeEntry
    return KnowledgeEntry


def _make_entry_from_dict(data: dict) -> Any:
    """从 dict 重建 KnowledgeEntry 实例。"""
    KE = _load_entry_module()
    return KE(
        task_id=data.get("task_id", ""),
        method_name=data.get("method_name", ""),
        symbol=data.get("symbol", ""),
        completed_time=data.get("completed_time", ""),
        regime=data.get("regime", ""),
        timeframe=data.get("timeframe", ""),
        tags=data.get("tags", []),
        source_run_id=data.get("source_run_id", ""),
        quality_score=data.get("quality_score", 0.0),
        total_return=data.get("total_return"),
        sharpe=data.get("sharpe"),
        max_drawdown=data.get("max_drawdown"),
        win_rate=data.get("win_rate"),
        insight_summary=data.get("insight_summary", ""),
        insight_category=data.get("insight_category", ""),
        confidence=data.get("confidence", 0.0),
        parameters=data.get("parameters", {}),
        statistics=data.get("statistics", {}),
        normalized_params=data.get("normalized_params", {}),
    )


# ─── 内部辅助函数 ──────────────────────────────────────────


def _safe_float(val: Any) -> Optional[float]:
    """安全地转换为 float，None / NaN 返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _stability_score(values: list[float]) -> float:
    """计算稳定性分数。

    公式：1 - (std / mean) 归一化到 [0, 1]。
    当 mean ≈ 0 或样本数不足时返回 0.0。

    Args:
        values: 指标值列表。

    Returns:
        float: [0, 1] 范围内的稳定性分数，越高越稳定。
    """
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return 0.0

    arr = np.array(valid, dtype=np.float64)
    mean = float(np.mean(arr))
    if abs(mean) < 1e-12:
        return 0.0

    std = float(np.std(arr, ddof=1))
    raw = 1.0 - (std / abs(mean))
    return max(0.0, min(1.0, raw))


def _pearson_corr(x: list[float], y: list[float]) -> float:
    """计算 Pearson 相关系数。

    Args:
        x: 第一个变量列表。
        y: 第二个变量列表。

    Returns:
        float: [-1, 1] 相关系数。样本不足或零方差时返回 0.0。
    """
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    try:
        arr_x = np.array(x, dtype=np.float64)
        arr_y = np.array(y, dtype=np.float64)
        if np.std(arr_x) == 0 or np.std(arr_y) == 0:
            return 0.0
        corr = np.corrcoef(arr_x, arr_y)[0, 1]
        if math.isnan(corr):
            return 0.0
        return float(corr)
    except Exception:
        return 0.0


def _spearman_corr(x: list[float], y: list[float]) -> float:
    """计算 Spearman 秩相关系数。

    Args:
        x: 第一个变量列表。
        y: 第二个变量列表。

    Returns:
        float: [-1, 1] 相关系数。样本不足时返回 0.0。
    """
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    try:
        from scipy.stats import spearmanr
        corr, _ = spearmanr(x, y)
        if math.isnan(corr):
            return 0.0
        return float(corr)
    except ImportError:
        # scipy 不可用时回退到 rank-based Pearson
        x_ranks = pd.Series(x).rank().tolist()
        y_ranks = pd.Series(y).rank().tolist()
        return _pearson_corr(x_ranks, y_ranks)


# ════════════════════════════════════════════════════════════
# KnowledgeAnalyzer
# ════════════════════════════════════════════════════════════


class KnowledgeAnalyzer:
    """知识分析器：基于统计规则的参数稳定性分析 + 策略聚类 + 规律发现。

    纯计算驱动，无 AI/LLM 依赖。
    所有分析基于 pandas/numpy 数值计算。

    Examples:
        >>> ka = KnowledgeAnalyzer(data_dir="data/knowledge_entries")
        >>> stability = ka.parameter_stability("ma_cross", "ma_fast")
        >>> top = ka.top_performers(metric="sharpe", top_k=5)
        >>> report = ka.generate_summary_report()
    """

    def __init__(self, data_dir: str = "data/knowledge_entries"):
        """初始化知识分析器。

        Args:
            data_dir: 知识条目 JSON 文件目录路径。
                      相对于当前工作目录，或绝对路径。
        """
        self._entries: list[Any] = []
        self._data_dir = data_dir
        self._load_entries()

    # ─── 数据加载 ────────────────────────────────────────────

    def _resolve_path(self) -> str:
        """解析 data_dir 为绝对路径。"""
        path = self._data_dir
        if not os.path.isabs(path):
            candidates = [
                os.path.join(os.getcwd(), path),
                os.path.join(os.path.dirname(__file__), "..", "..", "..", path),
                os.path.join(
                    os.path.dirname(__file__), "..", "..", "data", "knowledge_entries"
                ),
            ]
            for c in candidates:
                resolved = os.path.normpath(c)
                if os.path.isdir(resolved):
                    return resolved
            return os.path.normpath(candidates[0])
        return path

    def _load_entries(self) -> None:
        """从 data_dir 加载所有 JSON 文件为 KnowledgeEntry 实例。"""
        path = self._resolve_path()
        self._entries = []

        if not os.path.isdir(path):
            return

        for fname in os.listdir(path):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(path, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = _make_entry_from_dict(data)
                self._entries.append(entry)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    # ─── 数据预处理 ──────────────────────────────────────────

    def _to_dataframe(self) -> pd.DataFrame:
        """将所有条目转换为 DataFrame 以便分析。

        Returns:
            pd.DataFrame: 包含以下列的表格：
              method_name, symbol, regime, timeframe,
              total_return, sharpe, max_drawdown, win_rate,
              quality_score, confidence, parameters (dict),
              statistics (dict), normalized_params (dict),
              tags, insight_category.
        """
        records = []
        for e in self._entries:
            records.append({
                "method_name": e.method_name,
                "symbol": e.symbol,
                "regime": e.regime,
                "timeframe": e.timeframe,
                "total_return": _safe_float(e.total_return),
                "sharpe": _safe_float(e.sharpe),
                "max_drawdown": _safe_float(e.max_drawdown),
                "win_rate": _safe_float(e.win_rate),
                "quality_score": _safe_float(e.quality_score),
                "confidence": _safe_float(e.confidence),
                "parameters": e.parameters,
                "statistics": e.statistics,
                "normalized_params": e.normalized_params,
                "tags": e.tags,
                "insight_category": e.insight_category,
                "task_id": e.task_id,
            })
        return pd.DataFrame(records)

    def _get_entries_by_method(self, method_name: str) -> list[Any]:
        """按方法名过滤条目。"""
        return [e for e in self._entries if e.method_name == method_name]

    def _extract_param_values(
        self, entries: list[Any], param_key: str
    ) -> dict[Any, list[Any]]:
        """从条目列表中按 param_key 提取参数值并按值分组。

        Args:
            entries: 知识条目列表。
            param_key: 参数键名（如 "ma_fast", "period"）。

        Returns:
            dict: {param_value: [entry, ...]}，参数值→条目列表的映射。
        """
        groups: dict[Any, list[Any]] = defaultdict(list)
        for e in entries:
            val = e.parameters.get(param_key)
            if val is None:
                # 也在 normalized_params 中查找
                val = e.normalized_params.get(param_key)
            if val is not None:
                groups[val].append(e)
        return dict(groups)

    # ════════════════════════════════════════════════════════
    # 1. 参数稳定性分析
    # ════════════════════════════════════════════════════════

    def parameter_stability(
        self, method_name: str, param_key: str
    ) -> dict[str, Any]:
        """参数稳定性分析。

        给定一个方法名和参数键，分析该参数在不同值下的绩效方差。

        Args:
            method_name: 方法名（如 "ma_cross"）。
            param_key: 参数键名（如 "ma_fast" 或 normalized 后的 "period"）。

        Returns:
            dict: 稳定性分析结果。
            结构示例：
            {
                "method_name": "ma_cross",
                "param_key": "ma_fast",
                "values": [5, 10, 20, 30, 60],
                "metrics": {"total_return": [3.2, 4.1, 5.5, 4.8, 3.9]},
                "stability_score": 0.72,
                "best_value": 20,
                "recommendation": "ma_fast=20 在样本中表现最稳定"
            }

        Raises:
            ValueError: 方法名不存在或参数键在条目中未找到。
        """
        method_entries = self._get_entries_by_method(method_name)
        if not method_entries:
            raise ValueError(f"方法 '{method_name}' 不存在任何知识条目")

        # 检查参数键是否存在
        all_params_keys_in_use = set()
        for e in method_entries:
            all_params_keys_in_use.update(e.parameters.keys())
            all_params_keys_in_use.update(e.normalized_params.keys())
        if param_key not in all_params_keys_in_use:
            raise ValueError(
                f"参数键 '{param_key}' 在方法 '{method_name}' 的所有条目中未找到。"
                f"现有键: {sorted(all_params_keys_in_use)}"
            )

        groups = self._extract_param_values(method_entries, param_key)

        # 按参数值排序
        sorted_values = sorted(groups.keys(), key=lambda x: (x if isinstance(x, (int, float)) else 0))

        # 计算每个参数值组的主要指标均值
        metrics: dict[str, list[float]] = {
            "total_return": [],
            "sharpe": [],
            "win_rate": [],
        }

        for val in sorted_values:
            group_entries = groups[val]
            tr_mean = np.mean([
                _safe_float(e.total_return) or 0.0
                for e in group_entries
            ])
            sh_mean = np.mean([
                _safe_float(e.sharpe) or 0.0
                for e in group_entries
            ])
            wr_mean = np.mean([
                _safe_float(e.win_rate) or 0.0
                for e in group_entries
            ])
            metrics["total_return"].append(round(tr_mean, 4))
            metrics["sharpe"].append(round(sh_mean, 4))
            metrics["win_rate"].append(round(wr_mean, 4))

        # 基于 total_return 计算稳定性
        non_null_tr = [v for v in metrics["total_return"] if v is not None]
        stability = _stability_score(non_null_tr if non_null_tr else [0.0])

        # 最佳参数值（total_return 最高）
        best_idx = 0
        best_tr = float("-inf")
        for i, tr in enumerate(metrics["total_return"]):
            if tr is not None and tr > best_tr:
                best_tr = tr
                best_idx = i

        best_value = sorted_values[best_idx] if sorted_values else None

        # 生成建议文本
        if best_value is not None and stability > 0:
            recommendation = f"{param_key}={best_value} 在样本中表现最稳定（稳定性评分 {stability:.2f}）"
        else:
            recommendation = "样本不足，无法生成稳定性建议"

        return {
            "method_name": method_name,
            "param_key": param_key,
            "values": list(sorted_values),
            "metrics": metrics,
            "stability_score": round(stability, 4),
            "best_value": best_value,
            "recommendation": recommendation,
        }

    # ════════════════════════════════════════════════════════
    # 2. 策略相似度分析
    # ════════════════════════════════════════════════════════

    def strategy_similarity(self, method_a: str, method_b: str) -> dict[str, Any]:
        """策略相似度分析（基于参数分布重叠度）。

        使用 Jensen-Shannon 散度（或基于参数值的统计分布重叠）
        来衡量两个策略的参数分布相似度。

        Args:
            method_a: 方法 A 的名称。
            method_b: 方法 B 的名称。

        Returns:
            dict: 相似度分析结果。
            结构示例：
            {
                "method_a": "ma_cross",
                "method_b": "bollinger",
                "n_a": 10,
                "n_b": 8,
                "param_overlap": {"period": 0.85, "strategy_type": 1.0},
                "performance_correlation": 0.62,
                "overall_similarity": 0.73,
                "interpretation": "两种策略在参数分布上存在较高重叠度"
            }

        Raises:
            ValueError: 任一方法名不存在条目。
        """
        entries_a = self._get_entries_by_method(method_a)
        entries_b = self._get_entries_by_method(method_b)

        if not entries_a:
            raise ValueError(f"方法 '{method_a}' 不存在任何知识条目")
        if not entries_b:
            raise ValueError(f"方法 '{method_b}' 不存在任何知识条目")

        # 收集两个方法的参数分布
        def _param_distribution(entries: list[Any]) -> dict[str, set[Any]]:
            dist: dict[str, set[Any]] = defaultdict(set)
            for e in entries:
                for k, v in {**e.parameters, **e.normalized_params}.items():
                    if v is not None:
                        dist[k].add(v)
            return dict(dist)

        dist_a = _param_distribution(entries_a)
        dist_b = _param_distribution(entries_b)

        # 计算参数重叠度（Jaccard 系数）
        all_param_keys = set(dist_a.keys()) | set(dist_b.keys())
        param_overlap: dict[str, float] = {}

        for key in sorted(all_param_keys):
            set_a = dist_a.get(key, set())
            set_b = dist_b.get(key, set())
            if not set_a and not set_b:
                overlap = 1.0  # 两者都没有此参数 → 视为 1.0
            else:
                intersection = set_a & set_b
                union = set_a | set_b
                overlap = len(intersection) / max(len(union), 1)
            param_overlap[key] = round(overlap, 4)

        # 绩效相关性（使用可比较的指标：total_return）
        metric_values_a = [
            _safe_float(e.total_return) or 0.0 for e in entries_a
        ]
        metric_values_b = [
            _safe_float(e.total_return) or 0.0 for e in entries_b
        ]
        perf_corr = _pearson_corr(metric_values_a, metric_values_b)

        # 总体相似度 = 参数重叠度均值 × 0.6 + 绩效相关性 × 0.4
        avg_param_sim = (
            sum(param_overlap.values()) / max(len(param_overlap), 1)
        )
        overall = avg_param_sim * 0.6 + max(0, perf_corr) * 0.4

        # 解释文本
        if overall >= 0.7:
            interpretation = "两种策略在参数分布上存在较高重叠度"
        elif overall >= 0.4:
            interpretation = "两种策略在参数分布上有一定重叠"
        else:
            interpretation = "两种策略的参数分布差异较大"

        return {
            "method_a": method_a,
            "method_b": method_b,
            "n_a": len(entries_a),
            "n_b": len(entries_b),
            "param_overlap": param_overlap,
            "performance_correlation": round(perf_corr, 4),
            "overall_similarity": round(overall, 4),
            "interpretation": interpretation,
        }

    # ════════════════════════════════════════════════════════
    # 3. 策略聚类
    # ════════════════════════════════════════════════════════

    def cluster_strategies(
        self, min_similarity: float = 0.6
    ) -> list[dict[str, Any]]:
        """策略聚类：基于参数分布和绩效的相关性聚类。

        对每个方法对计算相似度，然后根据 min_similarity
        门限将策略分为若干簇。使用简单图连通分量算法。

        Args:
            min_similarity: 聚类门限（默认 0.6）。

        Returns:
            list[dict]: 聚类结果列表。
            每个元素代表一个簇，结构：
            {
                "cluster_id": 0,
                "methods": ["ma_cross", "macd"],
                "avg_similarity": 0.78,
                "n_members": 2,
            }
        """
        # 收集所有有条目支持的方法名
        method_names = sorted(set(e.method_name for e in self._entries))
        if len(method_names) < 2:
            return [
                {
                    "cluster_id": 0,
                    "methods": method_names,
                    "avg_similarity": 1.0,
                    "n_members": len(method_names),
                }
            ]

        # 构建相似度矩阵
        n = len(method_names)
        sim_matrix = np.zeros((n, n), dtype=np.float64)
        for i in range(n):
            for j in range(i + 1, n):
                try:
                    result = self.strategy_similarity(
                        method_names[i], method_names[j]
                    )
                    sim = result["overall_similarity"]
                except ValueError:
                    sim = 0.0
                sim_matrix[i, j] = sim
                sim_matrix[j, i] = sim
            sim_matrix[i, i] = 1.0  # 自身相似度为 1

        # 图连通分量聚类（超过门限的边构成图）
        visited = [False] * n
        clusters: list[list[int]] = []

        for i in range(n):
            if visited[i]:
                continue
            # BFS 找连通分量
            cluster_indices: list[int] = []
            queue = [i]
            visited[i] = True
            while queue:
                current = queue.pop(0)
                cluster_indices.append(current)
                for j in range(n):
                    if not visited[j] and sim_matrix[current, j] >= min_similarity:
                        visited[j] = True
                        queue.append(j)
            clusters.append(cluster_indices)

        # 转为输出格式
        result_clusters: list[dict[str, Any]] = []
        for cid, indices in enumerate(clusters):
            cluster_methods = [method_names[idx] for idx in sorted(indices)]
            # 计算簇内平均相似度
            if len(indices) > 1:
                similarities = []
                for i in range(len(indices)):
                    for j in range(i + 1, len(indices)):
                        similarities.append(
                            sim_matrix[indices[i], indices[j]]
                        )
                avg_sim = float(np.mean(similarities))
            else:
                avg_sim = 1.0

            result_clusters.append({
                "cluster_id": cid,
                "methods": cluster_methods,
                "avg_similarity": round(avg_sim, 4),
                "n_members": len(cluster_methods),
            })

        return result_clusters

    # ════════════════════════════════════════════════════════
    # 4. 市场状态分析
    # ════════════════════════════════════════════════════════

    def regime_analysis(self) -> dict[str, Any]:
        """市场状态分析：不同 regime 下各方法的平均表现。

        Returns:
            dict: 市场状态分析结果。
            结构示例：
            {
                "regimes": ["bull", "bear", "sideways", "volatile"],
                "methods": ["ma_cross", "grid"],
                "matrix": {
                    "ma_cross": {
                        "bull": {"count": 5, "avg_return": 12.5, "avg_sharpe": 1.8},
                        "bear": {"count": 2, "avg_return": -3.2, "avg_sharpe": 0.5},
                    },
                    ...
                },
                "best_combination": {
                    "method": "ma_cross",
                    "regime": "bull",
                    "avg_return": 12.5,
                },
            }
        """
        df = self._to_dataframe()
        if df.empty:
            return {"regimes": [], "methods": [], "matrix": {}, "best_combination": None}

        # 过滤掉 regime 为空或 unknown 的记录
        df_valid = df[df["regime"].isin(["bull", "bear", "sideways", "volatile"])]
        if df_valid.empty:
            return {"regimes": [], "methods": [], "matrix": {}, "best_combination": None}

        regimes = sorted(df_valid["regime"].unique())
        methods = sorted(df_valid["method_name"].unique())

        matrix: dict[str, dict[str, dict[str, Any]]] = {}

        for method in methods:
            matrix[method] = {}
            for regime in regimes:
                subset = df_valid[
                    (df_valid["method_name"] == method) &
                    (df_valid["regime"] == regime)
                ]
                count = len(subset)
                if count == 0:
                    continue
                avg_return = float(subset["total_return"].mean()) if subset["total_return"].notna().any() else None
                avg_sharpe = float(subset["sharpe"].mean()) if subset["sharpe"].notna().any() else None
                avg_win_rate = float(subset["win_rate"].mean()) if subset["win_rate"].notna().any() else None

                matrix[method][regime] = {
                    "count": count,
                }
                if avg_return is not None:
                    matrix[method][regime]["avg_return"] = round(avg_return, 4)
                if avg_sharpe is not None:
                    matrix[method][regime]["avg_sharpe"] = round(avg_sharpe, 4)
                if avg_win_rate is not None:
                    matrix[method][regime]["avg_win_rate"] = round(avg_win_rate, 4)

        # 最佳组合（avg_return 最高的 method+regime）
        best_combo: Optional[dict[str, Any]] = None
        best_avg_return = float("-inf")

        for method, regime_dict in matrix.items():
            for regime, stats in regime_dict.items():
                avg_ret = stats.get("avg_return")
                if avg_ret is not None and avg_ret > best_avg_return:
                    best_avg_return = avg_ret
                    best_combo = {
                        "method": method,
                        "regime": regime,
                        "avg_return": avg_ret,
                    }

        return {
            "regimes": regimes,
            "methods": methods,
            "matrix": matrix,
            "best_combination": best_combo,
        }

    # ════════════════════════════════════════════════════════
    # 5. Top-K 最佳组合
    # ════════════════════════════════════════════════════════

    def top_performers(
        self, metric: str = "sharpe", top_k: int = 5
    ) -> list[dict[str, Any]]:
        """表现最佳的组合（方法+参数+市场状态）。

        Args:
            metric: 排序指标（"total_return", "sharpe", "win_rate", "quality_score"）。
            top_k: 返回条目数（默认 5）。

        Returns:
            list[dict]: 表现最佳的条目列表。
            每个元素结构：
            {
                "rank": 1,
                "method_name": "ma_cross",
                "symbol": "601857",
                "regime": "bull",
                metric: 2.1,  # 动态键
                "parameters": {"ma_fast": 5, "ma_slow": 20},
                "confidence": 0.7,
                "task_id": "...",
            }

        Raises:
            ValueError: 指标名不支持。
        """
        supported_metrics = {"total_return", "sharpe", "win_rate", "quality_score"}
        if metric not in supported_metrics:
            raise ValueError(
                f"不支持的指标 '{metric}'。"
                f"支持的指标: {sorted(supported_metrics)}"
            )

        # 过滤指标值非空的条目
        valid = []
        for e in self._entries:
            val = _safe_float(getattr(e, metric, None))
            if val is not None:
                valid.append((val, e))

        # 降序排列
        valid.sort(key=lambda x: x[0], reverse=True)

        results = []
        for rank, (val, entry) in enumerate(valid[:top_k], start=1):
            results.append({
                "rank": rank,
                "method_name": entry.method_name,
                "symbol": entry.symbol,
                "regime": entry.regime,
                metric: round(val, 4),
                "parameters": dict(entry.parameters),
                "confidence": entry.confidence,
                "task_id": entry.task_id,
            })

        return results

    # ════════════════════════════════════════════════════════
    # 6. 指标相关性矩阵
    # ════════════════════════════════════════════════════════

    def correlation_matrix(
        self, method: str = "pearson"
    ) -> dict[str, Any]:
        """指标之间的相关性矩阵。

        Args:
            method: 相关性方法，"pearson" 或 "spearman"。

        Returns:
            dict: 相关性矩阵。
            结构示例：
            {
                "method": "pearson",
                "metrics": ["total_return", "sharpe", "max_drawdown", "win_rate"],
                "matrix": {
                    "total_return": {"total_return": 1.0, "sharpe": 0.85, ...},
                    "sharpe": {"total_return": 0.85, "sharpe": 1.0, ...},
                    ...
                },
            }

        Raises:
            ValueError: 不支持的 correlation method。
        """
        if method not in ("pearson", "spearman"):
            raise ValueError(f"不支持的相关性方法 '{method}'。仅支持 'pearson' 和 'spearman'。")

        corr_func = _pearson_corr if method == "pearson" else _spearman_corr

        metric_names = ["total_return", "sharpe", "max_drawdown", "win_rate"]

        # 提取平行数组
        series: dict[str, list[float]] = {m: [] for m in metric_names}
        for e in self._entries:
            for m in metric_names:
                val = _safe_float(getattr(e, m, None))
                if val is not None:
                    series[m].append(val)

        # 只保留所有指标都有的条目（完整的记录）
        # 实际上各指标值可能在不同条目上，我们分别计算每对指标的
        # 可用样本（包含两个指标值的条目）
        matrix: dict[str, dict[str, float]] = {
            m: {} for m in metric_names
        }

        for i, m1 in enumerate(metric_names):
            for j, m2 in enumerate(metric_names):
                if i == j:
                    matrix[m1][m2] = 1.0
                    continue

                # 收集同时有 m1 和 m2 的条目
                pairs_x: list[float] = []
                pairs_y: list[float] = []
                for e in self._entries:
                    v1 = _safe_float(getattr(e, m1, None))
                    v2 = _safe_float(getattr(e, m2, None))
                    if v1 is not None and v2 is not None:
                        pairs_x.append(v1)
                        pairs_y.append(v2)

                if len(pairs_x) < 3:
                    matrix[m1][m2] = 0.0
                else:
                    matrix[m1][m2] = round(corr_func(pairs_x, pairs_y), 4)

        return {
            "method": method,
            "metrics": metric_names,
            "matrix": matrix,
        }

    # ════════════════════════════════════════════════════════
    # 7. 结构化总结报告
    # ════════════════════════════════════════════════════════

    def generate_summary_report(self) -> str:
        """生成结构化总结报告（Markdown 模板，非 LLM）。

        所有内容通过纯计算和 f-string 模板生成，
        不依赖 AI/LLM 或生成式文本。

        Returns:
            str: Markdown 格式的总结报告文本。
        """
        n = len(self._entries)
        if n == 0:
            return "# 知识库分析报告\n\n**知识库为空**，无数据可供分析。\n"

        df = self._to_dataframe()

        # ── 1. 基本统计 ──
        method_counts = df["method_name"].value_counts().to_dict() if not df.empty else {}
        regime_counts = df["regime"].value_counts().to_dict() if not df.empty else {}
        symbols = sorted(df["symbol"].unique()) if not df.empty else []

        # ── 2. 方法级聚合 ──
        method_summary = ""
        for method in sorted(method_counts.keys()):
            sub = df[df["method_name"] == method]
            avg_tr = sub["total_return"].mean()
            avg_sh = sub["sharpe"].mean()
            avg_wr = sub["win_rate"].mean()
            method_summary += (
                f"- {method}: {method_counts[method]} 条"
            )
            if pd.notna(avg_tr):
                method_summary += f" | 平均收益 {avg_tr:.2f}%"
            if pd.notna(avg_sh):
                method_summary += f" | 平均夏普 {avg_sh:.2f}"
            if pd.notna(avg_wr):
                method_summary += f" | 平均胜率 {avg_wr:.1f}%"
            method_summary += "\n"

        # ── 3. 最佳表现者 ──
        top_sharpe = self.top_performers("sharpe", 3)
        top_return = self.top_performers("total_return", 3)

        top_sharpe_lines = ""
        for entry in top_sharpe:
            top_sharpe_lines += (
                f"  {entry['rank']}. {entry['method_name']} / {entry['symbol']}"
                f" — sharpe={entry.get('sharpe', 'N/A')}\n"
            )
        top_return_lines = ""
        for entry in top_return:
            top_return_lines += (
                f"  {entry['rank']}. {entry['method_name']} / {entry['symbol']}"
                f" — return={entry.get('total_return', 'N/A')}%\n"
            )

        # ── 4. 市场状态 ├─┬─
        regime_analysis_result = self.regime_analysis()
        regime_lines = ""
        if regime_analysis_result["matrix"]:
            for method in sorted(regime_analysis_result["matrix"].keys()):
                regime_lines += f"- {method}:\n"
                for reg in regime_analysis_result["regimes"]:
                    if reg in regime_analysis_result["matrix"][method]:
                        stats = regime_analysis_result["matrix"][method][reg]
                        parts = [f"  - {reg}: {stats['count']} 条"]
                        if "avg_return" in stats:
                            parts[-1] += f"，平均收益 {stats['avg_return']:.2f}%"
                        if "avg_sharpe" in stats:
                            parts[-1] += f"，平均夏普 {stats['avg_sharpe']:.2f}"
                        regime_lines += parts[-1] + "\n"
        else:
            regime_lines = "  (无有效市场状态标签数据)\n"

        # ── 5. 参数稳定性亮点 ──
        stability_lines = ""
        method_names_with_entries = sorted(method_counts.keys())
        for method in method_names_with_entries:
            # 找出该方法的常用参数键
            entries_m = self._get_entries_by_method(method)
            param_keys = set()
            for e in entries_m:
                param_keys.update(e.parameters.keys())
                param_keys.update(e.normalized_params.keys())
            # 排除策略类型等非数值键
            skip_keys = {"strategy_type", "_original_keys"}
            numeric_keys = [
                k for k in param_keys
                if k not in skip_keys and not k.startswith("_")
            ]
            for pk in sorted(numeric_keys)[:2]:  # 每方法最多展示 2 个参数
                try:
                    stab = self.parameter_stability(method, pk)
                    if stab["stability_score"] > 0:
                        stability_lines += (
                            f"- {method}.{pk}: 稳定性评分 {stab['stability_score']:.2f}"
                            f"，最佳值 {stab['best_value']}\n"
                        )
                except (ValueError, Exception):
                    pass

        if not stability_lines:
            stability_lines = "  (无充分样本进行参数稳定性分析)\n"

        # ── 6. 相关性 ├───
        corr_result = self.correlation_matrix()
        corr_lines = ""
        if corr_result["matrix"]:
            metric_names = corr_result["metrics"]
            # 表头
            header = "| 指标 | " + " | ".join(metric_names) + " |\n"
            sep = "| --- | " + " | ".join(["---"] * len(metric_names)) + " |\n"
            rows = ""
            for m1 in metric_names:
                row = f"| {m1} | "
                row += " | ".join(
                    f"{corr_result['matrix'][m1].get(m2, 0):.2f}"
                    for m2 in metric_names
                )
                row += " |\n"
                rows += row
            corr_lines = header + sep + rows
        else:
            corr_lines = "  (样本数量不足，无法计算相关性)\n"

        # ── 组装报告 ──
        report = f"""# 知识库分析报告

> 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')} +08:00
> 数据来源: {self._data_dir}
> 条目总数: {n}

---

## 一、基本统计

- **方法分布**: {len(method_counts)} 种方法
- **市场状态覆盖**: {len(regime_counts)} 种状态
- **标的覆盖**: {len(symbols)} 个标的

### 方法详情

{method_summary}
### 市场状态分布

""" + "\n".join(f"- {k}: {v} 条" for k, v in sorted(regime_counts.items())) + """

---

## 二、最佳表现者

### 按夏普比率 Top 3

""" + top_sharpe_lines + """
### 按总收益率 Top 3

""" + top_return_lines + """

---

## 三、市场状态分析

""" + regime_lines + """

---

## 四、参数稳定性

""" + stability_lines + """

---

## 五、指标相关性（Pearson）

""" + corr_lines + """

---

## 六、聚类概述

"""

        clusters = self.cluster_strategies(min_similarity=0.6)
        if clusters:
            for c in clusters:
                if c["n_members"] > 0:
                    report += (
                        f"- 簇 {c['cluster_id']}: " +
                        ", ".join(c["methods"]) +
                        f" (簇内相似度 {c['avg_similarity']:.2f}, {c['n_members']} 个成员)\n"
                    )
        else:
            report += "  (无有效聚类结果)\n"

        report += "\n---\n*报告由 KnowledgeAnalyzer.generate_summary_report() 自动生成，基于统计计算与规则模板。*\n"

        return report

    # ─── 属性 ──────────────────────────────────────────────

    @property
    def entries(self) -> list[Any]:
        """返回所有已加载的知识条目（只读视图）。"""
        return list(self._entries)

    @property
    def count(self) -> int:
        """知识条目总数。"""
        return len(self._entries)

    def reload(self) -> None:
        """重新加载知识条目 JSON 文件。"""
        self._load_entries()

    # ─── 内部: 已弃用的旧方法兼容 ──────────────────────────

    def get_statistics(self) -> dict[str, dict[str, int]]:
        """知识库统计（回退到 KnowledgeSearch 兼容格式）。

        Returns:
            按 method_name / symbol / regime / timeframe 分组的计数。
        """
        from collections import Counter

        result = {
            "method_name": Counter(),
            "symbol": Counter(),
            "regime": Counter(),
            "timeframe": Counter(),
        }

        for e in self._entries:
            for dim in ("method_name", "symbol", "regime", "timeframe"):
                val = getattr(e, dim, "")
                if val:
                    result[dim][val] += 1

        return {k: dict(v) for k, v in result.items()}
