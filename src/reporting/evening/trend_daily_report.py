#!/usr/bin/env python3
from src.config import SHANGHAI_TZ
"""
trend_daily_report.py — Phase 1: 趋势账户日报生成器
作者：墨衡 (moheng)
创建时间：2026-05-13T14:17+08:00
版本：v1.0

功能：
1. 汇总趋势账户当日状态并生成人类可读报告
2. 报告内容：趋势分数、仓位状态、当日信号、持仓汇总、资金概览

数据源：
- trade_engine.db → account_balance, positions, transactions
- analysis.db    → tech_indicators (trend_score)

调用方式：
    from automation_v2.phase1_core.trend_daily_report import generate_trend_daily_report
    report = generate_trend_daily_report()
    print(report)
"""

import json
import os
import sqlite3
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# ── 系统路径注入 ──
_AUTO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AUTO_DIR not in sys.path:
    sys.path.insert(0, _AUTO_DIR)

TZ = SHANGHAI_TZ

TRADE_DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"
ANALYSIS_DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\analysis.db"

ACCOUNT_ID = "acct_tech_trend"
SYMBOL = "601857"

# ── 研究层开关（可关闭降级） ──
ENABLE_RESEARCH_LAYER = True

# 趋势分数阈值（与 position_manager_v2 保持一致）
TREND_THRESHOLDS = {
    "EMERGENCY": (0, 45),
    "BASE":      (45, 55),
    "ENHANCED":  (55, 65),
    "STRONG_BUY":(65, 75),
    "CHASING":   (75, 100),
}

TREND_LABELS = {
    "EMERGENCY":  "紧急减仓区",
    "BASE":       "基础仓位",
    "ENHANCED":   "加仓区",
    "STRONG_BUY": "强买入区",
    "CHASING":    "追涨加仓区",
}

TREND_TARGET_PCT = {
    "EMERGENCY":  0.30,
    "BASE":       0.30,
    "ENHANCED":   0.45,  # 中值
    "STRONG_BUY": 0.60,
    "CHASING":    0.70,
}

def _get_db_conn(db_path: str) -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def _classify_score(score: float) -> Tuple[str, float]:
    """
    根据趋势分数确定状态和目标仓位

    Args:
        score: 趋势分数 (0-100)

    Returns:
        (state_name, target_position_pct)
    """
    for state, (lo, hi) in TREND_THRESHOLDS.items():
        if lo <= score < hi:
            return state, TREND_TARGET_PCT[state]
    return "BASE", 0.30

def _determine_signal(trend_score: float, state: str,
                      current_pct: float, target_pct: float) -> Tuple[str, str]:
    """
    根据趋势分数和仓位对比确定当日信号

    Args:
        trend_score: 当前趋势分数
        state: 状态名
        current_pct: 当前仓位百分比
        target_pct: 目标仓位百分比

    Returns:
        (action, reason)
    """
    if state == "EMERGENCY":
        return "SELL", f"分数{trend_score:.0f}<阈值45，触发紧急减仓"
    if state == "BASE":
        if current_pct > target_pct + 0.05:
            return "SELL", f"仓位{current_pct:.0%}超出基础上限{target_pct:.0%}，减仓"
        return "HOLD", f"基础区间{trend_score:.0f}/{45}-55)，观望"
    if state in ("ENHANCED", "STRONG_BUY", "CHASING"):
        if current_pct < target_pct - 0.03:
            return "BUY", f"分数{trend_score:.0f}≥阈值{TREND_THRESHOLDS[state][0]}，加仓至{target_pct:.0%}"
        if abs(current_pct - target_pct) <= 0.03:
            return "HOLD", f"仓位{current_pct:.0%}接近目标{target_pct:.0%}，维持"
        # current > target: 可能是衰减减仓中
        return "HOLD", f"仓位{current_pct:.0%}高于目标{target_pct:.0%}，等待回调"
    return "HOLD", "数据不足"

def _fmt_pnl(pnl_value: Optional[float]) -> str:
    """格式化盈亏"""
    if pnl_value is None:
        return "+0.00"
    return f"{'+' if pnl_value >= 0 else ''}{pnl_value:.2f}"

