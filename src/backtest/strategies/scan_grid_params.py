"""
墨枢 - P4-12 网格参数扫描工具

对网格回测策略进行多维参数网格扫描，找出最优组合。

功能:
  - GridParamScanner : 参数空间枚举 + 回测 + 结果排优
  - scan_all_grid_params() : 一键全参数扫描，返回 DataFrame
  - 输出 CSV 到 backtest_results/scans/

参数空间:
  - grid_type:     arithmetic / geometric / volatility
  - n_levels:      5, 10, 15, 20
  - cool_down_bars: 1, 3, 5
  - position_mode: fixed / layer / batcher
  - stop_loss_pct: 0.0, 0.03, 0.05, 0.08
  - vote_threshold: 0.5, 0.6, 0.7

用法::

    from backtest.strategies.scan_grid_params import scan_all_grid_params

    # 一键全参数扫描
    df = scan_all_grid_params("000001.SZ", "20260101", "20260514")
    print(df.head())
    print(f"最优组合: {df.iloc[0].to_dict()}")

Author: 墨衡
Created: 2026-05-15
"""

from __future__ import annotations

import csv
import itertools
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backtest.backtest_engine import BacktestResult

from backtest.strategies.grid_strategy import (
    GridStrategy,
    StaticGridSignal,
    DynamicGridSignal,
    GridVotingSignal,
    GridConfig,
)
from backtest.strategies.grid_position import (
    GridPositionManager,
    create_grid_manager,
)
from backtest.strategies.run_grid import (
    GridRunnerConfig,
    GridRunnerResult,
    run_grid_backtest,
    batch_run_grid,
)


# ═══════════════════════════════════════════════════════════════
# 参数空间 & 常量
# ═══════════════════════════════════════════════════════════════

GRID_PARAM_SPACE: Dict[str, List[Any]] = {
    "grid_type": ["arithmetic", "geometric", "volatility"],
    "n_levels": [5, 10, 15, 20],
    "cool_down_bars": [1, 3, 5],
    "position_mode": ["fixed", "layer", "batcher"],
    "stop_loss_pct": [0.0, 0.03, 0.05, 0.08],
    "vote_threshold": [0.5, 0.6, 0.7],
}

_SCAN_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..",
    "backtest_results", "scans",
)

_DEFAULT_SYMBOL = "000001.SZ"

# CSV 列定义
_CSV_HEADER: List[str] = [
    "idx",
    "symbol",
    "grid_type",
    "n_levels",
    "cool_down_bars",
    "position_mode",
    "stop_loss_pct",
    "vote_threshold",
    "config_key",
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
    "calmar_ratio",
    "composite_score",
    "status",
    "error",
]

_DEFAULT_DATE = ""


# ═══════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════


def _metric(
    result: Optional[BacktestResult], key: str, default: Any = "N/A"
) -> Any:
    """安全提取回测指标。"""
    if result is None:
        return default
    val = result.metrics.get(key)
    return val if val is not None else default


def _compute_composite_score(
    result: Optional[BacktestResult],
) -> float:
    """
    综合评分 = 夏普 × 0.5 + 年化收益率(归一化) × 0.3 + 胜率 × 0.2

    年化收益率 clip 到 [-0.5, 0.5] 后映射到 [0,1]。
    夏普通过 sigmoid 映射到 [0,1]。
    """
    if result is None:
        return 0.0

    sharpe = result.metrics.get("sharpe_ratio", 0.0) or 0.0
    annual_ret = result.metrics.get("annual_return_pct", 0.0) or 0.0
    win_rate = result.metrics.get("win_rate_pct", 0.0) or 0.0

    # 夏普 sigmoid 映射
    sharpe_norm = 1.0 / (1.0 + 2.71828 ** (-sharpe * 2.0))

    # 年化收益率归一化
    annual_norm = max(0.0, min(1.0, (annual_ret + 0.5) / 1.0))

    # 胜率本身在 [0, 1]
    win_norm = max(0.0, min(1.0, win_rate / 100.0))

    score = sharpe_norm * 0.5 + annual_norm * 0.3 + win_norm * 0.2
    return round(score, 4)


