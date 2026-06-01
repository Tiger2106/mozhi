"""
墨枢 - p0_fixes.preflight
综合交易预检模块 (P1_001b) — 自包含版本

包含：
  - MarketType 枚举 + inline 实现
  - get_market_type() / calc_price_boundary() / is_st_stock()
  - enhanced check_limit_trade() : 涨跌停预检（参数化接口，返回 dict 详情）
  - preflight_check()           : 综合预检入口（逐步集成：涨跌停 + 流动性 + 容量）

本模块自包含涨跌停逻辑，不依赖 backtest_engine.sim_layer 外部模块。

author: moheng
created_time: 2026-05-28T12:32+08:00
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# MarketType 枚举 — 板块类型
# ═══════════════════════════════════════════════════════════════

class MarketType(Enum):
    """A股板块类型枚举，用于确定涨跌停比例。"""
    MAIN_BOARD = "main"       # 主板 ±10%
    CHINEXT = "chinext"       # 创业板 ±20%
    STAR = "star"             # 科创板 ±20%
    BEI = "bei"               # 北交所 ±30%
    ST = "st"                 # ST 股  ±5%
    IPO_FIRST_DAY = "ipo"     # IPO 首日（特殊规则）


# ═══════════════════════════════════════════════════════════════
# 涨跌停比例常量
# ═══════════════════════════════════════════════════════════════

LIMIT_UP_RATIO: dict[MarketType, float] = {
    MarketType.MAIN_BOARD: 1.10,
    MarketType.CHINEXT: 1.20,
    MarketType.STAR: 1.20,
    MarketType.BEI: 1.30,
    MarketType.ST: 1.05,
}

LIMIT_DOWN_RATIO: dict[MarketType, float] = {
    MarketType.MAIN_BOARD: 0.90,
    MarketType.CHINEXT: 0.80,
    MarketType.STAR: 0.80,
    MarketType.BEI: 0.70,
    MarketType.ST: 0.95,
}

# 新股上市首日特殊涨跌幅（主板 44%，创业板/科创板无涨跌幅限制）
_IPO_FIRST_DAY_LIMIT_UP: float = 1.44
_IPO_FIRST_DAY_LIMIT_DOWN: float = 0.64


# ═══════════════════════════════════════════════════════════════
# get_market_type — 根据股票代码判定板块类型
# ═══════════════════════════════════════════════════════════════

def get_market_type(stock_code: str) -> MarketType:
    """根据股票代码判定板块类型。

    Parameters
    ----------
    stock_code : str
        6 位股票代码，可带 .SH / .SZ / .BJ 后缀。

    Returns
    -------
    MarketType
        对应的板块类型。无法识别时默认返回 MAIN_BOARD。
    """
    # 去除后缀，取前 6 位纯数字
    code = re.sub(r"\..+$", "", stock_code.strip()).strip()
    code = code[:6]

    # 检查 ST 标识（代码本身通常不含 ST 标记，此路径备用）
    # 主逻辑依靠前缀判定

    prefix_map = [
        ("688", MarketType.STAR),    # 科创板
        ("689", MarketType.STAR),    # 科创板
        ("30", MarketType.CHINEXT),  # 创业板
        ("8", MarketType.BEI),       # 北交所
        ("60", MarketType.MAIN_BOARD),   # 沪主板
        ("00", MarketType.MAIN_BOARD),   # 深主板
        ("01", MarketType.MAIN_BOARD),   # 深主板
        ("02", MarketType.MAIN_BOARD),   # 深主板
    ]

    for prefix, mt in prefix_map:
        if code.startswith(prefix):
            return mt

    # 无法识别则默认主板
    return MarketType.MAIN_BOARD


# ═══════════════════════════════════════════════════════════════
# is_st_stock — 判断是否为 ST 股
# ═══════════════════════════════════════════════════════════════

# 注意：此处为占位实现。实际项目中，ST 标记应从数据源（如 bar.st_status）获取。
# 纯代码前缀无法区分 ST/非 ST，本函数供 calc_price_boundary 回退使用。
_ST_SUFFIX_MARKERS = ("ST", "*ST")


def is_st_stock(stock_code: str) -> bool:
    """判断股票代码是否含有 ST 标记。

    通过检测股票代码是否包含 'ST' 或 '*ST' 子串。
    仅适用于代码本身含 ST 标记的场景（如 "600123ST"）。
    多数行情数据中 ST 标记不在代码中，而在额外字段中。
    """
    code_upper = stock_code.upper()
    for marker in _ST_SUFFIX_MARKERS:
        if marker in code_upper:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# calc_price_boundary — 计算涨跌停边界
# ═══════════════════════════════════════════════════════════════

def calc_price_boundary(
    prev_close: float,
    market_type: MarketType,
    point_value: float = 0.01,
    is_ipo_first_day: bool = False,
) -> Tuple[float, float]:
    """计算涨跌停价。

    Parameters
    ----------
    prev_close : float
        前收盘价。
    market_type : MarketType
        板块类型。
    point_value : float
        最小变动价位，默认 0.01。
    is_ipo_first_day : bool
        是否为新股上市首日。

    Returns
    -------
    tuple[float, float]
        (limit_up, limit_down)
    """
    if prev_close <= 0:
        return 0.0, 0.0

    if is_ipo_first_day and market_type == MarketType.MAIN_BOARD:
        # 主板新股上市首日 ±44%
        limit_up = _round_price(prev_close * _IPO_FIRST_DAY_LIMIT_UP, point_value)
        limit_down = _round_price(prev_close * _IPO_FIRST_DAY_LIMIT_DOWN, point_value)
        return limit_up, limit_down

    if is_ipo_first_day and market_type in (MarketType.CHINEXT, MarketType.STAR):
        # 创业板/科创板新股首日无涨跌幅限制
        return 0.0, 0.0

    # 常规涨跌停
    ratio_up = LIMIT_UP_RATIO.get(market_type, 1.10)
    ratio_down = LIMIT_DOWN_RATIO.get(market_type, 0.90)

    limit_up = _round_price(prev_close * ratio_up, point_value)
    limit_down = _round_price(prev_close * ratio_down, point_value)

    return limit_up, limit_down


def _round_price(price: float, point_value: float = 0.01) -> float:
    """按最小变动价位四舍五入到有效价位。"""
    if point_value <= 0:
        return round(price, 2)
    return round(round(price / point_value) * point_value, 2)


# ═══════════════════════════════════════════════════════════════
# 增强版 check_limit_trade
# ═══════════════════════════════════════════════════════════════

def check_limit_trade(
    prev_close: float,
    current_price: float,
    stock_code: str,
    side: str,
    market_type: Optional[MarketType] = None,
    point_value: float = 0.01,
    is_ipo_first_day: bool = False,
) -> Tuple[bool, str, dict]:
    """
    预检一笔交易是否受涨跌停限制（参数化接口，不依赖 bar 对象）。

    Parameters
    ----------
    prev_close : float
        前收盘价。
    current_price : float
        当前价格（或拟成交价）。
    stock_code : str
        6 位股票代码（可含 .SH/.SZ/.BJ 后缀）。
    side : str
        交易方向：'buy' 或 'sell'（不区分大小写）。
    market_type : MarketType, optional
        板块类型。若不提供，通过 get_market_type(stock_code) 推断。
    point_value : float
        最小变动价位，默认 0.01 元。
    is_ipo_first_day : bool
        是否为新股上市首日。

    Returns
    -------
    tuple[bool, str, dict]
        (allowed, reason, detail)

        - allowed=True, reason=""  → 允许交易
        - allowed=False, reason="..." → 被限制，reason 含原因
        - detail = {
            "market_type": str,       # 板块类型
            "limit_up_price": float,  # 涨停价
            "limit_down_price": float,# 跌停价
            "prev_close": float,      # 前收盘价
        }
    """
    # ── 输入校验 ──
    if prev_close is None or prev_close <= 0.0:
        return True, "", {
            "market_type": str(market_type or "unknown"),
            "limit_up_price": 0.0,
            "limit_down_price": 0.0,
            "prev_close": prev_close or 0.0,
        }

    if current_price is None or current_price <= 0.0:
        return True, "", {
            "market_type": str(market_type or "unknown"),
            "limit_up_price": 0.0,
            "limit_down_price": 0.0,
            "prev_close": prev_close,
        }

    # ── 方向归一化 ──
    s = side.strip().lower()
    supported = ("buy", "sell", "long", "short", "open", "close")
    if s not in supported:
        return True, f"未知交易方向 '{side}'，跳过涨跌停检查", {
            "market_type": str(market_type or "unknown"),
            "limit_up_price": 0.0,
            "limit_down_price": 0.0,
            "prev_close": prev_close,
        }

    is_buy = s in ("buy", "long", "open")

    # ── 获取板块类型并计算边界 ──
    mt = market_type or get_market_type(stock_code)
    limit_up, limit_down = calc_price_boundary(prev_close, mt, point_value, is_ipo_first_day)

    detail = {
        "market_type": mt.value,
        "limit_up_price": limit_up,
        "limit_down_price": limit_down,
        "prev_close": round(prev_close, 2),
    }

    # ── 涨跌停预检 ──
    if is_buy and limit_up > 0 and current_price >= limit_up:
        return (
            False,
            f"涨停禁止买入: 当前价={current_price:.2f} >= 涨停价={limit_up:.2f} [{mt.value}]",
            detail,
        )

    if not is_buy and limit_down > 0 and current_price <= limit_down:
        return (
            False,
            f"跌停禁止卖出: 当前价={current_price:.2f} <= 跌停价={limit_down:.2f} [{mt.value}]",
            detail,
        )

    return True, "", detail


# ═══════════════════════════════════════════════════════════════
# 综合预检入口
# ═══════════════════════════════════════════════════════════════

def preflight_check(
    prev_close: float,
    current_price: float,
    stock_code: str,
    side: str,
    volume: Optional[float] = None,
    market_cap: Optional[float] = None,
    market_type: Optional[MarketType] = None,
    point_value: float = 0.01,
    is_ipo_first_day: bool = False,
) -> dict:
    """
    综合预检入口——涨跌停 + 流动性 + 容量（逐步集成）。

    当前实现：
        - 涨跌停预检（check_limit_trade）：已实现，全功能。

    未来扩展：
        - 流动性检查：调用 get_liquidity_tier() 判定流动性等级
        - 容量检查：根据 volume 和 market_cap 判断是否超出日成交容量

    Parameters
    ----------
    prev_close : float
        前收盘价。
    current_price : float
        当前价格。
    stock_code : str
        股票代码。
    side : str
        交易方向：'buy' | 'sell'。
    volume : float, optional
        拟交易数量（股数）。
    market_cap : float, optional
        总市值（元），用于容量检查。
    market_type : MarketType, optional
        板块类型，不提供则自动推断。
    point_value : float
        最小变动价位。
    is_ipo_first_day : bool
        是否为新股上市首日。

    Returns
    -------
    dict
        {
            "pass": bool,        # 所有检查全部通过 → True
            "checks": {
                "limit_trade": {
                    "passed": bool,
                    "reason": str,
                    "detail": dict,   # 参见 check_limit_trade 返回值
                },
                "liquidity": {
                    "passed": bool,
                    "reason": str,
                    "detail": dict,
                },
                "capacity": {
                    "passed": bool,
                    "reason": str,
                    "detail": dict,
                },
            },
            "summary": str,      # 简短总结
        }
    """
    result = {
        "pass": True,
        "checks": {},
        "summary": "",
    }

    # ── 1. 涨跌停预检 ──
    limit_allowed, limit_reason, limit_detail = check_limit_trade(
        prev_close=prev_close,
        current_price=current_price,
        stock_code=stock_code,
        side=side,
        market_type=market_type,
        point_value=point_value,
        is_ipo_first_day=is_ipo_first_day,
    )
    result["checks"]["limit_trade"] = {
        "passed": limit_allowed,
        "reason": limit_reason,
        "detail": limit_detail,
    }

    if not limit_allowed:
        result["pass"] = False

    # ── 2. 流动性预检（预留） ──
    try:
        from .liquidity_model import get_liquidity_tier
        _ = get_liquidity_tier(stock_code)
        liquidity_passed = True
        liquidity_reason = ""
    except (ImportError, AttributeError):
        liquidity_passed = True
        liquidity_reason = "liquidity_model 未就绪，跳过"

    result["checks"]["liquidity"] = {
        "passed": liquidity_passed,
        "reason": liquidity_reason,
        "detail": {"liquidity_tier": "unknown"},
    }

    # ── 3. 容量预检（预留） ──
    capacity_passed = True
    capacity_detail = {}
    if volume is not None:
        capacity_detail["volume"] = volume
    if market_cap is not None:
        capacity_detail["market_cap"] = market_cap
    result["checks"]["capacity"] = {
        "passed": capacity_passed,
        "reason": "",
        "detail": capacity_detail,
    }

    # ── 汇总 ──
    failed_checks = [k for k, v in result["checks"].items() if not v["passed"]]
    if failed_checks:
        result["summary"] = f"预检未通过: {', '.join(failed_checks)}"
    else:
        result["summary"] = "全部预检通过"

    return result


# 兼容导出：为依赖 .price_boundary.MarketType 的调用方提供相同符号
# 本模块自包含后，不需要再从 price_boundary 导入
