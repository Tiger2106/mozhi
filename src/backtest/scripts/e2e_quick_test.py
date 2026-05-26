"""
e2e_quick_test.py — E2E 快速验证
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
import numpy as np
from backtest.engine.knowledge_bridge import KnowledgeBridge
from backtest.methods.base import MethodResult

out = r'C:\Users\17699\mozhi_platform\src\backtest\knowledge_entries_v2'
os.makedirs(out, exist_ok=True)
bridge = KnowledgeBridge(output_dir=out, sync_to_bitable=False)

cases = [
    ("ma_cross", "601857", {"total_return_pct": 15.3, "sharpe_ratio": 1.85, "max_drawdown_pct": -5.2, "win_rate_pct": 62.0, "signal_ratio": 0.35, "n_trades": 12}, {"fast_period": 5, "slow_period": 20}),
    ("macd", "601857", {"total_return_pct": 20.1, "sharpe_ratio": 2.15, "max_drawdown_pct": -7.1, "win_rate_pct": 68.0, "signal_ratio": 0.42, "n_trades": 18}, {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
    ("ma_cross", "600028", {"total_return_pct": 8.7, "sharpe_ratio": 1.22, "max_drawdown_pct": -3.8, "win_rate_pct": 55.0, "signal_ratio": 0.28, "n_trades": 8}, {"fast_period": 5, "slow_period": 20}),
    ("bollinger", "", {"total_return_pct": 5.5, "sharpe_ratio": 0.95, "max_drawdown_pct": -2.1, "win_rate_pct": 52.0, "signal_ratio": 0.22, "n_trades": 6}, {"period": 20, "std_dev": 2}),
]

entries = []
for method_name, symbol, stats, params in cases:
    n = 100
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    signals = pd.DataFrame({
        "signal": np.random.choice([0, 1, -1], n, p=[0.6, 0.2, 0.2]),
        "confidence": np.random.uniform(0, 1, n),
    }, index=pd.DatetimeIndex(dates))
    result = MethodResult(signals=signals, method_name=method_name, params=params, statistics=stats)
    entry = bridge.harvest(result, method_name=method_name, symbol=symbol, config={
        "params": params,
        "timeframe": "1d",
        "tags": ["test", "e2e"],
        "source_run_id": "e2e_001",
    })
    entries.append(entry)
    print(f"OK | {method_name:10s} | {symbol or '(global)':8s} | return={entry.total_return:6.1f}% | sharpe={entry.sharpe:.2f} | confidence={entry.confidence:.3f}")

print(f"\n✅ {len(entries)} entries harvested to {out}")

# 打印第一条的JSON内容
e0 = entries[0]
print(f"\n--- {e0.method_name}/{e0.symbol} entry ---")
dump = {k: getattr(e0, k, None) for k in ["task_id", "method_name", "symbol", "regime", "timeframe", "total_return", "sharpe", "max_drawdown", "win_rate", "confidence", "insight_summary"]}
for k, v in dump.items():
    print(f"  {k}: {v}")
