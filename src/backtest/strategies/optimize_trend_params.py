"""
墨枢 - P2-20 参数优化建议

读取参数扫描 CSV，根据夏普比率 + 收益率加权评分，
选出最优参数组合并输出配置建议。
"""

from __future__ import annotations

import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple


# ── 路径 ──────────────────────────────────────────────────────

_SCAN_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "backtest_results", "scans",
)

_REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "backtest_results", "reports",
)


# ═══════════════════════════════════════════════════════════════
# 核心函数
# ═══════════════════════════════════════════════════════════════


def load_scan_csv(csv_path: str) -> List[Dict[str, Any]]:
    """
    加载参数扫描 CSV 文件。

    参数
    ----------
    csv_path : str
        CSV 文件路径。

    返回
    -------
    List[Dict[str, Any]]
        每行数据字典列表。
    """
    rows: List[Dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def score_row(row: Dict[str, Any]) -> float:
    """
    计算单行参数组合的加权评分。

    评分公式:
        score = 0.6 * sharpe_norm + 0.4 * return_norm

    其中 sharpe_norm 和 return_norm 是 Z-score 标准化后的值。

    参数
    ----------
    row : Dict[str, Any]
        CSV 数据行。

    返回
    -------
    float
        加权评分。数值越高越优。
    """
    def safe_float(val: Any) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    sharpe = safe_float(row.get("sharpe_ratio", 0))
    total_ret = safe_float(row.get("total_return_pct", 0))
    ann_ret = safe_float(row.get("annual_return_pct", 0))
    trades = int(safe_float(row.get("total_trades", 0)))
    win_rate = safe_float(row.get("win_rate_pct", 0))

    # 如果没有交易，直接给最低分
    if trades == 0:
        return -9999.0

    # 综合：夏普比率权重 0.5，年化收益率 0.3，胜率 0.2
    score = 0.5 * sharpe + 0.3 * ann_ret + 0.2 * win_rate
    return score


def optimize_ma_params(
    csv_path: Optional[str] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    """
    从 MA 参数扫描 CSV 中选出最优参数组合。

    参数
    ----------
    csv_path : str, optional
        CSV 文件路径。默认为 backtest_results/scans/trend_scan_ma_20260514.csv。

    返回
    -------
    List[Tuple[Dict[str, Any], float]]
        按评分降序排列的 (行数据, 评分) 列表。
    """
    if csv_path is None:
        csv_path = os.path.join(_SCAN_DIR, "trend_scan_ma_20260514.csv")

    if not os.path.exists(csv_path):
        print(f"[optimize] CSV 文件不存在: {csv_path}")
        return []

    rows = load_scan_csv(csv_path)
    if not rows:
        print("[optimize] CSV 文件为空")
        return []

    # 计算每行的评分
    scored: List[Tuple[Dict[str, Any], float]] = []
    for row in rows:
        s = score_row(row)
        scored.append((row, s))

    # 按评分降序排列
    scored.sort(key=lambda x: x[1], reverse=True)

    return scored


def print_optimization_report(
    scored: List[Tuple[Dict[str, Any], float]],
    top_n: int = 5,
) -> None:
    """
    打印优化建议报告。

    参数
    ----------
    scored : List[Tuple[Dict[str, Any], float]]
        评分排序后的参数列表。
    top_n : int
        显示前 N 个组合。
    """
    if not scored:
        print("\n⚠️  无可用数据生成优化建议。")
        return

    print("=" * 70)
    print("  墨枢 · 趋势策略参数优化建议")
    print("=" * 70)

    for i, (row, score) in enumerate(scored[:top_n]):
        tag = row.get("tag", "N/A")
        sharpe = row.get("sharpe_ratio", "N/A")
        ann_ret = row.get("annual_return_pct", "N/A")
        total_ret = row.get("total_return_pct", "N/A")
        win_rate = row.get("win_rate_pct", "N/A")
        trades = row.get("total_trades", "N/A")
        pl_ratio = row.get("profit_loss_ratio", "N/A")
        max_dd = row.get("max_drawdown_pct", "N/A")

        print(f"\n  #{i+1}  评分: {score:+.4f}  |  标签: {tag}")
        print(f"      {'─' * 50}")
        print(f"      夏普比率:       {sharpe:>8}")
        print(f"      年化收益率:     {ann_ret:>8} %")
        print(f"      总收益率:       {total_ret:>8} %")
        print(f"      最大回撤:       {max_dd:>8} %")
        print(f"      胜率:           {win_rate:>8} %")
        print(f"      交易次数:       {trades:>8}")
        print(f"      盈亏比:         {pl_ratio:>8}")

    # 输出最优配置建议
    best_row, best_score = scored[0]
    print(f"\n{'=' * 70}")
    print("  [BEST] 最优配置建议")
    print(f"{'=' * 70}")

    signal_params_str = best_row.get("signal_params", "{}")
    try:
        signal_params = json.loads(signal_params_str.replace("'", '"'))
    except (json.JSONDecodeError, AttributeError):
        signal_params = {}

    print(f"""
  标的代码:     {best_row.get('symbol', 'N/A')}
  信号类型:     {best_row.get('signal_type', 'N/A')}
  MA 快线:      {signal_params.get('ma_fast', 'N/A')}
  MA 慢线:      {signal_params.get('ma_slow', 'N/A')}
  仓位模式:     {best_row.get('position_mode', 'N/A')}
  仓位参数:     {best_row.get('position_params', 'N/A')}
  风控参数:     {best_row.get('risk_params', 'N/A')}
  评分:          {best_score:+.4f}
""")

    print(f"{'─' * 70}")
    print("  配置代码示例:")
    print(f"{'─' * 70}")
    print(f"""
  from backtest.strategies.run_trend import TrendBacktestConfig, run_trend_backtest

  cfg = TrendBacktestConfig(
      symbol=\"{best_row.get('symbol', '601857')}\",
      signal_type=\"{best_row.get('signal_type', 'ma')}\",
      signal_params={signal_params},
      position_mode=\"{best_row.get('position_mode', 'fixed')}\",
      position_params={best_row.get('position_params', '{}').replace("'", '"')},
      risk_params=None,
      tag=\"{best_row.get('tag', 'optimized')}\",
  )
  result = run_trend_backtest(cfg)
""")

    print("=" * 70)


def save_optimization_report(
    scored: List[Tuple[Dict[str, Any], float]],
    output_path: Optional[str] = None,
) -> str:
    """
    将优化建议保存为 JSON 文件。

    参数
    ----------
    scored : List[Tuple[Dict[str, Any], float]]
        评分排序后的参数列表。
    output_path : str, optional
        输出文件路径。

    返回
    -------
    str
        保存的文件路径。
    """
    if not scored:
        print("[optimize] 无数据可保存。")
        return ""

    os.makedirs(_REPORTS_DIR, exist_ok=True)

    if output_path is None:
        output_path = os.path.join(_REPORTS_DIR, "optimize_ma_params.json")

    payload = {
        "meta": {
            "description": "墨枢 MA 参数优化建议",
            "total_combinations": len(scored),
        },
        "rankings": [
            {
                "rank": i + 1,
                "score": round(score, 4),
                "tag": row.get("tag", "N/A"),
                "signal_params": row.get("signal_params", "N/A"),
                "sharpe_ratio": row.get("sharpe_ratio", "N/A"),
                "annual_return_pct": row.get("annual_return_pct", "N/A"),
                "total_return_pct": row.get("total_return_pct", "N/A"),
                "max_drawdown_pct": row.get("max_drawdown_pct", "N/A"),
                "win_rate_pct": row.get("win_rate_pct", "N/A"),
                "total_trades": row.get("total_trades", "N/A"),
                "profit_loss_ratio": row.get("profit_loss_ratio", "N/A"),
            }
            for i, (row, score) in enumerate(scored)
        ],
        "recommendation": {
            "best_tag": scored[0][0].get("tag", "N/A"),
            "best_score": round(scored[0][1], 4),
            "signal_params": scored[0][0].get("signal_params", "N/A"),
            "position_mode": scored[0][0].get("position_mode", "N/A"),
            "position_params": scored[0][0].get("position_params", "N/A"),
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[optimize] 优化报告已保存: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    """
    主入口：读取 CSV → 评分排序 → 打印建议 → 保存 JSON。
    """
    csv_path = os.path.join(_SCAN_DIR, "trend_scan_ma_20260514.csv")

    # 支持命令行参数指定 CSV 文件
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]

    print(f"[optimize] 读取 CSV: {csv_path}")
    scored = optimize_ma_params(csv_path)

    if not scored:
        print("[optimize] 未找到有效的参数组合。")
        return

    print_optimization_report(scored, top_n=5)
    save_optimization_report(scored)


if __name__ == "__main__":
    main()
