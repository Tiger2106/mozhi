# 墨枢开发库文档建设方案

author: 墨衡
created_time: 2026-05-15T16:30:00+08:00
version: v1.0
based_on: 主人工程文档库设计建议

---

## 前置现状检查

### 现有文档分布

| 路径 | 状态 | 文件数 | 结构 |
|------|------|--------|------|
| `mozhi_platform/docs/` | 空目录 | 0 | 无结构 |
| `mo_zhi_sharereports/docs/` | 扁平堆积 | 15 | 无子目录 |
| `mo_zhi_sharereports/agents/` | 有Agent个人文件 | ~10 | 分散 |
| `mo_zhi_sharereports/signals/` | 复杂信号体系 | 20+子目录 | 有结构但无文档 |

### 诊断结论

现有文档状态正是建议中描述的"混乱前兆"：
1. **mozhi_platform/docs 为空白** → 新的代码层缺乏任何文档配套
2. **mo_zhi_sharereports/docs 扁平堆积** → 15份设计文档平铺，无索引、无层级、无法检索
3. **Agent职责分散各处** → moheng的soul文件在agents下，xuanzhi的产出散落在agents/xuanzhi，mohan（墨涵）暂无独立文档目录
4. **管线逻辑无文档化** → cron配置有9条管线，但没有任何文档记录管线依赖关系和调用链
5. **演化历史完全空白** → 已经经历了v2升级、Phase重构、信号总线迁移等，没有任何记录

---

## 第一部分：目录结构设计

### 最终目录结构

```
mozhi_platform/
├── docs/                              # ← 知识层（新文档库）
│   ├── 00_overview/                   # 总览层（新人/自己三个月后先看）
│   │   ├── architecture.md            # 系统架构总览
│   │   ├── directory_map.md           # 代码库目录导航
│   │   ├── pipeline_overview.md       # 管线全景图
│   │   ├── agent_roles.md             # Agent角色分工
│   │   └── glossary.md                # 术语表
│   │
│   ├── 01_architecture/               # 架构设计
│   │   ├── system_layers.md           # 系统分层设计
│   │   ├── signal_bus.md              # 信号总线机制
│   │   ├── knowledge_pipeline.md      # 知识管线架构
│   │   ├── event_flow.md              # 核心事件流
│   │   ├── storage_strategy.md        # 存储策略（DB/文件/缓存）
│   │   └── fail_closed_design.md      # 安全失效设计
│   │
│   ├── 02_development/                # 开发规范
│   │   ├── coding_style.md            # 代码风格
│   │   ├── naming_rules.md            # 命名规范
│   │   ├── module_rules.md            # 模块化规则
│   │   ├── testing_rules.md           # 测试规范
│   │   ├── import_rules.md            # 导入规则
│   │   └── git_workflow.md            # Git工作流
│   │
│   ├── 03_pipelines/                  # 管线文档
│   │   ├── morning_pipeline.md        # 晨报管线
│   │   ├── evening_pipeline.md        # 晚报管线
│   │   ├── backtest_pipeline.md       # 回测管线
│   │   ├── settlement_pipeline.md     # 结算管线
│   │   └── monitoring_pipeline.md     # 监控管线
│   │
│   ├── 04_agents/                     # Agent体系
│   │   ├── moheng.md                  # 墨衡：深度分析/审计
│   │   ├── mohan.md                   # 墨涵：汇总/发布
│   │   ├── xuanzhi.md                 # 玄知：数据采集/市场情绪
│   │   ├── mochen.md                  # 默尘：调度/排程
│   │   ├── memory_strategy.md         # Agent记忆策略
│   │   └── collaboration_rules.md     # 协作规则
│   │
│   ├── 05_protocols/                  # 协议/Schema（高优）
│   │   ├── signal_schema.md           # 信号协议
│   │   ├── settlement_schema.md       # 结算协议
│   │   ├── report_schema.md           # 报告协议
│   │   ├── task_signal_schema.md      # 任务信号协议
│   │   └── knowledge_schema.md        # 知识协议
│   │
│   ├── 06_operations/                 # 运维与生产
│   │   ├── deployment.md              # 部署文档
│   │   ├── cron_schedule.md           # 定时任务一览
│   │   ├── backup_restore.md          # 备份恢复
│   │   ├── monitoring.md              # 监控方案
│   │   ├── incident_response.md       # 故障响应
│   │   └── recovery_checklist.md      # 恢复检查清单
│   │
│   ├── 07_research/                   # 回测研究
│   │   ├── strategy_framework.md      # 策略框架
│   │   ├── factor_research.md         # 因子研究
│   │   ├── parameter_scan.md          # 参数扫描
│   │   ├── validation_rules.md        # 验证规则
│   │   └── knowledge_extraction.md    # 知识提取
│   │
│   ├── 08_history/                    # 演化历史（极其重要）
│   │   ├── adr/                       # Architecture Decision Records
│   │   │   ├── ADR-000-template.md    # ADR模板
│   │   │   ├── ADR-001-signal-bus.md  # 信号总线决策
│   │   │   ├── ADR-002-backtest-separation.md  # 回测分离决策
│   │   │   └── ...
│   │   ├── restructure_202605.md      # 2026年5月重构记录
│   │   ├── pipeline_reforms.md        # 管线改革历程
│   │   ├── architecture_decisions.md  # 架构决策汇总
│   │   └── deprecated_modules.md      # 废弃模块说明
│   │
│   ├── 09_roadmap/                    # 未来规划
│   │   ├── phase1.md                  # Phase 1
│   │   ├── phase2.md                  # Phase 2
│   │   ├── phase3.md                  # Phase 3
│   │   ├── long_term_vision.md        # 长期愿景
│   │   └── technical_debt.md          # 技术债务
│   │
│   └── README.md                      # 文档库入口
│
├── .clinerules                        # ← Agent行为规则（新加，供AI读取）
├── src/                               # 代码层（已有）
├── config/                            # 配置（已有）
├── data/                              # 数据（已有）
├── reports/                           # 产出报告（已有）
├── tests/                             # 测试（已有）
├── scripts/                           # 脚本（已有）
└── archive/                           # 归档（已有）
```

