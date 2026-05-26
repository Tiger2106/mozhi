# Phase 3 旧代码清理计划

**task_id**: phase3_dual_validation
**agent**: 墨衡 (moheng)
**date**: 2026-05-20
**status**: PLAN (not yet executed)
**⚠️ 注意: 此为计划文档，不实际执行删除操作**

---

## 清理前提条件

在清理之前，需确认以下条件全部满足：
1. ✅ DualValidator 测试通过
2. [ ] 新旧路径在实际数据上输出一致（偏差率低于阈值）
3. [ ] 所有策略已通过 Signal + SignalConsumer 路径验证
4. [ ] 回测管线已验证新路径可用

---

## 可安全删除的文件

### 1. `src/backtest/signal_bridge.py`

**文件**: `C:\Users\17699\mozhi_platform\src\backtest\signal_bridge.py`

**类**:
| 类名 | 替代方案 | 可删除 |
|:-----|:---------|:------:|
| `SignalBridge` | `SignalConsumer` + `SignalBacktestAdapter` | ✅ |
| `SignalBridgeConfig` | `ConsumerConfig` | ✅ |
| `SignalStrategy` | `SignalBacktestAdapter.wrap_strategy()` | ✅ |

**依赖关系**:
- `run_trend.py` 的 `run_trend_backtest()` 使用 `SignalBridge` → **需先迁移 run_trend_backtest 到新路径**
- `multi_runner.py` 的 `MultiStrategyRunner` 使用 `SignalBridge` → **需先迁移**
- `trend_strategy.py` 的 `TrendStrategy` 不直接使用 SignalBridge

**迁移路径**:
```
signal_bridge.py ──→ SignalConsumer + SignalBacktestAdapter
    │                       │
    ├── signal_to_orders()  ├── consume_batch()
    ├── get_indicator()     ├── (无需，方法引擎独立管理)
    └── get_factor()        └── (同上)
```

### 2. `src/backtest/simulator/` 目录

**路径**: `C:\Users\17699\mozhi_platform\src\backtest\simulator\`

**内容**: 旧版信号模拟器（与 `src/signals/simulator.py` 的 `SignalSimulator` 功能重叠）

**替代**: `src/signals/simulator.py` 中的 `SignalSimulator`

**注意**: 需先确认 `simulator/` 目录无其他依赖

### 3. 旧策略基类中的 SignalBridge 引用

**文件**: `src/backtest/strategies/`
- `trend_strategy.py` 中的 SignalBridge import（如果存在）

**处理方式**: 移除 import，确保 `TrendStrategy` 只输出 Signal 对象

---

## 可安全归档的文件

### 1. `src/backtest/adapters/_legacy/legacy_runner_adapter.py`

**路径**: `C:\Users\17699\mozhi_platform\src\backtest\adapters\_legacy\legacy_runner_adapter.py`

**原因**: 新路径已有 `SignalBacktestAdapter`，旧的 `LegacyRunnerAdapter`（从旧系统→新 `MethodResult`）可归档

**处理方式**: 移入 `_legacy/` 目录下的 `_archive/` 子目录

### 2. `src/backtest/engine/adapters/legacy_runner_adapter.py`

**路径**: `C:\Users\17699\mozhi_platform\src\backtest\engine\adapters\legacy_runner_adapter.py`

**原因**: 与 1 重复，是同一适配器的另一副本

**处理方式**: 与 1 一起归档

---

## 清理步骤

```
Phase 3 (当前)
  ├── ✅ 创建 DualValidator
  ├── ✅ 创建 SignalBacktestAdapter
  ├── ✅ 验证测试
  └── ⏳ 等待实际数据验证

Phase 4 (下一步)
  ├── 迁移 run_trend.py → SignalConsumer
  ├── 迁移 run_grid.py  → SignalConsumer
  ├── 迁移 run_reversal.py → SignalConsumer
  ├── 迁移 multi_runner.py → SignalConsumer
  └── 验证新路径一致性

Phase 5 (最终清理)
  ├── 删除 signal_bridge.py
  ├── 归档 legacy_runner_adapter.py
  ├── 清理策略文件中的 SignalBridge import
  └── 最终回测验证
```

---

## 保留文件

以下文件不应删除:
| 文件 | 原因 |
|:-----|:-----|
| `backtest_engine.py` | ⛔ 约束: 不修改 |
| `order_executor.py` | 被新路径复用 |
| 所有策略文件 | Phase 1 已完成改造成 Signal 输出，保留 |
| `src/signals/consumer.py` | ✅ 新路径核心 |
| `src/signals/signal_protocol_v1.py` | ✅ 新路径核心 |
| `src/signals/simulator.py` | ✅ 新路径核心 |

---

## 风险提示

1. **SignalBridge 被多处引用**: `run_trend.py`, `multi_runner.py`, `trend_strategy.py` 都 import 它。删除前需确保所有引用点已迁移。

2. **run_trend_backtest() 用户**: 如果有外部脚本调用 `run_trend_backtest()`，需保持向后兼容或同步更新。

3. **SignalStrategy 被继承**: 如果存在外部策略继承自 `SignalStrategy`，需告知迁移。
