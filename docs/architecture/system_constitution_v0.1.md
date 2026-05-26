# 墨枢系统宪法 v0.1
## System Constitution — 研究系统与交易系统解耦重构

> **author**: 墨涵 (mohan)
> **created**: 2026-05-20T01:00+08:00
> **updated**: 2026-05-20T01:10+08:00 (v0.1 复核修正)
> **origin**: 《研究系统与交易系统解耦重构论证会》Stage 0~1, 全员共识
> **定位**: 这不是技术文档，这是"什么永远不能被破坏"

---

## 一、架构原则（Architecture Principles）

所有设计和评审的最高依据。违反任何一条 = 设计驳回。

| 编号 | 原则 | 含义 |
|:----:|:----|:-----|
| **AP-01** | 单向依赖原则 | Research 不依赖 Trading。依赖方向只能自上而下。 |
| **AP-02** | 契约优先原则 | 系统间仅通过协议通信，不共享内部状态。 |
| **AP-03** | 生命周期隔离原则 | Research、Portfolio、Execution 生命周期独立。 |
| **AP-04** | 可审计原则 | 所有研究结论必须可追溯（Evidence → Signal → Decision）。 |
| **AP-05** | 禁止隐式耦合 | 禁止通过文件副作用、全局变量、共享状态通信。**例外豁免**：文件系统异步通信（JSON/MD 信号文件）视为 Event 协议的一种实现，遵循最终一致性要求。仍禁止通过文件副作用传递运行时状态或隐式控制流。 |

---

## 二、限界上下文（Bounded Contexts）

### 2.1 总览

> 整个系统由 **5 个核心 Context**（交易相关）+ **3 个支撑 Context**（治理相关）组成。

#### 5 个核心 Context

| Context | 职责 | Owner | 位置 |
|:--------|:-----|:-----|:-----|
| **Research** | Signal 研究 | 墨衡 | research/ |
| **Trading** | 下单执行 | （待定） | trading/ |
| **Risk** | 风控拦截 | （待定） | risk/ |
| **Portfolio** | 仓位配置 | （待定） | portfolio/ |
| **Knowledge** | 知识治理 | （待定） | knowledge/ |

#### 3 个支撑 Context

| Context | 职责 | Owner | 位置 |
|:--------|:-----|:-----|:-----|
| **Layer Q** | 质量审计 | 墨涵 | q_layer/ |
| **Testing** | 验收测试 | 墨萱 | testing/ |
| **Strategy Governance** | 架构治理与合规 | 墨涵 | governance/ |

### 2.2 Research Context

| | 内容 |
|:---|:-----|
| **负责** | Signal 研究、证据收集、分析输出 |
| **不负责** | 仓位计算、风控判断、订单路由、执行决策 |
| **禁止** | 修改仓位、下单、写账户、读取 Trading 数据库 |
| **输出** | Structured Signal（direction + confidence + horizon + regime + evidence_hash + metadata） |

### 2.3 Trading Context

| | 内容 |
|:---|:-----|
| **负责** | 下单执行、订单路由、重试、连接器管理 |
| **不负责** | Signal 生成、研究逻辑判断、仓位配置决策 |
| **禁止** | 读取研究逻辑、修改 Signal 方向、自行决定权重调整 |
| **输出** | 成交记录 + 执行回执（含 evidence_hash 引用） |

### 2.4 Risk Context

| | 内容 |
|:---|:-----|
| **负责** | 风控规则引擎、限额计算、交易前/后校验 |
| **不负责** | Signal 生成、仓位分配、策略设计 |
| **禁止** | 修改 Signal、替换 Trading 决策、参与交易执行逻辑 |
| **输出** | risk_verdict（PASS/BLOCK/REVIEW） |

### 2.5 Portfolio Context

| | 内容 |
|:---|:-----|
| **负责** | 资金配置、仓位分配、组合风险暴露管理 |
| **不负责** | Signal 研究、风控规则定义、交易执行 |
| **禁止** | 修改 Signal、执行订单、覆盖风控裁决 |
| **输出** | position_caps + 仓位快照 |

