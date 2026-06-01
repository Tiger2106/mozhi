"""
_legacy — 原有 engine 代码归档 (仅作引用，不动现有文件)
========================================================
三层分离后，原有 engine 目录下的代码保留不动，
本目录存放指向原代码的引用说明。

原有文件列表（保留在 engine/ 根目录）:
    - backtest_result_bundle.py
    - bitable_sync.py
    - knowledge_analyzer.py
    - knowledge_bridge.py
    - knowledge_entry.py
    - knowledge_normalizer.py
    - knowledge_search.py
    - portfolio_integration.py

子包:
    - adapters/
    - portfolio/
    - runners/

迁移记录:
    - v1.0 (2026-05-27): 三层分离架构建立
    - DataLayer → engine/data_layer/
    - ComputeLayer → engine/calc_layer/
    - SimulateLayer → engine/sim_layer/
    - 新入口 → engine/engine.py (run_backtest)

作者: moheng
版本: v1.0
"""
