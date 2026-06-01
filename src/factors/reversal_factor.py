"""
反转因子计算模块

基于后复权价格（adj_close_b）计算 3 个反转类因子：
  1. Reversal_1D（短周期1日收益反转）：
     adj_close_b[t-1]/adj_close_b[t-2] - 1
  2. Reversal_5D（5日收益反转）：
     adj_close_b[t-1]/adj_close_b[t-6] - 1
  3. Reversal_10D（10日收益反转）：
     adj_close_b[t-1]/adj_close_b[t-11] - 1

所有因子继承 FactorBase，注册类别为 'reversal'。
使用 iloc[-2] 避免前视偏差（前一交易日收盘价，不含当日）。
停牌股票返回 None（由基类 SuspensionHandler 自动处理）。

验收标准（IC_PIPELINE_T14_008）：
  - 3个反转因子在计算日期均有非None的因子值
  - 停牌股票返回 None

Author: 墨衡
Created: 2026-05-30T11:10:00+08:00
Version: v1
"""

from typing import Optional

import pandas as pd
import numpy as np

from src.factors.base import FactorBase


# ═══════════════════════════════════════════════════════════════
# Reversal_1D — 短周期1日收益反转
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-1] / adj_close_b[t-2] - 1
# 说明：前一交易日相对于前两交易日的收益，衡量极短期反转效应。
#       正值表示前一交易日上涨（短期延续），负值表示前一交易日下跌。
#       作为反转因子使用时通常取原始值（不做符号反转），
#       与预期方向（负相关）通过IC计算时的符号检验来判定。
# 需至少 3 行有效数据。
# ═══════════════════════════════════════════════════════════════

class Reversal1D(FactorBase):
    """短周期1日收益反转因子。

    计算前一交易日相对于前两交易日的收益反转：
      reversal_1d = adj_close_b[t-1] / adj_close_b[t-2] - 1

    使用后复权收盘价 adj_close_b，采用 iloc[-2] 位置获取前一交易日价格，
    iloc[-3] 获取前两交易日价格，避免前视偏差。
    需至少3行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 5):
        super().__init__(
            db_manager=db_manager,
            name='reversal_1d',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Reversal_1D 因子值。

        Args:
            df: 该股票的有效历史数据 DataFrame（含 adj_close_b, trade_date 等列），
                由基类 SuspensionHandler.filter_valid_data 过滤停牌日，
                按 trade_date 正序排列。

        Returns:
            float or None: 反转因子值。数据不足3行返回 None。
        """
        if df is None or len(df) < 3:
            return None

        try:
            # t-1: 前一交易日后复权收盘价
            price_t_minus_1 = df['adj_close_b'].iloc[-2]
            # t-2: 前两交易日后复权收盘价
            price_t_minus_2 = df['adj_close_b'].iloc[-3]

            # 空值/NaN检查
            if price_t_minus_1 is None or price_t_minus_2 is None:
                return None
            if isinstance(price_t_minus_1, float) and np.isnan(price_t_minus_1):
                return None
            if isinstance(price_t_minus_2, float) and np.isnan(price_t_minus_2):
                return None
            if price_t_minus_2 == 0:
                return None

            result = price_t_minus_1 / price_t_minus_2 - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# Reversal_5D — 5日收益反转
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-1] / adj_close_b[t-6] - 1
# 说明：前一交易日相对于6个交易日前（约1个交易周）的收益。
#       正值表示过去5个交易日下跌（高回报后回归均值），
#       负值表示过去5个交易日上涨（低回报后回归均值）。
#       与 momentum_5d 含义类似但使用后复权价格口径，
#       且不含当日（前视偏差控制）。
# 需至少 7 行有效数据。
# ═══════════════════════════════════════════════════════════════

