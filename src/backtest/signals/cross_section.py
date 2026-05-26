"""
CrossSectionReport — 多标横截面对比报告

职责：
  1. 接收 MultiInstrumentEngine.run() 的输出，生成标准化对比报告
  2. 按指定指标排名
  3. 计算标的相关性矩阵
  4. 输出总结对比表

用 法::

    from signals.multi_instrument_engine import MultiInstrumentEngine
    from signals.cross_section import CrossSectionReport

    engine = MultiInstrumentEngine()
    results = engine.run(["601857", "600519", "000300"])

    report = CrossSectionReport(results)
    table = report.summary_table()
    rank = report.rank_by("sharpe")
    corr = report.correlation_matrix()
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


class CrossSectionReport:
    """
    多标横截面对比报告。

    接受 MultiInstrumentEngine.run() 的输出（dict[str, dict]），
    提取各标的的绩效指标并生成标准化的对比表、排名和相关矩阵。

    Parameters
    ----------
    multi_engine_result : dict[str, dict]
        MultiInstrumentEngine.run() 的输出
    """

    # 指标名称映射：报告中的列名 → 引擎结果中的路径
    METRIC_MAP = {
        "symbol": ("symbol", str),
        "annualized_return": ("capital_efficiency.annualized_return", float),
        "max_drawdown": ("capital_efficiency.max_drawdown", float),
        "sharpe": ("capital_efficiency.sharpe_approx", float),
        "calmar": ("calmar", float),
        "total_breakouts": ("breakout.summary.total_breakouts", int),
        "false_breakout_rate": ("breakout.summary.false_rate", float),
        "capital_efficiency": ("capital_efficiency.capital_efficiency", float),
        "avg_hold_days": ("avg_hold_days", float),
    }

    def __init__(self, multi_engine_result: Dict[str, Dict[str, Any]]):
        self.raw = multi_engine_result  # {symbol: {...}}

    # ═══════════════════════════════════════════════════════════════
    # 核心接口
    # ═══════════════════════════════════════════════════════════════

    def summary_table(self) -> Dict[str, Dict[str, Any]]:
        """
        生成标准化的横截面对比表。

        Returns
        -------
        dict[str, dict]
            {symbol: {metric: value, ...}}
        """
        table: Dict[str, Dict[str, Any]] = {}
        for symbol, result in self.raw.items():
            if not isinstance(result, dict):
                continue
            if result.get("status") != "READY":
                continue

            row = self._extract_metrics(symbol, result)
            table[symbol] = row
        return table

    def rank_by(self, metric: str = "sharpe") -> List[Dict[str, Any]]:
        """
        按指定指标从高到低排名。

        Parameters
        ----------
        metric : str
            排名指标，如 "sharpe", "annualized_return", "capital_efficiency"

        Returns
        -------
        list[dict]
            [{symbol: ..., metric: value, rank: int}, ...]
        """
        table = self.summary_table()
        ranked: List[Dict[str, Any]] = []

        for symbol, row in table.items():
            value = row.get(metric)
            if value is None:
                continue
            if isinstance(value, str):
                continue  # 跳过字符串指标
            ranked.append({
                "symbol": symbol,
                metric: value,
                "rank": 0,
            })

        ranked.sort(key=lambda x: x.get(metric, 0), reverse=True)
        for i, entry in enumerate(ranked):
            entry["rank"] = i + 1

        return ranked

    def correlation_matrix(self) -> Dict[str, Dict[str, float]]:
        """
        计算标的之间的绩效相关性矩阵。

        使用各标的的条件收益矩阵中的 avg_return 序列计算相关系数。
        若条件收益矩阵不可用或数据不足，返回空字典。

        Returns
        -------
        dict[str, dict[str, float]]
            {sym_A: {sym_B: pearson_corr}}
        """
        symbols = [
            s for s, r in self.raw.items()
            if isinstance(r, dict) and r.get("status") == "READY"
        ]
        if len(symbols) < 2:
            return {}

        # 提取各标的的收益序列
        series_map: Dict[str, List[float]] = {}
        for s in symbols:
            returns = self._extract_return_series(s)
            if returns and len(returns) >= 5:
                series_map[s] = returns

        if len(series_map) < 2:
            return {}

        matrix: Dict[str, Dict[str, float]] = {s: {} for s in series_map}

        sym_list = list(series_map.keys())
        for i in range(len(sym_list)):
            s_a = sym_list[i]
            series_a = series_map[s_a]
            for j in range(i, len(sym_list)):
                s_b = sym_list[j]
                if i == j:
                    matrix[s_a][s_b] = 1.0
                    continue
                series_b = series_map[s_b]

                # 对齐长度至较短序列
                n = min(len(series_a), len(series_b))
                a_trunc = series_a[:n]
                b_trunc = series_b[:n]

                corr = self._pearson_correlation(a_trunc, b_trunc)
                matrix[s_a][s_b] = corr
                matrix[s_b][s_a] = corr

        return matrix

    def cross_reference(self) -> List[Dict[str, Any]]:
        """
        生成交叉引用综述：每个标的的最佳方面与最弱方面。

        Returns
        -------
        list[dict]
            [{symbol, best_metric, best_value, worst_metric, worst_value}]
        """
        table = self.summary_table()
        cross: List[Dict[str, Any]] = []

        # 只对数值指标进行比较
        numeric_metrics = [
            "sharpe", "annualized_return", "max_drawdown",
            "calmar", "capital_efficiency", "total_breakouts",
        ]

        for symbol, row in table.items():
            best_metric = ""
            best_value = -float("inf")
            worst_metric = ""
            worst_value = float("inf")

            for m in numeric_metrics:
                v = row.get(m)
                if v is None:
                    continue
                # 回撤 abs 越小越好
                if m == "max_drawdown":
                    if abs(v) < abs(worst_value) if worst_value != float("inf") else True:
                        best_metric = m
                        best_value = v
                    if abs(v) > abs(worst_value) if worst_value != float("inf") else True:
                        worst_metric = m
                        worst_value = v
                else:
                    if v > best_value:
                        best_metric = m
                        best_value = v
                    if v < worst_value:
                        worst_metric = m
                        worst_value = v

            cross.append({
                "symbol": symbol,
                "best_metric": best_metric,
                "best_value": best_value if best_value != -float("inf") else None,
                "worst_metric": worst_metric,
                "worst_value": worst_value if worst_value != float("inf") else None,
            })

        return cross

    # ═══════════════════════════════════════════════════════════════
    # 指标提取（内部方法）
    # ═══════════════════════════════════════════════════════════════

    def _extract_metrics(
        self, symbol: str, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """从单个标的的引擎结果提取指标。"""
        row: Dict[str, Any] = {
            "symbol": symbol,
        }

        # --- 资本效率相关 ---
        ce = result.get("capital_efficiency", {})
        if isinstance(ce, dict):
            # 年化收益率
            avg_ret = ce.get("avg_return_per_trade", 0)
            signal_freq = ce.get("signal_frequency", 0)
            total_bars = result.get("bar_count", 0)
            # 年化 ≈ avg_return_per_trade × 交易频率（年化）
            annualization_factor = 252.0 / max(signal_freq, 1) if signal_freq > 0 else 0
            if isinstance(avg_ret, (int, float)):
                row["annualized_return"] = round(avg_ret * annualization_factor, 4)
            else:
                row["annualized_return"] = 0.0

            # 最大回撤（从条件收益矩阵估算）
            matrix_result = result.get("conditional_return_matrix", {})
            max_dd = self._estimate_drawdown(matrix_result)
            row["max_drawdown"] = max_dd

            # Sharpe
            sharpe = ce.get("sharpe_approx", 0)
            row["sharpe"] = round(sharpe, 4) if isinstance(sharpe, (int, float)) else 0.0

            # 资金利用率
            cap_eff = ce.get("capital_efficiency", 0)
            row["capital_efficiency"] = round(cap_eff, 6) if isinstance(cap_eff, (int, float)) else 0.0

        # --- 突破相关 ---
        bo = result.get("breakout", {})
        if isinstance(bo, dict):
            summary = bo.get("summary", {})
            if isinstance(summary, dict):
                row["total_breakouts"] = summary.get("total_breakouts", 0)
                row["false_breakout_rate"] = round(summary.get("false_rate", 0), 4)
            else:
                row["total_breakouts"] = bo.get("event_count", 0)
                row["false_breakout_rate"] = 0.0
        else:
            row["total_breakouts"] = 0
            row["false_breakout_rate"] = 0.0

        # --- 持仓天数估算 ---
        bar_count = result.get("bar_count", 0)
        bo_count = row.get("total_breakouts", 0)
        # 平均持仓天数 ≈ bar_count / max(突破数, 1)
        row["avg_hold_days"] = round(bar_count / max(bo_count, 1), 2) if bo_count > 0 else 0.0

        # --- Calmar 比率（年化 / 回撤） ---
        ann_ret = row.get("annualized_return", 0.0)
        max_dd = row.get("max_drawdown", 0.0)
        row["calmar"] = round(ann_ret / max(abs(max_dd), 1e-6), 4) if max_dd != 0 else 0.0

        # --- 生命周期 ---
        lc = result.get("lifecycle", {})
        if isinstance(lc, dict):
            row["current_stage"] = lc.get("current_stage", "N/A")
        else:
            row["current_stage"] = "N/A"

        return row

    def _estimate_drawdown(self, matrix_result: Any) -> float:
        """
        从条件收益矩阵中估算最大回撤。

        使用矩阵中各模式的 min_return（绝对亏损最大的值）作为回撤估计。
        """
        if not isinstance(matrix_result, dict):
            return 0.0
        if matrix_result.get("status") != "READY":
            return 0.0

        matrix = matrix_result.get("matrix", {})
        if not matrix:
            return 0.0

        min_returns = []
        for val in matrix.values():
            if isinstance(val, dict):
                mn = val.get("min_return")
                if mn is not None and isinstance(mn, (int, float)):
                    min_returns.append(mn)

        if not min_returns:
            return 0.0

        # 取绝对值最大的负收益作为回撤
        worst = min(min_returns)  # 最负的
        return round(abs(worst), 4) if worst < 0 else 0.01  # 至少给一个基准值

    def _extract_return_series(self, symbol: str) -> List[float]:
        """
        从条件收益矩阵的原始结果中提取收益序列用于相关性计算。

        Parameters
        ----------
        symbol : str

        Returns
        -------
        list[float]
            收益序列（forward 收益）
        """
        result = self.raw.get(symbol)
        if not isinstance(result, dict):
            return []

        matrix_result = result.get("conditional_return_matrix", {})
        if not isinstance(matrix_result, dict):
            return []

        # 尝试从 _raw_results 提取完整收益序列
        raw_results = matrix_result.get("_raw_results")
        if isinstance(raw_results, list) and len(raw_results) > 0:
            returns = []
            for r in raw_results:
                if isinstance(r, dict):
                    fwd = r.get("ret_forward")
                    if isinstance(fwd, (int, float)):
                        returns.append(fwd)
            if len(returns) >= 5:
                return returns

        # 如果不包含原始数据，从聚合矩阵中重构收益序列
        matrix = matrix_result.get("matrix", {})
        if not matrix:
            return []

        # 从聚合模式中构造一个模拟序列
        reconstructed: List[float] = []
        for key, val in matrix.items():
            if not isinstance(val, dict):
                continue
            count = val.get("count", 0)
            avg_ret = val.get("avg_return", 0)
            if count > 0 and isinstance(avg_ret, (int, float)):
                # 用 avg_return 填充 count 次（简化处理）
                reconstructed.extend([avg_ret] * min(count, 50))

        return reconstructed[:200]  # 最多 200 个点

    # ═══════════════════════════════════════════════════════════════
    # 统计辅助方法
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _pearson_correlation(x: List[float], y: List[float]) -> float:
        """计算 Pearson 相关系数。"""
        n = len(x)
        if n < 3:
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = 0.0
        var_x = 0.0
        var_y = 0.0

        for xi, yi in zip(x, y):
            dx = xi - mean_x
            dy = yi - mean_y
            cov += dx * dy
            var_x += dx * dx
            var_y += dy * dy

        denom = math.sqrt(var_x * var_y)
        if denom < 1e-10:
            return 0.0

        return round(cov / denom, 4)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        """将值限制在 [low, high] 范围内。"""
        return max(low, min(high, value))
