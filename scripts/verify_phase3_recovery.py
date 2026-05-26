"""
信号衰减分析器测试
"""
import sys, os
sys.path.insert(0, r'C:\Users\17699\mozhi_platform')
os.chdir(r'C:\Users\17699\mozhi_platform')

# 测试 import
from backtest.signals.analysis.signal_decay import SignalDecayAnalyzer

# 创建测试数据
trades = [
    {'signal_date': '20250101', 'entry_date': '20250103', 'pnl': 2.5},
    {'signal_date': '20250105', 'entry_date': '20250106', 'pnl': 1.0},
    {'signal_date': '20250110', 'entry_date': '20250120', 'pnl': 0.5},
]

a = SignalDecayAnalyzer(trades)
print(f"Trades parsed: {a.count}")
print(f"Decay curve: {a.decay_curve()}")
print(f"Half-life (exponential): {a.half_life('exponential')}")
print(f"Optimal window: {a.optimal_window()}")

# 空数据
a2 = SignalDecayAnalyzer([])
print(f"Empty: {a2.count}")
print(f"Empty decay: {a2.decay_curve()}")
print("SignalDecayAnalyzer OK ✅")

# 测试 FakeBreakoutClassifier
from backtest.signals.fake_breakout_classifier import FakeBreakoutClassifier

clf = FakeBreakoutClassifier()
result = clf.classify(
    {'direction': 'UP', 'volume_ratio': 0.8, 'momentum': 0.02, 'price': 10.0},
    {'ma_trend': 1, 'nearest_support': 9.5, 'volatility_percentile': 0.3}
)
print(f"\nClassification: {result['label']} (score: {result['composite_score']})")
print(f"Dimensions: {result['dimension_scores']}")

# 批量
batch = clf.batch_classify([
    {'direction': 'UP', 'volume_ratio': 2.0, 'momentum': 0.05, 'price': 10.0},
    {'direction': 'DOWN', 'volume_ratio': 0.3, 'momentum': -0.03, 'price': 9.0},
])
print(f"Batch results: {[r['label'] for r in batch]}")

# 失败模式
patterns = clf.analyze_failure_patterns([
    {'is_fake': True, 'volume_ratio': 0.5, 'momentum': 0.01},
    {'is_fake': False, 'volume_ratio': 1.8, 'momentum': 0.04},
])
print(f"Failure patterns: {patterns}")

print("FakeBreakoutClassifier OK ✅")