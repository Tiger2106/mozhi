<!--
author: 墨衡
task: meeting_decouple_20260519
created_time: 2026-05-19T23:42:00+08:00
-->

# 研究系统与交易系统解耦重构分析报告

**提交人**: 墨衡（moheng）
**角色**: 当前系统主要实现者 / 执行方
**评审类型**: Stage 0 会前准备

---

## 1. 当前问题诊断 — 代码级耦合的具体表现

### 1.1 策略直接依赖交易层类型

最直接的问题：`src/backtest/strategies/` 下的所有策略文件均直接导入交易执行层的核心类型。

```python
# trend_strategy.py, grid_strategy.py 等
from backtest.backtest_engine import OrderRequest, OrderSide, OrderType
```

这意味着一个**策略研究员**在研究信号有效性时，必须理解 `OrderRequest` 的构造语义、`OrderType.MARKET/LIMIT` 的区别、`OrderSide.BUY/SELL` 的方向定义。这些概念本属于交易执行层，不应出现在研究代码中。策略的产出应当是**信号（Signal）**，而不是**订单（OrderRequest）**。

**波及范围**：`trend_strategy.py`、`grid_strategy.py`、`reversal_strategy.py`、`factor_calculator.py` 等 **超10个策略文件** 均存在此模式。

### 1.2 SignalBridge — 试图解耦反而成为新的耦合点

`src/backtest/signal_bridge.py` 的设计初衷是好的：将信号生成与订单执行解耦。但实际实现中，它**同时进口两个世界**：

- 从研究侧：`from phase1_core.indicator_engine import IndicatorEngine`、`from paper_trade.tech_signal_generator import generate_backtest_signals`
- 从交易侧：`from .backtest_engine import OrderRequest, OrderSide, OrderType`

`SignalBridge.signal_to_orders()` 方法本质上是将 Signal → OrderRequest，但这个转换逻辑现在**硬编码在回测系统内部**。若交易系统修改 OrderRequest 结构，SignalBridge 也必须同步修改——这是典型的**依赖方向错误**。

### 1.3 回测引擎（BacktestEngine）与交易概念耦合

`src/backtest/backtest_engine.py` 中定义/导入了：

- `OrderRequest` — 交易下单请求
- `OrderSide` — 买卖方向枚举
- `OrderType` — 订单类型枚举
- `Strategy` — 策略基类（与回测上下文绑定）
- `Position` — 持仓数据结构
- `PositionManager` — 持仓管理
- `CapitalManager` — 资金管理
- `FeeModel` — 手续费模型
- `SlippageModel` — 滑点模型
- `Performance` — 绩效计算

回测引擎应当只关心**模拟执行**而非交易执行。但当前 `CapitalManager`、`PositionManager`、`FeeModel` 等都编译在回测引擎内，导致：

- 回测引擎约 400 行核心逻辑 + 超过 8 个子模块
- 任何对交易概念的修改都可能影响回测的正确性
- 测试时需要构建完整的交易上下文

### 1.4 技术分析研究（src/trading/signals/）与回测策略重复

`src/trading/signals/tech_signal_generator.py`（1100+行）和 `src/backtest/strategies/` 下存在**冗余的信号产生逻辑**：

- 趋势信号：`tech_signal_generator.generate_trend_signal()` vs `TrendStrategy.generate_signals()`
- 反转信号：`tech_signal_generator.generate_reversal_signal()` vs `reversal_strategy.py`
- 网格信号：`tech_signal_generator.generate_grid_signal()` vs `grid_strategy.py`

两套逻辑相似但并非共享。修改一处信号生成逻辑，另一处必须同步手动更新——几乎不可能做到。

### 1.5 数据流混乱

当前数据流为：

```
策略(SignalStrategy.on_bar)
  ↓
SignalBridge.signal_to_orders()
  ↓
OrderRequest
  ↓
BacktestEngine.run()
  ↓
Portfolio/Position/Capital
```

研究过程中的中间产物（Signal、Factor Score、Indicator Value）没有标准化的序列化输出管道，无法被**独立验证**、**回放**或**被下游系统消费**。

---

## 2. 重构目标

解耦后应达到以下状态：

### 2.1 研究系统可独立运行

- 研究员在**不启动任何交易上下文**的情况下，可以运行策略、生成信号、回测验证
- 策略只产出 `Signal`（方向+强度+时间+标的），不产出 `OrderRequest`
- 所有交易类型（OrderRequest, OrderSide, OrderType）不进入研究代码的 import 路径

### 2.2 单层依赖方向

```
研究系统 (Research) → Signal (标准数据模型) → 交易系统 (Trading)
```

研究系统**不依赖**交易系统。交易系统**依赖**研究系统产出的 Signal 标准格式。依赖方向是单向的。

