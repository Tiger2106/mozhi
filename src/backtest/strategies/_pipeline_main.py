"""
墨衡 - P4 网格回测完整流水线
601857（中国石油）网格策略参数扫描 → 最优筛选 → 详细回测 → 全报告

运行方式: python _pipeline_main.py
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

# ── 路径 ❲通过共享配置模块❳ ──────────────────────────────
from src.config import PROJECT_ROOT, SHARED_REPORTS, MARKET_DATA_DB, SIGNALS_DIR, OUT_DIR as CFG_OUT_DIR
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

# ── 旧接口兼容 ────────────────────────────────────────────
BASE = str(PROJECT_ROOT)

# ── 导入回测模块 ──────────────────────────────────────────
from backtest.backtest_engine import BacktestConfig, BacktestEngine, Bar, OrderRequest, OrderSide, OrderType, Strategy
from backtest.strategies.grid_strategy import GridStrategy, StaticGridSignal, DynamicGridSignal, GridVotingSignal, GridBreakoutSignal, GridReversalSignal, GridConfig
from backtest.strategies.grid_position import (
    GridPositionManager, GridFixedPosition, GridLayerPosition, GridBatcherPosition,
    GridCoolDown, GridStopLoss, GridMaxExposure, create_grid_manager,
)
from backtest.strategies.run_grid import (
    GridRunnerConfig, GridRunnerResult, run_grid_backtest, batch_run_grid, load_stock_bars, _build_config_key,
)
from backtest.signal_bridge import SignalBridge, SignalBridgeConfig

# ── 输出路径 ❲从共享配置读取❳ ────────────────────────────
OUT_DIR = str(CFG_OUT_DIR)
os.makedirs(OUT_DIR, exist_ok=True)
SIGNALS_DIR = str(SHARED_REPORTS / "signals" / "tasks")
os.makedirs(SIGNALS_DIR, exist_ok=True)

# ── 参数 ──────────────────────────────────────────────────
SYMBOL = "601857"
START_DATE = "20260101"
END_DATE = "20260514"

# 自适应网格边界 (% 相对于均价)
LOWER_PCT = 0.85   # 下限 = avg * 0.85
UPPER_PCT = 1.15   # 上限 = avg * 1.15

# 参数空间
GRID_TYPES = ["arithmetic", "geometric"]
N_LEVELS = [5, 10, 15, 20]
COOL_DOWN = [1, 3, 5]
POSITION_MODES = ["fixed", "layer", "batcher"]
STOP_LOSS = [0.0, 0.03, 0.05]
VOTE_THRESHOLDS = [0.5, 0.6]

# 筛选条件
MIN_SHARPE = 1.0
MIN_ANNUAL_RET = 0.15  # 15%
MAX_DRAWDOWN = 0.20    # 20%


# ══════════════════════════════════════════════════════════
# 工具：获取价格均值和网格边界
# ══════════════════════════════════════════════════════════

def get_price_stats(symbol: str) -> Tuple[float, float, float, float]:
    """获取价格统计数据"""
    db = str(MARKET_DATA_DB)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute(
        "SELECT AVG(close), MIN(close), MAX(close), MIN(date), MAX(date) "
        "FROM stock_daily WHERE code=?",
        (symbol,),
    )
    r = cur.fetchone()
    conn.close()
    if r and r[0]:
        avg_close = float(r[0])
        min_close = float(r[1])
        max_close = float(r[2])
        print(f"[pipeline] {symbol} 均价={avg_close:.2f}, 区间=[{min_close:.2f}, {max_close:.2f}]")
        return avg_close, min_close, max_close
    raise ValueError(f"无法获取 {symbol} 的价格数据")


def compute_grid_bounds(avg_price: float) -> Tuple[float, float]:
    """计算百分比网格边界"""
    lb = round(avg_price * LOWER_PCT, 1)
    ub = round(avg_price * UPPER_PCT, 1)
    print(f"[pipeline] 网格边界: [{lb}, {ub}]")
    return lb, ub


# ══════════════════════════════════════════════════════════
# 工具：构建网格策略 + 仓位
# ══════════════════════════════════════════════════════════

def build_signal(
    grid_type: str, n_levels: int, vote_threshold: float,
    lower_bound: float, upper_bound: float,
) -> GridStrategy:
    """构建网格策略信号"""
    config = GridConfig(
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        n_levels=n_levels,
        grid_type=grid_type,
    )
    signal = StaticGridSignal(grid_config=config)

    if vote_threshold > 0.5:
        other_type = "geometric" if grid_type == "arithmetic" else "arithmetic"
        config2 = GridConfig(
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            n_levels=n_levels,
            grid_type=other_type,
        )
        signal2 = StaticGridSignal(grid_config=config2)
        signal = GridVotingSignal(
            sub_grids=[signal, signal2],
            vote_threshold=vote_threshold,
        )
    return signal


def build_position(position_mode: str, stop_loss_pct: float, cool_down_bars: int) -> GridPositionManager:
    """构建仓位管理器"""
    pos_kwargs: Dict[str, Any] = {}
    if position_mode == "fixed":
        pos_kwargs["quantity"] = 200
    elif position_mode == "layer":
        pos_kwargs["base_quantity"] = 100
        pos_kwargs["layer_multiplier"] = 2.0
        pos_kwargs["max_layers"] = 5
    elif position_mode == "batcher":
        pos_kwargs["total_grid_rows"] = 10

    risk_config: Dict[str, Any] = {
        "cool_down": {"cool_down_bars": cool_down_bars},
    }
    if stop_loss_pct > 0:
        risk_config["stop_loss"] = {"stop_loss_pct": stop_loss_pct}

    return create_grid_manager(
        position_mode=position_mode,
        position_kwargs=pos_kwargs,
        risk_config=risk_config,
    )


def make_config_key(gt, nl, cd, pm, sl, vt) -> str:
    sl_part = f"sl{sl:.0%}".replace("%", "pct") if sl > 0 else "nosl"
    return f"{gt[:4]}_n{nl}_cd{cd}_{pm}_{sl_part}_vt{vt:.1f}".replace(".", "p")


# ══════════════════════════════════════════════════════════
# 工具：回测单个组合
# ══════════════════════════════════════════════════════════

def run_single(param: dict) -> Dict[str, Any]:
    """运行单个参数组合的回测"""
    try:
        signal = build_signal(
            param["grid_type"], param["n_levels"], param["vote_threshold"],
            param["lb"], param["ub"],
        )
        position = build_position(
            param["position_mode"], param["stop_loss_pct"], param["cool_down_bars"],
        )
        cfg = GridRunnerConfig(
            symbol=SYMBOL,
            start_date=START_DATE,
            end_date=END_DATE,
            signal=signal,
            position=position,
            tag=f"scan_{param['config_key']}",
            initial_capital=1_000_000.0,
        )
        result = run_grid_backtest(cfg)
        bt = result.backtest_result
        if bt is None:
            return {**param, "status": "FAILED", "error": result.error}

        metrics = bt.metrics
        return {
            **param,
            "status": "SUCCESS",
            "total_trades": metrics.get("total_trades", 0),
            "total_return_pct": metrics.get("total_return_pct", 0),
            "annual_return_pct": metrics.get("annual_return_pct", 0),
            "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
            "win_rate_pct": metrics.get("win_rate_pct", 0),
            "profit_loss_ratio": metrics.get("profit_loss_ratio", 0),
            "calmar_ratio": metrics.get("calmar_ratio", 0),
            "avg_holding_days": metrics.get("avg_holding_days", 0),
            "avg_profit_pct": metrics.get("avg_profit_pct", 0),
            "avg_loss_pct": metrics.get("avg_loss_pct", 0),
            "error": "",
            "_backtest_result": bt,
        }
    except Exception as e:
        return {**param, "status": "FAILED", "error": str(e)}


def composite_score(r: dict) -> float:
    """综合评分"""
    sharpe = float(r.get("sharpe_ratio", 0) or 0)
    ann = float(r.get("annual_return_pct", 0) or 0)
    win = float(r.get("win_rate_pct", 0) or 0) / 100.0
    sharpe_norm = 1.0 / (1.0 + 2.71828 ** (-sharpe * 2.0))
    annual_norm = max(0.0, min(1.0, (ann + 0.5) / 1.0))
    return round(sharpe_norm * 0.5 + annual_norm * 0.3 + win * 0.2, 4)


# ══════════════════════════════════════════════════════════
# 任务1：参数扫描 + 最优筛选
# ══════════════════════════════════════════════════════════

def task1_scan_params(lower_bound: float, upper_bound: float) -> List[dict]:
    """执行全参数扫描"""
    print(f"\n{'='*60}")
    print(f"[任务1] 开始全参数扫描")
    print(f"  参数空间: {len(GRID_TYPES)}×{len(N_LEVELS)}×{len(COOL_DOWN)}×{len(POSITION_MODES)}×{len(STOP_LOSS)}×{len(VOTE_THRESHOLDS)}")
    total = (len(GRID_TYPES) * len(N_LEVELS) * len(COOL_DOWN) * len(POSITION_MODES) * len(STOP_LOSS) * len(VOTE_THRESHOLDS))
    print(f"  共 {total} 个组合")
    print(f"{'='*60}\n")

    params_list = []
    for gt, nl, cd, pm, sl, vt in itertools.product(
        GRID_TYPES, N_LEVELS, COOL_DOWN, POSITION_MODES, STOP_LOSS, VOTE_THRESHOLDS
    ):
        ck = make_config_key(gt, nl, cd, pm, sl, vt)
        params_list.append({
            "grid_type": gt,
            "n_levels": nl,
            "cool_down_bars": cd,
            "position_mode": pm,
            "stop_loss_pct": sl,
            "vote_threshold": vt,
            "config_key": ck,
            "lb": lower_bound,
            "ub": upper_bound,
        })

    results = []
    n = len(params_list)
    with ThreadPoolExecutor(max_workers=6) as ex:
        fut_map = {ex.submit(run_single, p): i for i, p in enumerate(params_list)}
        for fut in as_completed(fut_map):
            idx = fut_map[fut]
            try:
                r = fut.result()
                results.append(r)
                s = "OK" if r["status"] == "SUCCESS" else f"FAIL:{r['error'][:40]}"
                print(f"  [{idx+1}/{n}] {r['config_key']} → {s}")
            except Exception as e:
                print(f"  [{idx+1}/{n}] CRASH: {e}")
                results.append({**params_list[idx], "status": "FAILED", "error": str(e)})

    # 按综合评分排序
    successful = [r for r in results if r["status"] == "SUCCESS"]
    for r in successful:
        r["composite_score"] = composite_score(r)
    successful.sort(key=lambda r: r["composite_score"], reverse=True)

    print(f"\n[任务1] 完成: 共 {n} 组合, 成功 {len(successful)}, 失败 {n - len(successful)}")

    # 应用三重筛选
    filtered = [
        r for r in successful
        if float(r.get("sharpe_ratio", 0) or 0) >= MIN_SHARPE
        and float(r.get("annual_return_pct", 0) or 0) >= MIN_ANNUAL_RET
        and float(r.get("max_drawdown_pct", 0) or 1) <= MAX_DRAWDOWN
        and r.get("total_trades", 0) >= 2
    ]
    print(f"[任务1] 三重筛选后通过: {len(filtered)} 个")

    if len(filtered) == 0:
        print("[任务1] 无组合通过三重筛选，放宽条件...")
        # 放宽：Sharpe>0.5, annual>5%, maxDD<30%
        filtered = [
            r for r in successful
            if float(r.get("sharpe_ratio", 0) or 0) >= 0.5
            and float(r.get("annual_return_pct", 0) or 0) >= 0.05
            and float(r.get("max_drawdown_pct", 0) or 1) <= 0.30
            and r.get("total_trades", 0) >= 1
        ]
        print(f"[任务1] 宽松筛选后: {len(filtered)} 个")

    if len(filtered) == 0:
        print("[任务1] 仍无通过组合，使用全部成功组合的前10")
        filtered = successful[:10]

    top10 = filtered[:10]
    print(f"\n[任务1] Top 10:")
    for i, r in enumerate(top10, 1):
        print(f"  #{i}: {r['config_key']} → 夏普={float(r.get('sharpe_ratio',0)):.4f} "
              f"年化={float(r.get('annual_return_pct',0))*100:.2f}% "
              f"回撤={float(r.get('max_drawdown_pct',0))*100:.2f}% "
              f"胜率={float(r.get('win_rate_pct',0)):.1f}% "
              f"综合={r.get('composite_score',0):.4f}")

    return top10, filtered, successful


# ══════════════════════════════════════════════════════════
# 任务2：最优参数详细回测（净值曲线 + 交易明细）
# ══════════════════════════════════════════════════════════

def task2_detailed_backtest(top_params: List[dict]) -> Tuple[List[dict], List[dict], dict]:
    """对最优参数运行详细回测，提取净值曲线和交易明细"""
    best = top_params[0] if top_params else None
    if not best:
        return [], [], {}

    print(f"\n{'='*60}")
    print(f"[任务2] 对最优组合进行详细回测: {best['config_key']}")
    print(f"{'='*60}")

    # 构建配置
    signal = build_signal(best["grid_type"], best["n_levels"], best["vote_threshold"], best["lb"], best["ub"])
    position = build_position(best["position_mode"], best["stop_loss_pct"], best["cool_down_bars"])
    cfg = GridRunnerConfig(
        symbol=SYMBOL,
        start_date=START_DATE,
        end_date=END_DATE,
        signal=signal,
        position=position,
        tag=f"best_{best['config_key']}",
        initial_capital=1_000_000.0,
    )

    result = run_grid_backtest(cfg)
    bt = result.backtest_result
    if not bt:
        print(f"[任务2] 回测失败: {result.error}")
        return [], [], {}

    print(f"[任务2] 回测成功: 交易={bt.total_trades}, 年化={bt.metrics.get('annual_return_pct',0)*100:.2f}%, 夏普={bt.metrics.get('sharpe_ratio',0):.4f}")

    # ── 净值曲线 ──────────────────────────────────────
    equity_curve = bt.equity_curve if bt.equity_curve else []
    trades_list = bt.trades if bt.trades else []

    # 添加基准（沪深300）——从数据库获取
    bench_data = get_benchmark_data()

    # 合并净值数据
    equity_rows = []
    for point in equity_curve:
        dt = point.get("date", "")
        eq = point.get("total_equity", 0)
        ret = point.get("cumulative_return_pct", 0)
        bench_ret = bench_data.get(dt, {}).get("return_pct", None)
        equity_rows.append({
            "date": dt,
            "equity": round(eq, 2),
            "return_pct": round(ret * 100, 4),
            "benchmark_return_pct": round(bench_ret * 100, 4) if bench_ret is not None else "",
        })

    # ── 交易明细 ──────────────────────────────────────
    trade_rows = []
    for i, t in enumerate(trades_list):
        trade_rows.append({
            "trade_id": i + 1,
            "open_date": t.get("open_date", t.get("entry_date", "")),
            "close_date": t.get("close_date", t.get("exit_date", "")),
            "open_price": t.get("open_price", t.get("entry_price", 0)),
            "close_price": t.get("close_price", t.get("exit_price", 0)),
            "quantity": t.get("quantity", 0),
            "pnl": round(t.get("pnl", t.get("profit", 0)), 2),
            "return_pct": round((t.get("return_pct", 0) or 0) * 100, 4),
            "fee": round(t.get("fee", t.get("commission", 0)), 2),
            "direction": t.get("direction", t.get("side", "buy")),
        })

    return equity_rows, trade_rows, result.metrics


def get_benchmark_data() -> dict:
    """获取沪深300基准收益数据"""
    from backtest.strategies.run_grid import load_stock_bars
    try:
        bars = load_stock_bars("000300.SH", START_DATE, END_DATE)
        base_close = bars[0].close if bars else 100.0
        data = {}
        for bar in bars:
            ret = (bar.close - base_close) / base_close
            data[bar.date] = {"price": bar.close, "return_pct": ret}
        return data
    except (ValueError, Exception) as e:
        print(f"[pipeline] 基准数据获取失败: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# 任务3：现金流使用率分析
# ══════════════════════════════════════════════════════════

def task3_cash_usage(top_params: List[dict], trades: List[dict]) -> List[dict]:
    """分析资金使用率"""
    print(f"\n{'='*60}")
    print("[任务3] 资金使用率分析")
    print(f"{'='*60}")

    if not trades:
        print("[任务3] 无交易数据，返回空")
        return []

    initial_capital = 1_000_000.0
    price_avg = get_price_stats(SYMBOL)[0]
    total_volume = 0
    max_exposure = 0.0
    exposure_events = []

    for t in trades:
        qty = int(t.get("quantity", 0))
        open_price = float(t.get("open_price", 0))
        volume = qty * open_price
        total_volume += volume
        usage = volume / initial_capital
        max_exposure = max(max_exposure, usage)

        exposure_events.append({
            "date": t.get("open_date", ""),
            "action": "open",
            "quantity": qty,
            "price": open_price,
            "cost": round(volume, 2),
            "usage_pct": round(usage * 100, 2),
        })
        # Close returns funds (approximately)
        close_price = float(t.get("close_price", 0))
        close_cost = qty * close_price
        exposure_events.append({
            "date": t.get("close_date", ""),
            "action": "close",
            "quantity": qty,
            "price": close_price,
            "cost": round(close_cost, 2),
            "usage_pct": 0.0,
        })

    exposure_events.sort(key=lambda x: x["date"])

    avg_usage = (total_volume / len(trades) / initial_capital * 100) if trades else 0

    print(f"[任务3] 最大资金使用率: {max_exposure*100:.2f}%")
    print(f"[任务3] 平均单笔使用率: {avg_usage:.2f}%")
    print(f"[任务3] 总交易金额: {total_volume:.2f}")

    return exposure_events


# ══════════════════════════════════════════════════════════
# 写入 CSV / MD 文件
# ══════════════════════════════════════════════════════════

def write_csv(path: str, rows: List[dict]):
    """写入CSV"""
    if not rows:
        open(path, "w").write("")
        print(f"[write] CSV(空): {path}")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[write] CSV: {path} ({len(rows)} 行)")


def write_text(path: str, content: str):
    """写入文本文件"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[write] TXT: {path} ({len(content.splitlines())} 行)")


