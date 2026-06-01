"""
src.ic — 截面IC计算引擎包

提供 RankIC 计算引擎，包含 Spearman 秩相关系数计算、
IC 时间序列聚合、分组 IC 计算和 adjusted IC（剔除极端值）。

模块组成：
  - engine.py      : IC_Engine 主类
  - cross_sectional_ic.py : (规划) 截面IC管线集成

设计原则：
  - 核心计算使用 scipy.stats.spearmanr / pearsonr
  - 异常处理：样本量不足时返回 None
  - 支持 DatabaseManager 参数注入（与管线集成）
  - 统一日志记录

用法:
    from src.ic import IC_Engine

    engine = IC_Engine()
    result = engine.compute_rank_ic(
        factor_values=[...],
        forward_returns=[...],
        date="2026-05-26",
    )

Author: 墨衡
Version: v1.0
Created: 2026-05-30T11:59:00+08:00
"""

from src.ic.engine import IC_Engine

__all__ = ["IC_Engine"]
__version__ = "1.0.0"
