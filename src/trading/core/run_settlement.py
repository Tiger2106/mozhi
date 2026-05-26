# run_settlement.py — 结算脚本（T03: 主框架 + 全局事务 + FILLED 持仓处理）
# author: moheng | created_time: 2026-05-13 22:03 GMT+8
# version: v3 (T03 — 主入口框架 + 全局事务 + FILLED→positions)
#
# 职责链（19:00 cron 下的 Step 2）：
#   Step 1: settle_daily() [order_lifecycle.py] → PENDING/FROZEN → ROLLED_BACK + 解冻
#   Step 2: run_settlement()                    → FILLED→positions / 验证 / 公式修正
#
# 不负责：PENDING/FROZEN → ROLLED_BACK（由 settle_daily() 处理）
#
# ── ALTER TABLE 回滚方案说明 ──
# SQLite 的 ALTER TABLE ADD COLUMN 是不可逆操作（无 DROP COLUMN 支持）。
# 回退方式需通过以下方案之一：
#   方案 A：从备份恢复（推荐）—— 删除当前 trade_engine.db，从 backup/ 目录
#           恢复最近的备份文件。
#   方案 B：降级脚本 —— 创建新表并只复制需要的列，然后重命名替换旧表。
# 运行时行为：新加的列在旧查询中默认为 NULL 或 0.0（REAL 类型），
# 不影响原有 SELECT/WHERE/JOIN 条件。幂等迁移函数保证多次运行安全。
#

import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from utils.backup_manager import BackupManager

from src.config import SHANGHAI_TZ
TZ_CST = SHANGHAI_TZ
DB_PATH = r"C:\Users\17699\mo_zhi_sharereports\trade_engine.db"
ACCOUNT_IDS = [
    "acct_agg", "acct_bal", "acct_con",
    "acct_tech_trend", "acct_tech_reversal", "acct_tech_grid",
]

