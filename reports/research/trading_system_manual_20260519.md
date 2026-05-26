# 交易系统说明书（2026-05-19）

> **author**: moheng (墨衡)
> **created_time**: 2026-05-19T21:39:00+08:00
> **version**: v2.0 (墨枢系统) · 修订版（补充第八章回测能力清单）

---

## 一、系统全景总览

**一句话定位**：基于多Agent协作的自动化晨报/午间交易信号生成与仿真执行平台，覆盖从原始行情采集到交易指令落地的全链路。

### 组件清单

| 组件 | 角色 | 说明 |
|:----:|:----:|:------|
| 玄知 (xuanzhi) | 市场数据采集 + 初稿复核 | GPT-4o 实例，负责市场扫描和终端质检 |
| 墨衡 (moheng) | 深度分析 + 质量审查 | DeepSeek R1 实例，结构化分析与报告审计 |
| 墨萱 (moxuan) | 报告撰写 | 负责晨报初稿与定稿生成 |
| 墨涵 (mohan) | 知识审查 + 飞书发布 | 终端知识合规检查，推送报告到飞书群 |
| 墨辰 (mochen) | 调度器 (dispatcher) | 流水线编排、状态机驱动、Kill Switch |
| pipeline_connector | 交易执行桥接 | 消费 pipeline_complete 信号，对接仿真账户 |
| trading_calendar | 交易日历 | 判定交易日/非交易日，控制midday启动 |
| openclaw cron | 定时调度 | 系统级定时任务管理器 |

### 当前架构版本

- **墨枢系统 v7.2** — 多Agent投资工作流，文件驱动轮询通信
- **Layer Q治理体系 v1.0** — Q1~Q9质量关卡，0a~4c全线交付
- **仿真账户**：3个独立技术账户（trend/reversal/grid），各¥200K
- **midday cron**：2026-05-19刚刚从13天disable状态恢复

---

## 二、启动时间和触发链

### 定时任务表

| 时间 | 任务名称 | 触发器 | 前置依赖 | 描述 |
|:----:|:--------:|:------:|:--------:|:-----|
| **08:00 CST** | 晨报管线 (morning_report) | openclaw cron | 玄知市场扫描完成（数据就绪） | 7步Agent协作生成当日晨报并推送飞书 |
| **09:30 CST** | ⚠️ 早盘调度 | — | — | **已知缺口**，尚未实现 |
| **12:30 CST** | 午间交易 (midday_trade) | openclaw cron | trading_calendar判定为交易日 + kill_switch通过 | 消费晨报信号，执行仿真交易 |
| **19:00 CST** | 晚报结算 (evening_settlement) | openclaw cron | 收盘数据就绪 | 结算、绩效统计、仓位快照 |
| **19:50 CST** | 运营日报 (ops_daily) | openclaw cron | 晚报完成 | 生成运营日报 |

### 触发链图示

```
08:00 ──┬──> 玄知市场扫描 ──> 墨衡分析 ──> 墨萱初稿 ──> 墨衡审查 ──> 玄知复核 ──> 墨涵知识审查 ──> 墨萱定稿 ──> 墨涵推送飞书
        │                                                                                                       │
        └── (7步管线，文件驱动轮询)                                                                              │
                                                                                                                │
12:30 ──> trading_calendar ──> kill_switch ──> pipeline_complete信号 ──> pipeline_connector ──> 仿真交易执行     │
                                                                                                   ↑            │
                                                                                                   └── 消费晨报 ──┘
                                                                                                      signal_mapping
                                                                                                      仓位建议
                                                                                                      风险等级
```

### 依赖关系矩阵

| 依赖 | 类型 | 说明 |
|:----:|:----:|:-----|
| 晨报管线完成 → midday启动 | 软依赖 | midday只需要pipeline_complete信号，不严格要求晨报发布完成 |
| trading_calendar → kill_switch | 硬依赖 | 非交易日不执行，节假日跳过 |
| kill_switch → pipeline_connector | 硬依赖 | kill_switch判定为FAIL时终止流水线 |
| market_data → 玄知扫描 | 硬依赖 | 无行情数据无法启动晨报 |
| 晚报 → 运营日报 | 硬依赖 | 运营日报依赖晚报的结算数据 |

> **注意**：midday系统昨日（2026-05-18）刚刚从13天disable状态恢复。此前在2026-05-06被300s超时强杀后openclaw自动禁用，修复后重新启用。

---

