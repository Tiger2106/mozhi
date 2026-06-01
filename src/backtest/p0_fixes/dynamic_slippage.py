"""
P1_002b — DynamicSlippage 模型
==============================
自包含模块，内联上游流动性分档接口。
替代原 FixedSlippage/RatioSlippage，根据标的流动性分档自动调整滑点率。

滑点公式：base_rate * size_multiplier * volatility_factor

依赖：无（内联 LiquidityTier / classify_liquidity / BASE_SLIPPAGE_RATE）
"""

import enum
import math
from typing import Optional


# ---------------------------------------------------------------------------
# 内联上游接口 —— 流动性分档
# ---------------------------------------------------------------------------

class LiquidityTier(enum.Enum):
    """流动性分档枚举"""
    MEGA_CAP = "mega"      # 超大盘
    LARGE_CAP = "large"    # 大盘
    MID_CAP = "mid"        # 中盘
    SMALL_CAP = "small"    # 小盘


# 各分档基础滑点率（双边，小数表示）
BASE_SLIPPAGE_RATE = {
    LiquidityTier.MEGA_CAP: 0.0005,   # 0.05%
    LiquidityTier.LARGE_CAP: 0.0010,  # 0.10%
    LiquidityTier.MID_CAP: 0.0015,    # 0.15%
    LiquidityTier.SMALL_CAP: 0.0030,  # 0.30%
}

# 市值分档阈值（亿元）
MARKET_CAP_THRESHOLDS = [
    (3000, LiquidityTier.MEGA_CAP),
    (500, LiquidityTier.LARGE_CAP),
    (100, LiquidityTier.MID_CAP),
]

# 板块 -> 流动性倾向乘数（如果市值无法判定，用板块兜底）
BOARD_LIQUIDITY_MAP = {
    "688": LiquidityTier.SMALL_CAP,    # 科创板
    "300": LiquidityTier.MID_CAP,      # 创业板
    "000": LiquidityTier.LARGE_CAP,    # 深证主板
    "002": LiquidityTier.MID_CAP,      # 中小板
    "600": LiquidityTier.LARGE_CAP,    # 上证主板
    "601": LiquidityTier.LARGE_CAP,    # 上证主板
    "603": LiquidityTier.MID_CAP,      # 上证主板（偏中）
    "605": LiquidityTier.MID_CAP,      # 上证主板
    "830": LiquidityTier.SMALL_CAP,    # 北交所
    "920": LiquidityTier.SMALL_CAP,    # 北交所（新）
    "4": LiquidityTier.SMALL_CAP,      # 老三板
    "8": LiquidityTier.SMALL_CAP,      # 新三板
}


def classify_liquidity(
    market_cap: Optional[float] = None,
    board_code: Optional[str] = None,
) -> LiquidityTier:
    """
    根据市值和板块代码判断流动性分档。

    优先级：
    1. 有 market_cap → 按阈值分档
    2. 无 market_cap，有 board_code → 按板块映射
    3. 两者皆无 → 返回 MID_CAP（中性默认）
    """
    if market_cap is not None:
        for threshold, tier in MARKET_CAP_THRESHOLDS:
            if market_cap >= threshold:
                return tier
        # 低于最小阈值 → SMALL_CAP
        return LiquidityTier.SMALL_CAP

    if board_code is not None:
        board_prefix = board_code.strip()[:3]
        for prefix, tier in BOARD_LIQUIDITY_MAP.items():
            if board_prefix.startswith(prefix):
                return tier
        # 未知板块，取板前第一个字符再试
        short_prefix = board_code.strip()[:1]
        for prefix, tier in BOARD_LIQUIDITY_MAP.items():
            if short_prefix.startswith(prefix):
                return tier

    return LiquidityTier.MID_CAP


# ---------------------------------------------------------------------------
# 滑点模型 —— DynamicSlippage
# ---------------------------------------------------------------------------

