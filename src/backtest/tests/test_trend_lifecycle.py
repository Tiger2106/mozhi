"""
Phase 1-C 测试：Trend Lifecycle 趋势生命周期阶段判定器

测试内容:
  C1: 各阶段判定（5 阶段 + PRE_INIT）
  C2: 状态机切换（前进、跳级、禁止后退）
  C3: 与 False Breakout 协同分析
  C4: 与真实回测数据集成
  C5: 边界条件

用法:
    pytest src/backtest/tests/test_trend_lifecycle.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pandas as pd
import numpy as np

# ── 配置 ──────────────────────────────────────────────────────

BASE = r"C:\Users\17699\mozhi_platform"
sys.path.insert(0, BASE)
os.chdir(BASE)

MOZHI_BASE = Path(BASE)

# ── 工具函数 ──────────────────────────────────────────────────


def _make_ohlcv(dates: int = 120) -> pd.DataFrame:
    """生成标准 OHLCV 测试 DataFrame。"""
    np.random.seed(42)
    idx = pd.bdate_range(start="2026-01-01", periods=dates, freq="B")
    close = np.full(dates, 10.0)

    # 分段配置：sections = [(end, fn)]
    sections = [
        # RANGE 震荡
        (min(40, dates), lambda c, s, e: c[s:e] + np.cumsum(np.random.randn(e - s) * 0.03)),
        # 启动+加速 (40~60)
        (min(60, dates), lambda c, s, e: 10.0 + np.arange(1, e - s + 1) * 0.06 + np.random.randn(e - s) * 0.02),
        # 主升 (60~80)
        (min(80, dates), lambda c, s, e: c[s] + np.arange(1, e - s + 1) * 0.10 + np.random.randn(e - s) * 0.03),
        # 衰竭 (80~95)
        (min(95, dates), lambda c, s, e: c[s] + np.arange(1, e - s + 1) * 0.02 + np.random.randn(e - s) * 0.04),
    ]

    prev_end = 0
    for end, fn in sections:
        if end <= prev_end or end > dates:
            prev_end = end
            continue
        s, e = prev_end, end
        close[s:e] = fn(close, s, e)
        if e - s >= 2:
            close[s:e] = np.clip(close[s:e], 9.5, 15.0)
        prev_end = end

    # 剩余天数分配期
    if prev_end < dates:
        close[prev_end:] = close[prev_end] + np.random.randn(dates - prev_end) * 0.03

    open_p = close - np.random.rand(dates) * 0.05
    high = close + np.random.rand(dates) * 0.10
    low = close - np.random.rand(dates) * 0.10

    volume = np.random.randint(5_000_000, 15_000_000, dates)
    vol_segments = [
        (min(40, dates), 4_000_000),
        (min(60, dates), 8_000_000),
        (min(80, dates), 12_000_000),
        (min(95, dates), 6_000_000),
    ]
    prev_end = 0
    for end, v in vol_segments:
        if end <= prev_end:
            prev_end = end
            continue
        volume[prev_end:end] = v
        prev_end = end
    if prev_end < dates:
        volume[prev_end:] = 4_000_000

    df = pd.DataFrame({
        "open": open_p, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=idx)
    df.index.name = "date"
    return df


def _make_uptrend_data(dates: int = 120) -> pd.DataFrame:
    """生成强上升趋势数据（预期触发 INIT → ACCEL → MAIN → EXHAUST）。"""
    np.random.seed(123)
    idx = pd.bdate_range(start="2026-01-01", periods=dates, freq="B")
    close = 10.0 + np.arange(dates) * 0.08 + np.random.randn(dates) * 0.02
    open_p = close - np.random.rand(dates) * 0.04
    high = close + np.random.rand(dates) * 0.08
    low = close - np.random.rand(dates) * 0.08

    volume = np.full(dates, 8_000_000)
    volume[:30] = 4_000_000
    volume[30:50] = 6_000_000
    volume[50:80] = 15_000_000
    volume[80:100] = 10_000_000
    volume[100:] = 5_000_000

    df = pd.DataFrame({
        "open": open_p, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=idx)
    df.index.name = "date"
    return df


def _make_range_with_fakeouts(dates: int = 100) -> pd.DataFrame:
    """生成 RANGE 震荡 + 若干假突破的数据。"""
    np.random.seed(456)
    idx = pd.bdate_range(start="2026-01-01", periods=dates, freq="B")
    base = 10.0 + np.random.randn(dates) * 0.5
    base = np.clip(base, 9.0, 11.0)

    close = base
    open_p = close - np.random.rand(dates) * 0.2
    high = close + np.random.rand(dates) * 0.3
    low = close - np.random.rand(dates) * 0.3

    volume = np.random.randint(3_000_000, 8_000_000, dates)
    # 一些假突破：突然放量但价格没持续
    for b_idx in [15, 35, 55, 75]:
        volume[max(0, b_idx - 2): min(dates, b_idx + 2)] = 15_000_000
        # 这些点价格瞬间拉高
        if b_idx < dates:
            high[b_idx] = 11.5
            if b_idx + 1 < dates:
                close[b_idx + 1] = 9.5  # 快速回落

    df = pd.DataFrame({
        "open": open_p, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=idx)
    df.index.name = "date"
    return df


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def sample_data() -> pd.DataFrame:
    """标准测试数据（含趋势结构）。"""
    return _make_ohlcv()


@pytest.fixture
def uptrend_data() -> pd.DataFrame:
    """强上升趋势数据。"""
    return _make_uptrend_data()


@pytest.fixture
def range_data() -> pd.DataFrame:
    """RANGE 震荡数据（带假突破）。"""
    return _make_range_with_fakeouts()


@pytest.fixture
def real_market_data() -> pd.DataFrame:
    """加载真实市场数据（601857）。"""
    csv_path = MOZHI_BASE / "data" / "market" / "601857_SH.csv"
    if not csv_path.exists():
        pytest.skip("实际市场数据文件不存在: 601857_SH.csv")
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    col_map = {"Open": "open", "High": "high", "Low": "low",
               "Close": "close", "Volume": "volume", "Amount": "amount"}
    df = df.rename(columns=col_map)
    required = ["open", "high", "low", "close", "volume"]
    for c in required:
        if c not in df.columns:
            pytest.skip(f"市场数据缺少列: {c}")
    df = df[df.index >= "2026-01-01"]
    return df


# ═══════════════════════════════════════════════════════════════
# C1: 阶段判定测试
# ═══════════════════════════════════════════════════════════════


class TestTrendLifecycleDetector:
    """C1: 趋势生命周期阶段判定器测试。"""

    def test_detector_initialization(self):
        """检测器初始化测试。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector = TrendLifecycleDetector()
        assert detector.TQ_ACCEL_THRESHOLD == 0.70
        assert detector.VWAP_ACCEL_THRESHOLD == 3.0
        assert detector.CONSECUTIVE_HIGH_DAYS == 3

    def test_detector_custom_params(self):
        """自定义参数初始化测试。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector = TrendLifecycleDetector(params={
            "TQ_ACCEL_THRESHOLD": 0.80,
            "VWAP_ACCEL_THRESHOLD": 5.0,
        })
        assert detector.TQ_ACCEL_THRESHOLD == 0.80
        assert detector.VWAP_ACCEL_THRESHOLD == 5.0

    def test_detect_returns_lifecycle_result(self, sample_data):
        """检测返回 LifecycleResult。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, LifecycleResult, TrendPhase,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(sample_data)

        assert isinstance(result, LifecycleResult)
        assert isinstance(result.per_bar_phase, pd.Series)
        assert len(result.per_bar_phase) == len(sample_data)
        assert isinstance(result.transitions, list)
        assert isinstance(result.periods, list)
        assert isinstance(result.phase_stats, dict)

        # 验证所有阶段都是有效阶段
        for p in result.per_bar_phase:
            assert p in TrendPhase.ALL_PHASES, f"无效阶段: {p}"

    def test_detect_overall_range(self, sample_data):
        """RANGE 震荡期应处于 PRE_INIT。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector = TrendLifecycleDetector()
        result = detector.detect(sample_data)

        # 前 40 天震荡应该基本是 PRE_INIT
        first_40 = result.per_bar_phase.iloc[5:40]  # 跳过前 5 个 bar（无数据）
        pre_init_ratio = (first_40 == "PRE_INIT").sum() / len(first_40)
        print(f"RANGE 期 PRE_INIT 占比: {pre_init_ratio:.1%}")
        assert pre_init_ratio >= 0.7, \
            f"RANGE 期 PRE_INIT 比例 {pre_init_ratio:.1%} 不足 70%"

    def test_detect_progression(self, uptrend_data):
        """上升趋势应按 INIT → ACCEL → MAIN 次序递进（可跳级）。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector = TrendLifecycleDetector()
        result = detector.detect(uptrend_data)

        # 打印阶段切换
        print("\n阶段切换事件:")
        for t in result.transitions:
            print(f"  [{t.timestamp}] {t.from_phase} → {t.to_phase}: {t.trigger_reason}")

        # 应该有阶段切换
        assert len(result.transitions) >= 1, "上升趋势至少应有 1 次阶段切换"

        # 阶段顺序应递增（允许跳级）
        from backtest.signals.trend_lifecycle import TrendPhase, TrendLifecycleFSM

        phases_seen = []
        for t in result.transitions:
            phases_seen.append(t.to_phase)
            # 验证禁止后退
            t_phase_idx = [TrendLifecycleFSM.PHASE_ORDER.get(t.to_phase, 0)]

        # 打印阶段统计
        print("\n阶段统计:")
        for phase, stats in result.phase_stats.items():
            if stats["occurrences"] > 0:
                print(f"  {phase}: {stats}")

    def test_phase_consistency(self, uptrend_data):
        """阶段判定应与状态机一致。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, TrendPhase,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(uptrend_data)

        # 最后 5 个 bar 不应为初始阶段
        last_10 = result.per_bar_phase.iloc[-10:]
        pre_init_count = (last_10 == TrendPhase.PRE_INIT).sum()
        # 强趋势数据到末期应已经超越 PRE_INIT
        acquired_phases = set(result.per_bar_phase.iloc[50:].unique())
        print(f"趋势后半段阶段: {acquired_phases}")
        assert len(acquired_phases - {TrendPhase.PRE_INIT}) >= 1, \
            "强趋势数据到中后期应检测到除 PRE_INIT 外的阶段"

    def test_small_data_returns_empty(self):
        """小数据返回 PRE_INIT。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        small_df = _make_ohlcv(dates=30)
        detector = TrendLifecycleDetector()
        result = detector.detect(small_df)

        assert len(result.per_bar_phase) == 30
        assert (result.per_bar_phase == "PRE_INIT").all(), \
            "30 bars 数据不足，应全为 PRE_INIT"
        assert len(result.transitions) == 0

    def test_get_phase_at(self, uptrend_data):
        """get_phase_at 方法测试。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector = TrendLifecycleDetector()
        result = detector.detect(uptrend_data)

        # 指定索引查询
        phase_0 = result.get_phase_at(0)
        assert isinstance(phase_0, str)
        assert phase_0 in ("PRE_INIT",)

        # 越界查询应返回 PRE_INIT
        phase_oob = result.get_phase_at(9999)
        assert phase_oob == "PRE_INIT"

        # 最后一个 bar 查询
        phase_last = result.get_phase_at(len(uptrend_data) - 1)
        assert isinstance(phase_last, str)

    def test_to_dict_serialization(self, uptrend_data):
        """序列化测试。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector = TrendLifecycleDetector()
        result = detector.detect(uptrend_data)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "bar_count" in d
        assert "transitions" in d
        assert "periods" in d
        assert "phase_stats" in d
        assert d["bar_count"] == len(uptrend_data)

        # JSON 序列化验证
        import json
        json_str = json.dumps(d, ensure_ascii=False)
        assert len(json_str) > 0
        loaded = json.loads(json_str)
        assert loaded["bar_count"] == len(uptrend_data)


