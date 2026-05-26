"""Debug: run _check_cross_validate with matching values"""
from src.backtest.analysis.ingest.validator import Validator
from src.backtest.analysis.ingest.model import PipelineInput, MetricsCore, MetricsExt, AnalysisDoc, AnalysisMeta

meta = AnalysisMeta(run_id='r1', analysis_type='summary')
mc = MetricsCore(run_id='r1', metric_group='daily', total_return_pct=12.5, sharpe_ratio=1.5)
ext = MetricsExt(run_id='r1', metric_group='daily', metric_name='m0', metric_value=0.0)
doc = AnalysisDoc(run_id='r1', doc_type='summary_report', file_path='/tmp/test_doc_0.md')
pi = PipelineInput(meta=meta, metrics_core=[mc], metrics_ext=[ext], docs=[doc])

perf_row = {
    'run_id': 'test-run-001', 'total_return': 12.5, 'annualized_return': 15.3,
    'benchmark_return': 8.2, 'excess_return': 4.3, 'max_drawdown': -18.5,
    'sharpe_ratio': 1.5, 'calmar_ratio': 0.85, 'sortino_ratio': 2.1,
    'volatility': 22.0, 'win_rate': 58.3, 'total_trades': 120,
    'max_consecutive_wins': 8, 'max_consecutive_losses': 4,
    'final_equity': 1125000.0, 'winning_trades': 70, 'losing_trades': 50,
    'max_single_win': 35000.0, 'max_single_loss': -18000.0,
    'total_profit': 250000.0, 'total_loss': -125000.0, 'var_95_pct': -2.5
}

v = Validator(':memory:')
cr = v._check_cross_validate(pi, perf_row)
print(f'level: {cr.level}')
print(f'detail: {cr.detail}')
print(f'passed: {cr.passed}')

# Check the metrics_core fields
for pf, an in v.CROSS_FIELDS:
    pv = perf_row.get(pf)
    iv = getattr(mc, an, None)
    print(f'  {pf} -> {an}: perf={pv}, input={iv}')
    if pv is not None and iv is not None:
        ref = abs(float(pv)) if float(pv) != 0 else 1.0
        dev = abs(float(iv) - float(pv)) / ref
        if dev > v.CROSS_VALIDATE_THRESHOLD_ERROR:
            print(f'    ** ERROR level deviation: {dev*100:.4f}% > {v.CROSS_VALIDATE_THRESHOLD_ERROR*100}%')
        elif dev > v.CROSS_VALIDATE_THRESHOLD_WARN:
            print(f'    ** WARN level deviation: {dev*100:.4f}% > {v.CROSS_VALIDATE_THRESHOLD_WARN*100}%')
        else:
            print(f'    OK deviation: {dev*100:.6f}%')
