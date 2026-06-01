"""
波动因子计算模块

基于后复权价格（adj_close_b）计算 3 个波动类因子：
  1. Volatility_1M（近20日波动率）：stdev(return_1d, 20) × sqrt(252)
  2. Volatility_3M（近60日波动率）：stdev(return_1d, 60) × sqrt(252)
  3. Volatility_6M（近120日波动率）：stdev(return_1d, 120) × sqrt(252)

return_1d = adj_close_b[t]/adj_close_b[t-1] - 1
使用 iloc[-2] 避免前视偏差（return_1d计算时使用t-1对应的价格）。

所有因子继承 FactorBase，注册类别为 'volatility'。
停牌股票返回 None（由基类 SuspensionHandler 自动处理）。

验收标准（IC_PIPELINE_T14_011）：
  - 3个波动因子在计算日期均有非None的因子值
  - 停牌股票返回 None

Author: 墨衡
Created: 2026-05-30T11:38:00+08:00
Version: v1
"""

from typing import Optional

import pandas as pd
import numpy as np

from src.factors.base import FactorBase


# ═══════════════════════════════════════════════════════════════
# Volatility_1M — 1个月波动率（20个交易日）
# ═══════════════════════════════════════════════════════════════
#
# 公式：stdev(return_1d, 20) × sqrt(252)
#       return_1d = adj_close_b[t-1] / adj_close_b[t-2] - 1
# 说明：基于后复权收盘价，计算过去20个交易日的日收益率年化标准差。
#       使用 iloc[-2] 作为参考价格，避免前视偏差。
# 需至少 22 行有效数据（21个价格 → 20个日收益率）。
# ═══════════════════════════════════════════════════════════════

class Volatility1M(FactorBase):
    """1个月波动率因子（20个交易日）。

    计算过去20个交易日的日收益率年化标准差：
      volatility = stdev(return_1d, 20) × sqrt(252)

    使用后复权收盘价 adj_close_b，采用 iloc[-2] 定位前一交易日价格，
    避免前视偏差。年化乘子 sqrt(252) 将日波动率转换为年化波动率。
    需至少22行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 30):
        super().__init__(
            db_manager=db_manager,
            name='volatility_1m',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Volatility_1M 因子值。

        Args:
            df: 该股票的有效历史数据 DataFrame（含 adj_close_b, trade_date 等列），
                由基类 SuspensionHandler.filter_valid_data 过滤停牌日，
                按 trade_date 正序排列。

        Returns:
            float or None: 年化波动率因子值。数据不足22行返回 None。
        """
        if df is None or len(df) < 22:
            return None

        try:
            # 提取过去21个交易日（t-1 至 t-21）的后复权收盘价
            # iloc[-22:-1]: 从倒数第22行到倒数第2行，共21个价格 → 20个日收益率
            prices = df['adj_close_b'].iloc[-22:-1].values
            if len(prices) < 21:
                return None

            # 计算日收益率序列：return_1d[t] = adj_close_b[t]/adj_close_b[t-1] - 1
            returns = prices[1:] / prices[:-1] - 1.0

            if len(returns) < 2:
                return None

            # 样本标准差（ddof=1），年化 × sqrt(252)
            std = np.std(returns, ddof=1)
            result = float(std * np.sqrt(252.0))

            return None if np.isnan(result) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None


# ═══════════════════════════════════════════════════════════════
# Volatility_3M — 3个月波动率（60个交易日）
# ═══════════════════════════════════════════════════════════════
#
# 公式：stdev(return_1d, 60) × sqrt(252)
#       return_1d = adj_close_b[t-1] / adj_close_b[t-2] - 1
# 说明：基于后复权收盘价，计算过去60个交易日的日收益率年化标准差。
#       使用 iloc[-2] 避免前视偏差。
# 需至少 62 行有效数据（61个价格 → 60个日收益率）。
# ═══════════════════════════════════════════════════════════════

