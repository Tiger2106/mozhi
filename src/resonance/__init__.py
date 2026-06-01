"""
墨枢 — 右侧交易共振系统

Phase 0 共振系统核心模块包。

模块清单：
  - DCM:  波动率采集模块 (Data Collection: Volatility)
  - LQM:  流动性评估模块 (Liquidity: Turnover)
  - ZNM:  z-score 归一化模块
  - RSM:  共振状态机模块 (Resonance State Machine)
  - DSV:  双源验证模块 (Dual-Source Verification)
  - GKV:  门控验证模块 (Gate-Keeping Verification)
  - CPE:  组合评估模块 (Combined Performance Evaluation)
  - SG:   信号生成模块 (Signal Generator)
  - SCL:  调度层适配器 (Scheduling Layer Adapter)
  - DataBridge: 数据桥接模块
  - LookbackBuffer: 回看缓冲区
"""

from __future__ import annotations

__version__ = "0.3.0"
__phase__ = "Phase 0.3"
__author__ = "moheng"
