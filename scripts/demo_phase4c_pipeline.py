#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_phase4c_pipeline.py — Phase 4c 端到端管线演示

演示流程:
  1. 输入策略参数 → 提交到 Phase4cInterface
  2. 自动运行 Q 层验证 (G1 ExistenceValidator, Q3 Regime, Q5 Temporal)
  3. 输出 Q 评级报告 (含评级 + 瓶颈分析 + 改进建议)

使用方式:
  python demo_phase4c_pipeline.py                  # 默认演示模式
  python demo_phase4c_pipeline.py --pipeline full  # 完整管线模式
  python demo_phase4c_pipeline.py --json           # 输出 JSON 报告到文件

作者: 墨衡 (moheng)
创建时间: 2026-05-19 17:45 +08:00
"""

import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.pipeline.phase4c_interface import (
    Phase4cInterface,
    ValidationReport,
    ValidationStatus,
    PIPELINE_CONFIG,
)


# ============================================================
# 示例策略参数
# ============================================================

# 示例 1: 网格短周期策略 (84 天, 2 笔交易)
GRID_SHORT = {
    "strategy_id": "grid_601857_n5_84d",
    "method": "grid",
    "symbol": "601857",
    "trades": [
        {"date": "2026-01-22", "pnl_pct": -0.001, "regime": "TREND_UP"},
        {"date": "2026-03-04", "pnl_pct": 0.055, "regime": "TREND_UP"},
    ],
    "market_regime": "TREND_UP",
    "backtest_days": 84,
    "params": {"n_levels": 5, "grid_type": "arithmetic", "cooldown_bars": 1},
}

# 示例 2: 因子长周期策略 (6 年, 5 因子 IC 数据)
FACTOR_LONG = {
    "strategy_id": "factor_5factor_601857_6y",
    "method": "factor",
    "symbol": "601857",
    "ic_data": [{"date": f"202{i}-01-02", "ic": 0.032 * (1 if i % 2 == 0 else -1)} for i in range(6)],
    "perf_by_regime": {
        "TREND_UP": 5.2, "TREND_DOWN": -1.3,
        "SIDEWAYS": 3.8, "HIGH_VOL": 1.5,
        "LOW_VOL": 0.8,
    },
    "backtest_days": 1540,
    "params": {"factors": ["TrendQuality", "VWAP_dev", "Volume_ratio", "ATR_ratio", "OBV_change"]},
}

# 示例 3: P7 因子 IC 完整数据 (1540 天仿真)
FACTOR_FULL = {
    "strategy_id": "p7_factor_ic_replica",
    "method": "factor",
    "symbol": "601857",
    "pnl_data": [
        {"date": f"202{i % 6}-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}", "pnl_pct": 0.01 * ((i % 5) - 2)}
        for i in range(500)
    ],
    "trades": [
        {"date": "2024-03-15", "pnl_pct": 1.2, "regime": "TREND_UP"},
        {"date": "2024-06-20", "pnl_pct": 0.8, "regime": "TREND_UP"},
        {"date": "2024-09-10", "pnl_pct": -0.3, "regime": "SIDEWAYS"},
        {"date": "2025-01-08", "pnl_pct": 2.1, "regime": "TREND_UP"},
        {"date": "2025-04-22", "pnl_pct": 1.5, "regime": "HIGH_VOL"},
        {"date": "2025-07-01", "pnl_pct": -0.5, "regime": "TREND_DOWN"},
        {"date": "2025-10-14", "pnl_pct": 0.9, "regime": "SIDEWAYS"},
        {"date": "2026-01-06", "pnl_pct": 0.3, "regime": "TREND_UP"},
        {"date": "2026-02-18", "pnl_pct": -0.1, "regime": "SIDEWAYS"},
        {"date": "2026-04-01", "pnl_pct": 0.6, "regime": "LOW_VOL"},
        {"date": "2026-05-01", "pnl_pct": 1.1, "regime": "TREND_UP"},
        {"date": "2026-05-10", "pnl_pct": 0.4, "regime": "TREND_UP"},
    ],
    "market_regime": "MIXED",
    "backtest_days": 1540,
    "params": {"n_trades": 12, "regime_coverage": 5, "years": 6.4},
}

# 示例 4: 批量提交用
GRID_BATCH = {
    "strategy_id": "grid_601857_n10_84d",
    "method": "grid",
    "symbol": "601857",
    "trades": [
        {"date": "2026-02-10", "pnl_pct": 0.02, "regime": "TREND_UP"},
        {"date": "2026-02-25", "pnl_pct": -0.01, "regime": "TREND_UP"},
        {"date": "2026-03-15", "pnl_pct": 0.015, "regime": "SIDEWAYS"},
    ],
    "market_regime": "MIXED",
    "backtest_days": 84,
    "params": {"n_levels": 10, "grid_type": "geometric"},
}


# ============================================================
# 报告格式化
# ============================================================

def format_q_rating_table(results: list[dict]) -> str:
    """格式化 Q 评级汇总表"""
    lines = [
        "",
        " Q 评级汇总",
        "=" * 60,
        f" {'策略 ID':<30} {'状态':<10} {'评级':<6} {'瓶颈':<15}",
        f" {'-'*30} {'-'*10} {'-'*6} {'-'*15}",
    ]
    for r in results:
        lines.append(
            f" {r['strategy_id'][:28]:<30} {r['status']:<10} "
            f"{r['rating']:<6} {r['bottleneck'][:13]:<15}"
        )
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
# 主演示
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 4c 端到端管线演示",
    )
    parser.add_argument("--pipeline", choices=list(PIPELINE_CONFIG.keys()),
                        default="default", help="验证管线配置")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON 报告到文件")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式：仅演示 grid_short 策略")

    args = parser.parse_args()

    interface = Phase4cInterface(
        auto_run=True,
        use_adaptive_thresholds=True,
        pipeline_name=args.pipeline,
    )

    pipeline_v = interface.get_active_pipeline()

    print(f"\n{'=' * 60}")
    print(f"  Phase 4c 端到端管线演示")
    print(f"  管线段: {args.pipeline}")
    print(f"  激活验证器: {', '.join(pipeline_v)}")
    print(f"{'=' * 60}\n")

    # ——— Step 1: 选择策略 ———
    if args.quick:
        strategies = [("grid_short (84d, n=2)", GRID_SHORT)]
    else:
        strategies = [
            ("grid_short (84d, n=2)", GRID_SHORT),
            ("factor_full (6y, n=12)", FACTOR_FULL),
            ("fact_long (6y IC, n=6)", FACTOR_LONG),
            ("grid_batch (84d, n=3)", GRID_BATCH),
        ]

    results = []

    for name, params in strategies:
        print(f"  📤 提交: {name}")

        try:
            task_id = interface.submit_for_validation(params)
            status = interface.get_validation_status(task_id)
            print(f"     task_id: {task_id[:16]}...")
            print(f"     状态: {status.value}")

            if status == ValidationStatus.COMPLETED:
                report = interface.get_validation_report(task_id)
                q_report = interface.generate_q_report(task_id)

                results.append({
                    "strategy_id": params.get("strategy_id", name),
                    "task_id": task_id,
                    "status": q_report["rating"],
                    "rating": q_report["rating"],
                    "bottleneck": q_report["bottleneck"],
                    "overall_passed": report["overall_passed"],
                })

                # 打印简要结果
                print(f"     综合通过: {'✅' if report['overall_passed'] else '❌'} "
                      f"{report['overall_passed']}")
                print(f"     Q 评级: {q_report['rating']}")
                print(f"     瓶颈: {q_report['bottleneck']}")

                if report["fail_reasons"]:
                    for r in report["fail_reasons"]:
                        print(f"     ❌ {r}")
            else:
                print(f"     ⚠️  状态: {status}")

        except Exception as exc:
            print(f"     ❌ 异常: {exc}")

        print()

    # ——— Q 评级汇总表 ———
    if results:
        print(format_q_rating_table(results))

    # ——— 待实现验证器 ———
    pending = interface.pending_validators()
    if pending:
        print(f"\n  ⏳ 待实现验证器:")
        for vname, vdesc in pending.items():
            print(f"     {vname}: {vdesc}")

    # ——— JSON 输出 ———
    if args.json and results:
        json_path = Path("phase4c_demo_report.json")
        json_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n  ✅ JSON 报告已保存: {json_path}")

    interface.close()
    print(f"\n{'=' * 60}")
    print(f"  ✅ Phase 4c 管线演示完成")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
