"""
墨枢 - P3-17 / P3-18 反转参数扫描

对反转回测策略进行 RSI 参数网格扫描，找出最优组合。

功能:
  - scan_rsi_params() : RSI阈值(20,25,30) × 仓位(0.15,0.25) × 冷却期(2,5,10日)
  - 使用 run_reversal_backtest() 执行实际回测
  - 排序（夏普×0.5 + 收益率×0.3 + 胜率×0.2）
  - 输出 CSV 到 backtest_results/scans/
"""

from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backtest.strategies.run_reversal import (
    ReversalBacktestConfig,
    run_reversal_backtest,
    run_reversal_backtest_batch,
)
from backtest.backtest_engine import BacktestResult


# ═══════════════════════════════════════════════════════════════
# 输出目录
# ═══════════════════════════════════════════════════════════════

_SCAN_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..",
    "backtest_results", "scans",
)

# 扫描用固定参数
_SYMBOL = "601857"
_START_DATE = "20260105"
_END_DATE = "20260514"

# CSV 列定义
_CSV_HEADER = [
    "scan_type",
    "symbol",
    "signal_type",
    "signal_params",
    "position_mode",
    "position_params",
    "cooler_days",
    "tag",
    "annual_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
    "total_return_pct",
    "win_rate_pct",
    "total_trades",
    "profit_loss_ratio",
    "avg_holding_days",
    "avg_profit_pct",
    "avg_loss_pct",
    "composite_score",
]


def _metric(
    result: Optional[BacktestResult], key: str, default: Any = "N/A"
) -> Any:
    """安全提取指标。"""
    if result is None:
        return default
    val = result.metrics.get(key)
    return val if val is not None else default


def _extract_row(
    cfg: ReversalBacktestConfig,
    result: Optional[BacktestResult],
    scan_type: str,
    composite_score: float = 0.0,
) -> Dict[str, Any]:
    """将一次回测结果转换为 CSV 行。"""
    return {
        "scan_type": scan_type,
        "symbol": cfg.symbol,
        "signal_type": cfg.signal_type,
        "signal_params": str(cfg.signal_params),
        "position_mode": cfg.position_mode,
        "position_params": str(cfg.position_params),
        "cooler_days": cfg.cooler_days,
        "tag": cfg.tag,
        "annual_return_pct": _metric(result, "annual_return_pct"),
        "max_drawdown_pct": _metric(result, "max_drawdown_pct"),
        "sharpe_ratio": _metric(result, "sharpe_ratio"),
        "total_return_pct": _metric(result, "total_return_pct"),
        "win_rate_pct": _metric(result, "win_rate_pct"),
        "total_trades": _metric(result, "total_trades"),
        "profit_loss_ratio": _metric(result, "profit_loss_ratio"),
        "avg_holding_days": _metric(result, "avg_holding_days"),
        "avg_profit_pct": _metric(result, "avg_profit_pct"),
        "avg_loss_pct": _metric(result, "avg_loss_pct"),
        "composite_score": composite_score,
    }