### 2.3 共享信号格式

定义一个技术栈无关的 `Signal` 数据模型，位于独立的 `signal_models.py` 中：

```python
@dataclass
class Signal:
    symbol: str
    timestamp: datetime
    action: Literal["BUY", "SELL", "HOLD"]
    strength: float        # 0.0 ~ 1.0
    weight: float          # 组合权重
    metadata: dict         # 附加信息（指标值、置信度等）
```

研究系统产出的 Signal，交易系统消费。两套系统通过**文件/消息队列**交换这个标准格式。

### 2.4 可审计、可回放

- 每次研究运行产出完整的 Signal 序列（持久化到数据库或文件）
- 交易系统可以基于同组 Signal 进行不同的执行策略模拟
- 支持 "研究回溯"：拿历史 Signal 文件重新模拟决策

---

## 3. 架构方案（建议）

### 3.1 总体架构

```
┌─────────────────────────────────────┐
│          研究系统（Research）          │
│                                     │
│  ┌─────────┐  ┌──────────┐         │
│  │ 策略引擎 │  │ 因子引擎  │         │
│  │(纯研究)  │  │(研究用)   │         │
│  └────┬────┘  └────┬─────┘         │
│       │             │               │
│       ▼             ▼               │
│  ┌──────────────────────────┐       │
│  │     Signal Generator      │       │
│  │   (信号生产者，无交易依赖)    │       │
│  └────────────┬──────────────┘       │
│               │                      │
│               ▼                      │
│  ┌──────────────────────────┐       │
│  │   Research Simulator      │       │
│  │  (轻量回测，不依赖交易层)    │       │
│  └────────────┬──────────────┘       │
└───────────────┼─────────────────────┘
                │
                ▼  Signal (标准数据格式)
                │
┌───────────────┼─────────────────────┐
│               │                      │
│  ┌────────────▼──────────────┐       │
│  │     Signal Consumer        │       │
│  │  (信号消费者/适配器层)        │       │
│  └────────────┬──────────────┘       │
│               │                      │
│               ▼                      │
│  ┌──────────────────────────┐       │
│  │     Trading Engine        │       │
│  │  (订单管理、执行、结算)      │       │
│  └──────────────────────────┘       │
│                                     │
│          交易系统（Trading）          │
└─────────────────────────────────────┘

共享层：
┌──────────────────────────────┐
│  Signal Models + Serializer  │
│  (独立 lib，双方共同依赖)       │
└──────────────────────────────┘
```

### 3.2 关键架构决策

1. **Signal 库独立发布**: `mozhi_platform_signal` 或放在 `src/common/signal/`，两个系统都不依赖对方但都依赖它
2. **研究 Simulator 是轻量级的**: 只模拟信号到手数的转换和简单盈亏计算，不需要 PositionManager/CapitalManager/FeeModel
3. **交易系统保留自己完整的执行引擎**: 包括 OrderEngine、SlippageModel、FeeModel 等，但不包含信号生成逻辑
4. **数据交换通过文件系统**: Signal 文件写入 `data/signals/{date}/{run_id}.json`，交易系统监听目录变化
5. **Signal → Order 的转换由交易系统负责**: 交易系统决定具体如何执行（市价/限价、时间切片、对冲等）

---

## 4. 核心模块划分

### 4.1 研究系统（Research）保留/迁移模块

| 模块 | 用途 | 当前状态 |
|:----|:-----|:--------|
| `research/strategies/` | 策略实现（纯信号生成） | ✅ 已有，需剥离交易依赖 |
| `research/factors/` | 因子计算 | ✅ 已有（factor_calculator等） |
| `research/indicators/` | 技术指标 | ✅ 已有（indicator_engine等） |
| `research/signal_producer/` | Signal 生成 + 序列化 | ❌ 新建 |
| `research/simulator/` | 轻量级回测（只做盈亏模拟） | ❌ 新建 |
| `research/regime/` | 市场状态分类 | ✅ 已有 |
| `research/analysis/` | 绩效分析、归因分析 | ✅ 已有 |
| `research/optimizer/` | 参数调优 | ✅ 已有（部分） |

### 4.2 交易系统（Trading）保留模块

| 模块 | 用途 | 当前状态 |
|:----|:-----|:--------|
| `trading/order_engine/` | 订单管理、执行、生命周期 | ✅ 已有 |
| `trading/account/` | 账户管理、资金管理 | ✅ 已有 |
| `trading/position/` | 持仓管理 | ✅ 已有 |
| `trading/fees/` | 手续费计算 | ✅ 已有 |
| `trading/settlement/` | 日终结算 | ✅ 已有 |
| `trading/risk/` | 风控检查 | ✅ 已有 |
| `trading/signal_consumer/` | Signal 消费 → Order 转换 | ❌ 新建 |
| `trading/bridge/` | 连接外部交易通道 | ❌ 新建（如连接IB/券商） |