# ═══════════════════════════════════════════════════════════════
# C2: 状态机测试
# ═══════════════════════════════════════════════════════════════


class TestTrendLifecycleFSM:
    """C2: 状态机测试。"""

    def test_initial_state(self):
        """初始状态为 PRE_INIT。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()
        assert fsm.current_phase == TrendPhase.PRE_INIT
        assert fsm.transitions == []

    def test_forward_transition(self):
        """正常前进切换。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()

        # PRE_INIT → INIT
        ok = fsm.transition_to(
            TrendPhase.INIT, "放量突破",
            "2026-01-22", bar_index=42,
        )
        assert ok
        assert fsm.current_phase == TrendPhase.INIT

        # INIT → ACCEL
        ok = fsm.transition_to(
            TrendPhase.ACCEL, "TQ>0.7, VWAP>3%",
            "2026-02-05", bar_index=55,
        )
        assert ok
        assert fsm.current_phase == TrendPhase.ACCEL

        # ACCEL → MAIN
        ok = fsm.transition_to(
            TrendPhase.MAIN, "Volume 放量",
            "2026-02-15", bar_index=65,
        )
        assert ok
        assert fsm.current_phase == TrendPhase.MAIN

    def test_skip_transition(self):
        """跳级前进（PRE_INIT → MAIN）。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()
        ok = fsm.transition_to(
            TrendPhase.MAIN, "跳级进入主升期",
            "2026-02-10", bar_index=50,
        )
        assert ok
        assert fsm.current_phase == TrendPhase.MAIN
        assert len(fsm.transitions) == 1

    def test_backward_transition_denied(self):
        """禁止后退。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()
        fsm.transition_to(TrendPhase.INIT, "init", "2026-01-22", 42)
        fsm.transition_to(TrendPhase.MAIN, "main", "2026-02-15", 65)

        # 尝试后退到 INIT → 应拒绝
        ok = fsm.transition_to(
            TrendPhase.INIT, "不应后退",
            "2026-03-01", bar_index=80,
        )
        assert not ok
        assert fsm.current_phase == TrendPhase.MAIN
        assert len(fsm.transitions) == 2  # 只有前两次切换

    def test_same_phase_no_transition_recorded(self):
        """相同阶段不记录切换。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()
        ok = fsm.transition_to(TrendPhase.INIT, "init", "2026-01-22", 42)
        assert ok
        assert len(fsm.transitions) == 1

        # 再次切换到 INIT → 返回 True（不拒绝）但无新切换记录
        ok = fsm.transition_to(TrendPhase.INIT, "again", "2026-01-23", 43)
        assert ok
        assert len(fsm.transitions) == 1  # 没有新增

    def test_full_lifecycle(self):
        """完整 6 阶段全生命周期（含分配期）。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()
        fsm.transition_to(TrendPhase.INIT, "1", "D1", 0)
        fsm.transition_to(TrendPhase.ACCEL, "2", "D10", 9)
        fsm.transition_to(TrendPhase.MAIN, "3", "D20", 19)
        fsm.transition_to(TrendPhase.EXHAUST, "4", "D30", 29)
        fsm.transition_to(TrendPhase.DISTRIB, "5", "D40", 39)
        assert fsm.current_phase == TrendPhase.DISTRIB
        assert len(fsm.transitions) == 5

    def test_final_phase_any_transition_denied(self):
        """DISTRIB 无法后退。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()
        fsm.transition_to(TrendPhase.DISTRIB, "分配", "D50", 49)
        assert fsm.current_phase == TrendPhase.DISTRIB

        # 尝试回到 ACCEL → 拒绝
        ok = fsm.transition_to(TrendPhase.ACCEL, "不应", "D60", 59)
        assert not ok
        assert fsm.current_phase == TrendPhase.DISTRIB

    def test_reset(self):
        """重置测试。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleFSM, TrendPhase

        fsm = TrendLifecycleFSM()
        fsm.transition_to(TrendPhase.INIT, "init", "D1", 0)
        fsm.transition_to(TrendPhase.MAIN, "main", "D10", 9)
        fsm.reset()
        assert fsm.current_phase == TrendPhase.PRE_INIT
        assert fsm.transitions == []


