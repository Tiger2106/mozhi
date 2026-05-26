"""
墨枢 - 信号融合与处理子包（R1 阶段三）

提供：
- SignalFusionEngine          — 多因子融合引擎
- BacktestEventHook ABC       — 回测事件钩子基类
- SignalEventCollector        — 信号事件采集器
- SignalEventDB               — 信号事件数据库管理
- HookedRiskPipeline          — 带钩子注入的风险流水线
- 数据类: SignalEvent, FilterResult, DecisionResult, PositionUpdate
- Phase 3: MultiInstrumentEngine, CapitalPoolAllocator, CrossSectionReport,
           SignalDecayAnalyzer, FakeBreakoutClassifier

用法:
    # 1. 采集信号事件
    from backtest.signals.signal_collector import SignalEventCollector, SignalEvent

    collector = SignalEventCollector(batch_id="bt_001")
    collector.on_signal_created(SignalEvent(signal_id="s1", symbol="601857", ...))

    # 2. 带钩子的风险流水线
    from backtest.signals.signal_collector import HookedRiskPipeline
    pipeline = HookedRiskPipeline(risk_pipeline, signal_id="s1")
    pipeline.register_hook(collector)

    # 3. 多标并行
    from backtest.signals.multi_instrument_engine import MultiInstrumentEngine
    engine = MultiInstrumentEngine()
    results = engine.run(["601857", "600519"])
"""

from .signal_fusion import SignalFusionEngine

from .signal_collector import (
    # ABC
    BacktestEventHook,
    # 采集器
    SignalEventCollector,
    # 数据库
    SignalEventDB,
    # 流水线包装
    HookedRiskPipeline,
    # 数据类
    SignalEvent,
    FilterResult,
    DecisionResult,
    PositionUpdate,
)

from .breakout_profile import (
    # B1: 数据库
    BreakoutEventDB,
    BreakoutEvent,
    # B2: 特征提取
    BreakoutFeatureExtractor,
    FeatureSet,
    # B3: 评分卡
    BreakoutScoringCard,
    SCORECARD_WEIGHTS,
    SCORECARD_THRESHOLDS,
    # 辅助
    detect_breakout_points,
    # B4: 报告
    generate_breakout_report,
)

from .trend_lifecycle import (
    # C1: 阶段判定器
    TrendLifecycleDetector,
    # 状态机
    TrendLifecycleFSM,
    # 数据类
    TrendPhase,
    LifecycleResult,
    Transition,
    PhasePeriod,
    # C3: 突破协同分析
    analyze_breakout_lifecycle,
)

# Phase 3 — 高级模块
from .multi_instrument_engine import MultiInstrumentEngine
from .capital_pool import CapitalPoolAllocator
from .cross_section import CrossSectionReport
from .analysis.signal_decay import SignalDecayAnalyzer
from .fake_breakout_classifier import FakeBreakoutClassifier

__all__ = [
    "SignalFusionEngine",
    "BacktestEventHook",
    "SignalEventCollector",
    "SignalEventDB",
    "HookedRiskPipeline",
    "SignalEvent",
    "FilterResult",
    "DecisionResult",
    "PositionUpdate",
    # Breakout Profile
    "BreakoutEventDB",
    "BreakoutEvent",
    "BreakoutFeatureExtractor",
    "FeatureSet",
    "BreakoutScoringCard",
    "SCORECARD_WEIGHTS",
    "SCORECARD_THRESHOLDS",
    "detect_breakout_points",
    "generate_breakout_report",
    # Trend Lifecycle
    "TrendLifecycleDetector",
    "TrendLifecycleFSM",
    "TrendPhase",
    "LifecycleResult",
    "Transition",
    "PhasePeriod",
    "analyze_breakout_lifecycle",
    # Phase 3
    "MultiInstrumentEngine",
    "CapitalPoolAllocator",
    "CrossSectionReport",
    "SignalDecayAnalyzer",
    "FakeBreakoutClassifier",
]
