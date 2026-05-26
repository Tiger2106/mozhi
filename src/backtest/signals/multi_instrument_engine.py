"""
MultiInstrumentEngine — 多标的并行信号采集和分析引擎

职责：
  1. 对多个标的并行执行全流程分析
  2. 汇总各标的的突破、生命周期、条件收益矩阵、资本效率结果
  3. 输出横截面对比报告

用途::

    from signals.multi_instrument_engine import MultiInstrumentEngine

    engine = MultiInstrumentEngine()
    results = engine.run(["601857", "600519", "000300"])
    summary = engine.generate_summary(results)
    comparison = engine.compare_metrics(results)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import sys
import concurrent.futures
import time

from .breakout_profile import BreakoutEventDB, detect_breakout_points, BreakoutScoringCard
from .trend_lifecycle import TrendLifecycleDetector, TrendPhase


# ═══════════════════════════════════════════════════════════════
# 数据层 — 简化的价格数据获取
# ═══════════════════════════════════════════════════════════════


@dataclass
class Bar:
    """简化的 K 线数据结构"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    symbol: str = ""


def _load_bars_from_csv(
    filepath: str, symbol: str = "", date_format: str = "%Y-%m-%d"
) -> List[Bar]:
    """
    从 CSV 文件加载 K 线数据。

    CSV 必须包含列: date, open, high, low, close, volume（大小写不敏感）。
    """
    import csv
    bars: List[Bar] = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bar = Bar(
                date=str(row.get("date", row.get("Date", ""))),
                open=float(row.get("open", row.get("Open", 0))),
                high=float(row.get("high", row.get("High", 0))),
                low=float(row.get("low", row.get("Low", 0))),
                close=float(row.get("close", row.get("Close", 0))),
                volume=int(float(row.get("volume", row.get("Volume", 0)))),
                symbol=symbol or row.get("symbol", ""),
            )
            bars.append(bar)
    return bars


def _load_bars_from_market_cache(
    symbol: str, base_dir: Optional[str] = None, days: int = 360
) -> List[Bar]:
    """
    从本地 market_cache 目录加载 K 线数据。

    搜索策略:
      1. market_cache/{symbol}.csv
      2. market_cache/{symbol}_daily.csv
      3. 递归搜索 market_cache/ 下包含 symbol 的文件
    """
    if base_dir is None:
        ws = os.environ.get("OPENCLAW_WORKSPACE") or os.path.join(
            os.environ.get("USERPROFILE") or "/tmp",
            ".openclaw", "workspace-moheng"
        )
        base_dir = os.path.join(ws, "data", "market_cache")

    candidates = [
        os.path.join(base_dir, f"{symbol}.csv"),
        os.path.join(base_dir, f"{symbol}_daily.csv"),
        os.path.join(base_dir, f"{symbol}.CSV"),
    ]

    for path in candidates:
        if os.path.exists(path):
            bars = _load_bars_from_csv(path, symbol=symbol)
            if bars:
                return bars

    # 递归查找
    for root, dirs, files in os.walk(base_dir):
        for fn in files:
            if symbol in fn and fn.endswith((".csv", ".CSV")):
                full = os.path.join(root, fn)
                bars = _load_bars_from_csv(full, symbol=symbol)
                if bars:
                    return bars

    # 如果找不到文件，返回模拟数据（用于测试/演示）
    return _generate_mock_bars(symbol, days)


def _generate_mock_bars(symbol: str, days: int = 360) -> List[Bar]:
    """生成模拟 K 线数据（用于测试和演示）"""
    import random
    random.seed(hash(symbol) % (2**31))
    bars: List[Bar] = []
    price = 10.0 + random.random() * 90.0
    start = datetime(2025, 1, 1)

    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        # 跳过周末
        dt = datetime.strptime(d, "%Y-%m-%d")
        if dt.weekday() >= 5:
            continue

        change = (random.random() - 0.48) * 0.04  # 约48%概率上涨
        price *= (1 + change)
        vol = int(random.random() * 10_000_000 + 1_000_000)
        bar = Bar(
            date=d,
            open=round(price * (1 - random.random() * 0.005), 2),
            high=round(price * (1 + random.random() * 0.015), 2),
            low=round(price * (1 - random.random() * 0.015), 2),
            close=round(price, 2),
            volume=vol,
            symbol=symbol,
        )
        bars.append(bar)
    return bars