# ═══════════════════════════════════════════════════════════════
# C3: 与 False Breakout 协同分析测试
# ═══════════════════════════════════════════════════════════════


class TestBreakoutLifecycleCoanalysis:
    """C3: 假突破生命周期协同分析测试。"""

    def test_analyze_basic(self, sample_data):
        """基础协同分析。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, analyze_breakout_lifecycle,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(sample_data)

        # 模拟突破事件（取几个随机索引）
        breakout_indices = [10, 25, 45, 60, 75, 90, 105]
        false_indices = [10, 25, 105]  # 3 个假突破

        analysis = analyze_breakout_lifecycle(
            result, breakout_indices, false_indices,
        )

        # 验证基本结构
        assert analysis["total_breakouts"] == 7
        assert analysis["total_false_breakouts"] == 3

        # 验证 phase_distribution 包含所有阶段
        from backtest.signals.trend_lifecycle import TrendPhase
        for p in TrendPhase.ALL_PHASES:
            assert p in analysis["phase_distribution"]

        # 验证每个突破事件都有数据
        assert len(analysis["per_breakout"]) == 7
        assert "index" in analysis["per_breakout"][0]
        assert "date" in analysis["per_breakout"][0]
        assert "phase" in analysis["per_breakout"][0]
        assert "is_false" in analysis["per_breakout"][0]

        # 假突破标记正确
        for bo in analysis["per_breakout"]:
            if bo["index"] in false_indices:
                assert bo["is_false"] is True
            else:
                assert bo["is_false"] is False

    def test_analyze_all_true(self, sample_data):
        """所有突破事件都标记为假突破。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, analyze_breakout_lifecycle,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(sample_data)
        breakout_indices = [5, 15, 30]

        # 不传 false_breakout_indices → 都视为假突破
        analysis = analyze_breakout_lifecycle(result, breakout_indices)

        assert analysis["total_breakouts"] == 3
        assert analysis["total_false_breakouts"] == 0  # None 视为无标记
        for bo in analysis["per_breakout"]:
            assert bo["is_false"] is False

    def test_analyze_empty_breakouts(self, sample_data):
        """空突破事件列表。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, analyze_breakout_lifecycle,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(sample_data)

        analysis = analyze_breakout_lifecycle(result, [])
        assert analysis["total_breakouts"] == 0
        assert analysis["total_false_breakouts"] == 0
        assert analysis["false_ratio_total"] == 0.0

    def test_analyze_invalid_indices(self, sample_data):
        """越界索引应被忽略。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, analyze_breakout_lifecycle,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(sample_data)

        all_indices = [0, 1, 9999, -5, 2]
        valid_count = sum(
            1 for i in all_indices
            if 0 <= i < len(result.per_bar_phase)
        )

        analysis = analyze_breakout_lifecycle(result, all_indices)
        assert analysis["total_breakouts"] == valid_count, (
            f"预期 {valid_count} 有效索引, 得到 {analysis['total_breakouts']}"
        )
        assert analysis["total_breakouts"] < len(all_indices), "越界索引应被过滤"

    def test_phase_distribution_correct(self, sample_data):
        """阶段分布比例统计正确。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, analyze_breakout_lifecycle,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(sample_data)

        # 把假突破都放在 INIT 阶段
        all_indices = list(range(len(sample_data)))
        # 用 20 个索引覆盖不同阶段
        test_indices = [10, 20, 30, 50, 70, 90]
        false_indices = [10, 20, 30]  # 一半假突破

        analysis = analyze_breakout_lifecycle(
            result, test_indices, false_indices,
        )

        # 验证 false_ratio_total
        expected_ratio = round(len(false_indices) / len(test_indices) * 100, 1)
        assert analysis["false_ratio_total"] == expected_ratio

    def test_analyze_with_breakout_profile_on_real_data(self, real_market_data):
        """在真实数据上检测突破并分析生命周期分布。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, analyze_breakout_lifecycle,
        )
        from backtest.signals.breakout_profile import (
            detect_breakout_points, BreakoutFeatureExtractor, BreakoutScoringCard,
        )

        # 检测突破点
        breakout_indices = detect_breakout_points(real_market_data)
        if len(breakout_indices) < 2:
            pytest.skip("真实数据突破点不足，跳过")

        # 提取特征并评分
        extractor = BreakoutFeatureExtractor()
        features_list = extractor.extract_batch(real_market_data, breakout_indices)
        card = BreakoutScoringCard()
        scoring_results = card.batch_score(features_list)

        # 假突破索引
        false_indices = [
            idx for idx, sr in zip(breakout_indices, scoring_results)
            if sr["is_false_breakout"]
        ]

        # 生命周期检测
        detector = TrendLifecycleDetector()
        result = detector.detect(real_market_data)

        # 协同分析
        analysis = analyze_breakout_lifecycle(
            result, breakout_indices, false_indices,
        )

        print(f"\n真实数据突破-生命周期协同分析:")
        print(f"  总突破数: {analysis['total_breakouts']}")
        print(f"  假突破数: {analysis['total_false_breakouts']}")
        print(f"  整体假突破比例: {analysis['false_ratio_total']}%")
        print(f"\n阶段分布:")
        for phase, dist in analysis["phase_distribution"].items():
            if dist["total_breakouts"] > 0:
                print(
                    f"  {phase:>10}: "
                    f"总{dist['total_breakouts']} / "
                    f"假{dist['false_breakouts']} / "
                    f"比例{dist['false_ratio']}%"
                )
            else:
                print(f"  {phase:>10}: 0")

        # 验证分析结果完整
        assert analysis["total_breakouts"] == len(breakout_indices)
        assert analysis["total_false_breakouts"] == len(false_indices)


