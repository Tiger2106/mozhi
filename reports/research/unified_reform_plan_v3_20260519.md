<!--
author: 墨衡 (moheng) — 综合专家第三轮意见
created_time: 2026-05-19 15:09:00+08:00
task_id: unified_reform_plan_v3
version: v3.0
status: EXPERT_THIRD_ROUND_ABSORBED
based_on: unified_reform_plan_20260519.md (v2.0)
-->

# 网格研究流程改造：统一方案 v3（专家第三轮吸收版）

**生成时间**: 2026-05-19 15:09 +08:00
**版本**: v3.0
**基础**: v2.0（墨衡×墨涵共识版） + 专家第三轮意见

---

## 一、专家第三轮吸收清单

### 1.1 逐条采纳判定

#### 建议1: Q层作为"Transverse Governance Layer"（横向治理层）定位确认

| 维度 | 判定 |
|:-----|:----:|
| **采纳** | ✅ **完全采纳** |
| **理由** | v2.0中我们已经将Q层定义为"横向跨层审计层"，专家从更专业的架构视角将其定性为**Transverse Governance Layer**（横向治理层），并指出这是"非常专业的架构思想"。专家提出的"研究者不能自己给自己盖章"原则是对我们ADR-001决策的最佳理论支撑。 |
| **操作** | 将v2.0中"横向跨层审计层"表述统一为"**Transverse Governance Layer（横向治理层）**"。所有后续文档（架构图、技术文档、ADR）使用此标准术语。 |
| **变更影响** | 术语统一，架构决策不变，无需修改代码 |

#### 建议2: "双账本系统"概念

| 维度 | 判定 |
|:-----|:----:|
| **采纳** | ✅ **完全采纳并升格为架构原则** |
| **理由** | 专家精准提炼了我们的架构核心——P/B/S/E/R/I是"研究结果账本"（回答"赚了吗？"），Q是"可信度审计账本"（回答"为什么可信？"）。这为P层和Q层建立了清晰的职责边界和输出规范。 |
| **操作** | 在v3.0中新增§4"双账本操作规范"，明确定义两个账本的输出格式、审计关系和使用规则。 |
| **变更影响** | 新增结构性文档章节，调整Q层输出规范 |

#### 建议3: ExistenceValidator具体阈值

| 维度 | 判定 |
|:-----|:----:|
| **采纳** | ✅ **完全采纳，纳入MVP设计** |
| **理由** | v2.0中ExistenceValidator的阈值较粗略（夏普>0.3+交易笔数>20），专家的6项阈值更完整、专业：最小交易数≥30、多Regime覆盖≥2、多年度覆盖≥2年、单交易收益占比<40%、信号密度下限、样本分布检查。 |
| **操作** | 在v3.0的ExistenceValidator MVP设计（§5）中采用专家的6项阈值体系，输出格式采用专家建议的`ExistenceResult{exists, confidence, fail_reasons}`。 |
| **变更影响** | Q1模块设计需修改：扩展检查项从2项到6项，调整输出数据结构。**工时增加：+0.3天** |

#### 建议4: ADR-003确认

| 维度 | 判定 |
|:-----|:----:|
| **采纳** | ✅ **完全采纳** |
| **理由** | 专家完全同意我们"不立即重构MarketStateFilter，标记为架构债务并通过策略路由器远期解决"的决策，并评价为"成熟架构思维"。专家进一步指出TREND_UP开网格"本身存在理论矛盾"，进一步强化了ADR-003的必要性。 |
| **操作** | 维持v2.0的ADR-003决策不变，在架构债务清单中补充专家指出的"TREND_UP开网格存在理论矛盾"作为注释。已在v2.0的Phase 3计划中包含策略路由器。 |
| **变更影响** | 无代码变更，仅补充架构债务注释 |

#### 建议5: Failure Registry（失败数据库）— 新增（Owner决策：双层结构）

| 维度 | 判定 |
|:-----|:----:|
| **采纳** | ✅ **采纳，Owner决策为双层结构——Q9a Q_FAILURES（正式审计）+ Q9b RESEARCH_FAILURES（全量研究）** |
| **理由** | 专家论点"机构最值钱的往往不是成功策略，而是失败模式数据库"极具洞察力。当前系统记录成功策略（参数排行榜、KnowledgeBridge），但从不系统记录失败原因。失败模式会重复出现，系统地记录和分析失败是提升研究可信度的关键基础。 |
| **操作** | ① **Q9a Q_FAILURES**：记录**正式审计失败**，用于可信度治理。Phase 0b 基础设施，Day 1 开始建 ② **Q9b RESEARCH_FAILURES**：记录**全量研究失败**，用于长期知识积累 + Meta Research。延至 Phase 1~2 ③ 两层互相引用（strategy_id + failure_id）、职责分离；G1/G2/G3 门控失败自动写入 Q9a；人工复盘/元研究失败写入 Q9b ④ 数据隔离：Q9b 表结构与 Q9a 独立 |
| **变更影响** | **新增双模块：Q9a（Phase 0b，含在现有 1.6天 estimate 中）+ Q9b（Phase 1~2，新增 ~0.5天）。数据隔离：Q9b 表结构独立，通过 strategy_id + failure_id 交叉引用** |

#### 建议6: 战略方向确认

| 维度 | 判定 |
|:-----|:----:|
| **采纳** | ✅ **完全采纳，升级为系统使命** |
| **理由** | "把研究可信度作为第一目标"与v2.0中双方确认的"核心方向：建设研究可信度基础设施"完全一致。专家将其提炼为战略级口号，应作为整个Layer Q系统的核心设计原则。 |
| **操作** | 在v3.0文档标题和工作原则中嵌入此表述。所有架构决策评估时以"是否提升研究可信度"为第一判断标准。 |
| **变更影响** | 原则性表述更新，不涉及代码变更 |

### 1.2 吸收总结

| 建议 | 采纳状态 | 变更级别 | 工时影响 |
|:----|:--------:|:--------:|:--------:|
| 1. Transverse Governance Layer术语 | ✅ 完全采纳 | 术语统一 | 0 |
| 2. 双账本系统概念 | ✅ 完全采纳并升格 | 新增§4 | +0.3天 |
| 3. ExistenceValidator具体阈值 | ✅ 完全采纳 | 修改Q1设计 | +0.3天 |
| 4. ADR-003确认 | ✅ 完全采纳 | 补充注释 | 0 |
| 5. Failure Registry | ✅ 采纳（Owner决策：双层结构） | 新增Q9a+Q9b | +0.5天（Q9a含在Phase 0b现有estimate中，Q9b新增~0.5天） |
| 6. 战略方向确认 | ✅ 完全采纳 | 原则性表述 | 0 |
| **合计** | **6/6采纳（建议5升级为Owner双层决策）** | **中等变更** | **+2.1天**（建议1~4:+0.6天 + Q9a含在Phase 0b + Q9b新增~0.5天 + v2.0基线含Phase 0b其余部分） |

