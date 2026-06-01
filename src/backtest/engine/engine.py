"""
Engine — 回测入口 (三层一站式接口)
====================================
BT-001 三层分离: DataLayer → ComputeLayer → SimulateLayer

完整执行流程:
    1. DataLayer.load() → BacktestData (含指纹 + 校验)
    2. LookaheadRuntimeGuard.check() → 前视偏差检测
    3. ComputeLayer.compute() → List[Signal]
    4. SimLayer.simulate() → SimulateResult (含交易日志 + 指标)

用法:
    from engine.engine import run_backtest
    result = run_backtest(symbol="601857.SH", start="20200101", end="20260515")

作者: moheng
版本: v1.0
"""
from typing import Dict, Any, Optional, List
from pathlib import Path

from .data_layer import DataLayer, LookaheadRuntimeGuard
from .calc_layer import compute as compute_signals
from .sim_layer import simulate as run_simulation, SimulateResult
from .sim_layer.simulator import TradeRecord, PositionSnapshot


def run_backtest(
    symbol: str = "601857.SH",
    start: str = "20200101",
    end: str = "20260515",
    strategy_type: str = "ma_cross",
    strategy_params: Optional[Dict[str, Any]] = None,
    initial_capital: float = 1_000_000.0,
    fee_rate: float = 0.0003,
    slippage_rate: float = 0.001,
    min_fee: float = 5.0,
    stamp_tax_rate: float = 0.0005,
    enable_guard: bool = True,
    verbose: bool = True,
) -> SimulateResult:
    """一站式回测入口

    Args:
        symbol: 股票代码
        start: 起始日期 (YYYYMMDD)
        end: 结束日期 (YYYYMMDD)
        strategy_type: 策略类型 ("ma_cross")
        strategy_params: 策略参数字典
        initial_capital: 初始资金
        fee_rate: 手续费率
        slippage_rate: 滑点率
        min_fee: 最低手续费
        enable_guard: 是否启用前视偏差检测
        verbose: 是否打印执行信息

    Returns:
        SimulateResult（含完整交易日志、净值曲线、指标）

    三层执行流程:
        DataLayer → 一次性加载数据+校验+指纹
        ComputeLayer → 信号计算（GP-002/GP-004）
        SimLayer → 模拟交易（BT-008约束叠加+P0修复）
    """
    if strategy_params is None:
        strategy_params = {"fast": 5, "slow": 20}

    # ── Step 1: 数据层 ──
    dl = DataLayer()
    data = dl.load(symbol=symbol, start_date=start, end_date=end)

    if verbose:
        print(f"[DataLayer] Loaded {data.total_bars} bars, "
              f"fingerprint={data.data_fingerprint}")

    # ── 指纹完整性验证 ──
    if not data.verify_fingerprint():
        err_msg = (
            f"[Fingerprint] ❌ 数据指纹不匹配！"
            f"  expected={data.data_fingerprint}, "
            f"computed={data.compute_fingerprint()}"
        )
        raise ValueError(err_msg)
    elif verbose:
        print(f"[Fingerprint] ✅ 指纹验证通过: {data.data_fingerprint}")

    # ── Guard: 前视偏差检测 ──
    if enable_guard:
        guard = LookaheadRuntimeGuard()
        warnings = guard.check(data)
        if warnings:
            if verbose:
                for w in warnings:
                    print(f"[Guard] {w}")
        elif verbose:
            print("[Guard] PASS - 前视偏差检测通过")

    # ── Step 2: 计算层 ──
    signals = compute_signals(
        data=data,
        strategy_type=strategy_type,
        strategy_params=strategy_params,
        initial_capital=initial_capital,
    )

    if verbose:
        print(f"[ComputeLayer] Generated {len(signals)} signals "
              f"(strategy={strategy_type})")

    # ── Step 3: 模拟层 ──
    result = run_simulation(
        data=data,
        signals=signals,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        min_fee=min_fee,
        stamp_tax_rate=stamp_tax_rate,
    )

    if verbose:
        m = result.metrics
        print(f"[SimulateLayer] Trades: {result.total_trades}")
        print(f"  Total Return: {m.get('total_return_pct', 0):.4f}%")
        print(f"  Win Rate:     {m.get('win_rate_pct', 0):.2f}%")
        print(f"  Final Capital: {m.get('final_capital', 0):.2f}")

    return result


def compare_with_baseline(
    result: SimulateResult,
    baseline_path: Optional[str] = None,
    tolerance: float = 0.01,
) -> bool:
    """GP-003: 与黄金基线回归对比

    读取 experiments/baselines/ 下的基线 JSON，
    对比核心指标是否在容差范围内。

    Args:
        result: 当前回测结果
        baseline_path: 基线 JSON 路径（None=自动查找最新）
        tolerance: 容差（1% = 0.01）

    Returns:
        bool: 是否通过回归对比
    """
    import json, os

    ROOT = Path(r"C:\Users\17699\mozhi_platform")

    if baseline_path is None:
        baselines_dir = ROOT / "experiments" / "baselines"
        files = list(baselines_dir.glob("backtest_golden_baseline_*.json"))
        if not files:
            print("[Baseline] 未找到黄金基线文件")
            return False
        baseline_path = str(max(files, key=os.path.getctime))

    print(f"[Baseline] 加载基线: {baseline_path}")
    with open(baseline_path) as f:
        baseline = json.load(f)

    bl_metrics = baseline["output"]["metrics"]
    cur_return = result.metrics.get("total_return_pct", 0)
    bl_return = bl_metrics.get("total_return_pct", 0)

    diff_pct = abs(cur_return - bl_return)
    passed = (
        diff_pct <= tolerance * abs(bl_return)
        if bl_return != 0
        else diff_pct <= tolerance
    )

    print(f"[Baseline] 当前: {cur_return:.4f}% vs 基线: {bl_return:.4f}%")
    print(f"[Baseline] 差异: {diff_pct:.4f}pct, 容差: {tolerance*100:.0f}%")
    print(f"[Baseline] 回归对比: {'✅ PASS' if passed else '❌ FAIL'}")

    return passed
