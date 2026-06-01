"""
墨枢 - sim_layer.price_boundary
涨跌停常量和边界计算函数

提供：
  - MarketType 枚举：板块类型（主板/创业板/科创板/ST/北交所）
  - LIMIT_UP/DOWN_RATIO：各板块涨跌幅常量表
  - get_market_type(ts_code)：股票代码 → 板块判定
  - is_st_stock(name)：ST 股票判定
  - calc_price_boundary(price, market_type)：涨跌停价格边界计算
  - check_limit_trade(bar, side)：涨跌停交易预检
  - enrich_bar_with_boundary(bar, ...)：K线注入涨跌停边界

author: moheng
created_time: 2026-05-28T12:00+08:00
"""
from __future__ import annotations

import re
import math
from enum import Enum
from typing import Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 1. MarketType 枚举
# ═══════════════════════════════════════════════════════════════

class MarketType(Enum):
    """板块类型枚举。"""
    MAIN_BOARD = "main"    # 主板（含中小板）
    CHINEXT = "chinext"    # 创业板
    STAR = "star"          # 科创板
    ST = "st"              # ST / *ST
    BEI = "bei"            # 北交所


# ═══════════════════════════════════════════════════════════════
# 2. 涨跌幅常量表
# ═══════════════════════════════════════════════════════════════

LIMIT_UP_RATIO = {
    MarketType.MAIN_BOARD: 0.10,
    MarketType.CHINEXT: 0.20,
    MarketType.STAR: 0.20,
    MarketType.ST: 0.05,
    MarketType.BEI: 0.30,
}

LIMIT_DOWN_RATIO = {
    MarketType.MAIN_BOARD: -0.10,
    MarketType.CHINEXT: -0.20,
    MarketType.STAR: -0.20,
    MarketType.ST: -0.05,
    MarketType.BEI: -0.30,
}

# IPO 首日涨跌幅（仅主板有特殊规则）
IPO_LIMIT_UP_RATIO = 0.44
IPO_LIMIT_DOWN_RATIO = -0.36


# ═══════════════════════════════════════════════════════════════
# 3. 板块判定
# ═══════════════════════════════════════════════════════════════

_CODE_PREFIX_MAP = [
    # (前缀, 板块, 说明)
    ("688", MarketType.STAR,      "科创板"),
    ("300", MarketType.CHINEXT,   "创业板"),
    ("8",   MarketType.BEI,       "北交所（80/83/87/88/89 开头）"),
    ("4",   MarketType.BEI,       "北交所（4 开头）"),
    ("002", MarketType.MAIN_BOARD,"中小板（归入主板）"),
    ("000", MarketType.MAIN_BOARD,"深圳主板"),
    ("001", MarketType.MAIN_BOARD,"深圳主板"),
    ("003", MarketType.MAIN_BOARD,"深圳主板"),
    ("600", MarketType.MAIN_BOARD,"上海主板"),
    ("601", MarketType.MAIN_BOARD,"上海主板"),
    ("603", MarketType.MAIN_BOARD,"上海主板"),
    ("605", MarketType.MAIN_BOARD,"上海主板"),
]


def _clean_ts_code(ts_code: str) -> str:
    """清洗股票代码，去除交易所后缀（.SH/.SZ/.BJ 等）。"""
    return ts_code.split(".")[0].strip()


def get_market_type(ts_code: str) -> MarketType:
    """根据股票代码前缀判定所属板块。

    入参：
        ts_code: 股票代码，可带交易所后缀（如 600000.SH）

    返回：
        MarketType 枚举值；无法识别时默认返回 MAIN_BOARD
    """
    code = _clean_ts_code(ts_code)
    if not code:
        return MarketType.MAIN_BOARD

    for prefix, mtype, _desc in _CODE_PREFIX_MAP:
        if code.startswith(prefix):
            return mtype

    return MarketType.MAIN_BOARD


# ═══════════════════════════════════════════════════════════════
# 4. ST 判定
# ═══════════════════════════════════════════════════════════════

_ST_PATTERN = re.compile(r'^(\*?ST|SST)', re.IGNORECASE)


def is_st_stock(name: str) -> bool:
    """判断股票名称是否为 ST。

    入参：
        name: 股票名称（如 'ST康美', '*ST盐湖', '贵州茅台'）

    返回：
        bool
    """
    if not name:
        return False
    return bool(_ST_PATTERN.match(name))


# ═══════════════════════════════════════════════════════════════
# 5. 涨跌停价格边界计算
# ═══════════════════════════════════════════════════════════════