def _build_signal(
    grid_type: str,
    n_levels: int,
    vote_threshold: float,
) -> GridStrategy:
    """
    根据参数构建网格策略。

    固定使用 StaticGridSignal，range = [85, 115] 自适应。
    vote_threshold 超过 0.5 时包装为 GridVotingSignal（双网格投票），
    否则使用单一 StaticGridSignal。

    参数
    ----------
    grid_type : str
        "arithmetic" | "geometric" | "volatility"
    n_levels : int
        网格线数量。
    vote_threshold : float
        投票阈值（0.5 以上时启用双网格投票）。

    返回
    -------
    GridStrategy
    """
    config = GridConfig(
        lower_bound=85.0,
        upper_bound=115.0,
        n_levels=n_levels,
        grid_type=grid_type,
    )
    signal = StaticGridSignal(grid_config=config)

    # 如果 vote_threshold > 0.5，启用 GridVotingSignal 双网格投票
    if vote_threshold > 0.5:
        # 第二网格：使用不同 grid_type 增加多样性
        config2 = GridConfig(
            lower_bound=85.0,
            upper_bound=115.0,
            n_levels=n_levels,
            grid_type="geometric" if grid_type == "arithmetic" else "arithmetic",
        )
        signal2 = StaticGridSignal(grid_config=config2)
        signal = GridVotingSignal(
            sub_grids=[signal, signal2],
            vote_threshold=vote_threshold,
        )

    return signal


def _build_position(
    position_mode: str,
    stop_loss_pct: float,
    cool_down_bars: int,
) -> GridPositionManager:
    """
    根据参数构建仓位管理器。

    参数
    ----------
    position_mode : str
        "fixed" | "layer" | "batcher"
    stop_loss_pct : float
        止损比例。0.0 表示不启用止损。
    cool_down_bars : int
        冷却期 Bar 数。

    返回
    -------
    GridPositionManager
    """
    # 仓位参数
    pos_kwargs: Dict[str, Any] = {}
    if position_mode == "fixed":
        pos_kwargs["quantity"] = 200
    elif position_mode == "layer":
        pos_kwargs["base_quantity"] = 100
        pos_kwargs["layer_multiplier"] = 2.0
        pos_kwargs["max_layers"] = 5
    elif position_mode == "batcher":
        pos_kwargs["total_grid_rows"] = 10

    # 风控配置
    risk_config: Dict[str, Any] = {
        "cool_down": {"cool_down_bars": cool_down_bars},
    }
    if stop_loss_pct > 0:
        risk_config["stop_loss"] = {
            "stop_loss_pct": stop_loss_pct,
        }

    return create_grid_manager(
        position_mode=position_mode,
        position_kwargs=pos_kwargs,
        risk_config=risk_config,
    )


def _build_config_key(
    grid_type: str,
    n_levels: int,
    cool_down_bars: int,
    position_mode: str,
    stop_loss_pct: float,
    vote_threshold: float,
) -> str:
    """从参数组合生成唯一可读的配置标识。"""
    parts = [
        f"{grid_type[:4]}",
        f"n{n_levels}",
        f"cd{cool_down_bars}",
        f"{position_mode}",
        f"sl{stop_loss_pct:.0%}".replace("%", "pct") if stop_loss_pct > 0 else "nosl",
        f"vt{vote_threshold:.1f}".replace(".", "p"),
    ]
    return "_".join(parts)


