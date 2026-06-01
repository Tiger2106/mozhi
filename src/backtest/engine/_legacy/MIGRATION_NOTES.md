# engine/_legacy — 迁移说明

## 背景

原有 `engine/` 目录包含回测引擎的核心代码（knowledge_* 系列、bitable_sync 等）。
根据 BT-001 三层分离架构，新建了三个子包用于结构化代码：

- `data_layer/` — 数据加载、校验、指纹、前视偏差检测
- `calc_layer/` — 信号计算、策略接口
- `sim_layer/` — 模拟交易、约束叠加、交易日志审计

## 文件归属

| 原有文件 | 新位置 | 说明 |
|---------|--------|------|
| backtest_result_bundle.py | engine/ 原位保留 | 结果打包，保持独立 |
| bitable_sync.py | engine/ 原位保留 | 飞书同步，保持独立 |
| knowledge_*.py | engine/ 原位保留 | 知识库相关，保持独立 |
| portfolio_integration.py | engine/ 原位保留 | 组合集成，保持独立 |
| runners/ | engine/ 原位保留 | 执行器，保持独立 |
| adapters/ | engine/ 原位保留 | 适配器，保持独立 |
| portfolio/ | engine/ 原位保留 | 持仓管理，保持独立 |

## 新的入口

```python
from engine.engine import run_backtest

result = run_backtest(
    symbol="601857.SH",
    start="20200101",
    end="20260515",
    strategy_type="ma_cross",
    strategy_params={"fast": 5, "slow": 20},
    initial_capital=1_000_000,
)
```

## 三层接口说明

### DataLayer (engine/data_layer/)
| 接口 | 输入 | 输出 |
|------|------|------|
| `DataLayer.load()` | symbol, start_date, end_date | `BacktestData` (含指纹) |
| `LookaheadRuntimeGuard.check()` | `BacktestData` | `List[str]` 警告 |

### ComputeLayer (engine/calc_layer/)
| 接口 | 输入 | 输出 |
|------|------|------|
| `compute()` | `BacktestData`, strategy params | `List[Signal]` |

### SimulateLayer (engine/sim_layer/)
| 接口 | 输入 | 输出 |
|------|------|------|
| `simulate()` | `BacktestData`, `List[Signal]`, capital | `SimulateResult` |
| `ConstraintManager.check_buy/sell()` | `BacktestBar`, prices | `ConstraintResult` |
| `TradeLogger.log()` | `TradeRecord` | 写入审计日志 |

## P0 修复集成

| 修复 | 位置 | 说明 |
|------|------|------|
| P0-FIX-001 T+1延迟 | sim_layer/constraints.py, sim_layer/simulator.py | 挂单隔日可卖 |
| P0-FIX-002 前视偏差 | data_layer/guard.py | 运行时检测 |
| P0-FIX-003 分红现金流 | sim_layer/simulator.py | 分红调整 |
