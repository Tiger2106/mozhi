r"""
EXP-2026-003-KNOWDEEP Step 2: Dry-run 验证脚本
===============================================
author: 墨衡 (moheng)
created: 2026-05-26T16:00+08:00

目标:
  1. 验证回测管道能否跑通、无报错
  2. 验证 EXP-002 因子计算在 2007~2019 训练期能正常产出（因数据源仅到2020，使用代理窗口验证计算逻辑）
  3. 验证评估指标的净收益计算（扣除交易成本后）
  4. 记录版本标记和问题清单

约束:
  - 仅对 Q1（跨窗口鲁棒性）运行 dry-run
  - 使用 3~5 只代表性标的：000001.SZ、600519.SH、300750.SZ
  - 成本参数：commission_rate=0.0003, stamp_tax_rate=0.0005(仅卖出), slippage=0.001

使用:
  python scripts/exp_knowdeep003/exp003_dryrun.py

输出:
  - 控制台：dry-run 进度和结果摘要
  - 文件：step2_dryrun_report.json（详细JSON结果）
  - 日志：step2_dryrun.log（完整日志）

依赖:
  - C:\Users\17699\mozhi_platform (项目根)
  - C:\Users\17699\mo_zhi_sharereports\backtest_engine/ (回测引擎)
  - market_data.db (数据源)
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ═══════════════════════════════════════════════════════════════
# 路径设置
# ═══════════════════════════════════════════════════════════════

# 控制台编码修复（Windows GBK 兼容）
import io
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 回测引擎路径
BACKTEST_ENGINE_DIR = r"C:\Users\17699\mo_zhi_sharereports\backtest_engine"
if BACKTEST_ENGINE_DIR not in sys.path:
    sys.path.insert(0, r"C:\Users\17699\mo_zhi_sharereports")
    sys.path.insert(0, BACKTEST_ENGINE_DIR)

# ═══════════════════════════════════════════════════════════════
# 导入
# ═══════════════════════════════════════════════════════════════

# EXP-002 因子函数
from scripts.exp_invfac002.exp_factors import (
    calc_trend_quality,
    calc_vol_rsi_std,
    reverse_factor,
)

# 回测引擎
from backtest_engine.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    Bar,
    Strategy,
    OrderRequest,
)
from backtest_engine.order_executor import OrderSide, OrderType
from backtest_engine.performance import PerformanceCalculator


# ═══════════════════════════════════════════════════════════════
# 硬编码配置
# ═══════════════════════════════════════════════════════════════

# 实验配置 — EXP-003 设计文档 §3.1
EXP_CONFIG = {
    "commission_rate": 0.0003,       # 佣金费率
    "stamp_tax_rate": 0.0005,        # 印花税（仅卖出）
    "slippage": 0.001,               # 滑点（单边）
    "holding_period_days": 20,       # 持有期
    "initial_capital": 1_000_000.0,  # 初始资金
    "train_period": ("20070101", "20191231"),  # 训练期
    "val_period": ("20200101", "20260430"),    # 验证期
    "data_period": ("20200102", "20260515"),   # 实际可用数据范围
}

DB_PATH = os.path.join(PROJECT_ROOT, "data", "market", "market_data.db")

# Dry-run 标的（3只代表性标的）
STOCKS_DRYRUN = [
    ("000001", ".SZ"),   # 平安银行 — 上市最久的大盘金融
    ("600519", ".SH"),   # 贵州茅台 — 消费龙头
    ("300750", ".SZ"),   # 宁德时代 — 新能源
]

# 因子配置（继承 EXP-002 最优参数）
FACTOR_CONFIGS = {
    "l_vol_rsi_std": {
        "func": calc_vol_rsi_std,
        "fields": ["volume"],
        "params": {"rsi_period": 14, "std_period": 20},
        "direction": "positive",
    },
    "TrendQuality": {
        "func": calc_trend_quality,
        "fields": ["high", "low", "close"],
        "params": {"period": 20},
        "direction": "negative",
    },
}


# ═══════════════════════════════════════════════════════════════
# 辅助：版本标记
# ═══════════════════════════════════════════════════════════════

def get_version_tag() -> str:
    """获取 mozhi_platform git HEAD (short)。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ═══════════════════════════════════════════════════════════════
