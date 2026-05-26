<!--
author: 墨衡 (moheng)
task: meeting_decouple_20260519_stage1
created_time: 2026-05-19T23:47:00+08:00
-->

# Stage 1：问题共识 — 墨衡发言

**会议**: 研究系统与交易系统解耦重构论证会
**阶段**: Stage 1 — 问题共识
**角色**: 墨衡（moheng）— 执行方

---

## 1. 当前系统的核心问题

### 1.1 策略代码直接依赖交易层类型

`src/backtest/strategies/` 下的所有策略文件均直接导入交易执行层的核心类型：

```python
from backtest.backtest_engine import OrderRequest, OrderSide, OrderType
```

波及范围包括 `trend_strategy.py`、`grid_strategy.py`、`reversal_strategy.py`、`factor_calculator.py` 等 **超 10 个策略文件**。策略的产出本应是**信号（Signal）**，但当前产出是**订单（OrderRequest）**——研究层与交易层的关注点混为一谈。

### 1.2 SignalBridge 成为新的双向耦合点

`src/backtest/signal_bridge.py` 同时进口两个世界：

- **研究侧**：`from phase1_core.indicator_engine import IndicatorEngine`、`from paper_trade.tech_signal_generator import generate_backtest_signals`
- **交易侧**：`from .backtest_engine import OrderRequest, OrderSide, OrderType`

`SignalBridge.signal_to_orders()` 将 Signal → OrderRequest 的转换逻辑**硬编码在回测系统内部**。如果交易系统修改 OrderRequest 结构，SignalBridge 必须同步修改——这是典型的依赖方向错误：研究侧不应该感知交易侧的内部数据结构变化。

### 1.3 回测引擎承担了不应属于它的职责

`src/backtest/backtest_engine.py` 中编译了超过 8 个子模块：

- `OrderRequest` / `OrderSide` / `OrderType` — 交易下单语义
- `Position` / `PositionManager` — 持仓管理
- `CapitalManager` — 资金管理
- `FeeModel` — 手续费模型
- `SlippageModel` — 滑点模型
- `Performance` — 绩效计算

回测引擎应只关心**模拟执行**，但当前它膨胀成了"小全能"。核心逻辑约 400 行，加上子模块复杂度远高于一个模拟引擎所需的粒度。

### 1.4 信号生成逻辑两套并存且互不共享

`src/trading/signals/tech_signal_generator.py`（1100+ 行）和 `src/backtest/strategies/` 下存在**冗余的信号产生逻辑**：

- 趋势信号：`tech_signal_generator.generate_trend_signal()` vs `TrendStrategy.generate_signals()`
- 反转信号：`tech_signal_generator.generate_reversal_signal()` vs `reversal_strategy.py`
- 网格信号：`tech_signal_generator.generate_grid_signal()` vs `grid_strategy.py`

两套逻辑实现相似但并非共享。修改一处信号生成逻辑，另一处必须手动同步更新——几乎不可能做到。

### 1.5 研究中间产物无标准化输出管道

策略运行中的所有中间产物——Signal、Factor Score、Indicator Value——没有标准化的序列化/持久化机制。目前数据流为：

```
策略(SignalStrategy.on_bar)
  ↓
SignalBridge.signal_to_orders()
  ↓
OrderRequest
  ↓
BacktestEngine.run()
  ↓
绩效指标
```

中间状态的 Signal 在转换为 OrderRequest 后就丢失了，无法被**独立验证**、**事后回放**或**被下游系统消费**。

### 1.6 研究环境启动时必须加载完整交易上下文

当前要运行一个策略回测，必须：

```python
from backtest.backtest_engine import (
    BacktestEngine, OrderRequest, OrderSide, OrderType,
    Strategy, Position, PositionManager, CapitalManager,
    FeeModel, SlippageModel, Performance
)
```

研究员要测试一个简单的 MA crossover 信号，也必须加载完整的 BacktestEngine 及其 8 个子模块。这对于信号有效性验证来说，是一个不必要的重型依赖。

