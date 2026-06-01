"""
EXP-2026-003-KNOWDEEP Q4: 组合回测(真实交易条件模拟)
=====================================================
author: 墨衡 (moheng)
created: 2026-05-27T13:08+08:00

在真实交易条件下模拟C1-RWC方案，补全三项缺口：
  1. 极端行情压力测试 (2015股灾, 2018熊市)
  2. 费用扣除净收益 (单边0.155%, 双边0.31%)
  3. 完整资金曲线 (2015-2025)

### 标的 (排除宁德时代后的10只)
  600519.SH, 601318.SH, 600276.SH, 600030.SH, 600036.SH,
  601166.SH, 002594.SZ, 600887.SH, 000333.SZ, 000858.SZ

### 回测方案
  - 主方案: C1-RWC (HV=0.5, MV=0.3, LV=0.2)
  - 对比方案: C3-RWC-U (统一权重0.33/0.33/0.33)
  - 基准: 等权持有10只标的

### 回测参数
  - 回测期: 2015-01-01 至 2025-12-31
  - 信号: 日频 l_vol_rsi_std 复合信号
  - 调仓: 每交易日
  - 交易成本: 单边0.155%, 双边0.31%
  - 初始资金: 200,000
  - 资金分配: 全仓
  - 随机种子: seed=42
"""

from __future__ import annotations

import json, os, sqlite3, sys, time
from datetime import datetime
import numpy as np
from typing import Dict, List, Tuple, Optional


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, (np.bool_,)): return bool(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return super().default(obj)


# ── 路径 ────────────────────────────────────────────────
PROJECT_ROOT = r"C:\Users\17699\mozhi_platform"
DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")
Q4_DIR = os.path.join(PROJECT_ROOT, "docs", "07_research", "EXP-2026-003-KNOWDEEP", "q4")
os.makedirs(Q4_DIR, exist_ok=True)

# ── 标的池 ──────────────────────────────────────────────
TICKERS = [
    "600519.SH", "601318.SH", "600276.SH", "600030.SH", "600036.SH",
    "601166.SH", "002594.SZ", "600887.SH", "000333.SZ", "000858.SZ",
]

# ── 参数 ────────────────────────────────────────────────
INITIAL_CAPITAL = 200_000.0
FEE_SINGLE = 0.00155
RISK_FREE_RATE = 0.025
SEED = 42

RWC_WEIGHTS = {"high_vol": 0.5, "mid_vol": 0.3, "low_vol": 0.2}
RWC_U_WEIGHTS = {"high_vol": 1/3, "mid_vol": 1/3, "low_vol": 1/3}

CRASH_2015 = ("20150601", "20160131")
BEAR_2018  = ("20180101", "20181231")


# ═══════════════════════════════════════════════════════════
#  因子计算
# ═══════════════════════════════════════════════════════════

def calc_vol_rsi_std(volume: np.ndarray, rsi_period: int = 14, std_period: int = 20) -> np.ndarray:
    volume = np.asarray(volume, dtype=float)
    n = len(volume)
    result = np.full(n, np.nan)
    if n < rsi_period + std_period:
        return result
    vol_change = np.diff(volume)
    vol_change = np.concatenate([[0.0], vol_change])
    gain = np.clip(vol_change, 0, None)
    loss = np.clip(-vol_change, 0, None)
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    avg_gain[rsi_period] = np.mean(gain[1:rsi_period + 1])
    avg_loss[rsi_period] = np.mean(loss[1:rsi_period + 1])
    for i in range(rsi_period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (rsi_period - 1) + gain[i]) / rsi_period
        avg_loss[i] = (avg_loss[i - 1] * (rsi_period - 1) + loss[i]) / rsi_period
    rs = avg_gain / (avg_loss + 1e-10)
    vol_rsi = 100.0 - (100.0 / (1.0 + rs))
    for i in range(rsi_period + std_period - 1, n):
        result[i] = np.std(vol_rsi[i - std_period + 1:i + 1])
    return result


def reverse_factor(factor_series: np.ndarray) -> np.ndarray:
    return -1.0 * np.asarray(factor_series, dtype=float)


def classify_market_state(close: np.ndarray) -> Tuple[np.ndarray, float, float]:
    close = np.asarray(close, dtype=float)
    n = len(close)
    returns = np.diff(close) / close[:-1]
    returns = np.concatenate([[0.0], returns])
    rolling_vol = np.full(n, np.nan)
    for i in range(20, n):
        rolling_vol[i] = np.std(returns[i - 19:i + 1]) * np.sqrt(252)
    state = np.ones(n, dtype=np.int8)
    vol_series = rolling_vol[~np.isnan(rolling_vol)]
    if len(vol_series) < 10:
        return state, 0.0, 0.0
    high_threshold = np.percentile(vol_series, 80.0)
    low_threshold = np.percentile(vol_series, 30.0)
    for i in range(n):
        if np.isnan(rolling_vol[i]):
            state[i] = 1
        elif rolling_vol[i] >= high_threshold:
            state[i] = 2
        elif rolling_vol[i] < low_threshold:
            state[i] = 0
        else:
            state[i] = 1
    return state, high_threshold, low_threshold


# ═══════════════════════════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════════════════════════

def load_stock_data(ticker: str) -> Optional[Dict]:
    code = ticker.split(".")[0]
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT trade_date, close, volume FROM stock_daily "
        "WHERE ts_code=? AND trade_date>=? AND trade_date<=? "
        "ORDER BY trade_date",
        (ticker, "20150101", "20251231")
    ).fetchall()
    conn.close()
    if not rows:
        return None
    dates = [r[0] for r in rows]
    return {
        "ticker": ticker,
        "dates": dates,
        "close": np.array([r[1] for r in rows], dtype=float),
        "volume": np.array([r[2] for r in rows], dtype=float),
    }