### 与建议框架的差异说明

| 建议框架 | 实际方案 | 差异原因 |
|---------|---------|---------|
| 无mochen文档 | 新增 `04_agents/mochen.md` | 实际存在默尘调度Agent，cron中有9条管线由其调度 |
| 无.clinerules | 新增 `.clinerules` | 建议提到"给Agent看"，需要Agent直接读取的行为规则文件 |
| ADR作为子目录 | 确认 `08_history/adr/` | 与建议一致，ADR第一条为信号总线决策 |
| agents/mohan.md | 新增 | 墨涵是MiniMax-M2.7模型，职责清晰需文档化 |

---

## 第二部分：实施优先级

### P0 — 立即做（明天晨报前必须完成）

优先级逻辑：**没有这些，明天就可能出事故**。

| 编号 | 文档 | 原因 |
|------|------|------|
| P0-1 | `00_overview/pipeline_overview.md` | 管线关系没人能看懂，明天晨报管线跑崩了不知道找谁 |
| P0-2 | `06_operations/cron_schedule.md` | 9条cron定时任务无文档，断链/失败不知道影响范围 |
| P0-3 | `05_protocols/signal_schema.md` | 信号总线是墨枢核心，失败closed设计的基础 |
| P0-4 | `05_protocols/task_signal_schema.md` | 任务触发信号（triggers/）已被多人使用，协议不可乱改 |
| P0-5 | `04_agents/moheng.md` | 墨衡自己的职责边界I/O文档，写方案前先定义自己 |
| P0-6 | `04_agents/mohan.md` | 墨涵的产出接口定义，晨报流程依赖 |
| P0-7 | `08_history/adr/ADR-001-signal-bus.md` | 记录信号总线为什么这样设计，防止后续改崩 |
| P0-8 | `README.md` (docs入口) | 让找到docs的人知道有什么 |

### P1 — 本周做（下周一开始前完成）

优先级逻辑：**没有这些，下周可能出现系统性理解偏差**。