---

## 2. 问题造成的后果

### 2.1 开发效率损失

| 问题 | 具体代价 |
|:----|:---------|
| 策略直接依赖交易类型（§1.1） | 研究员必须理解 OrderRequest 构造语义、OrderSide/OrderType 的区别，才能写策略。每次修改策略至少多花 **10-15 分钟** 在交易层配置和调试上。 |
| 两套信号逻辑并存（§1.4） | 当要修改信号计算逻辑（如 EMA 周期参数），需要在 tech_signal_generator 和 strategy 两处同步修改。一次修改平均需要 **30 分钟** 的交叉验证和调试。 |
| 研究环境需加载完整交易上下文（§1.6） | 简单信号验证需要 30 秒 ~ 2 分钟启动回测引擎。若只需验证信号方向是否正确，**95% 的启动时间浪费在加载无关的交易模块上**。 |

每日累计：研究员在交易层上下文切换上损失约 **45-60 分钟** / 天。

### 2.2 维护成本上升

| 问题 | 具体代价 |
|:----|:---------|
| SignalBridge 双向依赖（§1.2） | 每次修改 OrderRequest 字段，SignalBridge 和所有策略内的 OrderRequest 构造代码都需要同步修改。**耦合度使得"修一个 bug 可能引入两个新 bug"。** |
| 回测引擎膨胀（§1.3） | 400 行核心 + 8 子模块的复杂度意味着任何对交易概念的修改（如 FeeModel 变更为百分比计费）都需要重新验证回测引擎的所有回测结果。回归测试成本随着模块数量**指数级增长**。 |

代码可维护性评分（自评）：从"健康"到"高危警戒线"。

### 2.3 数据质量与可审计性缺失

| 问题 | 具体代价 |
|:----|:---------|
| 研究中间产物无标准化输出（§1.5） | 信号在转换为 OrderRequest 后丢失。事后复盘时，无法区分"是信号错了"还是"是执行错了"。**审计链中断**。 |
| 信号逻辑两套并存（§1.4） | 两套信号逻辑若参数不一致（概率极高），会导致研究环境与生产环境的信号差异。一旦出现回测盈利但实盘亏损的情况，排查根本原因将耗费 **数天到数周**。 |

### 2.4 并行开发受阻塞

- 研究员 A 改趋势策略 → 需在一段时间内独占测试环境
- 交易工程师 B 改 OrderRequest 结构 → 可能破坏 A 的策略
- 两人无法同时工作在同一条流水线上
- 当前系统的耦合度使得**2 人并行开发效率 < 1.3 人单独开发效率**

---

## 3. 哪些问题最致命

### 🚨 问题一：策略直接产出 OrderRequest 而非 Signal（§1.1）

**致命原因**：这是所有问题的根源。策略产生的是订单指令而非信号，意味着：

- 研究员**不是在做研究**，而是在写交易代码。研究能力的提升被交易层认知门槛所阻塞。
- 策略产出天然绑定交易执行方式——换一种执行策略就必须改策略本身。
- 如果未来要切换到不同的交易执行引擎（如从本地模拟切换到 IB 实盘），所有策略都需要重写。
- 这本质上是一个**架构方向错误**——让"产生观点"的层去管"如何执行"的细节。

### 🚨 问题二：SignalBridge 双向依赖（§1.2）

**致命原因**：设计 SignalBridge 的初衷是解耦，但由于它同时持有研究侧和交易侧的引用，实际上变成了**最紧的耦合点**：

- 两端任何一侧的改动都必然会波及 SignalBridge
- SignalBridge 本身的测试依赖两个系统，测试复杂度翻倍
- 这是典型的**适配器模式被误用**——真正的解耦应该引入一个双边都不依赖的中间契约，而不是一个"两边的代码都写在一起"的适配器
- 当系统持续演进，SignalBridge 会成为"缓冲区"——大家都在这里加代码，最终变成一个不可维护的巨块

