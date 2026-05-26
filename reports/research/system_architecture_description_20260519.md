# 墨枢系统架构图 — 当前版本描述稿（2026-05-19）

## 总体说明

当前系统包含三大子图：

1. **任务流图（Task Flow）**：晨报管线（08:00）→ 午间交易（12:30）→ 晚报结算（19:00）→ 运营日报（19:50）
2. **数据流图（Data Flow）**：从外部数据源到最终报告和交易的全链路
3. **Layer Q 治理层**（新增）：Q1~Q9 质量关卡横向覆盖

---

## 子图一：任务流图（Task Flow）

### 时间线概览

```
08:00 ──→ 晨报管线（7步）──→ pipeline_complete 信号
                                    │
12:30 ──→ 午间交易调度 ──────────────┘
                                    ↓
                              仿真交易执行
                              (trend/reversal/grid)
                                    │
19:00 ──→ 晚报结算 ──────────────────┘
                                    │
19:50 ──→ 运营日报
```

### 晨报管线（Morning Pipeline）— 08:00 触发

**调度器（Scheduler）：** `openclaw cron` 08:00 触发，通过 trigger 文件驱动 7 步流水线。

**Step 0 — 玄知市场扫描**

- Agent：玄知（xuanzhi）
- 任务：市场数据采集、新闻/情绪扫描
- 输出：`datacollection_{tid}.json`（Status: READY）
- 异常：`failed_step0_{tid}.json`

**Step 0.5 — 墨涵知识注册**

- Agent：墨涵（mohan）
- 任务：注册扫描结果文档、检查知识接入点
- 输出：知识注册确认

**Step 1 — 墨衡深度分析**

- Agent：墨衡（moheng）
- 触发：`trigger_step1_{tid}.json`
- 任务：数据清洗与整合、结构化分析、signal_mapping 推导
- 输出：`structured_analysis_{tid}.json`
- 异常：`failed_step1_{tid}.json`

**Step 2 — 墨萱报告初稿**

- Agent：墨萱（moxuan）
- 触发：`trigger_step2_{tid}.json`
- 任务：读取结构化数据，生成自然语言初稿
- 输出：`reportdraft_{tid}.md`（DRAFT_READY）

**Step 3 — 墨衡质量审查 + Kill Switch**

- Agent：墨衡（moheng）
- 触发：`trigger_step3_{tid}.json`
- 任务：事实核查、逻辑审查、风险披露评估
- 判定：PASS → 继续 | WARN → 继续（带备注）| FAIL → Kill Switch 终止流水线
- 输出：`review_feedback_{tid}.md`（含 verdict）

**Step 3.5 — 玄知战略复核**

- Agent：玄知（xuanzhi）
- 触发：`trigger_step3.5_{tid}.json`
- 任务：战略合理性评估、风险和机会复核
- 输出：`strategic_review_{tid}.md`

**Step 3.6 — 墨涵知识审查**

- Agent：墨涵（mohan）
- 触发：`trigger_step3.6_{tid}.json`
- 任务：审核 draft 知识条目，定 confidence 级别，激活/驳回
- 输出：知识审查报告

**Step 4 — 墨萱汇总定稿**

- Agent：墨萱（moxuan）
- 触发：`trigger_step4_{tid}.json`
- 任务：汇总审查和复核意见，生成终稿
- 输出：`final_report_{tid}.md`

**Step 5 — 墨涵飞书推送**

- Agent：墨涵（mohan）
- 触发：`trigger_step5_{tid}.json`
- 任务：格式化成飞书消息、推送群消息、归档文档
- 输出：飞书群消息 + 归档记录

### 午间交易执行（Midday Trading）— 12:30 触发

**调度器：** `trade_loop_scheduler_midday`（openclaw cron，刚刚从13天disable状态恢复）

```
检查链：
  1. trading_calendar ── 判定是否为交易日
       │ 非交易日 → exit（跳过）
       ▼ 交易日
  2. kill_switch ── 检查系统控制文件
       │ allow_dispatch=false → exit
       ▼ 允许
  3. 查找 pipeline_complete_{seq}.json 信号
       │ 未找到 → exit（无信号）
       ▼ 找到
  4. 检查 trade_trigger.should_execute
       │ false → exit
       ▼ true
  5. 检查剩余交易时间 > 30s
       │ 不足 → exit
       ▼ 充足
  6. PipelineConnector.process_signal_trade()
       ├── trend 账户（¥200K 仿真）
       ├── reversal 账户（¥200K 仿真）
       └── grid 账户（¥200K 仿真）
```

### 晚报结算（Evening Settlement）— 19:00 触发

1. 读取当日所有交易成交记录
2. 更新三个仿真账户的资金持仓
3. 计算当日损益（PnL）
4. 生成仓位快照
5. 输出结算报告

### 运营日报（Operations Daily）— 19:50 触发

1. 读取晚报结算数据
2. 汇总各账户绩效（PnL、胜率、持仓）
3. 统计系统运行状态（cron 执行、错误日志）
4. 生成运营日报并推送

### 已知缺口

`09:30` 早盘调度不存在 — 晨报信号生成到午间执行之间无定时调度，待实现。

---

## 子图二：数据流图（Data Flow）

### 层次架构

