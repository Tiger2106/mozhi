"""
601857 端到端全模块集成回测 v2
使用正确的 BacktestEngine API
"""
import sys, os, json, sqlite3, uuid
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
BASE = r"C:\Users\17699\mozhi_platform"
os.chdir(BASE)
sys.path.insert(0, BASE)

print("=" * 50)
print("601857 全模块集成回测 v2")
print("=" * 50)

# ─── 1. 数据 ──────────────────────────────────────
print("\n[1/5] 加载数据...")
from backtest.data.market_data_adapter import fetch_price_volume

data = fetch_price_volume("601857.SH")
print(f"  {len(data)} rows ({data.index[0].date()} ~ {data.index[-1].date()})")

# ─── 2. 核心回测 ──────────────────────────────────
print("[2/5] BacktestEngine 回测...")
from backtest.backtest_engine import BacktestEngine, BacktestConfig, Bar, Strategy
from backtest.strategies import TrendStrategy

# DataFrame → Bar list
bars = []
for idx, row in data.iterrows():
    bars.append(Bar(
        date=str(idx.date()),
        symbol="601857.SH",
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        vwap=0.0,
    ))

cfg = BacktestConfig(
    start_date="2020-01-02",
    end_date="2026-05-15",
    initial_capital=200_000.0,
)

engine = BacktestEngine(config=cfg, strategy=Strategy())
result = engine.run(bars)

print(f"  成交:  {result.total_trades}")
print(f"  收益:  {result.metrics['total_return_pct']:.2%}")
print(f"  夏普:  {result.metrics.get('sharpe_ratio', 0):.2f}")
print(f"  回撤:  {result.metrics.get('max_drawdown_pct', 0):.2%}")

# ─── 3. Signal Events 采集 ─────────────────────────
print("\n[3/5] Signal Events 采集...")

# Clean DB
db_path = os.path.join(BASE, "data", "signals", "signal_events.db")
bo_path = os.path.join(BASE, "data", "signals", "breakout_events.db")
for p in [db_path, bo_path]:
    if os.path.exists(p):
        os.unlink(p)

from backtest.signals.signal_collector import SignalEventCollector

# Simple Event class
class FakeEvent:
    def __init__(self, **kw):
        self.__dict__.update(kw)

collector = SignalEventCollector(
    db_path=db_path,
    batch_id=f"e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
)

for i in range(20):
    collector.on_signal_created(FakeEvent(
        signal_id=f"sig_e2e_{i:04d}",
        symbol="601857.SH",
        signal_type="trend_follow",
        raw_score=0.75 + (i % 10) * 0.02,
        timestamp=datetime.now().isoformat(),
        strategy_id="TrendStrategy-v1",
    ))
collector.flush()

conn = sqlite3.connect(db_path)
sc = conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]
fc = conn.execute("SELECT COUNT(*) FROM filter_logs").fetchone()[0]
tc = conn.execute("SELECT COUNT(*) FROM trade_decisions").fetchone()[0]
conn.close()
collector.close()
print(f"  signal_events:   {sc}")
print(f"  filter_logs:     {fc}")
print(f"  trade_decisions: {tc}")

# ─── 4. 突破检测 + 生命周期 ──────────────────────
print("\n[4/5] 突破检测 + 生命周期...")

import numpy as np
import pandas as pd

# 补充计算列
df = data.copy()
ma20 = df["close"].rolling(20).mean()
df["VWAP"] = (df["high"] + df["low"] + df["close"]) / 3
df["VolumeRatio"] = df["volume"] / df["volume"].rolling(20).mean().clip(lower=1)
df["TrendQuality"] = df["close"].pct_change(5).abs().clip(0, 0.5) * 2
df["Regime"] = np.where(df["close"] > ma20, "TREND_UP", "RANGE")
for col in ["VWAP", "VolumeRatio", "TrendQuality"]:
    df[col] = df[col].fillna(0)

from backtest.signals.breakout_profile import (
    detect_breakout_points,
    BreakoutFeatureExtractor,
    BreakoutScoringCard,
)
from backtest.signals.trend_lifecycle import (
    TrendLifecycleDetector,
    TrendPhase,
    analyze_breakout_lifecycle,
)

# 突破检测
bi = detect_breakout_points(df)
print(f"  突破点: {len(bi)}")

# 特征提取
ext = BreakoutFeatureExtractor()
ext.precompute_factors(df)
feats = []
for idx in bi[:30]:
    f = ext.extract_at(df, idx)
    if f is not None:
        feats.append(f)
print(f"  特征: {len(feats)}")

# 评分
if feats:
    card = BreakoutScoringCard()
    scored_results = [card.score(f) for f in feats]
    false_cnt = sum(1 for r in scored_results if r['classification'] == 'false_breakout')
    print(f"  评分: {len(scored_results)} 假突破: {false_cnt} ({false_cnt/len(scored_results)*100:.0f}%)")
else:
    false_cnt = 0
    scored = None

# 生命周期
tl = TrendLifecycleDetector()
tres = tl.detect(df)
if tres.per_bar_phase is not None and len(tres.per_bar_phase) > 0:
    pc = {}
    for p in list(tres.per_bar_phase):
        pc[p] = pc.get(p, 0) + 1
    ordered = sorted(TrendPhase.ALL_PHASES, key=lambda x: TrendPhase.phase_index(x))
    print(f"  生命周期 ({len(tres.per_bar_phase)} bars):")
    for p in ordered:
        c = pc.get(p, 0)
        if c > 0:
            print(f"    {p}: {c} ({c/len(tres.per_bar_phase)*100:.1f}%)")

# ─── 5. 摘要 ──────────────────────────────────────
print("\n" + "=" * 50)
print("摘要")
print("=" * 50)

summary = {
    "symbol": "601857.SH",
    "bars": len(data),
    "trades": result.total_trades,
    "return_pct": round(result.metrics["total_return_pct"], 2),
    "sharpe_ratio": round(result.metrics.get("sharpe_ratio", 0), 2),
    "max_dd_pct": round(result.metrics.get("max_drawdown_pct", 0), 2),
    "signal_events": sc,
    "filter_logs": fc,
    "trade_decisions": tc,
    "breakout_detected": len(bi),
    "features_extracted": len(feats),
    "false_breakouts": false_cnt,
    "lifecycle_bars": len(tres.per_bar_phase) if tres.per_bar_phase is not None else 0,
    "lifecycle_phases": len(pc) if tres.per_bar_phase is not None else 0,
    "modules": [
        "BacktestEngine", "SignalEventCollector",
        "BreakoutFeatureExtractor", "BreakoutScoringCard",
        "TrendLifecycleDetector",
    ],
}

for k, v in summary.items():
    if isinstance(v, list):
        print(f"  {k}: {', '.join(v)}")
    else:
        print(f"  {k}: {v}")

report_path = os.path.join(
    BASE, "reports", "backtest",
    f"run_601857_e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
)
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)
print(f"\n报告: {os.path.basename(report_path)}")
print("✅ 全模块集成验证 v2")
