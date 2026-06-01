"""
动量因子计算模块

基于后复权价格（adj_close_b）计算 4 个动量类因子：
  1. Momentum_1M（20交易日）：adj_close_b[t-1]/adj_close_b[t-21] - 1
  2. Momentum_3M（60交易日）：adj_close_b[t-1]/adj_close_b[t-61] - 1
  3. Momentum_6M（120交易日）：adj_close_b[t-1]/adj_close_b[t-121] - 1
  4. Momentum_12M_1M（240交易日-20交易日，剔除近1个月）：
     adj_close_b[t-21]/adj_close_b[t-241] - 1

所有因子继承 FactorBase，注册类别为 'momentum'。
停牌股票返回 None（由基类 SuspensionHandler 自动处理）。

验收标准（IC_PIPELINE_T14_007）：
  - 4个动量因子在计算日期均有非None的因子值
  - 停牌股票返回 None

Author: 墨衡
Created: 2026-05-30T10:55:00+08:00
Version: v1
"""

from typing import Optional

import pandas as pd
import numpy as np

from src.factors.base import FactorBase


# ═══════════════════════════════════════════════════════════════
# Momentum_1M — 1个月动量（20个交易日）
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-1] / adj_close_b[t-21] - 1
# 说明：基于后复权收盘价，计算过去20个交易日的涨跌幅（不含当日），
#       t-1 = 前一交易日，t-21 = 21个交易日前。
# 需至少 22 行有效数据。
# 停牌日由 SuspensionHandler 自动过滤，跳过停牌日按实际交易日定位。
# ═══════════════════════════════════════════════════════════════

class Momentum1M(FactorBase):
    """1个月动量因子（20个交易日）。

    计算过去20个交易日的价格动量，公式：
      momentum = adj_close_b[昨] / adj_close_b[21天前] - 1

    使用后复权收盘价 adj_close_b，确保截面上价格口径一致。
    需至少22行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 30):
        super().__init__(
            db_manager=db_manager,
            name='momentum_1m',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Momentum_1M 因子值。

        Args:
            df: 该股票的有效历史数据 DataFrame（含 adj_close_b, trade_date 等列），
                由基类 SuspensionHandler.filter_valid_data 过滤停牌日，
                按 trade_date 正序排列。

        Returns:
            float or None: 动量因子值。数据不足22行返回 None。
        """
        # 需至少22行：iloc[-1]=today, iloc[-2]=yesterday(t-1), iloc[-22]=t-21
        if df is None or len(df) < 22:
            return None

        try:
            # t-1: 前一交易日后复权收盘价
            price_yesterday = df['adj_close_b'].iloc[-2]
            # t-21: 21个交易日后复权收盘价
            price_21d_ago = df['adj_close_b'].iloc[-22]

            if price_yesterday is None or price_21d_ago is None:
                return None
            if isinstance(price_yesterday, float) and np.isnan(price_yesterday):
                return None
            if isinstance(price_21d_ago, float) and np.isnan(price_21d_ago):
                return None
            if price_yesterday == 0 or price_21d_ago == 0:
                return None

            result = price_yesterday / price_21d_ago - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# Momentum_3M — 3个月动量（60个交易日）
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-1] / adj_close_b[t-61] - 1
# 说明：过去60个交易日的涨跌幅（不含当日）。
# 需至少 62 行有效数据。
# ═══════════════════════════════════════════════════════════════

class Momentum3M(FactorBase):
    """3个月动量因子（60个交易日）。

    计算过去60个交易日的价格动量，公式：
      momentum = adj_close_b[昨] / adj_close_b[61天前] - 1

    需至少62行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 70):
        super().__init__(
            db_manager=db_manager,
            name='momentum_3m',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Momentum_3M 因子值。

        Args:
            df: 该股票的有效历史数据，按 trade_date 正序排列。

        Returns:
            float or None: 动量因子值。数据不足62行返回 None。
        """
        if df is None or len(df) < 62:
            return None

        try:
            price_yesterday = df['adj_close_b'].iloc[-2]
            price_61d_ago = df['adj_close_b'].iloc[-62]

            if price_yesterday is None or price_61d_ago is None:
                return None
            if isinstance(price_yesterday, float) and np.isnan(price_yesterday):
                return None
            if isinstance(price_61d_ago, float) and np.isnan(price_61d_ago):
                return None
            if price_yesterday == 0 or price_61d_ago == 0:
                return None

            result = price_yesterday / price_61d_ago - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# Momentum_6M — 6个月动量（120个交易日）
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-1] / adj_close_b[t-121] - 1
# 说明：过去120个交易日的涨跌幅（不含当日）。
# 需至少 122 行有效数据。
# ═══════════════════════════════════════════════════════════════