> **核心原则**: 专家本轮所有6条建议，全部采纳。不影响v2.0已确认的架构决策，在现有框架上补充和完善。

---

## 二、更新后的路线图（纳入Failure Registry）

### 2.1 总览

```
Phase 0a (基础门禁)     Phase 0b (基础设施)     Phase 1 (验证结构化)    Phase 2 (深化+校准)
  Day 1                    Day 1~2                  Day 3~8                 Day 9~15  
  ┌───────────┐           ┌───────────┐           ┌───────────┐           ┌───────────┐
  │ Q1: Exist │           │Q9a: Q_FAIL│           │ Q3: Regime│           │ Q4: Capac │
  │Validator  │           │ URES      │           │ Q5: Tempor│           │ 阈值校准  │
  │ MVP + G1  │           │ DB+Gate   │           │ Q8: Fail  │           │ 跨报告    │
  │           │           │ 集成      │           │ G1/G2/G3  │           │ 集成+文档 │
  └───────────┘           └───────────┘           ├───────────┤           ├───────────┤
       │                       │                 │Q9b: RESEA │           │Q9b: RESEA │
       │                       │                 │RCH_FAILUR │           │RCH_FAILUR │
       │                       │                 │ ES开始建设 │           │ ES完成+Meta│
       ▼                       ▼                 └───────────┘           └───────────┘
  里程碑M0                 里程碑M0.5              里程碑M1                 里程碑M2
  "门禁就绪"              "Q_FAILURES就绪"       "验证门控闭环"          "完整Q层交付"
```

> **关键变化**: Phase 0拆分为Phase 0a（ExistenceValidator MVP）和Phase 0b（Q9a Q_FAILURES基础设施）。两者顺序推进，不并行。Day 1完成Phase 0a后即刻启动Phase 0b。Q9b RESEARCH_FAILURES延至Phase 1~2建设，保持数据隔离。

### 2.2 Phase 0a: ExistenceValidator MVP + G1门禁（Day 1）

#### 目标
Q1 ExistenceValidator MVP上线，作为研究入口门禁

#### 任务清单

| # | 任务 | 责任 | 工时 | 交付物 |
|:-:|:-----|:----:|:----:|:-------|
| 0a-1 | 实现Q1 ExistenceValidator（含6项检查+阈值+ExistenceResult输出） | 墨衡 | 0.8天 | `q1_existence_validator.py` |
| 0a-2 | G1 Gate集成到回测管线 | 墨衡 | 0.2天 | `pipeline/quality_gates.py` |
| 0a-3 | 验证601857网格通过ExistenceValidator | 墨衡 | 0.1天 | 首个通过案例 |

#### 里程碑 M0: "研究入口门禁就绪"
- **完成条件**:
  - ✅ Q1 ExistenceValidator实现6项检查、输出`ExistenceResult{exists, confidence, fail_reasons}`
  - ✅ G1 Gate集成到回测管线，不合格结果自动拦截+写入FAILED状态
  - ✅ 601857网格通过验证（作为第一个Pass案例）
- **验证**: 对历史3个已知"伪发现"回测结果运行ExistenceValidator，确保被正确拦截

### 2.3 Phase 0b: Q9a Q_FAILURES基础设施（Day 1~2）

#### 目标
建立Q_FAILURES（正式审计失败数据库），所有Q层门控的"不通过"结果自动记录，用于可信度治理

#### 任务清单

| # | 任务 | 责任 | 工时 | 交付物 |
|:-:|:-----|:----:|:----:|:-------|
| 0b-1 | 创建`q_failures/`目录结构和`q_failures`数据库表 | 墨萱 | 0.5天 | 目录+`q_failures` DBSchema |
| 0b-2 | 实现Q9a Q_FAILURES模块（写入+查询+统计） | 墨衡 | 0.5天 | `q9a_failure_registry.py` |
| 0b-3 | G1/G2/G3失败结果自动写入Q9a Q_FAILURES | 墨衡 | 0.3天 | Gate集成 |
| 0b-4 | Q9a Q_FAILURES查询工具 | 墨萱 | 0.3天 | `tools/q_failures_query.py` |

#### 里程碑 M0.5: "Q_FAILURES就绪"
- **完成条件**:
  - ✅ `research_failures/`目录存在，数据库表已建
  - ✅ Q9a+Q9b模块支持录入+查询+按failure_type/strategy_id/regime聚合统计
  - ✅ G1/G2/G3失败结果自动写入
  - ✅ 查询工具可正常使用

### 2.4 Phase 1: 验证结构化 + 门控闭环 + Q9b开始建设（Day 3~8）

（Q9a已在上阶段完成，本阶段开始建设Q9b RESEARCH_FAILURES）

#### 任务清单

| # | 任务 | 责任 | 工时 | 交付物 |
|:-:|:-----|:----:|:----:|:-------|
| 1.1 | 实现Q3 Regime Validator | 墨衡 | 1.0天 | `q3_regime_validator.py` |
| 1.2 | 实现Q5 Temporal Stability | 墨萱 | 0.5天 | `q5_temporal_validator.py` |
| 1.3 | 实现Q8 Failure Attribution Engine | 墨衡 | 0.5天 | `q8_failure_attribution.py` |
| 1.4 | G1+G2门控完善（含失败写入Q9a） | 墨衡 | 0.5天 | `pipeline/quality_gates.py` |
| 1.5 | 实现G3 Multi-Sign Gate流程 | 墨萱 | 1.0天 | `pipeline/review_signoff.py` |
| 1.6 | Q9b RESEARCH_FAILURES数据库表+目录结构（独立于Q9a） | 墨萱 | 0.3天 | `research_failures_ext/` |
| 1.7 | Q9b RESEARCH_FAILURES写入/查询模块 | 墨衡 | 0.2天 | `q9b_research_failures.py` |
| 1.8 | 全流程集成测试 | 墨衡+墨萱 | 1.5天 | 集成测试报告 |
| 1.9 | Q层产出文档（含Q9a+Q9b） | 墨衡 | 0.5天 | `docs/architecture/layer_q_spec.md` |

### 2.5 Phase 2: 容量稳定性 + 评分深化（Day 9~15）

| # | 任务 | 责任 | 工时 | 交付物 |
|:-:|:-----|:----:|:----:|:-------|
| 2.1 | 实现Q4 Capacity Validator | 墨萱 | 1.0天 | `q4_capacity_validator.py` |
| 2.2 | 评分阈值校准（基于432组历史+Q9a Q_FAILURES数据） | 墨衡 | 1.5天 | 校准报告+新阈值 |
| 2.3 | 跨报告比较工具 + Q9a+Q9b趋势分析 | 墨衡 | 1.5天 | `comparison_hub.py` |
| 2.4 | Q层成果集成文档 + Q9a+Q9b使用指南 | 墨涵 | 0.5天 | `docs/research/layer_q_usage.md` |
| 2.5 | Q9b RESEARCH_FAILURES Meta Research分析工具（Failure Trend + 复发检测） | 墨衡 | 0.3天 | `tools/research_failure_meta.py` |
| 2.6 | Q9b RESEARCH_FAILURES与Q9a Q_FAILURES交叉引用查询 | 墨萱 | 0.2天 | 交叉引用视图 |
| 2.7 | Phase 4c集成接口设计和实现 | 墨衡+墨萱 | 1.0天 | 集成接口 |
| 2.8 | 季度Kill Switch评审 | 团队 | — | 持续定期 |