# ═══════════════════════════════════════════════════════════════
# 条件收益矩阵
# ═══════════════════════════════════════════════════════════════


def _build_conditional_return_matrix(
    bars: List[Bar], lookback: int = 20, forward: int = 5
) -> Dict[str, Any]:
    """
    构建条件收益矩阵。

    以 lookback 窗口内的价格行为模式分类，计算 forward 窗口内的平均收益。
    输出矩阵用于分析特定历史模式下的预期收益分布。
    """
    if len(bars) < lookback + forward:
        return {"status": "INSUFFICIENT_DATA", "bars_required": lookback + forward, "bars_available": len(bars)}

    closes = [b.close for b in bars]
    volumes = [max(b.volume, 1) for b in bars]

    results: List[Dict[str, Any]] = []

    for i in range(lookback, len(bars) - forward):
        window = closes[i - lookback:i]
        future = closes[i:i + forward]

        # 分类条件: 近期趋势方向
        ret = (window[-1] - window[0]) / max(window[0], 1)
        vol_trend = "up" if volumes[i] > sum(volumes[i - 5:i]) / 5 else "down"
        price_trend = "up" if ret > 0.02 else ("down" if ret < -0.02 else "flat")

        # forward 收益率
        fwd_ret = (future[-1] - window[-1]) / max(window[-1], 1)
        max_fwd = max(future) / max(window[-1], 1) - 1
        min_fwd = min(future) / max(window[-1], 1) - 1

        results.append({
            "date": bars[i].date,
            "price_trend": price_trend,
            "vol_trend": vol_trend,
            "ret_lookback": round(ret, 4),
            "ret_forward": round(fwd_ret, 4),
            "max_forward": round(max_fwd, 4),
            "min_forward": round(min_fwd, 4),
        })

    # 聚合矩阵
    matrix: Dict[str, Dict[str, List[float]]] = {}
    for r in results:
        key = f"{r['price_trend']}_{r['vol_trend']}"
        if key not in matrix:
            matrix[key] = {"returns": [], "max_returns": [], "min_returns": []}
        matrix[key]["returns"].append(r["ret_forward"])
        matrix[key]["max_returns"].append(r["max_forward"])
        matrix[key]["min_returns"].append(r["min_forward"])

    aggregated = {}
    for key, vals in matrix.items():
        rets = vals["returns"]
        aggregated[key] = {
            "count": len(rets),
            "avg_return": round(sum(rets) / len(rets), 4),
            "max_return": round(max(rets), 4),
            "min_return": round(min(rets), 4),
            "positive_rate": round(sum(1 for r in rets if r > 0) / len(rets), 4),
            "avg_max_fwd": round(sum(vals["max_returns"]) / len(vals["max_returns"]), 4),
            "avg_min_fwd": round(sum(vals["min_returns"]) / len(vals["min_returns"]), 4),
        }

    return {
        "status": "READY",
        "lookback": lookback,
        "forward": forward,
        "total_samples": len(results),
        "matrix": aggregated,
        "_raw_results": results,  # 保留原始收益列表供夏普比计算
    }


# ═══════════════════════════════════════════════════════════════
# 资本效率
# ═══════════════════════════════════════════════════════════════


