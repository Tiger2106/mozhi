"""Fix NaN propagation in _calc_ema for TSI double-EMA"""
import re

path = r'C:\Users\17699\.openclaw\workspace-moheng\scripts\phase1_factor_backfill.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

# Fix 1: _calc_ema - np.mean -> np.nanmean to handle NaN in input values
old1 = 'ema = np.mean(values[:period])'
new1 = 'ema = np.nanmean(values[:period])'
if old1 in content:
    content = content.replace(old1, new1)
    print('✅ _calc_ema: np.mean -> np.nanmean')
else:
    print('❌ _calc_ema: pattern not found (may already be fixed)')

# Fix 2: Also check _calc_tsi loop - numpy NaN is not None, use np.isnan
old2 = 'if ema2[i] is not None and ema_abs2[i] is not None and not np.isnan(ema_abs2[i])'
new2 = 'if not np.isnan(ema2[i]) and not np.isnan(ema_abs2[i])'
if old2 in content:
    content = content.replace(old2, new2)
    print('✅ _calc_tsi loop: is not None -> not np.isnan')
else:
    print('ℹ️ _calc_tsi loop: pattern may differ')

# Fix 3: Add the missing _calc_structure_quality function if it doesn't exist
if 'def _calc_structure_quality' not in content:
    # Find position to add (before the main block or at end)
    struct_func = '''
def _calc_structure_quality(highs, lows, closes, period=30):
    """结构品质评分 = (H-L)/close 的滚动均值的倒数"""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    result = np.full(n, np.nan)
    ranges = (highs - lows) / np.maximum(closes, 1e-10)
    for i in range(period - 1, n):
        avg_range = np.nanmean(ranges[i - period + 1:i + 1])
        result[i] = 1.0 / max(avg_range, 1e-10)
    return result


def _calc_gaps(opens, closes, highs, lows):
    """跳空：up=gap_up 数量, down=gap_down 数量"""
    opens = np.asarray(opens, dtype=float)
    closes = np.asarray(closes, dtype=float)
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    n = len(closes)
    gap_up = np.zeros(n)
    gap_down = np.zeros(n)
    for i in range(1, n):
        if opens[i] > highs[i-1]:
            gap_up[i] = 1
        elif opens[i] < lows[i-1]:
            gap_down[i] = 1
    return gap_up, gap_down


def _calc_bb_position(closes, upper, lower):
    """布林带位置：[0,1] 归一化"""
    closes = np.asarray(closes, dtype=float)
    upper = np.asarray(upper, dtype=float)
    lower = np.asarray(lower, dtype=float)
    denom = upper - lower
    result = np.full(len(closes), np.nan)
    mask = denom > 1e-10
    result[mask] = (closes[mask] - lower[mask]) / denom[mask]
    return result
'''
    # Insert before __main__
    marker = 'if __name__ == "__main__":'
    if marker in content:
        idx = content.index(marker)
        content = content[:idx] + struct_func + '\n\n' + content[idx:]
        print('✅ Added missing structure/gap/bb_position functions')
    else:
        print('❌ Could not find __main__ marker to insert functions')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('✅ Saved fixes')
