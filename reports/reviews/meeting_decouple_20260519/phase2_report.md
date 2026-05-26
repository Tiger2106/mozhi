# Phase 2 完成报告 — SignalConsumer + SignalSimulator

**owner**: 墨衡 (moheng)
**created_time**: 2026-05-20T13:08:00+08:00
**status**: COMPLETED

---

## 一、任务摘要

Phase 2 建立了策略 Signal 对象到 BacktestEngine OrderRequest 的桥梁，包含两个核心模块和一个轻量模拟器。

### 交付清单

| 文件 | 路径 | 说明 |
|:---:|:-----|:-----|
| SignalConsumer | `src/signals/consumer.py` | Signal → OrderRequest 映射器 |
| SignalSimulator | `src/signals/simulator.py` | 独立信号效果模拟器 |
| 测试: Consumer | `tests/signals/test_consumer.py` | 9 个测试类，覆盖全部路径 |
| 测试: Simulator | `tests/signals/test_simulator.py` | 6 个测试类，覆盖边界与异常 |
| 本报告 | `reports/reviews/.../phase2_report.md` | 完成报告 |

---

## 二、模块设计

### 2.1 SignalConsumer (`src/signals/consumer.py`)

**类**: `SignalConsumer`, `ConsumerConfig`

**核心方法**:
- `consume(signal, context) → Optional[OrderRequest]` — 单信号映射
- `consume_batch(signals, context) → List[OrderRequest]` — 批量映射

**映射规则**:
| Signal 字段 | → | OrderRequest 字段 | 说明 |
|:-----------|:-:|:-----------------|:-----|
| `direction == "BUY"` | → | `OrderSide.BUY` | OrderSide.BUY |
| `direction == "SELL"` | → | `OrderSide.SELL` | |
| `direction == "HOLD"` | → | `None` | 不下单 |
| `extras["quantity"]` | → | `quantity` | 策略指定优先级高 |
| config.default_quantity | → | `quantity` | 缺省兜底 |
| (固定) | → | `OrderType.MARKET` | 统一市价单 |

**只读模式**: `ConsumerConfig(read_only=True)` 控制标记，返回值不受影响，调用方依此 flag 决定是否实际发单。

### 2.2 SignalSimulator (`src/signals/simulator.py`)

**类**: `SignalSimulator`, `SimResult`

**核心方法**:
- `evaluate(signal, price_data) → SimResult` — 单信号模拟

**模拟逻辑**:
1. 按 `signal.direction` 决定开仓方向（BUY/SELL × 方向乘数）
2. 通过 `extras["entry_index"]` 或索引 0 确定入场点
3. 持有 N 个 bar（`extras["holding_periods"]` 或 `ctor.holding_periods`）
4. 统计累计收益、最大回撤、胜率、近似夏普比率

**依赖**: pandas, numpy — 完全不依赖 BacktestEngine

---

## 三、测试覆盖

### Consumer 测试 (9 classes, 14 test cases)

| 测试类 | 覆盖内容 |
|:-------|:---------|
| TestConsumeBasic | BUY/SELL/HOLD 基本路径, symbol 保留 |
| TestQuantityResolution | extras.quantity 优先级, 缺省, 浮点向下取整, 字符串数字, 无效兜底 |
| TestReadOnlyMode | read_only 标记不影响返回值 |
| TestConsumeBatch | 批量转换, HOLD 过滤, 顺序保留, 空列表 |
| TestEdgeCases | 无效 direction → ValueError, zero quantity 保底 |

### Simulator 测试 (6 classes, 14 test cases)

| 测试类 | 覆盖内容 |
|:-------|:---------|
| TestEvaluateBasic | BUY/SELL 上涨/下跌回报, HOLD 空结果, confidence 传递 |
| TestEdgeCases | 空数据, 缺列, 单 bar, 零价格 |
| TestCustomParameters | extras.entry_index, holding_periods, 构造器参数, 越界兜底 |
| TestFlatAndNoise | 平稳价格, 噪声价格 |
| TestSimResultStructure | 字段完备性, drawdown 非正 |

---

## 四、约束遵守

| 约束 | 状态 |
|:----|:----:|
| 不改策略文件 | ✅ 未触碰 |
| 不改 backtest_engine.py（仅引用类型） | ✅ 仅 import, 零修改 |
| 不改早报管线/交易执行代码 | ✅ 未触碰 |
| 引用 backtest_engine 的 OrderRequest/OrderSide/OrderType | ✅ 正确引用 |
| 输出 SignalSimulator 独立于 BacktestEngine | ✅ 仅依赖 pandas/numpy |

---

## 五、下一步建议 (Phase 3)

1. **双系统验证**: Consumer + Simulator 组合验证流水线
2. **模拟器升级**: 接入真实回测引擎做全路径验证
3. **Kill Switch 集成**: 将 SignalConsumer 注入墨枢早报管线