class Reversal5D(FactorBase):
    """5日收益反转因子。

    计算前一交易日相对于6个交易日前（约1周）的收益反转：
      reversal_5d = adj_close_b[t-1] / adj_close_b[t-6] - 1

    使用 iloc[-2] 获取前一交易日价格，iloc[-7] 获取6个交易日前价格。
    需至少7行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 10):
        super().__init__(
            db_manager=db_manager,
            name='reversal_5d',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Reversal_5D 因子值。

        Args:
            df: 该股票的有效历史数据，按 trade_date 正序排列。

        Returns:
            float or None: 反转因子值。数据不足7行返回 None。
        """
        if df is None or len(df) < 7:
            return None

        try:
            # t-1: 前一交易日后复权收盘价
            price_t_minus_1 = df['adj_close_b'].iloc[-2]
            # t-6: 6个交易日后复权收盘价
            price_t_minus_6 = df['adj_close_b'].iloc[-7]

            if price_t_minus_1 is None or price_t_minus_6 is None:
                return None
            if isinstance(price_t_minus_1, float) and np.isnan(price_t_minus_1):
                return None
            if isinstance(price_t_minus_6, float) and np.isnan(price_t_minus_6):
                return None
            if price_t_minus_6 == 0:
                return None

            result = price_t_minus_1 / price_t_minus_6 - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# Reversal_10D — 10日收益反转
# ═══════════════════════════════════════════════════════════════
#
# 公式：adj_close_b[t-1] / adj_close_b[t-11] - 1
# 说明：前一交易日相对于11个交易日前（约2个交易周）的收益。
#       捕捉两周价格反转效应。中期反转因子常使用10日或20日窗口，
#       为覆盖反转因子的多周期维度，补充10日反转。
# 需至少 12 行有效数据。
# ═══════════════════════════════════════════════════════════════

class Reversal10D(FactorBase):
    """10日收益反转因子。

    计算前一交易日相对于11个交易日前（约2周）的收益反转：
      reversal_10d = adj_close_b[t-1] / adj_close_b[t-11] - 1

    使用 iloc[-2] 获取前一交易日价格，iloc[-12] 获取11个交易日前价格。
    需至少12行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 15):
        super().__init__(
            db_manager=db_manager,
            name='reversal_10d',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Reversal_10D 因子值。

        Args:
            df: 该股票的有效历史数据，按 trade_date 正序排列。

        Returns:
            float or None: 反转因子值。数据不足12行返回 None。
        """
        if df is None or len(df) < 12:
            return None

        try:
            # t-1: 前一交易日后复权收盘价
            price_t_minus_1 = df['adj_close_b'].iloc[-2]
            # t-11: 11个交易日后复权收盘价
            price_t_minus_11 = df['adj_close_b'].iloc[-12]

            if price_t_minus_1 is None or price_t_minus_11 is None:
                return None
            if isinstance(price_t_minus_1, float) and np.isnan(price_t_minus_1):
                return None
            if isinstance(price_t_minus_11, float) and np.isnan(price_t_minus_11):
                return None
            if price_t_minus_11 == 0:
                return None

            result = price_t_minus_1 / price_t_minus_11 - 1.0
            return None if (isinstance(result, float) and np.isnan(result)) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError) as e:
            return None


# ═══════════════════════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════════════════════

def create_reversal_factors(db_manager=None) -> list:
    """创建所有3个反转因子实例列表。

    Args:
        db_manager: 可选的 DatabaseManager 实例

    Returns:
        list[FactorBase]: [Reversal1D, Reversal5D, Reversal10D]
    """
    return [
        Reversal1D(db_manager=db_manager),
        Reversal5D(db_manager=db_manager),
        Reversal10D(db_manager=db_manager),
    ]


# ═══════════════════════════════════════════════════════════════
# 因子元数据
# ═══════════════════════════════════════════════════════════════

REVERSAL_FACTORS_META = [
    {
        "name": "reversal_1d",
        "class": "Reversal1D",
        "category": "reversal",
        "description": "1日收益反转：adj_close_b[t-1]/adj_close_b[t-2] - 1",
        "min_valid_rows": 3,
        "lookback": 5,
    },
    {
        "name": "reversal_5d",
        "class": "Reversal5D",
        "category": "reversal",
        "description": "5日收益反转：adj_close_b[t-1]/adj_close_b[t-6] - 1",
        "min_valid_rows": 7,
        "lookback": 10,
    },
    {
        "name": "reversal_10d",
        "class": "Reversal10D",
        "category": "reversal",
        "description": "10日收益反转：adj_close_b[t-1]/adj_close_b[t-11] - 1",
        "min_valid_rows": 12,
        "lookback": 15,
    },
]