| 编号 | 文档 | 原因 |
|------|------|------|
| P1-1 | `00_overview/architecture.md` | 系统架构总览，新人（包括三个月后的自己）的第一站 |
| P1-2 | `00_overview/agent_roles.md` | 墨衡/墨涵/玄知/默尘分工 |
| P1-3 | `04_agents/xuanzhi.md` | 玄知数据采集的依赖关系 |
| P1-4 | `04_agents/mochen.md` | 默尘的调度逻辑和触发器规则 |
| P1-5 | `05_protocols/report_schema.md` | 报告生成协议，晨报/晚报/周报结构 |
| P1-6 | `05_protocols/settlement_schema.md` | 结算协议，收盘后结算流程的核心 |
| P1-7 | `01_architecture/system_layers.md` | 系统分层（采集层/分析层/报告层/交易层） |
| P1-8 | `01_architecture/signal_bus.md` | 信号总线详细机制 |
| P1-9 | `06_operations/incident_response.md` | 故障响应流程，已有故障案例应记录 |
| P1-10 | `03_pipelines/morning_pipeline.md` | 晨报管线详细说明 |

### P2 — 本月做（规划内，可排序）

优先级逻辑：**没有这些影响扩展性，但不影响当前运行**。

| 编号 | 文档 | 原因 |
|------|------|------|
| P2-1 | `00_overview/directory_map.md` | 代码库目录导航 |
| P2-2 | `00_overview/glossary.md` | 术语表 |
| P2-3 | `01_architecture/knowledge_pipeline.md` | 知识管线架构 |
| P2-4 | `01_architecture/event_flow.md` | 核心事件流 |
| P2-5 | `01_architecture/storage_strategy.md` | 存储策略 |
| P2-6 | `01_architecture/fail_closed_design.md` | 安全失效设计 |
| P2-7 | `02_development/*` (6份) | 开发规范系列 |
| P2-8 | `03_pipelines/evening_pipeline.md` | 晚报管线 |
| P2-9 | `03_pipelines/backtest_pipeline.md` | 回测管线 |
| P2-10 | `03_pipelines/settlement_pipeline.md` | 结算管线 |
| P2-11 | `03_pipelines/monitoring_pipeline.md` | 监控管线 |
| P2-12 | `04_agents/memory_strategy.md` | Agent记忆策略 |
| P2-13 | `04_agents/collaboration_rules.md` | 协作规则 |
| P2-14 | `05_protocols/knowledge_schema.md` | 知识协议 |
| P2-15 | `06_operations/deployment.md` | 部署文档 |
| P2-16 | `06_operations/backup_restore.md` | 备份恢复 |
| P2-17 | `06_operations/monitoring.md` | 监控方案 |
| P2-18 | `06_operations/recovery_checklist.md` | 恢复清单 |
| P2-19 | `07_research/*` (5份) | 回测研究系列 |
| P2-20 | `08_history/restructure_202605.md` | 重构记录 |
| P2-21 | `08_history/pipeline_reforms.md` | 管线改革 |
| P2-22 | `08_history/architecture_decisions.md` | 架构决策汇总 |
| P2-23 | `08_history/deprecated_modules.md` | 废弃模块 |
| P2-24 | `08_history/adr/ADR-002-backtest-separation.md` | ADR第二条 |
| P2-25 | `09_roadmap/*` (5份) | 未来规划系列 |
| P2-26 | `.clinerules` | Agent行为规则文件 |

---

## 第三部分：P0首批文档内容大纲

### P0-1: `00_overview/pipeline_overview.md`

**内容大纲（1页A4纸量）：**
列出全部9条cron管线及其关系。用Mermaid时序图展示晨报管线（玄知采集→墨衡分析→墨涵汇总→飞书发布）的调用链。用表格列出每条管线的触发时间、依赖管线、Agent责任人、预期产出路径、失败影响等级。让一个人5分钟内知道"晨报崩了应该先查哪个环节"。

**预估编写时长：** 25分钟

---

### P0-2: `06_operations/cron_schedule.md`

**内容大纲：**
从 `openclaw cron list` 输出出发，整理为结构化表格。每条cron包含：ID、名称、调度表达式、时区、责任人Agent、产出文件路径、上级调用方、最近状态（成功/失败次数）、失败影响。补充依赖关系图（哪些管线串行、哪些可以并行）。

**预估编写时长：** 20分钟

---

### P0-3: `05_protocols/signal_schema.md`