def calc_price_boundary(
    prev_close: float,
    market_type: MarketType,
    is_ipo_first_day: bool = False,
    point_value: float = 0.01,
) -> Tuple[float, float]:
    """计算涨跌停价格边界。

    入参：
        prev_close: 前收盘价
        market_type: 板块类型
        is_ipo_first_day: 是否为 IPO 上市首日（仅主板有特殊规则）
        point_value: 最小变动价位（默认 0.01）

    返回：
        (limit_up_price, limit_down_price) 元组
    """
    if is_ipo_first_day and market_type == MarketType.MAIN_BOARD:
        up_ratio = IPO_LIMIT_UP_RATIO
        down_ratio = IPO_LIMIT_DOWN_RATIO
    else:
        up_ratio = LIMIT_UP_RATIO.get(market_type, 0.10)
        down_ratio = LIMIT_DOWN_RATIO.get(market_type, -0.10)

    limit_up = round(prev_close * (1 + up_ratio) / point_value) * point_value
    limit_down = round(prev_close * (1 + down_ratio) / point_value) * point_value

    # 安全保护：涨停价不低于前收盘，跌停价不高于前收盘
    if limit_up < prev_close:
        limit_up = prev_close
    if limit_down > prev_close:
        limit_down = prev_close

    # 修复浮点精度问题，确保跌停价 < 前收盘（除非前收盘为 0）
    if prev_close > 0 and limit_down >= prev_close:
        limit_down = prev_close - point_value

    return limit_up, limit_down


# ═══════════════════════════════════════════════════════════════
# 6. 涨跌停交易预检
# ═══════════════════════════════════════════════════════════════

def check_limit_trade(
    bar: object,
    side: str,
    prev_close: Optional[float] = None,
    market_type: Optional[MarketType] = None,
) -> Tuple[bool, str]:
    """检查指定交易方向是否被涨跌停限制。

    入参：
        bar: K 线对象，需有 close, symbol, limit_up_price, limit_down_price 等属性
        side: 交易方向，'buy' | 'sell'
        prev_close: 前收盘价（可选，用于自动计算边界）
        market_type: 板块类型（可选，自动推断）

    返回：
        (allowed: bool, reason: str)
        allowed=True 表示交易允许，reason 为空字符串
        allowed=False 表示交易被禁止，reason 包含原因说明
    """
    current_price = getattr(bar, 'close', None)
    if current_price is None:
        return True, ""

    # 获取或计算涨停/跌停价
    limit_up = getattr(bar, 'limit_up_price', None)
    limit_down = getattr(bar, 'limit_down_price', None)

    if limit_up is None or limit_down is None:
        # 需要自动计算
        if prev_close is None:
            prev_close = getattr(bar, 'prev_close', None)
        if prev_close is None:
            return True, ""

        if market_type is None:
            symbol = getattr(bar, 'symbol', '')
            # ST 特殊处理：若名称含 ST 则用 ST 板块
            stock_name = getattr(bar, 'name', '')
            if stock_name and is_st_stock(stock_name):
                mt = MarketType.ST
            else:
                mt = get_market_type(symbol)
        else:
            mt = market_type

        limit_up, limit_down = calc_price_boundary(prev_close, mt)

    # 检查涨跌停限制
    if side == 'buy':
        if math.isclose(current_price, limit_up, rel_tol=1e-9, abs_tol=1e-4):
            return False, f"涨停限制：当前价 {current_price} 已达涨停价 {limit_up}"
    elif side == 'sell':
        if math.isclose(current_price, limit_down, rel_tol=1e-9, abs_tol=1e-4):
            return False, f"跌停限制：当前价 {current_price} 已达跌停价 {limit_down}"

    return True, ""


# ═══════════════════════════════════════════════════════════════
# 7. K线注入涨跌停边界
# ═══════════════════════════════════════════════════════════════

def enrich_bar_with_boundary(
    bar: object,
    prev_close: Optional[float] = None,
    market_type: Optional[MarketType] = None,
) -> None:
    """向 K 线对象注入涨跌停边界属性（in-place）。

    注入属性：
        - limit_up_price: 涨停价
        - limit_down_price: 跌停价
        - market_type: 板块标识字符串

    入参：
        bar: K 线对象，需有 close 和 symbol 属性
        prev_close: 前收盘价（可选，默认从 bar.prev_close 获取）
        market_type: 板块类型（可选，自动推断）
    """
    if prev_close is None:
        prev_close = getattr(bar, 'prev_close', None)
    if prev_close is None:
        prev_close = getattr(bar, 'close', prev_close)

    if market_type is None:
        symbol = getattr(bar, 'symbol', '')
        stock_name = getattr(bar, 'name', '')
        if stock_name and is_st_stock(stock_name):
            market_type = MarketType.ST
        else:
            market_type = get_market_type(symbol)

    limit_up, limit_down = calc_price_boundary(prev_close, market_type)

    bar.limit_up_price = limit_up
    bar.limit_down_price = limit_down
    bar.market_type = market_type.value
