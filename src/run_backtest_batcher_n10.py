"""
运行 Grid batcher n10 回测 for 601857.SH
并验证 knowledge.db 写入 equity_series + trades
"""
import sys, os
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src")

from backtest.strategies.run_grid import (
    run_grid_backtest, GridRunnerConfig, make_grid_config,
)
from backtest.strategies.grid_strategy import (
    StaticGridSignal, GridConfig,
)
from backtest.pipeline.knowledge_db import KnowledgeDB

# ── 创建信号 ────────────────────────────────────────────────
signal = StaticGridSignal(
    grid_config=GridConfig(
        lower_bound=2.512,
        upper_bound=14.25,
        n_levels=10,
        grid_type="geometric",
        cool_down_bars=5,
    ),
)

# ── 创建配置 ────────────────────────────────────────────────
cfg = make_grid_config(
    symbol="601857.SH",
    signal=signal,
    position_mode="batcher",
    position_kwargs={
        "total_grid_rows": 10,
        "tiers": [
            {"level_from": 0.0, "level_to": 0.33, "ratio": 0.5},
            {"level_from": 0.33, "level_to": 0.66, "ratio": 0.3},
            {"level_from": 0.66, "level_to": 1.0, "ratio": 0.2},
        ],
    },
    risk_config={
        "cool_down": {"cool_down_bars": 3},
    },
    initial_capital=1_000_000,
    fee_rate=0.0003,
    slippage_rate=0.001,
    tag="static_n10_geometric_batcher_cd3",
)

# ── 运行时初始化 knowledge.db ──────────────────────────────
kdb = KnowledgeDB()
kdb.initialize()
kdb.close()

# ── 运行回测 ────────────────────────────────────────────────
print("=" * 60)
print("运行 Grid batcher n10 回测: 601857.SH")
print("=" * 60)

result = run_grid_backtest(cfg)

MI = result.metrics
print("\n=== 绩效指标 ===")
for key, label in [
    ("annual_return_pct", "年化收益率"),
    ("max_drawdown_pct", "最大回撤"),
    ("sharpe_ratio", "夏普比率"),
    ("total_return_pct", "总收益率"),
    ("win_rate_pct", "胜率"),
    ("total_trades", "交易次数"),
    ("profit_loss_ratio", "盈亏比"),
]:
    val = MI.get(key)
    if val is None:
        print(f"  {label}: N/A")
    else:
        print(f"  {label}: {val:.2f}" if isinstance(val, float) else f"  {label}: {val}")

# ── 验证 knowledge.db ────────────────────────────────────
print("\n=== 验证 knowledge.db ===")
kdb = KnowledgeDB()
equity_count = kdb._conn().__enter__().execute(
    "SELECT COUNT(*) FROM backtest_equity_series"
).fetchone()[0]
trades_count = kdb._conn().__enter__().execute(
    "SELECT COUNT(*) FROM backtest_trades"
).fetchone()[0]
print(f"  backtest_equity_series: {equity_count} 条记录")
print(f"  backtest_trades: {trades_count} 条记录")

# 获取最新 run_id
run_id = kdb.get_latest_run_id(strategy="grid", symbol="601857.SH")
if run_id:
    print(f"  最新 run_id: {run_id}")
    # 验证 equity 数据
    eq_rows = kdb.get_equity_series(run_id)
    print(f"  run_id {run_id} 的净值曲线: {len(eq_rows)} 条")
    if eq_rows:
        print(f"    第一条: date={eq_rows[0]['date']}, equity={eq_rows[0]['equity']:.2f}, nav={eq_rows[0]['nav']:.4f}")
        print(f"    最后一条: date={eq_rows[-1]['date']}, equity={eq_rows[-1]['equity']:.2f}, nav={eq_rows[-1]['nav']:.4f}")
    td_rows = kdb.get_trades(run_id)
    print(f"  run_id {run_id} 的交易明细: {len(td_rows)} 条")
else:
    print("  ⚠️ 未找到 run_id")

kdb.close()
print("\n✅ 回测完成!")