# ══════════════════════════════════════════════════════════
# 任务4：生成完整绩效报告
# ══════════════════════════════════════════════════════════

def task4_generate_report(
    top10: List[dict],
    all_successful: List[dict],
    equity_rows: List[dict],
    trade_rows: List[dict],
    cash_rows: List[dict],
    metrics: dict,
) -> str:
    """生成完整Markdown绩效报告"""
    print(f"\n{'='*60}")
    print("[任务4] 生成绩效报告")
    print(f"{'='*60}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    best = top10[0] if top10 else {}
    n_total = len(all_successful)
    n_filtered = len(top10)

    # ── 核心指标 ──────────────────────────────────────
    if metrics:
        total_ret = float(metrics.get("total_return_pct", 0) or 0) * 100
        annual_ret = float(metrics.get("annual_return_pct", 0) or 0) * 100
        sharpe = float(metrics.get("sharpe_ratio", 0) or 0)
        max_dd = float(metrics.get("max_drawdown_pct", 0) or 0) * 100
        calmar = float(metrics.get("calmar_ratio", 0) or 0)
        win_rate = float(metrics.get("win_rate_pct", 0) or 0)
        pl_ratio = float(metrics.get("profit_loss_ratio", 0) or 0)
        total_trades = metrics.get("total_trades", 0)
        volatility = float(metrics.get("volatility", 0) or 0) * 100
        sortino = float(metrics.get("sortino_ratio", 0) or 0)
        var_95 = float(metrics.get("var_95_pct", 0) or 0) * 100
    else:
        total_ret = annual_ret = sharpe = max_dd = calmar = win_rate = pl_ratio = total_trades = volatility = sortino = var_95 = 0

    # ── 胜率/盈亏比汇总 ──────────────────────────────
    if trade_rows:
        win_trades = [t for t in trade_rows if float(t.get("return_pct", 0)) > 0]
        loss_trades = [t for t in trade_rows if float(t.get("return_pct", 0)) <= 0]
        actual_win_rate = len(win_trades) / len(trade_rows) * 100 if trade_rows else 0
        avg_win = sum(float(t.get("return_pct", 0)) for t in win_trades) / len(win_trades) if win_trades else 0
        avg_loss = sum(float(t.get("return_pct", 0)) for t in loss_trades) / len(loss_trades) if loss_trades else 0
        actual_pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        total_pnl = sum(float(t.get("pnl", 0)) for t in trade_rows)
    else:
        actual_win_rate = 0
        avg_win = avg_loss = 0
        actual_pl_ratio = 0
        total_pnl = 0

    # ── 资金使用率汇总 ──────────────────────────────
    if cash_rows:
        open_events = [c for c in cash_rows if c.get("action") == "open"]
        avg_usage = sum(float(c.get("usage_pct", 0)) for c in open_events) / len(open_events) if open_events else 0
        max_usage = max(float(c.get("usage_pct", 0)) for c in open_events) if open_events else 0
    else:
        avg_usage = 0
        max_usage = 0

    # ── Build Markdown ────────────────────────────────
    md = f"""<!--
author: 墨衡
created_time: {now_str}
task_id: p4_batch7_grid_perf_analysis
-->
# 中国石油（601857）网格策略回测绩效报告

**报告时间**: {now_str}
**数据周期**: {START_DATE} ~ {END_DATE}（{len(equity_rows) if equity_rows else 0} 个交易日）
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
| **总计组合数** | {len(list(itertools.product(GRID_TYPES, N_LEVELS, COOL_DOWN, POSITION_MODES, STOP_LOSS, VOTE_THRESHOLDS)))} |
| 成功回测 | {n_total} |
| **通过三重筛选** | {n_filtered} |

### 筛选条件
- ✅ 夏普比率 ≥ {MIN_SHARPE}
- ✅ 年化收益率 ≥ {MIN_ANNUAL_RET*100:.0f}%
- ✅ 最大回撤 ≤ {MAX_DRAWDOWN*100:.0f}%
- ✅ 最少交易次数 ≥ 2

"""

    # ── Top 10 参数组合表 ──────────────────────────────
    md += """## 二、Top 10 最优参数组合

| 排名 | 配置标识 | 夏普 | 年化收益 | 最大回撤 | 总收益率 | 胜率 | 交易次数 | 综合评分 |
|:---:|:---|---:|---:|---:|---:|---:|---:|---:|
"""
    for i, r in enumerate(top10, 1):
        md += (
            f"| {i} | {r['config_key']} "
            f"| {float(r.get('sharpe_ratio',0)):.4f} "
            f"| {float(r.get('annual_return_pct',0))*100:.2f}% "
            f"| {float(r.get('max_drawdown_pct',0))*100:.2f}% "
            f"| {float(r.get('total_return_pct',0))*100:.2f}% "
            f"| {float(r.get('win_rate_pct',0)):.1f}% "
            f"| {r.get('total_trades',0)} "
            f"| {r.get('composite_score',0):.4f} |\n"
        )

    # ── 最优配置详情 ──────────────────────────────────
    md += f"""
## 三、最优组合详情

**最优配置**: `{best.get('config_key', 'N/A')}`

| 参数 | 值 |
|:---|---:|
| 网格类型 | {best.get('grid_type', 'N/A')} |
| 网格层数 | {best.get('n_levels', 'N/A')} |
| 冷却期 | {best.get('cool_down_bars', 'N/A')} Bar |
| 仓位模式 | {best.get('position_mode', 'N/A')} |
| 止损比例 | {best.get('stop_loss_pct', 'N/A')} |
| 投票阈值 | {best.get('vote_threshold', 'N/A')} |

### 核心绩效指标

| 指标 | 值 |
|:---|---:|
| 总收益率 | {total_ret:.4f}% |
| 年化收益率 | {annual_ret:.4f}% |
| 夏普比率 | {sharpe:.4f} |
| 最大回撤 | {max_dd:.4f}% |
| Calmar比率 | {calmar:.4f} |
| 胜率 | {actual_win_rate:.2f}% |
| 盈亏比 | {actual_pl_ratio:.4f} |
| 总交易次数 | {total_trades} |
| 总盈亏 | ¥{total_pnl:,.2f} |
| 年化波动率 | {volatility:.4f}% |
| Sortino比率 | {sortino:.4f} |
| VaR(95%) | {var_95:.4f}% |

"""

    # ── 净值曲线描述 ──────────────────────────────────
    md += """## 四、净值曲线分析

### 走势描述

"""
    if equity_rows:
        first = equity_rows[0]
        last = equity_rows[-1]
        start_eq = float(first.get("equity", 1_000_000))
        end_eq = float(last.get("equity", 1_000_000))
        peak_eq = max(float(e.get("equity", 0)) for e in equity_rows)
        trough_eq = min(float(e.get("equity", 0)) for e in equity_rows)
        md += (
            f"- **初始净值**: ¥{start_eq:,.2f}\n"
            f"- **最终净值**: ¥{end_eq:,.2f}\n"
            f"- **峰值净值**: ¥{peak_eq:,.2f}\n"
            f"- **谷值净值**: ¥{trough_eq:,.2f}\n"
            f"- **净值变化**: {((end_eq - start_eq) / start_eq) * 100:.4f}%\n\n"
        )

        # 有交易阶段描述
        active_dates = [e.get("date", "") for e in equity_rows if float(e.get("return_pct", 0)) != 0]
        if active_dates:
            md += f"- **活跃交易期**: {active_dates[0]} ~ {active_dates[-1]}（{len(active_dates)} 个交易日有净值变动）\n"
        md += "\n"

    # 说明没有图表
    md += """> 📊 注：当前为文本摘要报告。净值曲线图表可通过 equity_curve.csv 数据生成。

"""

    # ── 交易明细总结 ──────────────────────────────────
    md += """## 五、交易明细汇总

"""
    if trade_rows:
        md += f"| 指标 | 值 |\n|:---|---:|\n"
        md += f"| 总交易次数 | {len(trade_rows)} |\n"
        md += f"| 盈利交易 | {len(win_trades)} |\n"
        md += f"| 亏损交易 | {len(loss_trades)} |\n"
        md += f"| 平均盈利 | {avg_win:.4f}% |\n"
        md += f"| 平均亏损 | {avg_loss:.4f}% |\n"
        md += f"| 盈亏比 | {actual_pl_ratio:.4f} |\n"
        md += f"| 单笔最大盈利 | {max(float(t.get('return_pct',0)) for t in trade_rows):.4f}% |\n"
        md += f"| 单笔最大亏损 | {min(float(t.get('return_pct',0)) for t in trade_rows):.4f}% |\n\n"

        # 交易明细表
        md += "### 交易日志\n\n"
        md += "| # | 开仓日期 | 平仓日期 | 方向 | 开仓价 | 平仓价 | 数量 | 盈亏(¥) | 收益率 |\n"
        md += "|:---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|\n"
        for t in trade_rows[:50]:  # 最多50条
            md += (
                f"| {t.get('trade_id','')} | {t.get('open_date','')} | {t.get('close_date','')} "
                f"| {t.get('direction','')} | {float(t.get('open_price',0)):.2f} | {float(t.get('close_price',0)):.2f} "
                f"| {t.get('quantity',0)} | ¥{float(t.get('pnl',0)):,.2f} | {float(t.get('return_pct',0)):.4f}% |\n"
            )
    else:
        md += "无交易记录。\n"

    md += "\n"

    # ── 资金使用率 ──────────────────────────────────
    md += """## 六、资金使用率分析

"""
    if cash_rows:
        open_events = [c for c in cash_rows if c.get("action") == "open"]
        md += f"| 指标 | 值 |\n|:---|---:|\n"
        md += f"| 总开仓次数 | {len(open_events)} |\n"
        md += f"| 平均单次资金使用率 | {avg_usage:.2f}% |\n"
        md += f"| 最大资金使用率 | {max_usage:.2f}% |\n"
        md += f"| 总投入资金 | ¥{sum(float(c.get('cost',0)) for c in open_events):,.2f} |\n\n"

        # 资金使用率事件表
        md += "### 资金占用事件\n\n"
        md += "| 日期 | 动作 | 数量 | 价格 | 占用资金 | 使用率 |\n"
        md += "|:---:|:---:|---:|---:|---:|---:|\n"
        for c in cash_rows[:30]:
            md += f"| {c.get('date','')} | {c.get('action','')} | {c.get('quantity',0)} | ¥{c.get('price',0):.2f} | ¥{c.get('cost',0):,.2f} | {c.get('usage_pct',0):.2f}% |\n"
    else:
        md += "无资金使用数据。\n"

    md += "\n"

    # ── 结论与建议 ──────────────────────────────────
    md += """## 七、结论与建议

### 最佳策略配置

"""
    if best:
        md += f"> **`{best['config_key']}`** — 网格类型 `{best['grid_type']}`, {best['n_levels']} 层, `{best['position_mode']}` 仓位, 冷却 `{best['cool_down_bars']}` Bar, 止损 `{best.get('stop_loss_pct',0)}`, 投票阈值 `{best.get('vote_threshold',0)}`\n\n"

    md += f"""### 绩效表现总结

- **年化收益**: {annual_ret:.2f}%（{'达标✅' if annual_ret >= 15 else '未达15%目标'})
- **夏普比率**: {sharpe:.2f}（{'优秀>2' if sharpe >= 2 else '良好>1' if sharpe >= 1 else '一般'})
- **最大回撤**: {max_dd:.2f}%（{'控制良好✅' if max_dd < 20 else '偏高⚠️'})
- **综合评分**: {top10[0].get('composite_score',0):.4f}(Top1)

### 操作建议

"""

    if sharpe > 1.5 and max_dd < 15 and annual_ret > 10:
        md += "- **评级**: ⭐⭐⭐ 积极配置\n"
        md += "- **建议仓位比例**: 总资金30-50%\n"
        md += "- **建议操作**: 可实际部署到实盘监控\n"
    elif sharpe > 0.8 and max_dd < 20 and annual_ret > 5:
        md += "- **评级**: ⭐⭐ 均衡配置\n"
        md += "- **建议仓位比例**: 总资金15-30%\n"
        md += "- **建议操作**: 建议进一步观察后再部署\n"
    else:
        md += "- **评级**: ⭐ 保守观察\n"
        md += "- **建议仓位比例**: 总资金5-15%\n"
        md += "- **建议操作**: 需要更多数据验证或优化参数\n"

    md += f"""
### 风险提示

1. **数据周期有限**: 仅 84 个交易日数据，策略在更长周期的表现需验证
2. **样本内过拟合风险**: 参数扫描在固定数据上运行，存在过拟合可能
3. **市场环境变化**: 中国石油作为能源股，受油价和政策影响显著
4. **流动性风险**: 实际交易中滑点可能高于回测假设的 0.1%
5. **单标的局限**: 网格策略在震荡市中表现最佳，趋势行情中可能持续亏损

---

*报告由墨枢系统（moheng）自动生成*
*免责声明：本报告仅供参考，不构成投资建议。过去表现不代表未来收益。*
"""

    return md


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════

def main():
    t_start = time.time()
    print(f"[pipeline] 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[pipeline] 标的: {SYMBOL}, 数据: {START_DATE} ~ {END_DATE}")

    # ── 获取价格 ──────────────────────────────────────
    avg_price, min_p, max_p = get_price_stats(SYMBOL)
    lb, ub = compute_grid_bounds(avg_price)

    # ── 任务1：参数扫描 ──────────────────────────────────
    top10, filtered, all_successful = task1_scan_params(lb, ub)

    # 写入最优参数报告 MD
    best_params_md = f"""<!--
author: 墨衡
created_time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-->
# 中国石油（601857）网格策略最优参数选择报告

**数据周期**: {START_DATE} ~ {END_DATE}
**扫描范围**: {len(GRID_TYPES)}种网格 × {len(N_LEVELS)}种层数 × {len(COOL_DOWN)}种冷却 × {len(POSITION_MODES)}种仓位 × {len(STOP_LOSS)}种止损 × {len(VOTE_THRESHOLDS)}种投票 = {len(filtered)}成功通过三重筛选

## 筛选标准
- 夏普比率 ≥ {MIN_SHARPE}
- 年化收益率 ≥ {MIN_ANNUAL_RET*100:.0f}%
- 最大回撤 ≤ {MAX_DRAWDOWN*100:.0f}%

## Top 10 参数组合

| 排名 | 网格类型 | 层数 | 冷却 | 仓位 | 止损 | 投票 | 夏普 | 年化 | 回撤 | 胜率 | 交易 | 评分 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|---:|---:|---:|
"""
    for i, r in enumerate(top10, 1):
        best_params_md += f"| {i} | {r['grid_type']} | {r['n_levels']} | {r['cool_down_bars']} | {r['position_mode']} | {r['stop_loss_pct']} | {r['vote_threshold']} | {float(r['sharpe_ratio']):.4f} | {float(r['annual_return_pct'])*100:.2f}% | {float(r['max_drawdown_pct'])*100:.2f}% | {float(r['win_rate_pct']):.1f}% | {r['total_trades']} | {r['composite_score']:.4f} |\n"
    best_params_md += "\n*报告由墨衡自动生成*\n"

    write_text(os.path.join(OUT_DIR, "grid_best_params.md"), best_params_md)

    # 写入 Top10 CSV
    top10_csv = []
    for r in top10:
        top10_csv.append({
            "rank": top10.index(r) + 1,
            "grid_type": r["grid_type"],
            "n_levels": r["n_levels"],
            "cool_down_bars": r["cool_down_bars"],
            "position_mode": r["position_mode"],
            "stop_loss_pct": r["stop_loss_pct"],
            "vote_threshold": r["vote_threshold"],
            "sharpe_ratio": r.get("sharpe_ratio", ""),
            "annual_return_pct": r.get("annual_return_pct", ""),
            "max_drawdown_pct": r.get("max_drawdown_pct", ""),
            "total_return_pct": r.get("total_return_pct", ""),
            "win_rate_pct": r.get("win_rate_pct", ""),
            "total_trades": r.get("total_trades", ""),
            "composite_score": r.get("composite_score", ""),
        })
    write_csv(os.path.join(OUT_DIR, "grid_top_params.csv"), top10_csv)

    # ── 任务2：详细回测 ──────────────────────────────────
    equity_rows, trade_rows, metrics = task2_detailed_backtest(top10)
    write_csv(os.path.join(OUT_DIR, "grid_equity_curve.csv"), equity_rows)
    write_csv(os.path.join(OUT_DIR, "grid_trade_log.csv"), trade_rows)

    # ── 任务3：资金使用率 ──────────────────────────────
    cash_rows = task3_cash_usage(top10, trade_rows)
    write_csv(os.path.join(OUT_DIR, "grid_cash_usage.csv"), cash_rows)

    # ── 任务4：完整报告 ──────────────────────────────
    report_md = task4_generate_report(top10, all_successful, equity_rows, trade_rows, cash_rows, metrics)
    write_text(os.path.join(OUT_DIR, "grid_full_report.md"), report_md)

    elapsed = time.time() - t_start
    mins, secs = int(elapsed // 60), int(elapsed % 60)
    print(f"\n{'='*60}")
    print(f"[pipeline] 全部完成! 耗时 {mins}分{secs}秒")
    print(f"{'='*60}")

    # 输出文件汇总
    print(f"\n所有产出文件:")
    for fname in ["grid_best_params.md", "grid_top_params.csv", "grid_equity_curve.csv", "grid_trade_log.csv", "grid_cash_usage.csv", "grid_full_report.md"]:
        fpath = os.path.join(OUT_DIR, fname)
        if os.path.exists(fpath):
            sz = os.path.getsize(fpath)
            print(f"  ✅ {fpath} ({sz} 字节)")
        else:
            print(f"  ❌ {fpath} 不存在")


if __name__ == "__main__":
    main()