### 2.6 里程碑总表

| 里程碑 | 阶段 | 完成条件 | 验证方法 |
|:------:|:----:|:---------|:---------|
| M0 | Phase 0a | ExistenceValidator MVP + G1门禁 | 3个已知"伪发现"被拦截 |
| M0.5 | Phase 0b | Q9a Q_FAILURES可自动记录+查询 | 模拟Gate失败场景→确认写入Q9a |
| M1 | Phase 1 | Q1~Q8+Q9a全模块+门控闭环+Q9b开始建设 | 2个策略端到端审计 |
| M2 | Phase 2 | 阈值校准+容量+集成+Q9b完成（含Meta Research分析） | 432组历史校准报告 |

---

## 三、Layer Q详细设计（v2）—— 增加Q9a+Q9b Failure Registry

### 3.1 整体架构（更新版）

```
Layer Q — Transverse Governance Layer（横向治理层）
═════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────┐
│                   Q层流水线                                    │
│                                                              │
│  回测结果     Q1         Q2         Q3                       │
│  ─────────→ Existence → Robustness → Regime                 │
│   (全部P系列) Test       Surface     Consistency             │
│       │         │           │           │                    │
│       │         ▼           ▼           ▼                    │
│       │    ┌─────────────────────────────────┐              │
│       │    │      中间评分（3维预聚合）        │              │
│       │    └─────────────────────────────────┘              │
│       │                                                      │
│       │         Q4         Q5         Q6                     │
│       │    ┌─── Capacity → Temporal → OOS                   │
│       │    │   Stability  Stability   Survival                │
│       │    └──────────────────────────────────────────┐     │
│       │                         │                       │     │
│       │                         ▼                       │     │
│       │    ┌────────────────────────────────────────┐   │     │
│       │    │      Q7: ConfidenceScoreAggregator      │   │     │
│       │    │  6维评分 → 复合R → A~F评级 + 瓶颈     │   │     │
│       │    └────────────────────────────────────────┘   │     │
│       │                         │                       │     │
│       │                         ▼                       │     │
│       │    ┌────────────────────────────────────────┐   │     │
│       │    │    Q8: Failure Attribution Engine        │   │     │
│       │    │  根因分析→归因比例→改进方向推荐         │   │     │
│       │    └────────────────────────────────────────┘   │     │
│       │                         │                       │     │
│       │                         ▼                       │     │
│       │    ┌────────────────────────────────────────┐   │     │
│       │    │    Q9a: Q_FAILURES ★NEW               │   │     │
│       │    │  + Q9b: RESEARCH_FAILURES             │   │     │
│       │    │  + Failure Query Engine               │   │     │
│       │    │  + Failure Trend Analysis             │   │     │
│       │    └────────────────────────────────────────┘   │     │
│       │                         │                       │     │
│       └─────────────────────────┼───────────────────────┘     │
│                                 ▼                             │
│                    ┌────────────────────────────┐             │
│                    │  产出:                     │             │
│                    │  ① Q层审计报告              │             │
│                    │  ② P报告末段标准化段         │             │
│                    │  ③ Q9a+Q9b失败记录         │             │
│                    └────────────────────────────┘             │
│                                                              │
│  管控机制:                                                    │
│  ┌────────┐  ┌────────┐  ┌───────────────┐  ┌──────────────┐│
│  │G1 Gate │→│G2 Gate │→│G3 Multi-Sign  │→│Q9a Q_FAILURES││
│  │Existence│  │Robust  │  │(墨涵+墨萱      │  │              ││
│  │Pass/Fail│  │Threshold│  │ +Owner)       │  │自动记录     ││
│  └────────┘  └────────┘  └───────────────┘  └──────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Q1~Q8 模块定义

（内容同v2.0 §3.2，保持不变）

### 3.3 Q9: Failure Registry（Q9a Q_FAILURES + Q9b RESEARCH_FAILURES 双层结构）

| 属性 | 定义 |
|:-----|:------|
| **核心问题** | 策略为什么失败？失败模式是否重复出现？哪些失败类型最常见？ |
| **定位** | 系统级基础设施，与KnowledgeBridge（知识桥）并列——KB记录"什么成功"，FR记录"什么失败" |
| **输入** | G1/G2/G3门控不通过结果 → Q9a；Q8归因分析 + 人工复盘 → Q9b |

**结构说明**：根据 Owner 决策，Q9 由两个子层构成：

- **Q9a (Q_FAILURES)**：正式审计失败登记层，Phase 0b 建设，Day 1 启动。
  - 职责：G1/G2/G3 门控不通过结果的自动记录，用于可信度治理
  - 输出：正式审计失败记录（写入 `q_failures` 数据库表）
  - 消费者：Gate 门控系统、合规审计
- **Q9b (RESEARCH_FAILURES)**：全量研究失败积累层，Phase 1~2 建设。
  - 职责：人工复盘失败 + 元研究失败记录，用于长期知识积累 + Meta Research
  - 输出：研究扩展失败记录（写入独立 `research_failures` 目录和表结构）
  - 消费者：知识积累、失败模式分析

两层通过 `strategy_id + failure_id` 交叉引用。以下规范将按 Q9a / Q9b 分别阐述。

#### Q9a-A: Q9a Q_FAILURES 记录规范

每条失败记录包含以下字段：

| 字段 | 类型 | 说明 | 来源 |
|:-----|:----|:-----|:----|
| `failure_id` | UUID | 唯一标识 | 系统自动生成 |
| `strategy_id` | str | 策略名称/ID | 策略定义 |
| `parameter_set` | dict | 参数集（扫描中失败的参数组合） | 回测引擎 |
| `failure_type` | enum | 失败类型（见下方枚举） | 系统判定 |
| `regime` | enum | 失效市场状态 | RegimeAnalyzer |
| `cause` | str | 根因描述（Q8输出的TopSuggestion + 人工补充） | Q8 + 人工 |
| `discovered_by` | str | 哪个Validator/哪个阶段发现 | Gate触发 |
| `confidence_drop` | float | 若为后验添加：Q7评分变化的幅度 | Q7 |
| `timestamp` | datetime | 记录时间 | 系统自动 |
| `report_id` | str | 关联的审计报告ID | Q层报告 |
| `human_notes` | str | 人工复盘补充（可选） | 墨涵/Owner |

**failure_type 枚举定义**：

| 枚举值 | 含义 | 对应Q模块 | 典型特征 |
|:------:|:-----|:---------:|:---------|
| `STATISTICAL_NOISE` | 统计噪声（交易太少或信噪比过低） | Q1 (Existence) | 交易数<30，夏普低 |
| `REGIME_BOUNDED` | 仅在单一市场状态有效 | Q3 (Regime) | 某切片Sharpe<-0.5 |
| `PARAMETER_PEAK` | 参数尖峰（最优参数孤立） | Q2 (Robustness) | PlateauScore<0.3 |
| `CAPACITY_LIMITED` | 资金容量不足 | Q4 (Capacity) | 容量拐点<当前资金 |
| `TEMPORAL_DECAY` | 时间漂移（前期赚钱后期亏） | Q5 (Temporal) | RecentDegradation=true |
| `OOS_FAILED` | 样本外全面失效 | Q6 (OOS) | OOSScore<0.3 |
| `LOW_CONFIDENCE` | 综合置信度不足 | Q7 (Aggregator) | Rating D/E/F |
| `HUMAN_REJECTED` | 人工复审不通过 | G3 | 人工判定 |
| `UNKNOWN` | 未分类（待人工分析） | 兜底 | — |

#### Q9a-B: Q9a Q_FAILURES 存储方案

Q9a 使用固定数据库表 `q_failures`（与 `reliability_scores` 同库）：

```sql
CREATE TABLE q_failures (
    failure_id       TEXT PRIMARY KEY,
    strategy_id      TEXT NOT NULL,
    parameter_set    JSON,
    failure_type     TEXT NOT NULL,  -- enum值
    regime           TEXT,
    cause            TEXT,
    discovered_by    TEXT,           -- "Q1"|"Q2"|...|"G3"
    confidence_drop  REAL,
    timestamp        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    report_id        TEXT,
    human_notes      TEXT DEFAULT '',
    
    FOREIGN KEY (report_id) REFERENCES reliability_scores(report_id)
);

