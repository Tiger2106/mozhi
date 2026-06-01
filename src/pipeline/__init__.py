#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src.pipeline — A50截面IC管线模块

提供截面IC完整流水线（CrossSectionalICPipeline），
整合因子计算 → IC引擎 → 结果写入。

模块组成:
  - cross_sectional_ic_pipeline.py : 管线主体（run_pipeline / run_batch）
  - phase4c_interface.py          : Phase4c 接口（存量）
  - quality_gates.py               : 质量门禁（存量）
  - review_signoff.py              : 审查签核（存量）

用法:
    from src.pipeline import CrossSectionalICPipeline
    from src.db.connection import get_manager
    from src.ic.engine import IC_Engine
    from src.ic.forward_returns import ForwardReturns
    from src.factors.registry import FactorRegistry

    dm = get_manager()
    ic_engine = IC_Engine(db_manager=dm)
    fr = ForwardReturns(db_manager=dm)
    registry = FactorRegistry()

    pipeline = CrossSectionalICPipeline(dm, ic_engine, fr, registry)
    summary = pipeline.run_pipeline("20260526")

Author: 墨衡
Created: 2026-05-30
"""

from src.pipeline.cross_sectional_ic_pipeline import CrossSectionalICPipeline
from src.pipeline.scheduler import ICBatchScheduler

__all__ = ["CrossSectionalICPipeline", "ICBatchScheduler"]