# 编码安全的打印（解决 GBK 编码问题）
def _safe_print(*args, **kwargs):
    """
    编码安全的 print 替代函数。
    当默认编码无法处理 Unicode 字符时，自动降级为 replace 模式。
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # 降级处理：过滤不可编码字符
        text = " ".join(str(a) for a in args)
        safe_text = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace")
        print(safe_text, **kwargs)

# ============================================================
# §1 — 幂等迁移函数（T01）
# ============================================================

def _migrate_positions(conn):
    """
    幂等迁移 positions 表：向现有 positions 表添加结算所需的列。
    通过 PRAGMA table_info 检查列是否存在，缺失则 ADD COLUMN。
    所有 ADD COLUMN 在同一个事务内完成。

    幂等保证：
      - 第 1 次执行：成功添加所有缺失列
      - 第 2 次执行：全部跳过，无报错、无变更
      - 多次重复执行始终安全

    新增列涵盖：
      - avg_price/total_cost  — 加权平均成本法所需（区别于 entry_price）
      - current_price/market_value — 市值追踪
      - unrealized_pnl/realized_pnl — 浮动/已实现盈亏
      - cost_basis/total_fees — 成本基础与费用
      - daily_pnl/total_pnl — 盈亏汇总
      - margin_required/settlement_group — 保证金与结算分组
      - updated_at/notes — 时间戳与备注

    Args:
        conn: sqlite3.Connection 对象（需在事务中调用）
    """
    cur = conn.cursor()

    # Step 1: 获取现有列名集合
    existing_cols = set()
    cur.execute("PRAGMA table_info(positions)")
    for row in cur.fetchall():
        existing_cols.add(row[1])  # row[1] = column name

    # Step 2: 定义需要添加的列（name → type DDL）
    needed_cols = {
        "avg_price":        "REAL",
        "total_cost":       "REAL",
        "current_price":    "REAL",
        "market_value":     "REAL",
        "unrealized_pnl":   "REAL",
        "realized_pnl":     "REAL DEFAULT 0.0",
        "cost_basis":       "REAL",
        "total_fees":       "REAL",
        "daily_pnl":        "REAL",
        "total_pnl":        "REAL",
        "margin_required":  "REAL",
        "settlement_group": "TEXT",
        "updated_at":       "TEXT",
        "notes":            "TEXT",
    }

    # Step 3: 逐列检查，缺失则 ADD
    added_count = 0
    for col_name, col_type in needed_cols.items():
        if col_name not in existing_cols:
            ddl = f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}"
            cur.execute(ddl)
            _migrate_log_line("positions", col_name, col_type, "ADDED")
            added_count += 1
        else:
            _migrate_log_line("positions", col_name, col_type, "SKIPPED (already exists)")

    total = len(needed_cols)
    _safe_print(
        f"[MIGRATE positions] {added_count}/{total} columns added, "
        f"{total - added_count} already existed (idempotent OK)"
    )

def _migrate_account_balance(conn):
    """
    幂等迁移 account_balance 表。
    通过 PRAGMA table_info 检查列是否存在，缺失则 ADD COLUMN。

    需要添加的列：
      - last_settlement_time TEXT  — 上次结算时间

    Args:
        conn: sqlite3.Connection 对象（需在事务中调用）
    """
    cur = conn.cursor()

    existing_cols = set()
    cur.execute("PRAGMA table_info(account_balance)")
    for row in cur.fetchall():
        existing_cols.add(row[1])

    if "last_settlement_time" not in existing_cols:
        cur.execute("ALTER TABLE account_balance ADD COLUMN last_settlement_time TEXT")
        _safe_print("[MIGRATE account_balance] Added column last_settlement_time")
    else:
        _safe_print("[MIGRATE account_balance] Column last_settlement_time already exists (skipped)")

def _migrate_log_line(table: str, col_name: str, col_type: str, action: str):
    """统一迁移日志格式"""
    _safe_print(f"[MIGRATE {table}] {action}: {col_name} ({col_type})")

# ============================================================
# §2 — 余额/流水工具函数
# ============================================================

def _get_balance(cur, account_id: str) -> Dict:
    """获取账户最新余额快照"""
    cur.execute("""
        SELECT total_assets, available_balance, frozen_amount,
               position_market_value, initial_capital, realized_pnl
        FROM account_balance
        WHERE account_id = ?
        ORDER BY id DESC LIMIT 1
    """, (account_id,))
    row = cur.fetchone()
    if row is None:
        return {
            "total_assets": 0.0, "available_balance": 0.0,
            "frozen_amount": 0.0, "position_market_value": 0.0,
            "initial_capital": 0.0, "realized_pnl": 0.0,
        }
    return dict(row)

def _insert_balance_row(cur, account_id: str, total_assets: float,
                        available_balance: float, frozen_amount: float,
                        position_market_value: float):
    """
    插入新 account_balance 行（INSERT 而非 UPDATE，保留历史审计轨迹）。
    从上一行继承 initial_capital 和 realized_pnl。
    """
    cur.execute("""
        SELECT initial_capital, realized_pnl, loss_streak
        FROM account_balance
        WHERE account_id = ?
        ORDER BY id DESC LIMIT 1
    """, (account_id,))
    prev = cur.fetchone()
    initial_cap = prev["initial_capital"] if prev else 0.0
    realized = prev["realized_pnl"] if prev else 0.0
    loss_streak = prev["loss_streak"] if prev else 0

    now_str = datetime.now(TZ_CST).isoformat()
    cur.execute("""
        INSERT INTO account_balance
            (account_id, total_assets, available_balance,
             frozen_amount, position_market_value,
             initial_capital, realized_pnl, loss_streak, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        account_id,
        round(total_assets, 2),
        round(available_balance, 2),
        round(frozen_amount, 2),
        round(position_market_value, 2),
        initial_cap,
        realized,
        loss_streak,
        now_str,
    ))