### 2.6 Knowledge Context

| | 内容 |
|:---|:-----|
| **负责** | 决策知识归档、历史回测结果存储、元数据治理 |
| **不负责** | 缓存层、日常日志、中间产物管理 |
| **禁止** | 成为 God Context — 不存储运行时状态，只存已完成的决策记录 |
| **输出** | 结构化知识条目（含 backtest_hash + expires_at） |

### 2.7 Testing Context

| | 内容 |
|:---|:-----|
| **负责** | 测试计划制定、集成测试执行、协议合规性验证、验收报告输出 |
| **不负责** | 设计评审、代码审查、生产环境监控 |
| **禁止** | 修改生产契约、跳过 Layer Q 审计结果 |
| **输出** | Acceptance Report（PASS/FAIL + 测试覆盖率 + 缺陷清单） |

**Testing 与 Layer Q 的流水线关系**：Testing 验收基于 Layer Q 审计通过为前提。Q 层审计结果为 BLOCK 时，Testing 不启动验收。两者是流水线上下游关系，非并列关系。

### 2.8 Strategy Governance Context

| | 内容 |
|:---|:-----|
| **负责** | 架构合规自检、技术债务治理、契约版本演进管理 |
| **不负责** | 策略设计、日常运营、市场判断 |
| **禁止** | 干预 Layer Q 审计判断、参与交易决策 |
| **输出** | 架构合规报告 + 债务日志 |

---

## 三、跨层通信协议

### 3.1 核心规则

**任何 Context 不得直接读取其他 Context 内部数据库。**

通信只能通过以下四种方式：

```
Protocol  → 契约化接口（JSON Schema / Protobuf / OpenAPI）
API       → 有状态调用（同步请求-响应）
Event     → 异步通知（信号产生、风险触发、执行回执归档）
Snapshot  → 状态快照（仓位快照、风控预算快照）
```

> 文件系统异步通信（JSON/MD 信号文件）视为 Event 协议的一种实现。  
> 仍禁止通过文件副作用传递运行时状态或隐式控制流。

### 3.2 层间通信矩阵

| 方向 | 方式 | 协议 | 一致性要求 |
|:----|:----|:----|:----------|
| **Research → Trading** | Protocol | Signal Protocol（只读，单向） | 最终一致 |
| **Trading → Risk** | API | 订单校验请求 + Verdict 返回 | 强一致（同步阻塞） |
| **Risk → Portfolio** | Snapshot | 风险预算快照 | 接近实时（≤1s） |
| **Trading → Knowledge** | Event | 执行回执（含 evidence_hash + 成交明细） | 最终一致（可延迟数分钟） |
| **Risk → Knowledge** | Event | 风险事件日志 | 强一致（日志不可丢） |
| **Research → Knowledge** | Event | 结构化存档 + backtest_hash 去重 | 最终一致 |
| **Portfolio → Trading** | Snapshot | position_caps.json | 可缓存 ≤30s |
| **Layer Q → Knowledge** | Event | 审计意见归档（PASS/WARN/FAIL） | 最终一致 |
| **Layer Q 审计数据来源** | Event（Knowledge） | 通过 Knowledge 的 Event 归档获取 Research Output 和执行回执，不直接读任何 Context 内部存储 | — |

### 3.3 Signal Protocol（核心契约）

```
Signal {
  direction:   BUY/SELL/HOLD      (必须)
  confidence:  0.0~1.0            (必须)
  horizon:     short/medium/long  (必须, 精确范围由 Knowledge 元数据定义)
  regime:      趋势/震荡/事件驱动  (可选, 建议)
  signal_type: entry/adjustment/exit (必须)
  evidence_hash: string           (必须, 审计追溯)
  source_id:   string             (必须, 研究源标识)
  metadata:    {protocol_version, timestamp, strategy_id} (必须)
  weight:      0.0~1.0            (可选, 信号强度权重非仓位建议)
}
```

**Signal 禁止包含**：持仓逻辑、风控参数、仓位建议、execution 信息。

---

## 四、已采纳的架构决策（ADR）

