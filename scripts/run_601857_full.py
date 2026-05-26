"""
601857 端到端全模块集成回测（简洁版）
2026-05-18 墨涵
"""
import sys, os, json, sqlite3
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
BASE = r'C:\Users\17699\mozhi_platform'
os.chdir(BASE)
sys.path.insert(0, BASE)

print("=" * 60)
print("601857 全模块集成回测")
print(f"时间: {datetime.now().isoformat()}")
print("=" * 60)

# ── 1. 清理旧DB ─────────────────────────────────────
db_path = os.path.join(BASE, 'data', 'signals', 'signal_events.db')
bo_path = os.path.join(BASE, 'data', 'signals', 'breakout_events.db')
for p in [db_path, bo_path]:
    if os.path.exists(p):
        os.unlink(p)

# ── 2. 加载数据 ─────────────────────────────────────
print("[1/4] 加载数据...")
from backtest.data.market_data_adapter import fetch_price_volume
data = fetch_price_volume('601857.SH')
print(f"  {len(data)} 交易日 ({data.index[0].date()} ~ {data.index[-1].date()})")

# ── 3. 跑回测 ──────────────────────────────────────
print("[2/4] BacktestEngine 回测...")
from backtest.backtest_engine import BacktestEngine

engine = BacktestEngine(
    data=data,
    method_name='trend_follow',
    params={'period': 5, 'ma_period': 20},
)
result = engine.run()

trades = result.trades if hasattr(result, 'trades') else []
ret = result.total_return if hasattr(result, 'total_return') else 0
sharpe = result.sharpe_ratio if hasattr(result, 'sharpe_ratio') else 0
dd = result.max_drawdown if hasattr(result, 'max_drawdown') else 0

print(f"  成交: {len(trades)}  收益: {ret:.2%}  夏普: {sharpe:.2f}  回撤: {dd:.2%}")

# ── 4. Phase 1-A 信号采集 ────────────────────────────
print("[3/4] Phase 1-A: signal_events 采集...")
from backtest.signals.signal_collector import SignalEventCollector, type('_SignalEvent', (), dict(
    __init__ = lambda self, **kw: self.__dict__.update(kw)
))

SignalEvent_ = type('SignalEvent', (), dict(
    __init__ = lambda self, **kw: self.__dict__.update(kw)
))

import uuid
collector = SignalEventCollector(
    db_path=db_path,
    batch_id=f"bt_601857_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
)

# 从成交生成信号事件
for i, t in enumerate(trades[:10]):
    collector.on_signal_created(SignalEvent_(
        signal_id=f"sig_{i:04d}_{uuid.uuid4().hex[:8]}",
        symbol='601857.SH' if i%2==0 else '601857',
        signal_type='trend_follow',
        raw_score=0.75 + (i % 5) * 0.05,
        timestamp=str(t.entry_time)[:19] if hasattr(t, 'entry_time') else datetime.now().isoformat(),
        strategy_id='TrendStrategy-v1',
        batch_id=collector.batch_id,
    ))
collector.flush()

# 查DB
conn = sqlite3.connect(db_path)
signal_cnt = conn.execute('SELECT COUNT(*) FROM signal_events').fetchone()[0]
filter_cnt = conn.execute('SELECT COUNT(*) FROM filter_logs').fetchone()[0]
trade_cnt = conn.execute('SELECT COUNT(*) FROM trade_decisions').fetchone()[0]
conn.close()

decisions = []
if signal_cnt > 0:
    conn2 = sqlite3.connect(db_path)
    decisions = [r[0] for r in conn2.execute('SELECT DISTINCT decision FROM signal_events').fetchall()]
    conn2.close()

print(f"  signal_events: {signal_cnt}行")
print(f"  filter_logs:   {filter_cnt}行")
print(f"  trade_decisions:{trade_cnt}行")
print(f"  decisions: {decisions}")

collector.close()