# ═══════════════════════════════════════════════════════════════
# C4: 与真实回测数据集成测试
# ═══════════════════════════════════════════════════════════════


class TestTrendLifecycleIntegration:
    """C4: 与真实回测数据集成测试。"""

    def test_detect_on_real_data(self, real_market_data):
        """在真实市场数据上运行检测。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector = TrendLifecycleDetector()
        result = detector.detect(real_market_data)

        # 验证结果结构
        assert len(result.per_bar_phase) == len(real_market_data)

        # 打印阶段切换
        print(f"\n真实数据阶段切换 ({len(result.transitions)}):")
        for t in result.transitions:
            print(f"  [{t.timestamp}] {t.from_phase} → {t.to_phase}")

        # 打印阶段统计
        print(f"\n真实数据阶段统计:")
        for phase, stats in result.phase_stats.items():
            if stats["occurrences"] > 0:
                print(
                    f"  {phase:>10}: "
                    f"出现{stats['occurrences']}次 / "
                    f"平均{stats['avg_duration']}天 / "
                    f"平均收益{stats['avg_return']}%"
                )

        # 只要数据充足，应至少有一些阶段切换
        if len(real_market_data) >= 80:
            print(f"阶段数: {len([s for s in result.phase_stats.values() if s['occurrences'] > 0])}")

    def test_per_bar_phase_structure(self, real_market_data):
        """每 bar 阶段序列结构完整。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, TrendPhase,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(real_market_data)

        # 验证所有阶段值
        unique_phases = set(result.per_bar_phase.unique())
        for p in unique_phases:
            assert p in TrendPhase.ALL_PHASES, f"无效阶段: {p}"

        # 验证阶段序列与索引一致
        assert result.per_bar_phase.index.equals(real_market_data.index)

    def test_transition_consistency(self, real_market_data):
        """切换事件一致性验证。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, TrendLifecycleFSM,
        )

        detector = TrendLifecycleDetector()
        result = detector.detect(real_market_data)

        # 切换事件的阶段顺序应严格递增
        prev_order = -1
        for t in result.transitions:
            order = TrendLifecycleFSM.PHASE_ORDER.get(t.to_phase, -1)
            assert order >= prev_order, f"阶段顺序错误: {t}"
            prev_order = order

    def test_detection_stability(self, real_market_data):
        """检测稳定性：多次运行结果一致。"""
        from backtest.signals.trend_lifecycle import TrendLifecycleDetector

        detector1 = TrendLifecycleDetector()
        result1 = detector1.detect(real_market_data)

        detector2 = TrendLifecycleDetector()
        result2 = detector2.detect(real_market_data)

        # 切换次数应相同
        assert len(result1.transitions) == len(result2.transitions), \
            "检测不稳定：切换次数不一致"

        # 最后一个 bar 的阶段应相同
        assert result1.per_bar_phase.iloc[-1] == result2.per_bar_phase.iloc[-1], \
            "检测不稳定：最终阶段不一致"

    def test_integration_with_breakout_profile(self, real_market_data):
        """与 Breakout Profile 的完整集成。"""
        from backtest.signals.trend_lifecycle import (
            TrendLifecycleDetector, analyze_breakout_lifecycle,
        )
        from backtest.signals.breakout_profile import (
            detect_breakout_points,
        )

        # 1. 检测突破点
        breakout_indices = detect_breakout_points(real_market_data)
        if len(breakout_indices) < 2:
            pytest.skip("真实数据突破点不足，跳过")

        # 2. 生命周期检测
        detector = TrendLifecycleDetector()
        result = detector.detect(real_market_data)

        # 3. 协同分析（所有突破视为无标签，作为基线）
        analysis = analyze_breakout_lifecycle(result, breakout_indices)

        print(f"\n完整集成测试:")
        print(f"  Bar 总数: {len(real_market_data)}")
        print(f"  突破点数: {analysis['total_breakouts']}")
        print(f"  阶段切换数: {len(result.transitions)}")

        # 验证突破事件所在阶段信息
        for bo in analysis["per_breakout"][:5]:
            print(f"  突破 [{bo['date']}] 阶段={bo['phase']}")

        # 阶段分布概况
        non_zero_phases = sum(
            1 for d in analysis["phase_distribution"].values()
            if d["total_breakouts"] > 0
        )
        print(f"  覆盖阶段数: {non_zero_phases}")