def _write_csv(rows: List[Dict[str, Any]], filename: str) -> str:
    """将结果写入 CSV 文件。"""
    os.makedirs(_SCAN_OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(_SCAN_OUTPUT_DIR, filename)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[scan_reversal] CSV 已保存: {filepath}")
    return filepath


# ═══════════════════════════════════════════════════════════════
# 扫描函数
# ═══════════════════════════════════════════════════════════════


def _compute_composite_score(result: Optional[BacktestResult]) -> float:
    """
    计算综合评分 = 夏普×0.5 + 年化收益率×0.3 + 胜率×0.2

    所有指标需转成可加总的正分数格式。
    年化收益率可能是负值，使用 min-max 映射到 [0,1] 后加权。
    """
    if result is None:
        return 0.0

    sharpe = result.metrics.get("sharpe_ratio", 0.0) or 0.0
    annual_ret = result.metrics.get("annual_return_pct", 0.0) or 0.0
    win_rate = result.metrics.get("win_rate_pct", 0.0) or 0.0

    # 对夏普比率做 sigmoid 映射到 [0,1]
    sharpe_norm = 1.0 / (1.0 + (2.71828 ** (-sharpe * 2.0)))

    # 年化收益率归一化：clip 到 [-0.5, 0.5] 然后映射到 [0,1]
    annual_norm = max(0.0, min(1.0, (annual_ret + 0.5) / 1.0))

    # 胜率本身就是 [0,1]
    win_norm = max(0.0, min(1.0, win_rate / 100.0))

    score = sharpe_norm * 0.5 + annual_norm * 0.3 + win_norm * 0.2
    return round(score, 4)


def scan_rsi_params(
    rsi_thresholds: Tuple[int, ...] = (20, 25, 30),
    position_ratios: Tuple[float, ...] = (0.15, 0.25),
    cooler_days_list: Tuple[int, ...] = (2, 5, 10),
    max_workers: int = 4,
) -> str:
    """
    扫描 RSI 反转参数组合。

    网格：
      - RSI 超卖阈值：20, 25, 30
      - 仓位比例：0.15, 0.25
      - 冷却期：2, 5, 10 日

    参数
    ----------
    rsi_thresholds : tuple
        RSI 超卖阈值列表。
    position_ratios : tuple
        仓位比例列表。
    cooler_days_list : tuple
        冷却期天数列表。
    max_workers : int
        并发数。

    返回
    -------
    str
        CSV 文件路径。
    """
    print(f"[scan_rsi_params] 扫描反转参数:")
    print(f"  RSI阈值: {rsi_thresholds}")
    print(f"  仓位比例: {position_ratios}")
    print(f"  冷却期(日): {cooler_days_list}")
    print(f"  标的: {_SYMBOL}, 日期: {_START_DATE} ~ {_END_DATE}")

    configs: List[ReversalBacktestConfig] = []
    for oversold in rsi_thresholds:
        for ratio in position_ratios:
            for cool_days in cooler_days_list:
                tag = f"rsi{oversold}_pos{ratio:.0%}_cool{cool_days}"
                # 确保 tag 可作文件名
                tag = tag.replace("%", "pct")

                cfg = ReversalBacktestConfig(
                    symbol=_SYMBOL,
                    start_date=_START_DATE,
                    end_date=_END_DATE,
                    signal_type="rsi",
                    signal_params={
                        "period": 14,
                        "oversold": oversold,
                        "overbought": 100 - oversold,
                    },
                    position_mode="fixed",
                    position_params={"position_ratio": ratio},
                    cooler_days=cool_days,
                    tag=tag,
                )
                configs.append(cfg)

    total = len(configs)
    print(f"[scan_rsi_params] 共 {total} 个组合，启动回测...")

    # ── 执行批量回测 ──────────────────────────────────────
    results: List[BacktestResult] = [None] * total
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_reversal_backtest, cfg): i
            for i, cfg in enumerate(configs)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                res = future.result()
                results[idx] = res
                ann = res.metrics.get("annual_return_pct", "N/A")
                if isinstance(ann, float):
                    ann = f"{ann:.2%}"
                print(
                    f"  [{idx+1}/{total}] {configs[idx].tag} → "
                    f"Sharpe={res.metrics.get('sharpe_ratio', 'N/A'):.4f}, "
                    f"Return={ann}"
                )
            except Exception as e:
                print(f"  [{idx+1}/{total}] {configs[idx].tag} → 失败: {e}")
                results[idx] = None

    # ── 排序：综合评分 ────────────────────────────────────
    scored_rows: List[Dict[str, Any]] = []
    for cfg, res in zip(configs, results):
        score = _compute_composite_score(res)
        row = _extract_row(cfg, res, "rsi_params", composite_score=score)
        scored_rows.append(row)

    # 按综合评分降序排列
    scored_rows.sort(key=lambda r: float(r["composite_score"]), reverse=True)

    # 写入 CSV（固定文件名）
    filename = f"reversal_param_scan_{_END_DATE}.csv"
    csv_path = _write_csv(scored_rows, filename)

    # ── 打印 Top 5 ─────────────────────────────────────────
    print(f"\n[scan_rsi_params] 排序完成 (综合评分=夏普×0.5+收益率×0.3+胜率×0.2)")
    print(f"{'排名':<4} {'参数组合':<30} {'综合评分':<10} {'夏普':<10} {'年化收益':<12} {'胜率':<8}")
    print("-" * 80)
    for i, row in enumerate(scored_rows[:5], 1):
        sharpe = row["sharpe_ratio"]
        ann = row["annual_return_pct"]
        win = row["win_rate_pct"]
        print(
            f"{i:<4} {row['tag']:<30} "
            f"{row['composite_score']:<10} "
            f"{sharpe if isinstance(sharpe, str) else f'{sharpe:.4f}':<10} "
            f"{ann if isinstance(ann, str) else f'{ann:.2%}':<12} "
            f"{win if isinstance(win, str) else f'{win:.2f}':<8}"
        )

    return csv_path


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="反转回测参数扫描工具")
    parser.add_argument("--symbol", default=_SYMBOL, help="股票代码")
    parser.add_argument("--workers", type=int, default=4, help="并发数")
    args = parser.parse_args()

    print(f"反转参数扫描: symbol={args.symbol}, workers={args.workers}")
    csv_path = scan_rsi_params(max_workers=args.workers)
    print(f"\n扫描完成: {csv_path}")
