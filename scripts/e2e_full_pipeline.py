#!/usr/bin/env python3
"""
墨枢 — R1 全线 E2E 验证（Phase 4）
完整管线: MarketData → FactorRegistry → SignalFusion → CompositeSignal → R1BacktestEngine
验证 5 标准标的全线贯通。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline_paths import R1_BENCHMARK_SYMBOLS, research_date_dir, TZ
from src.backtest.data.market_data_adapter import fetch_price_volume
from src.backtest.factors.factor_registry import FactorRegistry
from src.backtest.models.signal_types import FactorSignal, CompositeSignal, SignalAction, SignalConfidence
from src.backtest.signals.signal_fusion import SignalFusionEngine
from src.backtest.backtest.r1_backtest_engine import R1BacktestEngine


def run_full_pipeline(symbol: str) -> Dict[str, Any]:
    """在单只标的上运行完整 R1 管线。"""
    result: Dict[str, Any] = {
        "symbol": symbol,
        "passed": False,
        "error": None,
        "timing_ms": {},
        "factor_scores": {},
        "composite_signal": None,
        "backtest_summary": None,
    }

    t_start = time.time()

    try:
        # ── Step 1: MarketData ──────────────────────
        t0 = time.time()
        df = fetch_price_volume(symbol)
        result["data_shape"] = list(df.shape)
        result["data_columns"] = list(df.columns)
        result["timing_ms"]["market_data"] = round((time.time() - t0) * 1000, 1)
        if df.empty:
            raise ValueError("dataframe is empty")

        # ── Step 2: FactorRegistry ─────────────────
        t0 = time.time()
        fr = FactorRegistry()
        scores = fr.compute_all(df, symbol=symbol)
        result["timing_ms"]["factor_registry"] = round((time.time() - t0) * 1000, 1)

        # 过滤掉 _meta_ 字段
        factor_scores = {k: round(float(v), 6) for k, v in scores.items() if not k.startswith("_meta")}
        result["factor_scores"] = factor_scores
        result["factor_count"] = len(factor_scores)

        # ── Step 3: FactorSignal 构造 ─────────────
        now_ts = pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
        signals: List[FactorSignal] = []
        for fname, fscore in factor_scores.items():
            action = SignalAction.BUY if fscore > 0 else (SignalAction.SELL if fscore < 0 else SignalAction.HOLD)
            conf = SignalConfidence.HIGH if abs(fscore) > 0.5 else (SignalConfidence.MEDIUM if abs(fscore) > 0.2 else SignalConfidence.LOW)
            signals.append(FactorSignal(
                symbol=symbol,
                timestamp=now_ts,
                factor_name=fname,
                action=action,
                confidence=conf,
                score=round(float(fscore), 4),
                metadata={},
            ))

        # ── Step 4: SignalFusion ────────────────────
        t0 = time.time()
        fusion = SignalFusionEngine()
        composite: CompositeSignal = fusion.fuse(signals)
        result["timing_ms"]["signal_fusion"] = round((time.time() - t0) * 1000, 1)

        result["composite_signal"] = {
            "action": composite.action.value if hasattr(composite.action, "value") else str(composite.action),
            "confidence": composite.confidence.value if hasattr(composite.confidence, "value") else str(composite.confidence),
            "composite_score": round(float(composite.composite_score), 4),
            "regime": str(composite.regime),
            "reasoning": composite.reasoning,
        }

        # ── Step 5: R1BacktestEngine ───────────────
        t0 = time.time()
        engine = R1BacktestEngine(initial_capital=1_000_000.0)
        bt_result = engine.run(
            df=df,
            symbol=symbol,
            method="breakout_retest",
            stop_loss_pct=0.05,
            exit_after_bars=10,
        )
        result["timing_ms"]["backtest"] = round((time.time() - t0) * 1000, 1)

        metrics = bt_result.metrics
        result["backtest_summary"] = {
            "method": "breakout_retest",
            "total_bars": bt_result.total_bars,
            "total_trades": len(bt_result.trades),
            "equity_final": round(float(metrics.get("equity_final", metrics.get("total_return_pct", 0))), 4),
            "total_return_pct": round(float(metrics.get("total_return_pct", 0)), 4),
            "sharpe": round(float(metrics.get("sharpe", metrics.get("sharpe_ratio", 0))), 4),
            "max_drawdown_pct": round(float(metrics.get("max_drawdown_pct", metrics.get("max_drawdown", 0))), 4),
            "win_rate": round(float(metrics.get("win_rate", 0)), 4),
        }

        result["timing_ms"]["total"] = round((time.time() - t_start) * 1000, 1)
        result["passed"] = True

    except Exception as e:
        import traceback
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        result["passed"] = False

    return result


def main() -> Dict[str, Any]:
    """对所有标准标的运行全管线验证。"""
    print("=" * 60)
    print("R1 全线 E2E 验证 — 完整管线直通测试")
    print(f"标的: {R1_BENCHMARK_SYMBOLS}")
    print("管线: MarketData → FactorRegistry → SignalFusion → CompositeSignal → R1BacktestEngine")
    print("=" * 60)

    report: Dict[str, Any] = {
        "test_name": "r1_complete_e2e",
        "date": datetime.now(TZ).strftime("%Y%m%d"),
        "timestamp": datetime.now(TZ).isoformat(),
        "symbols_tested": [],
        "symbol_results": {},
        "summary": {},
    }

    all_passed = True
    for symbol in R1_BENCHMARK_SYMBOLS:
        print(f"\n>>> 验证标的: {symbol}")
        result = run_full_pipeline(symbol)
        report["symbols_tested"].append(symbol)
        report["symbol_results"][symbol] = result

        status = "PASS" if result["passed"] else "FAIL"
        if not result["passed"]:
            all_passed = False

        print(f"  ┌─ 数据形状: {result.get('data_shape', 'N/A')}")
        print(f"  ├─ 因子数量: {result.get('factor_count', 0)}")
        cs = result.get("composite_signal", {})
        if cs:
            print(f"  ├─ 信号: action={cs.get('action')} confidence={cs.get('confidence')} score={cs.get('composite_score')}")
        bt = result.get("backtest_summary", {})
        if bt:
            print(f"  ├─ 回测: trades={bt.get('total_trades')} return={bt.get('total_return_pct')}% sharpe={bt.get('sharpe')}")
        timing = result.get("timing_ms", {})
        if timing:
            md_ms = timing.get('market_data', 0)
        fr_ms = timing.get('factor_registry', 0)
        sf_ms = timing.get('signal_fusion', 0)
        bt_ms = timing.get('backtest', 0)
        tot_ms = timing.get('total', 0)
        print(f"  └─ 耗时: {tot_ms}ms (data={md_ms}ms + factor={fr_ms}ms + fusion={sf_ms}ms + bt={bt_ms}ms)")
        print(f"  => status: [{status}] {result.get('error', '')}")

    total = len(report["symbols_tested"])
    passed = sum(1 for s in report["symbols_tested"] if report["symbol_results"][s]["passed"])
    report["summary"] = {
        "total_symbols": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{passed / total * 100:.1f}%",
        "all_passed": all_passed,
        "timestamp": datetime.now(TZ).isoformat(),
        "note": "新旧管线同时工作: R1BacktestEngine 负责新系统回测, legacy_runner_adapter 标注 _legacy 存档",
    }

    # 输出报告
    report_dir = research_date_dir(report["date"])
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "r1_complete_e2e.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"报告: {report_path}")
    print(f"总计: {total} 标的 | 通过: {passed} | 失败: {total - passed} | 通过率: {report['summary']['pass_rate']}")
    print(f"状态: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print(f"{'='*60}")

    return report


if __name__ == "__main__":
    main()