## 三、核心功能

### 3.1 晨报管线 (Morning Report Pipeline)

**7步流水线**，从行情到最终推送：

```
Step 1: 玄知 (xuanzhi)  — 市场扫描
  ├─ 读取原始行情数据
  ├─ 执行技术指标计算
  ├─ 识别当日关键信号（突破/反转/量异常）
  └─ 输出: datacollection_{task_id}.json

Step 2: 墨衡 (moheng) — 深度结构化分析
  ├─ 数据验证：玄知判断与资金流自洽性
  ├─ 深度逻辑推演：宏观驱动、资金可持续性、催化剂
  ├─ 风险量化：低/中/高三档
  ├─ 操作建议框架：进取/均衡/保守三档
  ├─ signal_mapping 推导：symbol/action/confidence/position_ratio/reason
  └─ 输出: structured_analysis_{task_id}.json

Step 3: 墨萱 (moxuan) — 报告初稿
  ├─ 基于结构化分析生成自然语言初稿
  └─ 输出: report_draft_{task_id}.md

Step 4: 墨衡 (moheng) — 质量审查 + Kill Switch
  ├─ 事实准确性核查
  ├─ 逻辑完整性审查
  ├─ 风险披露充分性评估
  ├─ 操作建议合规性检查
  ├─ verdict: PASS / WARN / FAIL
  └─ 输出: review_feedback_{task_id}.md

Step 5: 玄知 (xuanzhi) — 复核修正
  ├─ 根据审查意见修改初稿
  └─ 输出: report_revised_{task_id}.md

Step 6: 墨涵 (mohan) — 知识审查
  ├─ 终端合规性检查
  └─ 输出: report_approved_{task_id}.md

Step 7: 墨萱 (moxuan) — 定稿 + 墨涵推送
  ├─ 生成最终定稿
  ├─ 墨涵发送到飞书群
  └─ 输出: report_final_{task_id}.md
```

### 3.2 午间交易执行 (Midday Trade Execution)

```
1. trading_calendar判定今日是否为交易日
2. kill_switch检查晨报 verdict → FAIL则终止
3. pipeline_complete 信号就绪
4. pipeline_connector 读取 pipeline_complete 信号文件
5. 解析 signal_mapping 字段（action/confidence/position_ratio）
6. 分别对三个仿真账户（trend/reversal/grid）执行交易
7. 输出: 成交记录 → 资金持仓数据库
```

### 3.3 晚报结算 (Evening Settlement)

```
1. 读取当日所有交易的成交记录
2. 更新三个仿真账户的资金持仓
3. 计算当日损益（PnL）
4. 生成仓位快照
5. 输出: daily_settlement_{date}.json
```

### 3.4 运营日报 (Operations Daily Report)

```
1. 读取晚报结算数据
2. 汇总当日各账户绩效
3. 统计系统运行状态（cron执行情况、错误日志）
4. 生成运营日报 → 推送
```

---

## 四、早报关系 — 信号传递链

### 从晨报到交易信号的完整路径

```
晨报管线
  │
  ├── structured_analysis.json
  │     ├── signal_mapping.symbol       ← 标的代码（如 601857）
  │     ├── signal_mapping.action       ← BUY | SELL | HOLD
  │     ├── signal_mapping.confidence   ← 高 | 中 | 低
  │     ├── signal_mapping.suggested_price    ← 建议价格
  │     ├── signal_mapping.position_ratio     ← 仓位比例 [0,1]
  │     └── signal_mapping.reason       ← 核心逻辑
  │
  ├── risk_assessment.level             ← 低/中/高
  ├── operation_framework               ← 三档策略参考
  └── data_validation.passed            ← 数据自洽性标志
        │
        ▼
  report_draft_{task_id}.md            ← 人工可读报告
        │
        ▼
  review_feedback_{task_id}.md         ← 质量审查 verdict
        │
        ▼
  pipeline_complete 信号               ← dispatcher 触发 midday 消费
        │
        ▼
  pipeline_connector 执行交易
```

### signal_mapping 推导逻辑

| 字段 | 推导来源 |
|:----:|:---------|
| **symbol** | datacollection 中标的字段；默认 A50 主要标的 |
| **action** | data_validation.passed + operation_framework 三档 → BUY/SELL/HOLD |
| **confidence** | data_validation + risk_assessment → 高/中/低 |
| **suggested_price** | operation_framework 价格点位 / 技术分析支撑/阻力 |
| **position_ratio** | 进取[0.5-0.8] / 均衡[0.2-0.5] / 保守[0.0-0.2] |
| **reason** | 格式："基于 {data_validation结论} + {core_logic要点}" |

