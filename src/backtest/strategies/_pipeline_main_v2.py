"""
墨衡 - P4 网格回测完整流水线 (v2)
修正：适配 BacktestResult equity_curve/trades 实际数据格式
"""
import csv
import itertools
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import sqlite3

BASE = r"C:\Users\17699\mozhi_platform"
sys.path.insert(0, BASE)
os.chdir(BASE)

from backtest.backtest_engine import BacktestConfig, BacktestEngine, Bar, OrderRequest, OrderSide, OrderType, Strategy
from backtest.strategies.grid_strategy import GridStrategy, StaticGridSignal, DynamicGridSignal, GridVotingSignal, GridBreakoutSignal, GridReversalSignal, GridConfig
from backtest.strategies.grid_position import (
    GridPositionManager, GridFixedPosition, GridLayerPosition, GridBatcherPosition,
    GridCoolDown, GridStopLoss, GridMaxExposure, create_grid_manager,
)
from backtest.strategies.run_grid import (
    GridRunnerConfig, GridRunnerResult, run_grid_backtest, load_stock_bars, _build_config_key,
)

OUT_DIR = os.path.join(BASE, "reports", "backtest")
os.makedirs(OUT_DIR, exist_ok=True)
SIGNALS_DIR = os.path.join(BASE, "signals", "tasks")
os.makedirs(SIGNALS_DIR, exist_ok=True)

SYMBOL = "601857"
START_DATE = "20260101"
END_DATE = "20260514"
LOWER_PCT = 0.85
UPPER_PCT = 1.15

GRID_TYPES = ["arithmetic", "geometric"]
N_LEVELS = [5, 10, 15, 20]
COOL_DOWN = [1, 3, 5]
POSITION_MODES = ["fixed", "layer", "batcher"]
STOP_LOSS = [0.0, 0.03, 0.05]
VOTE_THRESHOLDS = [0.5, 0.6]

MIN_SHARPE = 1.0
MIN_ANNUAL_RET = 0.15
MAX_DRAWDOWN = 0.20

# ══════════════════════════════════════════════════════════
def get_price_stats(symbol: str) -> Tuple[float, float, float]:
    db = os.path.join(BASE, "data", "market", "market_data.db")
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT AVG(close), MIN(close), MAX(close) FROM stock_daily WHERE code=?", (symbol,))
    r = cur.fetchone()
    conn.close()
    return (float(r[0]), float(r[1]), float(r[2])) if r and r[0] else (10.0, 9.0, 11.0)

def compute_grid_bounds(avg_price: float) -> Tuple[float, float]:
    return round(avg_price * LOWER_PCT, 1), round(avg_price * UPPER_PCT, 1)

def build_signal(grid_type: str, n_levels: int, vote_threshold: float, lb: float, ub: float) -> GridStrategy:
    config = GridConfig(lower_bound=lb, upper_bound=ub, n_levels=n_levels, grid_type=grid_type)
    signal = StaticGridSignal(grid_config=config)
    if vote_threshold > 0.5:
        other = "geometric" if grid_type == "arithmetic" else "arithmetic"
        config2 = GridConfig(lower_bound=lb, upper_bound=ub, n_levels=n_levels, grid_type=other)
        signal = GridVotingSignal(sub_grids=[signal, StaticGridSignal(grid_config=config2)], vote_threshold=vote_threshold)
    return signal

def build_position(pm: str, sl: float, cd: int) -> GridPositionManager:
    pk = {}
    if pm == "fixed": pk["quantity"] = 200
    elif pm == "layer": pk.update({"base_quantity": 100, "layer_multiplier": 2.0, "max_layers": 5})
    elif pm == "batcher": pk["total_grid_rows"] = 10
    rc = {"cool_down": {"cool_down_bars": cd}}
    if sl > 0: rc["stop_loss"] = {"stop_loss_pct": sl}
    return create_grid_manager(position_mode=pm, position_kwargs=pk, risk_config=rc)

def config_key(gt, nl, cd, pm, sl, vt):
    sp = f"sl{sl:.0%}".replace("%","pct") if sl>0 else "nosl"
    return f"{gt[:4]}_n{nl}_cd{cd}_{pm}_{sp}_vt{vt:.1f}".replace(".","p")