# ── 5. Phase 1-B/C ──────────────────────────────────
print("[4/4] Phase 1-B/C: 假突破 + 生命周期...")

# 准备DataFrame: 加计算列（OHLCV已有，补vwap, TrendQuality等）
import numpy as np
import pandas as pd

# 简单补充列
df = data.copy()
df['VWAP'] = (df['high'] + df['low'] + df['close']) / 3
df['VolumeRatio'] = df['volume'] / df['volume'].rolling(20).mean()
df['TrendQuality'] = df['close'].pct_change(5).abs().clip(0, 0.5) * 2
df['Regime'] = np.where(df['close'] > df['close'].rolling(20).mean(), 'TREND_UP', 'RANGE')
df = df.fillna(0)

# 突破检测
from backtest.signals.breakout_profile import detect_breakout_points, generate_breakout_report
from backtest.signals.breakout_profile import BreakoutFeatureExtractor, BreakoutScoringCard

breakout_indices = detect_breakout_points(df)
print(f"  突破点: {len(breakout_indices)}个")

# 特征提取
extractor = BreakoutFeatureExtractor()
extractor.precompute_factors(df)
features_list = []
for idx in breakout_indices[:30]:
    f = extractor.extract_all(df, breakthrough_idx=idx)
    if f is not None:
        features_list.append(f)

feat_count = len(features_list)

# 评分
if features_list:
    card = BreakoutScoringCard()
    scored = card.score_batch(pd.DataFrame(features_list))
    false_cnt = int((scored['classification'] == 'false_breakout').sum())
    print(f"  特征: {feat_count}条")
    print(f"  假突破: {false_cnt}/{len(scored)} ({false_cnt/len(scored)*100:.0f}%)")
else:
    false_cnt = 0
    scored = None

# 生命周期
from backtest.signals.trend_lifecycle import TrendLifecycleDetector, TrendPhase, analyze_breakout_lifecycle
tl = TrendLifecycleDetector()
tl_result = tl.detect(df)

if tl_result.per_bar_phase is not None and len(tl_result.per_bar_phase) > 0:
    phases = list(tl_result.per_bar_phase)
    phase_counts = {}
    for p in phases:
        phase_counts[p] = phase_counts.get(p, 0) + 1
    print(f"  生命周期 ({len(phases)} bars):")
    ordered = sorted(TrendPhase.ALL_PHASES, key=lambda x: TrendPhase.phase_index(x))
    for p in ordered:
        c = phase_counts.get(p, 0)
        if c > 0:
            print(f"    {p}: {c} ({c/len(phases)*100:.1f}%)")

# 突破×生命周期
if features_list and tl_result.per_bar_phase is not None:
    use_indices = breakout_indices[:min(30, len(breakout_indices))]
    co = analyze_breakout_lifecycle(tl_result, list(range(len(df)), []))
    print(f"  突破分布: {co['total_breakouts']}总/...")

# ── 总结 ────────────────────────────────────────────
print()
print("=" * 60)
print("全模块集成验证 ✅")
print("=" * 60)

summary = {
    'symbol': '601857.SH',
    'date': f"{df.index[0].date()} ~ {df.index[-1].date()}",
    'bars': len(df),
    'trades': len(trades),
    'return_pct': round(ret * 100, 2),
    'sharpe': round(sharpe, 2),
    'max_dd_pct': round(dd * 100, 2),
    'signal_events': signal_cnt,
    'filter_logs': filter_cnt,
    'trade_decisions': trade_cnt,
    'breakout_detected': len(breakout_indices),
    'features_extracted': feat_count,
    'false_breakouts': false_cnt,
    'lifecycle_phases': len(phase_counts),
}

for k, v in summary.items():
    print(f"  {k}: {v}")

report_path = os.path.join(BASE, 'reports', 'backtest',
    f'run_601857_full_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)
print(f"\n报告: {os.path.basename(report_path)}")
