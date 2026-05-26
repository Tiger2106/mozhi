from src.config import SHANGHAI_TZ
"""
墨枢 - P5b-05/06: ReportRenderer
日报/周报渲染器
将数据提取器的结构化数据填充到模板，生成最终Markdown报告。

纯 Python 实现，无外部模板引擎依赖。

Author: 墨衡
Created: 2026-05-15
Version: 1.0

用法::

    renderer = ReportRenderer()
    md = renderer.render_daily(daily_data)   # 日报
    md = renderer.render_weekly(weekly_data)  # 周报
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Pattern, Tuple, Union

from backtest.pipeline.daily_extractor import DailyReportExtractor
from backtest.pipeline.weekly_extractor import WeeklyReportExtractor

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
MISSING_PLACEHOLDER = "N/A"

# 策略默认参数（各策略文件 __init__ / dataclass 默认值）
DEFAULT_STRATEGY_PARAMS = {
    "trend": {
        "ma_fast": 5,
        "ma_slow": 20,
        "signal_type": "crossover",
        "stop_loss": "未设置 (None)",
        "take_profit": "未设置 (None)",
    },
    "reversal": {
        "rsi_window": 14,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "kdj_n": 9,
        "kdj_m1": 3,
        "kdj_m2": 3,
        "bollinger_window": 20,
        "bollinger_std": 2.0,
        "bias_buy": -5.0,
        "bias_sell": 5.0,
        "min_votes": 2,
        "cooler_days": 2,
    },
    "grid": {
        "n_levels": 10,
        "grid_type": "arithmetic",
        "cool_down_bars": 5,
        "default_quantity": 100,
        "lower_bound": "动态计算",
        "upper_bound": "动态计算",
    },
    "multi_runner": {
        "allocation_mode": "equal",
        "conflict_priority": "trend(3)>reversal(2)>grid(1)",
        "initial_capital": "1,000,000",
        "fee_rate": 0.0003,
        "slippage_rate": 0.001,
    },
}

# 正则：模板变量 {{xxx}} 或 {{#each xxx}} / {{#if xxx}}
_VAR_RE = re.compile(r"\{\{(.+?)\}\}")
_BLOCK_RE = re.compile(
    r"\{\{#(each|if)\s+([\w.]+)\}\}(.*?)\{\{/(\1)\}\}",
    re.DOTALL,
)
# 嵌套 {{this.field}} 支持
_THIS_VAR_RE = re.compile(r"\{\{this\.([\w]+)\}\}")

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _resolve_path(data: dict, path: str) -> Any:
    """
    从嵌套字典中解析点号路径。

    _resolve_path({"a": {"b": 3}}, "a.b") → 3
    _resolve_path({"a": 1}, "a.b") → None  (路径不存在)
    """
    if not path or not data:
        return None

    parts = path.split(".")
    current: Any = data

    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return None
        else:
            return None

    return current

def _format_value(value: Any) -> str:
    """将任意 Python 值格式化为字符串，用于模板替换。"""
    if value is None:
        return MISSING_PLACEHOLDER
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        # 对浮点数，如果无小数部分则格式化为整数
        if isinstance(value, float) and value == int(value):
            return str(int(value))
        return str(value)
    return str(value)

# ═══════════════════════════════════════════════════════════════
# 模板引擎
# ═══════════════════════════════════════════════════════════════

def _pair_trades(trades_list: List[dict]) -> List[dict]:
    """
    将同一策略的独立 BUY/SELL 填充记录配对为完整的 round-trip 交易。

    FIFO 配对：同一策略内的 BUY 按时间顺序依次与后续的 SELL 配对，
    配对后计算盈亏金额、盈亏比例、持仓天数。

    参数
    ----------
    trades_list : list[dict]
        同一策略的填充记录列表（含 date, side, price, quantity, fee）。

    返回
    -------
    list[dict]
        配对后的 round-trip 交易列表：
        [{
            "entry_date": str, "exit_date": str,
            "entry_price": float, "exit_price": float,
            "quantity": int,
            "pnl": float, "pnl_pct": float,
            "holding_days": int,
            "direction": str,
        }, ...]
    """
    from datetime import datetime

    def _date_diff(d1: str, d2: str) -> int:
        try:
            return (datetime.strptime(d1, "%Y%m%d") - datetime.strptime(d2, "%Y%m%d")).days
        except (ValueError, TypeError):
            return 0

    pairs = []
    # 按日期排序
    sorted_trades = sorted(trades_list, key=lambda t: t.get("date", ""))
    buys = []  # 待配对的 BUY 队列

    for t in sorted_trades:
        side = t.get("side", "").upper()
        qty = int(t.get("quantity", 0))
        if side == "BUY":
            buys.append(t)
        elif side == "SELL" and buys:
            # FIFO: 从最老的 BUY 开始配对
            buy = buys.pop(0)
            entry_price = float(buy.get("price", 0))
            exit_price = float(t.get("price", 0))
            b_qty = int(buy.get("quantity", 0))
            s_qty = qty
            paired_qty = min(b_qty, s_qty)

            if entry_price > 0:
                pnl = (exit_price - entry_price) * paired_qty
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            else:
                pnl = 0.0
                pnl_pct = 0.0

            holding_days = _date_diff(t.get("date", ""), buy.get("date", ""))

            pairs.append({
                "entry_date": buy.get("date", "N/A"),
                "exit_date": t.get("date", "N/A"),
                "entry_price": round(entry_price, 4),
                "exit_price": round(exit_price, 4),
                "quantity": paired_qty,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "holding_days": holding_days,
                "direction": "做多",
            })

    return pairs

def _compute_pnl_distribution(pairs: List[dict]) -> dict:
    """
    从配对交易列表计算盈亏分布统计。

    返回
    -------
    dict
        {
            "total_trades": int,
            "winning_trades": int, "losing_trades": int,
            "win_rate": str ("66.67%"),
            "avg_win": float, "avg_loss": float,
            "avg_win_pct": str, "avg_loss_pct": str,
            "profit_loss_ratio": str ("2.50"),
            "max_win": float, "max_loss": float,
            "total_pnl": float,
            "avg_pnl": float,
        }
    """
    winning = [p for p in pairs if p.get("pnl", 0) > 0]
    losing = [p for p in pairs if p.get("pnl", 0) <= 0]

    total = len(pairs)
    wins = len(winning)
    losses = len(losing)

    avg_win = sum(p["pnl"] for p in winning) / wins if wins > 0 else 0.0
    avg_loss = sum(p["pnl"] for p in losing) / losses if losses > 0 else 0.0
    avg_win_pct = sum(p["pnl_pct"] for p in winning) / wins if wins > 0 else 0.0
    avg_loss_pct = sum(p["pnl_pct"] for p in losing) / losses if losses > 0 else 0.0

    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    win_rate = (wins / total * 100) if total > 0 else 0.0
    total_pnl = sum(p["pnl"] for p in pairs)
    avg_pnl = total_pnl / total if total > 0 else 0.0

    return {
        "total_trades": total,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": f"{win_rate:.2f}%",
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_win_pct": f"{avg_win_pct:.2f}%",
        "avg_loss_pct": f"{avg_loss_pct:.2f}%",
        "profit_loss_ratio": f"{profit_loss_ratio:.2f}",
        "max_win": round(max(p["pnl"] for p in winning), 2) if winning else 0.0,
        "max_loss": round(min(p["pnl"] for p in losing), 2) if losing else 0.0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
    }

def _flatten_trades_by_strategy(trades_data: dict) -> List[dict]:
    """
    将 trades.by_strategy 展开为扁平列表，补充 strategy 字段。
    用于 {{#each weekly.trades}} 循环。

    输入: {"trend": [{"date":..., "side":..., ...}], "reversal": [...]}
    输出: [{"strategy":"trend", "date":..., "side":..., ...}, ...]
    """
    flat = []
    by_strategy = trades_data.get("by_strategy", {})
    for strategy_name, trade_list in by_strategy.items():
        for trade in trade_list:
            flat.append({"strategy": strategy_name, **trade})
    return flat

def _render_simple_variable(text: str, data: dict) -> str:
    """
    渲染单行文本中的 {{path}} 变量（非块级指令）。

    不处理 {{#each}} {{/each}} {{#if}} {{/if}} —— 这些由块级处理器处理。
    """

    def replacer(m: re.Match) -> str:
        var_path = m.group(1).strip()

        # 跳过块级指令（each/if 内容）
        if var_path.startswith("#") or var_path.startswith("/"):
            return m.group(0)

        value = _resolve_path(data, var_path)
        return _format_value(value)

    return _VAR_RE.sub(replacer, text)

def _find_blocks(text: str, data: dict, block_re: Pattern) -> str:
    """
    递归处理模板中的块级指令（#each, #if）。

    按最内层优先处理：一旦匹配到可展开的块，就替换其结果，
    然后重新扫描，直到所有块都被展开。
    """
    result = text

    for _ in range(100):  # 安全上限，防止无限递归
        match = block_re.search(result)
        if not match:
            break

        directive = match.group(1)  # "each" 或 "if"
        block_path = match.group(2).strip()  # 路径
        block_body = match.group(3)  # 块内文本
        closing_directive = match.group(4)

        if directive != closing_directive:
            # 标签不匹配，跳过
            continue

        replacement = ""

        if directive == "each":
            # 特殊处理: weekly.trades 需要展平
            if block_path in ("weekly.trades", "trades.by_strategy"):
                items = _flatten_trades_by_strategy(
                    _resolve_path(data, "trades") or {}
                )
            else:
                items = _resolve_path(data, block_path)

            if items is not None and isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        # 替换块内 {{this.field}} 语法
                        item_text = _THIS_VAR_RE.sub(
                            lambda m: _format_value(
                                item.get(m.group(1), MISSING_PLACEHOLDER)
                            ),
                            block_body,
                        )
                        # 也替换 {{field}} 语法（当 item 直接可用时）
                        item_text = _render_simple_variable(item_text, item)
                    else:
                        # 简单值列表
                        item_text = block_body.replace("{{this}}", _format_value(item))
                    replacement += item_text
            else:
                replacement = f"*[no data: {block_path}]*"

        elif directive == "if":
            value = _resolve_path(data, block_path)
            condition_met = bool(value) and value != 0 and value != ""
            if condition_met:
                replacement = block_body
            # else: 空字符串

        result = result[: match.start()] + replacement + result[match.end():]

    return result

def _render_template(template_text: str, data: dict) -> str:
    """
    完整的模板渲染流水线。

    1. 递归展开块级指令（#each, #if）
    2. 替换普通变量（{{path}}）
    """
    text = _find_blocks(template_text, data, _BLOCK_RE)
    text = _render_simple_variable(text, data)
    return text

def _load_template(template_name: str) -> str:
    """从 templates/ 目录加载模板文件。"""
    template_path = os.path.join(TEMPLATE_DIR, template_name)
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

def _now_beijing() -> str:
    """返回当前北京时间 ISO 8601 字符串。"""
    beijing = SHANGHAI_TZ
    return datetime.now(beijing).strftime("%Y-%m-%d %H:%M:%S")

# ═══════════════════════════════════════════════════════════════
# ReportRenderer
# ═══════════════════════════════════════════════════════════════

class ReportRenderer:
    """
    报告渲染器。

    用法::

        renderer = ReportRenderer()
        md = renderer.render_daily(daily_data)
        md = renderer.render_weekly(weekly_data)

    template variables for strategy params:
        strategy_params (见 data 中传入):
            {
                "trend": {...},
                "reversal": {...},
                "grid": {...},
                "multi_runner": {...},
            }
        若未传入，使用 DEFAULT_STRATEGY_PARAMS。
    """

    # ── 日报渲染 ────────────────────────────────────────────

    def render_daily(self, data: dict) -> str:
        """
        将 DailyReportExtractor.extract_daily() 的输出渲染到日报模板。

        参数
        ----------
        data : dict
            DailyReportExtractor 输出的结构化日报数据。

        返回
        -------
        str
            已填充模板的 Markdown 字符串。
        """
        template = _load_template("daily.md")

        # 补充模板需要的额外字段（来自 extractor 但未直接对齐模板变量名）
        enhanced_data = self._enrich_daily_data(data)

        return _render_template(template, enhanced_data)

    @staticmethod
    def _enrich_daily_data(data: dict) -> dict:
        """
        为日报数据补充模板所需但 extractor 未直接提供的字段。

        extractor 输出的是回测内部数据结构，而日报模板使用了
        更偏向于真实交易监控的字段名。此处做桥接映射。
        """
        enriched = dict(data)

        # ── 市场指数占位符（回测中无此数据，留空） ──────────
        enriched.setdefault("market", {
            "index": {"sh": MISSING_PLACEHOLDER, "sz": MISSING_PLACEHOLDER},
            "price": MISSING_PLACEHOLDER,
            "chg_range": MISSING_PLACEHOLDER,
        })

        # ── 信号方向推导 ────────────────────────────────────
        signals = enriched.get("signals", {})
        strategies = signals.get("strategies", {})
        for name, sig in strategies.items():
            if isinstance(sig, dict):
                sig_val = sig.get("signal", 0)
                if sig_val > 0:
                    sig["direction"] = "做多"
                elif sig_val < 0:
                    sig["direction"] = "做空"
                else:
                    sig["direction"] = "空仓"

        # ── 冲突标记 ────────────────────────────────────────
        conflicts = signals.get("conflicts", [])
        enriched["conflict_flag"] = "⚠️ 有冲突" if conflicts else "✅ 无冲突"

        # ── 持仓/头寸数据（回测 extractor 无此字段，默认占位） ─
        positions = {}
        for name in strategies:
            positions[name] = {
                "holdings": MISSING_PLACEHOLDER,
                "market_value": MISSING_PLACEHOLDER,
                "capital_used": MISSING_PLACEHOLDER,
                "pnl": MISSING_PLACEHOLDER,
            }
        positions["total"] = {
            "market_value": MISSING_PLACEHOLDER,
            "capital_used": MISSING_PLACEHOLDER,
            "pnl": MISSING_PLACEHOLDER,
        }
        enriched["positions"] = positions

        # ── 策略净值桥接 ────────────────────────────────────
        equities = enriched.get("equities", {})
        per_strategy = equities.get("per_strategy", {})
        equity_section = {}
        for name in strategies:
            eq = per_strategy.get(name, 0)
            # 从 metrics 中获取夏普数据
            metrics_q = enriched.get("metrics", {})
            rolling_sharpe = metrics_q.get("rolling_sharpe", {})
            equity_section[name] = {
                "value": round(eq, 2) if isinstance(eq, (int, float)) else MISSING_PLACEHOLDER,
                "daily_return": f"{equities.get('daily_return_pct', 0):.4f}%",
                "cumulative": f"{equities.get('cumulative_return_pct', 0):.4f}%",
                "sharpe_20d": _format_value(rolling_sharpe.get("20d", MISSING_PLACEHOLDER)),
            }

        combined_eq = equities.get("combined", 0)
        equity_section["combined"] = {
            "value": round(combined_eq, 2) if isinstance(combined_eq, (int, float)) else MISSING_PLACEHOLDER,
            "daily_return": f"{equities.get('daily_return_pct', 0):.4f}%",
            "cumulative": f"{equities.get('cumulative_return_pct', 0):.4f}%",
            "sharpe_20d": _format_value(
                enriched.get("metrics", {}).get("rolling_sharpe", {}).get("20d", MISSING_PLACEHOLDER)
            ),
        }
        enriched["equity"] = equity_section

        # ── 风控数据占位 ────────────────────────────────────
        metrics = enriched.get("metrics", {})
        enriched["risk"] = {
            "max_drawdown": f"{metrics.get('max_drawdown_pct', 0):.2f}%",
            "drawdown_limit": MISSING_PLACEHOLDER,
            "drawdown_status": MISSING_PLACEHOLDER,
            "capital_usage": MISSING_PLACEHOLDER,
            "capital_limit": MISSING_PLACEHOLDER,
            "capital_status": MISSING_PLACEHOLDER,
            "concentration": MISSING_PLACEHOLDER,
            "concentration_limit": MISSING_PLACEHOLDER,
            "concentration_status": MISSING_PLACEHOLDER,
            "var_95": MISSING_PLACEHOLDER,
        }

        # ── 事件与建议占位 ──────────────────────────────────
        enriched["events"] = MISSING_PLACEHOLDER
        enriched["recommendations"] = MISSING_PLACEHOLDER

        # ── 逐笔交易明细（从全量回测结果计算） ───────────
        # daily extractor 只提供当日交易，所以配对只在当日有 BUY+SELL 时有效
        trades_data = enriched.get("trades", {})
        by_strategy = trades_data.get("by_strategy", {})
        all_trade_pairs = []
        all_pnl_stats = {}
        trade_pairs_by_strategy = {}

        for strat_name, trade_list in by_strategy.items():
            pairs = _pair_trades(trade_list)
            if pairs:
                for p in pairs:
                    p["strategy"] = strat_name
                trade_pairs_by_strategy[strat_name] = pairs
                all_trade_pairs.extend(pairs)
                strat_pnl = _compute_pnl_distribution(pairs)
                strat_pnl["strategy"] = strat_name
                all_pnl_stats[strat_name] = strat_pnl

        if all_trade_pairs:
            enriched["trade_pairs"] = all_trade_pairs
            enriched["trade_pairs_by_strategy"] = trade_pairs_by_strategy
            enriched["pnl_stats"] = {
                "per_strategy": all_pnl_stats,
                "combined": _compute_pnl_distribution(all_trade_pairs),
            }
        else:
            # 无可用交易配对时仍创建占位结构，模板中通过 {{#if pnl_stats}} 判断
            enriched["trade_pairs"] = []
            enriched["trade_pairs_by_strategy"] = {}
            enriched["pnl_stats"] = {}

        # ── 策略参数配置块 ──────────────────────────────────
        params = enriched.get("strategy_params", DEFAULT_STRATEGY_PARAMS)
        enriched["strategy_params"] = params

        # ── 生成时间 ────────────────────────────────────────
        enriched["generated_time"] = _now_beijing()

        return enriched

    # ── 周报渲染 ────────────────────────────────────────────

    def render_weekly(self, data: dict) -> str:
        """
        将 WeeklyReportExtractor.extract_weekly() 的输出渲染到周报模板。

        参数
        ----------
        data : dict
            WeeklyReportExtractor 输出的结构化周报数据。

        返回
        -------
        str
            已填充模板的 Markdown 字符串。
        """
        template = _load_template("weekly.md")

        enhanced_data = self._enrich_weekly_data(data)

        return _render_template(template, enhanced_data)

    @staticmethod
    def _enrich_weekly_data(data: dict) -> dict:
        """
        为周报数据补充模板所需但 extractor 未直接提供的字段。
        """
        enriched = dict(data)

        # ── 周范围 ─────────────────────────────────────────
        week_start = enriched.get("week_start", "")
        week_end = enriched.get("week_end", "")
        enriched["week_range"] = f"{week_start} ~ {week_end}"

        # ── 市场占位符 ─────────────────────────────────────
        enriched.setdefault("market", {
            "sh": {"this_week": MISSING_PLACEHOLDER, "last_week": MISSING_PLACEHOLDER, "change": MISSING_PLACEHOLDER},
            "price": {"this_week": MISSING_PLACEHOLDER, "last_week": MISSING_PLACEHOLDER, "change": MISSING_PLACEHOLDER},
            "volume": MISSING_PLACEHOLDER,
        })

        # ── 周度策略表现汇总桥接 ──────────────────────────
        summary = enriched.get("summary", {})
        per_strategy = summary.get("per_strategy", {})

        weekly_section: Dict[str, Any] = {}
        for name in ("trend", "reversal", "grid"):
            s = per_strategy.get(name, {})
            monthly = enriched.get("monthly_cumulative", {}).get("per_strategy", {})
            win_rate = enriched.get("win_rate", {})

            weekly_section[name] = {
                "return": f"{s.get('return_pct', 0):.2f}%",
                "mtd": f"{monthly.get(name, 0):.2f}%",
                "win_rate": f"{win_rate.get('daily_win_rate_pct', 0):.2f}%",
                "sharpe": MISSING_PLACEHOLDER,
                "last_sharpe": MISSING_PLACEHOLDER,
                "sharpe_change": MISSING_PLACEHOLDER,
            }

        combined_summary = summary.get("combined", {})
        weekly_section["combined"] = {
            "return": f"{combined_summary.get('return_pct', 0):.2f}%",
            "mtd": f"{enriched.get('monthly_cumulative', {}).get('cumulative_return_pct', 0):.2f}%",
            "win_rate": f"{enriched.get('win_rate', {}).get('daily_win_rate_pct', 0):.2f}%",
        }

        # 展平周交易（用于 #each 循环）
        weekly_section["trades"] = _flatten_trades_by_strategy(
            enriched.get("trades", {})
        )

        enriched["weekly"] = weekly_section

        # ── 持仓周变化 ─────────────────────────────────────
        holdings = enriched.get("holdings", {})
        per_strategy_holdings = holdings.get("per_strategy", {})

        holdings_section: Dict[str, Any] = {}
        for name in ("trend", "reversal", "grid"):
            h = per_strategy_holdings.get(name, {})
            positions_data = h.get("positions", {})
            position_count = len(positions_data) if isinstance(positions_data, dict) else 0

            holdings_section[name] = {
                "last_week": MISSING_PLACEHOLDER,
                "this_week": f"{position_count}只" if position_count > 0 else MISSING_PLACEHOLDER,
                "change": MISSING_PLACEHOLDER,
            }
        enriched["holdings"] = holdings_section

        # ── 月累计收益桥接 ─────────────────────────────────
        monthly = enriched.get("monthly_cumulative", {})
        mtd_section: Dict[str, Any] = {}
        for name in ("trend", "reversal", "grid"):
            mtd_section[name] = {
                "return": f"{monthly.get('per_strategy', {}).get(name, 0):.2f}%",
                "max_dd": MISSING_PLACEHOLDER,
                "trades": MISSING_PLACEHOLDER,
            }
        mtd_section["combined"] = {
            "return": f"{monthly.get('cumulative_return_pct', 0):.2f}%",
            "max_dd": MISSING_PLACEHOLDER,
        }
        enriched["mtd"] = mtd_section

        # ── 年度累计 ───────────────────────────────────────
        ytd_section: Dict[str, Any] = {}
        for name in ("trend", "reversal", "grid"):
            ytd_section[name] = {"return": MISSING_PLACEHOLDER}
        ytd_section["combined"] = {"return": MISSING_PLACEHOLDER}
        enriched["ytd"] = ytd_section

        # ── 资金分配状态桥接 ──────────────────────────────
        allocation_section: Dict[str, Any] = {}
        for name in ("trend", "reversal", "grid"):
            allocation_section[name] = {
                "current": MISSING_PLACEHOLDER,
                "target": MISSING_PLACEHOLDER,
                "deviation": MISSING_PLACEHOLDER,
                "action": MISSING_PLACEHOLDER,
            }

        # 从 metrics 中提取实际分配数据
        metrics = enriched.get("metrics", {})
        if metrics:
            allocation_raw = metrics.get("allocation", {})
            if allocation_raw:
                weights = allocation_raw.get("weights", {})
                mode = allocation_raw.get("mode", "equal")
                for name in ("trend", "reversal", "grid"):
                    w = weights.get(name, 0)
                    if isinstance(w, (int, float)):
                        allocation_section[name] = {
                            "current": f"{w*100:.1f}%",
                            "target": f"({mode})",
                            "deviation": MISSING_PLACEHOLDER,
                            "action": "维持" if mode == "equal" else MISSING_PLACEHOLDER,
                        }
        enriched["allocation"] = allocation_section

        # ── 风控评估桥接 ─────────────────────────────────
        enriched["risk"] = {
            "drawdown_status": MISSING_PLACEHOLDER,
            "drawdown_value": f"{abs(metrics.get('max_drawdown_pct', 0)):.2f}%"
                if metrics else MISSING_PLACEHOLDER,
            "drawdown_margin": MISSING_PLACEHOLDER,
            "loss_streak_status": MISSING_PLACEHOLDER,
            "trend_loss_streak": MISSING_PLACEHOLDER,
            "reversal_loss_streak": MISSING_PLACEHOLDER,
            "grid_loss_streak": MISSING_PLACEHOLDER,
            "sharpe_trend_status": MISSING_PLACEHOLDER,
            "sharpe_trend_detail": MISSING_PLACEHOLDER,
            "capital_usage_status": MISSING_PLACEHOLDER,
            "capital_usage_detail": MISSING_PLACEHOLDER,
        }

        # ── 展望与决策占位 ─────────────────────────────────
        enriched["outlook"] = MISSING_PLACEHOLDER
        enriched["decisions"] = MISSING_PLACEHOLDER

        # ── 逐笔交易明细（entry→exit 配对 + 盈亏分布） ──
        trades_data = enriched.get("trades", {})
        by_strategy = trades_data.get("by_strategy", {})
        all_trade_pairs = []
        all_pnl_stats = {}
        trade_pairs_by_strategy = {}

        for strat_name, trade_list in by_strategy.items():
            pairs = _pair_trades(trade_list)
            if pairs:
                for p in pairs:
                    p["strategy"] = strat_name
                trade_pairs_by_strategy[strat_name] = pairs
                all_trade_pairs.extend(pairs)
                all_pnl_stats[strat_name] = _compute_pnl_distribution(pairs)

        if all_trade_pairs:
            enriched["trade_pairs"] = all_trade_pairs
            enriched["trade_pairs_by_strategy"] = trade_pairs_by_strategy
            enriched["pnl_stats"] = {
                "per_strategy": all_pnl_stats,
                "combined": _compute_pnl_distribution(all_trade_pairs),
            }
            # 设置周报模板所需字段
            enriched["has_trade_pairs"] = True
        else:
            enriched["trade_pairs"] = []
            enriched["trade_pairs_by_strategy"] = {}
            enriched["pnl_stats"] = {}
            enriched["has_trade_pairs"] = False

        # ── 策略参数配置块 ──────────────────────────────────
        params = enriched.get("strategy_params", DEFAULT_STRATEGY_PARAMS)
        enriched["strategy_params"] = params

        # ── 生成时间 ───────────────────────────────────────
        enriched["generated_time"] = _now_beijing()

        return enriched

# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def render_daily_report(data: dict) -> str:
    """便捷函数：渲染日报。"""
    return ReportRenderer().render_daily(data)

def render_weekly_report(data: dict) -> str:
    """便捷函数：渲染周报。"""
    return ReportRenderer().render_weekly(data)

# ═══════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 日报自测
    sample_daily: dict = {
        "date": "20260515",
        "symbol": "601857.SH",
        "signals": {
            "strategies": {
                "trend": {"signal": 1, "strength": 0.8, "price": 12.5, "quantity": 1000},
                "reversal": {"signal": 0, "strength": 0.0, "price": 12.5, "quantity": 0},
                "grid": {"signal": -1, "strength": 1.0, "price": 12.5, "quantity": 500},
            },
            "conflicts": [
                {"pair": ["trend", "grid"], "direction_1": 1, "direction_2": -1,
                 "price": 12.5, "resolved": True, "resolved_direction": 1},
            ],
            "total_signal_count": 3,
        },
        "trades": {
            "by_strategy": {
                "trend": [{"date": "20260515", "side": "BUY", "price": 12.5,
                           "quantity": 1000, "fee": 5.0, "slippage": 0.01, "order_type": "MARKET"}],
            },
            "summary": {"total_trades": 1, "total_buy_volume": 1000,
                        "total_sell_volume": 0, "total_fee": 5.0},
        },
        "equities": {
            "per_strategy": {"trend": 1050000.0, "reversal": 1020000.0, "grid": 1005000.0},
            "combined": 3075000.0,
            "daily_return_pct": 0.25,
            "cumulative_return_pct": 5.35,
        },
        "metrics": {
            "rolling_sharpe": {"5d": 1.5, "20d": 1.2, "60d": 0.9},
            "max_drawdown_pct": -8.5,
            "total_return_pct": 12.3,
            "annualized_return_pct": 8.5,
            "overall_sharpe": 1.25,
            "allocation": {"weights": {"trend": 0.34, "reversal": 0.33, "grid": 0.33}, "mode": "equal"},
        },
    }

    renderer = ReportRenderer()
    md_daily = renderer.render_daily(sample_daily)
    print("=" * 60)
    print("DAILY REPORT")
    print("=" * 60)
    print(md_daily[:2000])
    print("... (truncated)")

    # 周报自测
    sample_weekly: dict = {
        "week_start": "20260511",
        "week_end": "20260517",
        "symbol": "601857.SH",
        "trading_days_in_week": 5,
        "summary": {
            "per_strategy": {
                "trend": {"return_pct": 1.25, "prev_return_pct": 0.85, "change_pct": 0.40},
                "reversal": {"return_pct": 0.85, "prev_return_pct": 0.65, "change_pct": 0.20},
                "grid": {"return_pct": 0.50, "prev_return_pct": 0.40, "change_pct": 0.10},
            },
            "combined": {"return_pct": 0.87, "prev_return_pct": 0.63, "change_pct": 0.23},
            "weekly_return_pct": 0.87,
            "prev_weekly_return_pct": 0.63,
            "week_over_week_change": 0.23,
        },
        "trades": {
            "by_strategy": {
                "trend": [
                    {"date": "20260511", "side": "BUY", "price": 12.5, "quantity": 1000,
                     "fee": 5.0, "slippage": 0.01, "order_type": "MARKET"},
                ],
                "grid": [
                    {"date": "20260513", "side": "SELL", "price": 12.8, "quantity": 500,
                     "fee": 3.0, "slippage": 0.02, "order_type": "LIMIT"},
                ],
            },
            "summary": {"total_trades": 2, "buy_trades": 1, "sell_trades": 1,
                        "total_volume": 1500, "total_fee": 8.0},
        },
        "daily_details": [
            {"date": "20260511", "combined_equity": 1005000.0, "daily_return_pct": 0.15, "trend": 505000.0, "reversal": 300000.0, "grid": 200000.0},
        ],
        "win_rate": {
            "daily_win_rate_pct": 60.0, "winning_days": 3, "losing_days": 2,
            "total_days": 5, "best_day_pct": 1.25, "worst_day_pct": -0.85, "avg_daily_return_pct": 0.15,
        },
        "monthly_cumulative": {
            "month_start": "20260501",
            "cumulative_return_pct": 2.35,
            "per_strategy": {"trend": 2.80, "reversal": 1.50, "grid": 2.10},
        },
        "holdings": {
            "per_strategy": {
                "trend": {
                    "positions": {"003816.SZ": {"quantity": 40000, "avg_cost": 12.5}},
                    "total_position_value": 500000.0,
                    "available_cash": 505000.0,
                    "total_equity": 1005000.0,
                },
            },
            "combined_summary": {
                "total_position_value": 500000.0,
                "total_equity": 1005000.0,
                "position_ratio_pct": 49.75,
            },
        },
        "conflicts": [],
    }

    md_weekly = renderer.render_weekly(sample_weekly)
    print("=" * 60)
    print("WEEKLY REPORT")
    print("=" * 60)
    print(md_weekly[:2000])
    print("... (truncated)")

    print("\n✅ ReportRenderer self-test passed.")
