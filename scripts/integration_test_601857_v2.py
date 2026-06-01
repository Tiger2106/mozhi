"""集成测试：601857.SH 完整 pipeline 运行 v2"""
import sys, json, time
sys.path.insert(0, ".")

from src.resonance import data_bridge as db
from src.resonance.pipeline import PipelineOrchestrator, PipelineConfig

print("=== Step 1: 数据检查 ===")
try:
    df = db.fetch_ohlcv("601857.SH", "20260301", "20260529")
    print(f"数据行数: {len(df)}")
    print(f"日期范围: {df.index[0]} ~ {df.index[-1]}")
    print(f"最新收盘价: {df['close'].iloc[-1]}")
    print(f"列名: {list(df.columns)}")
    print(f"列类型: {dict(df.dtypes)}")
    print(f"检查通过 ✅")
except Exception as e:
    print(f"数据获取失败: {e}")
    sys.exit(1)

print("\n=== Step 2: Pipeline 运行 ===")
config = PipelineConfig(
    tickers=["601857.SH"],
    lookback_window=60,
    verbose=True,
)
orch = PipelineOrchestrator(config=config)

t0 = time.time()
results = orch.run_once(tickers=["601857.SH"])
t1 = time.time()

print(f"执行时间: {(t1-t0)*1000:.1f}ms\n")

for ticker, r in results.items():
    print(f"=== {ticker} ===")
    print(f"  status={r.status}")
    print(f"  errors={r.errors}")
    print(f"  warnings={r.warnings}")
    
    if r.dcm_result:
        d = r.dcm_result
        print(f"  DCM: status={d.status} hv={d.volatility:.4f} hv_history_len={len(d.volatility_history) if hasattr(d, 'volatility_history') and d.volatility_history is not None else 0}")
    if r.lqm_result:
        d = r.lqm_result
        print(f"  LQM: status={d.status} score={d.liquidity_score:.4f} ratio={d.volume_ratio:.4f}")
    if r.znm_result:
        d = r.znm_result
        print(f"  ZNM: status={d.status} zscore={d.zscore}")
        if hasattr(d, 'normalized_values') and d.normalized_values is not None:
            print(f"  ZNM normalized_values: {d.normalized_values[:5]}... len={len(d.normalized_values)}")
    if r.rsm_result:
        d = r.rsm_result
        print(f"  RSM: state={d.current_state} strength={d.resonance_strength}")
    if r.dsv_result:
        d = r.dsv_result
        print(f"  DSV: passed={d.passed} score={d.divergence}")
    if r.gkv_result:
        d = r.gkv_result
        print(f"  GKV: passed={d.passed}")
    if r.cpe_result:
        d = r.cpe_result
        print(f"  CPE: verdict={d.verdict} score={d.score} days={d.continuous_days}")
    if r.sg_result:
        d = r.sg_result
        print(f"  SG: type={d.signal_type} threshold={d.threshold} strength={d.strength}")
    if r.scl_result:
        d = r.scl_result
        print(f"  SCL: action={d.action} type={d.signal_type}")
