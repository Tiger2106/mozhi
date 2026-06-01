"""
墨枢 - p0_fixes.liquidity_model
流动性分档模型：根据流通市值或板块代码对标的进行流动性分级，
并为每个等级提供基准滑点率。

author: moheng
created_time: 2026-05-28T12:11+08:00
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# LiquidityTier 枚举 — 流动性分档
# ═══════════════════════════════════════════════════════════════


class LiquidityTier(Enum):
    """流动性等级枚举。

    按流通市值划分四个等级：
      - MEGA_CAP:  超大市值（≥500 亿）
      - LARGE_CAP:  大盘股  （≥200 亿，<500 亿）
      - MID_CAP:    中盘股  （≥50 亿， <200 亿）
      - SMALL_CAP:  小盘股  （<50 亿）
    """

    MEGA_CAP = "mega"
    LARGE_CAP = "large"
    MID_CAP = "mid"
    SMALL_CAP = "small"


# ═══════════════════════════════════════════════════════════════
# BASE_SLIPPAGE_RATE — 各等级基准滑点率
# ═══════════════════════════════════════════════════════════════

BASE_SLIPPAGE_RATE: dict[LiquidityTier, float] = {
    LiquidityTier.MEGA_CAP: 0.0005,   # 0.05% — 超大市值，流动性极佳
    LiquidityTier.LARGE_CAP: 0.0010,  # 0.10% — 大盘股，流动性良好
    LiquidityTier.MID_CAP: 0.0015,    # 0.15% — 中盘股，流动性一般
    LiquidityTier.SMALL_CAP: 0.0030,  # 0.30% — 小盘股，流动性较差
}


def get_slippage_rate(tier: LiquidityTier) -> float:
    """获取给定流动性等级的基准滑点率。

    Parameters
    ----------
    tier : LiquidityTier
        流动性等级。

    Returns
    -------
    float
        对应的基准滑点率。
    """
    return BASE_SLIPPAGE_RATE[tier]


# ═══════════════════════════════════════════════════════════════
# classify_liquidity — 根据流通市值判定流动性等级
# ═══════════════════════════════════════════════════════════════

# 流通市值边界常量（单位：亿）
_MEGA_CAP_THRESHOLD: float = 500.0  # 超大盘阈值
_LARGE_CAP_THRESHOLD: float = 200.0  # 大盘阈值
_MID_CAP_THRESHOLD: float = 50.0    # 中盘阈值

# 板块代码前缀 → 备选流动性等级映射（当市值数据不可用时的回退）
_BOARD_CODE_TIER_MAP: dict[str, LiquidityTier] = {
    # 主板大市值：6xxxxx（上海主板）、00xxxx（深圳主板）
    "60": LiquidityTier.LARGE_CAP,
    "00": LiquidityTier.LARGE_CAP,
    # 创业板：30xxxx、科创板：688xxx
    "30": LiquidityTier.MID_CAP,
    "688": LiquidityTier.MID_CAP,
    # 北交所：8xxxxx
    "8": LiquidityTier.MID_CAP,
    # ST 股：带 ST 标识的归类为小盘
}

# 被标记为 ST/ST* 的板块后缀
_ST_SUFFIXES = ("ST", "*ST")


def classify_liquidity(
    market_cap: Optional[float] = None,
    board_code: Optional[str] = None,
) -> LiquidityTier:
    """根据流通市值判定流动性等级。

    优先使用 market_cap（亿）进行精确判定。
    若 market_cap 为 None 或无效值，则回退到 board_code 做备选判定。

    Parameters
    ----------
    market_cap : Optional[float]
        流通市值（单位：亿）。None 或 <=0 时视为无效。
    board_code : Optional[str]
        板块代码（如 "600000", "300750", "688981"）。
        也可附带 ST 后缀（如 "600123ST"），匹配时自动识别。

    Returns
    -------
    LiquidityTier
        判定得到的流动性等级。

    Raises
    ------
    ValueError
        当 market_cap 无效且 board_code 也未提供时。
    """
    # ── 优先：根据流通市值判定 ──
    if market_cap is not None and market_cap > 0:
        return _classify_by_market_cap(market_cap)

    # ── 备选：根据板块代码判定 ──
    if board_code is not None and len(board_code) >= 2:
        return _classify_by_board_code(board_code)

    raise ValueError(
        "无法判定流动性等级：market_cap 无效且未提供 board_code"
    )


def _classify_by_market_cap(market_cap: float) -> LiquidityTier:
    """仅根据流通市值（亿）判定流动性等级。"""
    # P1 确定边界规则：≥500亿→MEGA, ≥200亿→LARGE, ≥50亿→MID, <50亿→SMALL
    if market_cap >= _MEGA_CAP_THRESHOLD:  # ≥ 500亿
        return LiquidityTier.MEGA_CAP
    if market_cap >= _LARGE_CAP_THRESHOLD:  # ≥ 200亿
        return LiquidityTier.LARGE_CAP
    if market_cap >= _MID_CAP_THRESHOLD:    # ≥ 50亿
        return LiquidityTier.MID_CAP
    return LiquidityTier.SMALL_CAP           # < 50亿


def _classify_by_board_code(board_code: str) -> LiquidityTier:
    """仅根据板块代码做备选判定。

    回退策略：
      - 主板大市值（60xxxx / 00xxxx）→ LARGE_CAP
      - 创业板（30xxxx）/ 科创板（688xxx）/ 北交所（8xxxxx）→ MID_CAP
      - ST/ST* 股 → SMALL_CAP
    """
    # 先检查是否是 ST 股（后缀匹配）
    code_upper = board_code.upper()
    for suffix in _ST_SUFFIXES:
        if code_upper.endswith(suffix) or code_upper.endswith(suffix.replace("*", "")):
            return LiquidityTier.SMALL_CAP

    # 按前缀匹配
    # 按字符串长度降序匹配，优先匹配更长的前缀
    prefix_map = [
        ("688", LiquidityTier.MID_CAP),  # 科创板
        ("60", LiquidityTier.LARGE_CAP),  # 沪主板
        ("30", LiquidityTier.MID_CAP),    # 创业板
        ("00", LiquidityTier.LARGE_CAP),  # 深主板
        ("8", LiquidityTier.MID_CAP),     # 北交所
    ]

    for prefix, tier in prefix_map:
        if code_upper.startswith(prefix):
            return tier

    # 未知板块代码，默认 LARGE_CAP
    return LiquidityTier.LARGE_CAP


# ═══════════════════════════════════════════════════════════════
# 便利函数
# ═══════════════════════════════════════════════════════════════


def tier_name(tier: LiquidityTier) -> str:
    """返回可读的等级中文名称。"""
    names = {
        LiquidityTier.MEGA_CAP: "超大盘",
        LiquidityTier.LARGE_CAP: "大盘股",
        LiquidityTier.MID_CAP: "中盘股",
        LiquidityTier.SMALL_CAP: "小盘股",
    }
    return names[tier]