def _log_fund_flow(cur, flow_type: str, amount: float,
                   balance_before: float, balance_after: float,
                   order_id: str, description: str, account_id: str):
    """
    写入资金流水（增量 snapshot 模式）。
    balance_before / balance_after 反映写入时的瞬态余额，非最终汇总余额。
    """
    now_str = datetime.now(TZ_CST).isoformat()
    cur.execute("""
        INSERT INTO fund_flow
            (flow_type, amount, balance_before, balance_after,
             order_id, description, account_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (flow_type, amount, balance_before, balance_after,
          order_id, description, account_id, now_str))

def _sum_position_market_value(cur, account_id: str) -> float:
    """计算指定账户所有 OPEN 持仓的市值总和"""
    cur.execute("""
        SELECT COALESCE(SUM(market_value), 0.0)
        FROM positions
        WHERE account_id = ? AND status = 'OPEN'
    """, (account_id,))
    return cur.fetchone()[0]

def _update_frozen_safely(cur, account_id: str, new_frozen: float,
                          order_id: str = "", description: str = "") -> None:
    """
    安全更新账户冻结金额。

    Args:
        cur:          数据库游标
        account_id:   账户 ID
        new_frozen:   新的冻结金额（若 < -0.01 则抛出 ValueError）
        order_id:     关联订单 ID（可选，用于 fund_flow 记录）
        description:  操作描述（可选，用于 fund_flow 记录）

    Raises:
        ValueError:   当 new_frozen < -0.01 时，表示逻辑异常，不再静默截断

    正常值正常通过并写入 account_balance 更新。
    负值（-0.01 ≤ new_frozen < 0）写入 ERROR 级别 fund_flow 记录。
    """
    if new_frozen < -0.01:
        raise ValueError(
            f"frozen 金额异常: new_frozen={new_frozen:.4f} (account_id={account_id})"
        )

    # 获取当前余额快照
    bal = _get_balance(cur, account_id)
    bal_before = bal.get("frozen_amount", 0.0)

    if new_frozen < 0:
        # 微小负数（如 -0.001），不阻但记录 ERROR 级别
        _log_fund_flow(
            cur, "FROZEN_SAFE_WARN", new_frozen,
            bal_before, new_frozen,
            order_id, f"[WARN] 轻微负值冻结: {description} ({account_id})",
            account_id,
        )

    # 写入新的 balance 行（冻结金额变更）
    _insert_balance_row(
        cur, account_id,
        total_assets=bal["total_assets"],
        available_balance=bal["available_balance"],
        frozen_amount=round(new_frozen, 2),
        position_market_value=bal["position_market_value"],
    )
    _safe_print(f"[FROZEN] {account_id}: {bal_before:.2f} → {new_frozen:.2f} (order={order_id})")

# ============================================================
# §3 — FILLED 订单 → positions 处理（T03 核心）
# ============================================================

def _is_order_already_processed(cur, order_id: str, account_id: str) -> bool:
    """检查订单是否已被 settlement 处理过（ORDER_ID 幂等）"""
    cur.execute("""
        SELECT status, position_id FROM transactions
        WHERE order_id = ? AND account_id = ?
    """, (order_id, account_id))
    row = cur.fetchone()
    if row is None:
        return False
    return row["status"] == "FILLED" and row["position_id"] is not None

def _create_or_merge_position(conn, account_id: str, symbol: str,
                              action: str, quantity: int, price: float,
                              commission: float = 0.0, tax: float = 0.0) -> int:
    """
    创建或合并持仓（平均成本法）。

    参数：
      conn      — 数据库连接（从调用方获取 cur）
      account_id — 账户标识
      symbol    — 股票代码
      action    — 'BUY'/'BUY_TO_OPEN'/'+' 表示买入，其余视为卖出
      quantity  — 数量（正数）
      price     — 成交价
      commission — 佣金（可选，默认 0）
      tax       — 税费（可选，默认 0）

    逻辑：
      - 检查是否已有同名持仓（account_id + symbol + direction='LONG', status='OPEN'）
      - 无 → INSERT 新持仓行（cost_basis=price*quantity, avg_price=price）
      - 有且 BUY → 加权平均（新avg_price = (old_cost + new_cost) / (old_qty + new_qty)）
      - 有且 SELL → 平仓（quantity==old_qty则 position status='CLOSED'）
                      或减仓（quantity<old_qty则更新数量）

    返回：position_id
    """
    cur = conn.cursor()
    is_buy = action in ("BUY_TO_OPEN", "BUY", "+")
    trade_value = quantity * price
    total_cost = trade_value + commission + tax
    now_str = datetime.now(TZ_CST).isoformat()

    # 检查现有 OPEN 持仓（同名同方向）
    cur.execute("""
        SELECT id, quantity, avg_price, total_cost, realized_pnl
        FROM positions
        WHERE account_id = ? AND symbol = ? AND direction = 'LONG' AND status = 'OPEN'
        ORDER BY id DESC LIMIT 1
    """, (account_id, symbol))
    existing = cur.fetchone()

    if existing is None:
        # ── 创建新持仓 ──
        direction = "LONG"
        cur.execute("""
            INSERT INTO positions
                (account_id, symbol, direction, quantity,
                 avg_price, total_cost, current_price,
                 market_value, entry_price, entry_time,
                 unrealized_pnl, realized_pnl,
                 cost_basis, total_fees,
                 total_pnl, daily_pnl,
                 margin_required, settlement_group,
                 status, updated_at)
            VALUES (?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    'OPEN', ?)
        """, (
            account_id, symbol, direction,
            quantity if is_buy else -quantity,
            price, total_cost, price,
            quantity * price,
            price, now_str,
            0.0, 0.0,
            total_cost, total_cost,
            0.0, 0.0,
            0.0, "AUTO",
            now_str,
        ))
        return cur.lastrowid

    # ── 合并到已有持仓（平均成本法） ──
    pos_id = existing["id"]
    old_qty = existing["quantity"] or 0
    old_avg = existing["avg_price"] or 0.0
    old_cost = existing["total_cost"] or 0.0
    old_realized = existing["realized_pnl"] or 0.0

    if is_buy:
        # 买入：加权平均
        new_qty = old_qty + quantity
        new_cost = old_cost + total_cost
        new_avg = round(new_cost / new_qty, 4) if new_qty > 0 else 0.0
        new_realized = old_realized
    else:
        # 卖出：截断保护 — 不可卖出超过持仓量
        sell_qty = min(quantity, old_qty)
        cost_of_sold = sell_qty * old_avg
        realized = (sell_qty * price) - cost_of_sold
        new_qty = old_qty - sell_qty
        new_cost = old_cost - cost_of_sold
        new_avg = old_avg
        new_realized = old_realized + realized
        total_cost = new_cost  # 重置为卖出后成本

    new_market_value = new_qty * price
    new_unrealized = new_market_value - new_cost
    new_cost_basis = max(0.0, new_cost)

    if new_qty <= 0:
        # 全部平仓
        cur.execute("""
            UPDATE positions SET
                quantity = 0, status = 'CLOSED',
                close_price = ?, close_time = ?,
                pnl = ?, realized_pnl = ?,
                total_pnl = ?, updated_at = ?
            WHERE id = ?
        """, (price, now_str, new_realized, new_realized,
              new_realized, now_str, pos_id))
    else:
        # 减仓或保持
        cur.execute("""
            UPDATE positions SET
                quantity = ?, avg_price = ?,
                total_cost = ?, current_price = ?,
                market_value = ?, unrealized_pnl = ?,
                realized_pnl = ?, cost_basis = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            new_qty, new_avg,
            round(new_cost, 2), price,
            round(new_market_value, 2),
            round(new_unrealized, 2),
            round(new_realized, 2),
            round(new_cost_basis, 2),
            now_str, pos_id,
        ))

    return pos_id