```
┌─────────────────────────────────────────────────┐
│  外部数据源                                       │
│  ├── 行情数据（东方财富 API / akshare）            │
│  ├── 新闻信息（公开信息）                          │
│  └── 社交情绪（未接入）                            │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│  Agent 层                                        │
│  ├── 玄知（Agent）：市场扫描 / 初稿复核             │
│  ├── 墨衡（Agent）：深度分析 / 质量审查             │
│  ├── 墨萱（Agent）：报告起草 / 定稿                 │
│  └── 墨涵（Agent）：知识审查 / 飞书发布             │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│  文件系统（Agent间通信媒介）                       │
│  ├── signals/triggers/trigger_step*.json         │
│  ├── signals/datacollection_{tid}.json            │
│  ├── signals/pipeline_complete_{seq}.json         │
│  ├── reports/{type}/{date}/structured_analysis_.json │
│  ├── reports/{type}/{date}/review_feedback_{tid}.md │
│  ├── reports/{type}/{date}/final_report_{tid}.md   │
│  └── signals/tasks/*.done / *.failed               │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│  交易执行层                                       │
│  ├── trade_loop_scheduler.py（午间调度器）         │
│  ├── pipeline_connector.py（信号→交易桥接）         │
│  ├── OrderEngine（订单管理）                       │
│  ├── AccountManager（账户管理）                    │
│  └── settle_daily.py（结算引擎）                   │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│  数据库层                                         │
│  ├── file_registry.db（文件生命周期注册）           │
│  ├── trade_engine.db（交易记录、持仓、账户）        │
│  ├── factor_repository.db（因子数据存储）           │
│  └── knowledge.db（暂无，规划中）                   │
└─────────────────────────────────────────────────┘
```

### 数据从原始行情到最终报告的完整路径

```
行情数据（akshare/东方财富）
    │
    ▼
玄知市场扫描 ──→ datacollection_{tid}.json
    │
    ▼
墨衡深度分析 ──→ structured_analysis_{tid}.json
    │               ├── signal_mapping
    │               │   ├── symbol（标的）
    │               │   ├── action（BUY/SELL/HOLD）
    │               │   ├── confidence（高/中/低）
    │               │   ├── position_ratio（仓位比例）
    │               │   └── reason（核心逻辑）
    │               ├── risk_assessment
    │               └── data_validation
    │
    ▼
墨萱初稿 ──→ reportdraft_{tid}.md
    │
    ▼
墨衡质量审查 ──→ review_feedback_{tid}.md ──→ verdict = FAIL → Kill Switch
    │                                           verdict = PASS/WARN → 继续
    ▼
玄知复核 ──→ strategic_review_{tid}.md
    │
    ▼
墨涵知识审查 ──→ 知识条目激活/驳回
    │
    ▼
墨萱定稿 ──→ final_report_{tid}.md
    │
    ▼
墨涵飞书推送 ──→ 飞书群消息 + 归档
    │
    ▼
pipeline_complete_{seq}.json（含 trade_trigger）
    │
    ▼
[12:30] 午间调度器 ──→ pipeline_connector ──→ 仿真交易执行
    │                                               │
    │                                         ┌─────┴─────┐
    │                                         │            │
    │                                    trend 账户    grid 账户
    │                                    (¥200K)     (¥200K)
    │                                         │            │
    │                                         └─────┬─────┘
    │                                               │
    │                                          trade_engine.db
    │                                               │
    ▼                                               ▼
[19:00] 晚报结算 ──→ PnL 损益 ──→ 持仓快照
    │
    ▼
[19:50] 运营日报 ──→ 汇总推送
```

---

## 子图三：Layer Q 治理层（新增）

Layer Q 是横向覆盖在以上所有流程之上的质量治理体系。

```
                    ╔══════════════════════════════════╗
                    ║         Layer Q 治理层           ║
                    ╠══════════════════════════════════╣
                    ║ Q1: 数据采集治理（Existence Validator）║
                    ║ Q2: 分析稳健性（Robustness Validator）  ║
                    ║ Q3: 市场状态验证（Regime Validator） ║
                    ║ Q4: 容量评估（Capacity Validator）   ║
                    ║ Q5: 时序验证（Temporal Validator）   ║
                    ║ Q6: 样本外验证（OOS Validator）      ║
                    ║ Q7: 评分聚合器（Rating Aggregator）   ║
                    ║ Q8: 故障归因（Failure Attribution）   ║
                    ║ Q9: 故障注册表（Failure Registry）     ║
                    ║   ├── Q9a: Q_FAILURES（G1-G3门禁）  ║
                    ║   └── Q9b: RESEARCH_FAILURES（研究）║
                    ╚══════════════════════════════════╝
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   晨报管线             午间交易             晚报结算
   (Q1-Q7检查)        (Q8-Q9检查)         (Q9结算检查)
```

### Layer Q 集成关卡（G1~G3）

```
G1（数据采集后）──> ExistenceValidator → 数据样本是否足够？
    │ PASS → 继续
    │ FAIL → 写入 Q9a，驳回
    ▼
G2（分析完成后）──> RegimeValidator + RobustnessValidator → 市场状态和参数稳健性？
    │ PASS → 继续
    │ FAIL → 写入 Q9a + Q9b，驳回
    ▼
G3（报告发布前）──> 三方会签（墨萱技术 + 墨涵知识 + Owner 业务）
    │ 全部签过 → 发布
    │ 任意驳回 → 打回修改
```

---

## 格式说明（用于 ChatGPT 美化参考）

- 任务流图：用蓝色框表示 Agent 任务，黄色框表示文件/输出，红色虚线表示异常路径，绿色箭头表示调度触发
- 数据流图：用层叠框表示层次结构，实线箭头表示数据写/读，虚线箭头表示轮询/触发
- Layer Q：用双线框表示横向治理层，箭头指向各流程环节
- 底部保留"已知缺口"标注框（09:30早盘调度、回测系统待建、knowledge.db待建）
