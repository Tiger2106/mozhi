"""
mozhi_platform.src.backtest.factors.base — BaseFactor 因子抽象基类

所有因子须继承此类并实现 compute() 抽象方法。
同时须在模块级别定义 FACTOR_META 字典记录元信息。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseFactor(ABC):
    """因子抽象基类 — 合约四件套之因子版。

    每个因子代表一种从原始行情数据计算出的数值特征（如动量、波动率）。

    必须在模块级别定义 ``FACTOR_META`` 字典，格式参见
    :mod:`methods.manifest` 中的 FACTOR_META 协议。

    Examples:
        >>> class MomentumFactor(BaseFactor):
        ...     FACTOR_META = {
        ...         "name": "momentum",
        ...         "version": "1.0.0",
        ...         "category": "momentum",
        ...         "default_params": {"window": 20},
        ...     }
        ...     def compute(self, df: pd.DataFrame) -> pd.Series:
        ...         return df["close"].pct_change(self.params.get("window", 20))
    """

    def __init__(self, params: dict | None = None) -> None:
        """初始化因子实例。

        Args:
            params: 因子参数，会覆盖 FACTOR_META 中的 default_params。
        """
        self.params = dict(getattr(self, "FACTOR_META", {}).get("default_params", {}))
        if params:
            self.params.update(params)

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """从行情数据计算因子值。

        Args:
            df: OHLCV DataFrame。

        Returns:
            pd.Series: 因子数值序列，索引与 df 对齐。
                       返回值不含 NaN 的纯数值序列。

        Raises:
            NotImplementedError: 子类未实现时。
        """
        ...

    def __repr__(self) -> str:
        meta = getattr(self, "FACTOR_META", {})
        name = meta.get("name", type(self).__name__)
        return f"<{name} factor>"
