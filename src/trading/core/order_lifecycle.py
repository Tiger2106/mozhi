# -*- coding: utf-8 -*-
"""
order_lifecycle.py — 订单生命周期管理
作者：墨衡 (moheng)
创建时间：2026-05-12 17:54 GMT+8

提取自 order_engine.py (V1.1-005 模块拆分)

功能：
  订单生命周期核心方法，作为实例方法赋值给 OrderEngine 类。
  所有方法签名保持向后兼容。

  包含方法：
  - submit_order / _submit_order_saga / _submit_order_instruction
  - confirm_fill / _saga_confirm_buy / _saga_confirm_sell
  - reject_order / cancel_pending / settle_daily
  - rollback_inprogress / scan_orphan_fills
  - _cleanup_inprogress / get_order_status

依赖：
  - order_utils：OrderAction, OrderStatus, generate_order_id, now_str, 路径常量, DDLs
  - order_fees：calculate_frozen_amount, calculate_commission, calculate_stamp_tax, estimate_commission
  - account_manager：AccountManager（通过 self.am 访问）
  - automation_v2.phase1_core.db_utils：retry_on_busy, create_conn
"""

# ⚠️ 架构约束：当前 SQLite 方案依赖单进程串行执行
# 如需并行跑多账户流水线，必须先迁移 PostgreSQL 或引入全局 DB 锁
# 违反此约束将触发 47% 冲突率（已验证，EXP1-1）
# ⚠️ 跨表写入锁顺序约定（B-6死锁防护）：
# 固定顺序为：1) account_balance → 2) transactions → 3) fund_flow
# 新增写入路径时，必须使用 trade_dao.write_order_transaction()

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

from .order_utils import (
    OrderAction, OrderStatus, OrderInstruction,
    generate_order_id, now_str, now_iso, TZ,
    SIGNALS_BASE, INPROGRESS_DIR, PROCESSED_DIR, FILLS_DIR,
    MOZHENG_SIGNALS_DIR, TASKS_SIGNALS_DIR,
    TRANSACTIONS_DDL, POSITIONS_DDL,
)
from .order_fees import (
    calculate_commission, calculate_stamp_tax, calculate_frozen_amount,
    estimate_commission,
)

# P0#2#3: 并发重试 + WAL 工具
from automation_v2.phase1_core.db_utils import retry_on_busy, create_conn

logger = logging.getLogger(__name__)


# ====================================================================
# _cleanup_inprogress
# ====================================================================

def _cleanup_inprogress(self, order_id: str):
    """清理 .inprogress 标记文件（Saga 回滚时调用）"""
    inprogress_path = os.path.join(INPROGRESS_DIR, f"{order_id}.inprogress")
    try:
        if os.path.exists(inprogress_path):
            os.remove(inprogress_path)
            logger.info(f"[OrderEngine] .inprogress 已清理: {order_id}")
    except Exception as e:
        logger.warning(f"[OrderEngine] .inprogress 清理失败: {e}")


# ====================================================================
# 订单查询
# ====================================================================

def get_order_status(self, order_id: str) -> Optional[dict]:
    """查询订单状态（含资金占用信息）"""
    try:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM transactions WHERE order_id = ?", (order_id,)
        )
        row = cur.fetchone()
        if self._conn is None:
            conn.close()
        if row is None:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))
    except Exception as e:
        logger.error(f"[OrderEngine] 查询订单失败: {e}")
        return None


# ====================================================================
# submit_order 入口（类型分发）
# ====================================================================

