"""transformer.py — 字段映射 + 类型转换

P0 MVP: performance_summary → MetricsCore 字段映射 + PipelineInput 构建
P1: content_hash 通过 _hash_file 计算
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .datasource import DataSourceError
from .model import (
    AnalysisDoc,
    AnalysisMeta,
    MetricsCore,
    MetricsExt,
    PipelineInput,
    _hash_file,
)


class TransformError(Exception):
    """转换阶段异常"""

    def __init__(self, message: str, phase: str = "transform", details: dict | None = None):
        super().__init__(message)
        self.phase = phase
        self.details = details or {}


class Transformer:
    """从 V3 层表数据 → PipelineInput"""

    METRIC_GROUP_MAP = {
        "daily": "daily",
        "weekly": "weekly",
        "param_sweep": "param_sweep",
        "factor_ic": "factor_ic",
    }

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def transform(
        self,
        run_id: str,
        analysis_type: str,
        perf_row: dict | None = None,
        doc_files: list[dict] | None = None,
        initial_capital: float = 1000000.0,
    ) -> PipelineInput:
        """
        从 performance_summary 表行 + 自动发现的文档，转换为 PipelineInput。

        Args:
            run_id: 回测运行 UUID
            analysis_type: 分析类型（summary, deep_analysis, ...）
            perf_row: performance_summary 的行，None 时 raise DataSourceError
            doc_files: 自动发现的文档列表，没有则 pass 空列表
            initial_capital: 初始资金，用于计算 total_pnl

        Returns:
            经过 Pydantic 校验的 PipelineInput 实例

        Raises:
            DataSourceError: perf_row 为 None
            TransformError: Pydantic 校验失败或其他转换错误
        """
        if perf_row is None:
            raise DataSourceError(
                f"未找到 performance_summary 记录：run_id={run_id}",
                details={"run_id": run_id},
            )

        try:
            # 1. 构建 meta
            meta = AnalysisMeta(
                run_id=run_id,
                analysis_type=analysis_type,
            )

            # 2. 构建 metrics_core
            mc = self._map_perf_to_metrics_core(perf_row, run_id=run_id, initial_capital=initial_capital)

            # 3. 构建 docs
            docs: list[AnalysisDoc] = []
            if doc_files:
                for df in doc_files:
                    doc = AnalysisDoc(
                        run_id=run_id,
                        doc_type=df["doc_type"],
                        file_path=df["file_path"],
                        content_hash=df.get("content_hash", ""),
                        file_size_bytes=df.get("file_size_bytes", 0),
                    )
                    docs.append(doc)
            else:
                # 文档为空时，写入一条占位记录
                docs.append(
                    AnalysisDoc(
                        run_id=run_id,
                        doc_type="summary_report",
                        file_path="./placeholder_no_file.md",
                        content_hash="",
                        file_size_bytes=0,
                    )
                )

            # 4. 构建 PipelineInput
            return PipelineInput(
                meta=meta,
                metrics_core=[mc],
                metrics_ext=[],
                docs=docs,
            )

        except Exception as e:
            if isinstance(e, DataSourceError):
                raise
            raise TransformError(
                f"转换失败: {e}",
                details={"run_id": run_id, "analysis_type": analysis_type},
            ) from e

    def _map_perf_to_metrics_core(
        self,
        perf_row: dict,
        run_id: str = "",
        metric_group: str = "daily",
        initial_capital: float = 1000000.0,
    ) -> MetricsCore:
        """将 performance_summary 的一行映射到 MetricsCore"""

        # 计算 total_pnl
        final_equity = _to_float(perf_row.get("final_equity"))
        total_pnl = None
        if final_equity is not None:
            total_pnl = round(final_equity - initial_capital, 2)

        # ——— 字段映射逻辑 ———
        # performance_summary 表缺少以下列:
        #   winning_trades, losing_trades, total_profit, total_loss,
        #   max_single_win, max_single_loss
        # 通过 .get() 获取不存在的键返回 None, _to_int/_to_float(None) 返回 None
        # 其中 winning_trades/losing_trades 可从 total_trades * win_rate/100 推导

        total_trades = _to_int(perf_row.get("total_trades"))
        win_rate = _to_float(perf_row.get("win_rate"))

        # 推导 winning_trades / losing_trades
        # 注: performance_summary 中的 win_rate 为比值(0.0~1.0)而非百分比(0~100)
        winning_trades: int | None = _to_int(perf_row.get("winning_trades"))
        losing_trades: int | None = _to_int(perf_row.get("losing_trades"))
        if winning_trades is None and total_trades is not None and win_rate is not None:
            winning_trades = round(total_trades * win_rate)  # win_rate 是比值
            losing_trades = total_trades - winning_trades
        elif winning_trades is None:
            winning_trades = None
            losing_trades = None

        mc = MetricsCore(
            run_id=run_id,
            metric_group=metric_group,
            total_return_pct=_to_float(perf_row.get("total_return")),
            annual_return_pct=_to_float(perf_row.get("annualized_return")),
            final_equity=final_equity,
            total_pnl=total_pnl,
            benchmark_return_pct=_to_float(perf_row.get("benchmark_return")),
            excess_return_pct=_to_float(perf_row.get("excess_return")),
            max_drawdown_pct=_to_float(perf_row.get("max_drawdown")),
            annual_volatility_pct=_to_float(perf_row.get("volatility")),
            sharpe_ratio=_to_float(perf_row.get("sharpe_ratio")),
            calmar_ratio=_to_float(perf_row.get("calmar_ratio")),
            sortino_ratio=_to_float(perf_row.get("sortino_ratio")),
            var_95_pct=_to_float(perf_row.get("var_95_pct")),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate,
            total_profit=_to_float(perf_row.get("total_profit")),
            total_loss=_to_float(perf_row.get("total_loss")),
            profit_loss_ratio=None,
            max_consecutive_wins=_to_int(perf_row.get("max_consecutive_wins")),
            max_consecutive_losses=_to_int(perf_row.get("max_consecutive_losses")),
            max_single_win=_to_float(perf_row.get("max_single_win")),
            max_single_loss=_to_float(perf_row.get("max_single_loss")),
            verdict=None,
            risk_level=None,
            core_issue=None,
            improvement_potential=None,
        )
        return mc

    def _compute_content_hash(self, file_path: str | Path) -> str:
        """计算 SHA256 文件哈希"""
        return _hash_file(file_path)


# ——— 类型转换辅助函数 ———


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
