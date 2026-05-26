"""
Compute factor IC/RankIC for 601857 using 1540 daily data points.
No scipy dependency - manual spearmanr implementation.
"""
import pandas as pd
import numpy as np
import math

def spearman_rank_corr(x, y):
    """Compute Spearman rank correlation coefficient."""
    n = len(x)
    if n < 3:
        return 0.0, 1.0
    x_rank = pd.Series(x).rank().values
    y_rank = pd.Series(y).rank().values
    d = x_rank - y_rank
    d2 = np.sum(d ** 2)
    rho = 1 - (6 * d2) / (n * (n*n - 1))
    # t-statistic approximation for p-value
    t_stat = rho * math.sqrt((n - 2) / max(1 - rho*rho, 1e-10))
    # Using normal approximation for large n
    from math import erf
    p_val = 2 * (1 - 0.5 * (1 + erf(abs(t_stat) / math.sqrt(2))))
    return rho, p_val

# Try to import scipy, if not use manual
def spearmanr(x, y):
    rho, p = spearman_rank_corr(x, y)
    return rho, p

df = pd.read_csv('C:/Users/17699/mozhi_platform/data/market/601857_SH.csv')
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
print(f"Total rows: {len(df)}")
print(f"Date range: {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")
print()

# --- compute forward returns ---
for h in [1, 3, 5, 10, 20]:
    df[f'fwd_ret_{h}d'] = df['close'].pct_change(h).shift(-h)

# --- Factor 1: TrendQuality ---
def trend_quality(close_series):
    x = np.arange(len(close_series))
    if len(close_series) < 5 or np.isnan(close_series).any():
        return np.nan
    denom = np.sum((close_series - np.mean(close_series))**2)
    if denom == 0:
        return 0.0
    slope, intercept = np.polyfit(x, close_series, 1)
    fitted = slope * x + intercept
    r2 = 1 - np.sum((close_series - fitted)**2) / denom
    slope_pct = abs(slope / np.mean(close_series))
    if slope_pct < 0.0005:
        return max(0, r2 * 0.3)
    return max(0, r2)

trend_q = []
for i in range(len(df)):
    if i < 20:
        trend_q.append(np.nan)
    else:
        trend_q.append(trend_quality(df['close'].iloc[i-20:i+1].values))
df['TrendQuality'] = trend_q

# --- Factor 2: VWAP deviation (20d anchored) ---
price_vol = df['close'] * df['volume']
cum_pv = price_vol.rolling(20, min_periods=1).sum()
cum_v = df['volume'].rolling(20, min_periods=1).sum()
df['VWAP_20d'] = cum_pv / cum_v
df['VWAP_dev'] = (df['close'] - df['VWAP_20d']) / df['VWAP_20d']

# --- Factor 3: Volume ratio ---
df['Volume_MA20'] = df['volume'].rolling(20, min_periods=1).mean()
df['Volume_ratio'] = df['volume'] / df['Volume_MA20']

