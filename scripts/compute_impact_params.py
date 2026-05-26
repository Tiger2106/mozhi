"""
Compute market impact model parameters for P5 v2.
Non-linear impact + capital capacity estimation.
"""
import pandas as pd
import numpy as np
import math

df = pd.read_csv('C:/Users/17699/mozhi_platform/data/market/601857_SH.csv')
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

# --- Volume statistics ---
print("=" * 70)
print("VOLUME STATISTICS (601857, 2020-01 to 2026-05, 1540 days)")
print("=" * 70)

v = df['volume']
amt = df['amount']
close = df['close']

print(f"  Avg daily volume: {v.mean()/1e4:.0f} wan shou")
print(f"  Median daily volume: {v.median()/1e4:.0f} wan shou")
print(f"  Min daily volume: {v.min()/1e4:.1f} wan shou")
print(f"  Max daily volume: {v.max()/1e4:.0f} wan shou")
print(f"  Std daily volume: {v.std()/1e4:.0f} wan shou")
print(f"  Avg daily amount: {amt.mean()/1e8:.1f} hundred million CNY")
print(f"  Avg close price: {close.mean():.2f}")
print()

# Volume percentiles
for pct in [5, 10, 25, 50, 75, 90, 95]:
    val = v.quantile(pct/100)
    print(f"  P{pct}: {val/1e4:.1f} wan shou")

# Recent volume
recent = df.tail(84)
print(f"\n  Recent 84d avg volume: {recent['volume'].mean()/1e4:.0f} wan shou")
print(f"  Recent 84d avg amount: {recent['amount'].mean()/1e8:.1f} hundred million CNY")
print()

# --- Volatility ---
df['ret'] = df['close'].pct_change()
daily_vol = df['ret'].std()
annual_vol = daily_vol * math.sqrt(252)
print(f"  Daily volatility: {daily_vol:.4f} ({daily_vol*100:.2f}%)")
print(f"  Annualized volatility: {annual_vol:.4f} ({annual_vol*100:.2f}%)")
print()

# --- Spread estimation ---
df['spread_est'] = (df['high'] - df['low']) / df['close']
print(f"  Avg daily spread (HL proxy): {df['spread_est'].mean()*100:.2f}%")
print(f"  Median daily spread: {df['spread_est'].median()*100:.2f}%")
print()

# --- Almgren-Chriss parameters ---
print("=" * 70)
print("ALMGREN-CHRISS IMPACT MODEL PARAMETERS")
print("=" * 70)

sigma = daily_vol
V = v.mean()

print(f"  sigma (daily vol): {sigma:.4f}")
print(f"  V (avg daily volume): {V:.0f} shares ({V/1e4:.1f} wan shou)")
print()

for qty_label, qty, price in [
    ("200 shares (current)", 200, close.iloc[-1]),
    ("5,000 shares (5% fund)", 5000, close.iloc[-1]),
    ("20,000 shares (20% fund)", 20000, close.iloc[-1]),
    ("50,000 shares (50% fund)", 50000, close.iloc[-1]),
    ("100,000 shares (full)", 100000, close.iloc[-1]),
    ("500,000 shares (block)", 500000, close.iloc[-1]),
]:
    q_over_v = qty / V
    perm_impact = 0.1 * sigma * (q_over_v ** 0.3)
    temp_impact = 0.5 * sigma * (q_over_v ** 0.5)
    total_impact = perm_impact + temp_impact
    impact_bp = total_impact * 10000
    cost = total_impact * qty * price
    print(f"  {qty_label:30s}:")
    print(f"    Q/V={q_over_v*100:.4f}% | Perm={perm_impact*10000:.2f}bp | Temp={temp_impact*10000:.2f}bp | Total={impact_bp:.2f}bp")
    print(f"    Impact cost: {cost:.2f} CNY")
print()

# --- Multi-asset capacity ---
print("=" * 70)
print("MULTI-ASSET CROSS-SECTIONAL CAPACITY ESTIMATION")
print("=" * 70)

stocks_info = {
    "601857 (CNPC)": {"vol_ratio": 1.0, "price": close.iloc[-1], "adv": v.mean()},
    "600519 (Moutai)": {"vol_ratio": 0.3, "price": 1800, "adv": v.mean() * 0.3},
    "000001 (PingAn)": {"vol_ratio": 0.8, "price": 12, "adv": v.mean() * 0.8},
    "600036 (CMB)": {"vol_ratio": 0.5, "price": 40, "adv": v.mean() * 0.5},
}