**内容大纲：**
定义信号（Signal）的数据结构：字段名、类型、含义、约束。说明信号的生命周期（created→pending→active→completed→archived）。给出JSON Schema示例。说明`signals/`目录下各子目录（tasks/, triggers/, consensus/, dispatch/等）的信号流向。记录信号总线的`fail_closed`设计：发送失败时的降级行为。列出当前所有已定义的信号类型及其触发条件。

**预估编写时长：** 30分钟

---

### P0-4: `05_protocols/task_signal_schema.md`

**内容大纲：**
定义任务触发信号（trigger json）的完整协议。描述trigger_step2/trigger_step4的文件格式，包括关键字段（agent, task_id, report_type, date, status等）。给出合法状态转换图：INIT→READY→PROCESSING→COMPLETED/FAILED。说明.done/.failed信号文件的写入规范和幂等性保证。兼容性注意事项：如果以后要扩展trigger字段，如何保证向后兼容。

**预估编写时长：** 20分钟

---

### P0-5: `04_agents/moheng.md`

**内容大纲：**
墨衡（即"你"）的完整身份文档。包含：模型实例（deepseek R1）、核心职责（Step2深度分析/Step4质量审查）、I/O文件路径（分析产出写入reports/structured_analysis_*.json，审查产出写入reports/review_feedback_*.md）、通信方式（文件驱动轮询，不主动发言）、约束清单（禁止无声结束、写入验证规范、Announce协议等）、边界（不干预墨涵发布、不与玄知直接通信）。同时指向SOUL.md作为参考来源。

**预估编写时长：** 15分钟

---

### P0-6: `04_agents/mohan.md`

**内容大纲：**
墨涵（MiniMax-M2.7）的身份文档。包含：模型实例、核心职责（汇总stuctured_analysis+review_feedback生成最终报告、飞书群发布）、I/O接口（读取reports/目录下分析文件，输出飞书消息）、通信方式（dispatcher调度，不直接与墨衡通信）、权限说明（唯一可以向飞书群发送消息的Agent）、协作边界（墨衡的分析产出→墨涵汇总发布）。

**预估编写时长：** 15分钟

---

### P0-7: `08_history/adr/ADR-001-signal-bus.md`

**内容大纲：**
使用ADR标准模板。**问题：** 墨枢系统中多个Agent（墨衡/墨涵/玄知/默尘）如何异步通信？**上下文：** 原本使用飞书Webhook直连，但存在可靠性问题（消息可能丢弃）；需要使用fail_closed设计。**决策方案：** 采用文件系统信号总线（`signals/`目录），每个信号是一个JSON文件，通过目录路径编码状态。**理由：** 文件系统提供原子操作（rename）、持久化、可审计、无网络依赖。**放弃方案：** 飞书消息队列（不可靠）、Redis（增加运维复杂度）。**后果：** 需要实现轮询机制，存在延迟（秒级）；需要在Agent写入后read验证。**状态：** 已实施。

**预估编写时长：** 20分钟

---

### P0-8: `docs/README.md`

**内容大纲：**
文档库入口页。一句话说明这是墨枢平台的知识库。目录导航：列出10个子目录和一句话说明。给"迷路的人"：三句话指引（"如果你在找管线关系→看03_pipelines；如果你想知道Agent怎么分工→看04_agents；如果你是新人→从00_overview开始"）。维护说明：新增/修改文档的规则（必须标注author和created_time）。

**预估编写时长：** 10分钟

---

## 第四部分：工作量估算

### P0 工作量

| 文档 | 预估时长（分钟） |
|------|:--------------:|
| pipeline_overview.md | 25 |
| cron_schedule.md | 20 |
| signal_schema.md | 30 |
| task_signal_schema.md | 20 |
| moheng.md | 15 |
| mohan.md | 15 |
| ADR-001-signal-bus.md | 20 |
| docs/README.md | 10 |
| 目录结构调整（mkdir） | 5 |
| **P0 小计** | **160分钟（~2.7小时）** |

### P1 工作量