class Momentum6M(FactorBase):
    """6个月动量因子（120个交易日）。

    计算过去120个交易日的价格动量，公式：
      momentum = adj_close_b[昨] / adj_close_b[121天前] - 1

    需至少122行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 130):
        super().__init__(
            db_manager=db_manager,
            name='momentum_6m',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Momentum_6M 因子值。

        Args:
            df: 该股票的有效历史数据，按 trade_date 正序排列。

        Returns:
            float or None: 动量因子值。数据不足122行返回 None。
        """
        if df is None or len(df) < 122:
            return None

        try:
            price_yesterday = df['adj_close_b'].iloc[-2]
            price_121d_ago = df['adj_close_b'].iloc[-122]

            if price_yesterday is None or price_121d_ago is None:
                return None
            if isinstance(price_yesterday, float) and np.isnan(price_yesterday):
                return None
            if isinstance(price_121d_ago, float) and np.isnan(price_121d_ago):
                return None
            if price_yesterday == 0 or price_121d_ago == 0:
                return None

            result = price_yesterday / price_121d_ago - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# Momentum_12M_1M — 12个月扣除近1个月动量（220个交易日）
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-21] / adj_close_b[t-241] - 1
# 说明：从12个月前到1个月前的价格涨跌幅（不含近1个月），
#       即过去 220 个交易日的动量（不含最近20个交易日）。
#       常用于判断剔除短期噪音后的中期趋势。
# 需至少 242 行有效数据。
# ═══════════════════════════════════════════════════════════════