### 4.3 共享模块

| 模块 | 用途 |
|:----|:-----|
| `common/signal_models.py` | Signal 标准数据模型 |
| `common/serializer/` | Signal 序列化/反序列化（JSON/Parquet） |
| `common/types.py` | 基础类型定义（枚举、常量） |

### 4.4 移除/废弃

- `src/backtest/signal_bridge.py` — 被 Signal Producer + Signal Consumer 替代
- `src/backtest/backtest_engine.py` 中的 OrderRequest/OrderSide/OrderType → 迁移到 trading 或 common
- `src/backtest/strategies/` 与 `src/trading/signals/tech_signal_generator.py` 的重复信号逻辑 → 统一到 `research/strategies/`

---

## 5. 优点

### 5.1 开发效率提升

- 研究员可以在**秒级**（而非分钟级）内完成一轮策略修改→信号验证的迭代
- 不需要启动完整的回测环境即可获得信号输出
- 多人可同时研究不同策略，互不干扰

### 5.2 测试可靠性

- 研究系统可独立进行单元测试，不需要 mock 交易层
- 交易系统可直接用历史 Signal 文件做回归测试
- 验证信号质量的测试和验证交易执行的测试分开，错抓概率降低

### 5.3 职责清晰

- 研究系统只问"什么信号有效"
- 交易系统只问"怎样执行最好"
- 两个问题独立演进，各自优化

### 5.4 审计可追溯

- 每个 Signal 都有完整的元数据（时间戳、版本号、策略参数）
- 事后可以回放："当天 Signal 是什么 → 交易系统怎么执行的 → 结果如何"
- 支持 "what-if" 分析：同组 Signal 换一套执行参数，结果有何不同

### 5.5 技术栈灵活

- 研究系统可用 Python 全栈（pandas/numpy/scipy）
- 交易系统若需要高性能可用 Cython/Rust 重写核心模块
- Signal 格式作为契约，双方可以不改对方代码独立升级

---

## 6. 缺点

### 6.1 增加间接层

Signal 序列化/反序列化带来额外的 I/O 开销和延迟。对**实盘毫秒级决策场景**，File-based Signal 传递可能不够快。需评估是否在实盘模式下改用内存队列。

### 6.2 初期开发成本

- 新建 `common/signal_models` 模块
- 重构所有策略文件，剥离交易依赖
- 重写 `SignalConsumer` 替代 `SignalBridge`
- 迁移重复的信号逻辑

这部分成本约 **3~5 天** 的集中开发期。

### 6.3 需要额外维护接口兼容性

- Signal 格式一旦定下来，变更需要双方同步协调
- 版本化管理 Signal 格式（至少支持向后兼容 1 个版本）

### 6.4 轻量模拟器与全量回测的偏差

轻量仿真 Simulator 可能因为没有 PositionManager/CapitalManager 的完整逻辑，与全量回测产生细微偏差。需要建立**校准机制**（Simulator 结果 → 全量 Backtest Engine 复验）。

---

## 7. 迁移成本估算

### 7.1 分阶段人天估算

| 阶段 | 内容 | 人天 | 产出 |
|:----|:-----|:----|:-----|
| **Phase 1** | common/signal_models + 序列化模块 | 1 天 | `src/common/signal/` |
| **Phase 2** | 策略文件重构（剥离交易依赖）+ 统一 Signal 产出 | 3 天 | 所有策略 → 输出 Signal |
| **Phase 3** | 轻量研究 Simulator | 2 天 | `research/simulator/` |
| **Phase 4** | SignalConsumer（交易侧） | 1.5 天 | `trading/signal_consumer/` |
| **Phase 5** | 双系统并行运行 + 数据比对验证 | 2 天 | 新旧系统结果一致 |
| **Phase 6** | 废弃旧代码 + 清理 import | 0.5 天 | 移除 signal_bridge 等 |
| **预留缓冲** | 调试、troubleshooting | 2 天 | — |
| **合计** | | **12 天** | **约 2.5 工作周** |

### 7.2 风险最大的部分

**Phase 2（策略文件重构）** 是最大的风险点：

- `src/backtest/strategies/` 下有十多个策略文件，每个都需要重新审查 import 路径
- `SignalStrategy` 基类需要兼容现有子类，不能破坏现有回测脚本
- `_pipeline_main_v2.py` 等流水线脚本间接依赖策略的 on_bar() 接口
- 风险点在于**遗漏依赖**：某个策略的 deep import chain 中藏了对 OrderSide/OrderType 的隐性依赖，重构后才被发现