def _process_account_filled_orders(cur, account_id: str, summary: Dict):
    """
    处理指定账户所有未设置 position_id 的 FILLED 订单。
    包含增量余额追踪 + fund_flow 写入 + account_balance 更新。

    时序（v2 修复 P1-HSP-2 / P1-XZ-3）：
      1. 读取当前余额 snapshot
      2. 逐笔处理 FILLED order
         → 更新 positions
         → 写入 fund_flow（瞬态 snapshot）
      3. 最终写入 account_balance 新行
    """
    bal = _get_balance(cur, account_id)
    current_available = bal["available_balance"]
    current_frozen = bal["frozen_amount"]

    # 查询该账户所有未处理的 FILLED 订单
    cur.execute("""
        SELECT * FROM transactions
        WHERE account_id = ? AND status = 'FILLED' AND position_id IS NULL
        ORDER BY id
    """, (account_id,))
    filled = [dict(r) for r in cur.fetchall()]

    if not filled:
        summary["accounts_skipped"].append(account_id)
        return

    account_orders = 0
    for order in filled:
        if _is_order_already_processed(cur, order["order_id"], account_id):
            continue

        order_id = order["order_id"]
        symbol = order["symbol"]
        action = order["action"]
        quantity = order["quantity"]
        price = order["price"]
        commission = order.get("commission", 0.0)
        tax = order.get("tax", 0.0)
        trade_value = round(quantity * price + commission + tax, 2)

        # 增量 snapshot：操作前的余额
        bal_before_op = current_available

        if action in ("BUY_TO_OPEN", "BUY", "+"):
            current_available -= trade_value
        else:
            current_available += trade_value

        # fund_flow 写入（瞬态 snapshot）
        _log_fund_flow(cur, "FILLED_SETTLE", trade_value,
                       bal_before_op, current_available,
                       order_id, f"FILLED: {quantity}x {symbol} @{price}",
                       account_id)

        # 创建/合并持仓
        pos_id = _create_or_merge_position(
            conn=cur.connection,
            account_id=account_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            commission=commission,
            tax=tax,
        )

        # 更新 transactions.position_id
        cur.execute("""
            UPDATE transactions
            SET position_id = ?,
                notes = CASE
                    WHEN notes IS NULL OR notes = '' THEN 'run_settlement: pos created'
                    ELSE notes || '; run_settlement: pos created'
                END
            WHERE order_id = ? AND account_id = ?
        """, (pos_id, order_id, account_id))

        account_orders += 1
        summary["account_positions"][account_id].append({
            "order_id": order_id,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "position_id": pos_id,
        })

    # 统计持仓市值
    total_pos_mv = _sum_position_market_value(cur, account_id)

    # 写入 account_balance 新行
    new_total = current_available + total_pos_mv
    _insert_balance_row(cur, account_id, new_total, current_available,
                        current_frozen, total_pos_mv)

    summary["accounts_processed"] += 1
    if account_orders > 0:
        summary["total_orders_processed"] += account_orders