### 仓位决定规则

```
data_validation.passed = true  且 风险低  → 进取仓位 [0.5, 0.8]
data_validation 轻度冲突         或 风险中  → 均衡仓位 [0.2, 0.5]
data_validation 严重冲突        或 风险高  → 保守仓位 [0.0, 0.2] 或 HOLD
```

### midday cron 消费逻辑

1. 检查 `pipeline_complete_{seq}.json` 是否存在
2. 读取 `signal_mapping` 字段
3. 对每个仿真账户（trend/reversal/grid）分别评估执行
4. 不同账户可使用不同的策略权重（趋势跟踪vs反转vs网格）
5. 执行后写入成交记录

---

## 五、数据清单

### 5.1 目录结构

```
C:\Users\17699\
├── mo_zhi_sharereports\                  ← 主数据目录
│   ├── 试验信息库\
│   │   ├── signals\                      ← 信号文件
│   │   │   ├── triggers\                 ← 触发文件 (*.json)
│   │   │   ├── dispatch\                 ← 调度信号 (meeting_trigger_*.json)
│   │   │   ├── consensus\                ← 共识/心跳
│   │   │   │   └── heartbeat\            ← Agent心跳文件
│   │   │   ├── datacollection_*.json     ← 玄知数据采集结果
│   │   │   ├── reportdraft_*.md          ← 晨报初稿
│   │   │   └── pipeline_complete_*.json  ← 流水线完成信号（midday消费）
│   │   └── _retry_*.json                 ← 重试信号
│   │
│   ├── reports\                          ← 分析报告输出
│   │   ├── morning\                      ← 晨报
│   │   │   └── {YYYYMMDD}\
│   │   │       ├── structured_analysis_{task_id}.json
│   │   │       ├── review_feedback_{task_id}.md
│   │   │       └── report_final_{task_id}.md
│   │   ├── midday\                       ← 午间报告
│   │   └── evening\                      ← 晚报
│   │
│   ├── agents\                           ← Agent工作目录
│   │   └── moheng\                       ← 墨衡工作区
│   │       └── meeting_response\         ← 会议响应
│   │
│   ├── logs\                             ← 系统日志
│   │   └── pipeline\                     ← 流水线日志
│   │
│   └── pipeline\                         ← 流水线状态
│       └── tasks\                        ← 任务状态文件 (*.done / *.failed)
│
├── mozhi_platform\                       ← 源代码和分析平台
│   ├── src\                              ← 源代码
│   │   ├── utils\                        ← 工具函数
│   │   ├── automation_v2\                ← 自动化v2模块（心跳/调度）
│   │   └── ...
│   ├── reports\                          ← 生成报告
│   │   └── research\                     ← 研究文档
│   ├── docs\                             ← 文档
│   │   └── 05_protocols\                 ← 协议文档
│   └── registry\                         ← 文件注册数据库
│       └── file_registry.db              ← 文件生命周期数据库
│
└── .openclaw\                            ← openclaw配置
    └── cron\                             ← cron任务定义与状态
```

### 5.2 关键数据文件清单

| 文件模式 | 用途 | 生产者 | 消费者 | 格式 |
|:---------|:-----|:------:|:------:|:----:|
| `trigger_step2_{task_id}.json` | 触发墨衡深度分析 | dispatcher | 墨衡 | JSON |
| `trigger_step4_{task_id}.json` | 触发墨衡质量审查 | dispatcher | 墨衡 | JSON |
| `datacollection_{task_id}.json` | 玄知市场扫描数据 | 玄知 | 墨衡 | JSON |
| `structured_analysis_{task_id}.json` | 结构化分析结果 | 墨衡 | 墨萱 | JSON |
| `reportdraft_{task_id}.md` | 报告初稿 | 墨萱 | 墨衡 | Markdown |
| `review_feedback_{task_id}.md` | 质量审查意见 | 墨衡 | 玄知/墨萱 | Markdown |
| `pipeline_complete_{seq}.json` | 流水线完成信号 | dispatcher | pipeline_connector | JSON |
| `{task_id}_moheng.done` | 墨衡任务完成信号 | 墨衡 | dispatcher | 空文件 |
| `{task_id}_moheng.failed` | 墨衡任务失败信号 | 墨衡 | dispatcher | 空文件 |
| `moheng_hb_{seq}.json` | 墨衡心跳 | 墨衡 | 所有Agent | JSON |
| `file_registry.db` | 文件生命周期索引 | 系统 | 文件查询 | SQLite |
| `meeting_trigger_{seq}.json` | 会议响应触发 | 玄知 | 墨衡 | JSON |
| `_retry_{seq}_moheng.json` | 墨衡重试信号 | 玄知 | 墨衡 | JSON |