**应对措施**：
- Phase 2 在 feature branch 上做，CI 跑全量测试
- 先做依赖扫描（`python -c "import ..."` 测试所有策略能否独立 import）
- 渐进式迁移：先改 1 个策略验证，再批量改其余

次要风险：Phase 5（双系统比对）耗时取决于偏差大小。若轻量 Simulator 和完整 Backtest Engine 的对账结果差异过大，可能需要回溯修改 Simulator 逻辑。

---

## 8. 长期扩展性

### 8.1 多策略组合研究

解耦后，研究系统可以独立运行**多种策略**，每条策略输出独立的 Signal 流。组合层可以：

- 加权合并多个 Signal
- 做策略间的相关性分析
- 构建**信号融合层**（Signal Fusion Layer）

### 8.2 机器学习集成

Signal Producer 接口支持插入 ML 模型：

```python
class MLSignalProducer(SignalProducer):
    def produce(self, context) -> List[Signal]:
        features = self.feature_pipeline.transform(context)
        predictions = self.model.predict(features)
        return [self._to_signal(pred) for pred in predictions]
```

### 8.3 多交易通道

交易系统的 SignalConsumer 可以实例化为多个：

- `RealTrader` — 连接到 IB/CTP 等真实券商
- `PaperTrader` — 模拟交易（类似现有的 TradeWindowProcessor）
- `BacktestConsumer` — 回放 Signal 到完整 Backtest Engine
- `AuditTrader` — 只记录不执行，用于合规审计

### 8.4 实时研究平台

研究系统可以扩展为**流式处理**：

- Signal Producer 接入 Kafka/RabbitMQ
- 支持日内实时 Signal 生成（不限于日终回测）
- 轻量 Simulator 支持滚动窗口验证

### 8.5 多语言支持

Signal 序列化格式（JSON/Parquet）是语言无关的。交易系统如果未来需要用 Go/Rust 重写高性能部分，Signal 格式可作为对接口：

```
Python 研究系统 → Signal JSON → Go 交易执行引擎
```

### 8.6 更丰富的归因分析

解耦后可以做到：

- **Alpha 归因**：研究策略的信号质量（信息比率、IC）
- **Execution 归因**：交易系统的执行成本（滑点、手续费、冲击成本）
- 两者分开可针对性地优化

---

## 9. 风险 — 我最担心的三件事

### ⚠️ 风险 1：Phase 2 重构过程中破坏现有流水线

**严重程度**: 高 | **概率**: 中

当前系统每天都稳定产出 morning/evening 报告。解耦重构可能无意中破坏 `_pipeline_main_v2.py` 等关键流水线脚本。

**缓解措施**：
- feature branch + CI 全量测试（回测 + 报告生成 + 知识库入库）
- 保留旧的 `backtest/` 目录结构不做物理迁移，只改 import 路径 + 接口
- 重构完成后，新旧双系统并行运行至少 3 个交易日，逐日对账

### ⚠️ 风险 2：轻量 Simulator 与完整 Backtest Engine 的偏差不可接受

**严重程度**: 中 | **概率**: 中高

轻量 Simulator 省略了 PositionManager（多空对冲逻辑）、CapitalManager（资金分配）等模块。对简单策略（如 MA crossover）可能偏差可忽略，但对复杂策略（如网格策略的多仓位、多方向管理）可能产生显著差异。

**缓解措施**：
- Simulator 设计为 "可插拔执行器"：默认用轻量模式，也支持 FullEngine 模式
- 先对每个策略跑对标测试，记录偏差率
- 偏差率超过阈值（如 5%）的策略，其 Simulate 管道自动切换到 FullEngine 模式

### ⚠️ 风险 3：这个重构能坚持做完吗？

**严重程度**: 中 | **概率**: 中

从经验来看，这种解耦重构的最大风险不是技术难度，而是**持续性的投入**。Phase 1-2 需要 4 天的集中精力，中间如果插入其他紧急任务（系统故障、外部需求、临时修复），注意力被打散后重构很可能搁置。最终变成"半重构"状态——部分文件用新接口、部分用旧接口，反而比之前更混乱。

**缓解措施**：
- 每日固定 2 小时专门用于重构，不接受打断
- 增量推进：每天完成 1 个小模块的迁移，当天验证通过才收工
- 如果实在无法连续投入，至少保证 Phase 1（common/signal_models）先完成——这个模块是纯新增，不会和现有系统冲突，且后续所有步骤都依赖它

---

*以上分析基于当前代码库的直接审计，结合下午产出的 `split_architecture_design_20260519.md` 框架性设计。具体人天估算为保守值，实际可能因代码细节差异浮动 ±30%。*