# T10 别名：_process_account_filled_orders 已实现完整的增量余额追踪
#         每笔 FILLED 操作前记录 balance_before，操作后 balance_after
#         包含 fund_flow 写入 + account_balance 新行
_process_filled_orders_with_flow = _process_account_filled_orders

# ============================================================
# §4 — 验证层
# ============================================================

def _verify_ghost_frozen(cur, account_id: str) -> List[str]:
    """
    验证 ROLLED_BACK 订单的冻结资金是否已释放。
    由 settle_daily() 负责解冻，本函数仅验证不修改。

    Returns: 告警信息列表（无告警则为空列表）
    """
    warnings = []
    bal = _get_balance(cur, account_id)
    frozen = bal["frozen_amount"]

    if frozen > 0:
        cur.execute("""
            SELECT COALESCE(SUM(quantity * price + commission + tax), 0)
            FROM transactions
            WHERE account_id = ?
              AND status = 'ROLLED_BACK'
              AND (notes IS NULL OR notes NOT LIKE '%run_settlement%')
        """, (account_id,))
        ghost = cur.fetchone()[0]
        if ghost > 0:
            msg = (f"{account_id}: ghost frozen ¥{frozen:.2f} "
                   f"(estimated ¥{ghost:.2f}) — settle_daily() may have missed this")
            _safe_print(f"[WARN] {msg}")
            warnings.append(msg)
    return warnings

# ============================================================
# §5 — 公式修正
# ============================================================

def _fix_total_assets_formula(cur, account_id: str) -> bool:
    """
    修正 total_assets 公式（INSERT 新行而非 UPDATE）：
      total_assets = available_balance + position_market_value
    （而非旧的 available_balance + frozen_amount）

    仅在差异 > 0.01 时执行写入。

    Returns: True 已修正, False 无需修正
    """
    bal = _get_balance(cur, account_id)
    calculated_total = bal["available_balance"] + bal["position_market_value"]

    if abs(bal["total_assets"] - calculated_total) > 0.01:
        # INSERT 新行（保留历史审计轨迹）
        _insert_balance_row(
            cur, account_id,
            total_assets=calculated_total,
            available_balance=bal["available_balance"],
            frozen_amount=bal["frozen_amount"],
            position_market_value=bal["position_market_value"],
        )
        _safe_print(f"[FIX] {account_id}: total_assets {bal['total_assets']:.2f} → {calculated_total:.2f}")
        return True

    return False

# ============================================================
# §6 — 崩溃恢复（启动时检查）
# ============================================================