# ═══════════════════════════════════════════════════════════
#  信号生成（与 Q3 完全一致）
# ═══════════════════════════════════════════════════════════

def compute_signal_vector(stock_data: Dict, weights: Dict[str, float]) -> Dict[str, np.ndarray]:
    """
    为每只股票生成日频 C1-RWC 信号。

    流程:
      1. calc_vol_rsi_std(volume) → 原始因子
      2. classify_market_state(close) → 0/1/2 状态
      3. 按状态加权: composite = w[state] * vol_rsi_std
      4. reverse_factor → 最终的 trading signal

    Q3 的 IC 测试 IC(reversed_composite, fwd_ret) > 0,
    因此 trading signal = -composite.
    """
    state_map = {0: "low_vol", 1: "mid_vol", 2: "high_vol"}
    signals = {}
    for ticker, sd in stock_data.items():
        vol_std = calc_vol_rsi_std(sd["volume"])
        states, _, _ = classify_market_state(sd["close"])
        n = len(vol_std)
        composite = np.full(n, np.nan)
        for i in range(n):
            if np.isnan(vol_std[i]):
                continue
            sl = state_map.get(int(states[i]), "mid_vol")
            composite[i] = weights[sl] * vol_std[i]
        # reverse_factor: trading signal = -composite
        # High signal (close to 0) = stronger buy
        signals[ticker] = reverse_factor(composite)
    return signals


# ═══════════════════════════════════════════════════════════
#  投资组合回测
# ═══════════════════════════════════════════════════════════