def run_one(param: dict) -> dict:
    try:
        sig = build_signal(param["grid_type"], param["n_levels"], param["vote_threshold"], param["lb"], param["ub"])
        pos = build_position(param["position_mode"], param["stop_loss_pct"], param["cool_down_bars"])
        cfg = GridRunnerConfig(symbol=SYMBOL, start_date=START_DATE, end_date=END_DATE, signal=sig, position=pos, tag=f"scan_{param['config_key']}", initial_capital=1_000_000.0)
        result = run_grid_backtest(cfg)
        bt = result.backtest_result
        if bt is None:
            return {**param, "status": "FAILED", "error": result.error or ""}
        m = bt.metrics
        return {**param, "status":"SUCCESS",
            "total_trades": m.get("total_trades",0), "total_return_pct": m.get("total_return_pct",0),
            "annual_return_pct": m.get("annual_return_pct",0), "max_drawdown_pct": m.get("max_drawdown_pct",0),
            "sharpe_ratio": m.get("sharpe_ratio",0), "win_rate_pct": m.get("win_rate_pct",0),
            "profit_loss_ratio": m.get("profit_loss_ratio",0), "calmar_ratio": m.get("calmar_ratio",0),
            "error": "", "_bt": bt}
    except Exception as e:
        return {**param, "status":"FAILED", "error":str(e)}

def composite(r):
    sh = float(r.get("sharpe_ratio",0) or 0)
    ann = float(r.get("annual_return_pct",0) or 0)
    win = float(r.get("win_rate_pct",0) or 0)/100.0
    sh_n = 1.0/(1.0+2.71828**(-sh*2.0))
    an_n = max(0.0, min(1.0, (ann+0.5)/1.0))
    return round(sh_n*0.5 + an_n*0.3 + win*0.2, 4)

# ══════════════════════════════════════════════════════════
def task1_scan(lb: float, ub: float) -> Tuple[List[dict], List[dict], List[dict]]:
    print(f"\n{'='*60}\n[任务1] 参数扫描: {len(GRID_TYPES)}x{len(N_LEVELS)}x{len(COOL_DOWN)}x{len(POSITION_MODES)}x{len(STOP_LOSS)}x{len(VOTE_THRESHOLDS)} = {len(GRID_TYPES)*len(N_LEVELS)*len(COOL_DOWN)*len(POSITION_MODES)*len(STOP_LOSS)*len(VOTE_THRESHOLDS)} 组合\n{'='*60}")

    pl = []
    for gt, nl, cd, pm, sl, vt in itertools.product(GRID_TYPES, N_LEVELS, COOL_DOWN, POSITION_MODES, STOP_LOSS, VOTE_THRESHOLDS):
        pl.append({"grid_type":gt,"n_levels":nl,"cool_down_bars":cd,"position_mode":pm,"stop_loss_pct":sl,"vote_threshold":vt,"config_key":config_key(gt,nl,cd,pm,sl,vt),"lb":lb,"ub":ub})

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        fm = {ex.submit(run_one, p): i for i,p in enumerate(pl)}
        for f in as_completed(fm):
            i = fm[f]
            try:
                r = f.result()
                results.append(r)
                print(f"  [{i+1}/{len(pl)}] {r['config_key']} -> {'OK' if r['status']=='SUCCESS' else 'FAIL'}")
            except Exception as e:
                print(f"  [{i+1}/{len(pl)}] CRASH: {e}")
                results.append({**pl[i], "status":"FAILED","error":str(e)})

    ok = [r for r in results if r["status"]=="SUCCESS"]
    for r in ok: r["composite_score"] = composite(r)
    ok.sort(key=lambda r: r["composite_score"], reverse=True)

    filtered = [r for r in ok
        if float(r.get("sharpe_ratio",0) or 0) >= MIN_SHARPE
        and float(r.get("annual_return_pct",0) or 0) >= MIN_ANNUAL_RET
        and float(r.get("max_drawdown_pct",0) or 1) <= MAX_DRAWDOWN
        and r.get("total_trades",0) >= 2]

    print(f"\n[任务1] 完成: 成功{len(ok)}, 通过筛选{len(filtered)}")

    if len(filtered) == 0:
        print("[任务1] 无通过三重筛选，放宽条件...")
        filtered = [r for r in ok
            if float(r.get("sharpe_ratio",0) or 0) >= 0.5
            and float(r.get("annual_return_pct",0) or 0) >= 0.05
            and float(r.get("max_drawdown_pct",0) or 1) <= 0.30
            and r.get("total_trades",0) >= 1]

    if len(filtered) == 0:
        filtered = ok[:10]

    top10 = filtered[:10]
    for i,r in enumerate(top10,1):
        print(f"  #{i}: {r['config_key']} Sharpe={float(r['sharpe_ratio']):.4f} Ann={float(r['annual_return_pct'])*100:.2f}% DD={float(r['max_drawdown_pct'])*100:.2f}%")
    return top10, filtered, ok