# --- Factor 4: ATR expansion ratio ---
high_low = df['high'] - df['low']
high_close = (df['high'] - df['close'].shift(1)).abs()
low_close = (df['low'] - df['close'].shift(1)).abs()
df['TR'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df['ATR_20'] = df['TR'].rolling(20, min_periods=1).mean()
df['ATR_ratio'] = df['TR'] / df['ATR_20']

# --- Factor 5: OBV change rate ---
df['OBV'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
df['OBV_change'] = df['OBV'].pct_change(5)

for c in ['TrendQuality','VWAP_dev','Volume_ratio','ATR_ratio','OBV_change']:
    df[c] = df[c].replace([np.inf, -np.inf], np.nan)

factors = ['TrendQuality', 'VWAP_dev', 'Volume_ratio', 'ATR_ratio', 'OBV_change']
horizons = [1, 3, 5, 10, 20]

print("=" * 80)
print("FACTOR IC / RankIC SUMMARY (Daily Frequency)")
print("=" * 80)

all_results = []
for factor in factors:
    for h in horizons:
        col = f'fwd_ret_{h}d'
        valid = df[[factor, col]].dropna()
        n = len(valid)
        if n < 20:
            continue
        ic_val, ic_p = spearmanr(valid[factor].values, valid[col].values)
        pos_pct = (valid[factor].values * valid[col].values > 0).mean()
        sig = '***' if ic_p < 0.01 else ('**' if ic_p < 0.05 else ('*' if ic_p < 0.10 else ''))
        all_results.append({
            'factor': factor, 'horizon': h, 'IC': ic_val, 'IC_pval': ic_p,
            'pos_pct': pos_pct, 'sig_mark': sig, 'N': n
        })
        print(f"  {factor:20s} H={h:2d} | IC={ic_val:+.4f}{sig} | IC_pval={ic_p:.4f} | IC>0={pos_pct:.0%} | N={n}")
    print()

# Average IC by factor
print("=" * 80)
print("AVERAGE IC BY FACTOR (across all horizons)")
print("=" * 80)
for f in factors:
    f_res = [r for r in all_results if r['factor'] == f]
    if f_res:
        avg_ic = np.mean([r['IC'] for r in f_res])
        avg_pos = np.mean([r['pos_pct'] for r in f_res])
        sig_cnt = sum(1 for r in f_res if r['IC_pval'] < 0.05)
        print(f"  {f:20s} | avg_IC={avg_ic:+.4f} | avg_IC>0={avg_pos:.0%} | sig_at_5%={sig_cnt}/{len(f_res)}")

# IC Decay Curve
print()
print("=" * 80)
print("IC DECAY CURVE (TrendQuality)")
print("=" * 80)
for h in horizons:
    r = [x for x in all_results if x['factor'] == 'TrendQuality' and x['horizon'] == h]
    if r:
        r = r[0]
        print(f"  H={h:2d}d | IC={r['IC']:+.4f} | RankIC={r['IC']:+.4f} | p={r['IC_pval']:.4f} | N={r['N']}")

print()
print("IC DECAY CURVE (VWAP_dev)")
print("-" * 60)
for h in horizons:
    r = [x for x in all_results if x['factor'] == 'VWAP_dev' and x['horizon'] == h]
    if r:
        r = r[0]
        print(f"  H={h:2d}d | IC={r['IC']:+.4f} | p={r['IC_pval']:.4f} | N={r['N']}")

# Half-life estimation
print()
print("=" * 80)
print("HALF-LIFE ESTIMATION")
print("=" * 80)
tq_results = [r for r in all_results if r['factor'] == 'TrendQuality']
if tq_results:
    base_ic = max(r['IC'] for r in tq_results if r['horizon'] == 1)
    if not any(r['horizon'] == 1 for r in tq_results):
        base_ic = tq_results[0]['IC']
    base_r = [r for r in tq_results if r['horizon'] == 1][0]
    print(f"  Base H=1d: IC={base_r['IC']:+.4f}, p={base_r['IC_pval']:.4f}")
    print(f"  Target (half-life): {base_r['IC']/2:+.4f}")
    for r in tq_results:
        ratio = r['IC'] / base_r['IC'] if base_r['IC'] != 0 else 0
        print(f"    H={r['horizon']:2d}d | IC={r['IC']:+.4f} | IC/base={ratio:.2f}")
    
    # Find half-life (where IC drops below 50% of base)
    for i, r in enumerate(tq_results):
        if r['IC'] / base_r['IC'] < 0.5:
            if i == 0:
                print(f"  >> Half-life: <{r['horizon']}d (immediate decay)")
            elif r['horizon'] == tq_results[i-1]['horizon']:
                print(f"  >> Half-life: <{r['horizon']}d")
            else:
                hl_est = (tq_results[i-1]['horizon'] + r['horizon']) / 2
                print(f"  >> Half-life: ~{hl_est:.0f}d")
            break
    else:
        print(f"  >> Half-life: >{tq_results[-1]['horizon']}d (very slow decay)")

# Factor correlation
print()
print("=" * 80)
print("FACTOR CORRELATION MATRIX")
print("=" * 80)
corr_data = df[factors].dropna()
corr_matrix = corr_data.corr(method='spearman')
print(corr_matrix.round(3))

# Factor descriptive statistics
print()
print("=" * 80)
print("FACTOR DESCRIPTIVE STATISTICS")
print("=" * 80)
for f in factors:
    s = df[f].dropna()
    print(f"  {f:20s} | mean={s.mean():+.4f} | std={s.std():.4f} | p50={s.median():+.4f} | min={s.min():+.4f} | max={s.max():+.4f}")

# Weekly aggregation
print()
print("=" * 80)
print("FACTOR IC / RankIC (Weekly Frequency)")
print("=" * 80)
df_w = df.copy()
df_w['week'] = df_w['date'].dt.isocalendar().week.astype(int)
df_w['year'] = df_w['date'].dt.year
weekly = df_w.groupby(['year', 'week']).agg({
    'close': 'last', 'TrendQuality': 'last', 'VWAP_dev': 'last',
    'Volume_ratio': 'last', 'ATR_ratio': 'last', 'OBV_change': 'last'
}).reset_index()
for h in [1, 3, 5]:
    weekly[f'fwd_ret_{h}w'] = weekly['close'].pct_change(h).shift(-h)

for factor in factors:
    for h in [1, 3, 5]:
        col = f'fwd_ret_{h}w'
        if col not in weekly.columns:
            continue
        valid = weekly[[factor, col]].dropna()
        n = len(valid)
        if n < 10:
            continue
        ic_val, ic_p = spearmanr(valid[factor].values, valid[col].values)
        sig = '***' if ic_p < 0.01 else ('**' if ic_p < 0.05 else ('*' if ic_p < 0.10 else ''))
        pos_pct = (valid[factor].values * valid[col].values > 0).mean()
        print(f"  {factor:20s} H={h}w | IC={ic_val:+.4f}{sig} | IC>0={pos_pct:.0%} | N={n}")

# Monthly
print()
print("=" * 80)
print("FACTOR IC / RankIC (Monthly Frequency)")
print("=" * 80)
df_m = df.copy()
df_m['month'] = df_m['date'].dt.month
df_m['year'] = df_m['date'].dt.year
monthly = df_m.groupby(['year', 'month']).agg({
    'close': 'last', 'TrendQuality': 'last', 'VWAP_dev': 'last',
    'Volume_ratio': 'last', 'ATR_ratio': 'last', 'OBV_change': 'last'
}).reset_index()
for h in [1, 3, 6]:
    monthly[f'fwd_ret_{h}m'] = monthly['close'].pct_change(h).shift(-h)

for factor in factors:
    for h in [1, 3, 6]:
        col = f'fwd_ret_{h}m'
        if col not in monthly.columns:
            continue
        valid = monthly[[factor, col]].dropna()
        n = len(valid)
        if n < 8:
            continue
        ic_val, ic_p = spearmanr(valid[factor].values, valid[col].values)
        sig = '***' if ic_p < 0.01 else ('**' if ic_p < 0.05 else ('*' if ic_p < 0.10 else ''))
        pos_pct = (valid[factor].values * valid[col].values > 0).mean()
        print(f"  {factor:20s} H={h}m | IC={ic_val:+.4f}{sig} | IC>0={pos_pct:.0%} | N={n}")

print()
print("Done.")