| 编号 | 决议 | 日期 |
|:----:|:-----|:----|
| ADR-001 | Signal 协议必须为结构化对象，非裸 BUY/SELL | 2026-05-20 |
| ADR-002 | Signal 不包含仓位、风控、execution 信息 | 2026-05-20 |
| ADR-003 | Execution 不读取研究逻辑 | 2026-05-20 |
| ADR-004 | Portfolio 独立于 Research | 2026-05-20 |
| ADR-005 | Layer Q 审计 Research Output（主通道，通过 Knowledge Event 归档获取）+ Execution Behavior（辅通道） | 2026-05-20 |
| ADR-006 | 系统划分为 8 个限界上下文：5 核心（Research/Trading/Risk/Portfolio/Knowledge）+ 3 支撑（Layer Q/Testing/Governance） | 2026-05-20 |
| ADR-007 | 禁止跨 Context 直接读取内部数据库 | 2026-05-20 |
| ADR-008 | signal_type（entry/adjustment/exit）为 Signal 协议 mandatory 字段 | 2026-05-20 |
| ADR-009 | 文件系统异步通信视为 Event 协议实现，不违反 AP-05 | 2026-05-20 |
| ADR-010 | Testing 验收基于 Layer Q 审计通过的前提，两者为流水线上下游关系 | 2026-05-20 |

---

## 五、v0.1 明确不解决的问题

> 防止白皮书无限膨胀。只定义边界与契约。

**当前版本不讨论：**
- 分布式部署
- 高频交易
- 微服务化
- 云部署
- UI/可视化
- 实时风控实现细节
- 多机调度
- 多数据源统一接入
- 知识图谱
- 运行时争议仲裁机制（留 v0.2）
- 修宪流程细则（留 v0.2）
- 技术债务记录机制（留 v0.2）

**当前版本只定义：**
- 边界与契约
- 哪些永远不能做

---

## 六、系统退化警告（Architecture Failure Modes）

若违反以下红线，系统将重新退化为单体耦合。每条红线对应明确的后果。

| 红线 | 违反后果 | 严重等级 |
|:----|:---------|:--------:|
| Signal 携带仓位或风控指令 | Research 和 Trading 重新耦合 | 🔴 P0 |
| Execution 理解研究逻辑 | 分层架构崩塌，Trading 成为 Research 的延伸 | 🔴 P0 |
| Strategy 同时负责 Signal + Position + Order | 回到"职责爆炸"原状 | 🔴 P0 |
| 研究层直接读账户/持仓 | 绕过 Portfolio 和 Risk，产生审计黑洞 | 🔴 P0 |
| Portfolio 修改 Signal 方向 | 本末倒置，资金配置层替代研究做判断 | 🟡 P1 |
| Layer Q 参与交易决策 | Q 层从审计者变成执行者，自身不可审计 | 🟡 P1 |
| 跨 Context 直接读对方数据库 | 隐式耦合再生，半年后边界实际上是假的 | 🔴 P0 |
| Knowledge Context 存储运行时状态 | Knowledge 从归档变成交互依赖，单点故障 | 🟡 P1 |
| Testing 跳过 Layer Q 审计结果 | 质量防线被绕过，未通过审计的研究进入生产 | 🟡 P1 |

---

## 七、签署凭证

> 本宪法由《研究系统与交易系统解耦重构论证会》全员讨论并共识。
> 主人定稿批准后生效。修改需全员评审 + Owner 批准。

| 角色 | Agent | 对应 Context | 签署状态 |
|:----|:------|:-----------|:--------|
| 执行方 | 墨衡 | Research | 共识已达成 |
| 技术验收 | 墨萱 | Testing | 共识已达成 |
| 战略审查 | 玄知 | —（独立战略视角） | 共识已达成 |
| 架构治理 | 墨涵 | Layer Q + Strategy Governance | 共识已达成 |
| 知识治理 | 墨涵 | Knowledge（暂兼） | 共识已达成 |
| **Owner** | **主人** | —（全局） | **✅ 已批准** 🖋️ |