def run_portfolio_backtest(
    stock_data: Dict[str, Dict],
    signals: Dict[str, np.ndarray],
    name: str,
) -> Dict:
    """
    组合回测主函数。

    策略: 信号加权全仓做多
    流程:
      1. 找全部共同的交易日
      2. 每交易日: 取所有有有效信号的标的, 按信号值 min-max → [0,1] → 归一化为权重
      3. 等比例分配所有资金
      4. 执行调仓, 扣除费用
      5. 记录净值曲线
    """

    # ── 构建日期索引 ──
    tickers = list(stock_data.keys())
    date_to_ticker_idx = {}  # date -> {ticker: data_index}
    for ticker, sd in stock_data.items():
        for i, d in enumerate(sd["dates"]):
            date_to_ticker_idx.setdefault(d, {})[ticker] = i

    all_dates = sorted(date_to_ticker_idx.keys())
    print(f"    {name}: {len(all_dates)} common trading days")

    # ── 初始化 ──
    cash = float(INITIAL_CAPITAL)
    positions = {t: 0 for t in tickers}  # shares held
    total_fees = 0.0
    total_trades = 0
    equity_curve = []
    trade_log = []

    for di, date in enumerate(all_dates):
        # 收集当日有效标的的信息
        valid = []
        for t in tickers:
            idx = date_to_ticker_idx[date].get(t)
            if idx is None:
                continue
            close = stock_data[t]["close"][idx]
            if close <= 0 or np.isnan(close):
                continue
            sig_arr = signals.get(t)
            if sig_arr is None or idx >= len(sig_arr) or np.isnan(sig_arr[idx]):
                continue
            valid.append((t, close, sig_arr[idx]))

        if not valid:
            # 无数据交易日, 但已有持仓需要估值
            eq = cash
            for t in tickers:
                idx = date_to_ticker_idx[date].get(t)
                if idx is not None:
                    eq += positions[t] * stock_data[t]["close"][idx]
            equity_curve.append({"date": date, "total_equity": round(eq, 2)})
            continue

        # ── 计算当前权益 ──
        # prev = 前一日权益 or 初始资金
        # 实际上这里应该用前一日结束时的权益来算当日调仓
        # 先计算持仓市值
        cur_equity = cash
        for t in tickers:
            if positions.get(t, 0) <= 0:
                continue
            idx = date_to_ticker_idx.get(date, {}).get(t)
            if idx is not None:
                cur_equity += positions[t] * stock_data[t]["close"][idx]

        if di == 0:
            cur_equity = INITIAL_CAPITAL

        equity_curve.append({"date": date, "total_equity": round(cur_equity, 2)})

        # ── 计算目标权重 ──
        tickers_v = [v[0] for v in valid]
        prices_v = np.array([v[1] for v in valid])
        sigs_v = np.array([v[2] for v in valid])

        # 信号归一化 [0, 1]
        smin, smax = np.min(sigs_v), np.max(sigs_v)
        if smax - smin > 1e-12:
            sig_norm = (sigs_v - smin) / (smax - smin)
        else:
            sig_norm = np.ones(len(sigs_v)) / len(sigs_v)
        sig_norm = np.maximum(sig_norm, 1e-6)  # 避免0权重
        target_w = sig_norm / np.sum(sig_norm)

        # ── 执行调仓 ──
        # 目标持仓: 按权重分配全部资金
        new_positions = {}

        for j, t in enumerate(tickers_v):
            w = target_w[j]
            target_value = cur_equity * w
            price = prices_v[j]
            shares = int(target_value / price / 100) * 100  # 对齐100股/手
            if shares <= 0:
                new_positions[t] = 0
            else:
                new_positions[t] = shares

        # BUGFIX (2026-05-27 P0): 用现金余额直接追踪, 移除 allocated 模型
        # allocated 模型(remaining_cash=cur_equity-allocated)造成买入资金双倍扣减:
        #   - allocated 已包含全部目标买入成本
        #   - 买入循环又对增量部分再扣一次
        # 修复: remaining_cash 直接用 cash, 由买卖循环自然更新
        remaining_cash = cash

        # 计算成交额和费用 (只有变动部分产生费用)
        for t in tickers:
            current = positions.get(t, 0)
            target = new_positions.get(t, 0)
            if target > current:
                # 买入
                idx = date_to_ticker_idx.get(date, {}).get(t)
                if idx is None:
                    continue
                price = stock_data[t]["close"][idx]
                buy_shares = target - current
                trade_val = buy_shares * price
                fee = trade_val * FEE_SINGLE
                total_fees += fee
                total_trades += 1
                remaining_cash -= trade_val + fee
                trade_log.append({
                    "date": date, "ticker": t, "side": "buy",
                    "shares": buy_shares, "price": round(price, 2),
                    "fee": round(fee, 2),
                })

        # 卖出也产生费用 (但做多策略很少卖出, 主要是调仓降低仓位)
        for t in tickers:
            current = positions.get(t, 0)
            target = new_positions.get(t, 0)
            if current > target:
                sell_shares = current - target
                idx = date_to_ticker_idx.get(date, {}).get(t)
                if idx is None:
                    continue
                price = stock_data[t]["close"][idx]
                trade_val = sell_shares * price
                fee = trade_val * FEE_SINGLE
                total_fees += fee
                total_trades += 1
                remaining_cash += trade_val - fee
                trade_log.append({
                    "date": date, "ticker": t, "side": "sell",
                    "shares": sell_shares, "price": round(price, 2),
                    "fee": round(fee, 2),
                })

        positions = new_positions
        cash = remaining_cash

    # ── 计算绩效指标 ──
    metrics = compute_metrics(equity_curve, INITIAL_CAPITAL,
                              total_fees, total_trades, name)
    metrics["equity_curve"] = equity_curve
    return metrics