class Momentum12M1M(FactorBase):
    """12个月剔除近1个月动量因子（220个交易日=240-20）。

    从241个交易日前到21个交易日前（即从近12个月剔除近1个月）的价格动量：
      momentum = adj_close_b[21天前] / adj_close_b[241天前] - 1

    用于评估剔除短期扰动后的中期趋势，需至少242行有效数据。
    """

    def __init__(self, db_manager=None, lookback: int = 260):
        super().__init__(
            db_manager=db_manager,
            name='momentum_12m_1m',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Momentum_12M_1M 因子值。

        Args:
            df: 该股票的有效历史数据，按 trade_date 正序排列。

        Returns:
            float or None: 动量因子值。数据不足242行返回 None。
        """
        if df is None or len(df) < 242:
            return None

        try:
            # t-21: 21个交易日前后复权收盘价（剔除近1个月起点）
            price_21d_ago = df['adj_close_b'].iloc[-22]
            # t-241: 241个交易日前后复权收盘价（12个月前起点）
            price_241d_ago = df['adj_close_b'].iloc[-242]

            if price_21d_ago is None or price_241d_ago is None:
                return None
            if isinstance(price_21d_ago, float) and np.isnan(price_21d_ago):
                return None
            if isinstance(price_241d_ago, float) and np.isnan(price_241d_ago):
                return None
            if price_21d_ago == 0 or price_241d_ago == 0:
                return None

            result = price_21d_ago / price_241d_ago - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# Momentum_5D — 5个交易日动量
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-1] / adj_close_b[t-6] - 1
# 说明：基于后复权收盘价，计算过去5个交易日的涨跌幅（不含当日），
#       t-1 = 前一交易日，t-6 = 6个交易日前（回看7日区间）。
# 需至少 7 行有效数据。
# 停牌日由 SuspensionHandler 自动过滤。
# ═══════════════════════════════════════════════════════════════

class Momentum5D(FactorBase):
    """5个交易日动量因子（回看7日）。

    计算过去5个交易日的价格动量，公式：
      momentum = adj_close_b[昨] / adj_close_b[6天前] - 1

    使用后复权收盘价 adj_close_b，确保截面上价格口径一致。
    需至少7行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 15):
        super().__init__(
            db_manager=db_manager,
            name='momentum_5d',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Momentum_5D 因子值。

        Args:
            df: 该股票的有效历史数据 DataFrame（含 adj_close_b, trade_date 等列），
                由基类 SuspensionHandler.filter_valid_data 过滤停牌日，
                按 trade_date 正序排列。

        Returns:
            float or None: 动量因子值。数据不足7行返回 None。
        """
        # 需至少7行：iloc[-1]=today, iloc[-2]=yesterday(t-1), iloc[-7]=t-6
        if df is None or len(df) < 7:
            return None

        try:
            # t-1: 前一交易日后复权收盘价
            price_yesterday = df['adj_close_b'].iloc[-2]
            # t-6: 6个交易日后复权收盘价
            price_6d_ago = df['adj_close_b'].iloc[-7]

            if price_yesterday is None or price_6d_ago is None:
                return None
            if isinstance(price_yesterday, float) and np.isnan(price_yesterday):
                return None
            if isinstance(price_6d_ago, float) and np.isnan(price_6d_ago):
                return None
            if price_yesterday == 0 or price_6d_ago == 0:
                return None

            result = price_yesterday / price_6d_ago - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# 别名类：momentum_20d / momentum_60d / momentum_120d
# 复用对应月频因子的计算逻辑，仅名称不同
# ═══════════════════════════════════════════════════════════════

class Momentum20D(Momentum1M):
    """20个交易日动量别名，复用 Momentum1M 逻辑。

    公式：adj_close_b[t-1] / adj_close_b[t-21] - 1
    名称：momentum_20d（与 §4.1.1 命名对齐）
    """

    def __init__(self, db_manager=None, lookback: int = 30):
        super().__init__(db_manager=db_manager, lookback=lookback)
        self.name = 'momentum_20d'


class Momentum60D(Momentum3M):
    """60个交易日动量别名，复用 Momentum3M 逻辑。

    公式：adj_close_b[t-1] / adj_close_b[t-61] - 1
    名称：momentum_60d（与 §4.1.1 命名对齐）
    """

    def __init__(self, db_manager=None, lookback: int = 70):
        super().__init__(db_manager=db_manager, lookback=lookback)
        self.name = 'momentum_60d'


class Momentum120D(Momentum6M):
    """120个交易日动量别名，复用 Momentum6M 逻辑。

    公式：adj_close_b[t-1] / adj_close_b[t-121] - 1
    名称：momentum_120d（与 §4.1.1 命名对齐）
    """

    def __init__(self, db_manager=None, lookback: int = 130):
        super().__init__(db_manager=db_manager, lookback=lookback)
        self.name = 'momentum_120d'


# ═══════════════════════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════════════════════

def create_momentum_factors(db_manager=None) -> list:
    """创建所有动量因子实例列表（含别名）。

    Args:
        db_manager: 可选的 DatabaseManager 实例

    Returns:
        list[FactorBase]: [Momentum5D, Momentum1M, Momentum20D, Momentum3M,
                           Momentum60D, Momentum6M, Momentum120D, Momentum12M1M]
    """
    return [
        Momentum5D(db_manager=db_manager),
        Momentum1M(db_manager=db_manager),
        Momentum20D(db_manager=db_manager),
        Momentum3M(db_manager=db_manager),
        Momentum60D(db_manager=db_manager),
        Momentum6M(db_manager=db_manager),
        Momentum120D(db_manager=db_manager),
        Momentum12M1M(db_manager=db_manager),
    ]


# ═══════════════════════════════════════════════════════════════
# 因子元数据
# ═══════════════════════════════════════════════════════════════

MOMENTUM_FACTORS_META = [
    {
        "name": "momentum_5d",
        "class": "Momentum5D",
        "category": "momentum",
        "description": "5个交易日动量（回看7日）：adj_close_b[t-1]/adj_close_b[t-6] - 1",
        "min_valid_rows": 7,
        "lookback": 15,
    },
    {
        "name": "momentum_1m",
        "class": "Momentum1M",
        "category": "momentum",
        "description": "1个月动量（20交易日）：adj_close_b[t-1]/adj_close_b[t-21] - 1",
        "min_valid_rows": 22,
        "lookback": 30,
        "aliases": ["momentum_20d"],
    },
    {
        "name": "momentum_20d",
        "class": "Momentum20D",
        "category": "momentum",
        "description": "20个交易日动量别名，复用 Momentum1M 逻辑",
        "min_valid_rows": 22,
        "lookback": 30,
    },
    {
        "name": "momentum_3m",
        "class": "Momentum3M",
        "category": "momentum",
        "description": "3个月动量（60交易日）：adj_close_b[t-1]/adj_close_b[t-61] - 1",
        "min_valid_rows": 62,
        "lookback": 70,
        "aliases": ["momentum_60d"],
    },
    {
        "name": "momentum_60d",
        "class": "Momentum60D",
        "category": "momentum",
        "description": "60个交易日动量别名，复用 Momentum3M 逻辑",
        "min_valid_rows": 62,
        "lookback": 70,
    },
    {
        "name": "momentum_6m",
        "class": "Momentum6M",
        "category": "momentum",
        "description": "6个月动量（120交易日）：adj_close_b[t-1]/adj_close_b[t-121] - 1",
        "min_valid_rows": 122,
        "lookback": 130,
        "aliases": ["momentum_120d"],
    },
    {
        "name": "momentum_120d",
        "class": "Momentum120D",
        "category": "momentum",
        "description": "120个交易日动量别名，复用 Momentum6M 逻辑",
        "min_valid_rows": 122,
        "lookback": 130,
    },
    {
        "name": "momentum_12m_1m",
        "class": "Momentum12M1M",
        "category": "momentum",
        "description": "12个月剔除近1个月动量（220交易日=240-20）：adj_close_b[t-21]/adj_close_b[t-241] - 1",
        "min_valid_rows": 242,
        "lookback": 260,
    },
]