class DynamicSlippage:
    """
    动态滑点模型——替代原 FixedSlippage/RatioSlippage。

    根据标的的流动性分档自动调整滑点率。

    滑点公式：base_rate * size_multiplier * volatility_factor

    - base_rate：根据流动性分档选择 BASE_SLIPPAGE_RATE
    - size_multiplier：订单金额占日均成交额比例（0~1），越大滑点越高
    - volatility_factor：近期波动率调整（可选，默认 1.0）
    """

    # default_tier 映射：字符串 -> LiquidityTier
    DEFAULT_TIER_MAP = {
        "mega": LiquidityTier.MEGA_CAP,
        "large": LiquidityTier.LARGE_CAP,
        "mid": LiquidityTier.MID_CAP,
        "small": LiquidityTier.SMALL_CAP,
    }

    def __init__(self, default_tier: str = "mid"):
        if default_tier not in self.DEFAULT_TIER_MAP:
            raise ValueError(
                f"无效 default_tier: '{default_tier}'. "
                f"可选: {list(self.DEFAULT_TIER_MAP.keys())}"
            )
        self.default_tier = default_tier

    def _resolve_tier(
        self,
        market_cap: Optional[float] = None,
        board_code: Optional[str] = None,
    ) -> LiquidityTier:
        """解析流动性分档，None 参数回退到 default_tier"""
        if market_cap is not None or board_code is not None:
            return classify_liquidity(market_cap, board_code)
        return self.DEFAULT_TIER_MAP[self.default_tier]

    def get_slippage_rate(
        self,
        market_cap: Optional[float] = None,
        board_code: Optional[str] = None,
        order_value: Optional[float] = None,
        daily_volume_value: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> float:
        """
        计算动态滑点率。

        1. 确定 liquidity_tier（classify_liquidity）
        2. base_rate = BASE_SLIPPAGE_RATE[tier]
        3. size_multiplier = min(1.0, order_value / max(daily_volume_value, 1))
           （若缺省 order_value 或 daily_volume_value，size_multiplier=1.0）
        4. volatility_factor = min(2.0, max(0.5, volatility / 0.02))
           （若缺省 volatility，volatility_factor=1.0）
        5. return base_rate * size_multiplier * volatility_factor
        """
        # 1. 确定流动性分档
        tier = self._resolve_tier(market_cap, board_code)
        base_rate = BASE_SLIPPAGE_RATE[tier]

        # 2. size multiplier（订单金额占比）
        size_multiplier = 1.0
        if order_value is not None and daily_volume_value is not None:
            ratio = order_value / max(daily_volume_value, 1.0)
            size_multiplier = min(1.0, ratio)

        # 3. volatility factor（波动率调整）
        vol_factor = 1.0
        if volatility is not None:
            base_vol = 0.02  # 基准波动率 2%
            vol_factor = volatility / base_vol
            vol_factor = max(0.5, min(2.0, vol_factor))

        # 4. 合成滑点率
        rate = base_rate * size_multiplier * vol_factor
        return rate

    def calculate_slippage(
        self,
        price: float,
        qty: int,
        market_cap: Optional[float] = None,
        board_code: Optional[str] = None,
        daily_volume_value: Optional[float] = None,
        volatility: Optional[float] = None,
    ) -> dict:
        """
        计算一笔交易的滑点成本。

        参数
        ----
        price : float
            订单价格
        qty : int
            订单数量（正数为买入，负数为卖出）
        market_cap : float, optional
            市值（亿元）
        board_code : str, optional
            板块代码
        daily_volume_value : float, optional
            日均成交额（元）
        volatility : float, optional
            近期波动率（小数，如 0.03 表示 3%）

        返回
        ----
        dict : {
            "rate": float,          # 滑点率
            "cost": float,          # 滑点成本（金额）
            "effective_price": float, # 滑点后的有效成交价格
            "details": dict         # 明细
        }

        effective_price：
          - qty > 0（买单）：成交价向上偏离 = price * (1 + rate)
          - qty < 0（卖单）：成交价向下偏离 = price * (1 - rate)
        """
        order_value = abs(price * qty)
        rate = self.get_slippage_rate(
            market_cap=market_cap,
            board_code=board_code,
            order_value=order_value,
            daily_volume_value=daily_volume_value,
            volatility=volatility,
        )

        cost = order_value * rate

        if qty > 0:
            effective_price = price * (1.0 + rate)
        else:
            effective_price = price * (1.0 - rate)

        return {
            "rate": rate,
            "cost": round(cost, 4),
            "effective_price": round(effective_price, 6),
            "details": {
                "order_value": order_value,
                "tier": self._resolve_tier(market_cap, board_code).value,
                "base_rate": BASE_SLIPPAGE_RATE[self._resolve_tier(market_cap, board_code)],
            },
        }

    def set_default_tier(self, tier: str):
        """修改默认流动性分档"""
        if tier not in self.DEFAULT_TIER_MAP:
            raise ValueError(
                f"无效 default_tier: '{tier}'. "
                f"可选: {list(self.DEFAULT_TIER_MAP.keys())}"
            )
        self.default_tier = tier
