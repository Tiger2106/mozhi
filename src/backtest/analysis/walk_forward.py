"""
墨枢 — WalkForward 分析模块

P4 实施：Walk Forward 分析（滚动窗格）
验证策略参数的泛化能力。

核心组件:
  - WalkForwardFold: 单个窗格定义（训练期 + 测试期）
  - WalkForwardPlan: 窗格划分方案（支持多种方案，默认方案C）
  - WalkForwardRunner: 执行完整的 Walk Forward 分析
  - WalkForwardResult: 分析结果封装

设计参考: report_upgrade_v3_design.md §5

时间戳约定: 所有日期使用 "YYYYMMDD" 格式。
时区: Asia/Shanghai (+08:00)

Author: 墨衡 (moheng)
Created: 2026-05-18
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ─── 项目内部导入 ────────────────────────────────────────────
# 回测引擎
from backtest.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Bar,
    Strategy,
)
from backtest.performance import PerformanceCalculator

# 数据加载（复用 run_grid 中的数据加载函数）
from backtest.strategies.run_grid import load_stock_bars

# 网格策略参数扫描（部分函数在各方法内导入以避免循环依赖）
from backtest.strategies.scan_grid_params import GridParamScanner

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# WalkForwardFold
# ═══════════════════════════════════════════════════════════════


@dataclass
class WalkForwardFold:
    """单个 Walk Forward 窗格定义。

    每个窗格包含一个训练期（寻找最优参数）和一个测试期（验证参数泛化能力）。

    Attributes:
        fold_id: 窗格编号（1-based）。
        train_start: 训练期开始日期（YYYYMMDD）。
        train_end: 训练期结束日期（YYYYMMDD）。
        test_start: 测试期开始日期（YYYYMMDD）。
        test_end: 测试期结束日期（YYYYMMDD）。
        label: 窗格标签（可选），如 "W1"、"W2"。
    """

    fold_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = f"W{self.fold_id}"

    @property
    def total_days(self) -> int:
        """窗格总天数（训练 + 测试）。"""
        from datetime import datetime as dt

        train_days = (dt.strptime(self.test_end, "%Y%m%d") - dt.strptime(self.train_start, "%Y%m%d")).days
        test_days = (dt.strptime(self.test_end, "%Y%m%d") - dt.strptime(self.test_start, "%Y%m%d")).days
        # 估算交易日 (~60%)
        return int((train_days + test_days) * 0.6)

    def to_dict(self) -> Dict[str, str]:
        return {
            "fold_id": self.fold_id,
            "label": self.label,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
        }


# ═══════════════════════════════════════════════════════════════
# WalkForwardPlan
# ═══════════════════════════════════════════════════════════════


class WalkForwardPlan:
    """Walk Forward 窗格划分方案。

    内置方案:
        - SCHEME_C: 滚动窗格方案C（默认），步长 20 天
          来自设计文档 §5.1
    """

    # 方案C（滚动窗格，步长 222 日历天，覆盖 2023-01-01 ~ 2026-05-14）
    # 约 820 个交易日，5 个窗格等间距分布
    # 训练期 ≥ 252 日历天（≈180 交易日），测试期 ≥ 84 日历天（≈60 交易日）
    SCHEME_C: List[WalkForwardFold] = [
        WalkForwardFold(fold_id=1, train_start="20230101", train_end="20230909",
                        test_start="20230911", test_end="20231203", label="W1"),
        WalkForwardFold(fold_id=2, train_start="20230811", train_end="20240419",
                        test_start="20240420", test_end="20240712", label="W2"),
        WalkForwardFold(fold_id=3, train_start="20240320", train_end="20241127",
                        test_start="20241128", test_end="20250219", label="W3"),
        WalkForwardFold(fold_id=4, train_start="20241027", train_end="20250706",
                        test_start="20250707", test_end="20250928", label="W4"),
        WalkForwardFold(fold_id=5, train_start="20250605", train_end="20260211",
                        test_start="20260212", test_end="20260514", label="W5"),
    ]

    def __init__(
        self,
        folds: Optional[List[WalkForwardFold]] = None,
        scheme: str = "C",
    ):
        """
        参数:
            folds: 自定义窗格列表。None 则使用内置方案。
            scheme: 内置方案名 ("C" / "A" / "B")。folds 不为 None 时忽略。
        """
        if folds is not None:
            self.folds = folds
        elif scheme.upper() == "C":
            self.folds = list(self.SCHEME_C)
        elif scheme.upper() == "A":
            self.folds = self._build_scheme_a()
        elif scheme.upper() == "B":
            self.folds = self._build_scheme_b()
        else:
            raise ValueError(f"未知方案: {scheme}")

    @staticmethod
    def _build_scheme_a() -> List[WalkForwardFold]:
        """方案A: 固定窗格, 2折 (50%/50%)"""
        return [
            WalkForwardFold(fold_id=1, train_start="20260101", train_end="20260305",
                            test_start="20260306", test_end="20260514", label="W1"),
        ]

    @staticmethod
    def _build_scheme_b() -> List[WalkForwardFold]:
        """方案B: 固定窗格, 3折 (33%/33%/33%)"""
        return [
            WalkForwardFold(fold_id=1, train_start="20260101", train_end="20260208",
                            test_start="20260209", test_end="20260318", label="W1"),
            WalkForwardFold(fold_id=2, train_start="20260209", train_end="20260318",
                            test_start="20260319", test_end="20260514", label="W2"),
        ]

    @property
    def n_folds(self) -> int:
        return len(self.folds)

    def __iter__(self):
        return iter(self.folds)

    def __len__(self) -> int:
        return len(self.folds)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        return [f.to_dict() for f in self.folds]


# ═══════════════════════════════════════════════════════════════
# WalkForwardWindowResult
# ═══════════════════════════════════════════════════════════════


@dataclass
class WalkForwardWindowResult:
    """单个窗格的 Walk Forward 分析结果。

    Attributes:
        fold: 窗格定义。
        optimal_params: 训练期最优参数（含 config_key）。
        train_metrics: 训练期绩效指标。
        test_metrics: 测试期绩效指标。
        wfe: Walk Forward 效率比（test_sharpe / train_sharpe）。
        status: 状态（"SUCCESS" / "NO_TRADES" / "FAILED"）。
        error: 错误信息（若有）。
    """

    fold: WalkForwardFold
    optimal_params: Dict[str, Any] = field(default_factory=dict)
    train_metrics: Dict[str, Any] = field(default_factory=dict)
    test_metrics: Dict[str, Any] = field(default_factory=dict)
    wfe: float = 0.0
    status: str = "SUCCESS"
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fold": self.fold.to_dict(),
            "optimal_params": {
                k: v for k, v in self.optimal_params.items()
                if k in ("config_key", "grid_type", "n_levels", "cool_down_bars",
                        "position_mode", "stop_loss_pct", "vote_threshold")
            },
            "train_metrics": {
                k: v for k, v in self.train_metrics.items()
                if k in ("sharpe_ratio", "annual_return_pct", "max_drawdown_pct",
                        "total_return_pct", "total_trades", "win_rate_pct")
            },
            "test_metrics": {
                k: v for k, v in self.test_metrics.items()
                if k in ("sharpe_ratio", "annual_return_pct", "max_drawdown_pct",
                        "total_return_pct", "total_trades", "win_rate_pct")
            },
            "wfe": self.wfe,
            "status": self.status,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════
# WalkForwardResult (聚合结果)
# ═══════════════════════════════════════════════════════════════


@dataclass
class WalkForwardResult:
    """Walk Forward 分析聚合结果。

    Attributes:
        symbol: 标的代码。
        plan: 窗格划分方案。
        window_results: 各窗格结果列表。
        avg_wfe: 平均 WFE。
        wfe_std: WFE 标准差。
        param_reuse_rate: 最优参数重用率（最常选参数的出现比例）。
        completed_time: 完成时间（ISO8601 +08:00）。
    """

    symbol: str
    plan: WalkForwardPlan
    window_results: List[WalkForwardWindowResult] = field(default_factory=list)
    avg_wfe: float = 0.0
    wfe_std: float = 0.0
    param_reuse_rate: float = 0.0
    dominant_param_key: str = ""
    non_trading_windows: int = 0
    completed_time: str = ""

    def add_window(self, result: WalkForwardWindowResult) -> None:
        """添加单个窗格结果。"""
        self.window_results.append(result)
        self._recompute_aggregates()

    def _recompute_aggregates(self) -> None:
        """重新计算聚合指标。"""
        if not self.window_results:
            return

        wfes = [r.wfe for r in self.window_results if r.status == "SUCCESS"]
        self.avg_wfe = sum(wfes) / len(wfes) if wfes else 0.0
        self.wfe_std = (
            (sum((w - self.avg_wfe) ** 2 for w in wfes) / len(wfes)) ** 0.5
            if len(wfes) > 1 else 0.0
        )

        # 最优参数重用率
        param_keys = [r.optimal_params.get("config_key", "") for r in self.window_results if r.status == "SUCCESS"]
        if param_keys:
            from collections import Counter
            counter = Counter(param_keys)
            most_common = counter.most_common(1)
            self.dominant_param_key = most_common[0][0] if most_common else ""
            self.param_reuse_rate = most_common[0][1] / len(param_keys) if most_common else 0.0

        self.non_trading_windows = sum(
            1 for r in self.window_results
            if r.test_metrics.get("total_trades", 0) == 0
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "plan": self.plan.to_dict_list(),
            "n_folds": len(self.plan),
            "window_results": [r.to_dict() for r in self.window_results],
            "avg_wfe": round(self.avg_wfe, 4),
            "wfe_std": round(self.wfe_std, 4),
            "param_reuse_rate": round(self.param_reuse_rate, 4),
            "dominant_param_key": self.dominant_param_key,
            "non_trading_windows": self.non_trading_windows,
            "completed_time": self.completed_time,
        }

    def to_json(self, path: str) -> None:
        """序列化为 JSON 文件。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"[WalkForward] 结果已保存: {path}")