class Volatility3M(FactorBase):
    """3个月波动率因子（60个交易日）。

    计算过去60个交易日的日收益率年化标准差：
      volatility = stdev(return_1d, 60) × sqrt(252)

    需至少62行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 80):
        super().__init__(
            db_manager=db_manager,
            name='volatility_3m',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Volatility_3M 因子值。

        Args:
            df: 该股票的有效历史数据，按 trade_date 正序排列。

        Returns:
            float or None: 年化波动率因子值。数据不足62行返回 None。
        """
        if df is None or len(df) < 62:
            return None

        try:
            # 提取过去61个交易日（t-1 至 t-61）的后复权收盘价
            # iloc[-62:-1]: 从倒数第62行到倒数第2行，共61个价格 → 60个日收益率
            prices = df['adj_close_b'].iloc[-62:-1].values
            if len(prices) < 61:
                return None

            # 计算日收益率序列
            returns = prices[1:] / prices[:-1] - 1.0

            if len(returns) < 2:
                return None

            # 样本标准差（ddof=1），年化 × sqrt(252)
            std = np.std(returns, ddof=1)
            result = float(std * np.sqrt(252.0))

            return None if np.isnan(result) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None


# ═══════════════════════════════════════════════════════════════
# Volatility_6M — 6个月波动率（120个交易日）
# ═══════════════════════════════════════════════════════════════
#
# 公式：stdev(return_1d, 120) × sqrt(252)
#       return_1d = adj_close_b[t-1] / adj_close_b[t-2] - 1
# 说明：基于后复权收盘价，计算过去120个交易日的日收益率年化标准差。
#       使用 iloc[-2] 避免前视偏差。
# 需至少 122 行有效数据（121个价格 → 120个日收益率）。
# ═══════════════════════════════════════════════════════════════

class Volatility6M(FactorBase):
    """6个月波动率因子（120个交易日）。

    计算过去120个交易日的日收益率年化标准差：
      volatility = stdev(return_1d, 120) × sqrt(252)

    需至少122行有效（非停牌）历史数据。
    """

    def __init__(self, db_manager=None, lookback: int = 150):
        super().__init__(
            db_manager=db_manager,
            name='volatility_6m',
            lookback=lookback,
        )

    def calculate(self, df: pd.DataFrame) -> Optional[float]:
        """计算 Volatility_6M 因子值。

        Args:
            df: 该股票的有效历史数据，按 trade_date 正序排列。

        Returns:
            float or None: 年化波动率因子值。数据不足122行返回 None。
        """
        if df is None or len(df) < 122:
            return None

        try:
            # 提取过去121个交易日（t-1 至 t-121）的后复权收盘价
            # iloc[-122:-1]: 从倒数第122行到倒数第2行，共121个价格 → 120个日收益率
            prices = df['adj_close_b'].iloc[-122:-1].values
            if len(prices) < 121:
                return None

            # 计算日收益率序列
            returns = prices[1:] / prices[:-1] - 1.0

            if len(returns) < 2:
                return None

            # 样本标准差（ddof=1），年化 × sqrt(252)
            std = np.std(returns, ddof=1)
            result = float(std * np.sqrt(252.0))

            return None if np.isnan(result) else result

        except (IndexError, KeyError, TypeError, ZeroDivisionError):
            return None


# ═══════════════════════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════════════════════

def create_volatility_factors(db_manager=None) -> list:
    """创建所有3个波动因子实例列表。

    Args:
        db_manager: 可选的 DatabaseManager 实例

    Returns:
        list[FactorBase]: [Volatility1M, Volatility3M, Volatility6M]
    """
    return [
        Volatility1M(db_manager=db_manager),
        Volatility3M(db_manager=db_manager),
        Volatility6M(db_manager=db_manager),
    ]


# ═══════════════════════════════════════════════════════════════
# 因子元数据
# ═══════════════════════════════════════════════════════════════

VOLATILITY_FACTORS_META = [
    {
        "name": "volatility_1m",
        "class": "Volatility1M",
        "category": "volatility",
        "description": "1个月波动率（20交易日）：stdev(return_1d, 20) × sqrt(252)，return_1d=adj_close_b[t-1]/adj_close_b[t-2]-1",
        "min_valid_rows": 22,
        "lookback": 30,
    },
    {
        "name": "volatility_3m",
        "class": "Volatility3M",
        "category": "volatility",
        "description": "3个月波动率（60交易日）：stdev(return_1d, 60) × sqrt(252)，return_1d=adj_close_b[t-1]/adj_close_b[t-2]-1",
        "min_valid_rows": 62,
        "lookback": 80,
    },
    {
        "name": "volatility_6m",
        "class": "Volatility6M",
        "category": "volatility",
        "description": "6个月波动率（120交易日）：stdev(return_1d, 120) × sqrt(252)，return_1d=adj_close_b[t-1]/adj_close_b[t-2]-1",
        "min_valid_rows": 122,
        "lookback": 150,
    },
]