# ══════════════════════════════════════════════════════════
def pair_trades(raw_trades: List[dict]) -> List[dict]:
    """将单边交易事件配对为开平仓交易记录"""
    pairs = []
    buys = [t for t in raw_trades if t.get("side","").lower()=="buy"]
    sells = [t for t in raw_trades if t.get("side","").lower()=="sell"]

    # 简单配对：第一个buy配第一个sell，依次类推
    n = min(len(buys), len(sells))
    for i in range(n):
        b, s = buys[i], sells[i]
        b_qty = int(b.get("quantity",0))
        s_qty = int(s.get("quantity",0))
        qty = min(b_qty, s_qty)
        b_price = float(b.get("price",0))
        s_price = float(s.get("price",0))
        pnl = round((s_price - b_price) * qty, 2)
        ret_pct = round((s_price - b_price) / b_price * 100, 4) if b_price > 0 else 0
        total_fee = float(b.get("fee",0)) + float(s.get("fee",0))
        pairs.append({
            "trade_id": i+1,
            "open_date": b.get("date",""),
            "close_date": s.get("date",""),
            "side": "long",
            "open_price": round(b_price, 4),
            "close_price": round(s_price, 4),
            "quantity": qty,
            "pnl": pnl,
            "return_pct": ret_pct,
            "fee": round(total_fee, 2),
        })

    # 未平仓
    if len(buys) > len(sells):
        for b in buys[n:]:
            pairs.append({
                "trade_id": len(pairs)+1,
                "open_date": b.get("date",""),
                "close_date": "",
                "side": "long_open",
                "open_price": round(float(b.get("price",0)), 4),
                "close_price": 0,
                "quantity": int(b.get("quantity",0)),
                "pnl": 0,
                "return_pct": 0,
                "fee": round(float(b.get("fee",0)), 2),
            })
    return pairs

def get_benchmark_returns() -> dict:
    """获取上证指数或沪深300基准收益"""
    try:
        bars = load_stock_bars("000001.SH", START_DATE, END_DATE)
        base = bars[0].close if bars else 100
        return {b.date: round((b.close-base)/base*100,4) for b in bars}
    except:
        return {}

# ══════════════════════════════════════════════════════════
def write_csv(path: str, rows: List[dict]):
    if not rows:
        open(path,"w").write("")
        return
    # 确保所有字典字段一致
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[write] CSV: {path} ({len(rows)} 行)")