# ═══════════════════════════════════════════════════════════════
# WalkForwardRunner
# ═══════════════════════════════════════════════════════════════


class WalkForwardRunner:
    """Walk Forward 分析运行器。

    流程:
      1. 加载 K 线数据
      2. 按窗格划分方案遍历
      3. 每个窗格:
         a. 在训练期运行参数扫描 → 找出最优参数
         b. 用最优参数在测试期回测 → 记录指标
      4. 聚合 WFE / 参数重用率

    用法::

        runner = WalkForwardRunner(
            symbol="601857",
            start_date="20260101",
            end_date="20260514",
            scheme="C",
        )
        result = runner.run()
        result.to_json("data/results/walkforward_result.json")
    """

    def __init__(
        self,
        symbol: str = "601857",
        start_date: str = "20230101",
        end_date: str = "20260514",
        scheme: str = "C",
        max_workers: int = 1,
        focused_params: Optional[Dict[str, List[Any]]] = None,
    ):
        """
        参数:
            symbol: 标的代码。
            start_date: 数据开始日期。
            end_date: 数据结束日期。
            scheme: 窗格方案 ("C" / "A" / "B")。
            max_workers: 参数扫描并发数。
            focused_params: 聚焦的参数空间（减小扫描量）。
        """
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.scheme = scheme
        self.max_workers = max_workers

        # 聚焦参数空间（216 组合，单线程约 6s/窗格）
        self.focused_params = focused_params or {
            "grid_type": ["arithmetic", "geometric"],
            "n_levels": [5, 10, 15, 20],
            "cool_down_bars": [1, 3, 5],
            "position_mode": ["fixed", "layer", "batcher"],
            "stop_loss_pct": [0.0, 0.03, 0.05],
            "vote_threshold": [0.5],
        }

        # 窗格方案
        self.plan = WalkForwardPlan(scheme=scheme)

        # 缓存数据
        self._bars: List[Bar] = []

        # 修复 DB 路径（run_grid._DEFAULT_DB 指向 src/data，实际在 data/）
        self._fix_db_path()

    def _fix_db_path(self) -> None:
        """修正默认 DB 路径（_DEFAULT_DB 指向 src/data/，实际在 data/）。"""
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        correct_db = os.path.join(repo_root, "data", "market", "market_data.db")
        if os.path.exists(correct_db):
            os.environ["DB_PATH"] = correct_db

    # ═══════════════════════════════════════════════════════════
    # 数据加载
    # ═══════════════════════════════════════════════════════════════

    def _load_bars(self) -> List[Bar]:
        """加载 K 线数据（复用 run_grid.load_stock_bars）。"""
        if self._bars:
            return self._bars

        try:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))))),
                "data", "market", "market_data.db",
            )
            print(f"[WalkForward] DB path: {db_path}")
            bars = load_stock_bars(self.symbol, self.start_date, self.end_date, db_path)
            self._bars = bars
            print(f"[WalkForward] 数据加载完成: {len(bars)} bars")
            return bars
        except Exception as e:
            print(f"[WalkForward] 数据加载失败: {e}")
            raise

    # ═══════════════════════════════════════════════════════════
    # 参数扫描
    # ═══════════════════════════════════════════════════════════

    def _run_param_scan(
        self, bars: List[Bar],
    ) -> Dict[str, Any]:
        """在指定 bars 上运行参数扫描，返回最优参数。

        使用聚焦参数空间 + batch_run_grid 多线程扫描。
        网格上下界基于训练期平均价格动态计算（±15%）。

        参数:
            bars: 用于扫描的 Bar 数据列表。

        返回:
            Dict 包含最优参数的各项指标。
        """
        if not bars:
            return {"config_key": "", "sharpe_ratio": 0.0, "status": "FAILED"}

        from backtest.strategies.run_grid import batch_run_grid, GridRunnerConfig
        from backtest.strategies.grid_strategy import GridConfig, StaticGridSignal, GridVotingSignal

        # 基于训练期平均价格计算网格上下界
        avg_price = sum(b.close for b in bars) / len(bars)
        price_lower = round(avg_price * 0.85, 2)  # -15%
        price_upper = round(avg_price * 1.15, 2)  # +15%

        start_date = bars[0].date
        end_date = bars[-1].date

        # 手工构建配置（使用价格自适应上下界）
        configs: List[GridRunnerConfig] = []
        param_records: List[Dict[str, Any]] = []

        import itertools
        grid_types = self.focused_params.get("grid_type", ["arithmetic"])
        n_levels_list = self.focused_params.get("n_levels", [10])
        cool_down_list = self.focused_params.get("cool_down_bars", [3])
        position_modes = self.focused_params.get("position_mode", ["fixed"])
        stop_loss_list = self.focused_params.get("stop_loss_pct", [0.0])
        vote_thresholds = self.focused_params.get("vote_threshold", [0.5])

        for idx, (gt, nl, cd, pm, sl, vt) in enumerate(itertools.product(
            grid_types, n_levels_list, cool_down_list,
            position_modes, stop_loss_list, vote_thresholds,
        )):
            # 生成 config_key
            sl_part = f"sl{int(sl*100)}pct" if sl > 0 else "nosl"
            config_key = f"{gt[0:5]}_n{nl}_cd{cd}_{pm}_{sl_part}_vt{vt}".replace(
                "arithm", "arit"
            ).replace("geometr", "geom")

            # 构建网格信号
            from backtest.strategies.scan_grid_params import _build_position
            config = GridConfig(
                lower_bound=price_lower,
                upper_bound=price_upper,
                n_levels=nl,
                grid_type=gt,
                cool_down_bars=cd,
            )
            signal = StaticGridSignal(grid_config=config)

            # 投票阈值 > 0.5 时使用双网格投票
            if vt > 0.5:
                config2 = GridConfig(
                    lower_bound=price_lower,
                    upper_bound=price_upper,
                    n_levels=nl,
                    grid_type="geometric" if gt == "arithmetic" else "arithmetic",
                )
                signal2 = StaticGridSignal(grid_config=config2)
                signal = GridVotingSignal(sub_grids=[signal, signal2], vote_threshold=vt)

            position = _build_position(
                position_mode=pm, stop_loss_pct=sl, cool_down_bars=cd
            )

            cfg = GridRunnerConfig(
                symbol=self.symbol,
                signal=signal,
                position=position,
                start_date=start_date,
                end_date=end_date,
                tag=f"walk_{config_key}",
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

        print(f"  [param_scan] 开始扫描 {len(configs)} 组合 "
              f"(price_bounds=[{price_lower}, {price_upper}], "
              f"max_workers={self.max_workers})...")

        scan_results = batch_run_grid(configs, max_workers=self.max_workers)

        # 找出最优组合
        best_result = None
        best_sharpe = -999.0
        best_config_key = ""

        for i, (scan_res, param_row) in enumerate(zip(scan_results, param_records)):
            if scan_res.status != "SUCCESS" or scan_res.backtest_result is None:
                continue
            sharpe = scan_res.backtest_result.metrics.get("sharpe_ratio", 0.0) or 0.0
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_result = scan_res
                best_config_key = param_row.get("config_key", "")

        if best_result is None or best_result.backtest_result is None:
            return {"config_key": "", "sharpe_ratio": 0.0, "status": "FAILED"}

        bt = best_result.backtest_result
        params = self._parse_config_key(best_config_key)

        return {
            "config_key": best_config_key,
            "sharpe_ratio": best_sharpe,
            "annual_return_pct": bt.metrics.get("annual_return_pct", 0.0),
            "max_drawdown_pct": bt.metrics.get("max_drawdown_pct", 0.0),
            "total_return_pct": bt.metrics.get("total_return_pct", 0.0),
            "total_trades": bt.metrics.get("total_trades", 0),
            "win_rate_pct": bt.metrics.get("win_rate_pct", 0.0),
            "status": "SUCCESS",
            **params,
        }

    def _parse_config_key(self, key: str) -> Dict[str, Any]:
        """从 config_key 反向解析参数。"""
        params: Dict[str, Any] = {}
        if not key:
            return params

        parts = key.split("_")
        for part in parts:
            if part.startswith("arit") or part.startswith("geom") or part.startswith("volt"):
                params["grid_type"] = "arithmetic" if part.startswith("arit") else \
                    "geometric" if part.startswith("geom") else "volatility"
            elif part.startswith("n"):
                try:
                    params["n_levels"] = int(part[1:])
                except ValueError:
                    pass
            elif part.startswith("cd"):
                try:
                    params["cool_down_bars"] = int(part[2:])
                except ValueError:
                    pass
            elif part in ("fixed", "layer", "batcher"):
                params["position_mode"] = part
            elif part.startswith("sl") and part != "sl":
                try:
                    params["stop_loss_pct"] = float(part[2:].replace("pct", "")) / 100.0
                except ValueError:
                    pass
            elif part.startswith("vt"):
                try:
                    params["vote_threshold"] = float(part[2:].replace("p", "."))
                except ValueError:
                    pass

        return params

    def _run_single_backtest(
        self,
        cfg: Any,
        start_date: str = "",
        end_date: str = "",
    ) -> Optional[BacktestResult]:
        """为单一配置运行回测（使用 run_grid_backtest 标准封装）。

        run_grid_backtest 内部通过 load_stock_bars 自动加载对应日期范围的数据。
        """
        try:
            from backtest.strategies.run_grid import run_grid_backtest, GridRunnerConfig

            if hasattr(cfg, 'signal') and hasattr(cfg, 'position'):
                cfg.start_date = start_date
                cfg.end_date = end_date
                cfg.symbol = self.symbol
                result = run_grid_backtest(cfg)
                return result.backtest_result
            else:
                runner_cfg = GridRunnerConfig(
                    symbol=self.symbol,
                    signal=cfg.signal if hasattr(cfg, 'signal') else cfg,
                    position=cfg.position if hasattr(cfg, 'position') else None,
                    start_date=start_date,
                    end_date=end_date,
                )
                result = run_grid_backtest(runner_cfg)
                return result.backtest_result
        except Exception as e:
            logger.warning(f"  ˪ 回测失败: {e}")
            return None

    # ═══════════════════════════════════════════════════════════
    # 主运行逻辑
    # ═══════════════════════════════════════════════════════════

    def run(self) -> WalkForwardResult:
        """执行 Walk Forward 分析。"""
        print(f"\n{'='*60}")
        print(f"WalkForward 分析开始")
        print(f"  symbol={self.symbol}, 方案={self.scheme}")
        print(f"  {self.start_date} ~ {self.end_date}")
        print(f"  窗格数={self.plan.n_folds}")
        print(f"{'='*60}\n")

        # 1. 加载全量数据
        full_bars = self._load_bars()

        # 2. 初始化结果
        result = WalkForwardResult(
            symbol=self.symbol,
            plan=self.plan,
        )

        # 3. 逐窗格分析
        for fold in self.plan:
            print(f"\n{'─'*50}")
            print(f"[Fold {fold.label}] 训练: {fold.train_start}~{fold.train_end}, "
                  f"测试: {fold.test_start}~{fold.test_end}")
            print(f"{'─'*50}")

            # 过滤数据
            train_bars = [b for b in full_bars if fold.train_start <= b.date <= fold.train_end]
            test_bars = [b for b in full_bars if fold.test_start <= b.date <= fold.test_end]

            print(f"  训练期: {len(train_bars)} bars, 测试期: {len(test_bars)} bars")

            if not train_bars:
                result.add_window(WalkForwardWindowResult(
                    fold=fold, status="FAILED", error="训练期无数据"
                ))
                continue

            # 3a. 参数扫描（训练期）
            print(f"  参数扫描中 ({len(train_bars)} bars)...")
            optimal = self._run_param_scan(train_bars)

            if optimal.get("status") != "SUCCESS":
                result.add_window(WalkForwardWindowResult(
                    fold=fold, status="FAILED", error="参数扫描未找到有效组合"
                ))
                continue

            print(f"  最优参数: {optimal.get('config_key', 'N/A')}, "
                  f"训练 Sharpe={optimal.get('sharpe_ratio', 0.0):.4f}")

            cfg_key = optimal.get("config_key", "")

            # 计算训练期均价
            train_avg_price = sum(b.close for b in train_bars) / len(train_bars) if train_bars else 10.0

            # 3b. 重建最优参数的配置
            test_cfg = self._build_optimal_config(cfg_key, avg_price=train_avg_price)

            if test_cfg is None:
                result.add_window(WalkForwardWindowResult(
                    fold=fold, status="FAILED", error="最优参数重建失败"
                ))
                continue

            # 3c. 训练期回测（用于确认指标）
            print(f"  训练期验证中...")
            train_result = self._run_single_backtest(
                test_cfg,
                start_date=fold.train_start,
                end_date=fold.train_end,
            )

            # 3d. 测试期回测
            print(f"  测试期回测中 ({len(test_bars)} bars)...")
            test_result = self._run_single_backtest(
                test_cfg,
                start_date=fold.test_start,
                end_date=fold.test_end,
            )

            # 3e. 记录结果
            train_metrics = train_result.metrics if train_result else {}
            test_metrics = test_result.metrics if test_result else {}

            train_sharpe = train_metrics.get("sharpe_ratio", 0.0) or 0.0
            test_sharpe = test_metrics.get("sharpe_ratio", 0.0) or 0.0

            # WFE = test_sharpe / train_sharpe（当 train_sharpe > 0）
            wfe = test_sharpe / train_sharpe if train_sharpe > 0 else 0.0

            wr = WalkForwardWindowResult(
                fold=fold,
                optimal_params=optimal,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                wfe=round(wfe, 4),
                status="NO_TRADES" if test_metrics.get("total_trades", 0) == 0 else "SUCCESS",
            )
            result.add_window(wr)

            print(f"  结果: 训练 Sharpe={train_sharpe:.4f}, "
                  f"测试 Sharpe={test_sharpe:.4f}, WFE={wfe:.4f}")

        # 4. 聚合结果
        result.completed_time = datetime.now().astimezone().isoformat()

        print(f"\n{'='*60}")
        print(f"WalkForward 分析完成")
        print(f"  平均 WFE: {result.avg_wfe:.4f}")
        print(f"  WFE 标准差: {result.wfe_std:.4f}")
        print(f"  参数重用率: {result.param_reuse_rate:.2%}")
        print(f"  主导参数: {result.dominant_param_key}")
        print(f"  无交易窗格: {result.non_trading_windows}/{result.plan.n_folds}")
        print(f"{'='*60}")

        return result

    def _build_optimal_config(self, config_key: str, avg_price: float = 0.0) -> Any:
        """从 config_key 重建 GridRunnerConfig（使用动态价格上下界）。"""
        params = self._parse_config_key(config_key)
        if not params:
            return None

        gt = params.get("grid_type", "arithmetic")
        nl = params.get("n_levels", 5)
        vt = params.get("vote_threshold", 0.5)
        pm = params.get("position_mode", "fixed")
        sl = params.get("stop_loss_pct", 0.0)
        cd = params.get("cool_down_bars", 1)

        from backtest.strategies.grid_strategy import GridConfig, StaticGridSignal, GridVotingSignal
        from backtest.strategies.scan_grid_params import _build_position

        # 动态计算价格上下界
        if avg_price <= 0:
            avg_price = 10.0  # 回退默认值
        price_lower = round(avg_price * 0.85, 2)
        price_upper = round(avg_price * 1.15, 2)

        config = GridConfig(
            lower_bound=price_lower,
            upper_bound=price_upper,
            n_levels=nl,
            grid_type=gt,
        )
        signal = StaticGridSignal(grid_config=config)

        if vt > 0.5:
            config2 = GridConfig(
                lower_bound=price_lower,
                upper_bound=price_upper,
                n_levels=nl,
                grid_type="geometric" if gt == "arithmetic" else "arithmetic",
            )
            signal2 = StaticGridSignal(grid_config=config2)
            signal = GridVotingSignal(sub_grids=[signal, signal2], vote_threshold=vt)

        position = _build_position(position_mode=pm, stop_loss_pct=sl, cool_down_bars=cd)

        from backtest.strategies.run_grid import GridRunnerConfig
        cfg = GridRunnerConfig(
            symbol=self.symbol,
            signal=signal,
            position=position,
            tag=f"walk_{config_key}",
        )
        return cfg


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def run_walk_forward(
    symbol: str = "601857",
    scheme: str = "C",
    output_dir: str = "",
    start_date: str = "20230101",
    end_date: str = "20260514",
) -> WalkForwardResult:
    """运行一站式 Walk Forward 分析。

    参数:
        symbol: 标的代码。
        scheme: 窗格方案 ("C" / "A" / "B")。
        output_dir: 输出目录。空则使用默认路径。

    返回:
        WalkForwardResult。
    """
    runner = WalkForwardRunner(
        symbol=symbol,
        scheme=scheme,
        start_date=start_date,
        end_date=end_date,
    )
    result = runner.run()

    # 保存结果
    if not output_dir:
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "data", "results",
        )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"walkforward_{symbol}_{scheme}.json")
    result.to_json(output_path)

    return result


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Walk Forward 分析")
    parser.add_argument("--symbol", default="601857", help="标的代码")
    parser.add_argument("--scheme", default="C", choices=["A", "B", "C"], help="窗格方案")
    parser.add_argument("--output", default="", help="输出目录")
    args = parser.parse_args()

    result = run_walk_forward(
        symbol=args.symbol,
        scheme=args.scheme,
        output_dir=args.output,
    )
    print(f"\n分析完成: avg_wfe={result.avg_wfe:.4f}, "
          f"param_reuse={result.param_reuse_rate:.2%}")
