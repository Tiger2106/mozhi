"""
P0.4 — Resonance module shared test fixtures.

All resonance unit tests import fixtures from this conftest.
Author: 墨衡
Created: 2026-05-29
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# resonance 模块导入
# ---------------------------------------------------------------------------
from src.resonance.constants import (
    ANNUALIZATION_FACTOR,
    FULL_PASS_CAP,
    LOOKBACK_WINDOW,
    MAX_FILL_FORWARD,
    QUANTILE_THRESHOLD,
    RSM_STATE_ACTIVE,
    RSM_STATE_DECAY,
    RSM_STATE_NONE,
    RSM_STATE_WARN,
)
from src.resonance.dsv import DSVResult
from src.resonance.lookback_buffer import LookbackBuffer
from src.resonance.models import (
    CPEResult,
    DCMResult,
    GKVResult,
    LookbackData,
    LQMResult,
    ModuleStatus,
    ResonanceSignal,
    RSMPipelineState,
    RSMState,
    SGResult,
    SignalHistoryEntry,
    ZNMResult,
)
from src.resonance.pipeline import PipelineOrchestrator, PipelineConfig


# ===================================================================
# 基础数据 fixtures
# ===================================================================


@pytest.fixture(scope="session")
def signal_seed() -> int:
    """确定性随机种子，确保所有依赖随机性的测试可复现。"""
    return 42


@pytest.fixture(scope="session")
def ticker() -> str:
    """默认测试标的代码。"""
    return "TEST0001"


@pytest.fixture(scope="session")
def n_bars() -> int:
    """模拟 OHLCV 数据条数（50 个交易日 ≈ 2.5 个月）。"""
    return 50


@pytest.fixture(scope="session")
def sample_ohlcv_df(ticker: str, n_bars: int, signal_seed: int) -> pd.DataFrame:
    """
    标准模拟 OHLCV DataFrame。

    结构：100 → 110 稳步上涨，日内波动合理，随机种子固定。
    columns: date, trade_date, open, high, low, close, volume, amount, code
    """
    rng = np.random.default_rng(signal_seed)

    base = 100.0 * np.cumprod(1.0 + rng.normal(0.002, 0.015, n_bars))
    close = np.round(base, 2)

    open_prices = np.round(close * (1.0 + rng.uniform(-0.005, 0.005, n_bars)), 2)
    high = np.round(
        np.maximum(open_prices, close) * (1.0 + rng.uniform(0.0, 0.01, n_bars)), 2
    )
    low = np.round(
        np.minimum(open_prices, close) * (1.0 - rng.uniform(0.0, 0.01, n_bars)), 2
    )
    volume = rng.integers(1_000_000, 10_000_000, n_bars)

    dates = pd.bdate_range("2025-01-01", periods=n_bars, freq="B")

    df = pd.DataFrame(
        {
            "date": dates,
            "trade_date": dates,
            "open": open_prices,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
            "code": [ticker] * n_bars,
        }
    )
    df.set_index("date", inplace=True)
    df.index.name = "date"
    return df


@pytest.fixture
def sample_close_prices(sample_ohlcv_df: pd.DataFrame) -> np.ndarray:
    """从 sample_ohlcv_df 提取 close 列。"""
    return sample_ohlcv_df["close"].to_numpy(dtype=np.float64)


@pytest.fixture
def sample_returns(sample_close_prices: np.ndarray) -> np.ndarray:
    """从 close 价格计算对数收益率。"""
    return np.diff(np.log(sample_close_prices))


# ===================================================================
# 已知 HV 序列 fixtures（DCM / ZNM 测试用）
# ===================================================================


@pytest.fixture(scope="session")
def known_hv_series(signal_seed: int) -> np.ndarray:
    """
    预计算已知历史波动率序列（100 点）。

    特性（seed=42）：
      - bar 0-49: ~0.12（低波动期）
      - bar 50-99: ~0.35（高波动期）
      - 阶跃结构便于 z-score 突变检验
    """
    rng = np.random.default_rng(signal_seed)
    low_vol = 0.12 * np.ones(50) + rng.normal(0, 0.01, 50)
    high_vol = 0.35 * np.ones(50) + rng.normal(0, 0.02, 50)
    series = np.concatenate([low_vol, high_vol])
    np.clip(series, 0.02, None, out=series)
    return series


@pytest.fixture(scope="session")
def known_hv_series_short() -> np.ndarray:
    """短 HV 序列（25 点），用于测试 ZNM min_history 边界条件。"""
    return np.array(
        [
            0.10, 0.11, 0.09, 0.12, 0.11,
            0.10, 0.13, 0.10, 0.11, 0.12,
            0.11, 0.10, 0.12, 0.11, 0.10,
            0.13, 0.12, 0.11, 0.12, 0.11,
            0.10, 0.11, 0.12, 0.11, 0.10,
        ],
        dtype=np.float64,
    )


@pytest.fixture(scope="session")
def known_hv_series_vol_ramp(signal_seed: int) -> np.ndarray:
    """HV 序列：波动率从 0.05 线性递增到 0.50（80 点）。"""
    rng = np.random.default_rng(signal_seed + 1)
    n = 80
    ramp = np.linspace(0.05, 0.50, n)
    noise = rng.normal(0, 0.005, n)
    series = ramp + noise
    np.clip(series, 0.02, None, out=series)
    return series


# ===================================================================
# DataBridge mock fixture
# ===================================================================


@pytest.fixture
def mock_data_bridge(sample_ohlcv_df: pd.DataFrame) -> MagicMock:
    """
    模拟 DataBridge（实际为 src.resonance.data_bridge 模块级函数）。

    返回 MagicMock 对象，提供 fetch_ohlcv / fetch_realtime_quote / health_check
    方法。各测试可通过 .return_value / .side_effect 定制行为。
    """
    mock = MagicMock()
    mock.fetch_ohlcv.return_value = sample_ohlcv_df.copy()
    mock.fetch_realtime_quote.return_value = {
        "ticker": "TEST0001",
        "price": 105.50,
        "change_pct": 0.35,
        "volume": 5_000_000,
        "timestamp": "2025-03-01 10:00:00",
    }
    mock.health_check.return_value = True
    return mock


# ===================================================================
# LookbackBuffer fixtures
# ===================================================================


@pytest.fixture
def lb_dir() -> Path:
    """
    每个测试独立的临时目录，用于隔离 LookbackBuffer 持久化文件。

    注意：LookbackBuffer 硬编码了 LB_PERSIST_PATH 作为持久化路径，
    因此此目录主要用于手动文件操作测试。单元测试中通常直接
    使用内存操作（load(None) / replay_mode）。
    """
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def lookback_buffer() -> LookbackBuffer:
    """
    全新 LookbackBuffer 实例（无预存数据）。

    replay_mode=False，可以进行读写操作。
    对于需要空状态的测试，直接使用此 fixture 并调用 load(ticker)
    会返回 None（无文件）。
    """
    return LookbackBuffer(replay_mode=False)


@pytest.fixture
def lookback_buffer_with_data(ticker: str) -> LookbackBuffer:
    """
    预填充历史数据的 LookbackBuffer。

    使用 save/load 正向流程，包含已写入的 LookbackData。
    测试结束后调用 clear() 清理。
    """
    buf = LookbackBuffer(replay_mode=False)

    # 构造 10 日有序历史数据
    history: List[Tuple[str, float]] = []
    for i in range(10):
        day = f"202502{20 + i:02d}"
        value = 0.15 + 0.05 * i
        history.append((day, value))

    data = LookbackData(
        history=history,
        resonance_state=RSMState.ACTIVE,
        window_stats={
            "mean": 0.35,
            "std": 0.12,
            "min": 0.15,
            "max": 0.60,
            "zscore": 1.8,
            "latest_qq": 0.90,
        },
        last_update="20250301",
        ticker=ticker,
    )
    buf.save(ticker, data)

    yield buf

    buf.clear(ticker)


# ===================================================================
# DCM 结果 fixtures
# ===================================================================


@pytest.fixture
def dcm_result_pass() -> DCMResult:
    """标准 PASS 状态 DCMResult。"""
    return DCMResult(
        volatility=0.18,
        volatility_history=np.full(LOOKBACK_WINDOW, 0.18, dtype=np.float64),
        status=ModuleStatus.PASS,
    )


@pytest.fixture
def dcm_result_high_vol() -> DCMResult:
    """高波动 PASS 状态。"""
    return DCMResult(
        volatility=0.35,
        volatility_history=np.full(LOOKBACK_WINDOW, 0.35, dtype=np.float64),
        status=ModuleStatus.PASS,
    )


@pytest.fixture
def dcm_result_failed() -> DCMResult:
    """FAILED 状态（数据不足）。"""
    return DCMResult(
        volatility=0.0,
        volatility_history=np.array([], dtype=np.float64),
        status=ModuleStatus.FAILED,
    )


# ===================================================================
# ZNM 结果 fixtures
# ===================================================================


@pytest.fixture
def znm_result_pass() -> ZNMResult:
    """标准 PASS（z-score=1.2，未超阈值）。"""
    return ZNMResult(
        zscore=1.2,
        is_extreme=False,
        normalized_values=np.array([-0.5, 0.0, 0.8, 1.2], dtype=np.float64),
        status=ModuleStatus.PASS,
    )


@pytest.fixture
def znm_result_extreme_bull() -> ZNMResult:
    """极端偏多（zscore=3.5 >> QUANTILE_THRESHOLD）。"""
    return ZNMResult(
        zscore=3.5,
        is_extreme=True,
        normalized_values=np.array([0.5, 1.2, 2.8, 3.5], dtype=np.float64),
        status=ModuleStatus.PASS,
    )


@pytest.fixture
def znm_result_extreme_bear() -> ZNMResult:
    """极端偏空（zscore=-3.2 << -QUANTILE_THRESHOLD）。"""
    return ZNMResult(
        zscore=-3.2,
        is_extreme=True,
        normalized_values=np.array([-0.5, -1.8, -2.5, -3.2], dtype=np.float64),
        status=ModuleStatus.PASS,
    )


@pytest.fixture
def znm_result_failed() -> ZNMResult:
    """FAILED 状态。"""
    return ZNMResult(
        zscore=0.0,
        is_extreme=False,
        normalized_values=np.array([], dtype=np.float64),
        status=ModuleStatus.FAILED,
    )


# ===================================================================
# LQM 结果 fixtures
# ===================================================================


@pytest.fixture
def lqm_result_pass() -> LQMResult:
    """标准 PASS（流动性良好，liquidity_score=0.75）。"""
    return LQMResult(
        amplitude=1.8,
        volume_ratio=1.2,
        turnover_rate=1.5,
        liquidity_score=0.75,
        status=ModuleStatus.PASS,
    )


@pytest.fixture
def lqm_result_low_liq() -> LQMResult:
    """低流动性（liquidity_score=0.25 < LIQUIDITY_MIN_THRESHOLD）。"""
    return LQMResult(
        amplitude=0.5,
        volume_ratio=0.3,
        turnover_rate=0.2,
        liquidity_score=0.25,
        status=ModuleStatus.PASS,
    )


@pytest.fixture
def lqm_result_failed() -> LQMResult:
    """FAILED 状态。"""
    return LQMResult(
        amplitude=0.0,
        volume_ratio=0.0,
        turnover_rate=0.0,
        liquidity_score=0.0,
        status=ModuleStatus.FAILED,
    )


# ===================================================================
# DSV 结果 fixtures（dsv 模块独立定义）
# ===================================================================


@pytest.fixture
def dsv_result_pass() -> DSVResult:
    """标准通过：双源验证强一致。"""
    return DSVResult(
        passed=True,
        partial=False,
        score=0.85,
        vol_consistency=0.82,
        liquidity_consistency=0.78,
        method="dsv_standard",
        status=ModuleStatus.PASS,
        reason="双源验证强一致",
    )


@pytest.fixture
def dsv_result_partial() -> DSVResult:
    """部分通过：仅波动率一致，流动性端存在分歧。"""
    return DSVResult(
        passed=False,
        partial=True,
        score=0.55,
        vol_consistency=0.60,
        liquidity_consistency=0.40,
        method="dsv_standard",
        status=ModuleStatus.PASS,
        reason="仅波动率一致，流动性端存在分歧",
    )


@pytest.fixture
def dsv_result_failed() -> DSVResult:
    """FAILED：输入数据不完整。"""
    return DSVResult(
        passed=False,
        partial=False,
        score=0.0,
        vol_consistency=0.0,
        liquidity_consistency=0.0,
        method="",
        status=ModuleStatus.FAILED,
        reason="输入数据不完整",
    )


# ===================================================================
# RSM 状态 fixtures
# ===================================================================


@pytest.fixture
def rsm_state_none() -> RSMState:
    return RSMState.NONE


@pytest.fixture
def rsm_state_warn() -> RSMState:
    return RSMState.WARN


@pytest.fixture
def rsm_state_active() -> RSMState:
    return RSMState.ACTIVE


@pytest.fixture
def rsm_state_decay() -> RSMState:
    return RSMState.DECAY


@pytest.fixture
def rsm_pipeline_state_active(ticker: str) -> RSMPipelineState:
    """活跃共振的 RSMPipelineState。"""
    return RSMPipelineState(
        current_state=RSMState.ACTIVE,
        warn_consecutive_strength=5,
        warn_total_days=7,
        consecutive_decay_days=0,
        run_count=10,
        last_signal_date="20250301",
        history=[],
    )


@pytest.fixture
def rsm_pipeline_state_warn(ticker: str) -> RSMPipelineState:
    """WARN 状态的 RSMPipelineState。"""
    return RSMPipelineState(
        current_state=RSMState.WARN,
        warn_consecutive_strength=2,
        warn_total_days=3,
        consecutive_decay_days=0,
        run_count=5,
        last_signal_date="20250225",
        history=[],
    )


@pytest.fixture
def rsm_pipeline_state_none(ticker: str) -> RSMPipelineState:
    """无共振的 RSMPipelineState。"""
    return RSMPipelineState(
        current_state=RSMState.NONE,
        warn_consecutive_strength=0,
        warn_total_days=0,
        consecutive_decay_days=0,
        run_count=3,
        last_signal_date="20250201",
        history=[],
    )


# ===================================================================
# GKV 结果 fixtures
# ===================================================================


@pytest.fixture
def gkv_result_pass() -> GKVResult:
    """三闸门全开，信号放行。"""
    return GKVResult(
        gated=False,
        passed=True,
        reason="三闸门全部开放",
        status=ModuleStatus.PASS,
        gate_open=True,
        rsm_state_ok=True,
        dsv_consistency_ok=True,
        liquidity_ok=True,
        rsm_state_value=RSM_STATE_ACTIVE,
        dsv_score=0.85,
        liquidity_score=0.78,
        signal_strength=0.75,
    )


@pytest.fixture
def gkv_result_gated() -> GKVResult:
    """闸门封锁（流动性不足）。"""
    return GKVResult(
        gated=True,
        passed=False,
        reason="流动性评分不足",
        status=ModuleStatus.PASS,
        gate_open=False,
        rsm_state_ok=True,
        dsv_consistency_ok=True,
        liquidity_ok=False,
        rsm_state_value=RSM_STATE_WARN,
        dsv_score=0.80,
        liquidity_score=0.30,
        signal_strength=0.60,
    )


@pytest.fixture
def gkv_result_skipped() -> GKVResult:
    """SKIPPED（前置模块未执行）。"""
    return GKVResult(
        gated=True,
        passed=False,
        reason="前置模块未执行",
        status=ModuleStatus.SKIPPED,
        gate_open=False,
        rsm_state_ok=False,
        dsv_consistency_ok=False,
        liquidity_ok=False,
        rsm_state_value=RSM_STATE_NONE,
        dsv_score=0.0,
        liquidity_score=0.0,
        signal_strength=0.0,
    )


# ===================================================================
# CPE 结果 fixtures
# ===================================================================


@pytest.fixture
def cpe_result_pass() -> CPEResult:
    """FULL_PASS：综合评分良好，仓位上限 1.0。"""
    return CPEResult(
        score=0.75,
        rsm_weight=0.5,
        dsv_weight=0.3,
        liq_weight=0.2,
        continuous_days=6,
        conditional_pass=False,
        days_remaining=-1,
        status=ModuleStatus.PASS,
        position_cap=FULL_PASS_CAP,
        reason="综合评分良好，共振强度达标+DSV一致+流动性充足",
    )


@pytest.fixture
def cpe_result_conditional() -> CPEResult:
    """CONDITIONAL_PASS：连续 5 日达标，仓位上限 0.5。"""
    return CPEResult(
        score=0.65,
        rsm_weight=0.5,
        dsv_weight=0.3,
        liq_weight=0.2,
        continuous_days=5,
        conditional_pass=True,
        days_remaining=0,
        status=ModuleStatus.CONDITIONAL_PASS,
        position_cap=0.5,
        reason="连续5日共振达标+DSV通过→条件放行",
    )


@pytest.fixture
def cpe_result_low_score() -> CPEResult:
    """低评分：评分不足，不建议交易。"""
    return CPEResult(
        score=0.30,
        rsm_weight=0.5,
        dsv_weight=0.3,
        liq_weight=0.2,
        continuous_days=1,
        conditional_pass=False,
        days_remaining=4,
        status=ModuleStatus.PASS,
        position_cap=FULL_PASS_CAP,
        reason="共振强度不足，综合评分偏低",
    )


@pytest.fixture
def cpe_result_failed() -> CPEResult:
    """FAILED：前置模块输入异常。"""
    return CPEResult(
        score=0.0,
        rsm_weight=0.5,
        dsv_weight=0.3,
        liq_weight=0.2,
        continuous_days=0,
        conditional_pass=False,
        days_remaining=5,
        status=ModuleStatus.FAILED,
        position_cap=FULL_PASS_CAP,
        reason="前置模块输入异常",
    )


# ===================================================================
# SG 结果 fixtures
# ===================================================================


@pytest.fixture
def sg_result_buy(ticker: str) -> SGResult:
    """BUY / STRONG。"""
    return SGResult(
        signal_type="BUY",
        signal_strength="STRONG",
        score=0.82,
        status=ModuleStatus.PASS,
        ticker=ticker,
        reason="DCM+ZNM 看多，CPE 评分偏多，GKV 门控开放",
    )


@pytest.fixture
def sg_result_hold(ticker: str) -> SGResult:
    """HOLD / WEAK。"""
    return SGResult(
        signal_type="HOLD",
        signal_strength="WEAK",
        score=0.35,
        status=ModuleStatus.PASS,
        ticker=ticker,
        reason="CPE 评分不足 + GKV 闸门封锁",
    )


@pytest.fixture
def sg_result_sell(ticker: str) -> SGResult:
    """SELL / MEDIUM。"""
    return SGResult(
        signal_type="SELL",
        signal_strength="MEDIUM",
        score=0.65,
        status=ModuleStatus.PASS,
        ticker=ticker,
        reason="ZNM 极端偏空 + DSV 一致性恶化",
    )


@pytest.fixture
def sg_result_failed(ticker: str) -> SGResult:
    """FAILED。"""
    return SGResult(
        signal_type="HOLD",
        signal_strength="NONE",
        score=0.0,
        status=ModuleStatus.FAILED,
        ticker=ticker,
        reason="前置模块全部 FAILED",
    )


# ===================================================================
# ResonanaceSignal TypedDict fixtures（SCL 测试用）
# ===================================================================


@pytest.fixture
def resonance_signal_buy(ticker: str) -> ResonanceSignal:
    return ResonanceSignal(
        signal_type="BUY",
        strength=0.80,
        position_cap=FULL_PASS_CAP,
        reason="多模块共振一致看多",
        timestamp="2025-03-01T10:00:00+08:00",
        state=RSMState.ACTIVE,
        source_module="SG",
        confidence=0.85,
        symbol=ticker,
        suggested_price=105.50,
    )


@pytest.fixture
def resonance_signal_hold(ticker: str) -> ResonanceSignal:
    return ResonanceSignal(
        signal_type="HOLD",
        strength=0.30,
        position_cap=FULL_PASS_CAP,
        reason="各指标指向不一致",
        timestamp="2025-03-01T10:00:00+08:00",
        state=RSMState.NONE,
        source_module="SG",
        confidence=0.40,
        symbol=ticker,
        suggested_price=102.00,
    )


@pytest.fixture
def resonance_signal_conditional(ticker: str) -> ResonanceSignal:
    return ResonanceSignal(
        signal_type="CONDITIONAL_BUY",
        strength=0.65,
        position_cap=0.5,
        reason="连续共振达标，条件放行",
        timestamp="2025-03-01T10:00:00+08:00",
        state=RSMState.ACTIVE,
        source_module="CPE",
        confidence=0.70,
        symbol=ticker,
        suggested_price=104.00,
    )


# ===================================================================
# SCL signals list fixture
# ===================================================================


@pytest.fixture
def signal_list_buy_hold(
    resonance_signal_buy: ResonanceSignal,
    resonance_signal_hold: ResonanceSignal,
) -> List[ResonanceSignal]:
    """包含 BUY + HOLD 的信号列表（SCL consume 测试用）。"""
    return [resonance_signal_buy, resonance_signal_hold]


# ===================================================================
# Pipeline fixtures
# ===================================================================


@pytest.fixture
def pipeline_config(ticker: str) -> PipelineConfig:
    """标准 PipelineConfig。"""
    return PipelineConfig(
        tickers=[ticker],
        start_date="20250101",
        end_date="20250301",
        data_bridge="mock",
        lookback_window=LOOKBACK_WINDOW,
        output_dir="signals/resonance",
        dry_run=True,
        verbose=False,
        partial=False,
    )


@pytest.fixture
def pipeline_orchestrator(pipeline_config: PipelineConfig) -> PipelineOrchestrator:
    """PipelineOrchestrator 实例。"""
    return PipelineOrchestrator(config=pipeline_config, verbose=False)


# ===================================================================
# 辅助 fixture：全流程输入集合
# ===================================================================


@pytest.fixture
def full_pipeline_inputs(
    dcm_result_pass: DCMResult,
    lqm_result_pass: LQMResult,
    znm_result_pass: ZNMResult,
    dsv_result_pass: DSVResult,
    rsm_pipeline_state_active: RSMPipelineState,
    gkv_result_pass: GKVResult,
    cpe_result_pass: CPEResult,
) -> Dict[str, Any]:
    """所有模块结果的集合字典，供集成测试使用。"""
    return {
        "dcm": dcm_result_pass,
        "lqm": lqm_result_pass,
        "znm": znm_result_pass,
        "dsv": dsv_result_pass,
        "rsm": rsm_pipeline_state_active,
        "gkv": gkv_result_pass,
        "cpe": cpe_result_pass,
    }