def _compute_capital_efficiency(
    bars: List[Bar], matrix_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    计算标的的资本效率。

    资本效率 = Σ(正收益交易) / Σ(占用资本)
    近似估算: 条件收益矩阵中的 avg_return × positive_rate × 信号频率
    """
    if matrix_result.get("status") != "READY":
        return {"status": "INSUFFICIENT_DATA", "capital_efficiency": 0}

    matrix = matrix_result.get("matrix", {})
    if not matrix:
        return {"status": "NO_MATRIX", "capital_efficiency": 0}

    total_weighted_return = 0.0
    total_samples = 0
    for key, val in matrix.items():
        weight = val["count"]
        total_weighted_return += val["avg_return"] * val["positive_rate"] * weight
        total_samples += weight

    if total_samples == 0:
        return {"status": "NO_SAMPLES", "capital_efficiency": 0}

    avg_efficiency = total_weighted_return / total_samples
    signal_freq = len(bars) / max(total_samples, 1)

    # 夏普近似: 从原始结果重建收益列表
    # 通过条件收益矩阵构建中已存在的 results 数据集
    # 或者使用矩阵中的特征值推算
    returns = []
    if "_raw_results" in matrix_result:
        for r in matrix_result["_raw_results"]:
            returns.append(r["ret_forward"])

    sharpe_approx = 0.0
    if returns:
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns) if len(returns) > 1 else 1e-6
        sharpe_approx = mean_r / max(var_r ** 0.5, 1e-6) * (252 ** 0.5) if var_r > 0 else 0

    return {
        "status": "READY",
        "capital_efficiency": round(avg_efficiency * signal_freq, 6),
        "avg_return_per_trade": round(avg_efficiency, 6),
        "signal_frequency": round(1.0 / max(signal_freq, 1e-6), 2),
        "sharpe_approx": round(sharpe_approx, 4),
        "total_samples": total_samples,
        "total_bars": len(bars),
    }


# ═══════════════════════════════════════════════════════════════
# 主引擎
# ═══════════════════════════════════════════════════════════════


class MultiInstrumentEngine:
    """
    多标的并行信号采集和分析引擎。

    支持对多个证券标的批量执行：
      - 价格数据获取
      - 突破检测
      - 趋势生命周期检测
      - 条件收益矩阵构建
      - 资本效率计算
      - 汇总对比报告

    用法::

        engine = MultiInstrumentEngine()
        results = engine.run(["601857", "600519"])
        summary = engine.generate_summary(results)
    """

    def __init__(self, max_workers: int = 4, data_dir: Optional[str] = None):
        """
        Parameters
        ----------
        max_workers : int
            并行的最大工作线程数
        data_dir : str, optional
            市场数据目录路径，默认使用 data/market_cache
        """
        self.max_workers = max_workers
        self.data_dir = data_dir

    # ──────────────── 主入口 ────────────────

    def run(
        self,
        instruments: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        对多个标的并行执行全流程分析。

        对每个标的顺序执行:
          1. 价格数据获取
          2. 突破检测
          3. 趋势生命周期检测
          4. 条件收益矩阵构建
          5. 资本效率计算

        Parameters
        ----------
        instruments : list[str]
            标的代码列表，如 ["601857", "600519"]
        start_date : str, optional
            起始日期 (YYYY-MM-DD)
        end_date : str, optional
            结束日期 (YYYY-MM-DD)

        Returns
        -------
        dict[str, dict]
            {symbol: {...instrument_result...}} 键为标的代码，值为分析结果
        """
        if not instruments:
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}

        # 逐个获取数据（IO密集型可并行，但当前是文件读取）
        data: Dict[str, List[Bar]] = {}
        for symbol in instruments:
            bars = self._load_bars(symbol, start_date, end_date)
            if bars:
                data[symbol] = bars
            else:
                errors[symbol] = "无法加载价格数据"
                results[symbol] = {"status": "FAILED", "error": "无法加载价格数据"}

        # 并行执行分析（单标分析是CPU密集的边界）
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self.max_workers, len(data))
        ) as executor:
            future_map = {
                executor.submit(self._analyze_single, symbol, bars): symbol
                for symbol, bars in data.items()
            }
            for future in concurrent.futures.as_completed(future_map):
                symbol = future_map[future]
                try:
                    results[symbol] = future.result()
                except Exception as e:
                    results[symbol] = {"status": "FAILED", "error": str(e)}
                    errors[symbol] = str(e)

        return results

    # ──────────────── 单标分析 ────────────────

    def _analyze_single(
        self, symbol: str, bars: List[Bar]
    ) -> Dict[str, Any]:
        """
        对单个标的执行全链路分析（内部方法）。

        Parameters
        ----------
        symbol : str
        bars : list[Bar]

        Returns
        -------
        dict
        """
        result: Dict[str, Any] = {
            "symbol": symbol,
            "status": "READY",
            "bar_count": len(bars),
            "date_range": {
                "start": bars[0].date if bars else "",
                "end": bars[-1].date if bars else "",
            },
        }

        # 1. 突破检测
        try:
            from .breakout_profile import detect_breakout_points, BreakoutScoringCard
            breakout_events = detect_breakout_points(bars)
            result["breakout"] = {
                "event_count": len(breakout_events) if breakout_events else 0,
                "summary": {},
            }
        except Exception as e:
            result["breakout"] = {"status": "FAILED", "error": str(e)}

        # 2. 趋势生命周期
        try:
            tld = TrendLifecycleDetector()
            stage_bars = tld.label(bars)
            stage_dist = tld.get_stage_distribution()
            stage_pct = tld.get_stage_pct()

            result["lifecycle"] = {
                "total_bars_staged": len(stage_bars),
                "stage_distribution": stage_dist,
                "stage_pct": stage_pct,
                "current_stage": (
                    stage_bars[-1].stage.value if stage_bars else "UNKNOWN"
                ),
            }
        except Exception as e:
            result["lifecycle"] = {"status": "FAILED", "error": str(e)}

        # 3. 条件收益矩阵
        try:
            matrix = _build_conditional_return_matrix(bars)
            result["conditional_return_matrix"] = matrix
        except Exception as e:
            result["conditional_return_matrix"] = {
                "status": "FAILED",
                "error": str(e),
            }

        # 4. 资本效率
        try:
            capital_eff = _compute_capital_efficiency(
                bars, result.get("conditional_return_matrix", {})
            )
            result["capital_efficiency"] = capital_eff
        except Exception as e:
            result["capital_efficiency"] = {
                "status": "FAILED",
                "error": str(e),
            }

        return result

    # ──────────────── 数据加载 ────────────────

    def _load_bars(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Bar]:
        """
        加载某个标的的 K 线数据。

        Parameters
        ----------
        symbol : str
        start_date : str, optional
        end_date : str, optional

        Returns
        -------
        list[Bar]
        """
        bars = _load_bars_from_market_cache(symbol, self.data_dir)

        # 日期过滤
        if start_date:
            bars = [b for b in bars if b.date >= start_date]
        if end_date:
            bars = [b for b in bars if b.date <= end_date]

        # 确保按日期排序
        bars.sort(key=lambda b: b.date)

        return bars

    # ──────────────── 汇总方法 ────────────────

    def aggregate_results(self, results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        合并各标的的分析结果，生成综合统计。

        Parameters
        ----------
        results : dict
            run() 方法的输出

        Returns
        -------
        dict
        """
        total_instruments = len(results)
        successful = sum(
            1 for r in results.values() if r.get("status") == "READY"
        )
        failed = total_instruments - successful

        aggregated: Dict[str, Any] = {
            "total_instruments": total_instruments,
            "successful": successful,
            "failed": failed,
            "completion_rate": round(successful / max(total_instruments, 1), 4),
        }

        # 合并突破统计
        total_breakouts = 0
        total_false = 0
        for symbol, r in results.items():
            if r.get("status") == "READY" and "breakout" in r:
                b = r["breakout"]
                if "summary" in b:
                    total_breakouts += b["summary"].get("total_breakouts", 0)
                    total_false += b["summary"].get("false_breakouts", 0)

        aggregated["total_breakouts"] = total_breakouts
        aggregated["total_false_breakouts"] = total_false
        aggregated["false_breakout_rate"] = round(
            total_false / max(total_breakouts, 1), 4
        )

        return aggregated

    def generate_summary(self, results: Dict[str, Dict[str, Any]]) -> str:
        """
        生成可读的汇总对比报告（Markdown 格式）。

        Parameters
        ----------
        results : dict
            run() 方法的输出

        Returns
        -------
        str
            Markdown 格式的对比报告
        """
        lines = []
        lines.append("# 多标的并行分析报告")
        lines.append("")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**分析标的数**: {len(results)}")
        lines.append("")

        agg = self.aggregate_results(results)
        lines.append("## 总体统计")
        lines.append("")
        lines.append(f"- 成功: {agg['successful']} | 失败: {agg['failed']}")
        lines.append(f"- 完成率: {agg['completion_rate']:.1%}")
        lines.append(f"- 总突破事件: {agg['total_breakouts']}")
        lines.append(f"- 假突破率: {agg['false_breakout_rate']:.1%}")
        lines.append("")

        lines.append("## 各标的分项对比")
        lines.append("")
        lines.append("| 标的 | K线数 | 突破事件 | 假突破率 | 当前阶段 | 资本效率 | Sharpe |")
        lines.append("|:---|:----:|:--------:|:--------:|:--------:|:--------:|:------:|")

        for symbol in sorted(results.keys()):
            r = results[symbol]
            if r.get("status") != "READY":
                lines.append(
                    f"| {symbol} | — | ❌ {r.get('error', '失败')} | — | — | — | — |"
                )
                continue

            bar_cnt = r.get("bar_count", 0)
            b = r.get("breakout", {})
            breakout_cnt = b.get("event_count", 0) if isinstance(b, dict) else 0
            false_rate = (
                b.get("summary", {}).get("false_rate", 0)
                if isinstance(b, dict) and "summary" in b
                else 0
            )
            lc = r.get("lifecycle", {})
            cur_stage = (
                lc.get("current_stage", "N/A") if isinstance(lc, dict) else "N/A"
            )
            ce = r.get("capital_efficiency", {})
            cap_eff = (
                ce.get("capital_efficiency", "N/A") if isinstance(ce, dict) else "N/A"
            )
            sharpe = (
                ce.get("sharpe_approx", "N/A") if isinstance(ce, dict) else "N/A"
            )

            false_str = f"{false_rate:.1%}" if isinstance(false_rate, (int, float)) else "N/A"
            cap_str = f"{cap_eff:.6f}" if isinstance(cap_eff, (int, float)) else "N/A"
            sharpe_str = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else "N/A"

            lines.append(
                f"| {symbol} | {bar_cnt} | {breakout_cnt} | {false_str} | {cur_stage} | {cap_str} | {sharpe_str} |"
            )

        lines.append("")
        lines.append("## 条件收益矩阵对比")
        lines.append("")

        for symbol in sorted(results.keys()):
            r = results[symbol]
            if r.get("status") != "READY":
                continue
            matrix = r.get("conditional_return_matrix", {})
            if isinstance(matrix, dict) and matrix.get("status") == "READY":
                lines.append(f"### {symbol}")
                lines.append("")
                lines.append("| 条件模式 | 样本数 | 平均收益 | 胜率 |")
                lines.append("|:---------|:------:|:--------:|:----:|")
                for key, val in sorted(matrix.get("matrix", {}).items()):
                    lines.append(
                        f"| {key} | {val['count']} | {val['avg_return']:.4%} | {val['positive_rate']:.1%} |"
                    )
                lines.append("")

        return "\n".join(lines)

    def compare_metrics(
        self, results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        横截面对比各标的的绩效指标。

        对比维度:
          - 突破频率（事件数/日）
          - 假突破率
          - 当前趋势阶段
          - 条件收益矩阵中的最佳模式
          - 资本效率
          - 夏普比

        Parameters
        ----------
        results : dict
            run() 方法的输出

        Returns
        -------
        dict[str, dict]
            {metric_name: {symbol: value, ...}, ...}
        """
        comparison: Dict[str, Dict[str, Any]] = {
            "breakout_frequency": {},
            "false_breakout_rate": {},
            "current_stage": {},
            "capital_efficiency": {},
            "sharpe_approx": {},
            "best_condition_pattern": {},
            "total_breakouts": {},
            "stage_distribution_summary": {},
        }

        for symbol, r in results.items():
            if r.get("status") != "READY":
                continue

            bar_cnt = r.get("bar_count", 1)
            bars_per_year = max(bar_cnt, 1) / 360.0 * 252

            # 突破频率
            b = r.get("breakout", {})
            if isinstance(b, dict):
                b_events = b.get("event_count", 0) if "event_count" in b else (
                    b.get("summary", {}).get("total_breakouts", 0)
                    if "summary" in b else 0
                )
                comparison["total_breakouts"][symbol] = b_events
                comparison["breakout_frequency"][symbol] = round(
                    b_events / max(bars_per_year, 1), 2
                )
                false_cnt = (
                    b.get("summary", {}).get("false_breakouts", 0)
                    if "summary" in b else 0
                )
                comparison["false_breakout_rate"][symbol] = round(
                    false_cnt / max(b_events, 1), 4
                )

            # 当前阶段
            lc = r.get("lifecycle", {})
            if isinstance(lc, dict):
                comparison["current_stage"][symbol] = lc.get(
                    "current_stage", "UNKNOWN"
                )
                stage_pct = lc.get("stage_pct", {})
                if isinstance(stage_pct, dict):
                    # 取占比最高的阶段
                    top_stage = max(stage_pct, key=stage_pct.get) if stage_pct else "N/A"
                    comparison["stage_distribution_summary"][symbol] = {
                        "top_stage": top_stage,
                        "top_stage_pct": stage_pct.get(top_stage, 0),
                    }

            # 资本效率
            ce = r.get("capital_efficiency", {})
            if isinstance(ce, dict):
                comparison["capital_efficiency"][symbol] = ce.get(
                    "capital_efficiency", 0
                )
                comparison["sharpe_approx"][symbol] = ce.get("sharpe_approx", 0)

            # 最佳条件模式
            matrix = r.get("conditional_return_matrix", {})
            if isinstance(matrix, dict) and matrix.get("status") == "READY":
                m = matrix.get("matrix", {})
                if m:
                    best_key = max(m, key=lambda k: m[k]["avg_return"] * m[k]["positive_rate"])
                    comparison["best_condition_pattern"][symbol] = {
                        "pattern": best_key,
                        "avg_return": m[best_key]["avg_return"],
                        "positive_rate": m[best_key]["positive_rate"],
                    }

        return comparison

    def to_json(
        self,
        results: Dict[str, Dict[str, Any]],
        filepath: Optional[str] = None,
    ) -> Optional[str]:
        """
        将分析结果序列化为 JSON 文件或返回 JSON 字符串。

        Parameters
        ----------
        results : dict
            run() 方法的输出
        filepath : str, optional
            如果提供，将 JSON 写入文件

        Returns
        -------
        str or None
            如果 filepath 为 None，返回 JSON 字符串；否则写入文件并返回 None
        """
        # 确保可序列化（处理非 JSON 原生类型）
        clean = {}

        # 递归清理
        def _clean_val(v):
            if isinstance(v, (str, int, float, bool)):
                return v
            elif isinstance(v, dict):
                return {k: _clean_val(v2) for k, v2 in v.items()}
            elif isinstance(v, list):
                return [_clean_val(x) for x in v]
            elif isinstance(v, tuple):
                return [_clean_val(x) for x in v]
            elif v is None:
                return None
            else:
                return str(v)

        for symbol, r in results.items():
            clean[symbol] = _clean_val(r)

        # 添加元信息
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "engine_version": "1.0",
            "total_instruments": len(results),
            "results": clean,
        }

        if filepath:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return None
        else:
            return json.dumps(payload, ensure_ascii=False, indent=2)
