"""
Pipeline — 共振系统流水线编排模块

实现 DataBridge → DCM → LQM → ZNM → RSM ∥ DSV → GKV → CPE → SG → SCL
的完整流水线编排。

核心特性:
  - run_once() : 单日多标的执行
  - run_loop() : 多日多标的回滚执行
  - 每个模块调用前检查前置状态，自动跳过 SKIPPED/FAILED
  - 结果收集至 PipelineResult dataclass
  - 支持 PipelineConfig 配置
  - 可配置重试、超时、日期间隔等
  - 幂等性：重复调用同一标的+同一日期返回历史结果

Usage:
    >>> from src.resonance.pipeline import PipelineOrchestrator
    >>> orch = PipelineOrchestrator()
    >>> # 单次运行
    >>> results = orch.run_once(
    ...     tickers=["601857.SH", "600519.SH"],
    ...     date="20260529",
    ... )
    >>> # 循环运行
    >>> results = orch.run_loop(
    ...     tickers=["601857.SH"],
    ...     start_date="20260520",
    ...     end_date="20260529",
    ...     step_days=5,
    ... )

依赖:
    - src.resonance.data_bridge: DataBridge.fetch_ohlcv
    - src.resonance.dcm: DCM.compute
    - src.resonance.lqm: LQM.compute
    - src.resonance.znm: ZNM.compute
    - src.resonance.rsm: RSM.compute, RSM.compute_strength
    - src.resonance.dsv: DSV.compute
    - src.resonance.gkv: GKV.compute
    - src.resonance.cpe: CPE.compute
    - src.resonance.sg: SG.generate
    - src.resonance.scl: SCL.consume
    - src.resonance.constants: 全局常量
    - src.resonance.models: 所有模块结果类型

Author: moheng
Created: 2026-05-29T11:31:00+08:00
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.resonance.constants import LOOKBACK_WINDOW
from src.resonance.data_bridge import fetch_ohlcv
from src.resonance.dcm import compute as dcm_compute
from src.resonance.lqm import compute as lqm_compute
from src.resonance.znm import compute as znm_compute
from src.resonance.rsm import (
    LookbackBuffer,
    compute as rsm_compute,
    compute_strength as rsm_compute_strength,
)
from src.resonance.dsv import (
    DSVResult,
    compute as dsv_compute,
)
from src.resonance.gkv import compute as gkv_compute
from src.resonance.cpe import compute as cpe_compute
from src.resonance.sg import generate as sg_generate
from src.resonance.scl import (
    SCLResult,
    consume as scl_consume,
)
from src.resonance.models import (
    ModuleResult,
    ModuleStatus,
    PipelineConfig,
    RSMState,
    DCMResult,
    LQMResult,
    ZNMResult,
    RSMPipelineState,
    GKVResult,
    CPEResult,
    SGResult,
    ResonanceSignal,
)

logger = logging.getLogger("resonance.pipeline")

# ══════════════════════════════════════════════════════════
# 时区常量
# ══════════════════════════════════════════════════════════

_CST_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


# ══════════════════════════════════════════════════════════
# PipelineResult — 单标的流水线执行结果
# ══════════════════════════════════════════════════════════


@dataclass
class PipelineResult:
    """单个标的在单次流水线执行中的完整结果。

    包含所有模块的执行状态、产出数据以及最终信号。
    """

    ticker: str
    """标的代码，如 '601857.SH'。"""

    date: str
    """执行日期，YYYYMMDD 格式。"""

    status: str = "PENDING"
    """流水线整体状态: PENDING | RUNNING | PASS | PARTIAL | FAILED | SKIPPED。"""

    # ── 各模块结果（None = 未执行/不适用） ──

    data_bridge_result: Optional[pd.DataFrame] = None
    """DataBridge 原始 OHLCV 数据。用于下游 DCM / LQM。"""

    dcm_result: Optional[DCMResult] = None
    """DCM 波动率代理模块结果。"""

    lqm_result: Optional[LQMResult] = None
    """LQM 流动性评价模块结果。"""

    znm_result: Optional[ZNMResult] = None
    """ZNM z-score 归一化模块结果。"""

    rsm_state: Optional[RSMPipelineState] = None
    """RSM 共振状态机结果（持久化状态）。"""

    rsm_strength: Optional[float] = None
    """RSM 共振强度 [0, 1]，由 compute_strength(zscore) 计算。"""

    dsv_result: Optional[DSVResult] = None
    """DSV 双源校验结果。"""

    gkv_result: Optional[GKVResult] = None
    """GKV 门控核验结果。"""

    cpe_result: Optional[CPEResult] = None
    """CPE 组合评估结果。"""

    sg_result: Optional[SGResult] = None
    """SG 信号生成结果。"""

    scl_result: Optional[SCLResult] = None
    """SCL 信号消费结果。"""

    # ── 执行元信息 ──

    errors: List[str] = field(default_factory=list)
    """执行过程中记录的错误列表。"""

    warnings: List[str] = field(default_factory=list)
    """执行过程中记录的警告列表。"""

    execution_time_ms: float = 0.0
    """单标的流水线总执行时间（毫秒）。"""

    def to_summary(self) -> Dict[str, Any]:
        """汇总为精简字典，便于日志输出和外部消费。

        Returns:
            精简字段的字典，不包含大型数据（如 DataFrame、numpy 数组）。
        """
        return {
            "ticker": self.ticker,
            "date": self.date,
            "status": self.status,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "dcm_status": self.dcm_result.status.value if self.dcm_result else None,
            "lqm_status": self.lqm_result.status.value if self.lqm_result else None,
            "znm_status": self.znm_result.status.value if self.znm_result else None,
            "rsm_state": self.rsm_state.current_state.value if self.rsm_state else None,
            "rsm_strength": round(self.rsm_strength, 4) if self.rsm_strength is not None else None,
            "dsv_passed": self.dsv_result.passed if hasattr(self.dsv_result, "passed") else None,
            "gkv_passed": self.gkv_result.passed if self.gkv_result else None,
            "cpe_score": round(self.cpe_result.score, 4) if self.cpe_result else None,
            "sg_signal": self.sg_result.signal_type if self.sg_result else None,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


# ══════════════════════════════════════════════════════════
# PipelineError — 流水线异常类型
# ══════════════════════════════════════════════════════════


class PipelineError(Exception):
    """流水线执行过程中的可恢复异常。"""

    pass


class PipelineFatalError(Exception):
    """流水线执行过程中的不可恢复异常。"""

    pass


# ══════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════


def _get_project_root() -> Path:
    """从模块位置向上查找项目根目录。"""
    module_dir = Path(__file__).resolve().parent  # src/resonance/
    for parent in [module_dir, *module_dir.parents]:
        if parent.name == "src" and (parent.parent / ".git").is_dir():
            return parent.parent
    return module_dir.parent.parent


_PROJECT_ROOT: Path = _get_project_root()


def _epoch_now() -> float:
    """当前时间戳（秒，浮点）。"""
    return time.time()


def _ts_cst() -> str:
    """当前 CST 时间戳，ISO8601 格式。"""
    return datetime.now(_CST_TZ).isoformat()


def _make_date_list(start_date: str, end_date: str, step_days: int = 1) -> List[str]:
    """生成从 start_date 到 end_date 的日期字符串列表。

    Args:
        start_date: 起始日期，YYYYMMDD。
        end_date:   结束日期，YYYYMMDD。
        step_days:  步进天数（默认 1）。

    Returns:
        [YYYYMMDD, ...] 格式的日期列表。
    """
    s = datetime.strptime(start_date, "%Y%m%d")
    e = datetime.strptime(end_date, "%Y%m%d")
    dates: List[str] = []
    cursor = s
    while cursor <= e:
        dates.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=step_days)
    return dates


def _result_cache_key(ticker: str, date: str) -> str:
    """生成幂等性缓存的键。"""
    return f"{ticker}_{date}"


# ══════════════════════════════════════════════════════════
# PipelineOrchestrator — 管线编排器
# ══════════════════════════════════════════════════════════


class PipelineOrchestrator:
    """共振系统流水线编排器。

    管理完整流水线的执行生命周期，包括：
      - 模块链式调用与前置状态检查
      - 结果聚合至 PipelineResult
      - 可选的信号文件持久化
      - 幂等性缓存（历史结果）
      - 可配置重试与超时

    流水线执行顺序：
      DataBridge → DCM → LQM → ZNM → RSM ∥ DSV → GKV → CPE → SG → SCL

    Args:
        config: PipelineConfig 配置（可选）。未提供则使用全默认值。
        verbose: 是否输出详细执行日志（默认 True）。
    """

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        verbose: bool = True,
    ):
        self._config: PipelineConfig = config or PipelineConfig(tickers=[])
        self._verbose = verbose
        self._history_cache: Dict[str, PipelineResult] = {}
        """幂等性缓存：_result_cache_key(ticker, date) → PipelineResult。"""
        self._lookback_buffer: LookbackBuffer = LookbackBuffer(replay_mode=False)
        """RSM 历史回看缓冲区，用于跨日状态机连续性。"""

        self._max_cache_size: int = 10000
        """幂等性缓存最大条目数（默认 10000，超出后逐出最早条目）。"""

        self._run_count: int = 0
        """流水线执行总次数（用于统计和调试）。"""

        self._last_run_timestamp: str = ""
        """最近一次 run_once/run_loop 的执行时间戳。"""

    # ══════════════════════════════════════════════════════
    # 属性
    # ══════════════════════════════════════════════════════

    @property
    def config(self) -> PipelineConfig:
        """当前配置（只读引用）。"""
        return self._config

    @property
    def run_count(self) -> int:
        """流水线执行总次数。"""
        return self._run_count

    @property
    def cached_results(self) -> int:
        """历史缓存的结果数量。"""
        return len(self._history_cache)

    # ══════════════════════════════════════════════════════
    # run_once — 单日执行
    # ══════════════════════════════════════════════════════

    def run_once(
        self,
        tickers: Optional[List[str]] = None,
        date: Optional[str] = None,
        *,
        persist_signals: bool = True,
        dry_run: bool = False,
        lookback_window: int = LOOKBACK_WINDOW,
        retry_times: int = 0,
        retry_delay: float = 1.0,
    ) -> Dict[str, PipelineResult]:
        """执行单日流水线。

        处理指定日期所有标的的完整流水线链路。
        在流水线执行前先查找幂等性缓存。

        Args:
            tickers:         标的列表。未提供时使用 config.tickers。
            date:            执行日期，YYYYMMDD 格式。未提供时使用当日日期。
            persist_signals: 是否持久化 SG 产生的信号文件（默认 True）。
            dry_run:         干运行模式，不写入信号文件和缓存（默认 False）。
            lookback_window: 滚动窗口大小覆盖（默认 LOOKBACK_WINDOW=20）。
            retry_times:     模块调用失败时的重试次数（默认 0）。
            retry_delay:     重试间隔秒数（默认 1.0）。

        Returns:
            {ticker: PipelineResult} 映射字典。

        Raises:
            PipelineFatalError: 参数校验失败或不可恢复错误。
        """
        # ── 参数解析 ──
        resolved_tickers = tickers or self._config.get("tickers", [])
        if not resolved_tickers:
            raise PipelineFatalError("tickers 列表为空，未提供标的")

        resolved_date = date or datetime.now(_CST_TZ).strftime("%Y%m%d")
        self._last_run_timestamp = _ts_cst()
        self._run_count += 1

        results: Dict[str, PipelineResult] = {}

        for ticker in resolved_tickers:
            # ── 幂等性检查 ──
            cache_key = _result_cache_key(ticker, resolved_date)
            if cache_key in self._history_cache and not dry_run:
                cached = self._history_cache[cache_key]
                if self._verbose:
                    logger.info("缓存命中 [%s %s] — 返回历史结果", ticker, resolved_date)
                results[ticker] = cached
                continue

            # ── 执行流水线 ──
            start = _epoch_now()
            result = self._run_pipeline_for_ticker(
                ticker=ticker,
                date=resolved_date,
                persist_signals=persist_signals,
                dry_run=dry_run,
                lookback_window=lookback_window,
                retry_times=retry_times,
                retry_delay=retry_delay,
            )
            result.execution_time_ms = (_epoch_now() - start) * 1000

            # ── 缓存写入（非 dry_run 时） ──
            if not dry_run:
                # 容量保护：超出上限时逐出最早条目
                if len(self._history_cache) >= self._max_cache_size:
                    oldest_key = next(iter(self._history_cache))
                    del self._history_cache[oldest_key]
                self._history_cache[cache_key] = result

            results[ticker] = result

            # ── 日志输出 ──
            summary = result.to_summary()
            logger.info(
                "[%s %s] status=%-8s sg=%-6s dcm=%-8s lqm=%-8s znm=%-8s rsm=%-8s gkv=%-6s cpe=%.3f time=%sms",
                ticker, resolved_date,
                result.status,
                summary.get("sg_signal", "N/A"),
                summary.get("dcm_status", "N/A"),
                summary.get("lqm_status", "N/A"),
                summary.get("znm_status", "N/A"),
                summary.get("rsm_state", "N/A"),
                summary.get("gkv_passed", "N/A"),
                summary.get("cpe_score", 0.0),
                round(result.execution_time_ms, 1),
            )

        return results

    # ══════════════════════════════════════════════════════
    # run_loop — 多日循环执行
    # ══════════════════════════════════════════════════════

    def run_loop(
        self,
        tickers: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        *,
        step_days: int = 1,
        max_dates: Optional[int] = None,
        persist_signals: bool = True,
        dry_run: bool = False,
        lookback_window: int = LOOKBACK_WINDOW,
        retry_times: int = 0,
        retry_delay: float = 1.0,
    ) -> Dict[str, List[PipelineResult]]:
        """执行多日流水线循环。

        在 [start_date, end_date] 日期范围内逐日（或按 step_days 步进）
        执行 run_once()。

        Args:
            tickers:         标的列表。未提供时使用 config.tickers。
            start_date:      起始日期，YYYYMMDD。未提供时使用 end_date - 5 日。
            end_date:        结束日期，YYYYMMDD。未提供时使用当日日期。
            step_days:       步进天数（默认 1，逐日执行）。
            persist_signals: 是否持久化信号文件。
            dry_run:         干运行模式。
            lookback_window: 滚动窗口大小覆盖。
            retry_times:     重试次数。
            retry_delay:     重试间隔。

        Returns:
            {ticker: [PipelineResult, ...]} 映射字典，按日期升序排列。
        """
        # ── 参数解析 ──
        now = datetime.now(_CST_TZ)
        resolved_end = end_date or now.strftime("%Y%m%d")
        resolved_start = start_date or (
            (now - timedelta(days=5)).strftime("%Y%m%d")
        )
        resolved_tickers = tickers or self._config.get("tickers", [])
        if not resolved_tickers:
            raise PipelineFatalError("tickers 列表为空，未提供标的")

        dates = _make_date_list(resolved_start, resolved_end, step_days)
        if max_dates is not None and len(dates) > max_dates:
            logger.warning(
                "run_loop: dates=%d exceeds max_dates=%d, truncating",
                len(dates), max_dates,
            )
            dates = dates[:max_dates]
        logger.info(
            "run_loop: %s ~ %s (step=%d, tickers=%s, n_dates=%d)",
            resolved_start, resolved_end, step_days,
            resolved_tickers, len(dates),
        )

        # ── 逐日执行 ──
        all_results: Dict[str, List[PipelineResult]] = {
            t: [] for t in resolved_tickers
        }

        for i, date in enumerate(dates):
            logger.info("run_loop 迭代 [%d/%d]: %s", i + 1, len(dates), date)
            day_results = self.run_once(
                tickers=resolved_tickers,
                date=date,
                persist_signals=persist_signals,
                dry_run=dry_run,
                lookback_window=lookback_window,
                retry_times=retry_times,
                retry_delay=retry_delay,
            )
            for ticker, result in day_results.items():
                all_results[ticker].append(result)

        return all_results

    # ══════════════════════════════════════════════════════
    # _run_pipeline_for_ticker — 单标的流水线执行
    # ══════════════════════════════════════════════════════

    def _run_pipeline_for_ticker(
        self,
        ticker: str,
        date: str,
        *,
        persist_signals: bool = True,
        dry_run: bool = False,
        lookback_window: int = LOOKBACK_WINDOW,
        retry_times: int = 0,
        retry_delay: float = 1.0,
    ) -> PipelineResult:
        """执行单标的完整流水线。

        内部按以下顺序执行各模块：
          DataBridge → DCM → LQM → ZNM → RSM ∥ DSV → GKV → CPE → SG → SCL

        Args:
            ticker:          标的代码。
            date:            执行日期。
            persist_signals: 是否持久化信号。
            dry_run:         干运行模式。
            lookback_window: 滚动窗口大小。
            retry_times:     重试次数。
            retry_delay:     重试间隔。

        Returns:
            填充完整的 PipelineResult。
        """
        result = PipelineResult(ticker=ticker, date=date)
        if self._verbose:
            logger.info("开始流水线 [%s %s]", ticker, date)

        # ── 计算历史数据起止范围 ──
        dt = datetime.strptime(date, "%Y%m%d")
        # 需要至少 lookback_window + buffer 天的历史数据
        need_history_days = lookback_window + 20  # 20 天缓冲
        start_dt = dt - timedelta(days=need_history_days)
        start_date = start_dt.strftime("%Y%m%d")

        # ── Step 1: DataBridge — 获取 OHLCV ──
        result.status = "RUNNING"
        try:
            df = self._execute_with_retry(
                "DataBridge", ticker,
                fetch_ohlcv,
                retry_times, retry_delay,
                start_date=start_date, end_date=date,
            )
            result.data_bridge_result = df
        except Exception as e:
            result.errors.append(f"DataBridge 失败: {e}")
            result.status = "FAILED"
            return result

        # ── 从 DataFrame 提取数据 ──
        close_prices: np.ndarray = df["close"].values.astype(np.float64)
        latest_close = close_prices[-1] if len(close_prices) > 0 else np.nan

        # ── Step 2: DCM — 波动率代理 ──
        try:
            dcm_res = self._execute_with_retry(
                "DCM", ticker,
                dcm_compute,
                retry_times, retry_delay,
                close_prices=close_prices,
                window=lookback_window,
            )
            result.dcm_result = dcm_res
        except Exception as e:
            result.errors.append(f"DCM 失败: {e}")

        # ── 检查 DCM 状态 ──
        if result.dcm_result is None or result.dcm_result.status == ModuleStatus.FAILED:
            result.errors.append("DCM FAILED，流水线提前终止")
            result.status = "FAILED"
            return result

        # ── Step 3: LQM — 流动性评价 ──
        try:
            lqm_res = self._execute_with_retry(
                "LQM", ticker,
                lqm_compute,
                retry_times, retry_delay,
                df=df,
                window=lookback_window,
            )
            result.lqm_result = lqm_res
        except Exception as e:
            result.errors.append(f"LQM 失败: {e}")

        # ── 检查 LQM 状态（非关键，仅记录警告） ──
        if result.lqm_result is None:
            result.warnings.append("LQM 结果为空，后续 DSV/GKV 将以降级模式运行")
        elif result.lqm_result.status == ModuleStatus.FAILED:
            result.warnings.append("LQM FAILED，后续 DSV 将使用单源降级模式")

        # ── Step 4: ZNM — z-score 归一化 ──
        try:
            hv_history = result.dcm_result.volatility_history
            if hv_history is None or len(hv_history) == 0:
                hv_history = np.array([], dtype=np.float64)

            znm_res = self._execute_with_retry(
                "ZNM", ticker,
                znm_compute,
                retry_times, retry_delay,
                values=hv_history,
                window=lookback_window,
            )
            result.znm_result = znm_res
        except Exception as e:
            result.errors.append(f"ZNM 失败: {e}")

        # ── 检查 ZNM 状态 ──
        if result.znm_result is None or result.znm_result.status == ModuleStatus.FAILED:
            result.errors.append("ZNM FAILED，流水线提前终止")
            result.status = "FAILED"
            return result

        # ── Step 5: RSM — 共振状态机 ──
        try:
            rsm_state = self._execute_with_retry(
                "RSM", ticker,
                rsm_compute,
                retry_times, retry_delay,
                znm_result=result.znm_result,
                lookback_buffer=self._lookback_buffer,
            )
            result.rsm_state = rsm_state
            # 计算共振强度（用于 CPE 和 GKV）
            result.rsm_strength = rsm_compute_strength(result.znm_result.zscore)
        except Exception as e:
            result.errors.append(f"RSM 失败: {e}")

        # ── Step 6: DSV — 双源校验 ∥ RSM（依赖 ZNM + LQM，与 RSM 并行逻辑） ──
        try:
            vol_zscore_series = result.znm_result.normalized_values

            dsv_res = self._execute_with_retry(
                "DSV", ticker,
                dsv_compute,
                retry_times, retry_delay,
                vol_zscore_series=vol_zscore_series,
                lqm_result=result.lqm_result,
                window=lookback_window,
            )
            result.dsv_result = dsv_res
        except Exception as e:
            result.errors.append(f"DSV 失败: {e}")
            # DSV 失败不阻断流水线，GKV/CPE 以降级模式处理

        # ── 检查关键模块状态：RSM/DSV 失败时降级 ──
        rsm_available = result.rsm_state is not None
        dsv_available = (
            result.dsv_result is not None
            and hasattr(result.dsv_result, "status")
            and result.dsv_result.status == ModuleStatus.PASS
        )

        if not rsm_available and not dsv_available:
            result.errors.append("RSM 和 DSV 均不可用，无法完成 GKV/CPE 评估")
            result.status = "FAILED"
            return result

        # ── Step 7: GKV — 门控核验 ──
        rsm_state_val: Optional[RSMState] = (
            result.rsm_state.current_state if result.rsm_state else None
        )
        dsv_score: Optional[float] = (
            getattr(result.dsv_result, "score", None) if result.dsv_result else None
        )
        lqm_for_gkv: Optional[LQMResult] = (
            result.lqm_result
            if result.lqm_result and result.lqm_result.status == ModuleStatus.PASS
            else None
        )
        signal_strength: Optional[float] = result.rsm_strength

        try:
            gkv_res = self._execute_with_retry(
                "GKV", ticker,
                gkv_compute,
                retry_times, retry_delay,
                rsm_state=rsm_state_val,
                dsv_score=dsv_score,
                lqm_result=lqm_for_gkv,
                signal_strength=signal_strength,
            )
            result.gkv_result = gkv_res
        except Exception as e:
            result.errors.append(f"GKV 失败: {e}")

        # ── Step 8: CPE — 组合评估 ──
        liquidity_score: Optional[float] = (
            result.lqm_result.liquidity_score
            if result.lqm_result and result.lqm_result.status == ModuleStatus.PASS
            else None
        )
        dsv_passed: bool = (
            getattr(result.dsv_result, "passed", False) if result.dsv_result else True
        )
        dsv_partial: bool = (
            getattr(result.dsv_result, "partial", False) if result.dsv_result else False
        )

        try:
            cpe_res = self._execute_with_retry(
                "CPE", ticker,
                cpe_compute,
                retry_times, retry_delay,
                rsm_strength=result.rsm_strength,
                dsv_score=dsv_score,
                liquidity_score=liquidity_score,
                dsv_passed=dsv_passed,
                dsv_partial=dsv_partial,
            )
            result.cpe_result = cpe_res
        except Exception as e:
            result.errors.append(f"CPE 失败: {e}")

        # ── Step 9: SG — 信号生成 ──
        if result.gkv_result and result.cpe_result:
            try:
                sg_res = self._execute_with_retry(
                    "SG", ticker,
                    sg_generate,
                    retry_times, retry_delay,
                    cpe_result=result.cpe_result,
                    gkv_result=result.gkv_result,
                )
                result.sg_result = sg_res
            except Exception as e:
                result.errors.append(f"SG 失败: {e}")

        # ── Step 10: SCL — 信号消费 ──
        if result.sg_result and result.sg_result.status == ModuleStatus.PASS:
            try:
                # 构造 ResonanceSignal
                rsm_state_str = (
                    result.rsm_state.current_state.value
                    if result.rsm_state else RSMState.NONE.value
                )
                signal = ResonanceSignal(
                    signal_type=result.sg_result.signal_type,
                    strength=result.cpe_result.score if result.cpe_result else 0.0,
                    position_cap=result.cpe_result.position_cap if result.cpe_result else 1.0,
                    reason=result.sg_result.reason,
                    timestamp=_ts_cst(),
                    state=RSMState(rsm_state_str),
                    source_module="SG",
                    confidence=result.cpe_result.score if result.cpe_result else 0.0,
                    symbol=ticker,
                    suggested_price=float(latest_close),
                )

                scl_res = self._execute_with_retry(
                    "SCL", ticker,
                    scl_consume,
                    retry_times, retry_delay,
                    signals=[signal],
                    persist=persist_signals and not dry_run,
                )
                result.scl_result = scl_res
            except Exception as e:
                result.errors.append(f"SCL 失败: {e}")

        # ── 最终状态判定 ──
        result.status = self._determine_overall_status(result)

        if self._verbose:
            status_summary = result.to_summary()
            logger.info(
                "流水线完成 [%s %s] status=%s sg=%s cpe_score=%.3f errors=%d",
                ticker, date,
                result.status,
                status_summary.get("sg_signal", "N/A"),
                status_summary.get("cpe_score", 0.0),
                len(result.errors),
            )

        return result

    # ══════════════════════════════════════════════════════
    # 辅助方法
    # ══════════════════════════════════════════════════════

    def _execute_with_retry(
        self,
        module_name: str,
        ticker: str,
        func: Callable,
        retry_times: int,
        retry_delay: float,
        **kwargs,
    ) -> Any:
        """带重试机制的模块调用包装。

        Args:
            module_name: 模块名称（用于日志）。
            ticker:      标的代码。
            func:        模块函数。
            retry_times: 重试次数。
            retry_delay: 重试间隔秒数。
            **kwargs:    传递给 func 的参数。

        Returns:
            func 的返回值。

        Raises:
            最后一次尝试的异常（所有重试耗尽后）。
        """
        last_exception: Optional[Exception] = None

        for attempt in range(1 + max(0, retry_times)):
            try:
                # ticker 由 _execute_with_retry 的 positional 参数代为传递到 func，
                # 避免调用方重复传入 ticker=ticker 导致多次传参冲突
                return func(ticker=ticker, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < retry_times:
                    logger.warning(
                        "%s [%s] 尝试 %d/%d 失败: %s，%.1fs 后重试",
                        module_name, ticker,
                        attempt + 1, retry_times + 1,
                        e, retry_delay,
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(
                        "%s [%s] 所有尝试均失败: %s",
                        module_name, ticker, e,
                    )

        if last_exception is not None:
            raise last_exception  # type: ignore[misc]

        return None  # 不应到达此处

    @staticmethod
    def _determine_overall_status(result: PipelineResult) -> str:
        """根据各模块状态确定流水线整体状态。

        判定逻辑：
          - 没有任何模块成功执行 → FAILED
          - 全部模块 PASS → PASS
          - SG 成功生成信号 → PASS（核心产出优先）
          - 部分模块失败但 SG 成功 → PARTIAL
          - 关键模块失败且无 SG 产出 → FAILED

        Args:
            result: 填充中的 PipelineResult。

        Returns:
            "PASS" | "PARTIAL" | "FAILED" | "SKIPPED"。
        """
        # 检查是否有任何模块成功（DataBridge 成功是最低要求）
        if result.data_bridge_result is None:
            return "FAILED"

        # SG 成功生成信号 → 核心产出正常
        if result.sg_result and result.sg_result.status == ModuleStatus.PASS:
            if len(result.errors) == 0:
                return "PASS"
            return "PARTIAL"

        # 无 SG 但有错误 → FAILED
        if result.errors:
            return "FAILED"

        # 无错误、无 SG（可能被跳过）、核心模块正常
        return "SKIPPED"

    def clear_cache(self) -> int:
        """清除幂等性缓存。

        Returns:
            清除的缓存条目数。
        """
        count = len(self._history_cache)
        self._history_cache.clear()
        return count

    def get_cached_result(self, ticker: str, date: str) -> Optional[PipelineResult]:
        """获取幂等性缓存中的历史结果。

        Args:
            ticker: 标的代码。
            date:   日期，YYYYMMDD。

        Returns:
            缓存的结果，若不存在则返回 None。
        """
        return self._history_cache.get(_result_cache_key(ticker, date))


# ══════════════════════════════════════════════════════════
# 快捷入口函数
# ══════════════════════════════════════════════════════════


def run_pipeline(
    tickers: List[str],
    date: Optional[str] = None,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    step_days: int = 1,
    persist_signals: bool = True,
    dry_run: bool = False,
    verbose: bool = True,
    retry_times: int = 0,
    retry_delay: float = 1.0,
) -> Dict[str, Any]:
    """PipelineOrchestrator 快捷入口函数。

    单次执行：
        >>> from src.resonance.pipeline import run_pipeline
        >>> result = run_pipeline(tickers=["601857.SH"], date="20260529")

    多日循环：
        >>> result = run_pipeline(
        ...     tickers=["601857.SH"],
        ...     start_date="20260520",
        ...     end_date="20260529",
        ... )

    Args:
        tickers:         标的代码列表。
        date:            单次执行日期（省略时使用当日）。
        start_date:      循环执行起始日期（省略时使用 end_date - 5）。
        end_date:        循环执行结束日期（省略时使用当日）。
        step_days:       循环步进天数（默认 1）。
        persist_signals: 是否持久化信号文件（默认 True）。
        dry_run:         干运行模式（默认 False）。
        verbose:         详细日志（默认 True）。
        retry_times:     模块重试次数（默认 1）。
        retry_delay:     重试间隔秒数（默认 1.0）。

    Returns:
        - 单次执行：{ticker: PipelineResult.to_summary()}
        - 循环执行：{ticker: [PipelineResult.to_summary(), ...]}
    """
    orch = PipelineOrchestrator(verbose=verbose)

    if date:
        # run_once 模式
        results = orch.run_once(
            tickers=tickers,
            date=date,
            persist_signals=persist_signals,
            dry_run=dry_run,
            retry_times=retry_times,
            retry_delay=retry_delay,
        )
        return {
            ticker: r.to_summary()
            for ticker, r in results.items()
        }
    else:
        # run_loop 模式
        results = orch.run_loop(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            step_days=step_days,
            persist_signals=persist_signals,
            dry_run=dry_run,
            retry_times=retry_times,
            retry_delay=retry_delay,
        )
        return {
            ticker: [r.to_summary() for r in results[ticker]]
            for ticker in results
        }


# ══════════════════════════════════════════════════════════
# 模块引用清单（供工具/文档生成使用）
# ══════════════════════════════════════════════════════════

PIPELINE_MODULES: Dict[str, str] = {
    "DataBridge": "src.resonance.data_bridge.fetch_ohlcv",
    "DCM": "src.resonance.dcm.compute",
    "LQM": "src.resonance.lqm.compute",
    "ZNM": "src.resonance.znm.compute",
    "RSM": "src.resonance.rsm.compute",
    "DSV": "src.resonance.dsv.compute",
    "GKV": "src.resonance.gkv.compute",
    "CPE": "src.resonance.cpe.compute",
    "SG": "src.resonance.sg.generate",
    "SCL": "src.resonance.scl.consume",
}

__all__ = [
    "PipelineOrchestrator",
    "PipelineResult",
    "PipelineError",
    "PipelineFatalError",
    "run_pipeline",
    "PIPELINE_MODULES",
]
