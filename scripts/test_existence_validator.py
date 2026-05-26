#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_existence_validator.py — ExistenceValidator 测试脚本

测试用例:
  1. P6 FAIL: 84天/2笔交易（回测统计量不足）
  2. P7 PASS: N=1540天 IC 分析（全量日频因子观测）
  3. 空列表边界
  4. 单一样本
  5. 单一Regime
  6. 完全均匀分布
  7. 极端收益集中
  8. ExistenceResult 格式验证

作者：墨衡 (moheng)
创建时间：2026-05-19 16:00 GMT+8
"""

import sys
import os
import math
from datetime import date, datetime
from typing import Union

# 添加项目 src 到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.existence_validator import (
    TradeRecord,
    ExistenceResult,
    validate_existence,
)


# ============================================================
# 辅助函数
# ============================================================

def make_trade(d: Union[date, str], pnl: float, regime: str = "bull") -> TradeRecord:
    """快速创建 TradeRecord"""
    return TradeRecord(date=d, pnl_pct=pnl, regime=regime)


def print_result(label: str, result: ExistenceResult):
    """格式化输出测试结果"""
    status = "✅ PASS" if result.exists else "❌ FAIL"
    print(f"\n{'='*60}")
    print(f"  [{label}] {status}  (confidence={result.confidence})")
    print(f"{'='*60}")
    for k, v in sorted(result.details.items()):
        print(f"    {k}: {v}")
    if result.fail_reasons:
        print(f"  ❌ 未通过:")
        for r in result.fail_reasons:
            print(f"    - {r}")
    else:
        print(f"  ✅ 全部通过")
    return result


def verify_format(r: ExistenceResult, label: str) -> list[str]:
    """验证 ExistenceResult 格式规范"""
    errors = []
    # 类型检查
    if not isinstance(r.exists, bool):
        errors.append(f"[{label}] exists 应为 bool, 实际 {type(r.exists)}")
    if not isinstance(r.confidence, float):
        errors.append(f"[{label}] confidence 应为 float, 实际 {type(r.confidence)}")
    if not isinstance(r.fail_reasons, list):
        errors.append(f"[{label}] fail_reasons 应为 list, 实际 {type(r.fail_reasons)}")
    elif not all(isinstance(x, str) for x in r.fail_reasons):
        errors.append(f"[{label}] fail_reasons 元素应为 str")
    if not isinstance(r.details, dict):
        errors.append(f"[{label}] details 应为 dict, 实际 {type(r.details)}")
    # 范围检查
    if not (0.0 <= r.confidence <= 1.0):
        errors.append(f"[{label}] confidence 不在 [0,1] 范围内: {r.confidence}")
    # 一致性：exists=True 时 fail_reasons 应为空
    if r.exists and len(r.fail_reasons) > 0:
        errors.append(f"[{label}] exists=True 但 fail_reasons 不为空")
    if not r.exists and len(r.fail_reasons) == 0:
        errors.append(f"[{label}] exists=False 但 fail_reasons 为空")
    return errors


# ============================================================
# 测试用例
# ============================================================

def test_p6_fail():
    """
    P6 测试用例: 84天/2笔交易 ← 预期 FAIL
    
    数据来源: P6_position_comparison_601857_20260518.md
    回测周期: 2026-01-01 ~ 2026-05-14（84个交易日）
    交易记录: 仅 n5_fixed 组合产生 2 笔有效交易
    预期结果:
      - C1: 2 < 30 ❌
      - C2: 1 regime (仅 'bull') < 2 ❌
      - C3: 84天 < 730天(2年) ❌
      - C4: max占比 ~75.7% >= 40% ❌ (1盈1亏，利润集中于胜利方)
      - C5: 2/(84/365.25) ≈ 8.7 < 12 ❌
      - C6: 2笔分布于不同窗口，max=50% <= 50% ✅ (仅此项可能通过)
    """
    print("\n" + "★"*60)
    print("  [Test 1] P6 FAIL 用例: 84天/2笔交易")
    print("★"*60)

    # 84 个交易日 ≈ 134 个日历日 (2026-01-02 ~ 2026-05-14)
    # 2 笔交易分别位于时段首尾，确保 C3 和 C5 均判定失败
    trades = [
        make_trade("2026-01-02", +8.88, "bull"),
        make_trade("2026-05-12", -2.85, "bull"),
    ]

    result = validate_existence(trades)
    print_result("P6_FAIL", result)
    return result


def test_p7_pass():
    """
    P7 测试用例: N=1540天 IC 分析 ← 预期 PASS
    
    数据来源: P7_factor_ic_601857_20260518.md
    分析周期: 2020-01-02 ~ 2026-05-15（1540个交易日）
    观测记录: 每日 5因子 IC 计算结果，每交易日 1 条观测
    预期结果:
      - C1: 1540 >= 30 ✅
      - C2: 4 regimes >= 2 ✅
      - C3: ~6.36年 >= 2年 ✅
      - C4: IC 值 ~|0.04|，分布均匀，max占比 ≈ 1/1540 ≈ 0.06% < 40% ✅
      - C5: 1540/6.36 ≈ 242 >= 12 ✅
      - C6: 1540笔均匀分散于 10 窗口 ≈ 154/窗口，max=10% <= 50% ✅
    
    注意: 这里每个交易日生成 1 条观测（daily IC value）
    """
    print("\n" + "★"*60)
    print("  [Test 2] P7 PASS 用例: N=1540天 IC 分析")
    print("★"*60)

    n = 1540
    trades = []

    # 生成 1540 个交易日的观测数据
    # 起始: 2020-01-02, 结束: 2026-05-15
    # 使用 5 种 regime 标签映射不同时间段
    regime_map = {
        (0, 303): "bear",    # 2020-01~2021-01 COVID波动
        (304, 700): "range", # 2021-02~2022-11 震荡
        (701, 1100): "bull", # 2022-12~2024-06 上行
        (1101, 1400): "range", # 2024-07~2025-08 震荡
        (1401, n-1): "bull",  # 2025-09~2026-05 上行
    }

    # 实际交易历日期（跳过周末/节假日，近似模拟）
    start = date(2020, 1, 2)
    # 生成略多于 1540 天，取前 1540 个交易日
    # 简单模拟: 每个自然日增加，跳过周六日
    trading_days: list[date] = []
    d = start
    while len(trading_days) < n:
        if d.weekday() < 5:  # 周一至周五
            trading_days.append(d)
        from datetime import timedelta
        d += timedelta(days=1)

    trading_days = trading_days[:n]

    for i, td in enumerate(trading_days):
        # 确定 regime
        regime = "range"
        for (lo, hi), rg in regime_map.items():
            if lo <= i <= hi:
                regime = rg
                break
        # IC 值: 均值 ~0，标准差 ~0.04（基于 TrendQuality 的实测 IC 分布）
        # 使用简单伪随机（确定性序列）
        from hashlib import md5
        seed = md5(f"ic_{i}".encode()).hexdigest()
        ic_val = (int(seed[:8], 16) / 0xFFFFFFFF) * 0.16 - 0.08
        trades.append(TradeRecord(date=td, pnl_pct=ic_val, regime=regime))

    result = validate_existence(trades)
    print_result("P7_PASS", result)
    return result


def test_empty():
    """空列表边界"""
    print("\n" + "★"*60)
    print("  [Test 3] 边界: 空列表")
    print("★"*60)
    result = validate_existence([])
    print_result("EMPTY", result)
    return result


def test_single_sample():
    """单一观测"""
    print("\n" + "★"*60)
    print("  [Test 4] 边界: 单一观测")
    print("★"*60)
    trades = [make_trade("2026-01-15", +5.0, "bull")]
    result = validate_existence(trades)
    print_result("SINGLE", result)
    return result


def test_single_regime():
    """单一Regime 覆盖（30笔交易集中在1种状态）"""
    print("\n" + "★"*60)
    print("  [Test 5] 单Regime: 30笔 ≥ 30 ✅, 但 1 regime < 2 ❌")
    print("★"*60)
    from datetime import timedelta
    trades = []
    d = date(2025, 1, 15)
    for i in range(30):
        trades.append(make_trade(d, pnl=(+1.0 if i % 2 == 0 else -0.5), regime="bull"))
        d += timedelta(days=5)  # 每 5 天一笔，避开日期溢出
    result = validate_existence(trades)
    print_result("SINGLE_REGIME", result)
    return result


def test_uniform_distribution():
    """
    完全均匀分布: 120笔交易均匀分布在 10 年中
    预期: 全部通过 ✅
    """
    print("\n" + "★"*60)
    print("  [Test 6] 均匀分布: 120笔/10年/4 regimes → 全部通过")
    print("★"*60)

    regimes_list = ["bull", "bear", "range", "side"]
    from datetime import timedelta
    trades = []
    d = date(2020, 1, 15)
    for i in range(120):
        if d.weekday() >= 5:  # 跳过周末
            d += timedelta(days=1)
            continue
        trades.append(make_trade(d, pnl=+0.5, regime=regimes_list[i % 4]))
        d += timedelta(days=30)  # 每月一次

    result = validate_existence(trades)
    print_result("UNIFORM", result)
    return result


def test_extreme_concentration():
    """极端收益集中: 1笔占 99% 收益"""
    print("\n" + "★"*60)
    print("  [Test 7] 极端收益集中: 29笔微利 + 1笔巨盈")
    print("★"*60)
    from datetime import timedelta
    trades = []
    d = date(2025, 1, 15)
    for i in range(29):
        trades.append(make_trade(d, +0.01, "bull"))
        d += timedelta(days=10)
    trades.append(make_trade(date(2025, 3, 1), +99.0, "bull"))
    d = date(2026, 1, 10)
    for i in range(5):
        trades.append(make_trade(d, +0.02, "range"))
        d += timedelta(days=30)
    result = validate_existence(trades)
    print_result("EXTREME_CONCENTRATION", result)
    return result


# ============================================================
# 语义模糊案例（辅助理解而非通过/失败判定）
# ============================================================

def test_edge_cases():
    """
    边缘案例汇总:
    - 同一天多笔交易
    - PnL=0 的观测
    """
    print("\n" + "★"*60)
    print("  [Test 8] 边缘: 同日多笔 + PnL=0")
    print("★"*60)
    from datetime import timedelta
    trades = [
        make_trade("2026-01-15", 0.0, "bull"),
        make_trade("2026-01-15", 0.0, "bull"),
        make_trade("2026-01-15", 0.0, "bull"),
        make_trade("2026-01-16", +0.5, "bull"),
        make_trade("2026-06-15", +1.0, "range"),
        make_trade("2027-01-15", -0.3, "bear"),
        make_trade("2027-06-15", +0.8, "bull"),
        make_trade("2028-01-15", +0.2, "range"),
        make_trade("2028-06-15", -0.1, "bear"),
        make_trade("2029-01-15", +0.4, "bull"),
        make_trade("2029-06-15", +0.6, "range"),
        make_trade("2029-07-15", +0.3, "range"),
    ]
    result = validate_existence(trades)
    print_result("EDGE_CASES", result)
    return result


# ============================================================
# 格式验证
# ============================================================

def verify_all_formats(results: dict[str, ExistenceResult]) -> list[str]:
    """对所有测试结果执行格式验证"""
    all_errors = []
    for label, r in results.items():
        errors = verify_format(r, label)
        if errors:
            all_errors.extend(errors)
            for e in errors:
                print(f"  ⚠️  格式错误: {e}")
        else:
            print(f"  ✅ 格式 OK: {label}")
    return all_errors


# ============================================================
# 主入口
# ============================================================

def main():
    print("=" * 60)
    print("  ExistenceValidator Phase 0a MVP — 测试套件")
    print(f"  时间: {datetime.now().isoformat()}")
    print("=" * 60)

    # 执行所有测试
    r1 = test_p6_fail()
    r2 = test_p7_pass()
    r3 = test_empty()
    r4 = test_single_sample()
    r5 = test_single_regime()
    r6 = test_uniform_distribution()
    r7 = test_extreme_concentration()
    r8 = test_edge_cases()

    # 收集结果
    all_results = {
        "P6_FAIL": r1,
        "P7_PASS": r2,
        "EMPTY": r3,
        "SINGLE": r4,
        "SINGLE_REGIME": r5,
        "UNIFORM": r6,
        "EXTREME_CONC": r7,
        "EDGE_CASES": r8,
    }

    # 格式验证
    print("\n" + "=" * 60)
    print("  ExistenceResult 格式验证")
    print("=" * 60)
    fmt_errors = verify_all_formats(all_results)

    # 预期判定
    print("\n" + "=" * 60)
    print("  预期结果验证")
    print("=" * 60)

    checks = [
        ("P6_FAIL → exists=False", not r1.exists, True),
        ("P7_PASS → exists=True", r2.exists, True),
        ("P6_FAIL: C1 失败", any("C1" in r for r in r1.fail_reasons), True),
        ("P6_FAIL: C3 失败", any("C3" in r for r in r1.fail_reasons), True),
        ("P6_FAIL: C4 失败", any("C4" in r for r in r1.fail_reasons), True),
        ("P6_FAIL: C5 失败", any("C5" in r for r in r1.fail_reasons), True),
        ("P6_FAIL: C2 失败", any("C2" in r for r in r1.fail_reasons), True),
        ("UNIFORM → exists=True", r6.exists, True),
        ("SINGLE_REGIME: C2 失败", any("C2" in r for r in r5.fail_reasons), True),
        ("EMPTY: exists=False", not r3.exists, True),
        ("EMPTY: confidence=0.0", r3.confidence == 0.0, True),
    ]

    all_passed = True
    for label, actual, expected in checks:
        ok = actual == expected
        status = "✅" if ok else "❌"
        if not ok:
            all_passed = False
        print(f"  {status} {label} (expected={expected}, got={actual})")

    # 检查是否有格式错误
    if fmt_errors:
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("  ✅ 所有测试通过")
    else:
        print("  ❌ 存在未通过的测试")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
