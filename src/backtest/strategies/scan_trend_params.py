"""
墨枢 - P2-16 参数扫描工具

对趋势回测策略进行参数网格扫描，找出最优组合。

功能:
  - scan_ma_params()      : MA周期组合 (5,10)×(20,60)
  - scan_position_params() : 仓位比例 0.2 / 0.5
  - scan_risk_params()    : 止损 5% / 10%
  - scan_all()            : 全组合扫描
  - 输出 CSV 汇总文件
"""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backtest.strategies.run_trend import (
    TrendBacktestConfig,
    run_trend_backtest,
    run_trend_backtest_batch,
)
from backtest.backtest_engine import BacktestResult


# ═══════════════════════════════════════════════════════════════
# 输出目录
# ═══════════════════════════════════════════════════════════════

_SCAN_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "backtest_results", "scans"
)

# CSV 列定义
_CSV_HEADER = [
    "scan_type",
    "symbol",
    "signal_type",
    "signal_params",
    "position_mode",
    "position_params",
    "risk_params",
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
]


def _metric(
    result: Optional[BacktestResult], key: str, default: Any = "N/A"
) -> Any:
    """安全提取指标。"""
    if result is None:
        return default
    val = result.metrics.get(key)
    return val if val is not None else default


def _extract_risk_summary(risk_params: Optional[Dict]) -> str:
    """将风险参数字典转成简短摘要字符串。"""
    if risk_params is None:
        return "none"
    parts = []
    for k, v in risk_params.items():
        if isinstance(v, float):
            parts.append(f"{k}={v:.2%}")
        else:
            parts.append(f"{k}={v}")
    return "|".join(parts)


def _extract_row(
    cfg: TrendBacktestConfig,
    result: Optional[BacktestResult],
    scan_type: str,
) -> Dict[str, Any]:
    """将一次回测结果转换为 CSV 行。"""
    return {
        "scan_type": scan_type,
        "symbol": cfg.symbol,
        "signal_type": cfg.signal_type,
        "signal_params": str(cfg.signal_params),
        "position_mode": cfg.position_mode,
        "position_params": str(cfg.position_params),
        "risk_params": _extract_risk_summary(cfg.risk_params),
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
    }