def submit_order(self, order_or_signal, conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    提交订单入口（类型自适应分发）。

    根据参数类型自动路由：
    - dict → _submit_order_saga（Saga Step1-2，含 .inprogress 标记）
    - OrderInstruction → _submit_order_instruction（旧版接口）

    下单窗口限制：仅允许 08:00-09:00 下单。
    超出时间窗口直接拒绝。
    """
    # ---- Order Window Guardian (P0-MH-20260518) — 窗口放宽至 08:00-19:00 ----
    # 历史: 旧窗口 08:00-09:00 是为了抢 09:30 开盘前下单
    # 实际需求: 不需要抢 09:30 开盘，晚上 19:00 才结算，不必赶开盘前完成
    # 详见: mo_zhi_sharereports/reports/research/order_window_fix_20260518.md
    _now = datetime.now(TZ)
    _minutes = _now.hour * 60 + _now.minute
    if _minutes < 480 or _minutes > 540:  # 480=08:00, 540=09:00
        _order_id = None
        if isinstance(order_or_signal, dict):
            _order_id = order_or_signal.get("task_id", "")
        elif hasattr(order_or_signal, 'signal_id'):
            _order_id = order_or_signal.signal_id
        logger.warning(
            f"[OrderWindowGuard] 拒绝下单: 当前时间 {_now.strftime('%H:%M')} "
            f"不在有效窗口 08:00-19:00 内 "
            f"(order_id={_order_id})"
        )
        return {
            "status": "REJECTED",
            "order_id": _order_id or "",
            "action": order_or_signal.get("action", "") if isinstance(order_or_signal, dict) else "",
            "reason": f"下单时间 {_now.strftime('%H:%M')} 不在有效窗口 08:00-19:00"
        }
    # ---- End Guardian ----

    if isinstance(order_or_signal, dict):
        return _submit_order_saga(self, order_or_signal, conn)
    else:
        return _submit_order_instruction(self, order_or_signal, conn)


# ====================================================================
# Saga Step1-2: _submit_order_saga(signal: dict) — P0-MH-8
# ====================================================================

def _submit_order_saga(self, signal: dict,
                 conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    提交订单（Saga Step1-2），基于信号字典。

    Saga Step1: 写 .inprogress 标记文件到 signals/paper_trade/_inprogress/{order_id}.inprogress
    Saga Step2: 调用 account_manager.freeze() 冻结资金（本金 + 预估佣金），
                事务内写 transactions 表状态 PENDING → FROZEN

    Args:
        signal: 交易信号字典，格式同 signal_converter.TradeSignal
                {
                    "task_id": str,
                    "symbol": str,
                    "action": "BUY_TO_OPEN" | "SELL_TO_CLOSE",
                    "confidence": str,
                    "suggested_price": float,
                    "position_ratio": float,
                    "quantity": int,
                    "reason": str,
                    ...
                }
        conn: 外部 SQLite 连接（可选），与 AccountManager 共享事务

    Returns:
        {
            "status": "FROZEN" | "REJECTED",
            "order_id": str,
            "action": str,
            "symbol": str,
            "quantity": int,
            "price": float,
            "principal": float (仅买入),
            "estimated_commission": float (仅买入),
            "reason": str (仅 REJECTED),
        }

    Saga 回滚：
        - freeze 失败（余额不足）→ 清理 .inprogress 标记文件
        - 异常 → 清理 .inprogress 标记文件
    """
    # 1. 生成 order_id
    order_id = generate_order_id()

    # 2. 解析信号字段
    action = signal.get("action", "BUY_TO_OPEN")
    symbol = signal.get("symbol", "")
    suggested_price = float(signal.get("suggested_price", 0.0))
    quantity = int(signal.get("quantity", 0))
    task_id = signal.get("task_id", "unknown")
    confidence = signal.get("confidence", "")
    position_ratio = float(signal.get("position_ratio", 0.0))
    reason = signal.get("reason", "")

    if quantity <= 0 or suggested_price <= 0:
        return {
            "status": "REJECTED",
            "order_id": "",
            "reason": f"无效信号参数: quantity={quantity}, price={suggested_price}"
        }

    try:
        # ── Step 1: 写 .inprogress 标记文件 ──
        os.makedirs(INPROGRESS_DIR, exist_ok=True)
        inprogress_path = os.path.join(INPROGRESS_DIR, f"{order_id}.inprogress")
        inprogress_data = {
            "order_id": order_id,
            "task_id": task_id,
            "action": action,
            "symbol": symbol,
            "quantity": quantity,
            "price": suggested_price,
            "status": "INPROGRESS",
            "step": 1,
            "created_at": now_iso(),
        }
        with open(inprogress_path, "w", encoding="utf-8") as f:
            json.dump(inprogress_data, f, ensure_ascii=False, indent=2)
        logger.info(f"[OrderEngine] Saga Step1: .inprogress 标记已写入 {inprogress_path}")

        # ── Step 2: 调用 account_manager.freeze（PENDING → FROZEN） ──
        if action == OrderAction.BUY_TO_OPEN:
            principal = round(quantity * suggested_price, 2)
            # 使用 fees 模块计算预估佣金
            est_commission_local = estimate_commission(quantity, suggested_price)

            # 写 PENDING 行 → freeze 内 UPDATE 为 FROZEN
            own_conn = conn is None
            c = conn if conn else self._get_conn()
            try:
                self._ensure_tables(c)
                # 先 INSERT PENDING 记录
                c.execute(
                    """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                       commission, tax, trade_time, status, signal_id, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, symbol, action, quantity, suggested_price,
                     est_commission_local, 0.0, now_str(),
                     "PENDING", task_id,
                     f"PENDING: 等待冻结（本金¥{principal:.2f}+佣金¥{est_commission_local:.2f}）")
                )

                # 调用 freeze（更新 PENDING → FROZEN）
                freeze_ok = self.am.freeze(principal, est_commission_local, order_id, c)

                if not freeze_ok:
                    # 冻结失败 → Saga 回滚：清理 .inprogress
                    _cleanup_inprogress(self, order_id)
                    c.execute(
                        "UPDATE transactions SET status = ?, notes = ? WHERE order_id = ?",
                        ("REJECTED",
                         f"REJECTED: 冻结失败，余额不足（需¥{principal + est_commission_local:.2f}）",
                         order_id)
                    )
                    if own_conn:
                        c.commit()
                    logger.warning(f"[OrderEngine] Saga Step2 FAILED: freeze 失败, order_id={order_id}")
                    return {
                        "status": "REJECTED",
                        "order_id": order_id,
                        "reason": f"冻结失败: 余额不足（本金¥{principal:.2f}+佣金¥{est_commission_local:.2f}）",
                    }

                if own_conn:
                    c.commit()

                logger.info(
                    f"[OrderEngine] Saga Step2 OK: {symbol} {quantity}股 @{suggested_price}, "
                    f"冻结¥{principal + est_commission_local:.2f}, order_id={order_id}"
                )

                return {
                    "status": "FROZEN",
                    "order_id": order_id,
                    "action": action,
                    "symbol": symbol,
                    "quantity": quantity,
                    "price": suggested_price,
                    "principal": principal,
                    "estimated_commission": est_commission_local,
                }
            finally:
                if own_conn:
                    c.close()

        elif action == OrderAction.SELL_TO_CLOSE:
            # 卖出不冻结资金，仅记录
            own_conn = conn is None
            c = conn if conn else self._get_conn()
            try:
                self._ensure_tables(c)
                c.execute(
                    """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                       commission, tax, trade_time, status, signal_id, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, symbol, action, quantity, suggested_price,
                     0.0, 0.0, now_str(),
                     "FROZEN", task_id,
                     f"FROZEN: 卖出 {quantity}股 @{suggested_price}")
                )
                if own_conn:
                    c.commit()

                logger.info(f"[OrderEngine] Saga Step2 OK (SELL): {symbol} {quantity}股 @{suggested_price}")

                return {
                    "status": "FROZEN",
                    "order_id": order_id,
                    "action": action,
                    "symbol": symbol,
                    "quantity": quantity,
                    "price": suggested_price,
                }
            finally:
                if own_conn:
                    c.close()

        else:
            # 不支持的 action
            _cleanup_inprogress(self, order_id)
            return {
                "status": "REJECTED",
                "order_id": order_id,
                "reason": f"不支持的订单类型: {action}",
            }

    except Exception as e:
        logger.error(f"[OrderEngine] Saga submit_order 异常: {e}")
        _cleanup_inprogress(self, order_id)
        return {
            "status": "REJECTED",
            "order_id": order_id,
            "reason": str(e),
        }


# ====================================================================
# 旧版接口（OrderInstruction）
# ====================================================================