CREATE INDEX idx_failure_type ON q_failures(failure_type);
CREATE INDEX idx_strategy_id ON q_failures(strategy_id);
CREATE INDEX idx_regime ON q_failures(regime);
CREATE INDEX idx_timestamp ON q_failures(timestamp);
```

**Q9a 查询与分析能力**（主要用于治理审计）：

| 查询类型 | 示例 | 用途 |
|:---------|:-----|:-----|
| 按策略聚合 | `SELECT * FROM q_failures WHERE strategy_id='...' ORDER BY timestamp` | 查看某个策略的完整失败史 |
| 按失败类型统计 | `SELECT failure_type, COUNT(*) FROM q_failures GROUP BY failure_type` | 最常出现的失败模式TopN |
| 按市场状态聚合 | `SELECT regime, COUNT(*) FROM q_failures GROUP BY regime` | 哪些市场状态最容易导致失效 |
| 按时间趋势 | `SELECT DATE(timestamp), COUNT(*) FROM q_failures GROUP BY DATE` | 失败率是否在上升/下降 |
| 按发现者 | `SELECT * FROM q_failures WHERE discovered_by='Q3'` | 特定Validator发现了哪些问题 |

#### Q9a-C: Q9a 门控集成（G1/G2/G3→Q9a 自动写入）

所有 Gate 的"不通过"结果自动触发 Q9a 写入：

```
G1不通过 ──→ 写入 Q9a: failure_type="STATISTICAL_NOISE", discovered_by="Q1"
G2不通过 ──→ 写入 Q9a: failure_type="PARAMETER_PEAK", discovered_by="Q2"
G3不通过 ──→ 写入 Q9a: failure_type="HUMAN_REJECTED" 或对应类型, discovered_by="G3"
Q3异常  ──→ 写入 Q9a: failure_type="REGIME_BOUNDED", discovered_by="Q3"
...
```

---

#### Q9b: RESEARCH_FAILURES（全量研究失败积累层）

#### Q9b-A: Q9b RESEARCH_FAILURES 记录规范

Q9b 记录规范基于 Q9a 的全部字段，并额外增加扩展字段：

| 字段 | 类型 | 说明 |
|:-----|:----|:-----|
| 继承 Q9a 全部字段 | — | failure_id, strategy_id, parameter_set, failure_type, regime, cause, discovered_by, confidence_drop, timestamp, report_id, human_notes |
| `yield_reference` | str | (新增) 引用的研究产出ID |
| `external_source` | str | (新增) 外部来源（如文献引用、同行讨论） |
| `meta_tags` | JSON | (新增) 元研究标签（如 "recurring", "known_pattern"） |

**failure_type 枚举**同 Q9a（见 §Q9a-A），另增 2 个子类型：

| 枚举值 | 含义 | 典型场景 |
|:------:|:-----|:---------|
| `META_PATTERN` | 元分析发现的重复失败模式 | 跨策略复发检测 |
| `PILOT_REJECTED` | 试验性研究提前终止 | 研究者主动终止 |

#### Q9b-B: Q9b RESEARCH_FAILURES 存储方案

Q9b 使用独立目录 + 独立数据库表（与 Q9a 数据隔离）：

```text
research_failures/
├── index.json                  # 索引文件（策略→失败记录ID映射）
├── records/                    # 失败记录文件
│   ├── {failure_id}.json       # 单条记录
│   └── ...
├── aggregations/               # 预聚合统计（定期更新）
│   ├── by_strategy.json        # 按策略聚合
│   ├── by_failure_type.json    # 按失败类型聚合
│   └── by_regime.json          # 按市场状态聚合
└── query_log.md                # 查询日志（记录所有查询）
```

独立数据库表（与 Q9a 表结构不同，增加扩展字段）：

```sql
CREATE TABLE research_failures (
    failure_id       TEXT PRIMARY KEY,
    strategy_id      TEXT NOT NULL,
    parameter_set    JSON,
    failure_type     TEXT NOT NULL,
    regime           TEXT,
    cause            TEXT,
    discovered_by    TEXT,
    confidence_drop  REAL,
    timestamp        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    report_id        TEXT,
    human_notes      TEXT DEFAULT '',
    yield_reference  TEXT DEFAULT '',     -- Q9b 扩展
    external_source  TEXT DEFAULT '',     -- Q9b 扩展
    meta_tags        JSON DEFAULT '[]',  -- Q9b 扩展
    
    FOREIGN KEY (report_id) REFERENCES reliability_scores(report_id)
);
```

**Q9b 查询与分析能力**（主要用于元研究）：

| 查询类型 | 示例 | 用途 |
|:---------|:-----|:-----|
| 复发检测 | 相同 strategy_id + 相同 failure_type + 相隔 > 30 天 | 同一策略是否有复发失败 |
| 元分析聚合 | `SELECT meta_tags, COUNT(*) FROM research_failures GROUP BY meta_tags` | 失败模式标签分布 |
| 外部来源统计 | `SELECT external_source, COUNT(*) FROM research_failures GROUP BY external_source` | 失败来源分析 |
| 跨层引用 | `SELECT q9a.failure_type, q9b.failure_type FROM q_failures AS q9a JOIN research_failures AS q9b ON q9a.strategy_id = q9b.strategy_id` | Q9a ↔ Q9b 交叉对比 |

#### Q9b-C: Q9b 知识积累用途

Q9b RESEARCH_FAILURES 作为 KnowledgeBridge（知识桥）的镜像补充：

| KnowledgeBridge (成功) | RESEARCH_FAILURES (失败) |
|:-----------------------|:-------------------------|
| 记录"成功了什么" | 记录"为什么失败" |
| 供新策略参考"成功因子" | 供新策略检查"是否踩过同样坑" |
| 向下游传递最佳实践 | 向下游传递禁区清单 |
| 正向反馈循环 | 负向反馈循环 |

#### 双层交叉引用

Q9a 与 Q9b 通过 `(strategy_id, failure_id)` 关联，支持以下跨层操作：

| 操作 | 描述 |
|:-----|:-----|
| Q9a→Q9b | 从正式审计失败追溯至对应的研究扩展记录 |
| Q9b→Q9a | 从研究失败记录查看对应的正式审计判定 |
| 联合查询 | 同时从两个表获取同一策略的完整失败历史 |

实施工时已在 Phase 计划表（§2）中按 Q9a（Phase 0b, 1.6 天）+ Q9b（Phase 1~2, 0.5 天）分拆，此处不再重复。

### 3.4 双账本系统架构总览（更新版）

```
完整的量化研究平台架构 (Phase 4c + Layer Q):

       ┌──────────────────────────────────────────────────────────┐
       │            Layer Q (Transverse Governance Layer)         │
       │            ───── 可信度审计账本 ─────                     │
       │            回答: "为什么可信？"                          │
       │  Q1  Q2  Q3  Q4  Q5  Q6  Q7  Q8  Q9a Q9b               │
       │  Exist  Robust  Regime  Capac  Tempor  OOS  Aggreg  Fail │
       └────────────────────────┬─────────────────────────────────┘
                                │ 审计
        ┌───────────────────────┼─────────────────────────────┐
        │                       │                             │
        ▼                       ▼                             ▼
   ┌─────────┐           ┌──────────────┐           ┌──────────────┐
   │P Series  │           │ Six Layers   │           │ 回测管线      │
   │(工具集)   │ ←审计→    │ (报告结构)    │ ←审计→    │ (pipeline)   │
   │P1~P8     │           │ Layer 1~6    │           │ + Quality    │
   │          │           │              │           │   Gates      │
   └──────────┘           └──────────────┘           └──────────────┘
        │                       │                             │
        └───────────────────────┼─────────────────────────────┘
                                │ 产出
                                ▼
                    ┌───────────────────────┐
                    │  研究结果账本           │
                    │  回答: "赚了吗？"       │
                    │  - P系列分析结果        │
                    │  - 六层报告            │
                    │  - 参数排行榜          │
                    │  - KnowledgeBridge    │
                    └───────────────────────┘

    双账本体系:
    ┌──────────────────────────────────────────────────────────────────┐
    │ 账本A: 研究结果账本 (P/B/S/E/R/I)      账本B: 可信度审计账本 (Q) │
    │ ──────────────────────────              ──────────────────────── │
    │ 核心问题: "赚了吗？"                   核心问题: "为什么可信？"   │
    │ 输出: 收益指标、夏普、最大回撤、        输出: 存在性验证、参数地形、 │
    │       交易记录、参数排行榜、            市场适配、容量分析、       │
    │       归因分析、研究报告               时间稳定性、OOS验证、      │
    │                                       置信度评级、失败记录      │
    │ 用途: 决策参考                        用途: 决策约束             │
    │ 消费者: 策略研究者、交易员             消费者: 风控、知识审计      │
    └──────────────────────────────────────────────────────────────────┘
