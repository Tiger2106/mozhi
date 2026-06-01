"""
因子计算模块

提供：
  - FactorBase: 因子基类（所有因子子类的父类）
  - SuspensionHandler: 停牌/缺失数据处理工具
  - FactorRegistry: 因子注册表（按类别管理、批量计算）

模块结构：
  - base.py:     FactorBase + SuspensionHandler
  - registry.py: FactorRegistry

Author: 墨衡
Created: 2026-05-30T10:54:00+08:00
Version: v1
"""

from src.factors.base import FactorBase, SuspensionHandler
from src.factors.registry import FactorRegistry
from src.factors.momentum_factor import (
    Momentum1M,
    Momentum3M,
    Momentum6M,
    Momentum12M1M,
    Momentum5D,
    Momentum20D,
    Momentum60D,
    Momentum120D,
    create_momentum_factors,
    MOMENTUM_FACTORS_META,
)
from src.factors.reversal_factor import (
    Reversal1D,
    Reversal5D,
    Reversal10D,
    create_reversal_factors,
    REVERSAL_FACTORS_META,
)
from src.factors.quality_factor import (
    ROE,
    ProfitMargin,
    AssetTurnover,
    Leverage,
    EarningsVariability,
    SalesGrowth,
    create_quality_factors,
    QUALITY_FACTORS_META,
)
from src.factors.valuation_factor import (
    PE_TTM,
    PB,
    PS_TTM,
    PCF_TTM,
    create_valuation_factors,
    VALUATION_FACTORS_META,
)  # TEMP-REMOVED: T+21 OOM repair 2026-05-30 — kept for restore
from src.factors.volatility_factor import (
    Volatility1M,
    Volatility3M,
    Volatility6M,
    create_volatility_factors,
    VOLATILITY_FACTORS_META,
)

def create_default_registry(db_manager=None):
    """创建并返回预注册全部20个因子的 FactorRegistry。"""
    registry = FactorRegistry()
    for f in create_momentum_factors(db_manager):
        registry.register(f, category='momentum')
    for f in create_reversal_factors(db_manager):
        registry.register(f, category='reversal')
    for f in create_quality_factors(db_manager):
        registry.register(f, category='quality')
    # TEMP-REMOVED: T+21 OOM repair 2026-05-30
    # Removed 4 valuation factors (pe_ttm, pb, ps_ttm, pcf_ttm) to reduce memory usage.
    # Re-enable after OOM issue is resolved.
    # for f in create_valuation_factors(db_manager):
    #     registry.register(f, category='valuation')
    for f in create_volatility_factors(db_manager):
        registry.register(f, category='volatility')
    return registry


__all__ = [
    'FactorBase',
    'SuspensionHandler',
    'FactorRegistry',
    'create_default_registry',
    # 动量因子
    'Momentum1M',
    'Momentum3M',
    'Momentum6M',
    'Momentum12M1M',
    'Momentum5D',
    'Momentum20D',
    'Momentum60D',
    'Momentum120D',
    'create_momentum_factors',
    'MOMENTUM_FACTORS_META',
    # 反转因子
    'Reversal1D',
    'Reversal5D',
    'Reversal10D',
    'create_reversal_factors',
    'REVERSAL_FACTORS_META',
    # 质量因子
    'ROE',
    'ProfitMargin',
    'AssetTurnover',
    'Leverage',
    'EarningsVariability',
    'SalesGrowth',
    'create_quality_factors',
    'QUALITY_FACTORS_META',
    # 估值因子
    'PE_TTM',
    'PB',
    'PS_TTM',
    'PCF_TTM',
    'create_valuation_factors',
    'VALUATION_FACTORS_META',
    # 波动因子
    'Volatility1M',
    'Volatility3M',
    'Volatility6M',
    'create_volatility_factors',
    'VOLATILITY_FACTORS_META',
]