def _write_csv(rows: List[Dict[str, Any]], filename: str) -> str:
    """将结果写入 CSV 文件。"""
    os.makedirs(_SCAN_OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(_SCAN_OUTPUT_DIR, filename)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[scan] CSV 已保存: {filepath}")
    return filepath


def _build_base_config(symbol: str = "601857") -> TrendBacktestConfig:
    """构建基准配置（MA金叉+固定仓位30%，无风控）。"""
    return TrendBacktestConfig(
        symbol=symbol,
        signal_type="ma",
        signal_params={"ma_fast": 5, "ma_slow": 20},
        position_mode="fixed",
        position_params={"position_ratio": 0.3},
        risk_params=None,
        tag="scan_ma",
    )


# ═══════════════════════════════════════════════════════════════
# 扫描函数
# ═══════════════════════════════════════════════════════════════


def scan_ma_params(
    symbol: str = "601857",
    fast_periods: Tuple[int, ...] = (5, 10),
    slow_periods: Tuple[int, ...] = (20, 60),
    max_workers: int = 4,
) -> str:
    """
    扫描 MA 周期参数组合。

    参数
    ----------
    symbol : str
        股票代码。
    fast_periods : tuple
        快线周期列表。
    slow_periods : tuple
        慢线周期列表。
    max_workers : int
        并发数。

    返回
    -------
    str
        CSV 文件路径。
    """
    print(f"[scan_ma] 扫描 MA 参数组合: fast={fast_periods}, slow={slow_periods}")

    configs: List[TrendBacktestConfig] = []
    for fast in fast_periods:
        for slow in slow_periods:
            if fast >= slow:
                print(f"  [skip] fast={fast} >= slow={slow}, 跳过")
                continue
            cfg = _build_base_config(symbol)
            cfg.signal_params = {"ma_fast": fast, "ma_slow": slow}
            cfg.tag = f"ma_f{fast}_s{slow}"
            configs.append(cfg)

    results = run_trend_backtest_batch(configs, max_workers=max_workers)
    rows = [_extract_row(cfg, res, "ma_params") for cfg, res in zip(configs, results)]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scan_ma_params_{symbol}_{ts}.csv"
    return _write_csv(rows, filename)


def scan_position_params(
    symbol: str = "601857",
    ratios: Tuple[float, ...] = (0.2, 0.5),
    max_workers: int = 4,
) -> str:
    """
    扫描仓位比例参数。

    参数
    ----------
    symbol : str
        股票代码。
    ratios : tuple
        仓位比例列表。
    max_workers : int
        并发数。

    返回
    -------
    str
        CSV 文件路径。
    """
    print(f"[scan_position] 扫描仓位比例: ratios={ratios}")

    configs: List[TrendBacktestConfig] = []
    for ratio in ratios:
        cfg = _build_base_config(symbol)
        cfg.position_params = {"position_ratio": ratio}
        cfg.tag = f"pos_{ratio:.0%}".replace("%", "pct")
        configs.append(cfg)

    results = run_trend_backtest_batch(configs, max_workers=max_workers)
    rows = [_extract_row(cfg, res, "position_params") for cfg, res in zip(configs, results)]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scan_position_params_{symbol}_{ts}.csv"
    return _write_csv(rows, filename)


def scan_risk_params(
    symbol: str = "601857",
    stop_losses: Tuple[float, ...] = (0.05, 0.10),
    max_workers: int = 4,
) -> str:
    """
    扫描止损参数。

    参数
    ----------
    symbol : str
        股票代码。
    stop_losses : tuple
        止损比例列表（如 0.05 表示 5%）。
    max_workers : int
        并发数。

    返回
    -------
    str
        CSV 文件路径。
    """
    print(f"[scan_risk] 扫描止损参数: stop_losses={stop_losses}")

    configs: List[TrendBacktestConfig] = []
    # 对比有风和无反的差异
    for stop_loss in stop_losses:
        cfg = _build_base_config(symbol)
        cfg.risk_params = {"fixed_stop_loss": stop_loss}
        cfg.tag = f"stop_{stop_loss:.0%}".replace("%", "pct")
        configs.append(cfg)
    # 添加一个无风控的基线
    cfg_no_risk = _build_base_config(symbol)
    cfg_no_risk.risk_params = None
    cfg_no_risk.tag = "no_stop"
    configs.append(cfg_no_risk)

    results = run_trend_backtest_batch(configs, max_workers=max_workers)
    rows = [_extract_row(cfg, res, "risk_params") for cfg, res in zip(configs, results)]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scan_risk_params_{symbol}_{ts}.csv"
    return _write_csv(rows, filename)


# ═══════════════════════════════════════════════════════════════
# 全参数扫描
# ═══════════════════════════════════════════════════════════════


def scan_all(
    symbol: str = "601857",
    max_workers: int = 4,
) -> Dict[str, str]:
    """
    执行全部参数扫描。

    返回
    -------
    Dict[str, str]
        扫描类别到 CSV 文件路径的映射。
    """
    print(f"{'='*60}")
    print("[scan_all] 开始全参数扫描")
    print(f"{'='*60}")

    # P2-16a: MA 周期扫描
    ma_csv = scan_ma_params(symbol=symbol, max_workers=max_workers)

    # P2-16b: 仓位比例扫描
    pos_csv = scan_position_params(symbol=symbol, max_workers=max_workers)

    # P2-16c: 止损扫描
    risk_csv = scan_risk_params(symbol=symbol, max_workers=max_workers)

    summary = {
        "ma_params": ma_csv,
        "position_params": pos_csv,
        "risk_params": risk_csv,
    }

    print(f"\n{'='*60}")
    print("[scan_all] 全参数扫描完成")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"{'='*60}")

    return summary


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="趋势回测参数扫描工具")
    parser.add_argument(
        "scan_type",
        nargs="?",
        default="all",
        choices=["all", "ma", "position", "risk"],
        help="扫描类型 (默认: all)",
    )
    parser.add_argument("--symbol", default="601857", help="股票代码")
    parser.add_argument("--workers", type=int, default=4, help="并发数")
    args = parser.parse_args()

    print(f"参数扫描: type={args.scan_type}, symbol={args.symbol}, workers={args.workers}")

    scanners = {
        "ma": lambda: scan_ma_params(args.symbol, max_workers=args.workers),
        "position": lambda: scan_position_params(args.symbol, max_workers=args.workers),
        "risk": lambda: scan_risk_params(args.symbol, max_workers=args.workers),
        "all": lambda: scan_all(args.symbol, max_workers=args.workers),
    }

    result = scanners[args.scan_type]()
    print(f"\n扫描完成，输出: {result}")