```

---

## 四、"双账本"操作规范

### 4.1 账本定义

| 账本 | 系统 | 角色 | 产出 | 核心问题 |
|:----:|:----:|:----:|:-----|:--------:|
| **账本A** | P/B/S/E/R/I | **Producer Layer（生产系统）** | 研究指标、报告、收益数据、参数排行榜 | **"赚了吗？"** |
| **账本B** | Layer Q | **Independent Validator Layer（独立审计系统）** | ExistenceResult、评分报告、审计意见 | **"为什么可信？"** |

### 4.2 核心原则

> **"研究者不能自己给自己盖章。"**

- 账本A的职责是**产生和展示**研究结果
- 账本B的职责是**审计和质疑**研究结果
- 两个账本由**不同的角色/系统**维护，职责边界严格分离
- 避免Self-confirming loop（自证循环）—— 防止"策略产生收益→策略解释收益→策略给自己评级"的闭环

### 4.3 账本A（研究结果账本）输出规范

#### A1: 适用范围
所有P系列分析工具（P1~P8）、六层报告（Layer 1~6）、KnowledgeBridge条目、参数排行榜

#### A2: 输出格式要求

每份产出必须包含以下标准字段：

```json
{
  "report_type": "P1|P3|P4|P6|Layer1~6|Knowledge",
  "strategy_id": "grid_601857",
  "date": "2026-05-19",
  "content": {
    // 各模块自有内容
  },
  "producer": "P-Series | Six-Layers | KB",
  "disclaimer": "本报告仅反映研究结果，不构成可信度保证。可信度评估请参考附带的Layer Q审计段。"
}
```

#### A3: 必须附带的声明
每份账本A报告末尾必须包含以下标准化声明段（与Q层审计段并列）：

```markdown
---
> **研究结果声明**: 以上为**研究结果账本（账本A）**的内容，回答"赚了吗？"。
> 可信度评估请参见随附的**Layer Q可信度审计段（账本B）**，回答"为什么可信？"。
> 两份账本独立出具，互不替代。
```

#### A4: 禁止行为
- ❌ 账本A产出中不得包含"可信/不可信"、"可靠/不可靠"等质量判定性表述
- ❌ 账本A不得自我评分、自我评级
- ❌ 账本A不得引用/引用账本B的评分作为自身内容的佐证
- ❌ 研究者不得修改账本A的输出来影响账本B的审计结果

### 4.4 账本B（可信度审计账本）输出规范

#### B1: 适用范围
所有Q层模块（Q1~Q8 + Q9a Q_FAILURES + Q9b RESEARCH_FAILURES）的输出、Quality Gate（G1/G2/G3）的判定

#### B2: 输出格式要求

每份产出必须包含以下标准字段：

```json
{
  "audit_type": "Existence|Robustness|Regime|Capacity|Temporal|OOS|Aggregated|Failure",
  "strategy_id": "grid_601857",
  "audit_date": "2026-05-19",
  "hard_gate_passed": true|false,
  "findings": [
    // 各模块审计发现
  ],
  "auditor": "Q1|Q2|...|Q9a|Q9b|G3-AuditorName",
  "disclaimer": "本审计仅评估研究可信度，不构成收益保证。可信与盈利之间存在固有差距。"
}
```

#### B3: 标准输出段

账本B的审计结果嵌入P报告末尾时，必须包含以下标准化段：

```markdown
---
## 可信度审计段（Layer Q — Transverse Governance Layer）

