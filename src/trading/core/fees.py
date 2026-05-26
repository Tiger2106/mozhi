"""fees — 费用计算常量模块（BS-8）

提供统一费用计算函数：
  - 佣金：万2.5 + 最低5元
  - 印花税：千1（仅卖出时收取）
  - 预留配置化入口（v2.0 替换常量来源）

所有费用计算通过函数调用，不直接引用常量值。
"""

from typing import Tuple

# ============================================================
# 费用常量
# ============================================================
# v2.0 规划：从配置文件/环境变量读取此常量

COMMISSION_RATE: float = 0.00025       # 万2.5
COMMISSION_MIN: float = 5.0            # 最低佣金5元
STAMP_TAX_RATE: float = 0.001          # 千1（卖出时收取）


# ============================================================
# 佣金计算
# ============================================================

def calc_commission(quantity: int, price: float) -> float:
    """计算实际佣金。

    公式：
        max(quantity × price × 万2.5, 5)

    参数：
        quantity — 股数（整数）
        price — 每股价格

    返回：
        佣金金额（四舍五入到小数点后2位, round-half-even）
    """
    raw = quantity * price * COMMISSION_RATE
    return round(max(raw, COMMISSION_MIN), 2)


def calc_estimated_commission(quantity: int, price: float) -> float:
    """计算预估佣金（与calc_commission相同，语义区分）。

    用于 freeze() 时预估冻结金额。
    当前实现与 calc_commission 一致；未来若引入滑点等附加费用，
    预估与实际可能不同，此函数提供扩展点。

    返回结果==calc_commission(quantity, price)。
    """
    return calc_commission(quantity, price)


# ============================================================
# 印花税计算
# ============================================================

def calc_stamp_tax(quantity: int, price: float, action: str = "BUY_TO_OPEN") -> float:
    """计算印花税。

    规则：
        - BUY_TO_OPEN（买入）：不收印花税 → 返回 0.0
        - SELL_TO_CLOSE（卖出）：收千1 → quantity × price × 千1

    参数：
        quantity — 股数（整数）
        price — 每股价格
        action — 操作类型（BUY_TO_OPEN / SELL_TO_CLOSE）

    返回：
        印花税金额（四舍五入到小数点后2位）
    """
    if action == "BUY_TO_OPEN":
        return 0.0
    raw = quantity * price * STAMP_TAX_RATE
    return round(raw, 2)


# ============================================================
# 总费用计算
# ============================================================

def calc_total_fees(
    quantity: int,
    price: float,
    action: str,
) -> Tuple[float, float, float]:
    """计算单笔交易的总费用明细。

    参数：
        quantity — 股数
        price — 每股价格
        action — BUY_TO_OPEN / SELL_TO_CLOSE

    返回：
        (commission, stamp_tax, total) 元组
        - commission: 实际佣金
        - stamp_tax: 印花税
        - total: commission + stamp_tax
    """
    commission = calc_commission(quantity, price)
    stamp_tax = calc_stamp_tax(quantity, price, action)
    return (commission, stamp_tax, round(commission + stamp_tax, 2))


# ============================================================
# 任务 P0-MH-3 兼容接口（标准命名别名）
# ============================================================

MIN_COMMISSION: float = COMMISSION_MIN  # 最低佣金5元（别名）


def estimate_commission(quantity: int, price: float) -> float:
    """预估佣金（P0-MH-3 标准接口）。

    公式：
        max(quantity × price × 万2.5, 5)

    实际实现委托给 calc_estimated_commission。
    """
    return calc_estimated_commission(quantity, price)


def actual_commission(quantity: int, price: float) -> float:
    """实际佣金（P0-MH-3 标准接口）。

    公式与预估佣金一致。
    """
    return calc_commission(quantity, price)


def estimate_stamp_tax(quantity: int, price: float, is_sell: bool = False) -> float:
    """预估印花税（P0-MH-3 标准接口）。

    规则：
        - is_sell=False（买入）：不收印花税 → 返回 0.0
        - is_sell=True（卖出）：收千1 → quantity × price × 千1

    参数：
        quantity — 股数（整数）
        price — 每股价格
        is_sell — True=卖出 / False=买入

    返回：
        印花税金额（四舍五入到小数点后2位）
    """
    if not is_sell:
        return 0.0
    raw = quantity * price * STAMP_TAX_RATE
    return round(raw, 2)


def calculate_freeze_amount(quantity: int, price: float, action: str) -> float:
    """计算冻结金额（P0-MH-3 标准接口）。

    公式：
        本金 + 预估佣金 + 预估印花税

    action 参数支持两种格式：
        - BUY_TO_OPEN / SELL_TO_CLOSE（paper_trade 标准格式）
        - buy / sell（兼容格式）

    参数：
        quantity — 股数
        price — 每股价格
        action — 操作类型

    返回：
        总冻结金额（四舍五入到小数点后2位）
    """
    principal = quantity * price
    # 兼容两种 action 格式
    if action.upper() in ("SELL_TO_CLOSE", "SELL"):
        is_sell = True
    else:
        is_sell = False
    comm = estimate_commission(quantity, price)
    tax = estimate_stamp_tax(quantity, price, is_sell)
    return round(principal + comm + tax, 2)