### 5.3 数据库

| 名称 | 位置 | 用途 |
|:----|:-----|:-----|
| `file_registry.db` | `mozhi_platform\registry\` | 文件生命周期注册与查询 |

> 查询工具：`python -m src.utils.file_lifecycle search --source archive "关键词"`

---

## 六、系统流程图（ASCII Art 时间线）

```
时间线    晨报管线                          午间交易                    晚报/运营
─────    ────────                          ────────                    ────────

08:00 ──┬──> (Step 1) 玄知市场扫描 ──── 生成 datacollection.json
         │
08:10 ──┤──> (Step 2) 墨衡深度分析 ──── 生成 structured_analysis.json
         │
08:25 ──┤──> (Step 3) 墨萱初稿 ──────── 生成 reportdraft.md
         │
08:35 ──┤──> (Step 4) 墨衡质量审查 ──── 生成 review_feedback.md
         │                                    verdict = PASS/WARN/FAIL
         │                                    (FAIL → Kill Switch 终止)
08:45 ──┤──> (Step 5) 玄知复核修正 ──── 生成 report_revised.md
         │
08:50 ──┤──> (Step 6) 墨涵知识审查 ──── 生成 report_approved.md
         │
08:55 ──┤──> (Step 7) 墨萱定稿 + 墨涵推送飞书
         │                                    ╔═══════════════════════╗
         │                                    ║ pipeline_complete信号 ║
         │                                    ╚═══════════════════════╝
         │                                              │
         │                                              ▼
12:30 ──┼─────────────────────────> trading_calendar ◄──┤
         │                                   │ 是交易日? │
         │                                   ▼          │
         │                              kill_switch     │
         │                                   │ verdict  │
         │                                   ▼          │
         │                              pipeline_connector ──> 仿真交易执行
         │                                   │
         │                                   ├── trend 账户 (¥200K)
         │                                   ├── reversal 账户 (¥200K)
         │                                   └── grid 账户 (¥200K)
         │
19:00 ──┼────────────────────────────────────────────────> 晚报结算
         │                                   读取成交记录
         │                                   更新资金持仓
         │                                   计算损益 PnL
         │
19:50 ──┼────────────────────────────────────────────────> 运营日报
                                                    汇总各账户绩效
                                                    系统运行状态统计

═══════════════════════════════════════════════════════════════════════
缺 口：09:30 早盘调度尚未实现 — 晨报信号生成后 → 早盘执行之间无定时调度
═══════════════════════════════════════════════════════════════════════

系统通信机制：
  ┌──────────────────────────────────────────────┐
  │  Agent 间通信 = 文件驱动轮询                  │
  │  • 生产者写入文件 → 设置 READY 状态           │
  │  • 消费者轮询目录 → 检测新文件                 │
  │  • 写入后必须 read 验证                       │
  │  • 完成信号 = .done / .failed                 │
  └──────────────────────────────────────────────┘

Agent交互模式：
  ┌──────────┐      文件      ┌──────────┐
  │ dispatcher│ ──────────> │  moheng  │  (spawn方式执行)
  │ (mochen)  │ <────────── │          │  (Announce + .done回复)
  └──────────┘    .done     └──────────┘