| 审计项 | 结果 | 评分 |
|:-------|:----:|:----:|
| Existence (存在性) | ✅ 通过 | 0.85 |
| Robustness (参数稳定性) | ⚠️ 警告 | 0.32 |
| Regime Consistency (市场适配) | 🔴 不通过 | 0.12 |
| Capacity (容量) | ✅ 通过 | 0.90 |
| Temporal (时间稳定性) | 🟡 边缘 | 0.45 |
| OOS Survival (样本外存活) | ✅ 通过 | 0.78 |

**复合R值**: 0.47 | **评级**: C（存在明显过拟合）
**瓶颈维度**: Regime Consistency + Robustness
**Auditor**: Layer Q ✅（独立审计，不参与研究过程）

---
> **审计声明**: 以上为**可信度审计账本（账本B）**的内容，回答"为什么可信？"。
> 本审计由Layer Q（Independent Validator Layer）独立完成，与P系列生产系统职责分离。
> 审计结果仅评估研究可信度，不构成收益保证。
```

#### B4: 禁止行为
- ❌ 账本B不得修改账本A的原始数据
- ❌ 账本B不得包含投资建议（买入/卖出/持仓建议）
- ❌ 账本B的评分不得用于排名/评比（这是账本A的"参数排行榜"的职责）
- ❌ 同一研究者不得同时参与同一策略的账本A生产和账本B审计

#### B4a: 小团队旅行条款

当团队规模 ≤ 3 人时，采用等效保证措施替代完全角色分离：

- T1: 接口隔离 — 账本A/B 通过标准化中间接口通信
- T2: 交叉审查 — 墨衡写的 Q 模块必须由墨萱审查通过
- T3: 盲测机制 — 每季度墨萱独立编写"副本审计"对比 Q 层结果
- T4: 审计日志透明 — 所有 Q 层判定记录代码作者和审查者
- T5: 签署责任声明 — 墨萱在审计报告末尾注明小团队依赖

> 当团队规模 > 5 人时，应回归 §B4 的完全分离原则。

### 4.5 两账本协同规则

| 场景 | 账本A行为 | 账本B行为 | 优先权 |
|:-----|:---------|:---------|:------:|
| 策略上线前 | 产出报告和参数推荐 | 执行审计，给出评级和瓶颈 | 账本B—不通过则不上线 |
| 策略运行中 | 持续产出绩效报告 | 定期审计（月度/季度） | 两者独立，账本B降级触发复审 |
| 策略下线 | 记录历史绩效 | 标记为失败记录（Q9a Q_FAILURES） | 账本B主导下线决策 |
| 跨策略比较 | 参数排行榜（按收益） | 可信度排名（按评级） | 两者独立，互不混淆 |

---

## 五、ExistenceValidator（Q1）MVP设计

### 5.1 检查项与阈值

参考专家建议，ExistenceValidator第一版包含6项检查：

| 序号 | 检查项 | 适配阈值 | 判定逻辑 | 备注 |
|:----:|:-------|:--------:|:---------|:-----|
| C1 | **最小交易数** | >= 30 | 回测全周期总交易笔数是否达到30 | 专家建议的硬阈值；不到30笔的交易在统计上无意义 |
| C2 | **多Regime覆盖** | >= 2 | 策略执行的交易是否分布在至少2种市场状态下 | 需要RegimeAnalyzer的切片支持；单一Regime策略标记为boundary case |
| C3 | **多年度覆盖** | >= 2年 | 回测时间跨度是否覆盖至少2个完整日历年度 | 确保牛市和震荡年份都有覆盖 |
| C4 | **非单段收益贡献** | 最大单交易收益占比 < 40% | 收益最集中的一笔交易占总收益比例不超过40% | 防止"一波流"——整个策略靠一波行情 |
| C5 | **信号密度** | 年均交易数 >= 12 (下限) | 平均每年交易数不低于12笔（即月均至少1笔） | 如果策略信号过于稀疏，即使交易数>30，可能仅集中在某一时间段 |
| C6 | **样本分布** | 交易不集中在一个窗口周期 | 检查交易在时间轴上的分布：最长无交易间隔是否超过总回测周期的30% | 防止"前2年不交易，后1年交易30笔"的分布偏斜 |

### 5.2 输出格式

严格遵循专家建议的`ExistenceResult`结构：

```python
@dataclass
class ExistenceResult:
    """策略存在性验证结果"""
    exists: bool               # True: 基础alpha存在; False: 统计上无意义
    confidence: float          # 置信度 [0.0, 1.0]
    fail_reasons: list[str]    # 不通过原因列表（为空表示全部通过）
```

**判定规则**：
- `exists = True` ⇔ 全部6项检查通过
- `confidence = min(pass_rate_weighted)` —— 基于每项检查的通过质量加权
- `fail_reasons` —— 列出所有不通过的检查项及具体数值

**置信度计算**：
```
C1通过 +0.30, 未通过则exists=False (硬门禁)
C2通过 +0.15, 部分覆盖(仅2种) +0.10, 未覆盖 +0.00
C3通过 +0.15, 仅1年 +0.05
C4通过 +0.15, 占比40-60% +0.08, 超过60%+0.00
C5通过 +0.15, 低于下限按比例衰减
C6通过 +0.10, 分布偏斜减半
```

权重分布：
| 检查项 | 基础权重 | 是否硬门禁 | 说明 |
|:------:|:--------:|:----------:|:-----|
| C1: 最小交易数 | 0.30 | ✅ 硬门禁 | 不到30笔直接不通过 |
| C2: 多Regime覆盖 | 0.15 | — | 覆盖2种即可，非硬门禁但权重较大 |
| C3: 多年度覆盖 | 0.15 | — | 至少2年覆盖 |
| C4: 非单段收益贡献 | 0.15 | — | 防范"一波流" |
| C5: 信号密度 | 0.15 | — | 年均交易数下限 |
| C6: 样本分布 | 0.10 | — | 防范时间偏斜 |

> 注：C1为硬门禁（Hard Gate）——如果最小交易数<30，`exists`直接判定为`False`且`confidence`为0.0。其他5项为软检查，综合决定置信度水平。

**关于 C1 与 601857 案例的说明**：

601857 网格（84天 / 2笔交易）无法通过 C1 硬门禁（≥30笔）。
此情况本身恰恰说明 C1 的价值——2 笔交易不足以构成 alpha 存在的证据。

该案例属于 Q 层上线前建立的历史研究，不受 ExistenceValidator 约束。
Q 层上线后，此类回测将在 Phase 0a 被自动拦截并记录至 Q9a Q_FAILURES，
不进入深度分析流程。

> 设计启示：C1 硬门禁不是为了"刁难"现有案例，而是防止"伪发现"污染后续分析。
  601857 当前无法通过 C1，正说明此案例需要更多工作才能证明统计可信度。
  这也是 Q9a Q_FAILURES 存在的意义——记录失败的案例，追踪其后续变化。

### 5.3 输入输出示例

```json
// 输入：策略回测结果（来自P系列报告）
{
  "strategy_id": "grid_601857",
  "total_trades": 43,
  "period_years": 3.2,
  "regimes_covered": ["OSCILLATION_LOWVOL", "OSCILLATION_HIGHVOL", "TREND_UP"],
  "max_single_trade_return_pct": 23.5,
  "trades_per_year": 13.4,
  "longest_no_trade_gap_months": 4,
  "total_period_months": 38
}