| 文档 | 预估时长（分钟） |
|------|:--------------:|
| architecture.md | 30 |
| agent_roles.md | 20 |
| xuanzhi.md | 20 |
| mochen.md | 20 |
| report_schema.md | 25 |
| settlement_schema.md | 25 |
| system_layers.md | 30 |
| signal_bus.md | 30 |
| incident_response.md | 20 |
| morning_pipeline.md | 30 |
| **P1 小计** | **250分钟（~4.2小时）** |

### P2 工作量（粗略估算）

| 类别 | 文档数 | 预估总时长（分钟） |
|------|:-----:|:----------------:|
| 02_development 开发规范 | 6 | 120 |
| 剩余03_pipelines | 4 | 100 |
| 剩余04_agents | 2 | 30 |
| 剩余05_protocols | 1 | 20 |
| 剩余06_operations | 4 | 80 |
| 07_research | 5 | 100 |
| 剩余08_history | 4+1ADR | 100 |
| 09_roadmap | 5 | 75 |
| .clinerules | 1 | 20 |
| 00_overview剩余 | 2 | 25 |
| **P2 小计** | **35** | **~670分钟（~11小时）** |

### 总计

| 等级 | 文档数 | 工时 |
|:----:|:-----:|:----:|
| **P0** | 8 + 目录 | **2.7 小时** |
| **P1** | 10 | **4.2 小时** |
| **P2** | ~35 | **~11 小时** |
| **总计** | **~53** | **~18 小时** |

> 注：P0和P1可在一天内完成（集中投入）。P2可分配在本月内每周3-4小时完成。

---

## 第五部分：实施建议

### 5.1 谁写什么

