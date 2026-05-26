# Phase 1 策略重构报告 — 信号协议解耦

**author**: 墨衡
**created_time**: 2026-05-20T12:50:00+08:00
**status**: COMPLETED

---

## 总览

Phase 1 目标：所有策略剥离交易依赖（`OrderRequest`/`OrderSide`/`OrderType`），全部改为统一 `Signal` 协议输出。

## 扫描结果

| 策略文件 | 变更类型 | 说明 |
|----------|----------|------|
| `trend_strategy.py` | ✅ 实质性修改 | 移除 `OrderRequest/OrderSide/OrderType` import；`on_bar()` 返回改为 `List[Signal]`；旧版 Signal 类保留为 `_LegacySignal`；旧版函数（`ma_signal` 等）保留使用 `_LegacySignal` |
| `grid_strategy.py` | ✅ 实质性修改 | 移除 `OrderRequest/OrderSide/OrderType` import；移除 `reversal_strategy.Signal` 依赖；`GridSignal` 改为独立 dataclass（不继承自基类）；所有 `_post_bar_orders()` 返回 `List[ProtocolSignal]`；`GridVotingSignal.on_bar()` 使用信号协议 |
| `run_grid.py` | ✅ 实质性修改 | `GridSignalProvider` 适配层改为消费 `Signal` 对象；`_GridRunnerStrategy.on_bar()` 返回 `List[Signal]`；移除对 `OrderRequest/OrderSide/OrderType` 的全部引用 |
| `run_trend.py` | ✅ 已预先适配 | 已导入 `Signal` 协议，无交易依赖 |
| `run_reversal.py` | ✅ 已预先适配 | 已导入 `Signal` 协议，无交易依赖 |
| `reversal_strategy.py` | ✅ 无需修改 | 无交易依赖 |
| `multi_runner.py` | ✅ 已预先适配 | 已导入 `Signal` 协议，无交易依赖 |
| `_pipeline_main.py` | ✅ 无需修改 | 无交易依赖 |
| `_pipeline_main_v2.py` | ✅ 无需修改 | 无交易依赖 |

## 关键设计决策

### 1. 向后兼容
| 旧导入方式 | 新行为 |
|---|---|
| `from trend_strategy import Signal` | 现在导入的是协议 `Signal`（`src.signals.signal_protocol_v1.Signal`） |
| `from trend_strategy import ma_signal, weighted_vote` | 无变化（内部使用 `_LegacySignal`） |
| `from grid_strategy import GridSignal` | 无变化（GridSignal 保留 `action`/`strength` 字段，仅不再继承自 `Signal`） |

### 2. Signal 映射规则
| 旧字段 | 新字段 |
|--------|--------|
| `OrderRequest.symbol` | `Signal.symbol` |
| `OrderSide.BUY/SideBUY` | `Signal.direction = "BUY"` |
| `OrderRequest.quantity` | `Signal.extras["quantity"]` |
| `OrderType.MARKET` | 移除（由执行层决定） |
| 仓位限制 | `Signal.extras["quantity"]` 中体现 |

### 3. 信号协议字段（`signal_protocol_v1.Signal`）
| 字段 | 说明 |
|------|------|
| `signal_id` | UUID |
| `symbol` | 证券代码 |
| `direction` | "BUY"/"SELL"/"HOLD" |
| `confidence` | 置信度 [0, 1] |
| `horizon` | 时间周期 |
| `signal_type` | "trend"/"reversal"/"grid" |
| `timestamp` | 时间戳 |
| `protocol_version` | "1.0" |
| `extras` | 扩展信息（含 quantity） |

## 验证结果
- ✅ 所有 9 个目标策略文件无 `OrderRequest/OrderSide/OrderType` 引用
- ✅ 协议 `Signal` 导入测试通过
- ✅ 旧版 `ma_signal/macd_signal/weighted_vote` 向后兼容测试通过
- ✅ `GridSignal` 独立数据类兼容测试通过

## 遗留问题
- `signal_bridge.py` 内部仍有对策略 `on_bar` 返回类型的隐式假设（策略输出 `Signal` 后被转换为 `OrderRequest` 再送到 backtest_engine）。这是基础设施层，将在 Phase 2 中处理。
- `reversal_strategy.py` 的本地 `Signal` 数据类（`action`/`strength`）未被修改——不影响 Phase 1 目标（它不依赖交易类型）。