// 输出：ExistenceResult
{
  "exists": true,
  "confidence": 0.85,
  "fail_reasons": []
}
```

```json
// 反面示例：2笔交易的"伪发现"
{
  "strategy_id": "fake_strategy_x",
  "total_trades": 2,
  "period_years": 1.0,
  "regimes_covered": ["TREND_UP"],
  "max_single_trade_return_pct": 95.0,
  "trades_per_year": 2.0,
  "longest_no_trade_gap_months": 11,
  "total_period_months": 12
}

// 输出：ExistenceResult
{
  "exists": false,
  "confidence": 0.0,
  "fail_reasons": [
    "C1_FAILED: total_trades=2, threshold=30",
    "C2_FAILED: regimes_covered=1, threshold=2",
    "C3_FAILED: period_years=1.0, threshold=2.0",
    "C4_FAILED: max_single_trade_ratio=0.95, threshold=0.40",
    "C5_FAILED: trades_per_year=2.0, threshold=12",
    "C6_FAILED: longest_gap_ratio=0.92, threshold=0.30"
  ]
}
```

### 5.4 门禁行为

```
ExistenceValidator执行
        │
        ▼
  ┌──────────────┐
  │ exists=True? │──No──→ ① 写入FAILED状态
  └──────┬───────┘       ② 标注"统计无效"
         │ Yes           ③ 写入Q9a Q_FAILURES
         ▼               ④ 不允许进入参数扫描
   继续推进               ⑤ 返回 ExistenceResult
   (进入Q2++)
```

### 5.5 依赖

| 依赖项 | 已有/新建 | 状态 |
|:-------|:---------:|:----:|
| 回测引擎 | 已有 | ✅ |
| RegimeAnalyzer | 已有 | ✅ 用于C2检查 |
| P系列报告输出（逐笔交易明细） | 已有 | ✅ 用于C4/C5/C6 |
| 固定粗参数配置 | 已有 | ✅ 用于初始回测 |

### 5.6 实施工时

| 子任务 | 工时 | 说明 |
|:-------|:----:|:------|
| 6项检查逻辑实现 | 0.3天 | 核心判定逻辑 |
| confidence计算（加权） | 0.1天 | 置信度计算 |
| ExistenceResult数据结构 | 0.1天 | Dataclass + JSON序列化 |
| G1 Gate集成 | 0.1天 | 门禁行为 |
| 测试（3个通过+3个不通过案例） | 0.2天 | 含边界测试 |
| **合计** | **0.8天** | |

> **与v2.0对比**: 工时从0.5天增加到0.8天，因检查项从2项扩展到6项，新增置信度计算和更复杂的门禁行为。

---

## 六、完整工时估算（v2）

### 6.1 各模块工时总表

| 编号 | 模块 | 责任人 | 工时（天） | 新增/修改 | 对v2.0的变更 |
|:----:|:-----|:------:|:----------:|:---------:|:-------------|
| 0a-1 | Q1: ExistenceValidator | 墨衡 | 0.8 | **修改（扩展）** | 检查项2→6，+0.3天 |
| 0a-2 | G1 Gate集成 | 墨衡 | 0.2 | 维持 | 不变 |
| 0a-3 | 601857验证案例 | 墨衡 | 0.1 | 维持 | 不变 |
| **0a合计** | | **墨衡** | **1.1** | | **+0.3天** |
| 0b-1 | research_failures目录+DB | 墨萱 | 0.5 | **新增** | +0.5天 |
| 0b-2 | Q9a Q_FAILURES模块 | 墨衡 | 0.5 | **新增** | +0.5天 |
| 0b-3 | Gate→Q9a自动写入集成 | 墨衡 | 0.3 | **新增** | +0.3天 |
| 0b-4 | Failure Registry查询工具 | 墨萱 | 0.3 | **新增** | +0.3天 |
| **0b合计** | | **墨衡+墨萱** | **1.6** | **新增模块** | **+1.6天** |
| 1.1 | Q3: Regime Validator | 墨衡 | 1.0 | 维持 | 不变 |
| 1.2 | Q5: Temporal Stability | 墨萱 | 0.5 | 维持 | 不变 |
| 1.3 | Q8: Failure Attribution | 墨衡 | 0.5 | 维持 | 不变 |
| 1.4 | G1+G2门控完善(含Q9a写入) | 墨衡 | 0.5 | **修改** | +0.2天(Gate+Q9a) |
| 1.5 | G3 Multi-Sign Gate | 墨萱 | 1.0 | 维持 | 不变 |
| 1.6 | 全流程集成测试 | 墨衡+墨萱 | 1.5 | 维持 | 不变 |
| 1.7 | Q层文档 | 墨衡 | 0.5 | **修改** | +0.1天(含双账本规范) |
| **1合计** | | | **5.5** | | **+0.3天** |
| 2.1 | Q4: Capacity Validator | 墨萱 | 1.0 | 维持 | 不变 |
| 2.2 | 评分阈值校准(含FR数据) | 墨衡 | 1.5 | **修改** | +0.5天(含FR分析) |
| 2.3 | 跨报告比较+FR趋势分析 | 墨衡 | 1.5 | **修改** | +0.5天(含FR趋势) |
| 2.4 | Q层成果文档+FR指南 | 墨涵 | 0.5 | **修改** | +0.2天(含FR使用) |
| 2.5 | Phase 4c集成接口 | 墨衡+墨萱 | 1.0 | 维持 | 不变 |
| **2合计** | | | **5.5** | | **+1.2天** |

### 6.2 按角色汇总

| 角色 | Phase 0a | Phase 0b | Phase 1 | Phase 2 | **合计** |
|:----:|:--------:|:--------:|:-------:|:-------:|:--------:|
| **墨衡** | 1.1 | 0.8 | 2.5 | 3.0 | **7.4天** |
| **墨萱** | — | 0.8 | 1.5 | 2.5 | **4.8天** |
| **墨涵** | — | — | 0 | 0.5 | **0.5天** |
| **小计** | **1.1** | **1.6** | **4.0** | **6.0** | **12.7天** |

### 6.3 与v2.0对比

| 维度 | v2.0 | v3.0 | 变化 |
|:-----|:----:|:----:|:----:|
| 模块总数 | 8 (Q1~Q8) | 10 (Q1~Q8 + Q9a + Q9b) | +2 |
| 总工时（人天） | ~14.0 | ~15.6 | +1.6 |
| 里程碑 | 3 (M1/M2/M3) | 4 (M0/M0.5/M1/M2) | +1 |
| 检查项（Q1） | 2项 | 6项 | +4 |
| 代码库 | Q1~Q8 | Q1~Q8 + Q9a(Q_FAILURES) + Q9b(RESEARCH_FAILURES) | +Q9a+Q9b |
| DB表 | reliability_scores | + q_failures (Q9a) + research_failures (Q9b) | +2表 |
| 架构债务 | ADR-003 (未确认) | ADR-003 (专家确认) | 更稳固 |
| 架构术语 | "横向跨层审计层" | "Transverse Governance Layer" | 术语统一 |
| 运作原则 | 未明确定义 | "双账本系统" | 新增 |

### 6.4 阶段时间线

```
Day 1:     [Phase 0a] Q1 ExistenceValidator MVP (墨衡0.8天)
                                    G1 Gate集成 (墨衡0.2天)
                                    → 里程碑M0: "门禁就绪"
                                    [Phase 0b启动] FR目录+DB (墨萱0.5天)