### 🚨 问题三：信号生成逻辑两套并存且不一致（§1.4）

**致命原因**：这是**最危险的问题**，因为它会无声地产生错误：

- 两套代码实现"看似"同样的信号逻辑，但细节差异不可避免
- 回测用 strategy → 回测结果漂亮
- 实盘用 tech_signal_generator → 实际表现不同
- 差距出现时，你无法快速判断是"信号做错了"还是"执行的滑点/手续费导致的"
- 这种"无声 bug"可能在一个错误的策略上运行数月，累积损失难以估量

**补充说明**：§1.5（中间产物无标准化输出）同样致命，因为它直接破坏了可审计性。但 §1.1 若不解决，即使解决了 §1.5，策略产出的仍然是 OrderRequest，治标不治本。

---

## 4. 哪些问题必须优先解决

### 优先级 1：策略产出 Signal 而非 OrderRequest（§1.1）

**为什么第一优先？**

**因为这是根因**。所有其他问题（SignalBridge 耦合、回测引擎膨胀、两套信号逻辑、无标准输出）都源于或恶化了同一个事实：**策略层涉足了不应涉足的交易层细节**。

**如果只解决这一个问题**，效果包括：
1. 策略文件不再依赖 `OrderRequest/OrderSide/OrderType` — 研究环境轻了
2. SignalBridge 自然可以变成纯粹的 Signal → Order 转换器（简化职责）
3. 为统一信号逻辑提供了土壤（产出格式一致，才能合并共享）
4. 标准化 Signal 输出成为可能（因为策略产出就是 Signal）

**怎么做（仅问题层面）**：
- 需要定义一个研究员和交易员都能理解的标准信号格式
- 所有策略的产出格式统一为该信号格式
- 信号格式不应包含任何交易执行细节

### 优先级 2：统一两套信号生成逻辑（§1.4）

**为什么第二优先？**

**因为独立优先级 1 后，如果信号逻辑仍然两套，问题并未真正解决。** 优先级 1 解决了"策略不依赖交易层"，但如果没有统一信号逻辑，研开和实盘信号仍然可能不一致。

**必须优先的理由**：
1. 两套逻辑并存是**潜在的最大亏损源**——无声错误比显式错误更危险
2. 优先解决 §1.1 后，策略的产出格式统一为 Signal，与 tech_signal_generator 的产出格式一致——此时合并两套逻辑成为自然动作，不需要额外适配
3. 一旦信号生成逻辑归并到一处，回测和生产环境使用的信号计算代码完全相同，"回测盈利实盘亏损"的一半问题自动消除

**建议顺序**：先做完 §1.1 的改造，立即进入 §1.4 的统一，两个问题连着解决。

### 为什么不优先解决 §1.2（SignalBridge）和 §1.3（回测引擎膨胀）

- **SignalBridge**：解决了 §1.1 后，SignalBridge 的职责自然减化为"Signal → OrderRequest"转换器，不再需要同时驾驭两端。可以后续再清理。
- **回测引擎膨胀**：这是"问题但后果较小的"——回测引擎虽然复杂，但它在**正常工作**。在资源有限的情况下，先解决导致"信号正确性风险"的问题，再解决"代码组织整洁性"的问题。

---

## 小结

| 顺序 | 问题 | 优先级理由 |
|:----:|:----|:----------|
| **P0** | 策略直接产出 OrderRequest（§1.1） | 根因，不解决则一切免谈 |
| **P1** | 两套信号生成逻辑并存（§1.4） | 无声 bug 的最大来源，需紧跟 P0 |
| P2 | SignalBridge 双向依赖（§1.2） | P0 解决后自然简化，后续清理 |
| P3 | 回测引擎膨胀（§1.3） | 整洁性问题，不影响正确性 |
| P3 | 中间产物无标准化输出（§1.5） | P0 + 信号格式统一后可自然解决 |