print(f"  {'Stock':25s} {'ADV(wan)':>10s} {'Price':>7s} {'10bpCap(w)':>12s} {'50bpCap(w)':>12s}")
print("  " + "-" * 66)
for stock, info in stocks_info.items():
    adv = info['adv']
    adv_wan = adv / 1e4
    price = info['price']  # estimated for other stocks
    sigma_used = sigma * (1.0 if stock == "601857 (CNPC)" else 1.2)
    
    for target_bp, label in [(0.001, 10), (0.005, 50)]:
        x = 0.01
        for _ in range(100):
            f = 0.1 * sigma_used * (x**0.3) + 0.5 * sigma_used * (x**0.5) - target_bp
            if abs(f) < 1e-12:
                break
            dfx = 0.03 * sigma_used * (x**-0.7) + 0.25 * sigma_used * (x**-0.5)
            x = x - f / dfx
            x = max(0.0001, min(x, 1.0))
        capacity_shares = x * adv
        capacity_amount = capacity_shares * price / 1e4
        if label == 10:
            cap10 = capacity_amount
        else:
            cap50 = capacity_amount
    
    print(f"  {stock:25s} {adv_wan:>8.0f}  {price:>6.2f} {cap10:>10.0f}  {cap50:>10.0f}")

# --- Impact curve ---
print()
print("=" * 70)
print("IMPACT CURVE (601857)")
print("=" * 70)
print(f"  {'Q/V %':>10s} {'Qty':>10s} {'Amt(w)':>10s} {'Perm(bp)':>10s} {'Temp(bp)':>10s} {'Total(bp)':>10s}")
print("  " + "-" * 60)
for qv_pct in [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
    q_over_v = qv_pct / 100
    qty = q_over_v * V
    amt_val = qty * close.iloc[-1] / 1e4
    perm = 0.1 * sigma * (q_over_v ** 0.3)
    temp = 0.5 * sigma * (q_over_v ** 0.5)
    total = perm + temp
    print(f"  {qv_pct:>9.3f}% {qty:>10.0f} {amt_val:>8.1f}  {perm*10000:>8.2f} {temp*10000:>8.2f} {total*10000:>8.2f}")

# --- Non-linearity analysis ---
print()
print("=" * 70)
print("NON-LINEARITY ANALYSIS")
print("=" * 70)
for qv_pct in [0.01, 0.1, 1.0, 5.0]:
    q_over_v = qv_pct / 100
    perm_nl = 0.1 * sigma * (q_over_v ** 0.3)
    temp_nl = 0.5 * sigma * (q_over_v ** 0.5)
    total_nl = perm_nl + temp_nl
    perm_lin = 0.1 * sigma * q_over_v
    temp_lin = 0.5 * sigma * q_over_v
    total_lin = perm_lin + temp_lin
    ratio = total_nl / total_lin if total_lin > 0 else 0
    print(f"  Q/V={qv_pct:.2f}%: Non-linear={total_nl*10000:.2f}bp | Linear={total_lin*10000:.2f}bp | Ratio={ratio:.2f}x")

# --- Capital capacity for 601857 specific ---
print()
print("=" * 70)
print("CAPITAL CAPACITY BREAKDOWN (601857)")
print("=" * 70)
print(f"  {'Impact(bp)':>12s} {'Max Qty':>12s} {'Amount(CNY)':>14s} {'% of ADV':>10s}")
print("  " + "-" * 48)
for target_bp in [1, 2, 5, 10, 20, 50]:
    target = target_bp / 10000
    x = 0.01
    for _ in range(100):
        f = 0.1 * sigma * (x**0.3) + 0.5 * sigma * (x**0.5) - target
        if abs(f) < 1e-12:
            break
        dfx = 0.03 * sigma * (x**-0.7) + 0.25 * sigma * (x**-0.5)
        x = x - f / dfx
        x = max(0.0001, min(x, 1.0))
    qty = x * V
    amt_val = qty * close.iloc[-1]
    pct_adv = x * 100
    print(f"  {target_bp:>10d}bp {qty:>10.0f} {amt_val:>12.0f}  {pct_adv:>7.3f}%")

print()
print("Done.")