Day 1-2:   [Phase 0b] Q9a Q_FAILURES模块 (墨衡0.5天) 
                                    Gate集成 (墨衡0.3天)
                                    查询工具 (墨萱0.3天)
                                    → 里程碑M0.5: "失败数据库就绪"
Day 3-8:   [Phase 1] Q3+Q5+Q8+G3+测试+文档
                                    → 里程碑M1: "验证门控闭环"
Day 9-15:  [Phase 2] Q4+校准+跨报告+Phase 4c集成
                                    → 里程碑M2: "完整Q层交付"
                                    
总工期: ~15个工作日（~3周）
v2.0基线: ~14个工作日
v3.0增加: ~1天（源自Failure Registry基础设施）
```

---

## 七、专家第三轮吸收对照表

### 7.1 吸收前后对比

| 专家建议 | v2.0状态 | v3.0变更 | 体现在文档章节 |
|:---------|:---------|:---------|:--------------|
| 1. Transverse Governance Layer术语 | "横向跨层审计层" → "横向治理层" | 统一术语 | §1.1, §3, §4 |
| 2. 双账本系统 | 未明确定义 | 新增§4 | §4: "双账本操作规范" |
| 3. ExistenceValidator 6项阈值 | 2项检查（夏普>0.3+交易数>20） | 6项专家阈值 | §5: "ExistenceValidator MVP设计" |
| 4. ADR-003确认 | 已决议，缺专家确认 | 补充专家确认注释 | §1.1(4) |
| 5. Failure Registry | 不存在 | 新增Q9a+Q9b双层Failure Registry | §3.3: "Q9: Failure Registry(Q9a+Q9b)" + §2.3 Phase 0b |
| 6. 战略方向确认 | "建设研究可信度基础设施" | 升级为"研究可信度第一目标" | §1.1(6) |

### 7.2 正式采纳声明

```
专家第三轮意见采纳声明
══════════════════════════════════
日期: 2026-05-19
版本: unified_reform_plan_v3_20260519.md (v3.0)

本文件已全面吸收专家第三轮意见（来源: 2605191505重构整个网格研究流程2.txt）。

采纳比例: 6条/6条 = 100%
变更范围: 中等（术语统一 + 新增Q9a+Q9b双层Failure Registry + 扩展Q1 + 新增双账本规范）
工时影响: +1.6天（v2.0基线14.0天 → v3.0最终15.6天）

架构基座已稳定。从"讨论功能"升级为"研究治理架构（Research Governance Architecture）"。
```

---

## 八、附录

### 8.1 关键架构决策记录（ADR，更新版）

| ADR编号 | 标题 | 决策 | 日期 | 状态 |
|:-------:|:-----|:-----|:----:|:----:|
| ADR-001 | Layer Q定位 | Transverse Governance Layer（横向治理层），不嵌入Layer 6 | 2026-05-19 | ✅ 专家确认 |
| ADR-002 | ExistenceValidator优先级 | Phase 0a（Day 1），硬门禁6项检查 | 2026-05-19 | ✅ 专家确认 |
| ADR-003 | MarketStateFilter矛盾 | 记录为Architectural Debt，Phase 3策略路由器解决 | 2026-05-19 | ✅ 专家确认 |
| ADR-004 | 不修改P系列 | Layer Q不做P系列计算逻辑变更，仅在其上构建分析层 | 2026-05-15 | ✅ 维持 |
| ADR-005 | 改造作为Phase 4c配套 | 命名Phase 4c.5，同一时间线 | 2026-05-15 | ✅ 维持 |
| **ADR-006** | **双账本系统** | P层=研究结果账本（"赚了吗？"），Q层=可信度审计账本（"为什么可信？"） | 2026-05-19 | ✅ 新建 |
| **ADR-007** | **Failure Registry（Q9a + Q9b 双层）** | 系统级失败数据库，与KnowledgeBridge并列；Q9a门控自动记录 + Q9b研究积累 | 2026-05-19 | ✅ 新建 |

### 8.2 架构债务清单（更新版）

| 编号 | 描述 | 发现日期 | 计划解决 | 备注 |
|:----:|:-----|:--------:|:--------:|:-----|
| AD-001 | MarketStateFilter策略无关路由（TREND_UP开网格的理论矛盾） | 2026-05-19 | Phase 3 | 专家确认此矛盾的必然性 |
| AD-002 | P系列报告版本分歧（Layer Q读取时的基线锁定） | 2026-05-19 | Phase 0前 | 必须先锁定评分数据源版本 |
| AD-003 | 阈值校准依赖历史数据量（432组可能不足） | 2026-05-19 | 持续累积 | 每季度重新校准 |

### 8.3 参考文档

| 文档 | 日期 | 作者 |
|:-----|:----|:------|
| 专家第一版提案（2605191428重构整个网格研究流程.txt） | 2026-05-19 | 外部专家 |
| 专家第二版评估（2605191451重构整个网格研究流程1.txt） | 2026-05-19 | 外部专家 |
| **专家第三版确认（2605191505重构整个网格研究流程2.txt）** | **2026-05-19** | **外部专家** |
| 墨衡评估方案（backtest_system_reform_20260519.md） | 2026-05-19 | 墨衡 |
| 统一方案v2（unified_reform_plan_20260519.md） | 2026-05-19 | 墨衡+墨涵 |
| **本文（unified_reform_plan_v3_20260519.md）** | **2026-05-19** | **墨衡（吸收专家第三轮）** |

---

*本文由墨枢系统（墨衡 v7.2）生成，吸收专家第三轮全部6条建议*
*版本: v3.0 | 状态: EXPERT_THIRD_ROUND_ABSORBED*
*基础: v2.0（墨衡×墨涵共识） + 专家第三轮6/6完全采纳*
*下一阶段: 等待Owner确认后进入Phase 0a实施*
