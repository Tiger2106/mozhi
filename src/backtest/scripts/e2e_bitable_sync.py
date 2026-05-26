"""
e2e_bitable_sync.py — KnowledgeBridge → Bitable E2E 验证脚本

运行：python -m backtest.scripts.e2e_bitable_sync

作者: 墨涵（E2E测试）
创建时间: 2026-05-17
"""

import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.engine.knowledge_bridge import KnowledgeBridge
from backtest.engine.knowledge_entry import KnowledgeEntry
from backtest.methods.base import MethodResult


def make_test_bars(n=120):
    """创建模拟OHLC数据"""
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close - np.random.rand(n) * 0.5,
        "high": close + np.random.rand(n) * 1.0,
        "low": close - np.random.rand(n) * 1.0,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
    }, index=pd.DatetimeIndex(dates, name="date"))


def make_result(method_name, symbol, statistics, params=None, n=60):
    """创建 MethodResult"""
    df = make_test_bars(n)
    signals = pd.DataFrame({
        "signal": [0] * n,
        "confidence": [0.0] * n,
    }, index=df.index)
    
    # 生成一些交易信号（20% 仓位信号）
    n_sig = max(1, n // 5)
    sig_indices = np.random.choice(range(n), n_sig, replace=False)
    for idx in sig_indices:
        signals.iloc[idx, 0] = np.random.choice([1, -1])
        signals.iloc[idx, 1] = np.random.uniform(0.3, 1.0)
    
    return MethodResult(
        signals=signals,
        method_name=method_name,
        params=params or {},
        statistics=statistics,
    )


def main():
    print("=" * 60)
    print("KnowledgeBridge → Bitable E2E 验证")
    print("=" * 60)
    
    # 创建桥（output_dir 用于本地JSON存档）
    output_dir = os.path.join(os.path.dirname(__file__), "..", "knowledge_entries_v2")
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n📁 JSON输出目录: {output_dir}")
    
    # Bitable 配置
    bitable_config = {
        "app_token": "RGmrb7sNoaRMz5syt2jcgOWNnnE",
        "table_id": "tblXP7Jf9hNQ50Nl",
    }
    
    bridge = KnowledgeBridge(
        output_dir=output_dir,
        sync_to_bitable=True,
        bitable_config=bitable_config,
    )
    
    # 创建多个测试结果
    test_cases = [
        ("ma_cross", "601857", {"total_return_pct": 15.3, "sharpe_ratio": 1.85, "max_drawdown_pct": -5.2, "win_rate_pct": 62.0, "signal_ratio": 0.35, "n_trades": 12}),
        ("ma_cross", "600028", {"total_return_pct": 8.7, "sharpe_ratio": 1.22, "max_drawdown_pct": -3.8, "win_rate_pct": 55.0, "signal_ratio": 0.28, "n_trades": 8}),
        ("ma_cross", "", {"total_return_pct": 12.0, "sharpe_ratio": 1.55, "max_drawdown_pct": -4.5, "win_rate_pct": 60.0, "signal_ratio": 0.30, "n_trades": 10}),
        ("macd", "601857", {"total_return_pct": 20.1, "sharpe_ratio": 2.15, "max_drawdown_pct": -7.1, "win_rate_pct": 68.0, "signal_ratio": 0.42, "n_trades": 18}),
        ("bollinger", "600028", {"total_return_pct": 5.5, "sharpe_ratio": 0.95, "max_drawdown_pct": -2.1, "win_rate_pct": 52.0, "signal_ratio": 0.22, "n_trades": 6}),
    ]
    
    results = []
    for method_name, symbol, stats in test_cases:
        print(f"\n  🧪 {method_name} / {symbol or '(global)'}...")
        result = make_result(method_name, symbol, stats)
        
        params = {"period": 30}
        if method_name == "ma_cross":
            params = {"fast_period": 5, "slow_period": 20}
        elif method_name == "macd":
            params = {"fast_period": 12, "slow_period": 26, "signal_period": 9}
        elif method_name == "bollinger":
            params = {"period": 20, "std_dev": 2}
        
        entry = bridge.harvest(
            result,
            method_name=method_name,
            symbol=symbol,
            config={
                "params": params,
                "timeframe": "1d",
                "tags": ["test", "e2e"],
                "source_run_id": "e2e_001",
            },
        )
        
        results.append(entry)
        print(f"    ✅ {entry.symbol} | return={entry.total_return}% | sharpe={entry.sharpe} | confidence={entry.confidence:.3f}")
    
    print(f"\n{'=' * 60}")
    print(f"📊 共 {len(results)} 条知识条目已写入:")
    print(f"   - JSON: {output_dir}")
    print(f"   - Bitable: https://my.feishu.cn/base/RGmrb7sNoaRMz5syt2jcgOWNnnE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