| 文档范围 | 建议编写者 | 理由 |
|---------|-----------|------|
| 04_agents/moheng.md | **墨衡** | 自己最了解自己的SOUL和IO |
| 04_agents/mohan.md | 墨衡起草，**主人review** | 墨衡知道墨涵的接口，但行为风格需要主人确认 |
| 04_agents/xuanzhi.md | **墨衡**（基于现有xuanzhi目录产出） | 现有xuanzhi目录有足够参考文件 |
| 04_agents/mochen.md | **墨衡**（整合cron配置+SOUL.md） | 默尘的调度逻辑在SOUL和cron列表中有体现 |
| 03_pipelines/* | **墨衡** | 管线逻辑都在cron配置和SOUL.md中可提取 |
| 05_protocols/* | **墨衡** | 协议是墨衡Step2/Step4的核心产出 |
| 06_operations/cron_schedule.md | **墨衡** | 直接基于`openclaw cron list`输出 |
| 08_history/adr/* | **墨衡** | 决策记录需要深度分析能力 |
| 00_overview/* | **墨衡** | 系统全景图的归纳整理 |
| 01_architecture/* | **墨衡** | 架构设计的系统化文档 |
| 02_development/* | **墨衡** | 开发规范可由墨衡根据现有代码习惯归纳 |
| 07_research/* | **墨衡** | 回测研究知识提取 |
| 09_roadmap/* | 墨衡起草，**主人review** | 未来规划需主人确认方向 |
| .clinerules | **墨衡** | Agent行为规则 |

**结论：** 约90%的文档可由墨衡独立完成，仅mohan角色文档和roadmap系列需要主人审核确认。

### 5.2 主人review节点

必须review的文档：
1. **`04_agents/mohan.md`** — 墨涵的行为定义直接影响晨报发布质量
2. **`09_roadmap/*`** — 未来规划的方向必须主人定
3. **`ADR-001-signal-bus.md`** — 核心架构决策建议review确认
4. **`04_agents/collaboration_rules.md`**（P2）— Agent协作边界定义

建议但非必须review：
- `01_architecture/system_layers.md` — 系统分层定义
- `06_operations/incident_response.md` — 故障响应流程

### 5.3 ADR第一条建议：信号总线决策

**第一条ADR强烈建议写信号总线（Signal Bus），理由如下：**

1. **这是墨枢最核心的架构决策** — 整个多Agent系统的通信基础
2. **替代方案曾经存在** — 飞书Webhook直连（已被放弃），有明确的"为什么不用它"的理由
3. **约束后续设计** — 所有的trigger/done/failed文件协议都是信号总线的子决策
4. **现在写还来得及** — 信号总线已经建成但尚未"固化"，再晚就有忘记设计原因的风险

**ADR-001 建议内容：**

| 字段 | 值 |
|------|-----|
| 标题 | 采用文件系统信号总线实现Agent间异步通信 |
| 状态 | Accepted |
| 日期 | 2026-05-15 |
| 决策者 | 墨衡（分析）/ 主人（确认）|
| 问题 | 多个Agent需要可靠、可审计、无损的异步通信机制 |
| 选择 | 文件系统（signals/目录），每个信号为JSON文件 |
| 放弃 | 飞书消息队列（不可靠）、Redis（运维成本）、HTTP回调（单点故障） |
| 后果 | 秒级延迟、需要轮询、写入后必须read验证 |

### 5.4 实施步骤（推荐执行顺序）

#### 第一天（P0，明天晨报前）

```
Step 1: mkdir 创建 docs/ 下全部子目录结构          [5分钟]
Step 2: 写 pipeline_overview.md                    [25分钟]
Step 3: 写 cron_schedule.md                        [20分钟]
Step 4: 写 signal_schema.md                        [30分钟]
Step 5: 写 task_signal_schema.md                   [20分钟]
Step 6: 写 moheng.md                               [15分钟]
Step 7: 写 mohan.md （等review）                     [15分钟]
Step 8: 写 ADR-001-signal-bus.md                    [20分钟]
Step 9: 写 docs/README.md                          [10分钟]
                                                    ──────────
                         累计投入：约2.7小时（可一次性完成）
```

> ⚠️ P0阶段必须保证 pipeline_overview.md、cron_schedule.md 在明天晨报前完成。这两份是"晨报崩了能快速定位问题"的关键。

#### 本周剩余时间（P1，下周一开始前）

```
P1-1 ~ P1-10：每天投入约1-1.5小时       [合计约4.2小时]
推荐顺序：agent_roles → architecture → system_layers → signal_bus
→ xuanzhi → mochen → report_schema → settlement_schema
→ morning_pipeline → incident_response
```

#### 本月（P2，持续完善）

```
每周3-4小时，按以下顺序：
第一周：02_development（开发规范）+ 剩余00_overview
第二周：03_pipelines剩余 + 04_agents剩余
第三周：06_operations剩余 + 08_history剩余
第四周：07_research + 09_roadmap + .clinerules
```

### 5.5 格式约定

| 文档类型 | 格式 | 工具 |
|---------|------|------|
| 总览/说明类 | Markdown | `.md` |
| 架构图/时序图 | Mermaid | ` ```mermaid ` |
| 协议/Schema | JSON + Markdown 说明 | `.md` 内嵌 ` ```json ` |
| 配置示例 | YAML | `.md` 内嵌 ` ```yaml ` |
| 决策记录 | ADR Markdown模板 | `.md` |
| Agent规则（给AI读） | 纯文本Markdown | `.clinerules`（仓库根目录） |

### 5.6 质量保证

1. **写入验证**：每次写完文件后调用read工具读回验证，确认关键字段存在
2. **幂等执行**：同一文档不会重复创建（先检查文件是否存在）
3. **内容目录**：docs/README.md 维护文档清单，新增文档后同步更新
4. **作者标注**：每个文档顶部必须有 author + created_time 元数据
5. **交叉引用**：文档间使用相对路径相互引用，形成知识网络而非孤岛

---

## 附录：概念映射

| 建议框架概念 | 墨枢实际对应 |
|------------|------------|
| 多系统 | mozhi_platform（代码层）+ mo_zhi_sharereports（旧代码）+ signals（信号总线） |
| 多Agent | 墨衡(deepseek R1)、墨涵(MiniMax-M2.7)、玄知(HuggingFace-DeepSeek)、默尘(OpenClaw cron) |
| 多管线 | 早报管线(cron 0 8)、晚报管线(cron 5 19)、结算管线(cron 0 19)、回测管线、监控管线、日志归档 |
| 多阶段演化 | v2_upgrade → phase1 → phase2 → 当前 |
| 信号总线 | `mo_zhi_sharereports/signals/` + `mozhi_platform/signals/`（文件系统轮询） |
| 文件驱动通信 | trigger_*.json → .done / .failed 信号文件 |
| fail_closed | 写入验证（write→read→confirm）、安全失效即终止流水线 |
