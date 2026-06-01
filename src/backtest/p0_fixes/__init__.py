"""
P0修复模块：T+1延迟、前视偏差检测、分红对齐、涨跌停边界、流动性分档、集合竞价

包含：
  - lookahead_guard: 前视偏差检测
  - t1_fix: T+1 延迟处理
  - dividend_*: 分红对齐
  - price_boundary: 涨跌停常量和边界计算 (P1)
  - liquidity_model: 流动性分档模型 (P1_002a)
  - auction_engine: 集合竞价撮合引擎 (P1_004a)
"""

# 注意：price_boundary 依赖 backtest_engine.sim_layer，
# 在测试环境或未部署该模块时可能不可用。
try:
    from . import price_boundary
except ImportError:
    price_boundary = None  # type: ignore[assignment]

from . import liquidity_model
from . import auction_engine
from . import preflight
from . import engine_preflight_integration

# 从 preflight 导出 MarketType（自包含版本不再依赖 price_boundary）
from .preflight import MarketType
from .engine_preflight_integration import OrderPreflightValidator

__all__ = [
    "price_boundary",
    "liquidity_model",
    "auction_engine",
    "preflight",
    "engine_preflight_integration",
    "OrderPreflightValidator",
]