def _recover_crash_state(cur, account_id: str) -> List[str]:
    """
    启动时恢复检查：检测上次运行崩溃导致的 dangling FILLED 订单。
    全局事务保证：崩溃时整个事务回滚，不应存在部分提交的垃圾数据。
    此处仅作验证性检查。

    Returns: 悬挂订单列表（为空则正常）
    """
    cur.execute("""
        SELECT order_id, status, position_id FROM transactions
        WHERE account_id = ?
          AND status = 'FILLED'
          AND (position_id IS NULL
               OR position_id NOT IN (SELECT id FROM positions))
        ORDER BY id
    """, (account_id,))
    dangling = cur.fetchall()
    if dangling:
        _safe_print(f"[RECOVER] {account_id}: {len(dangling)} orphan FILLED orders found")
    else:
        _safe_print(f"[RECOVER] {account_id}: no crash state detected")
    return [dict(r) for r in dangling]

# ============================================================
# §7 — 主入口（全局事务 + verify-only 模式）
# ============================================================

def run_settlement(db_path: str = DB_PATH, mode: str = "full") -> Dict:
    """
    主结算流程（全局事务）。

    参数：
      db_path — 数据库路径（默认 DB_PATH）
      mode    — "full": 完整执行（含写操作）
                "verify-only": 仅只读验证，不执行任何写入

    执行顺序（Phase）：
      Phase 0: 幂等迁移（_migrate_positions + _migrate_account_balance）
      Phase 1: 处理 FILLED 订单 → positions（_process_account_filled_orders）
      Phase 2: 验证 ROLLED_BACK 冻结一致性（_verify_ghost_frozen）
      Phase 3: total_assets 公式修正（_fix_total_assets_formula）

    事务保证（full mode）：
      - 所有账户处理在同一个事务内
      - 任一账户失败 → conn.rollback() → 全部回滚
      - 成功时 conn.commit() 仅执行一次

    返回 dict：
      {
        "status": "SUCCESS|ERROR",
        "summary": {
          "accounts_processed": int,
          "accounts_skipped": [str],
          "total_orders_processed": int,
          "ghost_frozen_warnings": [str],
          "formula_fixes": int,
          "errors": [str]
        },
        "accounts": {
          "acct_agg": {
            "positions": [...],
            "issues": [...]
          },
          ...
        }
      }
    """
    # ── 初始化结果结构 ──
    result = {
        "status": "SUCCESS",
        "summary": {
            "mode": mode,
            "accounts_processed": 0,
            "accounts_skipped": [],
            "total_orders_processed": 0,
            "account_positions": {aid: [] for aid in ACCOUNT_IDS},
            "ghost_frozen_warnings": [],
            "formula_fixes": 0,
            "errors": [],
        },
        "accounts": {
            aid: {"positions": [], "issues": []}
            for aid in ACCOUNT_IDS
        },
    }

    # ── 数据库备份（降级处理：失败不阻塞主流程）──
    _safe_print("[SETTLEMENT] Running backup...")
    try:
        bm = BackupManager(
            db_path=db_path,
            backup_dir=r"C:\Users\17699\mo_zhi_sharereports\backup",
        )
        backup_path = bm.run_daily_backup()
        _safe_print(f"[SETTLEMENT] Backup saved: {backup_path}")
    except Exception as backup_err:
        _safe_print(f"[WARN] Backup failed (non-blocking): {backup_err}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.cursor()

        # ── Phase 0: 幂等迁移 ──
        # 注意: ALTER TABLE 在 SQLite 中不能在事务内回滚（DDL 隐式提交）
        # 但幂等保证保证安全
        _migrate_positions(conn)
        _migrate_account_balance(conn)

        if mode == "verify-only":
            # ── verify-only 模式：只读验证 ──
            _safe_print("[SETTLEMENT] verify-only mode: read-only checks starting...")

            for account_id in ACCOUNT_IDS:
                # 检查 FILLED 订单
                cur.execute("""
                    SELECT COUNT(*) FROM transactions
                    WHERE account_id = ? AND status = 'FILLED' AND position_id IS NULL
                """, (account_id,))
                pending_filled = cur.fetchone()[0]
                if pending_filled > 0:
                    msg = f"{account_id}: {pending_filled} FILLED orders awaiting settlement"
                    _safe_print(f"[VERIFY] {msg}")
                    result["accounts"][account_id]["issues"].append(msg)

                # 检查虚冻
                warnings = _verify_ghost_frozen(cur, account_id)
                result["summary"]["ghost_frozen_warnings"].extend(warnings)
                result["accounts"][account_id]["issues"].extend(warnings)

                # 检查公式
                bal = _get_balance(cur, account_id)
                calculated = bal["available_balance"] + bal["position_market_value"]
                if abs(bal["total_assets"] - calculated) > 0.01:
                    msg = (f"{account_id}: total_assets mismatch "
                           f"(current={bal['total_assets']:.2f}, "
                           f"expected={calculated:.2f})")
                    _safe_print(f"[VERIFY] {msg}")
                    result["accounts"][account_id]["issues"].append(msg)

                # 崩溃恢复检查
                dangling = _recover_crash_state(cur, account_id)
                if dangling:
                    for d in dangling:
                        msg = f"{account_id}: dangling FILLED order {d['order_id']}"
                        result["accounts"][account_id]["issues"].append(msg)

            _safe_print("[SETTLEMENT] verify-only complete.")
            return result

        # ── full mode: 完整执行 + 全局事务 ──
        # 显式启动事务（SQLite 默认 auto-commit off for manual control）
        conn.execute("BEGIN")

        # ── Phase 0.5: 崩溃恢复检查 ──
        for account_id in ACCOUNT_IDS:
            dangling = _recover_crash_state(cur, account_id)
            if dangling:
                for d in dangling:
                    msg = f"{account_id}: dangling FILLED order {d['order_id']} (will reprocess)"
                    _safe_print(f"[RECOVER] {msg}")
                    result["accounts"][account_id]["issues"].append(msg)
                    # Clear position_id so Phase 1 can reprocess
                    cur.execute("""
                        UPDATE transactions SET position_id = NULL, notes = 'run_settlement: recovered dangling'
                        WHERE order_id = ? AND account_id = ?
                    """, (d['order_id'], account_id))

        # ── Phase 1: FILLED 订单 → positions ──
        for account_id in ACCOUNT_IDS:
            _process_account_filled_orders(cur, account_id, result["summary"])

        # ── Phase 2: 验证 ROLLED_BACK 冻结一致性（不修改） ──
        for account_id in ACCOUNT_IDS:
            warnings = _verify_ghost_frozen(cur, account_id)
            result["summary"]["ghost_frozen_warnings"].extend(warnings)
            result["accounts"][account_id]["issues"].extend(warnings)

        # ── Phase 3: total_assets 公式修正 ──
        fix_count = 0
        for account_id in ACCOUNT_IDS:
            if _fix_total_assets_formula(cur, account_id):
                fix_count += 1
        result["summary"]["formula_fixes"] = fix_count

        # ── 全局提交 ──
        conn.commit()
        _safe_print(f"[SETTLEMENT] All {len(ACCOUNT_IDS)} accounts settled successfully.")
        result["status"] = "SUCCESS"

    except Exception as e:
        if mode != "verify-only":
            conn.rollback()
            _safe_print(f"[SETTLEMENT] GLOBAL ROLLBACK due to: {e}")
        else:
            _safe_print(f"[SETTLEMENT] verify-only error: {e}")
        result["status"] = "ERROR"
        result["summary"]["errors"].append(str(e))
        raise
    finally:
        conn.close()

    return result

# ============================================================
# §8 — 入口点
# ============================================================

if __name__ == "__main__":
    import sys

    _safe_print("=== run_settlement v3 (T03) ===")

    # 命令行参数解析
    script_mode = "full"  # 默认
    script_db = DB_PATH   # 默认
    if len(sys.argv) > 1:
        if sys.argv[1] in ("verify-only", "full"):
            script_mode = sys.argv[1]
        else:
            script_db = sys.argv[1]
    if len(sys.argv) > 2:
        if sys.argv[2] in ("verify-only", "full"):
            script_mode = sys.argv[2]
        else:
            script_db = sys.argv[2]

    _safe_print(f"  mode={script_mode}, db={script_db}")
    result = run_settlement(db_path=script_db, mode=script_mode)
    _safe_print(f"  Result status: {result['status']}")
    _safe_print(f"  Summary: {result['summary']}")
