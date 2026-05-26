"""
R1 阶段一 — E2E 验证脚本

在 5 只标的上跑完整因子链：
  market_data → 6 因子族 → 因子仓库注册
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# 确保 src 在路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.data.market_data_adapter import (
    fetch_price_volume,
    validate_dataframe,
)
from src.backtest.factors.volume.vwap_factor import (
    calc_vwap,
    calc_vwap_deviation,
    calc_multi_vwap,
)
from src.backtest.factors.volume.volume_profile_factor import (
    calc_volume_profile,
    calc_lvn,
)
from src.backtest.factors.trend.trend_quality_factor import (
    calc_adx,
    calc_trend_strength,
    calc_trend_consistency,
)
from src.backtest.factors.regime.regime_factor import classify_regime
from src.backtest.factors.volume.volume_flow_factor import (
    calc_smart_money_score,
    calc_volume_trend,
    calc_volume_ratio,
)
from src.backtest.factors.structure.structure_factor import (
    calc_support_resistance,
    calc_structure_quality,
)
from src.backtest.factors.factor_cache import (
    cached_factor_calc,
    list_cache_stats,
)
from pipeline_paths import (
    R1_BENCHMARK_SYMBOLS,
    research_report_dir,
)


def run_e2e() -> dict:
    """运行全链路 E2E 验证，返回结果报告。"""
    today_str = date.today().strftime("%Y%m%d")
    report = {
        "validation_date": today_str,
        "test_id": f"e2e_phase1_{today_str}",
        "symbols_tested": [],
        "symbols_passed": [],
        "symbols_failed": [],
        "factor_results": {},
        "summary": {},
    }

    for symbol in R1_BENCHMARK_SYMBOLS:
        print(f"\n{'='*60}")
        print(f"验证标的: {symbol}")
        print(f"{'='*60}")

        symbol_result = _validate_symbol(symbol)
        report["symbols_tested"].append(symbol)
        report["factor_results"][symbol] = symbol_result

        if symbol_result["passed"]:
            report["symbols_passed"].append(symbol)
            print(f"  ✅ {symbol} 通过")
        else:
            report["symbols_failed"].append(symbol)
            print(f"  ❌ {symbol} 失败: {symbol_result.get('error', 'unknown')}")

    total = len(report["symbols_tested"])
    passed = len(report["symbols_passed"])
    report["summary"] = {
        "total_symbols": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{passed / total * 100:.1f}%",
        "timestamp": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
    }

    # 缓存统计
    try:
        report["cache_stats"] = list_cache_stats()
    except Exception:
        report["cache_stats"] = {"error": "cache stats unavailable"}

    return report


def _validate_symbol(symbol: str) -> dict:
    """验证单个标的的全因子链。"""
    result = {
        "symbol": symbol,
        "passed": False,
        "error": None,
        "data_shape": None,
        "factors": {},
    }

    try:
        # ── Step 1: 获取数据 ──────────────────────
        df = fetch_price_volume(symbol)
        valid, issues = validate_dataframe(df)
        if not valid:
            result["error"] = f"数据验证失败: {issues}"
            return result

        result["data_shape"] = list(df.shape)
        print(f"  📊 数据形状: {df.shape}, 列: {list(df.columns)}")

        # ── Step 2: VWAP 因子 ─────────────────────
        vwap_series = calc_vwap(df)
        vwap_dev = calc_vwap_deviation(df)
        multi_vwap = calc_multi_vwap(df, windows=[5, 10, 20])
        result["factors"]["vwap"] = {
            "shape": len(vwap_series),
            "last_vwap": round(float(vwap_series.iloc[-1]), 4),
            "last_deviation": round(float(vwap_dev.iloc[-1]), 4),
            "multi_keys": list(multi_vwap.keys()),
        }
        print(f"  ✅ VWAP: last={result['factors']['vwap']['last_vwap']}")

        # ── Step 3: Volume Profile ─────────────────
        vp = calc_volume_profile(df)
        lvn = calc_lvn(df)
        result["factors"]["volume_profile"] = {
            "poc": vp["poc"],
            "vah": vp["vah"],
            "val": vp["val"],
            "value_area_pct": vp["value_area_pct"],
            "lvn_count": len(lvn),
        }
        print(f"  ✅ Volume Profile: POC={vp['poc']:.2f}")

        # ── Step 4: Trend Quality ────────────────
        adx = calc_adx(df, period=14)
        ts = calc_trend_strength(adx)
        tc = calc_trend_consistency(df, lookback=10)
        last_adx_valid = float(adx.dropna().iloc[-1]) if len(adx.dropna()) > 0 else None
        result["factors"]["trend_quality"] = {
            "last_adx": last_adx_valid,
            "last_strength": float(ts.dropna().iloc[-1]) if len(ts.dropna()) > 0 else None,
            "last_consistency": float(tc.dropna().iloc[-1]) if len(tc.dropna()) > 0 else None,
        }
        print(f"  ✅ Trend Quality: ADX={last_adx_valid:.2f}")

        # ── Step 5: Regime ──────────────────────
        regime_result = classify_regime(df)
        result["factors"]["regime"] = {
            "regime": regime_result["regime"],
            "confidence": regime_result["confidence"],
        }
        print(f"  ✅ Regime: {regime_result['regime']} (conf={regime_result['confidence']:.3f})")

        # ── Step 6: Volume Flow ────────────────
        sms = calc_smart_money_score(df, lookback=10)
        vt = calc_volume_trend(df, period=20)
        vr = calc_volume_ratio(df)
        result["factors"]["volume_flow"] = {
            "smart_money_score_mean": round(float(sms.mean()), 4),
            "volume_trend_last": round(float(vt.iloc[-1]), 4),
            "volume_ratio_last": round(float(vr.iloc[-1]), 4),
        }
        print(f"  ✅ Volume Flow: SMS_mean={result['factors']['volume_flow']['smart_money_score_mean']:.3f}")

        # ── Step 7: Structure ──────────────────
        sr = calc_support_resistance(df, lookback=60)
        sq = calc_structure_quality(df, lookback=30)
        result["factors"]["structure"] = {
            "support_count": len(sr["support"]),
            "resistance_count": len(sr["resistance"]),
            "structure_quality": float(sq),
        }
        print(f"  ✅ Structure: quality={sq:.4f}")

        # ── Step 8: Cache layer ──────────────
        def _demo_calc(x):
            return x * 2

        cached_result = cached_factor_calc(
            f"demo_{symbol}", _demo_calc, 42, ttl=3600
        )
        result["factors"]["cache"] = {
            "demo_cache_result": cached_result,
        }
        print(f"  ✅ Cache: demo={cached_result}")

        result["passed"] = True

    except Exception as e:
        result["error"] = str(e)
        import traceback
        result["traceback"] = traceback.format_exc()
        print(f"  ❌ 异常: {e}")

    return result


if __name__ == "__main__":
    print("🚀 R1 阶段一 E2E 验证开始")
    print(f"   标的列表: {R1_BENCHMARK_SYMBOLS}")

    report = run_e2e()

    # 写入报告
    report_dir = research_report_dir()
    report_path = report_dir / "e2e_phase1_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"📊 E2E 验证报告已写入: {report_path}")
    print(f"  总计: {report['summary']['total_symbols']} 只标的")
    print(f"  通过: {report['summary']['passed']} ✅")
    print(f"  失败: {report['summary']['failed']} ❌")
    print(f"  通过率: {report['summary']['pass_rate']}")
    print(f"{'='*60}")