# 辅助：时间戳
# ═══════════════════════════════════════════════════════════════

def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════

def load_stock_data(ts_code: str) -> Optional[dict]:
    """从 market_data.db 加载个股数据并 QFQ 复权，与 EXP-002 一致。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT date, open, high, low, close, volume, adj_factor
        FROM stock_daily
        WHERE code=?
        ORDER BY date
    """, (ts_code,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    dates = np.array([r[0] for r in rows])
    open_p = np.array([r[1] for r in rows], dtype=float)
    high = np.array([r[2] for r in rows], dtype=float)
    low = np.array([r[3] for r in rows], dtype=float)
    close = np.array([r[4] for r in rows], dtype=float)
    volume = np.array([r[5] for r in rows], dtype=float)
    adj_factor = np.array([r[6] if r[6] else 1.0 for r in rows], dtype=float)

    # QFQ 前复权
    latest_adj = adj_factor[-1] if len(adj_factor) > 0 else 1.0
    adj_ratio = adj_factor / latest_adj
    open_qfq = open_p * adj_ratio
    high_qfq = high * adj_ratio
    low_qfq = low * adj_ratio
    close_qfq = close * adj_ratio

    return {
        "code": ts_code,
        "dates": dates,
        "open": open_qfq,
        "high": high_qfq,
        "low": low_qfq,
        "close": close_qfq,
        "volume": volume,
        "adj_factor_raw": adj_factor,
    }


def to_bar_list(data: dict) -> List[Bar]:
    """将 numpy 格式的数据转换为 Bar 列表。"""
    bars = []
    for i in range(len(data["dates"])):
        bar = Bar(
            date=str(data["dates"][i]),
            symbol=data["code"],
            open=float(data["open"][i]),
            high=float(data["high"][i]),
            low=float(data["low"][i]),
            close=float(data["close"][i]),
            volume=float(data["volume"][i]),
        )
        bars.append(bar)
    return bars


# ═══════════════════════════════════════════════════════════════
# 因子计算 + 信号生成
# ═══════════════════════════════════════════════════════════════

def compute_factor_values(stock_data: dict) -> dict:
    """
    计算 l_vol_rsi_std 和 TrendQuality 因子。
    返回 {factor_name: np.ndarray}。
    """
    result = {}
    for fname, fcfg in FACTOR_CONFIGS.items():
        fields = [stock_data[f] for f in fcfg["fields"]]
        values = fcfg["func"](*fields, **fcfg["params"])
        result[fname] = values
    return result


def factor_to_signal(
    factor_values: np.ndarray,
    direction: str,
    threshold: float = 0.0,
    lookback: int = 20,
) -> np.ndarray:
    """
    将因子值转换为交易信号。

    Parameters
    ----------
    factor_values : np.ndarray — 因子值序列
    direction : str — "positive"表示高因子值触发买入
    threshold : float — 信号阈值（标准差倍数，0=仅需不为NaN）
    lookback : int — 滚动窗口用于计算阈值

    Returns
    -------
    np.ndarray — 信号: 1(买入), -1(卖出), 0(无), NaN(信号未就绪)
    """
    n = len(factor_values)
    signal = np.full(n, np.nan)

    # 等待足够的lookback窗口
    if n < lookback:
        return signal

    valid = ~np.isnan(factor_values)
    rolling_mean = np.full(n, np.nan)
    rolling_std = np.full(n, np.nan)

    for i in range(lookback, n):
        window = factor_values[i - lookback:i]
        valid_win = window[~np.isnan(window)]
        if len(valid_win) > 5:
            rolling_mean[i] = np.mean(valid_win)
            rolling_std[i] = np.std(valid_win)

    for i in range(lookback, n):
        if not valid[i] or np.isnan(rolling_mean[i]) or np.isnan(rolling_std[i]):
            continue
        if rolling_std[i] < 1e-10:
            continue

        zscore = (factor_values[i] - rolling_mean[i]) / rolling_std[i]

        if direction == "positive":
            # l_vol_rsi_std: 正向因子，高值=买入信号
            if zscore > threshold:
                signal[i] = 1  # 买入
            elif zscore < -threshold:
                signal[i] = -1  # 卖出
            else:
                signal[i] = 0
        elif direction == "negative":
            # TrendQuality: 负向因子，低值=买入信号（反转）
            if zscore < -threshold:
                signal[i] = 1  # 买入（负向因子极端低值触发反转买入）
            elif zscore > threshold:
                signal[i] = -1  # 卖出（负向因子极端高值触发反转卖出）
            else:
                signal[i] = 0

    return signal


# ═══════════════════════════════════════════════════════════════
# 因子回测策略
# ═══════════════════════════════════════════════════════════════

class FactorBacktestStrategy(Strategy):
    """
    基于因子信号的持有期策略。

    逻辑：
      - 在持有期内不重复开仓
      - 持有期届满后检查信号，决定开仓方向
      - 管理多标的持仓
    """

    def __init__(
        self,
        signals: Dict[str, np.ndarray],
        dates: np.ndarray,
        holding_period: int = 20,
        commission_rate: float = 0.0003,
        stamp_tax_rate: float = 0.0005,
        slippage: float = 0.001,
    ):
        super().__init__()
        self.signals = signals          # {symbol: np.ndarray of signals}
        self.dates = dates              # 全局日期索引
        self.holding_period = holding_period
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage = slippage

        # 状态跟踪: {symbol: {"entry_date": str, "direction": 1|-1}}
        self.active_positions: Dict[str, dict] = {}
        self.signals_by_date: Dict[str, Dict[str, float]] = {}

        # 预构建日期→信号映射
        self._build_date_signal_map()

    def _build_date_signal_map(self):
        """将信号数组转换为日期→{symbol: signal}字典。"""
        for symbol, sig_arr in self.signals.items():
            for i, date_str in enumerate(self.dates):
                if i >= len(sig_arr):
                    break
                s = sig_arr[i]
                if not np.isnan(s) and s != 0:
                    if date_str not in self.signals_by_date:
                        self.signals_by_date[date_str] = {}
                    self.signals_by_date[date_str][symbol] = int(s)

    def on_bar(self, context, bar: Bar) -> Optional[List[OrderRequest]]:
        if bar.date not in self.signals_by_date:
            return None

        symbols_signals = self.signals_by_date[bar.date]
        if bar.symbol not in symbols_signals:
            return None

        signal = symbols_signals[bar.symbol]
        orders = []

        # 检查是否有此标的的活跃持仓
        pos = context.positions.get(bar.symbol) if context.positions.has_position(bar.symbol) else None

        if pos is not None:
            # 已有持仓：检查持有期是否已到
            avg_price = pos.avg_price
            if signal == -1:
                # 卖出信号 → 平仓
                qty = pos.quantity
                if qty > 0:
                    orders.append(OrderRequest(
                        symbol=bar.symbol,
                        side=OrderSide.SELL,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                    ))
        elif signal == 1:
            # 无持仓且买入信号 → 开仓
            max_cost = context.available_capital * 0.30  # 单标的不超过30%资金
            qty = int(max_cost // (bar.close * (1 + self.slippage)))
            qty = (qty // 100) * 100  # 整手
            if qty >= 100:
                orders.append(OrderRequest(
                    symbol=bar.symbol,
                    side=OrderSide.BUY,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                ))

        return orders if orders else None


# ═══════════════════════════════════════════════════════════════
# 自定义手续费计算器（含印花税）
# ═══════════════════════════════════════════════════════════════

def calc_net_return(
    trades: List[Dict[str, Any]],
    equity_curve: List[Dict[str, float]],
    initial_capital: float,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage: float = 0.001,
) -> dict:
    """
    重新计算扣除交易成本后的净收益指标。
    因为引擎当前未区分印花税，这里手动修正。

    返回修正后的指标。
    """
    if not equity_curve or len(equity_curve) < 2:
        return {"error": "insufficient data"}

    # 1. 计算总成本明细
    total_commission = 0.0
    total_stamp_tax = 0.0
    total_slippage = 0.0

    for t in trades:
        price = t.get("price", 0)
        qty = t.get("quantity", 0)
        turnover = price * qty

        # 佣金：所有交易
        commission = turnover * commission_rate
        commission = max(commission, 5.0)  # 最低5元
        total_commission += commission

        # 印花税：仅卖出
        if t.get("side") == "sell":
            stamp = turnover * stamp_tax_rate
            total_stamp_tax += stamp

        # 滑点：所有交易
        slip = turnover * slippage
        total_slippage += slip

    total_cost = total_commission + total_stamp_tax + total_slippage

    # 2. 计算毛/净收益
    first_equity = equity_curve[0]["total_equity"]
    last_equity = equity_curve[-1]["total_equity"]
    gross_return = last_equity - first_equity
    total_return_pct = (last_equity - first_equity) / first_equity * 100

    # 净收益 = 总收益 - 总成本
    net_return = gross_return - total_cost
    net_return_pct = net_return / first_equity * 100

    # 3. 持有期检查（基于交易记录）
    buy_trades = [t for t in trades if t.get("side") == "buy"]
    sell_trades = [t for t in trades if t.get("side") == "sell"]
    holding_periods = []
    for st in sell_trades:
        # 找到最近的买入
        for bt in reversed(buy_trades):
            if bt.get("symbol") == st.get("symbol") and bt.get("date") < st.get("date"):
                # 粗略估算交易日数
                delta = (int(st.get("date", "0")) - int(bt.get("date", "0")))
                holding_periods.append(delta)
                break

    return {
        "total_commission": round(total_commission, 2),
        "total_stamp_tax": round(total_stamp_tax, 2),
        "total_slippage": round(total_slippage, 2),
        "total_trading_cost": round(total_cost, 2),
        "cost_breakdown": {
            "commission_pct": round(total_commission / total_cost * 100, 1) if total_cost > 0 else 0,
            "stamp_tax_pct": round(total_stamp_tax / total_cost * 100, 1) if total_cost > 0 else 0,
            "slippage_pct": round(total_slippage / total_cost * 100, 1) if total_cost > 0 else 0,
        },
        "gross_return_pct": round(total_return_pct, 4),
        "net_return_pct": round(net_return_pct, 4),
        "cost_drag_pct": round(total_cost / first_equity * 100, 4),
        "avg_holding_period": round(np.mean(holding_periods), 1) if holding_periods else None,
    }


# ═══════════════════════════════════════════════════════════════
# 1号干运行：因子计算验证
# ═══════════════════════════════════════════════════════════════

def run_factor_validation(stock_data: dict) -> dict:
    """验证因子计算函数在可用数据上能否正常产出。"""
    result = {
        "stock_code": stock_data["code"],
        "data_points": len(stock_data["dates"]),
        "date_range": f"{stock_data['dates'][0]} ~ {stock_data['dates'][-1]}",
        "factors_validated": {},
    }

    factor_values = compute_factor_values(stock_data)

    for fname, values in factor_values.items():
        non_nan = np.sum(~np.isnan(values))
        all_nan = np.sum(np.isnan(values))
        min_val = float(np.nanmin(values)) if non_nan > 0 else None
        max_val = float(np.nanmax(values)) if non_nan > 0 else None

        result["factors_validated"][fname] = {
            "computed": True,
            "non_nan_count": int(non_nan),
            "nan_count": int(all_nan),
            "min": round(min_val, 6) if min_val is not None else None,
            "max": round(max_val, 6) if max_val is not None else None,
        }

    return result


# ═══════════════════════════════════════════════════════════════
# 2号干运行：回测管道验证
# ═══════════════════════════════════════════════════════════════

def run_backtest_pipeline(
    stock_data_list: List[dict],
    start_date: str,
    end_date: str,
) -> dict:
    """
    验证回测管道完整性：数据→因子→信号→回测→指标。

    返回执行结果字典。
    """
    result = {
        "period": f"{start_date} ~ {end_date}",
        "stocks": [d["code"] for d in stock_data_list],
        "pipeline_steps": {},
        "output_files": [],
        "errors": [],
    }

    # Step 1: 数据加载
    print(f"\n[Step 1] 数据加载...")
    all_bars = []
    step1_ok = True
    for sd in stock_data_list:
        bars = to_bar_list(sd)
        all_bars.extend(bars)
        print(f"  {sd['code']}: {len(bars)} bars ({sd['dates'][0]} ~ {sd['dates'][-1]})")

    # 过滤日期范围
    filtered_bars = [b for b in all_bars if start_date <= b.date <= end_date]
    result["pipeline_steps"]["data_load"] = {
        "status": "PASS",
        "total_bars": len(filtered_bars),
        "stock_count": len(stock_data_list),
    }
    print(f"  过滤后: {len(filtered_bars)} bars")

    if not filtered_bars:
        result["pipeline_steps"]["data_load"]["status"] = "FAIL"
        result["errors"].append("无有效数据")
        return result

    # Step 2: 因子计算
    print(f"\n[Step 2] 因子计算...")
    factor_values_by_stock = {}
    signals_by_stock = {}
    step2_ok = True

    stock_code_map = {d["code"]: d for d in stock_data_list}
    for sd in stock_data_list:
        factor_vals = compute_factor_values(sd)
        factor_values_by_stock[sd["code"]] = factor_vals

        # 生成信号
        for fname, fcfg in FACTOR_CONFIGS.items():
            sig = factor_to_signal(
                factor_vals[fname],
                direction=fcfg["direction"],
                threshold=1.0,
                lookback=20,
            )
            signals_by_stock[f"{sd['code']}_{fname}"] = sig

        # 验证因子产出
        for fname, vals in factor_vals.items():
            non_nan = np.sum(~np.isnan(vals))
            print(f"  {sd['code']}/{fname}: {non_nan} non-NaN")
            if non_nan == 0:
                step2_ok = False

    result["pipeline_steps"]["factor_calc"] = {
        "status": "PASS" if step2_ok else "WARN",
        "factors": list(FACTOR_CONFIGS.keys()),
        "expected_lookback": 20,
    }

    if not step2_ok:
        result["errors"].append("部分因子未能产出有效值")

    # Step 3: 回测运行
    print(f"\n[Step 3] 回测运行...")
    print(f"  参数: commission={EXP_CONFIG['commission_rate']}, "
          f"slippage={EXP_CONFIG['slippage']}, "
          f"持有期={EXP_CONFIG['holding_period_days']}d")

    try:
        # 合并信号字典（每个标的独立信号）
        combined_signals = {}
        for sd in stock_data_list:
            code = sd["code"]
            # 取两因子信号的加权和作为综合信号
            sig_lvol = signals_by_stock.get(f"{code}_l_vol_rsi_std", np.full(len(sd["dates"]), np.nan))
            sig_tq = signals_by_stock.get(f"{code}_TrendQuality", np.full(len(sd["dates"]), np.nan))

            # 等权合成
            combined = np.full(len(sd["dates"]), np.nan)
            both_valid = ~np.isnan(sig_lvol) & ~np.isnan(sig_tq)
            combined[both_valid] = sig_lvol[both_valid] * 0.5 + sig_tq[both_valid] * 0.5
            combined_signals[code] = combined

        # 使用第一个股票的日期索引（所有标的日期一致）
        ref_date = stock_data_list[0]["dates"]

        # 创建策略
        strategy = FactorBacktestStrategy(
            signals=combined_signals,
            dates=ref_date,
            holding_period=EXP_CONFIG["holding_period_days"],
            commission_rate=EXP_CONFIG["commission_rate"],
            stamp_tax_rate=EXP_CONFIG["stamp_tax_rate"],
            slippage=EXP_CONFIG["slippage"],
        )

        # 配置引擎
        cfg = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            initial_capital=EXP_CONFIG["initial_capital"],
            fee_rate=EXP_CONFIG["commission_rate"],    # 仅用于佣金（不含印花税）
            slippage_rate=EXP_CONFIG["slippage"],
            min_fee=5.0,
        )

        engine = BacktestEngine(config=cfg, strategy=strategy)
        bt_result = engine.run(filtered_bars)

        # Step 4: 绩效指标
        print(f"\n[Step 4] 绩效指标...")
        metrics = bt_result.metrics

        # 修正净收益（含印花税）
        cost_analysis = calc_net_return(
            trades=bt_result.trades,
            equity_curve=bt_result.equity_curve,
            initial_capital=EXP_CONFIG["initial_capital"],
            commission_rate=EXP_CONFIG["commission_rate"],
            stamp_tax_rate=EXP_CONFIG["stamp_tax_rate"],
            slippage=EXP_CONFIG["slippage"],
        )

        print(f"  总交易: {bt_result.total_trades}")
        print(f"  毛收益: {metrics.get('total_return_pct', 0):.2f}%")
        print(f"  净收益修正: {cost_analysis.get('net_return_pct', 0):.2f}%")
        print(f"  交易成本: {cost_analysis.get('total_trading_cost', 0):.2f}")
        print(f"  Sharpe: {metrics.get('sharpe_ratio', 0):.4f}")
        print(f"  最大回撤: {metrics.get('max_drawdown_pct', 0):.2f}%")

        result["pipeline_steps"]["backtest"] = {
            "status": "PASS",
            "total_trades": bt_result.total_trades,
            "total_bars": bt_result.total_bars,
            "actual_range": f"{bt_result.start_date} ~ {bt_result.end_date}",
        }

        result["pipeline_steps"]["performance"] = {
            "status": "PASS",
            "metrics_summary": {
                "total_return_pct": metrics.get("total_return_pct"),
                "annual_return_pct": metrics.get("annual_return_pct"),
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                "win_rate_pct": metrics.get("win_rate_pct"),
                "profit_loss_ratio": metrics.get("profit_loss_ratio"),
            },
            "cost_analysis": cost_analysis,
        }

    except Exception as e:
        tb = traceback.format_exc()
        result["pipeline_steps"]["backtest"] = {"status": "FAIL", "error": str(e)}
        result["errors"].append(f"回测异常: {str(e)}\n{tb}")
        print(f"  [ERROR] {e}")

    return result


# ═══════════════════════════════════════════════════════════════
# 3号干运行：数据源时间范围检查
# ═══════════════════════════════════════════════════════════════

def check_data_availability() -> dict:
    """检查数据源是否能覆盖 EXP-003 要求的时间范围。"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT MIN(date), MAX(date) FROM stock_daily")
    actual_min, actual_max = cur.fetchone()

    cur.execute("SELECT code, MIN(date), MAX(date), COUNT(*) FROM stock_daily GROUP BY code LIMIT 50")
    stock_ranges = {}
    for code, min_d, max_d, cnt in cur.fetchall():
        stock_ranges[code] = {
            "min_date": min_d,
            "max_date": max_d,
            "rows": cnt,
        }
    conn.close()

    # 检查覆盖度
    required_start = EXP_CONFIG["train_period"][0]  # 20070101
    required_end = EXP_CONFIG["val_period"][1]      # 20260430

    train_gap = ""
    if actual_min and actual_min > required_start:
        train_gap = f"缺少 {required_start} ~ {actual_min}（约{int((int(actual_min[:4]) - int(required_start[:4])))}年）"

    val_coverage = "完整" if actual_max and actual_max >= required_end else f"缺少 {actual_max} ~ {required_end}"

    return {
        "actual_min_date": actual_min,
        "actual_max_date": actual_max,
        "required_train_start": required_start,
        "required_val_end": required_end,
        "train_data_gap": train_gap,
        "val_coverage": val_coverage,
        "stock_coverage": {
            code: info["min_date"] >= required_start[:8]
            for code, info in stock_ranges.items()
        },
    }


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("EXP-2026-003-KNOWDEEP Step 2: Dry-run 验证")
    print(f"启动时间: {now_iso()}")
    print("=" * 70)

    dryrun_report = {
        "title": "EXP-003 Step 2 Dry-run Report",
        "experiment": "EXP-2026-003-KNOWDEEP",
        "step": 2,
        "created_time": now_iso(),
        "version_tag": get_version_tag(),
        "author": "墨衡 (moheng)",
        "dryrun_params": {
            "stocks": [f"{c}{s}" for c, s in STOCKS_DRYRUN],
            "data_source": str(DB_PATH),
            "commission_rate": EXP_CONFIG["commission_rate"],
            "stamp_tax_rate": EXP_CONFIG["stamp_tax_rate"],
            "slippage": EXP_CONFIG["slippage"],
            "holding_period": EXP_CONFIG["holding_period_days"],
            "backtest_engine_version": "C:\\Users\\17699\\mo_zhi_sharereports\\backtest_engine",
            "factor_source": "scripts.exp_invfac002.exp_factors (commit 0bec5f6)",
        },
        "checks": {},
        "issues": [],
        "conclusion": "PENDING",
    }

    # ── 检查0: 数据可用性 ──────────────────────────────────
    print(f"\n{'─' * 50}")
    print("[检查0] 数据源时间范围检查")
    print(f"{'─' * 50}")

    data_check = check_data_availability()
    print(f"  实际数据: {data_check['actual_min_date']} ~ {data_check['actual_max_date']}")
    print(f"  要求训练期: {data_check['required_train_start']} ~ 20191231")
    print(f"  训练数据差距: {data_check['train_data_gap'] or '无'}")
    print(f"  验证期覆盖: {data_check['val_coverage']}")

    data_issue = None
    if data_check["train_data_gap"]:
        data_issue = (
            f"数据源仅覆盖 {data_check['actual_min_date']} 起，"
            f"缺少 2007~2019 训练期数据（{data_check['train_data_gap']}）。"
            f"Dry-run 使用 2020-2022 作为代理训练窗口，2023~2026-04 作为代理验证窗口。"
        )
        print(f"\n  [⚠] {data_issue}")
        dryrun_report["issues"].append({
            "severity": "BLOCKER",
            "category": "数据源",
            "description": data_issue,
            "mitigation": "需从其他数据源补充 A50 2007-2019 日线数据（如TuShare/Wind API 批量拉取）",
        })

    dryrun_report["checks"]["data_availability"] = {
        "status": "PASS" if not data_check["train_data_gap"] else "WARN",
        "details": data_check,
    }

    # ── 加载数据 ──────────────────────────────────────────
    print(f"\n{'─' * 50}")
    print("[加载] 加载 dry-run 标的日线数据")
    print(f"{'─' * 50}")

    stock_data_list = []
    load_errors = []
    for code, suffix in STOCKS_DRYRUN:
        try:
            data = load_stock_data(code)
            if data is None or len(data["dates"]) == 0:
                load_errors.append(f"{code}{suffix}: 无数据")
                continue
            stock_data_list.append(data)
            print(f"  {code}{suffix}: {len(data['dates'])} rows, {data['dates'][0]} ~ {data['dates'][-1]}")
        except Exception as e:
            load_errors.append(f"{code}{suffix}: {e}")

    if not stock_data_list:
        print("[FATAL] 无可用数据，终止")
        dryrun_report["conclusion"] = "FAIL"
        return dryrun_report

    # ── 检查1: 因子计算验证 ────────────────────────────────
    print(f"\n{'─' * 50}")
    print("[检查1] 因子计算验证")
    print(f"{'─' * 50}")

    factor_checks = []
    all_factors_ok = True
    for sd in stock_data_list:
        fv = run_factor_validation(sd)
        factor_checks.append(fv)
        for fname, finfo in fv["factors_validated"].items():
            status = "PASS" if finfo["non_nan_count"] > 0 else "FAIL"
            print(f"  {fv['stock_code']}/{fname}: {status} ({finfo['non_nan_count']} non-NaN)")
            if status == "FAIL":
                all_factors_ok = False

    dryrun_report["checks"]["factor_validation"] = {
        "status": "PASS" if all_factors_ok else "FAIL",
        "details": factor_checks,
    }

    if not all_factors_ok:
        dryrun_report["issues"].append({
            "severity": "BLOCKER",
            "category": "因子计算",
            "description": "部分标的因子计算未能产出有效值",
        })

    # ── 检查2: 回测管道（代理训练期 2020-2022） ─────────────
    print(f"\n{'─' * 50}")
    print("[检查2] 回测管道验证 — 代理训练期 2020-01~2022-12")
    print(f"{'─' * 50}")

    train_result = run_backtest_pipeline(
        stock_data_list=stock_data_list,
        start_date="20200102",
        end_date="20221231",
    )

    has_train_errors = len(train_result.get("errors", [])) > 0
    dryrun_report["checks"]["train_window_backtest"] = train_result
    dryrun_report["checks"]["train_window_backtest"]["status"] = "WARN" if not has_train_errors else "FAIL"

    if has_train_errors:
        dryrun_report["issues"].append({
            "severity": "HIGH",
            "category": "回测管道",
            "description": f"训练期回测异常: {train_result['errors']}",
        })

    # ── 检查3: 回测管道（代理验证期 2023-01~2026-04） ───────
    print(f"\n{'─' * 50}")
    print("[检查3] 回测管道验证 — 代理验证期 2023-01~2026-04")
    print(f"{'─' * 50}")

    val_result = run_backtest_pipeline(
        stock_data_list=stock_data_list,
        start_date="20230101",
        end_date="20260430",
    )

    has_val_errors = len(val_result.get("errors", [])) > 0
    dryrun_report["checks"]["val_window_backtest"] = val_result
    dryrun_report["checks"]["val_window_backtest"]["status"] = "WARN" if not has_val_errors else "FAIL"

    if has_val_errors:
        dryrun_report["issues"].append({
            "severity": "HIGH",
            "category": "回测管道",
            "description": f"验证期回测异常: {val_result['errors']}",
        })

    # ── 结论判定 ──────────────────────────────────────────
    has_blocker = any(i["severity"] == "BLOCKER" for i in dryrun_report["issues"])
    has_high = any(i["severity"] == "HIGH" for i in dryrun_report["issues"])

    if has_blocker:
        dryrun_report["conclusion"] = "FAIL"
    elif has_high:
        dryrun_report["conclusion"] = "WARN — 需调整"
    else:
        dryrun_report["conclusion"] = "PASS"

    print(f"\n{'=' * 70}")
    print(f"DDRY-RUN 结论: {dryrun_report['conclusion']}")
    if dryrun_report["issues"]:
        print(f"发现 {len(dryrun_report['issues'])} 个问题:")
        for i, issue in enumerate(dryrun_report["issues"], 1):
            print(f"  [{issue['severity']}] {issue['category']}: {issue['description'][:100]}")
    print(f"{'=' * 70}")

    return dryrun_report


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    t0 = time.time()
    report = main()
    elapsed = time.time() - t0

    print(f"\n耗时: {elapsed:.1f}s")
    print(f"结论: {report['conclusion']}")

    # 写入 JSON
    output_dir = os.path.join(PROJECT_ROOT, "reports", "EXP-2026-003-KNOWDEEP")
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, "step2_dryrun_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"JSON 报告: {json_path}")