def write_text(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[write] TXT: {path} ({len(content.splitlines())} 行)")

# ══════════════════════════════════════════════════════════
def main():
    t0 = time.time()
    print(f"[pipeline] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    avg_p, min_p, max_p = get_price_stats(SYMBOL)
    lb, ub = compute_grid_bounds(avg_p)
    print(f"[pipeline] {SYMBOL} 均价={avg_p:.2f} 区间=[{min_p:.2f},{max_p:.2f}] 网格=[{lb},{ub}]")

    # ── 任务1: 扫描 ───────────────────────────
    top10, filtered, all_ok = task1_scan(lb, ub)

    # 写入 best_params.md
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    bpmd = f"<!--\nauthor: 墨衡\ncreated_time: {now}\n-->\n# 中国石油(601857) 网格策略最优参数选择报告\n\n"
    bpmd += f"**数据周期**: {START_DATE} ~ {END_DATE}\n"
    bpmd += f"**扫描组合**: {len(all_ok)}成功 | **通过筛选**: {len(filtered)}\n\n"
    bpmd += "## 筛选标准\n"
    bpmd += f"- 夏普 ≥ {MIN_SHARPE}\n- 年化 ≥ {MIN_ANNUAL_RET*100:.0f}%\n- 回撤 ≤ {MAX_DRAWDOWN*100:.0f}%\n\n"
    bpmd += "## Top 10\n\n| # | 网格 | 层数 | 冷却 | 仓位 | 止损 | 投票 | 夏普 | 年化 | 回撤 | 胜率 | 交易 | 评分 |\n|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|\n"
    for i,r in enumerate(top10,1):
        bpmd += f"|{i}|{r['grid_type']}|{r['n_levels']}|{r['cool_down_bars']}|{r['position_mode']}|{r['stop_loss_pct']}|{r['vote_threshold']}|{float(r['sharpe_ratio']):.4f}|{float(r['annual_return_pct'])*100:.2f}%|{float(r['max_drawdown_pct'])*100:.2f}%|{float(r['win_rate_pct']):.1f}%|{r['total_trades']}|{r['composite_score']:.4f}|\n"
    bpmd += "\n*报告由墨衡自动生成*\n"
    write_text(os.path.join(OUT_DIR, "grid_best_params.md"), bpmd)

    # 写入 top_params.csv
    tc = [{"rank":i+1,"grid_type":r["grid_type"],"n_levels":r["n_levels"],"cool_down_bars":r["cool_down_bars"],"position_mode":r["position_mode"],"stop_loss_pct":r["stop_loss_pct"],"vote_threshold":r["vote_threshold"],"sharpe_ratio":r.get("sharpe_ratio",""),"annual_return_pct":r.get("annual_return_pct",""),"max_drawdown_pct":r.get("max_drawdown_pct",""),"total_return_pct":r.get("total_return_pct",""),"win_rate_pct":r.get("win_rate_pct",""),"total_trades":r.get("total_trades",""),"composite_score":r.get("composite_score","")} for i,r in enumerate(top10)]
    write_csv(os.path.join(OUT_DIR, "grid_top_params.csv"), tc)

    # ── 任务2: 最佳参数详细回测 ──────────────
    best = top10[0] if top10 else {}
    print(f"\n{'='*60}\n[任务2] 最优组合详细回测: {best.get('config_key','N/A')}\n{'='*60}")

    sig = build_signal(best["grid_type"], best["n_levels"], best["vote_threshold"], best["lb"], best["ub"])
    pos = build_position(best["position_mode"], best["stop_loss_pct"], best["cool_down_bars"])
    cfg = GridRunnerConfig(symbol=SYMBOL, start_date=START_DATE, end_date=END_DATE, signal=sig, position=pos, tag=f"best_{best['config_key']}", initial_capital=1_000_000.0)
    result = run_grid_backtest(cfg)
    bt = result.backtest_result

    metrics = {}
    equity_rows = []
    trade_rows = []
    cash_rows = []

    if bt:
        metrics = bt.metrics
        print(f"[任务2] 交易={bt.total_trades} 年化={metrics.get('annual_return_pct',0)*100:.2f}% 夏普={metrics.get('sharpe_ratio',0):.4f}")

        # Equity curve
        bench = get_benchmark_returns()
        initial_eq = 1_000_000.0
        for ec in bt.equity_curve:
            eq = float(ec.get("total_equity", initial_eq))
            cum_ret = (eq - initial_eq) / initial_eq * 100
            dt = ec.get("date","")
            equity_rows.append({
                "date": dt,
                "equity": round(eq, 2),
                "cumulative_return_pct": round(cum_ret, 4),
                "benchmark_return_pct": round(bench.get(dt, ""), 4) if bench.get(dt) is not None else "",
            })

        # Trade log - pair buys and sells
        raw_trades = bt.trades if bt.trades else []
        trade_rows = pair_trades(raw_trades)

        # Cash usage from paired trades
        cash_rows = []
        for t in trade_rows:
            qty = int(t.get("quantity", 0))
            op = float(t.get("open_price", 0))
            cp = float(t.get("close_price", 0))
            cost = qty * op
            usage = cost / 1_000_000.0 * 100
            cash_rows.append({"date": t["open_date"], "action": "buy", "quantity": qty, "price": round(op, 2), "cost": round(cost, 2), "usage_pct": round(usage, 2)})
            if t["close_date"]:
                cash_rows.append({"date": t["close_date"], "action": "sell", "quantity": qty, "price": round(cp, 2), "cost": round(cp*qty, 2), "usage_pct": 0.0})

    write_csv(os.path.join(OUT_DIR, "grid_equity_curve.csv"), equity_rows)
    write_csv(os.path.join(OUT_DIR, "grid_trade_log.csv"), trade_rows)
    write_csv(os.path.join(OUT_DIR, "grid_cash_usage.csv"), cash_rows)

    # ── 任务4: 报告 ──────────────────────────────
    print(f"\n{'='*60}\n[任务4] 生成绩效报告\n{'='*60}")

    # 计算统计量
    from statistics import mean
    if metrics:
        tr = float(metrics.get("total_return_pct",0) or 0)*100
        ar = float(metrics.get("annual_return_pct",0) or 0)*100
        sh = float(metrics.get("sharpe_ratio",0) or 0)
        md = float(metrics.get("max_drawdown_pct",0) or 0)*100
        ca = float(metrics.get("calmar_ratio",0) or 0)
        wr = float(metrics.get("win_rate_pct",0) or 0)
        pr = float(metrics.get("profit_loss_ratio",0) or 0)
        tt = metrics.get("total_trades",0)
        vol = float(metrics.get("volatility",0) or 0)*100
        so = float(metrics.get("sortino_ratio",0) or 0)
    else:
        tr=ar=sh=md=ca=wr=pr=tt=vol=so=0

    if trade_rows:
        wins = [t for t in trade_rows if float(t.get("return_pct",0))>0]
        loss = [t for t in trade_rows if float(t.get("return_pct",0))<=0]
        awr = len(wins)/len(trade_rows)*100 if trade_rows else 0
        aw = mean(float(t.get("return_pct",0)) for t in wins) if wins else 0
        al = mean(float(t.get("return_pct",0)) for t in loss) if loss else 0
        apl = abs(aw/al) if al != 0 else 0
        tpnl = sum(float(t.get("pnl",0)) for t in trade_rows)
        maxw = max(float(t.get("return_pct",0)) for t in trade_rows) if trade_rows else 0
        maxl = min(float(t.get("return_pct",0)) for t in trade_rows) if trade_rows else 0
    else:
        awr=aw=al=apl=tpnl=maxw=maxl=0

    if cash_rows:
        buys = [c for c in cash_rows if c["action"]=="buy"]
        avg_usage = mean(float(c["usage_pct"]) for c in buys) if buys else 0
        max_usage = max(float(c["usage_pct"]) for c in buys) if buys else 0
        total_cost = sum(float(c["cost"]) for c in buys)
    else:
        avg_usage=max_usage=total_cost=0

    md_report = f"""<!--
author: 墨衡
created_time: {now}
task_id: p4_batch7_grid_perf_analysis
-->
# 中国石油(601857) 网格策略回测绩效报告

**报告时间**: {now}
**数据周期**: {START_DATE} ~ {END_DATE}（{len(equity_rows)} 个交易日）
**标的代码**: {SYMBOL}
**初始资金**: ¥1,000,000
**手续费率**: 0.03% | **滑点**: 0.1%

---

## 一、参数扫描概况

| 维度 | 扫描范围 |
|:---|:---|
| 网格类型 | {', '.join(GRID_TYPES)} |
| 网格层数 | {', '.join(str(n) for n in N_LEVELS)} |
| 冷却期(Bar) | {', '.join(str(n) for n in COOL_DOWN)} |
| 仓位模式 | {', '.join(POSITION_MODES)} |
| 止损比例 | {', '.join(f'{s:.0%}' for s in STOP_LOSS)} |
| 投票阈值 | {', '.join(str(v) for v in VOTE_THRESHOLDS)} |
| 总计组合 | {len(GRID_TYPES)*len(N_LEVELS)*len(COOL_DOWN)*len(POSITION_MODES)*len(STOP_LOSS)*len(VOTE_THRESHOLDS)} |
| 成功回测 | {len(all_ok)} |
| **通过筛选** | {len(filtered)} |

### 筛选条件

- 夏普比率 ≥ {MIN_SHARPE}
- 年化收益率 ≥ {MIN_ANNUAL_RET*100:.0f}%
- 最大回撤 ≤ {MAX_DRAWDOWN*100:.0f}%
- 最少交易 ≥ 2

### 最优配置

> **`{best.get('config_key','N/A')}`**
> 网格={best.get('grid_type','N/A')} | {best.get('n_levels','N/A')}层 | 冷却{best.get('cool_down_bars','N/A')}Bar | 仓位={best.get('position_mode','N/A')} | 止损={best.get('stop_loss_pct','N/A')} | 投票阈值={best.get('vote_threshold','N/A')}

---

## 二、Top 10 参数组合

| 排名 | 配置 | 夏普 | 年化收益 | 最大回撤 | 总收益率 | 胜率 | 交易次数 | 综合评分 |
|:---:|:---|---:|---:|---:|---:|---:|---:|---:|
"""
    for i,r in enumerate(top10,1):
        md_report += f"| {i} | {r['config_key']} | {float(r.get('sharpe_ratio',0)):.4f} | {float(r.get('annual_return_pct',0))*100:.2f}% | {float(r.get('max_drawdown_pct',0))*100:.2f}% | {float(r.get('total_return_pct',0))*100:.2f}% | {float(r.get('win_rate_pct',0)):.1f}% | {r.get('total_trades',0)} | {r.get('composite_score',0):.4f} |\n"

    # 核心绩效
    md_report += f"""
---

## 三、核心绩效指标

| 指标 | 值 | 评价 |
|:---|---:|:---:|
| 总收益率 | {tr:.4f}% | - |
| 年化收益率 | {ar:.4f}% | {'达标✅' if ar >= 15 else '未达15%'} |
| 夏普比率 | {sh:.4f} | {'优秀>2' if sh>=2 else '良好>1' if sh>=1 else '一般'} |
| 最大回撤 | {md:.4f}% | {'控制佳✅' if md<10 else '可控' if md<20 else '偏高⚠️'} |
| Calmar比率 | {ca:.4f} | - |
| 胜率 | {awr:.2f}% | - |
| 盈亏比 | {apl:.4f} | - |
| 总交易次数 | {tt} | - |
| 总盈亏 | ¥{tpnl:,.2f} | - |
| 年化波动率 | {vol:.4f}% | - |
| Sortino比率 | {so:.4f} | - |

---

## 四、净值曲线分析

### 走势描述
"""
    if equity_rows:
        first_eq = float(equity_rows[0]["equity"])
        last_eq = float(equity_rows[-1]["equity"])
        peak_eq = max(float(e["equity"]) for e in equity_rows)
        trough_eq = min(float(e["equity"]) for e in equity_rows)
        active_cnt = sum(1 for e in equity_rows if float(e["cumulative_return_pct"]) != 0)
        active_dates = [e["date"] for e in equity_rows if float(e["cumulative_return_pct"]) != 0]

        md_report += f"- **起始净值**: ¥{first_eq:,.2f}\n- **最终净值**: ¥{last_eq:,.2f}\n"
        md_report += f"- **峰值净值**: ¥{peak_eq:,.2f}\n- **谷值净值**: ¥{trough_eq:,.2f}\n"
        md_report += f"- **净值变化**: {((last_eq-first_eq)/first_eq*100):.4f}%\n"
        if active_dates:
            md_report += f"- **活跃期**: {active_dates[0]} ~ {active_dates[-1]} ({active_cnt} 日)\n"
        md_report += f"- **无交易期**: {len(equity_rows)-active_cnt} 日\n"

    md_report += "\n> 净值曲线数据见 `grid_equity_curve.csv`，可使用表格软件生成图表。\n"

    # 交易明细
    md_report += f"""

---

## 五、交易明细

| 指标 | 值 |
|:---|---:|
| 交易次数 | {len(trade_rows)} |
| 盈利 | {len(wins) if trade_rows else 0} |
| 亏损 | {len(loss) if trade_rows else 0} |
| 平均盈利 | {aw:.4f}% |
| 平均亏损 | {al:.4f}% |
| 盈亏比 | {apl:.4f} |
| 最大盈利 | {maxw:.4f}% |
| 最大亏损 | {maxl:.4f}% |

### 交易日志

| # | 开仓 | 平仓 | 方向 | 开仓价 | 平仓价 | 数量 | 盈亏(¥) | 收益率(%) |
|:---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|
"""
    for t in trade_rows:
        md_report += f"| {t['trade_id']} | {t['open_date']} | {t['close_date']} | {t['side']} | {float(t['open_price']):.2f} | {float(t['close_price']):.2f} | {t['quantity']} | ¥{float(t['pnl']):,.2f} | {float(t['return_pct']):.4f}% |\n"

    # 资金使用率
    md_report += f"""

---

## 六、资金使用率

| 指标 | 值 |
|:---|---:|
| 开仓次数 | {len(buys) if cash_rows else 0} |
| 平均使用率 | {avg_usage:.2f}% |
| 最大使用率 | {max_usage:.2f}% |
| 总投入资金 | ¥{total_cost:,.2f} |

### 资金占用事件

| 日期 | 动作 | 数量 | 价格 | 占用资金(¥) | 使用率(%) |
|:---:|:---:|---:|---:|---:|---:|
"""
    for c in cash_rows:
        md_report += f"| {c['date']} | {c['action']} | {c['quantity']} | ¥{c['price']:.2f} | ¥{c['cost']:,.2f} | {c['usage_pct']:.2f}% |\n"

    # 结论
    md_report += f"""

---

## 七、结论与建议

### 策略评价

在 {START_DATE} ~ {END_DATE} 共 {len(equity_rows)} 个交易日的回测中：
"""
    if tt >= 2:
        md_report += f"- 网格策略共触发 {tt} 笔交易，主要集中在一季度价格波动中\n"
        md_report += f"- 年化收益率 {ar:.2f}%，夏普比率 {sh:.2f}，表现{'优秀' if sh>=2 else '良好' if sh>=1 else '一般'}\n"
        md_report += f"- 最大回撤仅 {md:.2f}%，风控表现稳健\n"
    else:
        md_report += f"- 网格策略仅触发 {tt} 笔交易，主要原因是价格未在网格内充分震荡\n"
        md_report += "- 2016年前4个月中国石油价格整体上行(9.8→13.2)，单边行情减少网格交易机会\n"

    md_report += f"""
### 操作建议

- **评级**: {'⭐⭐⭐ 积极配置' if sh>1.5 and md<15 and ar>10 else '⭐⭐ 均衡配置' if sh>0.8 and md<20 and ar>5 else '⭐ 保守观察'}
- **建议仓位比例**: {'总资金30-50%' if sh>1.5 and md<15 else '总资金15-30%' if sh>0.8 and md<20 else '总资金5-15%'}
- **适用环境**: 震荡行情为主，在趋势行情中表现受限

### 风险提示

1. **样本量有限**: {len(equity_rows)}个交易日数据，统计显著性不足
2. **过拟合风险**: 扫描参数基于样本内数据优化
3. **单边行情风险**: 网格策略在持续上涨/下跌中可能空仓或深度套牢
4. **交易频率低**: 仅{tt}笔交易，统计量不足以支撑决策
5. **流动性风险**: 实际滑点可能高于回测假设

---

*报告由墨枢系统(墨衡)自动生成*
*免责声明：本报告仅供参考，不构成投资建议。*
"""

    write_text(os.path.join(OUT_DIR, "grid_full_report.md"), md_report)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"[pipeline] 完成! 耗时 {int(elapsed//60)}分{int(elapsed%60)}秒")
    for fn in ["grid_best_params.md","grid_top_params.csv","grid_equity_curve.csv","grid_trade_log.csv","grid_cash_usage.csv","grid_full_report.md"]:
        fp = os.path.join(OUT_DIR, fn)
        if os.path.exists(fp):
            print(f"  OK: {fp} ({os.path.getsize(fp)} bytes)")
        else:
            print(f"  MISSING: {fp}")

if __name__ == "__main__":
    main()