```

---

## 七、数据流图

### 从原始行情到最终报告的完整数据路径

```
                    ┌───────────────────┐
                    │  原始行情数据源     │
                    │  (交易所 API/推流) │
                    └────────┬──────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │  玄知 (xuanzhi) 市场扫描     │
              │  • 技术指标计算              │
              │  • 信号识别（突破/反转/量） │
              │  • 基础判断                  │
              └────────────┬────────────────┘
                           │
                    datacollection_{task_id}.json
                           │
                           ▼
              ┌─────────────────────────────┐
              │  墨衡 (moheng) 深度分析      │
              │  • 数据验证与矛盾检测        │
              │  • 宏观逻辑推演              │
              │  • 风险量化                  │
              │  • 操作建议框架              │
              │  • signal_mapping 推导       │
              └────────────┬────────────────┘
                           │
                    structured_analysis_{task_id}.json
                           │
                           ▼
              ┌─────────────────────────────┐
              │  墨萱 (moxuan) 报告初稿      │
              │  • 自然语言生成              │
              │  • 结构化数据 → 可读报告     │
              └────────────┬────────────────┘
                           │
                    reportdraft_{task_id}.md
                           │
                           ▼
              ┌─────────────────────────────┐
              │  墨衡 (moheng) 质量审查      │
              │  • 事实核查                  │
              │  • 逻辑完整性检查            │
              │  • 风险披露评估              │
              │  • 合规性审查                │
              │  • verdict: PASS/WARN/FAIL   │
              └────────────┬────────────────┘
                           │
                    review_feedback_{task_id}.md
                           │
                    ┌──────┴──────┐
                    │             │
              verdict=PASS    verdict=FAIL
                    │             │
                    ▼             ▼
            ┌──────────┐  ┌──────────────┐
            │ 继续管线  │  │ Kill Switch  │
            │(Step 5-7) │  │ 终止流水线   │
            └────┬─────┘  └──────────────┘
                 │
                 ▼
          ┌──────────────┐
          │ 玄知复核修正   │
          │ 墨涵知识审查   │
          │ 墨萱定稿 +    │
          │ 墨涵飞书推送   │
          └──────┬───────┘
                 │
                 ▼
          ╔════════════════╗
          ║  pipeline_complete ║
          ║  信号文件        ║
          ╚════════════════╝
                 │
                 ▼
          ┌──────────────────────┐
          │  pipeline_connector  │   ← midday cron (12:30)
          │  解析 signal_mapping │
          │  执行仿真交易        │
          └──────────┬───────────┘
                     │
              ┌──────┴──────┐
              │ 成交记录     │
              │ 资金持仓更新  │
              │ PnL 计算     │
              └──────┬──────┘
                     │
                     ▼
          ┌──────────────────────┐
          │  晚报结算 / 运营日报  │
          │  (Settlement)        │
          └──────────────────────┘

═══════════════════════════════════════════════════════════════
层  Layer Q 治理关卡 (Q1~Q9)
次  0a: 数据采集层 ──── 玄知市场扫描 (Q1)
结  0b: 分析层 ──────── 墨衡深度分析 (Q2)
构  0c: 撰写层 ──────── 墨萱初稿/定稿 (Q3)
    1a: 审查层 ──────── 墨衡质量审查 (Q4)
    1b: 复核层 ──────── 玄知复核 (Q5)
    2a: 法规层 ──────── 墨涵知识审查 (Q6)
    2b: 发布层 ──────── 墨涵飞书推送 (Q7)
    3a: 执行层 ──────── pipeline_connector (Q8)
    4c: 结算层 ──────── 晚报/运营日报 (Q9)
