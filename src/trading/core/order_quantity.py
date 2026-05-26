# -*- coding: utf-8 -*-
"""
order_quantity.py — 下单映射模块（Phase1c 重写）

将信号 qty_pct → 实际股数，实现下单映射逻辑。
P0-MX-001-Phase1c 核心模块。

变更记录：
  v2.0 (2026-05-12): Phase1c 重写
    - 新签名: calculate_order_quantity(signal, available_cash, config)
    - 新增 SignalMappingConfig 类
    - 逻辑: 可用资金 * qty_pct / suggest_price → 向下取整到 lot_size

设计依据：
  - 墨枢 P0-MX-001 Phase1c
  - 信号格式: {task_id, action, symbol, qty_pct (0~1), suggested_price, ...}

author: moheng
created_time: 2026-05-12 19:58 GMT+8
task_id: P0-MX-001-Phase1c
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── 默认配置路径 ──
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # automation_v2/
    "configs", "signal_mapping.json"
)

# ── 信号 action → OrderEngine 指令映射 ──
ACTION_MAP = {
    "BUY": "BUY_TO_OPEN",
    "SELL": "SELL_TO_CLOSE",
    "HOLD": "HOLD",
}


# ============================================================
# SignalMappingConfig — 信号→仓位映射配置
# ============================================================

class SignalMappingConfig:
    """信号→仓位映射配置

    从 JSON 文件加载下单映射参数：
      - min_qty: 最小交易股数（默认 100）
      - lot_size: 交易单位（默认 100，A股一手）
      - max_qty: 单笔最大股数（默认 100000）
      - fee_buffer_ratio: 手续费缓冲系数（默认 0.995，预留 0.5%）

    配置文件路径: configs/signal_mapping.json
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.min_qty = 100
        self.lot_size = 100
        self.max_qty = 100000
        self.fee_buffer_ratio = 0.995
        self._loaded = False
        self._load()

    def _load(self):
        """从 JSON 文件加载配置，失败时使用默认值（即类上的初始值）。"""
        if not os.path.exists(self.config_path):
            logger.info(
                f"[SignalMappingConfig] 配置不存在: {self.config_path}, 使用默认值"
            )
            self._loaded = True
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.min_qty = data.get("min_qty", 100)
            self.lot_size = data.get("lot_size", 100)
            self.max_qty = data.get("max_qty", 100000)
            self.fee_buffer_ratio = data.get("fee_buffer_ratio", 0.995)
            self._loaded = True

            logger.info(
                f"[SignalMappingConfig] 已加载配置: "
                f"lot_size={self.lot_size}, min_qty={self.min_qty}, "
                f"max_qty={self.max_qty}, fee_buffer={self.fee_buffer_ratio}"
            )
        except Exception as e:
            logger.error(f"[SignalMappingConfig] 加载失败: {e}, 使用默认值")

    def to_dict(self) -> dict:
        """将当前配置序列化为 dict。"""
        return {
            "min_qty": self.min_qty,
            "lot_size": self.lot_size,
            "max_qty": self.max_qty,
            "fee_buffer_ratio": self.fee_buffer_ratio,
        }


# ============================================================
# get_position_quantity — 查询持仓股数
# ============================================================

def get_position_quantity(symbol: str, db_path: str) -> int:
    """查询指定品种的当前持仓股数（OPEN 状态）。

    Args:
        symbol: 品种代码（如 "600519.SH"）
        db_path: SQLite 数据库路径

    Returns:
        持仓股数（0 表示无持仓）
    """
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM positions "
            "WHERE symbol = ? AND status = 'OPEN'",
            (symbol,)
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"[order_quantity] 查询持仓失败: {e}")
        return 0


# ============================================================
# calculate_order_quantity — 核心下单量计算
# ============================================================

