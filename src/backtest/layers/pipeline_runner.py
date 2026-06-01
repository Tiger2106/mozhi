"""
Pipeline Runner — 三层分离一站式回测
====================================
DataLayer → ComputeLayer → SimulateLayer

使用示例:
    from backtest.layers.pipeline_runner import run_backtest

    result = run_backtest(
        symbol="601857.SH",
        start_date="20200101",
        end_date="20260515",
        strategy_type="ma_cross",
        strategy_params={"fast": 5, "slow": 20},
        initial_capital=1_000_000,
    )
    print(result.metrics)
"""
from typing import Dict, Any, Optional

from .data_layer import DataLayer
from .compute_layer import ComputeEngine, MaCrossoverStrategy
from .simulate_layer import ConstraintAwareExecutor, SimulateResult
from ..p0_fixes.lookahead_guard import LookaheadGuard
from ..contracts.backtest_data_contract import BacktestData


def run_backtest(
    symbol: str = "601857.SH",
    start_date: str = "20200101",
    end_date: str = "20260515",
    strategy_type: str = "ma_cross",
    strategy_params: Optional[Dict[str, Any]] = None,
    initial_capital: float = 1_000_000.0,
    fee_rate: float = 0.0003,
    slippage_rate: float = 0.001,
    min_fee: float = 5.0,
    run_guard: bool = True,
) -> SimulateResult:
    """三层一站式回测入口（GP-003 回归对比框架）

    执行流程:
    1. DataLayer → BacktestData (含指纹)
    2. LookaheadGuard 前视偏差检测
    3. ComputeLayer → List[Signal]
    4. ConstraintAwareExecutor → SimulateResult

    Returns:
        SimulateResult（含完整交易日志、净值曲线、指标）
    """
    if strategy_params is None:
        strategy_params = {"fast": 5, "slow": 20}

    # ── Step 1: 数据层 ──
    dl = DataLayer()
    data = dl.load(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )

    print(f"[DataLayer] Loaded {data.total_bars} bars, "
          f"fingerprint={data.data_fingerprint}")

    # ── Lookahead Guard ──
    if run_guard:
        guard = LookaheadGuard()
        guard.check_data_contract(data)
        guard.check_static_bias(data, [])
        guard_result = guard.get_summary()
        print(f"[LookaheadGuard] {guard_result}")
        if not guard._passed:
            print("[WARN] Lookahead check failed — signals may be affected")

    # ── Step 2: 计算层 ──
    if strategy_type == "ma_cross":
        strategy = MaCrossoverStrategy(
            fast=strategy_params.get("fast", 5),
            slow=strategy_params.get("slow", 20),
            position_ratio=strategy_params.get("position_ratio", 0.3),
            stop_loss=strategy_params.get("stop_loss", 0.05),
        )
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

    engine = ComputeEngine(strategy=strategy)
    signals = engine.compute(data, initial_capital=initial_capital)
    print(f"[ComputeLayer] Generated {len(signals)} signals")

    # ── Step 3: 模拟层 ──
    executor = ConstraintAwareExecutor(
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        min_fee=min_fee,
    )
    result = executor.execute_signals(data, signals, initial_capital)
    print(f"[SimulateLayer] Total trades: {result.total_trades}")

    # 打印关键指标
    m = result.metrics
    print(f"\n{'='*50}")
    print(f"  Total Return: {m.get('total_return_pct', 0):.4f}%")
    print(f"  Win Rate:     {m.get('win_rate_pct', 0):.2f}%")
    print(f"  Trades:       {m.get('total_trades', 0)}")
    if result.warnings:
        print(f"  Warnings:     {len(result.warnings)}")
        for w in result.warnings[:3]:
            print(f"    - {w}")
    print(f"{'='*50}")

    return result


def compare_with_baseline(
    result: SimulateResult,
    baseline_path: str = None,
    tolerance: float = 0.01,
) -> bool:
    """GP-003: 回归对比

    对比当前回测结果与黄金基线。
    如果路径为空，默认读取 baselines 目录下的最新基线。

    Args:
        result: 当前回测结果
        baseline_path: 基线文件路径
        tolerance: 容差（百分比，默认 1%）

    Returns:
        bool: 是否通过回归对比
    """
    import json, os
    from pathlib import Path

    ROOT = Path(r"C:\Users\17699\mozhi_platform")

    if baseline_path is None:
        # 自动查找最新基线
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
    passed = diff_pct <= tolerance * abs(bl_return) if bl_return != 0 else diff_pct <= tolerance

    print(f"[Baseline] 当前: {cur_return:.4f}% vs 基线: {bl_return:.4f}%")
    print(f"[Baseline] 差异: {diff_pct:.4f}pct, 容差: {tolerance*100:.0f}%")
    print(f"[Baseline] 回归对比: {'✅ PASS' if passed else '❌ FAIL'}")

    return passed