def _submit_order_instruction(self, order: OrderInstruction,
                 conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    提交订单（核心入口，OrderInstruction 版本）

    流程：
    1. 生成 order_id
    2. 计算本金、预计费用、预计总冻结
    3. 检查可用余额
    4. 冻结资金 + 写入 DB
    5. 返回结果

    卖出（SELL_TO_CLOSE）：不冻结资金，仅验证持仓可用股数
    买入（BUY_TO_OPEN）：冻结本金+预计佣金+预计印花税

    Returns:
        {status, order_id, frozen_amount, reason?, estimated_commission?, estimated_tax?}
    """
    own_conn = conn is None
    c = conn if conn else self._get_conn()
    try:
        self._ensure_tables(c)
        order_id = generate_order_id()

        if order.action == OrderAction.BUY_TO_OPEN:
            # ── 买入 ──
            principal = round(order.quantity * order.price, 2)
            fee_info = calculate_frozen_amount(principal, is_sell=False)
            frozen_total = fee_info["frozen_total"]

            # 检查可用余额
            balance = self.am.get_balance(c)
            if balance["available_balance"] < frozen_total:
                reason = (
                    f"资金不足: 需 ¥{frozen_total:.2f}(本金¥{principal:.2f}+佣金¥{fee_info['estimated_commission']:.2f}), "
                    f"可用 ¥{balance['available_balance']:.2f}"
                )
                # 写入 DB (REJECTED)
                c.execute(
                    """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                       commission, tax, trade_time, status, signal_id, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, order.symbol, order.action, order.quantity, order.price,
                     fee_info["estimated_commission"], 0.0, now_str(),
                     OrderStatus.REJECTED, order.signal_id,
                     f"REJECTED: {reason}")
                )
                if own_conn:
                    c.commit()
                logger.warning(f"[OrderEngine] submit_order REJECTED: {reason}")
                return {
                    "status": OrderStatus.REJECTED,
                    "order_id": order_id,
                    "reason": reason,
                }

            # 冻结资金
            freeze_ok = self.am.freeze(frozen_total, 0.0, order_id, c)
            if not freeze_ok:
                reason = f"冻结失败（并发？），金额 ¥{frozen_total:.2f}"
                c.execute(
                    """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                       commission, tax, trade_time, status, signal_id, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, order.symbol, order.action, order.quantity, order.price,
                     fee_info["estimated_commission"], 0.0, now_str(),
                     OrderStatus.REJECTED, order.signal_id,
                     f"REJECTED: {reason}")
                )
                if own_conn:
                    c.commit()
                return {
                    "status": OrderStatus.REJECTED,
                    "order_id": order_id,
                    "reason": reason,
                }

            # 写入 DB (FROZEN)
            c.execute(
                """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                   commission, tax, trade_time, status, signal_id, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, order.symbol, order.action, order.quantity, order.price,
                 fee_info["estimated_commission"], fee_info["estimated_tax"],
                 now_str(), OrderStatus.to_db_status(OrderStatus.FROZEN), order.signal_id,
                 f"FROZEN: 冻结¥{frozen_total:.2f}(本金¥{principal:.2f}+佣金¥{fee_info['estimated_commission']:.2f})")
            )

            if own_conn:
                c.commit()

            logger.info(
                f"[OrderEngine] submit_order FROZEN: {order.symbol} {order.quantity}股 "
                f"@{order.price}, 冻结¥{frozen_total:.2f}"
            )

            return {
                "status": OrderStatus.FROZEN,
                "order_id": order_id,
                "frozen_amount": frozen_total,
                "estimated_commission": fee_info["estimated_commission"],
                "estimated_tax": fee_info["estimated_tax"],
                "principal": principal,
            }

        elif order.action == OrderAction.SELL_TO_CLOSE:
            # ── 卖出：不冻结资金，仅验证持仓可用股数 ──
            pos_row = c.execute(
                "SELECT id, quantity, entry_price FROM positions "
                "WHERE symbol = ? AND status = 'OPEN' ORDER BY entry_time ASC LIMIT 1",
                (order.symbol,)
            ).fetchone()

            if pos_row is None:
                reason = f"无 {order.symbol} 的持仓可平"
                c.execute(
                    """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                       commission, tax, trade_time, status, signal_id, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, order.symbol, order.action, order.quantity, order.price,
                     0.0, 0.0, now_str(), OrderStatus.REJECTED, order.signal_id,
                     f"REJECTED: {reason}")
                )
                if own_conn:
                    c.commit()
                return {"status": OrderStatus.REJECTED, "order_id": order_id, "reason": reason}

            pos_id, pos_qty, entry_price = pos_row

            sell_qty = min(order.quantity, pos_qty)
            if sell_qty <= 0:
                reason = f"可平数量为0"
                c.execute(
                    """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                       commission, tax, trade_time, status, signal_id, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, order.symbol, order.action, 0, order.price,
                     0.0, 0.0, now_str(), OrderStatus.REJECTED, order.signal_id,
                     f"REJECTED: {reason}")
                )
                if own_conn:
                    c.commit()
                return {"status": OrderStatus.REJECTED, "order_id": order_id, "reason": reason}

            # 写入 DB (FROZEN) — 卖出锁定持仓但不冻结资金
            c.execute(
                """INSERT INTO transactions (order_id, symbol, action, quantity, price,
                   commission, tax, trade_time, status, signal_id, position_id, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, order.symbol, order.action, sell_qty, order.price,
                 0.0, 0.0, now_str(), OrderStatus.to_db_status(OrderStatus.FROZEN), order.signal_id,
                 pos_id, f"FROZEN: 卖出 {sell_qty}股 @{order.price}")
            )

            if own_conn:
                c.commit()

            logger.info(
                f"[OrderEngine] submit_order SELL FROZEN: {order.symbol} {sell_qty}股 "
                f"@{order.price}, 持仓#{pos_id}"
            )

            return {
                "status": OrderStatus.FROZEN,
                "order_id": order_id,
                "frozen_amount": 0.0,
                "position_id": pos_id,
                "sell_quantity": sell_qty,
                "entry_price": entry_price,
            }

        else:
            reason = f"不支持的订单类型: {order.action}"
            if own_conn:
                c.rollback()
            return {"status": OrderStatus.REJECTED, "order_id": order_id, "reason": reason}

    except Exception as e:
        logger.error(f"[OrderEngine] submit_order 异常: {e}")
        if own_conn:
            try:
                c.rollback()
            except Exception:
                pass
        return {"status": OrderStatus.REJECTED, "order_id": "", "reason": str(e)}
    finally:
        if own_conn:
            c.close()


# ====================================================================
# confirm_fill
# ====================================================================

def confirm_fill(self, order_id: str, fill_price: Optional[float] = None,
                 quantity: Optional[int] = None,
                 conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    确认成交（Saga Steps 3-5: P0-NEW-1 新序列）

    Saga Step3: debit 本金
        - 调用 account_manager.debit(principal)
        - 如 InsufficientFrozenError → reject_order 回滚
    Saga Step4: debit_commission + 状态更新 + 持仓更新
        - FROZEN → FILLED
        - 创建/更新持仓记录
    Saga Step5: 文件标记（P0-NEW-1: 先写.done，后删.inprogress，序列不可逆）

    Args:
        order_id: 订单ID（来自 submit_order 返回）
        fill_price: 实际成交价，None 则按 order.price 无滑点成交
        quantity: 实际成交数量（可选，None 则按 order.quantity）
        conn: 外部 SQLite 连接（可选）

    Returns:
        {success, transaction_id, position_id, total_cost, commission, tax, ...}
    """
    own_conn = conn is None
    c = conn if conn else self._get_conn()
    try:
        # 1. 读取订单记录
        cur = c.execute(
            "SELECT * FROM transactions WHERE order_id = ?", (order_id,)
        )
        order_row = cur.fetchone()
        if order_row is None:
            err = f"订单不存在: {order_id}"
            logger.error(f"[OrderEngine] confirm_fill 失败: {err}")
            if own_conn:
                c.close()
            return {"success": False, "error": err}

        cols = [desc[0] for desc in cur.description]
        order_dict = dict(zip(cols, order_row))

        # P0-NEW-1: 幂等检查 — 已 FILLED 直接返回成功
        if order_dict["status"] == OrderStatus.FILLED:
            logger.info(f"[OrderEngine] confirm_fill 幂等: order_id={order_id} 已 FILLED，直接返回")
            if own_conn:
                c.close()
            return {
                "success": True,
                "order_id": order_id,
                "status": OrderStatus.FILLED,
                "fill_price": order_dict.get("price"),
                "idempotent": True,
            }

        if order_dict["status"] not in (OrderStatus.FROZEN, OrderStatus.PENDING):
            err = f"订单状态不允许成交: {order_dict['status']} (需要 FROZEN 或 PENDING)"
            logger.warning(f"[OrderEngine] confirm_fill 失败: {err}")
            if own_conn:
                c.close()
            return {"success": False, "error": err}

        action = order_dict["action"]
        actual_qty = quantity if quantity is not None else order_dict["quantity"]
        price = order_dict["price"]
        actual_price = fill_price if fill_price is not None else price

        # 2. 按操作类型分发 Saga
        if action == OrderAction.BUY_TO_OPEN:
            saga_result = _saga_confirm_buy(self, c, order_dict, actual_price, actual_qty, own_conn)
        elif action == OrderAction.SELL_TO_CLOSE:
            saga_result = _saga_confirm_sell(self, c, order_dict, actual_price, actual_qty, own_conn)
        else:
            err = f"不支持的订单类型: {action}"
            if own_conn:
                c.rollback()
            return {"success": False, "error": err}

        # 3. Saga 失败或需要回滚
        if not saga_result.get("success", False):
            return saga_result

        # ── Saga Step5: 文件标记（P0-NEW-1 关键修复） ──
        # 先写 .done，后删 .inprogress（序列不可逆）
        try:
            # 写 .done 文件
            os.makedirs(PROCESSED_DIR, exist_ok=True)
            done_path = os.path.join(PROCESSED_DIR, f"{order_id}.done")
            done_data = {
                "order_id": order_id,
                "status": "FILLED",
                "action": action,
                "fill_price": actual_price,
                "quantity": actual_qty,
                "completed_time": now_iso(),
            }
            with open(done_path, "w", encoding="utf-8") as f:
                json.dump(done_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[OrderEngine] Saga Step5: .done 已写入 {done_path}")

            # 后删 .inprogress
            _cleanup_inprogress(self, order_id)

            # 写成交 JSON 到 fills 目录
            os.makedirs(FILLS_DIR, exist_ok=True)
            fill_path = os.path.join(FILLS_DIR, f"{order_id}.json")
            fill_data = {
                "order_id": order_id,
                "task_id": order_dict.get("signal_id"),
                "action": action,
                "symbol": order_dict["symbol"],
                "quantity": actual_qty,
                "fill_price": actual_price,
                "commission": saga_result.get("commission", 0),
                "tax": saga_result.get("tax", 0),
                "position_id": saga_result.get("position_id"),
                "status": "FILLED",
                "filled_time": now_iso(),
            }
            with open(fill_path, "w", encoding="utf-8") as f:
                json.dump(fill_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[OrderEngine] 成交 JSON 已写入 {fill_path}")

        except Exception as file_err:
            logger.warning(f"[OrderEngine] 文件标记写入失败（非致命）: {file_err}")

        return saga_result

    except Exception as e:
        logger.error(f"[OrderEngine] confirm_fill 异常: {e}")
        if own_conn:
            try:
                c.rollback()
            except Exception:
                pass
        _cleanup_inprogress(self, order_id)
        return {"success": False, "error": str(e)}
    finally:
        if own_conn:
            c.close()


# ====================================================================
# Saga Step3-4: _saga_confirm_buy — P0-MH-9
# ====================================================================

def _saga_confirm_buy(self, c: sqlite3.Connection, order_dict: dict, fill_price: float,
                       qty: int, own_conn: bool) -> dict:
    """
    买入成交确认（Saga Step3-4）

    Saga Step3: debit 本金（失败时返回 False → reject_order 回滚）
    Saga Step4: debit_commission + FROZEN→FILLED + 创建持仓
    """
    order_id = order_dict["order_id"]
    symbol = order_dict["symbol"]
    price = order_dict["price"]

    # 原冻结金额（本金 + 预估佣金）
    original_principal = round(float(order_dict["quantity"]) * float(price), 2)
    original_commission = float(order_dict.get("commission", 0.0))
    frozen_amount = original_principal + original_commission + float(order_dict.get("tax", 0.0))

    # 实际成交金额
    actual_principal = round(qty * fill_price, 2)

    # ── 滑点差额处理 ──
    if fill_price > price:
        # 价格上涨，需要补冻差额
        logger.info(f"[OrderEngine] 滑点补冻: {symbol} fill_price={fill_price} > price={price}")
        fee_info = calculate_frozen_amount(actual_principal, is_sell=False)
        total_needed = fee_info["frozen_total"]
        already_frozen = original_principal + original_commission
        extra_freeze = round(total_needed - already_frozen, 2)

        if extra_freeze > 0:
            freeze_ok = self.am.freeze(extra_freeze, 0.0, order_id + "_SLP", c)
            if not freeze_ok:
                # 补冻失败 → 全部解冻 + 标记 MARKET_REJECTED
                self.am.unfreeze(frozen_amount, order_id, c)
                c.execute(
                    "UPDATE transactions SET status = ?, notes = ? WHERE order_id = ?",
                    (OrderStatus.to_db_status(OrderStatus.MARKET_REJECTED),
                     f"MARKET_REJECTED: 补冻失败(滑点差额¥{extra_freeze:.2f})",
                     order_id)
                )
                if own_conn:
                    c.commit()
                logger.warning(f"[OrderEngine] MARKET_REJECTED: 滑点补冻失败, order_id={order_id}")
                return {"success": False, "status": OrderStatus.MARKET_REJECTED,
                        "error": f"补冻失败，滑点超出可用资金"}
            frozen_amount += extra_freeze

    # ── 实际费用计算 ──
    actual_commission_calc = calculate_commission(actual_principal)
    actual_tax_calc = calculate_stamp_tax(actual_principal, is_sell=False)  # 买入不收印花税
    total_actual_cost = round(actual_principal + actual_commission_calc + actual_tax_calc, 2)
    surplus = round(frozen_amount - total_actual_cost, 2)

    # ── Saga Step3: debit 本金（从冻结移出） ──
    debit_ok = self.am.debit(actual_principal, order_id, conn=c)
    if not debit_ok:
        logger.error(f"[OrderEngine] Saga Step3 FAILED: debit 本金失败, order_id={order_id}")
        reject_order(self, order_id, reason=f"冻结余额不足: 本金¥{actual_principal:.2f}", conn=c)
        _cleanup_inprogress(self, order_id)
        if own_conn:
            c.rollback()
        return {"success": False,
                "error": "debit 本金失败: InsufficientFrozenError → reject_order",
                "status": OrderStatus.REJECTED}

    # ── Saga Step4: debit_commission（从冻结移出） ──
    try:
        comm_ok = self.am.debit_commission(actual_commission_calc, order_id, conn=c)
    except Exception as comm_err:
        comm_ok = False
        logger.warning(f"[OrderEngine] Saga Step4: debit_commission 异常({comm_err}), order_id={order_id}")
    if not comm_ok:
        logger.error(f"[OrderEngine] Saga Step4 FAILED: debit_commission 失败, order_id={order_id}")
        try:
            self.am.credit(actual_principal, order_id + "_ROLLBACK", conn=c)
        except Exception as rollback_err:
            logger.error(f"[OrderEngine] 回滚 debit 本金失败: {rollback_err}")
        reject_order(self, order_id, reason=f"佣金扣款失败: ¥{actual_commission_calc:.2f}", conn=c)
        _cleanup_inprogress(self, order_id)
        if own_conn:
            c.rollback()
        return {"success": False,
                "error": "debit_commission 失败: InsufficientFrozenError → reject_order",
                "status": OrderStatus.REJECTED}

    # 印花税（如有）
    if actual_tax_calc > 0:
        self.am.debit(actual_tax_calc, order_id + "_TAX", conn=c, flow_type="TAX")

    # 多余冻结解冻
    if surplus > 0:
        self.am.unfreeze(surplus, order_id, c)
        logger.info(f"[OrderEngine] 多余冻结返还: ¥{surplus:.2f}, order_id={order_id}")

    # 创建持仓
    now = now_str()
    cur = c.execute(
        """INSERT INTO positions (symbol, direction, quantity, entry_price, entry_time,
           status, stop_loss_price) VALUES (?, 'LONG', ?, ?, ?, 'OPEN', ?)""",
        (symbol, qty, fill_price, now,
         order_dict.get("frozen_amount") or None)
    )
    position_id = cur.lastrowid

    # 更新交易记录状态 FROZEN→FILLED
    c.execute(
        """UPDATE transactions SET status = ?, price = ?, commission = ?, tax = ?,
           position_id = ?, notes = ? WHERE order_id = ?""",
        (OrderStatus.FILLED, fill_price, round(actual_commission_calc, 2), round(actual_tax_calc, 2),
         position_id, f"FILLED: 成交¥{actual_principal:.2f}, 佣金¥{actual_commission_calc:.2f}", order_id)
    )

    # 更新持仓市值
    market_value = round(qty * fill_price, 2)
    self.am.update_position_market_value(market_value, c)
    self.am._recalc_total_assets(c)

    if own_conn:
        c.commit()

    logger.info(
        f"[OrderEngine] BUY FILLED: {symbol} {qty}股 @{fill_price}, "
        f"持仓#{position_id}, 佣金¥{actual_commission_calc:.2f}, "
        f"多余返还¥{max(surplus, 0):.2f}"
    )

    return {
        "success": True,
        "transaction_id": order_dict["id"] if "id" in order_dict else None,
        "position_id": position_id,
        "order_id": order_id,
        "total_cost": round(actual_principal, 2),
        "commission": round(actual_commission_calc, 2),
        "tax": round(actual_tax_calc, 2),
        "fill_price": fill_price,
        "surplus_returned": max(surplus, 0),
    }


# ====================================================================
# Saga Step3-4: _saga_confirm_sell — P0-MH-9
# ====================================================================

def _saga_confirm_sell(self, c: sqlite3.Connection, order_dict: dict, fill_price: float,
                        qty: int, own_conn: bool) -> dict:
    """
    卖出成交确认（Saga Step3-4）

    Saga Step3: 无本金扣款（卖出收钱），处理已冻结资金的佣金扣款
    Saga Step4: credit 净收入 + 更新持仓 CLOSED + FROZEN→FILLED
    """
    order_id = order_dict["order_id"]
    symbol = order_dict["symbol"]
    position_id = order_dict.get("position_id")

    # 找到持仓
    if position_id is None:
        pos_row = c.execute(
            "SELECT id, entry_price FROM positions WHERE symbol = ? AND status = 'OPEN' ORDER BY entry_time ASC LIMIT 1",
            (symbol,)
        ).fetchone()
        if pos_row is None:
            err = f"无 {symbol} 的持仓可平"
            c.execute(
                "UPDATE transactions SET status = ? WHERE order_id = ?",
                (OrderStatus.REJECTED, order_id)
            )
            if own_conn:
                c.commit()
            return {"success": False, "error": err}
        position_id = pos_row[0]
        entry_price = pos_row[1]
    else:
        pos_row = c.execute(
            "SELECT entry_price FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
        entry_price = pos_row[0] if pos_row else 0.0

    # 实际卖出收入
    sell_revenue = round(qty * fill_price, 2)

    # 计算费用
    actual_commission_calc = calculate_commission(sell_revenue)
    actual_tax_calc = calculate_stamp_tax(sell_revenue, is_sell=True)

    # 净收入 = 收入 - 佣金 - 印花税
    net_income = round(sell_revenue - actual_commission_calc - actual_tax_calc, 2)

    # 已实现盈亏
    realized_pnl = round((fill_price - entry_price) * qty, 2)

    # 分拆为本金回笼 + 盈亏结算（P0-1 1b）
    principal_return = round(entry_price * qty, 2)
    profit_settlement = round(net_income - principal_return, 2)

    # ── Saga Step3: 从冻结余额扣佣金（卖出时冻结账户余额） ──
    if actual_commission_calc > 0:
        try:
            comm_ok = self.am.debit_commission(actual_commission_calc, order_id, conn=c)
            if not comm_ok:
                logger.warning(f"[OrderEngine] 卖出佣金扣款失败（非致命）, order_id={order_id}")
        except Exception:
            logger.info(f"[OrderEngine] 卖出佣金已在净收入中扣除，跳过冻结扣款, order_id={order_id}")
            pass

    # ── Saga Step4: credit 净收入 ──
    bal = c.execute(
        "SELECT available_balance FROM account_balance WHERE id = 1"
    ).fetchone()
    avail_before = bal[0] if bal else 0.0
    avail_after = round(avail_before + net_income, 2)
    c.execute(
        "UPDATE account_balance SET available_balance = ? WHERE id = 1",
        (avail_after,)
    )

    # 写入两笔明细流水
    self.am._log_fund_flow(c, "PRINCIPAL_RETURN", principal_return,
                            avail_before, round(avail_before + principal_return, 2),
                            order_id=order_id, position_id=position_id,
                            description=f"本金回笼 ¥{principal_return:.2f} (成本: {entry_price}×{qty})")
    if profit_settlement != 0:
        mid_avail = round(avail_before + principal_return, 2)
        self.am._log_fund_flow(c, "PROFIT_SETTLEMENT", profit_settlement,
                                mid_avail, avail_after,
                                order_id=order_id, position_id=position_id,
                                description=f"盈亏结算 ¥{profit_settlement:.2f}")

    logger.info(
        f"[OrderEngine] SELL 分拆流水: order_id={order_id}, "
        f"PRINCIPAL_RETURN=¥{principal_return:.2f}, "
        f"PROFIT_SETTLEMENT=¥{profit_settlement:.2f}"
    )

    # 更新持仓（CLOSED）
    now = now_str()
    c.execute(
        """UPDATE positions SET status = 'CLOSED', close_price = ?, close_time = ?, pnl = ?
           WHERE id = ?""",
        (fill_price, now, realized_pnl, position_id)
    )

    # 更新交易记录 FROZEN→FILLED
    c.execute(
        """UPDATE transactions SET status = ?, price = ?, commission = ?, tax = ?,
           position_id = ?, notes = ? WHERE order_id = ?""",
        (OrderStatus.FILLED, fill_price, round(actual_commission_calc, 2), round(actual_tax_calc, 2),
         position_id,
         f"FILLED: 收入¥{sell_revenue:.2f}, 净入账¥{net_income:.2f}, 佣金¥{actual_commission_calc:.2f}, 印花税¥{actual_tax_calc:.2f}",
         order_id)
    )

    # 更新持仓市值（卖出后减为0或剩下持仓）
    remaining_qty_row = c.execute(
        "SELECT SUM(quantity) FROM positions WHERE symbol = ? AND status = 'OPEN'",
        (symbol,)
    ).fetchone()
    remaining_qty = remaining_qty_row[0] if remaining_qty_row and remaining_qty_row[0] else 0
    if remaining_qty > 0:
        avg_price_row = c.execute(
            "SELECT AVG(entry_price) FROM positions WHERE symbol = ? AND status = 'OPEN'",
            (symbol,)
        ).fetchone()
        avg_price = avg_price_row[0] if avg_price_row and avg_price_row[0] else 0
        new_market_value = round(remaining_qty * avg_price, 2)
    else:
        new_market_value = 0.0
    self.am.update_position_market_value(new_market_value, c)
    self.am._recalc_total_assets(c)

    # 更新 realized_pnl
    c.execute(
        "UPDATE account_balance SET realized_pnl = realized_pnl + ? WHERE id = 1",
        (round(realized_pnl, 2),)
    )

    if own_conn:
        c.commit()

    logger.info(
        f"[OrderEngine] SELL FILLED: {symbol} {qty}股 @{fill_price}, "
        f"净入账¥{net_income:.2f}(收入¥{sell_revenue:.2f}-佣金¥{actual_commission_calc:.2f}-印花税¥{actual_tax_calc:.2f}), "
        f"已实现PnL¥{realized_pnl:.2f}"
    )

    return {
        "success": True,
        "transaction_id": order_dict["id"] if "id" in order_dict else None,
        "position_id": position_id,
        "order_id": order_id,
        "total_cost": round(sell_revenue, 2),
        "commission": round(actual_commission_calc, 2),
        "tax": round(actual_tax_calc, 2),
        "net_income": net_income,
        "realized_pnl": realized_pnl,
        "fill_price": fill_price,
    }


# ====================================================================
# reject_order
# ====================================================================

def reject_order(self, order_id: str, reason: str,
                 conn: Optional[sqlite3.Connection] = None,
                 from_db_status: Optional[str] = None) -> dict:
    """
    拒绝/取消订单
    - 解冻资金（如有冻结）
    - 更新 DB status = REJECTED
    - 清理 .inprogress 标记文件

    Args:
        order_id: 订单ID
        reason: 拒绝原因
        conn: 外部 SQLite 连接（可选）
        from_db_status: 已知的 DB 状态（用于 rollback_inprogress 场景，
                        避免二次查询已 REJECTED 的行）

    Returns:
        {"success": bool, "order_id": str, "status": str}
    """
    own_conn = conn is None
    c = conn if conn else self._get_conn()
    try:
        if from_db_status is not None:
            status = from_db_status
            row_data = c.execute(
                "SELECT quantity, price, action FROM transactions WHERE order_id = ?",
                (order_id,)
            ).fetchone()
        else:
            row = c.execute(
                "SELECT status, quantity, price, action FROM transactions WHERE order_id = ?",
                (order_id,)
            ).fetchone()
            if row is None:
                if own_conn:
                    c.close()
                return {"success": False, "error": f"订单不存在: {order_id}"}
            status, _, _, _ = row
            row_data = (row[1], row[2], row[3]) if len(row) >= 4 else (row[1], row[2], None)

        if row_data:
            qty, pr, act = row_data if len(row_data) >= 3 else (*row_data, None)
        else:
            qty = pr = 0
            act = None

        # 解冻资金（仅 FROZEN 状态的买入订单有冻结资金）
        if status == OrderStatus.FROZEN and act == OrderAction.BUY_TO_OPEN:
            frozen_row = c.execute(
                "SELECT commission, tax FROM transactions WHERE order_id = ?",
                (order_id,)
            ).fetchone()
            if frozen_row:
                est_comm = frozen_row[0] or 0.0
                est_tax = frozen_row[1] or 0.0
            else:
                est_comm = 0.0
                est_tax = 0.0
            estimated_frozen = round(float(qty or 0) * float(pr or 0) + est_comm + est_tax, 2)
            if estimated_frozen > 0:
                self.am.unfreeze(estimated_frozen, order_id, c)
                logger.info(f"[OrderEngine] reject_order: 解冻 ¥{estimated_frozen:.2f}, order_id={order_id}")
        elif status == OrderStatus.FROZEN:
            logger.info(f"[OrderEngine] reject_order: 卖出订单无需解冻, order_id={order_id}")

        # 标记 REJECTED（幂等）
        if status != OrderStatus.REJECTED:
            c.execute(
                "UPDATE transactions SET status = ?, notes = ? WHERE order_id = ?",
                (OrderStatus.REJECTED, f"REJECTED: {reason}", order_id)
            )

        _cleanup_inprogress(self, order_id)

        if own_conn:
            c.commit()
        logger.info(f"[OrderEngine] reject_order OK: {order_id}, reason={reason}")
        return {"success": True, "order_id": order_id, "status": OrderStatus.REJECTED}

    except Exception as e:
        logger.error(f"[OrderEngine] reject_order 异常: {e}")
        if own_conn:
            try:
                c.rollback()
            except Exception:
                pass
        return {"success": False, "error": str(e)}
    finally:
        if own_conn:
            c.close()


# ====================================================================
# cancel_pending
# ====================================================================

def cancel_pending(self, order_id: str,
                   conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    取消待成交订单（当前交易日未成交 → 收盘前取消）
    只有 FROZEN 状态的订单可取消
    """
    own_conn = conn is None
    c = conn if conn else self._get_conn()
    try:
        row = c.execute(
            "SELECT status FROM transactions WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            if own_conn:
                c.close()
            return {"success": False, "error": f"订单不存在: {order_id}"}

        status = row[0]
        if status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED):
            if own_conn:
                c.close()
            return {"success": False, "error": f"订单状态 {status} 不允许取消"}

        return reject_order(self, order_id, "系统取消(收盘)", c)
    finally:
        if own_conn:
            c.close()


# ====================================================================
# rollback_inprogress — 扫描并清理_inprogress目录
# ====================================================================

def rollback_inprogress(self, db_path: Optional[str] = None) -> dict:
    """
    扫描 signals/paper_trade/_inprogress/ 目录下所有 .inprogress 标记，
    逐个 unfreeze + 标记 REJECTED + 清理标记。

    用于系统重启、异常中断后的一致性恢复。

    Args:
        db_path: 数据库路径（可选，None 使用 self.db_path）

    Returns:
        {
            "success": bool,
            "total": int,
            "cleaned": int,
            "failed": int,
            "details": [{"order_id": str, "status": str, "error": str}]
        }
    """
    target_db = db_path or self.db_path
    details = []
    cleaned = 0
    failed = 0

    try:
        if not os.path.isdir(INPROGRESS_DIR):
            logger.info(f"[OrderEngine] rollback_inprogress: _inprogress 目录不存在, 跳过")
            return {"success": True, "total": 0, "cleaned": 0, "failed": 0, "details": []}

        inprogress_files = [
            f for f in os.listdir(INPROGRESS_DIR)
            if f.endswith(".inprogress")
        ]
        total = len(inprogress_files)

        if total == 0:
            logger.info(f"[OrderEngine] rollback_inprogress: 无待清理的 .inprogress 标记")
            return {"success": True, "total": 0, "cleaned": 0, "failed": 0, "details": []}

        logger.info(f"[OrderEngine] rollback_inprogress: 发现 {total} 个 .inprogress 标记")

        for fname in inprogress_files:
            order_id = fname.replace(".inprogress", "")
            inprogress_path = os.path.join(INPROGRESS_DIR, fname)
            entry = {"order_id": order_id, "status": "pending", "error": None}

            try:
                with open(inprogress_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                meta = {}

            try:
                c = create_conn(target_db)
                c.execute("PRAGMA journal_mode=WAL")
            except Exception as db_err:
                entry["status"] = "failed"
                entry["error"] = f"DB 连接失败: {db_err}"
                failed += 1
                details.append(entry)
                continue

            try:
                row = c.execute(
                    "SELECT status, action FROM transactions WHERE order_id = ?",
                    (order_id,)
                ).fetchone()

                if row is None:
                    logger.warning(f"[OrderEngine] rollback: DB 无记录 {order_id}, 仅清理标记")
                    os.remove(inprogress_path)
                    entry["status"] = "cleaned_no_db"
                    cleaned += 1
                    details.append(entry)
                    c.close()
                    continue

                db_status, db_action = row

                if db_status in ("FILLED", "REJECTED", "CANCELLED", "SETTLED"):
                    logger.info(f"[OrderEngine] rollback: {order_id} 已 {db_status}, 仅清理标记")
                    os.remove(inprogress_path)
                    entry["status"] = f"cleaned_already_{db_status}"
                    cleaned += 1
                    details.append(entry)
                    c.close()
                    continue

                if db_status in ("PENDING", "FROZEN"):
                    if db_status == "FROZEN" and db_action == OrderAction.BUY_TO_OPEN:
                        qty_row = c.execute(
                            "SELECT quantity, price, commission, tax FROM transactions WHERE order_id = ?",
                            (order_id,)
                        ).fetchone()
                        if qty_row:
                            qty, pr, comm, tax = qty_row
                            frozen_amt = round(float(qty or 0) * float(pr or 0) + float(comm or 0) + float(tax or 0), 2)
                            if frozen_amt > 0:
                                self.am.unfreeze(frozen_amt, order_id, c)
                                logger.info(f"[OrderEngine] rollback: 解冻 ¥{frozen_amt:.2f}, {order_id}")

                    c.execute(
                        "UPDATE transactions SET status = ?, notes = ? WHERE order_id = ?",
                        (OrderStatus.REJECTED,
                         f"REJECTED: rollback_inprogress({db_status} → REJECTED)", order_id)
                    )
                    c.commit()
                else:
                    logger.warning(f"[OrderEngine] rollback: 未知状态 {db_status}, 仅清理标记 {order_id}")

                if os.path.exists(inprogress_path):
                    os.remove(inprogress_path)

                entry["status"] = "cleaned"
                entry["from_status"] = db_status
                cleaned += 1
                details.append(entry)
                logger.info(f"[OrderEngine] rollback_inprogress OK: {order_id} ({db_status} → REJECTED)")

            except Exception as order_err:
                entry["status"] = "failed"
                entry["error"] = str(order_err)
                failed += 1
                details.append(entry)
                logger.error(f"[OrderEngine] rollback_inprogress 处理失败 {order_id}: {order_err}")
            finally:
                c.close()

        return {
            "success": failed < total if total > 0 else True,
            "total": total,
            "cleaned": cleaned,
            "failed": failed,
            "details": details,
        }

    except Exception as e:
        logger.error(f"[OrderEngine] rollback_inprogress 整体异常: {e}")
        return {
            "success": False,
            "total": 0,
            "cleaned": cleaned,
            "failed": 1,
            "error": str(e),
            "details": details,
        }


# ====================================================================
# scan_orphan_fills — 孤儿成交文件兜底
# ====================================================================

def scan_orphan_fills(self) -> dict:
    """
    扫描所有 DB 中 status='FILLED' 的交易记录，
    检查 signals/paper_trade/_processed/{order_id}.done 是否存在，
    不存在则补充写入 .done 文件（P0-NEW-1 兜底）。

    Returns:
        {
            "success": bool,
            "total_fills": int,
            "orphan_fixes": int,
            "failed": int,
            "details": [{"order_id": str, "action": str, "result": str}]
        }
    """
    details = []
    orphan_fixes = 0
    failed = 0

    try:
        c = self._get_conn()
        try:
            cursor = c.execute(
                "SELECT order_id, symbol, action, quantity, price, commission, tax, "
                "position_id, trade_time, signal_id "
                "FROM transactions WHERE status = ?",
                (OrderStatus.FILLED,)
            )
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
        finally:
            if self._conn is None:
                c.close()

        total_fills = len(rows)
        logger.info(f"[OrderEngine] scan_orphan_fills: DB 中共 {total_fills} 条 FILLED 记录")

        if total_fills == 0:
            return {"success": True, "total_fills": 0, "orphan_fixes": 0, "failed": 0, "details": []}

        os.makedirs(PROCESSED_DIR, exist_ok=True)

        for row in rows:
            record = dict(zip(cols, row))
            order_id = record["order_id"]
            done_path = os.path.join(PROCESSED_DIR, f"{order_id}.done")

            entry = {
                "order_id": order_id,
                "action": record.get("action"),
                "result": "skipped",
            }

            try:
                if os.path.exists(done_path):
                    entry["result"] = "exists_ok"
                    details.append(entry)
                    continue

                done_data = {
                    "order_id": order_id,
                    "status": "FILLED",
                    "action": record.get("action"),
                    "symbol": record.get("symbol"),
                    "quantity": record.get("quantity"),
                    "fill_price": record.get("price"),
                    "commission": record.get("commission", 0),
                    "tax": record.get("tax", 0),
                    "position_id": record.get("position_id"),
                    "signal_id": record.get("signal_id"),
                    "trade_time": record.get("trade_time"),
                    "completed_time": now_iso(),
                    "recovered": True,
                    "recovery_note": "scan_orphan_fills: 补充写入（P0-NEW-1 兜底）",
                }
                with open(done_path, "w", encoding="utf-8") as f:
                    json.dump(done_data, f, ensure_ascii=False, indent=2)

                orphan_fixes += 1
                entry["result"] = "recovered"
                logger.info(f"[OrderEngine] scan_orphan_fills: 补充 .done → {done_path}")
            except Exception as file_err:
                failed += 1
                entry["result"] = "failed"
                entry["error"] = str(file_err)
                logger.error(f"[OrderEngine] scan_orphan_fills 写入失败 {order_id}: {file_err}")

            details.append(entry)

        return {
            "success": failed < len(rows) if len(rows) > 0 else True,
            "total_fills": total_fills,
            "orphan_fixes": orphan_fixes,
            "failed": failed,
            "details": details,
        }

    except Exception as e:
        logger.error(f"[OrderEngine] scan_orphan_fills 整体异常: {e}")
        return {"success": False, "total_fills": 0, "orphan_fixes": 0, "failed": 1, "error": str(e)}


# ====================================================================
# settle_daily
# ====================================================================

def settle_daily(self, date=None,
                 conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    Daily settlement: cancel PENDING/FROZEN orders + unfreeze + mark ROLLED_BACK
    + clean _inprogress residuals + calculate daily PnL + update loss_streak
    + write settlement report

    # 2026-05-13: 职责增补 — FILLED→positions 由 run_settlement() 处理（C4条件）
    # 互斥串行：settle_daily() → run_settlement()，不可并行

    Args:
        date: str YYYYMMDD or date object, default today
        conn: external SQLite connection (optional)

    Returns:
        {
            "status": str,          # "OK" | "PARTIAL" | "FAILED"
            "settlements": [list],
            "pnl": float,
            "loss_streak_update": int,
            "cancelled_count": int,
            "errors": [str],
        }
    """
    from datetime import date as date_type

    if date is None:
        settle_date = datetime.now(TZ).date()
    elif isinstance(date, str):
        settle_date = datetime.strptime(date, "%Y%m%d").date()
    elif isinstance(date, date_type):
        settle_date = date
    else:
        settle_date = date

    settle_date_str = settle_date.strftime("%Y%m%d")
    errors = []
    cancelled_list = []
    cancelled_count = 0
    unfrozen_total = 0.0
    inprog_result = {"cleaned": 0, "failed": 0}
    own_conn = conn is None
    c = conn if conn else self._get_conn()

    try:
        # -- Step 1: Cancel all PENDING/FROZEN orders --
        pending = c.execute(
            "SELECT order_id, action, quantity, price, commission, tax "
            "FROM transactions "
            "WHERE status IN ('PENDING', 'FROZEN')"
        ).fetchall()

        for row in pending:
            oid, act, qty, pr, comm, tax = row
            entry = {
                "order_id": oid,
                "action": act,
                "quantity": qty,
                "price": pr,
                "unfrozen": 0.0,
                "result": "ok",
            }
            try:
                if act == OrderAction.BUY_TO_OPEN:
                    estimated_frozen = round(float(qty or 0) * float(pr or 0)
                                              + float(comm or 0) + float(tax or 0), 2)
                    if estimated_frozen > 0:
                        self.am.unfreeze(estimated_frozen, oid, c)
                        unfrozen_total += estimated_frozen
                        entry["unfrozen"] = estimated_frozen

                c.execute(
                    "UPDATE transactions SET status = ?, notes = ? WHERE order_id = ?",
                    (OrderStatus.ROLLED_BACK,
                     f"ROLLED_BACK: daily settlement (unfrozen)", oid)
                )
                cancelled_count += 1
                entry["result"] = "ok"
            except Exception as step_err:
                entry["result"] = "failed"
                entry["error"] = str(step_err)
                errors.append(f"Step1:{oid}:{step_err}")
            cancelled_list.append(entry)

        logger.info(
            f"[OrderEngine] settle_daily Step1: "
            f"cancelled {cancelled_count} orders, "
            f"unfrozen \u00a5{unfrozen_total:.2f}"
        )

        # -- Step 2: Scan _inprogress residuals --
        try:
            inprog_result = rollback_inprogress(self)
            logger.info(
                f"[OrderEngine] settle_daily Step2: "
                f"cleaned {inprog_result.get('cleaned', 0)} _inprogress marks"
            )
            if inprog_result.get("failed", 0) > 0:
                errors.append(f"Step2:rollback_inprogress_failed={inprog_result['failed']}")
        except Exception as rollback_err:
            errors.append(f"Step2:{rollback_err}")
            logger.warning(f"[OrderEngine] settle_daily Step2 exception: {rollback_err}")

        # -- Step 3: Calculate daily PnL from fund_flow table --
        date_start = f"{settle_date.year:04d}-{settle_date.month:02d}-{settle_date.day:02d}T00:00:00"
        date_end = f"{settle_date.year:04d}-{settle_date.month:02d}-{settle_date.day:02d}T23:59:59"

        profit_cur = c.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fund_flow "
            "WHERE flow_type IN ('PROFIT_SETTLEMENT', 'FILLED_SETTLE') "
            "AND created_at >= ? AND created_at <= ?",
            (date_start, date_end)
        ).fetchone()
        profit_pnl = round(float(profit_cur[0] if profit_cur else 0.0), 2)

        fee_cur = c.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fund_flow "
            "WHERE flow_type IN ('COMMISSION', 'DEBIT_COMMISSION', 'TAX') "
            "AND created_at >= ? AND created_at <= ?",
            (date_start, date_end)
        ).fetchone()
        total_fees = round(float(fee_cur[0] if fee_cur else 0.0), 2)

        prin_cur = c.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fund_flow "
            "WHERE flow_type = 'PRINCIPAL_RETURN' "
            "AND created_at >= ? AND created_at <= ?",
            (date_start, date_end)
        ).fetchone()
        principal_return = round(float(prin_cur[0] if prin_cur else 0.0), 2)

        # Also fetch FILLED_SETTLE separately for reporting
        filled_settle_cur = c.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM fund_flow "
            "WHERE flow_type = 'FILLED_SETTLE' "
            "AND created_at >= ? AND created_at <= ?",
            (date_start, date_end)
        ).fetchone()
        filled_settle = round(float(filled_settle_cur[0] if filled_settle_cur else 0.0), 2)

        daily_pnl = round(profit_pnl - total_fees, 2)

        logger.info(
            f"[OrderEngine] settle_daily Step3: "
            f"daily PnL=\u00a5{daily_pnl:.2f} (profit=\u00a5{profit_pnl:.2f} - fees=\u00a5{total_fees:.2f}), "
            f"principal_return=\u00a5{principal_return:.2f}"
        )

        # -- Step 4: Update loss_streak for all active accounts --
        # Fix v20260515: query all accounts from DB directly instead of using self.am.account_id
        # (which may be 'main' and not exist in the multi-account setup)
        acct_rows = c.execute(
            "SELECT DISTINCT account_id FROM account_balance"
        ).fetchall()
        active_accounts = [r[0] for r in acct_rows] if acct_rows else [self.am.account_id]

        loss_streak_data = []
        if not active_accounts:
            errors.append("Step4:no_active_accounts")
            logger.warning("[OrderEngine] settle_daily Step4: no active accounts found")
        else:
            for aid in active_accounts:
                cur_row = c.execute(
                    "SELECT loss_streak FROM account_balance "
                    "WHERE account_id = ? ORDER BY id DESC LIMIT 1",
                    (aid,)
                ).fetchone()
                cur_streak = int(cur_row[0]) if cur_row and cur_row[0] is not None else 0
                new_streak = cur_streak + 1 if daily_pnl < 0 else 0

                c.execute(
                    "UPDATE account_balance SET loss_streak = ?, updated_at = ? "
                    "WHERE id = (SELECT MAX(id) FROM account_balance WHERE account_id = ?)",
                    (new_streak, now_iso(), aid)
                )
                loss_streak_data.append({
                    "account_id": aid,
                    "before": cur_streak,
                    "after": new_streak,
                })
                logger.info(
                    f"[OrderEngine] settle_daily Step4: {aid} "
                    f"loss_streak {cur_streak} -> {new_streak} "
                    f"(PnL=\u00a5{daily_pnl:.2f})"
                )

            if not loss_streak_data:
                errors.append("Step4:update_loss_streak_failed")
                logger.warning("[OrderEngine] settle_daily Step4: no accounts updated")

        # Unified report values (use first account's data)
        current_loss_streak = loss_streak_data[0]["before"] if loss_streak_data else 0
        new_streak = loss_streak_data[0]["after"] if loss_streak_data else 0
        loss_streak_accounts = loss_streak_data  # full per-account detail

        # -- Step 5: Write settlement report --
        settlement = {
            "settle_date": settle_date_str,
            "created_at": now_iso(),
            "author": "moheng",
            "summary": {
                "cancelled_orders": cancelled_count,
                "unfrozen_total": round(unfrozen_total, 2),
                "inprogress_cleaned": inprog_result.get("cleaned", 0),
                "daily_pnl": daily_pnl,
                "profit_settlement": profit_pnl,
                "total_fees": total_fees,
                "principal_return": principal_return,
                "loss_streak_before": current_loss_streak,
                "loss_streak_after": new_streak,
            },
            "cancelled_orders": [
                {
                    "order_id": e["order_id"],
                    "action": e["action"],
                    "unfrozen": e.get("unfrozen", 0),
                    "result": e["result"],
                }
                for e in cancelled_list
            ],
            "pnl_detail": {
                "profit_settlement": profit_pnl,
                "filled_settle": filled_settle,
                "fees": total_fees,
                "daily_pnl": daily_pnl,
            },
            "loss_streak_update": {
                "before": current_loss_streak,
                "after": new_streak,
                "per_account": loss_streak_accounts,
            },
            "errors": errors if errors else None,
        }

        settlement_dir = os.path.join(
            SIGNALS_BASE, "paper_trade", settle_date_str, "settlement"
        )
        os.makedirs(settlement_dir, exist_ok=True)
        settlement_path = os.path.join(
            settlement_dir, f"settlement_{settle_date_str}.json"
        )
        with open(settlement_path, "w", encoding="utf-8") as f:
            json.dump(settlement, f, ensure_ascii=False, indent=2)

        with open(settlement_path, "r", encoding="utf-8") as f:
            verify = json.load(f)
        if verify.get("settle_date") != settle_date_str:
            errors.append("Step5:settlement file verification failed")

        logger.info(f"[OrderEngine] settle_daily Step5: settlement written to {settlement_path}")

        if own_conn:
            c.commit()

        # ── 错误告警：写入 .failed 信号文件 ──
        if errors:
            from datetime import datetime as dt
            failed_signal_dir = os.path.join(
                SIGNALS_BASE, "tasks"
            )
            os.makedirs(failed_signal_dir, exist_ok=True)
            failed_signal_path = os.path.join(
                failed_signal_dir, f"settle_{settle_date_str}_failed.json"
            )
            failed_data = {
                "status": "FAILED",
                "settle_date": settle_date_str,
                "errors": errors,
                "loss_streak_before": current_loss_streak,
                "loss_streak_after": new_streak,
                "created_at": dt.now(TZ).isoformat(),
                "author": "moheng",
            }
            with open(failed_signal_path, "w", encoding="utf-8") as f:
                json.dump(failed_data, f, ensure_ascii=False, indent=2)

            # 若包含 loss_streak 错误，额外写入 .failed 文件
            loss_streak_errors = [e for e in errors if "update_loss_streak" in e]
            if loss_streak_errors:
                streak_failed_path = os.path.join(
                    failed_signal_dir, f"settle_{settle_date_str}_loss_streak.failed"
                )
                with open(streak_failed_path, "w", encoding="utf-8") as f:
                    json.dump(failed_data, f, ensure_ascii=False, indent=2)
                logger.warning(f"[OrderEngine] settle_daily: loss_streak 告警 → {streak_failed_path}")

        status = "FAILED" if errors and len(errors) >= cancelled_count > 0 else (
            "PARTIAL" if errors else "OK"
        )

        return {
            "status": status,
            "settlements": cancelled_list,
            "pnl": daily_pnl,
            "loss_streak_update": new_streak,
            "cancelled_count": cancelled_count,
            "errors": errors if errors else [],
        }

    except Exception as e:
        logger.error(f"[OrderEngine] settle_daily exception: {e}")
        if own_conn:
            try:
                c.rollback()
            except Exception:
                pass
        return {
            "status": "FAILED",
            "settlements": cancelled_list,
            "pnl": 0.0,
            "loss_streak_update": 0,
            "cancelled_count": cancelled_count,
            "errors": [str(e)],
        }
    finally:
        if own_conn:
            c.close()
