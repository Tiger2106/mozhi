#!/usr/bin/env python3
"""
墨枢 - R1 阶段三 E2E 验证脚本

验证管线：MarketData → 6因子 → FactorRegistry → SignalFusion → CompositeSignal
验证项目：
  1. SignalFusionEngine.fuse() 输出正确的 CompositeSignal
  2. attribute_trades() 正确归因 n 笔交易
  3. RegimeAnalyzer.get_current_regime() 返回有效状态
  4. 输出报告到 reports/research/{date}/r1_phase3_e2e.json

作者: 墨衡
创建时间: 2026-05-18
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

# ── 项目根 ──────────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\17699\mozhi_platform")
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline_paths import research_date_dir, today_str
from src.backtest.models.signal_types import (
    FactorSignal,
    CompositeSignal,
    MarketRegime,
    SignalAction,
    SignalConfidence,
)
from src.backtest.factors.factor_registry import FactorRegistry
from src.backtest.signals.signal_fusion import SignalFusionEngine
from src.backtest.analysis.trade_attribution import attribute_trades
from src.backtest.regime.regime_analyzer import RegimeAnalyzer
from src.backtest.backtest.r1_backtest_engine import TradeRecord

TZ = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════
# 验证 #1: SignalFusionEngine
# ═══════════════════════════════════════════════════════════════

def validate_signal_fusion() -> Dict[str, Any]:
    """验证 SignalFusionEngine.fuse() 的正确性"""
    print("[E2E] === 验证 #1: SignalFusionEngine ===")
    results: Dict[str, Any] = {
        "name": "SignalFusionEngine.fuse()",
        "passed": False,
        "details": {},
    }

    engine = SignalFusionEngine()

    # ── 测试 1: 同向信号 ──────────────────────────────────
    buy_signals = [
        FactorSignal("601857", "2026-01-01T10:00:00+08:00", "ma_trend",
                      SignalAction.BUY, SignalConfidence.HIGH, 0.8),
        FactorSignal("601857", "2026-01-01T10:00:00+08:00", "volume_ratio",
                      SignalAction.BUY, SignalConfidence.MEDIUM, 0.6),
        FactorSignal("601857", "2026-01-01T10:00:00+08:00", "momentum",
                      SignalAction.BUY, SignalConfidence.HIGH, 0.7),
    ]
    composite1 = engine.fuse(buy_signals, MarketRegime.UPTREND)
    assert composite1.action == SignalAction.BUY, f"BUY expected, got {composite1.action}"
    assert composite1.composite_score > 0.5, f"score > 0.5 expected, got {composite1.composite_score}"
    results["details"]["same_direction"] = {
        "action": composite1.action.value,
        "score": composite1.composite_score,
        "confidence": composite1.confidence.value,
    }

    # ── 测试 2: 反向信号 ──────────────────────────────────
    mixed_signals = [
        FactorSignal("601857", "2026-01-01T10:00:00+08:00", "ma_trend",
                      SignalAction.BUY, SignalConfidence.HIGH, 0.7),
        FactorSignal("601857", "2026-01-01T10:00:00+08:00", "momentum",
                      SignalAction.SELL, SignalConfidence.HIGH, -0.6),
    ]
    composite2 = engine.fuse(mixed_signals, MarketRegime.RANGE)
    results["details"]["opposite_direction"] = {
        "action": composite2.action.value,
        "score": composite2.composite_score,
    }

    # ── 测试 3: 低置信度过滤 ────────────────────────────────
    low_signals = [
        FactorSignal("601857", "2026-01-01T10:00:00+08:00", "ma_trend",
                      SignalAction.BUY, SignalConfidence.LOW, 0.1),
        FactorSignal("601857", "2026-01-01T10:00:00+08:00", "volume_ratio",
                      SignalAction.SELL, SignalConfidence.LOW, -0.2),
    ]
    composite3 = engine.fuse(low_signals)
    assert composite3.action == SignalAction.HOLD, f"HOLD expected, got {composite3.action}"
    results["details"]["low_confidence_filter"] = {
        "action": composite3.action.value,
        "score": composite3.composite_score,
        "reasoning": composite3.reasoning,
    }

    # ── 测试 4: 空信号 ──────────────────────────────────────
    empty = engine.fuse([])
    assert empty.action == SignalAction.HOLD
    results["details"]["empty_input"] = {
        "action": empty.action.value,
        "score": empty.composite_score,
    }

    results["passed"] = True
    print("[E2E]  ✓ SignalFusionEngine 全部测试通过")
    return results


# ═══════════════════════════════════════════════════════════════
# 验证 #2: Trade Attribution
# ═══════════════════════════════════════════════════════════════

def validate_trade_attribution() -> Dict[str, Any]:
    """验证 attribute_trades() 归因正确性"""
    print("[E2E] === 验证 #2: TradeAttribution ===")
    results: Dict[str, Any] = {
        "name": "attribute_trades()",
        "passed": False,
        "details": {},
    }

    # 3 笔交易
    trades = [
        TradeRecord("2026-01-01T10:00:00+08:00", "2026-01-01T14:00:00+08:00",
                    10.0, 11.0, 1, 1.0, 100.0, 0.10, 4, "signal"),
        TradeRecord("2026-01-02T10:00:00+08:00", "2026-01-02T14:00:00+08:00",
                    10.0, 9.5, 1, 1.0, -50.0, -0.05, 4, "signal"),
        TradeRecord("2026-01-03T10:00:00+08:00", "2026-01-03T14:00:00+08:00",
                    10.0, 12.0, -1, 1.0, -200.0, -0.20, 4, "signal"),
    ]

    factor_signals: Dict[str, List[FactorSignal]] = {
        "ma_trend": [
            FactorSignal("601857", "2026-01-01T10:00:00+08:00", "ma_trend",
                          SignalAction.BUY, SignalConfidence.HIGH, 0.8),
            FactorSignal("601857", "2026-01-02T10:00:00+08:00", "ma_trend",
                          SignalAction.BUY, SignalConfidence.MEDIUM, 0.6),
            FactorSignal("601857", "2026-01-03T10:00:00+08:00", "ma_trend",
                          SignalAction.SELL, SignalConfidence.HIGH, -0.7),
        ],
        "volume_ratio": [
            FactorSignal("601857", "2026-01-01T10:00:00+08:00", "volume_ratio",
                          SignalAction.BUY, SignalConfidence.MEDIUM, 0.5),
            FactorSignal("601857", "2026-01-02T10:00:00+08:00", "volume_ratio",
                          SignalAction.SELL, SignalConfidence.MEDIUM, -0.4),
            FactorSignal("601857", "2026-01-03T10:00:00+08:00", "volume_ratio",
                          SignalAction.BUY, SignalConfidence.HIGH, 0.9),
        ],
    }

    report = attribute_trades(trades, factor_signals)

    # 验证
    assert report.total_trades == 3, f"3 trades expected, got {report.total_trades}"
    assert len(report.trade_attributions) == 3, f"3 attributions expected, got {len(report.trade_attributions)}"

    # 检查第一笔
    attr0 = report.trade_attributions[0]
    assert attr0.direction == 1
    assert len(attr0.active_factors) > 0
    assert len(attr0.factor_contributions) > 0

    # 因子统计
    assert "ma_trend" in report.factor_stats
    assert "volume_ratio" in report.factor_stats

    # 相关性
    assert report.correlation is not None

    results["details"] = {
        "total_trades": report.total_trades,
        "total_pnl": report.total_pnl,
        "top_factor_by_win_rate": report.top_factor_by_win_rate,
        "top_factor_by_pnl": report.top_factor_by_pnl,
        "factor_stats": {
            name: {
                "win_rate": s.win_rate,
                "total_pnl": s.total_pnl,
                "profit_factor": s.profit_factor,
            }
            for name, s in report.factor_stats.items()
        },
        "correlation_pairs": [
            {"a": p[0], "b": p[1], "r": round(p[2], 4)}
            for p in (report.correlation.factor_pairs if report.correlation else [])
        ],
    }

    results["passed"] = True
    print("[E2E]  ✓ TradeAttribution 全部归因验证通过")
    return results


# ═══════════════════════════════════════════════════════════════
# 验证 #3: RegimeAnalyzer
# ═══════════════════════════════════════════════════════════════

def validate_regime_analyzer() -> Dict[str, Any]:
    """验证 RegimeAnalyzer.get_current_regime() 的有效性"""
    print("[E2E] === 验证 #3: RegimeAnalyzer ===")
    results: Dict[str, Any] = {
        "name": "RegimeAnalyzer",
        "passed": False,
        "details": {},
    }

    # 生成上涨趋势数据
    np.random.seed(42)
    n = 120
    closes = []
    px = 100.0
    for i in range(n):
        px += 0.8 + np.random.normal(0, 0.3)
        px = max(px, 1.0)
        closes.append(px)

    close = np.array(closes)
    df = pd.DataFrame({
        "open": np.concatenate([[100.0], close[:-1]]),
        "high": np.maximum(np.concatenate([[100.0], close[:-1]]), close) * 1.005,
        "low": np.minimum(np.concatenate([[100.0], close[:-1]]), close) * 0.995,
        "close": close,
        "volume": np.random.randint(500000, 1500000, n),
    })

    analyzer = RegimeAnalyzer()
    window_result = analyzer.analyze_window(df, lookback=60)
    current = analyzer.get_current_regime()
    transitions = analyzer.regime_transition_score()

    # 验证当前状态
    assert current["regime"] in ("UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX", "UNKNOWN")
    assert 0.0 <= current["confidence"] <= 1.0
    assert current["duration_bars"] >= 0

    # 验证窗口分析
    assert len(window_result.sequence) > 0
    assert window_result.dominant_regime != ""

    # 验证转换矩阵
    all_states = ["UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "CLIMAX", "UNKNOWN"]
    for state in all_states:
        assert state in transitions, f"转换矩阵缺少状态 {state}"

    # 验证知识沉淀
    entry = analyzer.knowledge_entry()
    assert entry.regime == current["regime"]
    assert entry.confidence == current["confidence"]
    assert len(entry.summary) > 0

    results["details"] = {
        "current_regime": current["regime"],
        "confidence": current["confidence"],
        "duration_bars": current["duration_bars"],
        "dominant_regime": window_result.dominant_regime,
        "stability": window_result.stability,
        "transitions_possible": sum(
            1 for from_s in all_states
            for to_s in all_states
            if transitions[from_s][to_s] > 0
        ),
        "knowledge_summary": entry.summary[:100] + "..." if len(entry.summary) > 100 else entry.summary,
    }

    results["passed"] = True
    print("[E2E]  ✓ RegimeAnalyzer 全部验证通过")
    return results


# ═══════════════════════════════════════════════════════════════
# 验证 #4: 端到端管线
# ═══════════════════════════════════════════════════════════════

def validate_end_to_end_pipeline() -> Dict[str, Any]:
    """完整管线验证：MarketData → FactorRegistry → SignalFusion → CompositeSignal"""
    print("[E2E] === 验证 #4: 端到端管线 ===")
    results: Dict[str, Any] = {
        "name": "端到端管线验证",
        "passed": False,
        "details": {},
    }

    # ── 生成模拟市场数据 ──────────────────────────────
    np.random.seed(42)
    n = 120
    closes = []
    px = 100.0
    for i in range(n):
        px += 0.5 + np.random.normal(0, 0.4)
        px = max(px, 1.0)
        closes.append(px)
    close = np.array(closes)

    df = pd.DataFrame({
        "open": np.concatenate([[100.0], close[:-1]]),
        "high": np.maximum(np.concatenate([[100.0], close[:-1]]), close) * 1.008,
        "low": np.minimum(np.concatenate([[100.0], close[:-1]]), close) * 0.992,
        "close": close,
        "volume": np.random.randint(500000, 1500000, n),
    })

    # ── Step 1: FactorRegistry ──────────────────────────
    registry = FactorRegistry()
    all_scores = registry.compute_all(df, symbol="601857", date="2026-01-01")

    # 过滤元信息
    factor_scores = {k: v for k, v in all_scores.items() if not k.startswith("_meta")}
    factor_count = len(factor_scores)
    assert factor_count >= 6, f"至少 6 个因子，得到 {factor_count}"

    results["details"]["factor_registry"] = {
        "registered_count": registry.count(),
        "computed_scores": factor_scores,
        "categories": registry.list_by_category(),
    }

    # ── Step 2: SignalFusion ───────────────────────────
    engine = SignalFusionEngine()
    factor_signals_list = []
    for fname, score in factor_scores.items():
        action = SignalAction.BUY if score > 0 else SignalAction.SELL
        factor_signals_list.append(FactorSignal(
            symbol="601857",
            timestamp="2026-01-01T10:00:00+08:00",
            factor_name=fname,
            action=action,
            confidence=SignalConfidence.HIGH if abs(score) > 0.7 else SignalConfidence.MEDIUM,
            score=score,
        ))

    composite = engine.fuse(factor_signals_list, MarketRegime.UPTREND)
    assert isinstance(composite, CompositeSignal)
    assert composite.action in (SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD)
    assert -1.0 <= composite.composite_score <= 1.0

    results["details"]["signal_fusion"] = {
        "action": composite.action.value,
        "composite_score": composite.composite_score,
        "confidence": composite.confidence.value,
        "regime": composite.regime.value,
        "sub_signal_count": len(composite.sub_signals),
        "reasoning": composite.reasoning,
    }

    # ── Step 3: RegimeAnalyzer ──────────────────────────
    analyzer = RegimeAnalyzer()
    analyzer.analyze_window(df, lookback=60)
    current = analyzer.get_current_regime()

    results["details"]["regime_analyzer"] = {
        "current_regime": current["regime"],
        "confidence": current["confidence"],
    }

    # ── Step 4: TradeAttribution ────────────────────────
    trades = [
        TradeRecord("2026-01-01T10:00:00+08:00", "2026-01-01T14:00:00+08:00",
                    10.0, 10.5, 1, 1.0, 50.0, 0.05, 4, "signal"),
    ]
    attribution = attribute_trades(trades, {"composite": factor_signals_list})

    results["details"]["trade_attribution"] = {
        "total_trades": attribution.total_trades,
        "trade_count": len(attribution.trade_attributions),
    }

    results["passed"] = True
    print("[E2E]  ✓ 端到端管线全部验证通过")
    return results


# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    """执行全部 E2E 验证并输出报告。"""
    print("=" * 60)
    print("  墨枢 R1 阶段三 E2E 验证")
    print(f"  时间: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    t0 = time.time()

    # 并行验证各项
    v1 = validate_signal_fusion()
    v2 = validate_trade_attribution()
    v3 = validate_regime_analyzer()
    v4 = validate_end_to_end_pipeline()

    elapsed = time.time() - t0

    # 汇总
    all_passed = all(v["passed"] for v in [v1, v2, v3, v4])

    report: Dict[str, Any] = {
        "report_type": "r1_phase3_e2e",
        "completed_time": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "elapsed_seconds": round(elapsed, 2),
        "all_passed": all_passed,
        "results": [v1, v2, v3, v4],
        "summary": {
            "total_checks": 4,
            "passed": sum(1 for v in [v1, v2, v3, v4] if v["passed"]),
            "failed": sum(1 for v in [v1, v2, v3, v4] if not v["passed"]),
        },
        "verification": {
            "1_signal_fusion": "✅" if v1["passed"] else "❌",
            "2_trade_attribution": "✅" if v2["passed"] else "❌",
            "3_regime_analyzer": "✅" if v3["passed"] else "❌",
            "4_end_to_end_pipeline": "✅" if v4["passed"] else "❌",
        },
    }

    # 写入报告
    date_str = today_str()
    output_dir = research_date_dir(date_str)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "r1_phase3_e2e.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"  E2E 验证完成: {'✅ 全部通过' if all_passed else '❌ 有失败项'}")
    print(f"  耗时: {elapsed:.2f}s")
    print(f"  报告: {report_path}")
    print(f"  通过/总数: {report['summary']['passed']}/{report['summary']['total_checks']}")
    print("=" * 60)
    print()
    print("验证详情:")
    print(f"  1. SignalFusionEngine.fuse()     → {v1['verification'] if 'verification' not in report else report['verification']['1_signal_fusion']}")
    for v in [v1, v2, v3, v4]:
        print(f"  {v['name']} → {'✅' if v['passed'] else '❌'}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
