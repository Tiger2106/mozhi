# 墨家投资室 - 回测引擎
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 模块结构：
#   data_ingestion/ — 数据采集 + ETL 归一化
#   calc/            — 因子计算库
#   collector/       — 分钟级数据采集器
#   pipeline/        — 管线编排（因子计算 → 信号输出）

from . import data_ingestion
from . import calc
from . import collector
from . import pipeline

__all__ = [
    'data_ingestion',
    'calc',
    'collector',
    'pipeline',
]