def _extract_row(
    params: Dict[str, Any],
    result: GridRunnerResult,
    idx: int,
) -> Dict[str, Any]:
    """将一次扫描结果转换为 CSV 行。"""
    bt_result = result.backtest_result

    row: Dict[str, Any] = {
        "idx": idx,
        "symbol": result.symbol,
        "grid_type": params.get("grid_type", ""),
        "n_levels": params.get("n_levels", ""),
        "cool_down_bars": params.get("cool_down_bars", ""),
        "position_mode": params.get("position_mode", ""),
        "stop_loss_pct": params.get("stop_loss_pct", ""),
        "vote_threshold": params.get("vote_threshold", ""),
        "config_key": result.config_key,
        "annual_return_pct": _metric(bt_result, "annual_return_pct"),
        "max_drawdown_pct": _metric(bt_result, "max_drawdown_pct"),
        "sharpe_ratio": _metric(bt_result, "sharpe_ratio"),
        "total_return_pct": _metric(bt_result, "total_return_pct"),
        "win_rate_pct": _metric(bt_result, "win_rate_pct"),
        "total_trades": _metric(bt_result, "total_trades"),
        "profit_loss_ratio": _metric(bt_result, "profit_loss_ratio"),
        "avg_holding_days": _metric(bt_result, "avg_holding_days"),
        "avg_profit_pct": _metric(bt_result, "avg_profit_pct"),
        "avg_loss_pct": _metric(bt_result, "avg_loss_pct"),
        "calmar_ratio": _metric(bt_result, "calmar_ratio"),
        "composite_score": _compute_composite_score(bt_result),
        "status": result.status,
        "error": result.error or "",
    }
    return row