def calculate_order_quantity(
    signal: dict,
    available_cash: float,
    config: Optional[SignalMappingConfig] = None,
) -> int:
    """计算实际下单股数。

    核心逻辑:
      1. 可用资金 × qty_pct → 分配金额
      2. 分配金额 / suggested_price → 原始股数
      3. 向下取整到 lot_size 的倍数（A股默认 100 股/手）
      4. 应用 min_qty / max_qty 约束

    Args:
        signal: 信号字典（来自 signal_converter Phase1a）
                {action, symbol, qty_pct (0~1), suggested_price, ...}
        available_cash: 当前可用资金（来自 AccountManager.get_balance）
        config: SignalMappingConfig 实例（默认新建）

    Returns:
        下单股数（int，0 表示不下单）
    """
    if config is None:
        config = SignalMappingConfig()

    action = signal.get("action", "HOLD")
    qty_pct = signal.get("qty_pct", 0.0)
    price = signal.get("suggested_price", 0.0)

    # ── 前置校验 ──

    if action == "HOLD":
        logger.debug(f"[order_quantity] HOLD 信号, 跳过数量计算")
        return 0

    if not price or price <= 0:
        logger.warning(f"[order_quantity] 价格无效: {price}")
        return 0

    if qty_pct <= 0 or qty_pct > 1.0:
        logger.warning(f"[order_quantity] qty_pct 超出 [0,1] 范围: {qty_pct}")
        return 0

    if available_cash <= 0:
        logger.debug(f"[order_quantity] 可用资金为 0, 不下单")
        return 0

    # ── 核心计算: 资金 × 比例 / 价格 → 股数(取整到 lot_size) ──
    raw_shares = int(available_cash * qty_pct / price)
    qty = int(raw_shares / config.lot_size) * config.lot_size

    # ── 约束检查 ──

    if qty < config.min_qty:
        logger.info(
            f"[order_quantity] 不足最低交易量: 计算={qty} < 最低={config.min_qty}"
        )
        return 0

    if qty > config.max_qty:
        qty = int(config.max_qty / config.lot_size) * config.lot_size
        logger.info(f"[order_quantity] 超最大限制, 截断至 {qty}")

    logger.debug(
        f"[order_quantity] 计算结果: action={action}, "
        f"cash={available_cash:.2f}, pct={qty_pct}, "
        f"price={price}, qty={qty}"
    )
    return qty


# ============================================================
# 命令行自测
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== order_quantity.py 自测 (Phase1c) ===\n")

    cfg = SignalMappingConfig()
    print(f"配置: {cfg.to_dict()}\n")

    # 买入测试
    signal = {
        "action": "BUY",
        "symbol": "600519.SH",
        "qty_pct": 0.3,
        "suggested_price": 150.0,
    }
    qty = calculate_order_quantity(signal, 200000.0, cfg)
    print(f"买入: cash=200k, pct=0.3, price=150 → {qty}股")

    # 买入测试（半仓）
    signal["qty_pct"] = 0.5
    qty = calculate_order_quantity(signal, 200000.0, cfg)
    print(f"买入: cash=200k, pct=0.5, price=150 → {qty}股")

    # 卖出测试
    signal["action"] = "SELL"
    signal["qty_pct"] = 1.0
    qty = calculate_order_quantity(signal, 200000.0, cfg)
    print(f"卖出: cash=200k, pct=1.0, price=150 → {qty}股")

    # HOLD 测试
    signal["action"] = "HOLD"
    qty = calculate_order_quantity(signal, 200000.0, cfg)
    print(f"HOLD: {qty}股 (应为 0)")

    # 资金不足测试
    signal["action"] = "BUY"
    qty = calculate_order_quantity(signal, 0.0, cfg)
    print(f"资金为 0: {qty}股 (应为 0)")

    # 低价股测试
    signal["qty_pct"] = 0.5
    signal["suggested_price"] = 3.5
    qty = calculate_order_quantity(signal, 50000.0, cfg)
    print(f"低价股: cash=50k, pct=0.5, price=3.5 → {qty}股")

    print("\n=== 自测完成 ===")
