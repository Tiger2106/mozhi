"""
VERIFY-003 随机因子噪声测试 — 核心分析模块

基于真实A50行情数据，使用随机噪声代替因子值，
验证IC管线对随机噪声不会产生系统性偏差。
"""
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

_MOZHI_ROOT = Path("C:/Users/17699/mozhi_platform").resolve()
if str(_MOZHI_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOZHI_ROOT))

from src.ic.engine import IC_Engine

TZ = timezone(timedelta(hours=8))
DB_PATH = r"C:\Users\17699\mozhi_platform\data\market\a50_ic.db"


# ── 数据获取 ─────────────────────────────────────────


def get_recent_trade_dates(
    conn: sqlite3.Connection,
    n_dates: int = 50,
) -> List[str]:
    """获取最近 N 个交易日的日期列表（升序）。"""
    rows = conn.execute(
        """
        SELECT DISTINCT trade_date
        FROM a50_daily_ohlcv
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (n_dates,),
    ).fetchall()
    dates = [r[0] for r in rows]
    dates.reverse()
    return dates


def get_stock_codes(conn: sqlite3.Connection) -> List[str]:
    """获取A50成分股代码列表。"""
    rows = conn.execute(
        "SELECT ts_code FROM a50_universe ORDER BY ts_code"
    ).fetchall()
    return [r[0] for r in rows]


def get_forward_returns(
    conn: sqlite3.Connection,
    trade_date: str,
    stock_codes: List[str],
    forward_window: int = 1,
) -> pd.Series:
    """获取指定截面日的前向收益（adj_close_b 计算）。

    前向收益 = adj_close_b[t+N] / adj_close_b[t] - 1，N=forward_window 个交易日。
    """
    date_std = trade_date.replace("-", "")
    placeholders = ",".join("?" for _ in stock_codes)

    # 获取截面日价格
    rows = conn.execute(
        f"""
        SELECT ts_code, adj_close_b
        FROM a50_daily_ohlcv
        WHERE trade_date = ?
          AND ts_code IN ({placeholders})
          AND adj_close_b IS NOT NULL
        """,
        [date_std] + stock_codes,
    ).fetchall()
    price_map = {r[0]: r[1] for r in rows}

    # 获取未来第 N 个交易日价格
    future_rows = conn.execute(
        f"""
        SELECT ts_code, adj_close_b, trade_date
        FROM a50_daily_ohlcv
        WHERE trade_date > ?
          AND ts_code IN ({placeholders})
          AND adj_close_b IS NOT NULL
        ORDER BY ts_code, trade_date
        """,
        [date_std] + stock_codes,
    ).fetchall()

    grouped: Dict[str, list] = defaultdict(list)
    for r in future_rows:
        grouped[r[0]].append(r[1])

    fr_map: Dict[str, float] = {}
    for code in stock_codes:
        if code not in price_map or price_map[code] is None or price_map[code] == 0:
            continue
        future_list = grouped.get(code, [])
        if len(future_list) < forward_window:
            continue
        price_future = future_list[forward_window - 1]
        if price_future is None or price_future == 0:
            continue
        fr_map[code] = price_future / price_map[code] - 1.0

    return pd.Series(fr_map, dtype=np.float64)


# ── 随机因子生成 ──────────────────────────────────────


def generate_random_factor(
    n_stocks: int,
    seed: int,
    distribution: str = "normal",
) -> np.ndarray:
    """生成与 A50 成分股数等长的随机因子值。"""
    rng = np.random.default_rng(seed)
    if distribution == "normal":
        return rng.normal(loc=0.0, scale=1.0, size=n_stocks)
    elif distribution == "uniform":
        return rng.uniform(low=-1.73, high=1.73, size=n_stocks)
    elif distribution == "student_t":
        return rng.standard_t(df=5, size=n_stocks)
    else:
        raise ValueError(f"Unknown distribution: {distribution}")


# ── 单次试验 ──────────────────────────────────────────


def run_single_trial(
    trade_date: str,
    stock_codes: List[str],
    forward_returns: pd.Series,
    seed: int,
    distribution: str = "normal",
    min_stocks: int = 30,
    engine: Optional[IC_Engine] = None,
) -> Optional[Dict[str, Any]]:
    """单次随机因子 IC 试验。"""
    if engine is None:
        engine = IC_Engine(min_obs=5)

    available_codes = [c for c in stock_codes if c in forward_returns.index]
    n_available = len(available_codes)
    if n_available < min_stocks:
        return None

    random_factors = generate_random_factor(n_available, seed, distribution)
    fr_values = forward_returns[available_codes].values

    result = engine.compute_rank_ic(
        factor_values=random_factors,
        forward_returns=fr_values,
        date=trade_date,
    )
    if result is not None:
        result["seed"] = seed
        result["n_stocks"] = n_available
        result["distribution"] = distribution

    return result


# ── 多截面多试验套件 ──────────────────────────────────


def run_noise_ic_suite(
    trade_dates: List[str],
    stock_codes: List[str],
    seeds: List[int],
    db_path: str = DB_PATH,
    forward_window: int = 1,
    min_stocks: int = 30,
    distribution: str = "normal",
) -> pd.DataFrame:
    """运行随机因子 IC 试验套件。

    对每个截面日 × 每个随机种子，计算随机因子与真实前向收益的 Rank IC。

    Returns
    -------
    pd.DataFrame with columns: trade_date, seed, rank_ic, ic_value, p_value, n_stocks
    """
    engine = IC_Engine(min_obs=5)
    conn = sqlite3.connect(db_path)
    all_results: List[Dict[str, Any]] = []

    try:
        for td in trade_dates:
            date_std = td.replace("-", "")
            fr = get_forward_returns(conn, date_std, stock_codes, forward_window)
            for seed in seeds:
                result = run_single_trial(
                    trade_date=td, stock_codes=stock_codes,
                    forward_returns=fr, seed=seed,
                    distribution=distribution, min_stocks=min_stocks,
                    engine=engine,
                )
                if result is not None:
                    all_results.append(result)
    finally:
        conn.close()

    return pd.DataFrame(all_results)


# ── 结果分析 ──────────────────────────────────────────


def analyze_noise_ic_results(
    df: pd.DataFrame,
    n_stocks_expected: int = 50,
) -> Dict[str, Any]:
    """分析随机因子 IC 试验结果。"""
    if df.empty:
        return {"n_trials": 0, "error": "empty dataframe"}

    ic_values = df["rank_ic"].dropna().values
    n = len(ic_values)
    n_stocks_avg = df["n_stocks"].mean()
    n_stocks = round(n_stocks_avg) if not np.isnan(n_stocks_avg) else n_stocks_expected

    std_theoretical = 1.0 / np.sqrt(n_stocks - 1) if n_stocks > 1 else np.nan

    p_sig_count = int((df["p_value"] < 0.05).sum())
    p_sig_rate = p_sig_count / n if n > 0 else 0.0

    # Wilson score interval for binomial proportion
    if n > 0:
        z = 1.96
        p_hat = p_sig_rate
        denom = 1 + z**2 / n
        center = (p_hat + z**2 / (2 * n)) / denom
        margin = z * np.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denom
        ci_lower = max(0, center - margin)
        ci_upper = min(1, center + margin)
    else:
        ci_lower = ci_upper = 0.0

    # 兼容 date / trade_date 两种命名
    date_col = "trade_date" if "trade_date" in df.columns else ("date" if "date" in df.columns else None)

    by_seed = {}
    if "seed" in df.columns:
        for seed, grp in df.groupby("seed"):
            grp_ic = grp["rank_ic"].dropna()
            grp_p = grp["p_value"].dropna()
            by_seed[int(seed)] = {
                "n": len(grp_ic),
                "ic_mean": float(grp_ic.mean()),
                "ic_std": float(grp_ic.std()),
                "p_sig_rate": float((grp_p < 0.05).sum() / max(len(grp_p), 1)),
                "positive_rate": float((grp_ic > 0).sum() / max(len(grp_ic), 1)),
            }

    return {
        "n_trials": n,
        "n_dates": int(df[date_col].nunique()) if date_col and date_col in df.columns else 0,
        "n_seeds": int(df["seed"].nunique()) if "seed" in df.columns else 0,
        "n_stocks_avg": float(n_stocks_avg),
        "ic_mean": float(np.mean(ic_values)),
        "ic_std": float(np.std(ic_values, ddof=1)),
        "ic_std_theoretical": float(std_theoretical),
        "p_value_mean": float(np.mean(df["p_value"].dropna())),
        "p_value_std": float(np.std(df["p_value"].dropna(), ddof=1)),
        "p_sig_count": p_sig_count,
        "p_sig_rate": float(p_sig_rate),
        "p_sig_rate_ci": [float(ci_lower), float(ci_upper)],
        "positive_count": int((ic_values > 0).sum()),
        "positive_rate": float((ic_values > 0).sum() / n),
        "t_stat_mean": float(np.mean(df["t_stat"].dropna())),
        "min_ic": float(np.min(ic_values)),
        "max_ic": float(np.max(ic_values)),
        "by_seed": by_seed,
    }


def print_analysis_report(stats: Dict[str, Any]) -> None:
    """打印分析报告。"""
    print("=" * 60)
    print("VERIFY-003 随机因子噪声测试报告")
    print("=" * 60)
    print(f"\n试验概览:")
    print(f"  有效试验次数: {stats['n_trials']}")
    print(f"  截面数:       {stats['n_dates']}")
    print(f"  种子组数:     {stats['n_seeds']}")
    print(f"  平均成分股数: {stats['n_stocks_avg']:.1f}")

    print(f"\nIC统计:")
    print(f"  Rank IC 均值:       {stats['ic_mean']:.6f}  (期望: 0.000)")
    print(f"  Rank IC 标准差:     {stats['ic_std']:.6f}")
    print(f"  理论标准差 (H0):    {stats['ic_std_theoretical']:.6f}")

    print(f"\np值统计:")
    print(f"  p值均值:    {stats['p_value_mean']:.4f}")
    print(f"  p值标准差:  {stats['p_value_std']:.4f}")
    print(f"  p<0.05比例: {stats['p_sig_rate']:.4f}  (期望: 0.050)")
    print(f"  95% CI:     [{stats['p_sig_rate_ci'][0]:.4f}, {stats['p_sig_rate_ci'][1]:.4f}]")

    print(f"\n正负比率:")
    print(f"  IC>0比例:  {stats['positive_rate']:.4f}  (期望: 0.500)")
    print(f"  IC范围:    [{stats['min_ic']:.4f}, {stats['max_ic']:.4f}]")

    print(f"\n按种子分组:")
    for seed, s in stats.get("by_seed", {}).items():
        print(f"  seed={seed:>5d}: n={s['n']:>3d}  "
              f"ic_mean={s['ic_mean']:+.4f}  ic_std={s['ic_std']:.4f}  "
              f"p_sig={s['p_sig_rate']:.3f}  pos={s['positive_rate']:.3f}")

    print(f"\n{'='*60}")
    print("综合判定:")
    ic_mean_ok = abs(stats["ic_mean"]) < 0.01
    ic_std_ok = abs(stats["ic_std"] - stats["ic_std_theoretical"]) < 0.03
    p_sig_ok = 0.03 <= stats["p_sig_rate"] <= 0.07
    pos_ok = 0.40 <= stats["positive_rate"] <= 0.60

    checks = [
        ("IC均值 ≈ 0", ic_mean_ok, f"{stats['ic_mean']:.6f}"),
        ("IC标准差 ≈ 1/sqrt(n-1)", ic_std_ok,
         f"{stats['ic_std']:.4f} vs {stats['ic_std_theoretical']:.4f}"),
        ("p<0.05 显著率 ≈ 5%", p_sig_ok, f"{stats['p_sig_rate']:.4f}"),
        ("正比率 ≈ 50%", pos_ok, f"{stats['positive_rate']:.4f}"),
    ]

    all_pass = all(c[1] for c in checks)
    for name, passed, val in checks:
        mark = "PASS" if passed else "WARN"
        print(f"  [{mark}] {name}: {val}")

    print(f"\n  总判定: {'PASSED' if all_pass else 'NEED_REVIEW'}")
    print("=" * 60)