def compute_metrics(equity_curve, initial_capital, total_fees, total_trades, name):
    if not equity_curve:
        return {"error": "No equity curve"}

    eq_vals = np.array([p["total_equity"] for p in equity_curve])
    dates = [p["date"] for p in equity_curve]
    n = len(eq_vals)

    total_return = (eq_vals[-1] - initial_capital) / initial_capital
    years = n / 250.0
    cagr = (eq_vals[-1] / initial_capital) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    # 最大回撤
    peak = np.maximum.accumulate(eq_vals)
    dd = np.where(peak > 0, (peak - eq_vals) / peak, 0.0)
    max_dd = float(np.max(dd))
    max_dd_idx = int(np.argmax(dd))
    mdd_start = dates[int(np.argmax(peak[:max_dd_idx + 1]))] if max_dd_idx > 0 else dates[0]
    mdd_end = dates[max_dd_idx] if max_dd_idx < len(dates) else dates[-1]

    # 日收益率
    eq_vals_safe = np.maximum(eq_vals, 1.0)  # avoid div by zero
    daily_ret = np.diff(eq_vals_safe) / eq_vals_safe[:-1]
    daily_ret = np.nan_to_num(daily_ret, nan=0.0, posinf=0.0, neginf=0.0)
    daily_ret = np.concatenate([[0.0], daily_ret])

    ann_vol = float(np.nanstd(daily_ret) * np.sqrt(250.0)) if len(daily_ret) > 1 else 0.0
    sharpe = (cagr - RISK_FREE_RATE) / ann_vol if ann_vol > 1e-12 else 0.0

    downside = daily_ret[daily_ret < 0]
    down_vol = float(np.nanstd(downside) * np.sqrt(250.0)) if len(downside) > 1 else 0.0
    sortino = (cagr - RISK_FREE_RATE) / down_vol if down_vol > 1e-12 else 0.0

    win_rate = float(np.sum(daily_ret > 0)) / len(daily_ret) if len(daily_ret) > 0 else 0.0

    fee_pct = total_fees / initial_capital
    avg_trades = total_trades / years if years > 0 else 0.0

    return {
        "name": name,
        "initial_capital": round(initial_capital, 2),
        "final_equity": round(float(eq_vals[-1]), 2),
        "total_return_pct": round(float(total_return) * 100, 4),
        "cagr_pct": round(float(cagr) * 100, 4),
        "max_drawdown_pct": round(float(max_dd) * 100, 4),
        "max_drawdown_period": f"{mdd_start} ~ {mdd_end}",
        "annual_volatility_pct": round(ann_vol * 100, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "win_rate_pct": round(win_rate * 100, 4),
        "total_trades": total_trades,
        "total_fees_paid": round(total_fees, 2),
        "fees_as_pct_of_initial": round(float(fee_pct) * 100, 4),
        "avg_trades_per_year": round(avg_trades, 2),
    }


# ═══════════════════════════════════════════════════════════
#  基准计算 (等权持有, 每月调仓)
# ═══════════════════════════════════════════════════════════

def run_benchmark(stock_data: Dict[str, Dict]) -> Dict:
    """等权买入持有, 每20交易日调仓一次"""
    tickers = list(stock_data.keys())
    n = len(tickers)

    date_to_idx = {}
    for t, sd in stock_data.items():
        for i, d in enumerate(sd["dates"]):
            date_to_idx.setdefault(d, {})[t] = i
    all_dates = sorted(date_to_idx.keys())

    cash = INITIAL_CAPITAL
    positions = {t: 0 for t in tickers}
    total_fees = 0.0
    equity_curve = []
    rebal_counter = 0

    for di, date in enumerate(all_dates):
        # 估值
        eq = cash
        for t in tickers:
            idx = date_to_idx[date].get(t)
            if idx is not None:
                eq += positions[t] * stock_data[t]["close"][idx]

        equity_curve.append({"date": date, "total_equity": round(eq, 2)})

        if di == 0:
            # 初始建仓
            target_per = eq / n
            for t in tickers:
                idx = date_to_idx[date].get(t)
                if idx is None:
                    continue
                price = stock_data[t]["close"][idx]
                shares = int(target_per / price)
                cost = shares * price
                fee = cost * FEE_SINGLE
                total_fees += fee
                cash -= cost + fee
                positions[t] = shares
            continue

        rebal_counter += 1
        if rebal_counter >= 20:
            rebal_counter = 0
            target_per = eq / n
            rows = []
            for t in tickers:
                idx = date_to_idx[date].get(t)
                if idx is None:
                    continue
                price = stock_data[t]["close"][idx]
                target_shares = int(target_per / price)
                rows.append((t, price, target_shares))

            # 先卖出超额的
            for t, price, target in rows:
                diff = positions[t] - target
                if diff > 0:
                    cash += diff * price
                    fee = diff * price * FEE_SINGLE
                    total_fees += fee
                    cash -= fee
                    positions[t] = target

            # 再买入不足的
            for t, price, target in rows:
                diff = target - positions[t]
                if diff > 0:
                    cost = diff * price
                    fee = cost * FEE_SINGLE
                    total_fees += fee
                    cash -= cost + fee
                    positions[t] = target

    eq_vals = np.array([p["total_equity"] for p in equity_curve])
    total_return = (eq_vals[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL
    years = len(eq_vals) / 250.0
    cagr = (eq_vals[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    peak = np.maximum.accumulate(eq_vals)
    dd = np.where(peak > 0, (peak - eq_vals) / peak, 0.0)
    max_dd = float(np.max(dd))

    return {
        "name": "benchmark_ew",
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": round(float(eq_vals[-1]), 2),
        "total_return_pct": round(float(total_return) * 100, 4),
        "cagr_pct": round(float(cagr) * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "equity_curve": equity_curve,
    }


# ═══════════════════════════════════════════════════════════
#  子窗口分析
# ═══════════════════════════════════════════════════════════

def extract_window(equity_curve: List[Dict], start: str, end: str) -> Dict:
    window = [p for p in equity_curve if start <= p["date"] <= end]
    if len(window) < 2:
        return {"trading_days": len(window), "error": "insufficient data"}
    eq_vals = np.array([p["total_equity"] for p in window])
    w_init = window[0]["total_equity"]
    w_final = window[-1]["total_equity"]
    total_ret = (w_final - w_init) / w_init if w_init > 0 else 0.0
    peak = np.maximum.accumulate(eq_vals)
    dd = np.where(peak > 0, (peak - eq_vals) / peak, 0.0)
    max_dd = float(np.max(dd))
    return {
        "trading_days": len(window),
        "start_date": window[0]["date"],
        "end_date": window[-1]["date"],
        "initial_equity": round(float(w_init), 2),
        "final_equity": round(float(w_final), 2),
        "total_return_pct": round(float(total_ret) * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
    }


# ═══════════════════════════════════════════════════════════
#  对比分析
# ═══════════════════════════════════════════════════════════

def compare(c1, c3, bm):
    comp = {}
    c1_curve = {p["date"]: p["total_equity"] for p in c1.get("equity_curve", [])}
    c3_curve = {p["date"]: p["total_equity"] for p in c3.get("equity_curve", [])}
    bm_curve = {p["date"]: p["total_equity"] for p in bm.get("equity_curve", [])}
    common = sorted(set(c1_curve) & set(c3_curve) & set(bm_curve))
    if len(common) < 10:
        return {"error": "insufficient data"}
    c1_excess = [c1_curve[d] - bm_curve[d] for d in common]
    c3_excess = [c3_curve[d] - bm_curve[d] for d in common]
    c1_pct = c1.get("total_return_pct", 0)
    c3_pct = c3.get("total_return_pct", 0)
    bm_pct = bm.get("total_return_pct", 0)
    comp["c1_vs_benchmark"] = {
        "excess_return_pct": round(c1_pct - bm_pct, 4),
    }
    comp["c3_vs_benchmark"] = {
        "excess_return_pct": round(c3_pct - bm_pct, 4),
    }
    comp["c1_vs_c3"] = {
        "c1_advantage": c1_pct > c3_pct,
        "c1_over_benchmark": c1_pct > bm_pct,
        "c3_over_benchmark": c3_pct > bm_pct,
    }
    return comp


# ═══════════════════════════════════════════════════════════
#  费用影响
# ═══════════════════════════════════════════════════════════

def fee_analysis(c1):
    fees = c1.get("total_fees_paid", 0)
    initial = c1.get("initial_capital", INITIAL_CAPITAL)
    net_ret = c1.get("total_return_pct", 0)
    fee_pct = fees / initial * 100
    return {
        "total_fees_paid": round(fees, 2),
        "fees_as_pct_of_initial": round(fee_pct, 4),
        "avg_trades_per_year": c1.get("avg_trades_per_year", 0),
        "gross_return_pct": round(net_ret + fee_pct, 4),
        "net_return_pct": round(net_ret, 4),
        "fee_drag_pct": round(fee_pct, 4),
    }


# ═══════════════════════════════════════════════════════════
#  报告生成
# ═══════════════════════════════════════════════════════════

def generate_report(results: Dict, path: str):
    c1 = results["c1_rwc"]
    c3 = results["c3_rwc_u"]
    bm = results["benchmark_ew"]
    fee = results["fee_impact"]
    comp = results["comparison"]
    ew = results["extreme_windows"]

    lines = [
        f"# EXP-2026-003-KNOWDEEP Q4：组合回测报告",
        f"",
        f"> author: 墨衡 (moheng)  |  created: {results['run_timestamp']}  |  elapsed: {results['elapsed_seconds']}s",
        f"",
        f"---",
        f"",
        f"## 一、回测配置",
        f"",
        f"| 参数 | 值 |",
        f"|:----|:---|",
        f"| 回测期 | {results['config']['backtest_period']} |",
        f"| 标的数 | {results['config']['n_tickers']} 只 |",
        f"| 初始资金 | ¥{results['config']['initial_capital']:,.0f} |",
        f"| 信号频率 | 日频 |",
        f"| 调仓频率 | 每交易日 |",
        f"| 交易成本 | 单边{results['config']['fee_single_side']*100:.3f}%, 双边{results['config']['fee_round_trip']*100:.2f}% |",
        f"| 资金分配 | 全仓, 不保留现金 |",
        f"| 无风险利率 | {results['config']['risk_free_rate']*100:.1f}% |",
        f"| 随机种子 | seed={results['config']['random_seed']} |",
        f"",
        f"### 标的列表",
        f"",
    ]
    for i, t in enumerate(results["config"]["tickers"], 1):
        lines.append(f"- {i}. `{t}`")
    lines += [
        f"",
        f"---",
        f"",
        f"## 二、方案定义",
        f"",
        f"| 方案 | 权重 | 说明 |",
        f"|:----|:----|:------|",
        f"| **C1-RWC** | HV=0.5, MV=0.3, LV=0.2 | 主方案, 加权状态依赖 |",
        f"| **C3-RWC-U** | 0.33/0.33/0.33 | 对比方案, 统一权重 |",
        f"| **基准** | 等权持有10只 | 买入持有, 每月调仓 |",
        f"",
        f"---",
        f"",
        f"## 三、总收益对比",
        f"",
        f"| 指标 | C1-RWC | C3-RWC-U | 基准(EW) |",
        f"|:----|:------:|:--------:|:--------:|",
        f"| 总收益率 | {c1['total_return_pct']:.2f}% | {c3['total_return_pct']:.2f}% | {bm['total_return_pct']:.2f}% |",
        f"| 年化(CAGR) | {c1['cagr_pct']:.2f}% | {c3['cagr_pct']:.2f}% | {bm['cagr_pct']:.2f}% |",
        f"| 最大回撤 | {c1['max_drawdown_pct']:.2f}% | {c3['max_drawdown_pct']:.2f}% | {bm['max_drawdown_pct']:.2f}% |",
        f"| 夏普比率 | {c1['sharpe_ratio']:.2f} | {c3['sharpe_ratio']:.2f} | - |",
        f"| 索提诺 | {c1['sortino_ratio']:.2f} | {c3['sortino_ratio']:.2f} | - |",
        f"| 年化波动率 | {c1['annual_volatility_pct']:.2f}% | {c3['annual_volatility_pct']:.2f}% | - |",
        f"| 胜率 | {c1['win_rate_pct']:.2f}% | {c3['win_rate_pct']:.2f}% | - |",
        f"| 最终权益 | ¥{c1['final_equity']:,.2f} | ¥{c3['final_equity']:,.2f} | ¥{bm['final_equity']:,.2f} |",
        f"",
        f"---",
        f"",
        f"## 四、极端行情压力测试",
        f"",
        f"### 4.1 2015股灾 (2015-06 ~ 2016-01)",
        f"",
    ]
    cw = ew["crash_2015"]
    lines += [
        f"| 指标 | C1-RWC | C3-RWC-U | 基准 |",
        f"|:----|:------:|:--------:|:----:|",
        f"| 累计收益率 | {cw['C1_RWC']['total_return_pct']:.2f}% | {cw['C3_RWC_U']['total_return_pct']:.2f}% | {cw['benchmark']['total_return_pct']:.2f}% |",
        f"| 最大回撤 | {cw['C1_RWC']['max_drawdown_pct']:.2f}% | {cw['C3_RWC_U']['max_drawdown_pct']:.2f}% | {cw['benchmark']['max_drawdown_pct']:.2f}% |",
        f"| 交易日 | {cw['C1_RWC']['trading_days']} | {cw['C3_RWC_U']['trading_days']} | {cw['benchmark']['trading_days']} |",
        f"",
        f"### 4.2 2018熊市 (2018-01 ~ 2018-12)",
        f"",
    ]
    bw = ew["bear_2018"]
    def _safe_ew(d, key):
        if "error" in d:
            return d["error"]
        v = d.get(key)
        if v is None:
            return "N/A"
        if key == "trading_days":
            return str(v)
        return f"{v:.2f}%"
    lines += [
        f"| 指标 | C1-RWC | C3-RWC-U | 基准 |",
        f"|:----|:------:|:--------:|:----:|",
        f"| 累计收益率 | {_safe_ew(bw['C1_RWC'], 'total_return_pct')} | {_safe_ew(bw['C3_RWC_U'], 'total_return_pct')} | {_safe_ew(bw['benchmark'], 'total_return_pct')} |",
        f"| 最大回撤 | {_safe_ew(bw['C1_RWC'], 'max_drawdown_pct')} | {_safe_ew(bw['C3_RWC_U'], 'max_drawdown_pct')} | {_safe_ew(bw['benchmark'], 'max_drawdown_pct')} |",
        f"| 交易日 | {_safe_ew(bw['C1_RWC'], 'trading_days')} | {_safe_ew(bw['C3_RWC_U'], 'trading_days')} | {_safe_ew(bw['benchmark'], 'trading_days')} |",
        f"",
        f"---",
        f"",
        f"## 五、费用影响分析",
        f"",
        f"| 指标 | 值 |",
        f"|:----|:---|",
        f"| 总费用支出 | ¥{fee['total_fees_paid']:,.2f} |",
        f"| 费用占初始资金 | {fee['fees_as_pct_of_initial']:.2f}% |",
        f"| 年均交易次数 | {fee['avg_trades_per_year']:.0f} 次 |",
        f"| 推算毛收益率 | {fee['gross_return_pct']:.2f}% |",
        f"| 净收益率(已扣除) | {fee['net_return_pct']:.2f}% |",
        f"| 费用拖累 | {fee['fee_drag_pct']:.2f}% |",
        f"",
        f"---",
        f"",
        f"## 六、与基准对比",
        f"",
    ]
    c1vbm = comp.get("c1_vs_benchmark", {})
    c3vbm = comp.get("c3_vs_benchmark", {})
    c1vc3 = comp.get("c1_vs_c3", {})

    lines += [
        f"| 对比项 | C1-RWC vs 基准 | C3-RWC-U vs 基准 |",
        f"|:------|:--------------:|:----------------:|",
        f"| 超额收益 | {c1vbm.get('excess_return_pct', 0):.2f}% | {c3vbm.get('excess_return_pct', 0):.2f}% |",
        f"| C1 vs C3 | {'C1 优势' if c1vc3.get('c1_advantage') else 'C3 优势'} | - |",
        f"| 超越基准 | {'Yes' if c1vc3.get('c1_over_benchmark') else 'No'} | {'Yes' if c1vc3.get('c3_over_benchmark') else 'No'} |",
        f"",
        f"| 方案 | 终值净值 | 终值权益 |",
        f"|:----|:-------:|:--------:|",
        f"| C1-RWC | {c1['final_equity']/INITIAL_CAPITAL:.4f} | ¥{c1['final_equity']:,.2f} |",
        f"| C3-RWC-U | {c3['final_equity']/INITIAL_CAPITAL:.4f} | ¥{c3['final_equity']:,.2f} |",
        f"| 基准 | {bm['final_equity']/INITIAL_CAPITAL:.4f} | ¥{bm['final_equity']:,.2f} |",
        f"",
        f"---",
        f"",
        f"## 七、回撤详情",
        f"",
        f"| 方案 | 最大回撤 | 发生时段 |",
        f"|:----|:-------:|:---------|",
        f"| C1-RWC | {c1['max_drawdown_pct']:.2f}% | {c1['max_drawdown_period']} |",
        f"| C3-RWC-U | {c3['max_drawdown_pct']:.2f}% | {c3['max_drawdown_period']} |",
        f"| 基准 | {bm['max_drawdown_pct']:.2f}% | - |",
        f"",
        f"---",
        f"",
        f"## 八、摘要",
        f"",
    ]

    s = results["summary"]
    lines += [
        f"- C1-RWC 超越基准: {'Yes' if s['c1_vs_benchmark'] else 'No'}",
        f"- C1-RWC 优于 C3-RWC-U: {'Yes' if s['c1_vs_c3'] else 'No'}",
        f"- 夏普 > 1.0: {'Yes' if s['c1_sharpe_above_1'] else 'No'}",
        f"- 正向收益: {'Yes' if s['c1_positive_return'] else 'No'}",
        f"",
    ]

    c1_ret = c1.get("total_return_pct", 0)
    bm_ret = bm.get("total_return_pct", 0)
    if c1_ret > 0:
        concl = (
            f"C1-RWC 方案实现年化 {c1['cagr_pct']:.2f}%, "
            f"夏普 {c1['sharpe_ratio']:.2f}, "
            f"最大回撤 {c1['max_drawdown_pct']:.2f}%. "
        )
        if c1_ret > bm_ret:
            concl += f"超额基准 {c1_ret - bm_ret:.2f}%."
        else:
            concl += f"但未超越基准({bm_ret:.2f}%)."
    else:
        concl = "C1-RWC 在回测期未产生正收益."
    lines += [f"> {concl}", ""]

    lines += [
        f"### 资金曲线样本",
        f"",
        f"| 日期 | C1-RWC NAV | C3-RWC-U NAV | 基准 NAV |",
        f"|:----|:----------:|:------------:|:---------:|",
    ]
    c1_eq = c1.get("equity_curve", [])
    c3_eq = c3.get("equity_curve", [])
    bm_eq = bm.get("equity_curve", [])
    c1_map = {p["date"]: p["total_equity"] for p in c1_eq}
    c3_map = {p["date"]: p["total_equity"] for p in c3_eq}
    bm_map = {p["date"]: p["total_equity"] for p in bm_eq}
    sample_dates = sorted(set(c1_map) & set(c3_map) & set(bm_map))[::100]
    for d in sample_dates:
        lines.append(
            f"| {d} | {c1_map[d]/INITIAL_CAPITAL:.4f} | "
            f"{c3_map[d]/INITIAL_CAPITAL:.4f} | "
            f"{bm_map[d]/INITIAL_CAPITAL:.4f} |"
        )

    lines += [
        f"",
        f"---",
        f"*Report generated by moheng (DeepSeek R1) for EXP-2026-003-KNOWDEEP Q4*",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  [OK] Report written: {path}")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    rt = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    np.random.seed(SEED)

    print(f"EXP-2026-003 Q4 Portfolio Backtest  ({rt})")
    print(f"Tickers ({len(TICKERS)}): {', '.join(TICKERS)}")
    print("=" * 60)

    # ── 1. 加载数据 ──
    print("\n[1/8] Loading stock data...")
    stock_data = {}
    for ticker in TICKERS:
        sd = load_stock_data(ticker)
        if sd is None:
            print(f"  SKIP {ticker}: data not found")
            continue
        stock_data[ticker] = sd
    print(f"  Loaded {len(stock_data)}/{len(TICKERS)} stocks")

    # ── 2. 计算信号 ──
    print("\n[2/8] Computing C1-RWC signals...")
    c1_signals = compute_signal_vector(stock_data, RWC_WEIGHTS)

    print("[3/8] Computing C3-RWC-U signals...")
    c3_signals = compute_signal_vector(stock_data, RWC_U_WEIGHTS)

    # ── 3. 基准 ──
    print("[4/8] Computing benchmark (equal-weight, monthly rebal)...")
    benchmark_result = run_benchmark(stock_data)

    # ── 4. C1-RWC ──
    print("[5/8] Running C1-RWC backtest...")
    c1_result = run_portfolio_backtest(stock_data, c1_signals, "C1-RWC")
    _p = lambda k: c1_result.get(k, "N/A")
    print(f"    Final: {_p('final_equity')}  Ret: {_p('total_return_pct')}%  "
          f"Sharpe: {_p('sharpe_ratio')}  MDD: {_p('max_drawdown_pct')}%  "
          f"Trades: {_p('total_trades')}  Fees: {_p('total_fees_paid')}")

    # ── 5. C3-RWC-U ──
    print("[6/8] Running C3-RWC-U backtest...")
    c3_result = run_portfolio_backtest(stock_data, c3_signals, "C3-RWC-U")
    _p3 = lambda k: c3_result.get(k, "N/A")
    print(f"    Final: {_p3('final_equity')}  Ret: {_p3('total_return_pct')}%  "
          f"Sharpe: {_p3('sharpe_ratio')}  MDD: {_p3('max_drawdown_pct')}%")

    # ── 6. 极端行情 ──
    print("[7/8] Extracting extreme market windows...")
    extreme_windows = {
        "crash_2015": {
            "label": "2015股灾 (2015-06 ~ 2016-01)",
            "range": {"start": CRASH_2015[0], "end": CRASH_2015[1]},
            "C1_RWC": extract_window(c1_result.get("equity_curve", []), *CRASH_2015),
            "C3_RWC_U": extract_window(c3_result.get("equity_curve", []), *CRASH_2015),
            "benchmark": extract_window(benchmark_result.get("equity_curve", []), *CRASH_2015),
        },
        "bear_2018": {
            "label": "2018熊市 (2018-01 ~ 2018-12)",
            "range": {"start": BEAR_2018[0], "end": BEAR_2018[1]},
            "C1_RWC": extract_window(c1_result.get("equity_curve", []), *BEAR_2018),
            "C3_RWC_U": extract_window(c3_result.get("equity_curve", []), *BEAR_2018),
            "benchmark": extract_window(benchmark_result.get("equity_curve", []), *BEAR_2018),
        },
    }

    # ── 7. 对比分析 ──
    comparison = compare(c1_result, c3_result, benchmark_result)
    fee_impact = fee_analysis(c1_result)

    # ── 8. 写入输出 ──
    ct = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    el = time.time() - t0

    q4_results = {
        "task_id": "EXP-2026-003-KNOWDEEP",
        "work_package": "Q4",
        "run_timestamp": rt,
        "completed_time": ct,
        "elapsed_seconds": round(el, 2),
        "status": "READY",
        "config": {
            "backtest_period": "2015-01-01 ~ 2025-12-31",
            "tickers": TICKERS,
            "n_tickers": len(TICKERS),
            "initial_capital": INITIAL_CAPITAL,
            "fee_single_side": FEE_SINGLE,
            "fee_round_trip": FEE_SINGLE * 2,
            "risk_free_rate": RISK_FREE_RATE,
            "random_seed": SEED,
            "c1_rwc_weights": RWC_WEIGHTS,
            "c3_rwc_u_weights": RWC_U_WEIGHTS,
        },
        "c1_rwc": c1_result,
        "c3_rwc_u": c3_result,
        "benchmark_ew": benchmark_result,
        "extreme_windows": extreme_windows,
        "comparison": comparison,
        "fee_impact": fee_impact,
        "summary": {
            "c1_vs_benchmark": c1_result.get("total_return_pct", 0) > benchmark_result.get("total_return_pct", 0),
            "c1_vs_c3": c1_result.get("total_return_pct", 0) > c3_result.get("total_return_pct", 0),
            "c1_sharpe_above_1": c1_result.get("sharpe_ratio", 0) > 1.0,
            "c1_positive_return": c1_result.get("total_return_pct", 0) > 0,
        },
    }

    # JSON
    json_path = os.path.join(Q4_DIR, "q4_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(q4_results, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"\n[OK] JSON saved: {json_path}")

    # 验证
    with open(json_path, "r", encoding="utf-8") as f:
        v = json.load(f)
    assert v["status"] == "READY", "JSON status must be READY"
    print("  [Verify] status=READY")

    # 报告
    report_path = os.path.join(Q4_DIR, "q4_portfolio_report.md")
    generate_report(q4_results, report_path)

    with open(report_path, "r", encoding="utf-8") as f:
        assert f.read().startswith("#"), "Report must start with #"

    print(f"\n{'=' * 60}")
    print(f"Q4 COMPLETE | {el:.1f}s | {ct}")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {report_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
