# 代码结构映射 — 回测三层分离架构

> 最后更新: 2026-05-27
> 作者: moheng

## 概述

依据 BT-001 三层分离架构，回测引擎分为三个正交模块：
**DataLayer / ComputeLayer / SimulateLayer**。
三模块仅通过 BacktestData 数据合约通信（BT-002）。

## 目录结构

```
src/backtest/
├── __init__.py
│
├── engine/                          ← 回测引擎入口
│   ├── __init__.py                  ← 原引擎初始化（保留）
│   │
│   ├── data_layer/                  ← 🏗️ 数据层 (BT-001)
│   │   ├── __init__.py              ← 接口导出
│   │   ├── loader.py                ← DataLayer.load() (GP-001)
│   │   ├── contract.py              ← BacktestBar, BacktestData (BT-004)
│   │   └── guard.py                 ← TimeAlignmentGuard, LookaheadRuntimeGuard
│   │
│   ├── calc_layer/                  ← 🏗️ 计算层 (BT-001)
│   │   ├── __init__.py              ← 接口导出
│   │   └── signals.py               ← Signal, Strategy, MaCrossoverStrategy, ComputeEngine
│   │
│   ├── sim_layer/                   ← 🏗️ 模拟层 (BT-001)
│   │   ├── __init__.py              ← 接口导出
│   │   ├── simulator.py             ← ConstraintAwareExecutor, SimulateResult, simulate()
│   │   ├── constraints.py           ← ConstraintManager (BT-008: 停牌>涨跌停>T+1)
│   │   └── logger.py                ← TradeLogger (BT-005 审计日志)
│   │
│   ├── engine.py                    ← 🚀 一站式入口 run_backtest()
│   │
│   ├── _legacy/                     ← 归档：原引擎引用说明
│   │   ├── __init__.py
│   │   └── MIGRATION_NOTES.md
│   │
│   ├── backtest_result_bundle.py    ← [保留] 结果打包
│   ├── bitable_sync.py              ← [保留] 飞书同步
│   ├── knowledge_*.py               ← [保留] 知识库相关
│   ├── portfolio_integration.py     ← [保留] 组合集成
│   ├── adapters/                    ← [保留] 适配器
│   ├── portfolio/                   ← [保留] 持仓管理
│   └── runners/                     ← [保留] 执行器
│
├── contracts/                       ← 数据合约
│   └── backtest_data_contract.py    ← BacktestData, BacktestBar, TimeAlignmentGuard
│
├── layers/                          ← 层实现（源文件）
│   ├── data_layer.py
│   ├── compute_layer.py
│   ├── simulate_layer.py
│   └── pipeline_runner.py           ← 原一站式入口（现在 engine/engine.py 为入口）
│
├── p0_fixes/                        ← P0修复
│   ├── lookahead_guard.py           ← P0-FIX-002: 前视偏差检测
│   ├── t1_fix.py                    ← P0-FIX-001: T+1说明
│   └── dividend_alignment.py        ← P0-FIX-003: 分红现金流对齐
│
├── backtest/                        ← R1 回测引擎
│   └── r1_backtest_engine.py
│
└── ... (其他模块: data, methods, factors, signals 等)
```

## 三层接口说明

### DataLayer (数据层)

| 文件 | 类/函数 | 输入 | 输出 | 约束 |
|------|---------|------|------|------|
| `loader.py` | `DataLayer.load()` | symbol, start_date, end_date | `BacktestData` | GP-001: 仅加载一次 |
| `contract.py` | `BacktestBar` | 原始数据字段 | 合约化对象 | BT-004 字段校验 |
| `contract.py` | `BacktestData` | 类型字典 | 完整合约（含指纹） | 指纹验证 |
| `guard.py` | `LookaheadRuntimeGuard.check()` | `BacktestData` | `List[str]` 警告 | BT-007 前视偏差防护 |

### ComputeLayer (计算层)