═══════════════════════════════════════════════════════════════
```

---

## 八、回测能力清单

### 8.1 现有回测能力总览

当前系统中已有的回测能力均为**研究任务（research task）模式**——手动或按需触发的非自动化流水线。回测结果以 Markdown 报告形式输出到 `reports/research/` 目录。

| 回测领域 | 执行方式 | 输出位置 |
|:--------:|:--------:|:---------|
| 网格策略回测 | 手动触发 research task | `reports/research/` (Phase 4 P系列) |
| 因子 IC 验证 | 手动触发 research task | `reports/research/` (P7) |
| 参数扫描分析 | 手动触发 research task | `reports/research/` (param_decay) |
| Layer Q 治理回测 | 手动触发 research task | `reports/research/` (P1~P8) |

### 8.2 回测方法论

#### 8.2.1 网格策略回测（Phase 4 P系列报告）

基于历史数据回放，评估网格参数（网格间距、层数、步长等）在不同市场环境下的表现。通过对比已平衡/未平衡两种状态，判断网格策略的收益风险特征。

#### 8.2.2 因子 IC 验证（P7）

日频因子值与未来收益之间的相关性分析，覆盖 **1540 天**的完整周期。采用 Pearson/Spearman 秩相关系数评估因子预测能力，辅助判断因子是否具备统计显著性。

#### 8.2.3 参数扫描分析（param_decay）

对策略参数进行系统性的**参数敏感性扫描**，评估不同参数组合下的收益稳健性和衰减特征。用于识别参数过拟合风险及最优参数区间。

#### 8.2.4 Layer Q 治理回测验证

在历史数据上验证 Q1~Q9 质量关卡的有效性，对各关卡（P1~P8）给出评级结果：

| 关卡 | 评级 | 说明 |
|:----:|:----:|:------|
| **P7** | **A级** | 6年日频数据，统计显著性强 |
| **P1** | **F级** | 84天仅2笔交易 → 被G1拦截 |
| **P2** | **F级** | 84天仅2笔交易 → 被G1拦截 |
| **P5** | **F级** | 84天仅2笔交易 → 被G1拦截 |

> 注：G1 关卡为入场频率最低门槛，交易笔数不足时自动拦截。

### 8.3 回测工具

| 工具 | 路径 | 用途 |
|:----|:----|:------|
| `research_workflow.py` | 研究流程脚手架 | 回测任务的基础运行框架 |
| `q9b_research_failures.py` | 回测失败记录 | 记录并分析回测过程中的失败案例 |
| `phase4c_interface.py` | Layer Q集成接口 | 含 `compute_q_rating` 函数，供回测调用 |
| `existence_validator.py` | 样本存在性验证 | Phase 0a MVP，验证样本数据是否存在 |
| P系列报告分析文件 | 各Phase报告目录 | Phase 4 各P层级的结果分析文件 |

### 8.4 已知缺口

| 缺口 | 严重度 | 说明 |
|:----|:------:|:------|
| 无统一回测引擎（backtest runner） | 🔴 高 | 各回测任务独立运行，缺乏统一框架和标准化输出 |
| 无自动参数扫描平台 | 🟡 中 | 参数扫描需手动配置，无Web UI或API接口 |
| 无 OOS（Out-of-Sample）验证流水线 | 🟡 中 | Q6已实现样本外验证逻辑，但未与回测流水线对接 |
| 回测结果未进入知识库持久化 | 🟢 低 | 回测报告以文件形式存在，未注册到文件生命周期数据库，无法跨任务检索复用 |

---

## 附录 A：文件使用规范

### 通信协议

1. **触发文件**：`trigger_step{2/4}_{task_id}.json`，必须包含 `agent` 字段
2. **完成信号**：`{task_id}_{agent}.done` 空文件，表示任务完成
3. **失败信号**：`{task_id}_{agent}.failed` 空文件，表示任务失败
4. **互斥规则**：`.done` 与 `.failed` 不可共存
5. **写入验证**：写入后立即 `read` 验证

### 状态文件格式

```
C:\Users\17699\.openclaw\cron\cron_add-trade-calendar.yaml    ← midday cron 定义
C:\Users\17699\.openclaw\cron\cron_morning-report.yaml        ← 晨报 cron 定义
```

## 附录 B：已知问题和改进项

| 问题 | 严重度 | 状态 |
|:----|:------:|:----:|
| 09:30 早盘调度不存在 | 🔴 高 | 待实现 |
| midday cron 刚恢复（13天disable） | 🟡 中 | 已修复 |
| factor_repository.py编码损坏 | 🟢 低 | 已修复（45处私用区字符） |
| 仿真账户独立资金，无总资金概念 | 🟡 中 | 需确认设计意图 |
| 无熔断机制（连续亏损自动停盘） | 🟡 中 | 待设计 |
| 缺少交易日持仓状态快照备份 | 🟢 低 | 待补充 |

---

## 📌 待建里程碑

本文档为 **"交易系统说明书"（v2.0 修订版）**，当前标注为 **"待建"** 状态。

**含义说明**：
- 文档中描述的**交易管线、晨报管线、晚报结算、运营日报**为**已上线运行**（状态：✅ 在线）
- **第八章：回测能力清单**中列出的回测能力为**已实现但未集成**（状态：🔄 可用，手动触发）
- **回测工程的统一化（统一引擎、参数平台、OOS流水线）** 为**待建**状态（状态：⏳ 规划中）

**预期里程碑**：

| 里程碑 | 预计 | 状态 |
|:------|:----:|:----:|
| 统一回测引擎 v1 | TBD | ⏳ 规划 |
| 自动参数扫描平台 | TBD | ⏳ 规划 |
| OOS 验证流水线对接 (Q6→Q8) | TBD | ⏳ 规划 |
| 回测结果知识库持久化 | TBD | ⏳ 规划 |
| 回测能力全自动集成至主线 | TBD | ⏳ 远期 |

> 待建里程碑更新后将同步修改本文档标题和版次标识。
