# -*- coding: utf-8 -*-
from src.config import SHANGHAI_TZ
"""
risk_limits.py — Phase1d 风控规则模块

对信号和下单进行多维度风控校验，在 process_signal Step2 调用。

作者：墨衡 (moheng)
创建时间：2026-05-12 20:10 GMT+8
任务：P0-MX-001-Phase1d

校验维度:
  1. check_per_trade_limit — 单笔金额上限（默认10万）
  2. check_cool_down — 同symbol 5分钟间隔保护
  3. check_daily_pnl — 每日亏损上限（默认-5000元净盈亏）
  4. check_volatility — 大盘剧烈波动保护（>3%跳空暂停交易）

入口: check_all(signal, order_engine, config) → (reject, reasons)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Any

logger = logging.getLogger("paper_trade.risk_limits")

# ── 时区 ──
TZ_CST = SHANGHAI_TZ
DEFAULT_DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"

# ── 文件级默认实例（供模块函数复用）─
_DEFAULT_DB = DEFAULT_DB_PATH

# ============================================================
# RiskConfig — 风控阈值配置
# ============================================================

class RiskConfig:
    """风控阈值配置，所有阈值可通过实例化传入覆盖。"""

    def __init__(self, **kwargs):
        # 单笔金额上限
        self.max_order_amount = kwargs.get("max_order_amount", 100000.0)
        # 同symbol信号间隔（秒）
        self.cool_down_seconds = kwargs.get("cool_down_seconds", 300)
        # 每日净亏损上限（负值）
        self.max_daily_loss = kwargs.get("max_daily_loss", -5000.0)
        # 跳空暂停阈值
        self.volatility_gap = kwargs.get("volatility_gap", 0.03)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

# ============================================================
# 内部工具
# ============================================================

def _extract_db_path(order_engine) -> str:
    """从 order_engine 提取数据库路径。"""
    db = getattr(order_engine, "db_path", None)
    if db:
        return db
    am = getattr(order_engine, "am", None)
    if am:
        db = getattr(am, "db_path", None)
        if db:
            return db
    return DEFAULT_DB_PATH

def _get_balance_dict(order_engine) -> dict:
    """通过 order_engine 获取账户资金/持仓信息。"""
    am = getattr(order_engine, "am", None)
    if am and hasattr(am, "get_balance"):
        try:
            return am.get_balance()
        except Exception as e:
            logger.warning(f"[risk_limits] get_balance 失败: {e}")
    return {}

# ============================================================
# 检查函数
# ============================================================

def check_per_trade_limit(signal: dict, config: RiskConfig) -> Tuple[bool, str]:
    """单笔金额上限检查。

    估算本次交易金额 = suggested_price × qty_pct × 可用资金上限，
    无法准确获取可用资金时使用 initial_capital 作为参考基准。

    Returns:
        (ok: True 表示通过, reason: 否决原因或空串)
    """
    qty_pct = signal.get("qty_pct", 0.0)
    price = signal.get("suggested_price", 0.0)

    if not price or price <= 0 or qty_pct <= 0:
        return True, ""

    # 以 20 万初始资金为基准估算单笔占用金额
    # 若 signal 有 available_cash 字段，优先使用
    base_cash = signal.get("available_cash", 200000.0)
    estimated_amount = base_cash * qty_pct

    if estimated_amount > config.max_order_amount:
        return False, (
            f"单笔金额上限: 估算 {estimated_amount:.0f}元 "
            f"(本金×{qty_pct:.0%}) 超过上限 {config.max_order_amount:.0f}元"
        )
    return True, ""

def check_cool_down(symbol: str, order_engine, config: RiskConfig) -> Tuple[bool, str]:
    """同品种信号间隔保护。

    检查数据库中该品种最近一笔成交/交易时间，
    若距现在不足 config.cool_down_seconds 秒则否决。

    Returns:
        (ok: True 表示通过, reason: 否决原因或空串)
    """
    db_path = _extract_db_path(order_engine)

    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT MAX(trade_time) FROM transactions WHERE symbol = ?",
            (symbol,)
        ).fetchone()
        conn.close()

        if not row or not row[0]:
            return True, ""

        try:
            last_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                last_time = datetime.fromisoformat(row[0])
            except (ValueError, TypeError):
                return True, ""

        elapsed = (datetime.now() - last_time).total_seconds()
        if elapsed < config.cool_down_seconds:
            return False, (
                f"信号间隔: {symbol} 上次交易 {last_time.strftime('%H:%M:%S')}, "
                f"距现在 {elapsed:.0f}秒 < {config.cool_down_seconds}秒要求"
            )
        return True, ""

    except Exception as e:
        logger.warning(f"[risk_limits] check_cool_down DB 查询失败: {e}")
        return True, ""

def check_daily_pnl(order_engine, config: RiskConfig) -> Tuple[bool, str]:
    """每日亏损上限检查。

    通过查询今日交易记录的已成交盈亏判断当日净盈亏，
    低于 config.max_daily_loss 时暂停交易。

    Returns:
        (ok: True 表示通过, reason: 否决原因或空串)
    """
    db_path = _extract_db_path(order_engine)
    today = datetime.now(TZ_CST).strftime("%Y-%m-%d")

    try:
        conn = sqlite3.connect(db_path)
        # 从 transactions 计算今日已成交交易的净盈亏
        # 买入：-price*quantity (资金流出)
        # 卖出：+price*quantity (资金流入, 含盈亏)
        # 粗略净值通过 commission + tax 估算方向
        row = conn.execute(
            """SELECT COALESCE(SUM(
                CASE
                    WHEN action IN ('SELL','SELL_TO_CLOSE','SELL_TO_OPEN')
                    THEN price * quantity - commission - tax
                    WHEN action IN ('BUY','BUY_TO_OPEN','BUY_TO_CLOSE')
                    THEN -(price * quantity + commission + tax)
                    ELSE 0
                END
            ), 0) FROM transactions
            WHERE trade_time LIKE ? AND status IN ('FILLED','CONFIRMED')""",
            (f"{today}%",)
        ).fetchone()
        conn.close()

        today_pnl = float(row[0]) if row else 0.0

        if today_pnl <= config.max_daily_loss:
            return False, (
                f"每日亏损上限: 今日净盈亏 {today_pnl:.2f}元 "
                f"已达停损线 {config.max_daily_loss:.0f}元"
            )
        return True, ""

    except Exception as e:
        logger.warning(f"[risk_limits] check_daily_pnl 查询失败: {e}")
        return True, ""

def check_volatility(order_engine, config: RiskConfig) -> Tuple[bool, str]:
    """大盘剧烈波动保护。

    参考 price_utils 的波动率数据，检测是否出现 >3% 的跳空缺空。
    若存在则暂停交易。

    Note:
        当前 MVP 实现通过比较昨收/当前价格计算跳空。
        后续可接入外部行情源实现更精确的波动率判断。

    Returns:
        (ok: True 表示通过, reason: 否决原因或空串)
    """
    db_path = _extract_db_path(order_engine)

    try:
        # 获取最近一笔交易的成交价作为参考基准
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT price, trade_time FROM transactions "
            "WHERE status IN ('FILLED','CONFIRMED') "
            "ORDER BY trade_time DESC LIMIT 1"
        ).fetchone()
        conn.close()

        if not row or not row[0] or float(row[0]) <= 0:
            return True, ""

        last_price = float(row[0])
        last_time = row[1]

        # 尝试从 price_utils 获取当前行情价
        from utils.price_utils import get_current_price
        current_price = get_current_price("")

        if current_price is None or current_price <= 0:
            return True, ""

        gap = abs(current_price - last_price) / last_price

        if gap > config.volatility_gap:
            return False, (
                f"波动保护: 参考价从 {last_price:.2f} → {current_price:.2f}, "
                f"跳空幅度 {gap:.2%} 超过阈值 {config.volatility_gap:.0%}"
            )
        return True, ""

    except ImportError:
        # price_utils 不可用时跳过此检查
        return True, ""
    except Exception as e:
        logger.warning(f"[risk_limits] check_volatility 计算失败: {e}")
        return True, ""

# ============================================================
# 核心入口: check_all
# ============================================================

_DEFAULT_RISK_CONFIG = RiskConfig()

def check_all(
    signal: dict,
    order_engine,
    config: Optional[RiskConfig] = None,
) -> Tuple[bool, List[str]]:
    """执行全部风控检查链。

    依次执行四个维度的风控检查，收集所有否决原因。
    全部通过返回 (False, [])，任一否决返回 (True, [原因])。

    Args:
        signal: Phase1a 信号字典（含 symbol, action, suggested_price, qty_pct）
        order_engine: OrderEngine 实例（用于持仓/资金/交易记录查询）
        config: RiskConfig 风控配置（默认使用全局默认值）

    Returns:
        (reject: bool, reasons: List[str])
        reject=True 表示信号被风控拦截，reasons 包含详细原因列表
        reject=False 表示全部通过，reasons 为空列表
    """
    if config is None:
        config = _DEFAULT_RISK_CONFIG

    action = signal.get("action", "HOLD")
    symbol = signal.get("symbol", "")

    # HOLD 信号跳过所有风控检查
    if action == "HOLD":
        return False, []

    reasons: List[str] = []

    # 1. 单笔金额上限
    ok, reason = check_per_trade_limit(signal, config)
    if not ok:
        reasons.append(reason)

    # 2. 同symbol 5分钟间隔
    ok, reason = check_cool_down(symbol, order_engine, config)
    if not ok:
        reasons.append(reason)

    # 3. 每日亏损上限
    ok, reason = check_daily_pnl(order_engine, config)
    if not ok:
        reasons.append(reason)

    # 4. 大盘波动保护
    ok, reason = check_volatility(order_engine, config)
    if not ok:
        reasons.append(reason)

    if reasons:
        logger.warning(
            f"[risk_limits] 风控拦截 {symbol}: "
            f"action={action}, reasons={'; '.join(reasons)}"
        )
        return True, reasons

    return False, []

# ============================================================
# CLI 自测
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== risk_limits.py 自测 ===\n")

    from trading.core.order_engine import OrderEngine
    from trading.core.account_manager import AccountManager

    am = AccountManager()
    oe = OrderEngine(db_path=DEFAULT_DB_PATH, account_manager=am)
    cfg = RiskConfig()

    test_cases = [
        ("HOLD 信号", {"action": "HOLD", "symbol": "000001.SH"}),
        ("正常买入", {"action": "BUY", "symbol": "600519.SH", "suggested_price": 150.0, "qty_pct": 0.1}),
        ("超限大单", {"action": "BUY", "symbol": "600519.SH", "suggested_price": 150.0, "qty_pct": 0.8}),
    ]

    for label, sig in test_cases:
        reject, reasons = check_all(sig, oe, cfg)
        status = "✅ 通过" if not reject else f"❌ 拦截: {'; '.join(reasons)}"
        print(f"  [{label}] {status}")

    print("\n=== 自测完成 ===")