| 文件 | 类/函数 | 输入 | 输出 | 约束 |
|------|---------|------|------|------|
| `signals.py` | `compute()` | `BacktestData`, strategy params | `List[Signal]` | GP-002 零分配, GP-004 种子=42 |
| `signals.py` | `Strategy` | `BacktestData`, bar_idx | `Optional[Signal]` | BT-003 策略接口 |
| `signals.py` | `MaCrossoverStrategy` | fast, slow, position_ratio, stop_loss | 信号 | MA交叉策略 |
| `signals.py` | `ComputeEngine` | `BacktestData`, Strategy | `List[Signal]` | GP-004 |

### SimulateLayer (模拟层)

| 文件 | 类/函数 | 输入 | 输出 | 约束 |
|------|---------|------|------|------|
| `simulator.py` | `simulate()` | `BacktestData`, `List[Signal]`, capital | `SimulateResult` | 一站式口 |
| `simulator.py` | `ConstraintAwareExecutor.execute_signals()` | data, signals, capital | `SimulateResult` | BT-008 约束叠加 |
| `constraints.py` | `ConstraintManager` | `BacktestBar`, prices, buy_date | `ConstraintResult` | 停牌>涨跌停>T+1 |
| `logger.py` | `TradeLogger` | `TradeRecord` | 审计日志 | BT-005 可审计 |

## P0 修复映射

| P0 | 描述 | 位置 |
|----|------|------|
| FIX-001 | T+1 延迟处理 + 分时闸门 | `sim_layer/constraints.py` (ConstraintManager.check_t1), `sim_layer/simulator.py` (挂单队列) |
| FIX-002 | 前视偏差运行时检测 | `data_layer/guard.py` (LookaheadRuntimeGuard) |
| FIX-003 | 分红现金流对齐 | `sim_layer/simulator.py` (SimulateResult.p0_fixes_applied 标记) |

## 数据流

```
[CSV/DB]
    │
    ▼
DataLayer.load()        ← GP-001: 一次性加载
    │
    ▼
BacktestData (含指纹)    ← BT-004: 数据合约
    │
    ▼
LookaheadRuntimeGuard   ← BT-007: 前视偏差检测
    │
    ▼
ComputeEngine.compute() ← GP-002: 零新分配
    │                     GP-004: 种子=42
    ▼
List[Signal]            ← BT-003: 标准信号协议
    │
    ▼
ConstraintAwareExecutor ← BT-008: 约束叠加 (停牌>涨跌停>T+1)
    │                     P0-FIX-001/003
    ▼
SimulateResult          ← BT-005: 交易日志审计
  ├── trades[]          ← TradeLogger 记录
  ├── equity_curve[]    ← 净值曲线
  └── metrics{}         ← 绩效指标
```

## 回归对比

### 黄金基线

基线文件: `experiments/baselines/backtest_golden_baseline_bc5f464.json`

```python
from engine.engine import run_backtest, compare_with_baseline

result = run_backtest(symbol="601857.SH", start="20200101", end="20260515")
compare_with_baseline(result)  # 自动查找最新基线
```

### 运行方法

```bash
# 完整回测
cd C:\Users\17699\mozhi_platform
python -c "from engine.engine import run_backtest; result = run_backtest(); print(result.metrics)"

# 回归对比
python -c "from engine.engine import run_backtest, compare_with_baseline; r = run_backtest(); compare_with_baseline(r)"

# 指定参数
python -c "
from engine.engine import run_backtest
r = run_backtest(
    symbol='601857.SH',
    start='20200101',
    end='20260515',
    strategy_params={'fast': 5, 'slow': 20, 'position_ratio': 0.3, 'stop_loss': 0.05},
)
print(f'Return: {r.metrics.get(\"total_return_pct\", 0):.4f}%')
print(f'Trades: {r.total_trades}')
"
```

### 预期差异

新 pipeline 添加了 P0 修复（T+1延迟、涨跌停/停牌约束），
因此新结果与基线存在约 0.8% 的差异——新结果是更真实的市场模拟。