def _write_csv(rows: List[Dict[str, Any]], filename: str) -> str:
    """将扫描结果写入 CSV 文件。"""
    os.makedirs(_SCAN_OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(_SCAN_OUTPUT_DIR, filename)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[scan_grid] CSV 已保存: {filepath}")
    return filepath


# ═══════════════════════════════════════════════════════════════
# P4-12: GridParamScanner
# ═══════════════════════════════════════════════════════════════


class GridParamScanner:
    """
    网格参数扫描器（P4-12）。

    支持枚举 GRID_PARAM_SPACE 中的所有参数组合，
    执行批量回测，结果排序和最优参数选择。

    用法::

        scanner = GridParamScanner()
        configs = scanner.generate_configs()
        scanner.run_scan("000001.SZ", "20260101", "20260514")
        scanner.save_results("scan_result.csv")
        best = scanner.get_best_params(metric="sharpe")
        print(best)
    """

    def __init__(
        self,
        param_space: Optional[Dict[str, List[Any]]] = None,
    ):
        self._param_space = param_space or dict(GRID_PARAM_SPACE)

        # 扫描结果缓存
        self._config_keys: List[str] = []
        self._results: List[GridRunnerResult] = []
        self._param_rows: List[Dict[str, Any]] = []
        self._csv_path: Optional[str] = None

    # ═══════════════════════════════════════════════════════════
    # 配置生成
    # ═══════════════════════════════════════════════════════════

    def generate_configs(self) -> List[GridRunnerConfig]:
        """
        枚举所有参数组合，生成 GridRunnerConfig 列表。

        使用 itertools.product 展开笛卡尔积。

        返回
        -------
        List[GridRunnerConfig]
            所有参数组合对应的配置列表。
        """
        # 提取各维参数
        grid_types: List[str] = self._param_space.get("grid_type", ["arithmetic"])
        n_levels_list: List[int] = self._param_space.get("n_levels", [10])
        cool_down_list: List[int] = self._param_space.get("cool_down_bars", [3])
        position_modes: List[str] = self._param_space.get("position_mode", ["fixed"])
        stop_loss_list: List[float] = self._param_space.get("stop_loss_pct", [0.0])
        vote_thresholds: List[float] = self._param_space.get("vote_threshold", [0.5])

        configs: List[GridRunnerConfig] = []
        param_records: List[Dict[str, Any]] = []

        for idx, (gt, nl, cd, pm, sl, vt) in enumerate(
            itertools.product(
                grid_types,
                n_levels_list,
                cool_down_list,
                position_modes,
                stop_loss_list,
                vote_thresholds,
            )
        ):
            config_key = _build_config_key(gt, nl, cd, pm, sl, vt)

            signal = _build_signal(grid_type=gt, n_levels=nl, vote_threshold=vt)
            position = _build_position(
                position_mode=pm,
                stop_loss_pct=sl,
                cool_down_bars=cd,
            )

            cfg = GridRunnerConfig(
                symbol=_DEFAULT_SYMBOL,
                signal=signal,
                position=position,
                tag=f"scan_{config_key}",
            )
            configs.append(cfg)

            param_records.append({
                "idx": idx,
                "grid_type": gt,
                "n_levels": nl,
                "cool_down_bars": cd,
                "position_mode": pm,
                "stop_loss_pct": sl,
                "vote_threshold": vt,
                "config_key": config_key,
            })

        self._config_keys = [r["config_key"] for r in param_records]
        self._param_rows = param_records

        print(
            f"[GridParamScanner] 生成 {len(configs)} 个配置组合"
        )
        return configs

    # ═══════════════════════════════════════════════════════════
    # 扫描执行
    # ═══════════════════════════════════════════════════════════

    def run_scan(
        self,
        symbol: str = _DEFAULT_SYMBOL,
        start_date: str = "",
        end_date: str = "",
        max_workers: int = 4,
    ) -> None:
        """
        执行全参数扫描。

        流程：
          1. generate_configs() 生成所有组合
          2. 在每个配置上设定 symbol / 日期范围
          3. 通过 batch_run_grid 并行执行
          4. 结果存入 self._results

        参数
        ----------
        symbol : str
            股票代码。
        start_date : str
            开始日期（YYYYMMDD）。
        end_date : str
            结束日期（YYYYMMDD）。
        max_workers : int
            并发数，默认 4。
        """
        # 生成配置
        configs = self.generate_configs()

        # 注入 symbol 和日期范围
        for cfg in configs:
            cfg.symbol = symbol
            cfg.start_date = start_date
            cfg.end_date = end_date

        total = len(configs)
        print(
            f"[GridParamScanner] 开始扫描: symbol={symbol}, "
            f"{start_date} ~ {end_date}, 共 {total} 个组合, "
            f"并发 {max_workers}"
        )

        # 执行批量回测
        self._results = batch_run_grid(configs, max_workers=max_workers)

        # 打印成功/失败统计
        success_count = sum(1 for r in self._results if r.status == "SUCCESS")
        failed_count = sum(1 for r in self._results if r.status == "FAILED")
        print(
            f"[GridParamScanner] 扫描完成: "
            f"成功 {success_count}, 失败 {failed_count}"
        )

    # ═══════════════════════════════════════════════════════════
    # 结果保存
    # ═══════════════════════════════════════════════════════════

    def save_results(self, path: str = "") -> str:
        """
        将扫描结果写入 CSV 文件。

        按综合评分降序排列。

        参数
        ----------
        path : str
            文件路径（含扩展名 .csv）。
            为空时自动生成路径。

        返回
        -------
        str
            实际写入的文件路径。
        """
        if not self._results or not self._param_rows:
            raise ValueError("尚无扫描结果，请先调用 run_scan()")

        # 构建 CSV 行
        rows: List[Dict[str, Any]] = []
        for i, (param, result) in enumerate(
            zip(self._param_rows, self._results)
        ):
            row = _extract_row(param, result, idx=i + 1)
            rows.append(row)

        # 按综合评分降序排列
        rows.sort(key=lambda r: float(r["composite_score"]), reverse=True)

        # 重新编号 index
        for i, row in enumerate(rows):
            row["idx"] = i + 1

        # 确定文件名
        if not path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"grid_param_scan_{ts}.csv"

        self._csv_path = _write_csv(rows, path)

        # 打印 Top 5
        self._print_top5(rows)

        return self._csv_path

    @staticmethod
    def _print_top5(rows: List[Dict[str, Any]]) -> None:
        """打印前 5 个最优组合。"""
        print("\n[GridParamScanner] Top 5 最优参数组合")
        print(f"{'排名':<4} {'配置':<40} {'综合评分':<10} {'夏普':<10} {'年化收益':<12} {'胜率':<8}")
        print("-" * 90)
        for i, row in enumerate(rows[:5], 1):
            sharpe = row["sharpe_ratio"]
            ann = row["annual_return_pct"]
            win = row["win_rate_pct"]
            print(
                f"{i:<4} {row['config_key']:<40} "
                f"{row['composite_score']:<10} "
                f"{sharpe if isinstance(sharpe, float) else f'{sharpe:.4f}':<10} "
                f"{ann if isinstance(ann, float) else f'{ann:.2%}':<12} "
                f"{win if isinstance(win, float) else f'{win:.2f}':<8}"
            )

    # ═══════════════════════════════════════════════════════════
    # 最优参数选择
    # ═══════════════════════════════════════════════════════════

    def get_best_params(
        self,
        metric: str = "sharpe",
        top_n: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        根据指定指标选择最优参数组合。

        支持指标: sharpe (夏普), annual_return (年化收益),
                   win_rate (胜率), composite (综合评分, 默认)。

        参数
        ----------
        metric : str
            排序指标名。
            "sharpe" / "annual_return" / "win_rate" / "composite"
        top_n : int
            返回前 N 个最优组合（默认 3）。

        返回
        -------
        List[Dict[str, Any]]
            按指标降序排列的最优参数组合。
        """
        if not self._results or not self._param_rows:
            raise ValueError("尚无扫描结果，请先调用 run_scan()")

        # 构建列表
        entries: List[Dict[str, Any]] = []
        for param, result in zip(self._param_rows, self._results):
            r = result.backtest_result
            entries.append({
                "config_key": param["config_key"],
                "grid_type": param["grid_type"],
                "n_levels": param["n_levels"],
                "cool_down_bars": param["cool_down_bars"],
                "position_mode": param["position_mode"],
                "stop_loss_pct": param["stop_loss_pct"],
                "vote_threshold": param["vote_threshold"],
                "sharpe": _metric(r, "sharpe_ratio", 0.0),
                "annual_return": _metric(r, "annual_return_pct", 0.0),
                "win_rate": _metric(r, "win_rate_pct", 0.0),
                "composite": _compute_composite_score(r),
                "status": result.status,
            })

        # 排序字段映射
        sort_key_map: Dict[str, str] = {
            "sharpe": "sharpe",
            "annual_return": "annual_return",
            "win_rate": "win_rate",
            "composite": "composite",
        }

        sort_key = sort_key_map.get(metric, "composite")
        entries.sort(key=lambda e: e[sort_key], reverse=True)

        # 过滤掉失败的组合
        best = [e for e in entries if e["status"] == "SUCCESS"][:top_n]

        if not best:
            print(f"[scan_grid] 警告: 按 {metric} 排序未找到成功的组合")
            return []

        print(f"\n[GridParamScanner] 最优参数 (按 {metric}):")
        for i, entry in enumerate(best, 1):
            print(
                f"  #{i}: {entry['config_key']} → "
                f"{metric}={entry.get(sort_key, 'N/A'):.4f}, "
                f"夏普={entry['sharpe']:.4f}, "
                f"年化={entry['annual_return']:.2%}"
            )

        return best

    # ═══════════════════════════════════════════════════════════
    # 属性访问
    # ═══════════════════════════════════════════════════════════

    @property
    def results(self) -> List[GridRunnerResult]:
        return list(self._results)

    @property
    def csv_path(self) -> Optional[str]:
        return self._csv_path


# ═══════════════════════════════════════════════════════════════
# P4-12: 一站式全参数扫描函数
# ═══════════════════════════════════════════════════════════════


def scan_all_grid_params(
    symbol: str = _DEFAULT_SYMBOL,
    start_date: str = "20230101",
    end_date: str = "20260514",
    max_workers: int = 4,
    param_space: Optional[Dict[str, List[Any]]] = None,
) -> Any:
    """
    一站式全参数扫描：生成配置 → 运行 → 保存 → 返回结果表（P4-12）。

    使用 GridParamScanner 执行完整的参数网格扫描，
    结果写入 backtest_results/scans/ 目录的 CSV 文件，
    同时返回 pandas DataFrame（降序排列，如 pandas 不可用则返回 List[Dict]）。

    参数
    ----------
    symbol : str
        股票代码，默认 "000001.SZ"。
    start_date : str
        开始日期（YYYYMMDD，默认 20260101）。
    end_date : str
        结束日期（YYYYMMDD，默认 20260514）。
    max_workers : int
        并发数，默认 4。
    param_space : dict, optional
        自定义参数空间。不提供则使用 GRID_PARAM_SPACE。

    返回
    -------
    pandas.DataFrame
        包含所有参数组合及其回测绩效的结果表，按综合评分降序排列。
        列名见 _CSV_HEADER。
        如 pandas 不可用，返回 List[Dict]。
    """
    print(f"\n{'='*60}")
    print(f"[scan_all_grid_params] 开始全参数扫描")
    print(f"  symbol={symbol}, {start_date} ~ {end_date}")
    print(f"  并发数={max_workers}")
    print(f"{'='*60}\n")

    scanner = GridParamScanner(param_space=param_space)
    scanner.run_scan(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        max_workers=max_workers,
    )

    # 保存结果（自动 CSV）
    csv_path = scanner.save_results()

    # 输出 Top 5
    scanner.get_best_params(metric="composite", top_n=5)

    # 尝试返回 DataFrame
    try:
        import pandas as pd

        df = pd.read_csv(csv_path)
        # 添加 index 标号（已包含 idx 列）
        df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
        df.index = df.index + 1  # 1-based index
        df.index.name = "rank"
        total = len(df)
        success = len(df[df["status"] == "SUCCESS"])
        print(f"\n[scan_all_grid_params] 完成: 共 {total} 组合, 成功 {success} 组合")
        return df
    except ImportError:
        print("\n[scan_all_grid_params] pandas 不可用，返回 List[Dict]")
        import csv

        rows: List[Dict[str, Any]] = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="网格回测参数扫描工具")
    parser.add_argument("--symbol", default=_DEFAULT_SYMBOL, help="股票代码")
    parser.add_argument("--start", default="20230101", help="开始日期 (YYYYMMDD)")
    parser.add_argument("--end", default="20260514", help="结束日期 (YYYYMMDD)")
    parser.add_argument("--workers", type=int, default=4, help="并发数")
    parser.add_argument(
        "--action",
        default="scan_all",
        choices=["scan_all", "generate", "best"],
        help="操作 (默认 scan_all)",
    )
    parser.add_argument("--metric", default="composite", help="排序指标")
    parser.add_argument("--top", type=int, default=5, help="返回前 N 个最优")

    args = parser.parse_args()

    print(
        f"网格参数扫描: symbol={args.symbol}, "
        f"{args.start} ~ {args.end}, workers={args.workers}"
    )

    if args.action == "generate":
        scanner = GridParamScanner()
        configs = scanner.generate_configs()
        print(f"生成了 {len(configs)} 个配置组合")
        for cfg in configs[:5]:
            print(f"  - {cfg.symbol}: {cfg.signal.__class__.__name__}")
        print(f"  ... 共 {len(configs)} 个")

    elif args.action == "best":
        # 需要先扫描
        scanner = GridParamScanner()
        scanner.run_scan(
            symbol=args.symbol,
            start_date=args.start,
            end_date=args.end,
            max_workers=args.workers,
        )
        scanner.save_results()
        scanner.get_best_params(metric=args.metric, top_n=args.top)

    else:
        # scan_all
        df = scan_all_grid_params(
            symbol=args.symbol,
            start_date=args.start,
            end_date=args.end,
            max_workers=args.workers,
        )
        print(f"\n扫描完成，结果表共 {len(df)} 行")