def _fmt_money(value: float) -> str:
    """格式化金额"""
    return f"{value:,.2f}"

# ════════════════════════════════════════════════════════════════
# Phase 2-2: 研究层集成函数
# ════════════════════════════════════════════════════════════════

def save_to_tech_signals(trade_signal_dict: Dict[str, Any], cursor: sqlite3.Cursor) -> bool:
    """
    将信号字典写入 tech_signals 表

    基础字段：task_id, code, date, action, confidence, suggested_price,
    position_ratio, quantity, reason, status, account_id

    新增研究字段 signal_hit/forward_return/market_regime 留 NULL（由
    signal_evaluator 和 market_regime_labeler 在后续运行时回填）。

    幂等保护：UNIQUE(code, date, task_id) 约束自动处理重复记录。
    INSERT OR IGNORE 在冲突时静默跳过。

    Args:
        trade_signal_dict: 信号字典
        cursor: 数据库游标

    Returns:
        True 表示成功写入新记录，False 表示已存在或因错误跳过
    """
    try:
        cursor.execute(
            """INSERT OR IGNORE INTO tech_signals
               (task_id, code, date, action, confidence, suggested_price,
                position_ratio, quantity, reason, status, account_id,
                trend_score, current_position_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_signal_dict["task_id"],
                trade_signal_dict["code"],
                trade_signal_dict["date"],
                trade_signal_dict["action"],
                trade_signal_dict.get("confidence", "中"),
                trade_signal_dict.get("suggested_price"),
                trade_signal_dict.get("position_ratio"),
                trade_signal_dict.get("quantity"),
                trade_signal_dict.get("reason", ""),
                trade_signal_dict.get("status", "READY"),
                trade_signal_dict.get("account_id", ACCOUNT_ID),
                trade_signal_dict.get("trend_score"),
                trade_signal_dict.get("current_position_pct"),
            )
        )
        if cursor.rowcount == 0:
            logger.info(f"[trend_daily] 信号已存在（幂等跳过）: {trade_signal_dict.get('task_id')}")
            return False
        logger.info(f"[trend_daily] 信号已写入 tech_signals: {trade_signal_dict.get('task_id')}")
        return True
    except sqlite3.IntegrityError:
        logger.info(f"[trend_daily] 信号已存在（IntegrityError 跳过）: {trade_signal_dict.get('task_id')}")
        return False
    except Exception as e:
        logger.error(f"[trend_daily] 写入 tech_signals 失败: {e}")
        return False

def run_research_pipeline(db_conn: sqlite3.Connection,
                          trade_signal_dict: Dict[str, Any],
                          today: str,
                          signal_type: str = "trend") -> Dict[str, Any]:
    """
    组合研究层调用链

    流程：
      1. 写入 tech_signals 表（save_to_tech_signals）
      2. 通过 SignalRateLimiter 限流（仅记录，不阻止）
      3. 通过 signal_conflict_logger 检测与反转/网格信号的冲突
         （grid_action 暂传 None，表示网格信号尚未生成）
      4. 通过 signal_evaluator.backfill_forward_returns 回填前向收益率
      5. 通过 market_regime_labeler.label_market_regime 标注市场环境

    Args:
        db_conn: trade_engine.db 的 sqlite3 连接
        trade_signal_dict: 信号字典
        today: 信号日期 YYYY-MM-DD

    Returns:
        {
            "status": "OK" | "PARTIAL",
            "saved": bool,
            "rate_limited": bool,
            "rate_reason": str,
            "conflict_id": int | None,
            "evaluator_result": dict | None,   # backfill_forward_returns 结果
            "regime_result": dict | None,       # label_market_regime 结果
        }
    """
    result: Dict[str, Any] = {
        "status": "OK",
        "saved": False,
        "rate_limited": False,
        "rate_reason": "",
        "conflict_id": None,
        "evaluator_result": None,    # Phase 2-3: signal_evaluator 回填结果
        "regime_result": None,       # Phase 2-3: market_regime 标注结果
    }

    # ── 第0步：如果动作是 HOLD，跳过写入和研究层（HOLD 不视为信号） ──
    action = trade_signal_dict.get("action", "")
    if action.upper() == "HOLD":
        logger.info(f"[trend_daily] 信号为 HOLD，跳过研究层写入: {trade_signal_dict.get('task_id')}")
        return result

    # ── 第1步：写入 tech_signals 表 ──
    try:
        cursor = db_conn.cursor()
        saved = save_to_tech_signals(trade_signal_dict, cursor)
        db_conn.commit()
        result["saved"] = saved
    except Exception as e:
        logger.error(f"[trend_daily] 研究层-写入 tech_signals 异常: {e}")
        result["status"] = "PARTIAL"

    # ── 第2步：SignalRateLimiter（仅记录，不阻止） ──
    try:
        from phase1_core.signal_rate_limiter import SignalRateLimiter
        limiter = SignalRateLimiter()
        allowed, reason = limiter.check_and_throttle(trade_signal_dict.get("code", SYMBOL))
        if not allowed:
            result["rate_limited"] = True
            result["rate_reason"] = reason
            logger.info(f"[trend_daily] 信号被限流（仅记录，不阻止）: {reason}")
    except Exception as e:
        logger.warning(f"[trend_daily] 研究层-限流检查异常: {e}")

    # ── 第3步：信号冲突检测（与对侧信号对比） ──
    try:
        from phase1_core.signal_conflict_logger import log_signal_conflict

        # 将 BUY_TO_OPEN/SELL_TO_CLOSE 等映射为 BUY/SELL/None
        raw_action = trade_signal_dict.get("action", "")
        if raw_action.upper() in ("BUY", "BUY_TO_OPEN"):
            parsed_action = "BUY"
        elif raw_action.upper() in ("SELL", "SELL_TO_CLOSE"):
            parsed_action = "SELL"
        else:
            parsed_action = None

        if signal_type == "reversal":
            # 反转信号运行时：检测与已存在的趋势信号冲突
            conflict_id = log_signal_conflict(
                db_conn,
                code=trade_signal_dict.get("code", SYMBOL),
                date=trade_signal_dict.get("date", today),
                trend_action=None,         # 由趋势信号模块独立写入
                reversal_action=parsed_action,
                grid_action=None,
            )
        else:
            # 趋势信号运行时：检测与已存在的反转/网格信号冲突
            conflict_id = log_signal_conflict(
                db_conn,
                code=trade_signal_dict.get("code", SYMBOL),
                date=trade_signal_dict.get("date", today),
                trend_action=parsed_action,
                reversal_action=None,      # 由反转信号模块独立写入
                grid_action=None,          # 网格信号尚未生成
            )
        result["conflict_id"] = conflict_id
    except Exception as e:
        logger.warning(f"[trend_daily] 研究层-冲突检测异常: {e}")

    # ── 第4步：前向收益率回填（signal_evaluator） ──
    try:
        from phase1_core.signal_evaluator import backfill_forward_returns
        eval_result = backfill_forward_returns(db_conn, today)
        result["evaluator_result"] = eval_result
        logger.info(f"[trend_daily] 前向收益率回填完成: "
                     f"{json.dumps(eval_result, ensure_ascii=False)}")
    except Exception as e:
        logger.warning(f"[trend_daily] 前向收益率回填异常: {e}")
        result["evaluator_result"] = {"status": "FAILED", "error": str(e)}

    # ── 第5步：市场环境标注（market_regime_labeler） ──
    try:
        from phase1_core.market_regime_labeler import label_market_regime
        regime_result = label_market_regime(db_conn, today)
        result["regime_result"] = regime_result
        logger.info(f"[trend_daily] 市场环境标注完成: "
                     f"{json.dumps(regime_result, ensure_ascii=False)}")
    except Exception as e:
        logger.warning(f"[trend_daily] 市场环境标注异常: {e}")
        result["regime_result"] = {"status": "FAILED", "error": str(e)}

    return result

def generate_trend_daily_report(account_id: str = ACCOUNT_ID) -> str:
    """
    生成当日趋势账户状态报告

    报告内容：
    1. 趋势分数（当前值、5日均值、上一日值）
    2. 仓位状态（当前仓位%、五态状态名、目标仓位%）
    3. 当日信号（BUY/HOLD/SELL 及触发原因）
    4. 持仓汇总（标的、数量、均价、盈亏）
    5. 资金概览（总资产、可用、冻结）

    Args:
        account_id: 账户ID，默认为 'acct_tech_trend'

    Returns:
        格式化的人类可读报告字符串
    """
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    lines = []
    lines.append(f"=== {account_id} 趋势账户日报 | {today} ===")
    lines.append("")

    # ──── 1. 查询资金账户 ────
    conn_trade = _get_db_conn(TRADE_DB_PATH)
    try:
        cursor = conn_trade.execute(
            "SELECT total_assets, available_balance, frozen_amount, "
            "       position_market_value, initial_capital, realized_pnl "
            "FROM account_balance WHERE account_id = ?",
            (account_id,)
        )
        account = cursor.fetchone()
    finally:
        conn_trade.close()

    if not account:
        return f"错误：未找到账户 {account_id} 的资金信息"

    total_assets = account["total_assets"]
    available = account["available_balance"]
    frozen = account["frozen_amount"]
    position_market_value = account["position_market_value"]
    realized_pnl = account["realized_pnl"]

    position_pct = position_market_value / total_assets if total_assets > 0 else 0.0

    # ──── 2. 查询当前持仓（OPEN 且属于该账户） ────
    conn_trade2 = _get_db_conn(TRADE_DB_PATH)
    try:
        cursor = conn_trade2.execute(
            """SELECT p.symbol, p.quantity, p.entry_price, p.pnl, p.status
               FROM positions p
               WHERE p.account_id = ? AND p.status = 'OPEN'
               ORDER BY p.symbol""",
            (account_id,)
        )
        open_positions = [dict(r) for r in cursor.fetchall()]
    finally:
        conn_trade2.close()

    # ──── 3. 查询趋势分数（从 analysis.db） ────
    conn_ana = _get_db_conn(ANALYSIS_DB_PATH)
    try:
        # 当日最新分数
        cursor = conn_ana.execute(
            """SELECT date, trend_score, trend_summary
               FROM tech_indicators
               WHERE code = ? AND trend_score IS NOT NULL
               ORDER BY date DESC LIMIT 5""",
            (SYMBOL,)
        )
        score_rows = [dict(r) for r in cursor.fetchall()]
    finally:
        conn_ana.close()

    # ──── 解析趋势分数数据 ────
    current_score: Optional[float] = None
    prev_score: Optional[float] = None
    score_5d_avg: Optional[float] = None
    trend_summary: Optional[str] = None

    if score_rows:
        latest = score_rows[0]
        current_score = latest["trend_score"]
        trend_summary = latest.get("trend_summary", "")

        if len(score_rows) > 1:
            prev_score = score_rows[1]["trend_score"]

        scores = [r["trend_score"] for r in score_rows if r["trend_score"] is not None]
        if scores:
            score_5d_avg = sum(scores) / len(scores)

    # 如果没有当日分数，尝试查询当日 stock_daily 来判断是否有行情
    try:
        conn_ana2 = _get_db_conn(ANALYSIS_DB_PATH)
        cursor = conn_ana2.execute(
            "SELECT date, close FROM stock_daily WHERE code = ? ORDER BY date DESC LIMIT 1",
            (SYMBOL,)
        )
        latest_kline = cursor.fetchone()
        conn_ana2.close()
        latest_market_date = latest_kline["date"] if latest_kline else None
    except Exception:
        latest_market_date = None

    # 从最新数据日期推断报告日期（若无当日数据则用数据库最新日）
    if score_rows:
        report_data_date = score_rows[0]["date"]
    elif latest_market_date:
        report_data_date = latest_market_date
    else:
        report_data_date = today

    # ──── 4. 生成报告 ────

    # --- 趋势分数 ---
    if current_score is not None:
        score_line = f"趋势分数：{current_score:.1f}"
        parts = []
        if score_5d_avg is not None:
            parts.append(f"5日均值: {score_5d_avg:.1f}")
        if prev_score is not None:
            diff = current_score - prev_score
            diff_str = f"{'+' if diff >= 0 else ''}{diff:.1f}"
            parts.append(f"上一日: {prev_score:.1f} ({diff_str})")
        if parts:
            score_line += f" ({' | '.join(parts)})"
        lines.append(score_line)
    else:
        lines.append(f"趋势分数：无数据（最新行情日期: {latest_market_date or '无'}）")

    # --- 仓位状态 ---
    state_name, target_pct = _classify_score(current_score) if current_score is not None else ("BASE", 0.30)
    state_label = TREND_LABELS.get(state_name, state_name)
    lines.append(
        f"仓位状态：{state_label} (目标仓位: {target_pct:.0%})"
    )

    # --- 信号 ---
    signal_action, signal_reason = _determine_signal(
        current_score or 50, state_name, position_pct, target_pct
    )
    lines.append(f"    → 信号: {signal_action} ({signal_reason})")

    # ── Phase 2-2: 研究层接入（生成信号后立即调用） ──
    if ENABLE_RESEARCH_LAYER:
        try:
            conn_rl = _get_db_conn(TRADE_DB_PATH)
            trade_signal_dict = {
                "task_id": f"trend_{report_data_date}_{SYMBOL}_{int(datetime.now(TZ).timestamp())}",
                "code": SYMBOL,
                "date": report_data_date,
                "action": signal_action,
                "confidence": "中",
                "suggested_price": latest_kline["close"] if latest_market_date else None,
                "position_ratio": target_pct,
                "quantity": None,
                "reason": signal_reason,
                "status": "READY",
                "account_id": account_id,
                "trend_score": current_score,
                "current_position_pct": position_pct,
            }
            pipeline_result = run_research_pipeline(conn_rl, trade_signal_dict, report_data_date)
            if pipeline_result.get("saved"):
                lines.append(f"    [研究层] 信号已写入 tech_signals")
            if pipeline_result.get("rate_limited"):
                lines.append(f"    [研究层] 限流记录: {pipeline_result['rate_reason'][:60]}")
            if pipeline_result.get("conflict_id") is not None:
                lines.append(f"    [研究层] 冲突记录 id={pipeline_result['conflict_id']}")
        except Exception as e:
            logger.warning(f"[trend_daily] 研究层调用失败（降级继续）: {e}")
        finally:
            try:
                conn_rl.close()
            except Exception:
                pass

    # --- 持仓 ---
    lines.append("")
    lines.append("持仓：")
    if open_positions:
        for pos in open_positions:
            symbol = pos.get("symbol", "?")
            qty = pos.get("quantity", 0)
            entry_price = pos.get("entry_price", 0.0)
            pnl = pos.get("pnl")
            market_value = qty * (latest_kline["close"] if latest_market_date else entry_price)
            lines.append(
                f"  {symbol} | {qty:,}股 @ {entry_price:.2f} | "
                f"盈亏: {_fmt_pnl(pnl)} | 市值: {_fmt_money(market_value)}"
            )
    else:
        lines.append("  无持仓")

    # --- 资金 ---
    lines.append("")
    lines.append("资金：")
    lines.append(
        f"  总资产: {_fmt_money(total_assets)} | "
        f"可用: {_fmt_money(available)} | "
        f"冻结: {_fmt_money(frozen)} | "
        f"仓位%: {position_pct:.1%}"
    )

    # --- 数据日期信息 ---
    lines.append("")
    if report_data_date != today:
        lines.append(f"[注] 趋势数据截至 {report_data_date}（非今日），最新行情日期 {latest_market_date}")

    return "\n".join(lines)

def main():
    """命令行入口"""
    import sys

    aid = sys.argv[1] if len(sys.argv) > 1 else ACCOUNT_ID
    report = generate_trend_daily_report(aid)
    print(report)

if __name__ == "__main__":
    main()
